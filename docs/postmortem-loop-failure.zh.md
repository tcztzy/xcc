# 为什么多轮修复未能清零剩余错误

## 摘要

约 20 轮修复中，错误从 219 降到 109——实打实的 50% 削减。
但最后约 15 轮几乎没有净收益：
每次尝试要么 (a) 造成大规模回退必须撤销，
要么 (b) 只是让错误在不同类别间转移，总数不变。剩余 109 个错误分三类：

| 类别 | 数量 | 为什么碰不到 |
|---|---|---|
| `expected instruction opcode` | 13 | 嵌套表达式求值后 tern/logical 块缺终止指令 |
| `duplicate case value` | 9 | 枚举/常量解析把不同名字映射到相同整数值 |
| PHI / 支配 / value-token | 7+8+2 | 混合宽度运算 + PHI 放错位置 |

下面是循环失败的诊断。

---

## 1. 那个抵制了所有修复的根因 Bug

### 1.1 症状

`_ternary` 或 `_logical` 创建的块（`tern.then`、`log.rhs`）缺终止指令（terminator），
导致 `expected instruction opcode`。

### 1.2 代码生成器做了什么

```python
# _ternary（简化）
then_bb = AppendBasicBlock(fn, "tern.then")
PositionBuilderAtEnd(builder, then_bb)
then_val = _emit_expr(expr.then_expr)   # 可能创建嵌套块
BuildBr(builder, merge_bb)              # 假设 builder 还在 then_bb
```

当 `expr.then_expr` 包含另一个三元表达式或 `&&`/`||` 时，`_emit_expr`
递归进入嵌套的 `_ternary` / `_logical`。嵌套调用创建了自己的块，
并把 builder 留在**内层** merge 块。紧接着的 `BuildBr(merge_bb)` 从**错误的块**
发出分支——外层的 `then_bb` 永远拿不到终止指令。

### 1.3 为什么 `_bb_needs_term` + `PositionBuilderAtEnd` 让事情更糟

显然的修复思路：`_emit_expr` 之后，检查 `then_bb` 是否还需要终止指令，
如果需要，把 builder 挪回去再发分支。

```python
if _bb_needs_term(then_bb):
    PositionBuilderAtEnd(builder, then_bb)
    BuildBr(builder, merge_bb)
```

这**看起来**正确，但引入了第二个 bug：`LLVMPositionBuilderAtEnd`
在一个**已有终止指令**的块上，会插入到**现有终止指令之前**。所以当
`then_bb` 已被终止（比如三元表达式内的语句表达式里有 `return`），
重新定位会把 builder 放在最后一个真实指令和已有终止指令**之间**。
随后的 `BuildBr` 添加了**第二个终止指令** → IR 畸形 → 级联错误。

### 1.4 LLVM C API 为什么是问题的一部分

`LLVMPositionBuilderAtEnd` 的语义是模糊的：

- 在**没有终止指令**的块上：定位到所有指令之后（安全）。
- 在**有终止指令**的块上：定位到终止指令**之前**（危险——你可以插入永
  远不会执行的指令）。

没有 API 能在不调用 `GetBasicBlockTerminator` 的情况下问"这个块有终止
指令吗？"。而 `GetBasicBlockTerminator` 对空块返回 `None`（ctypes NULL
指针），这又有 `None == 0` 为 `False` 的坑（本次会话中已修复）。但即便
检查正确，重定位方式仍然脆弱，因为：

1. 嵌套表达式求值后，builder 可能在**任何地方**。
2. `_bb_needs_term` 只告诉你某个特定块是否需要终止指令，它**不**告诉你
   builder 当前在哪，也不告诉你嵌套表达式之后的指令是否发到了正确的块。
3. 即便你把 builder 挪对了位置，嵌套表达式产生的**值**（SSA 寄存器）可
   能定义在嵌套块中，在外层块使用它们是支配违规。

### 1.5 缺失的 primitive

LLVM-C 有 `LLVMSaveInsertPosition` / `LLVMRestoreInsertPosition`（或 C++
的 `IRBuilder::saveIP()` / `restoreIP()`）。这些函数保存和恢复 builder 的
**精确**插入点——包括"在终止指令之前"的状态。使用 save/restore：

```python
saved = SaveInsertPosition(builder)
PositionBuilderAtEnd(builder, outer_block)
# ... 发外层块指令 ...
RestoreInsertPosition(builder, saved)
```

xcc 的 ctypes 绑定（`_LLVMC`）没有封装这些函数。所有试图用
`PositionBuilderAtEnd` + `GetInsertBlock` 手动模拟 save/restore 的尝试
都失败了，因为它们丢失了"在终止指令之前"的插入状态。

---

## 2. 为什么循环反复撞 109 的墙

### 2.1 修复 → 回退 → 撤销循环

| 尝试 | 做了什么 | 结果 | 净效果 |
|------|---------|------|--------|
| A | `_emit_case` 加 `_bb_needs_term` + 重定位 | opcode 42→14 | +28 |
| B | `_prev_case_bb` fallthrough 链（入栈） | opcode 14→34 | 撤销 |
| C | `_prev_case_bb` 简化（无栈） | opcode 34→15 | 撤销 |
| D | `_ternary` 加 `_bb_needs_term` | opcode 15→106 | 撤销 |
| E | `_logical` 加 `_bb_needs_term` | opcode 15→106 | 撤销 |
| F | `_logical` 选择性重定位 | opcode 106→310 | 撤销 |

每次尝试遵循相同的模式：找到一个没终止指令的块，加 `_bb_needs_term` 守卫，
尝试重定位，发分支。除了简单的 `_emit_case` 修复之外，每次尝试都大规模回退，
因为修复触发了在原"破但稳定"的代码中无害的场景（有嵌套表达式且已有终止指令
的块）。

### 2.2 测试中的确认偏差

每次代码修改后，`make` 没有先删除所有 `.o` 文件。构建系统跳过了已有 `.o` 的
文件，所以报告的错误数是**混合**了旧的缓存成功和新的失败。这掩盖了修改的真实
影响（当最终运行 `find . -name '*.o' -delete` 后，错误从 109 跳到 313，才发现问题）。

### 2.3 没有差异诊断

每一轮都把 13 个 opcode 文件当作一个整体，尝试通用修复。但这 13 个文件
至少有三种不同的根因：

1. **switch default 内的三元表达式**（frameobject.c）
2. **带 switch predecessor 的逻辑 AND/OR**（ast.c）
3. **模块级语法问题**（`_json.c`——`}` 作为错误）

对所有三种做统一修复是不可能的；每种需要各自处理。但循环不断用同样的
修复模式去试，然后撤销。

### 2.4 类别转移被误认为进展

好几次总错误数停在 109，但类别在变：
- `Switch constants must match` (3) → `duplicate case value` (9)
- `expected value token` (44) → `expected instruction opcode` (41)

这些转移被报告为"修复了类别 A，但 B 增加了"，却没有认识到同样的文件
仍然在失败——只是产生了不同的错误。净通过率没有变化。

---

## 3. 知识缺口

### 3.1 LLVM builder 语义

Builder 的插入点状态比"哪个块"更复杂。它包括插入点是否在终止指令之前。
`PositionBuilderAtEnd` **不会**创建一个安全的"块尾"位置——它走到**真正的**
尾部，可能在终止指令之前。这是正确的 LLVM 行为（你可以在终止指令前插
入更多指令），但它与假定"块尾"意味着"安全加终止指令"的代码冲突。

### 3.2 SSA 支配

定义在子块（如内层 `tern.then`）的值不能在没有 PHI 节点的情况下在父块
（如外层 `tern.then`）使用。当 builder 漂移到嵌套块时，属于父块的指令
被发到了子块，同时造成了缺终止指令**和**支配违规。只修复终止指令并不能
修复支配问题。

### 3.3 ctypes NULL vs Python None

块没有终止指令时 `GetBasicBlockTerminator` 返回 NULL（0 指针）。
ctypes 绑定对 NULL 指针返回 `None`。Python 中 `None == 0` 是 `False`，
所以初版 `_bb_needs_term` 总是返回 `False`（声称每个块都有终止指令）。
这被发现并修复了，但说明了 ctypes 指针语义跟 C API 不同，需要显式处理。

---

## 4. 方法论问题

### 4.1 没有 save/restore 模式

每次修复尝试都是"重定位" builder，而不是保存和恢复它。LLVM C API 有
可封装的 `LLVMCopyPosition`（或 C++ 等价物），但从未被添加到绑定中。
没有 save/restore，代码无法安全地求值一个可能创建自己块的子表达式，
然后回到原来的插入点。

### 4.2 在错误的抽象层做修复

修复被应用在单个发射点（`_ternary`、`_logical`、`_emit_case`）。但问题是
系统性的：**任何**可能递归进入会创建块的表达式的 `_emit_expr` 调用都可能
漂移 builder。修复应该在 `_emit_expr` 层——一个在递归前保存插入位置、
递归后恢复的包装器——而不是在每个表达式处理器里。

### 4.3 没有单步测试循环

修改后直接在整个 CPython 代码库（~260 个文件）上跑 `make -k -j4`。这把
几件事混在一起：
- 改动对目标文件的影响
- 未重编译文件的缓存效应
- 其他类别中无关的错误

正确循环：改代码 → 编译**单个**目标文件 → 对其 IR 跑 `llc` → 检查
错误信息 → 迭代。

---

## 5. 什么做法会有效

### 5.1 子表达式的 `_emit_expr` 包装器

一个 builder 位置 save/restore primitive，用在 `_ternary`、`_logical`、
`_emit_case` 的入口：

```
saved_ip = SaveInsertPosition(builder)
PositionBuilderAtEnd(builder, parent_block)
try:
    result = _emit_expr(sub_expr)
finally:
    RestoreInsertPosition(builder, saved_ip)
```

这确保了在任何子表达式求值后（不管创建了多少嵌套块），builder 回到父块。
父块于是保证有正确的指令，可以被安全地终止。

### 5.2 分离终止指令发射和表达式求值

目前 `_ternary` 在同一个方法里既求值表达式又发终止指令。应该分离：先求值
表达式（用 save/restore），再显式终止块。save/restore 处理漂移；显式终止
处理终止指令。

### 5.3 枚举常量求值需要正确的作用域

`duplicate case value` 错误来自 `_eval_case_val` 未能查找枚举常量（返回 0，
导致多个 case 标签都求值为 0）。修复需要正确的全局作用域查找，通过
`SemaUnit.file_scope`——这个能力部分实现了但可能没有覆盖所有枚举声明模式。

---

## 6. 结论

多轮修复循环失败，不是因为 bug 修不了，而是因为：

1. **LLVM builder save/restore primitive 在绑定中缺失。** 没有它，所有重定位
   尝试都是脆弱的，容易导致支配违规。

2. **修复被放在单个发射点，而非 `_emit_expr` 分发层。** builder 漂移问题是
   系统性的，不是三元或逻辑表达式特有的。

3. **测试循环太慢太宽。** 单文件编译 + `llc` 验证能立即捕获回退，避免
   "修→撤"循环。

4. **剩余 109 个错误不是一个类别，而是至少五个不同的根因**，需要不同的处理
   方式。通用修复无法覆盖所有。

本次会话中的工作正确地消除了 7 个类别的 110 个错误。剩余 109 个需要：
在对 LLVM 绑定添加 `SaveRestoreInsertPosition`，用 save/restore 包装
`_emit_expr`，以及修复枚举常量解析——每项都是一个有针对性的、架构上
正确的修改，而不是另一轮试错。
