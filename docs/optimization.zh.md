# 优化：让代码跑得更快

优化是编译器最复杂的部分之一。各项目在这个维度上差异巨大——从 TCC 的零优化到 GCC 的数百个 pass。

## 优化的层次

### 前端优化（语言感知）

这些优化利用 C/C++ 的语言语义，在 IR 层次之上进行：

| 优化 | 说明 | 谁在做 |
|------|------|--------|
| 常量折叠 | `3 + 4` → `7` | 全部 |
| 类型收缩 | 将不必要的 `int` → `short` | GCC, Clang, CCC (narrow pass) |
| NRVO | 返回值优化，消除临时对象拷贝 | Clang, GCC |
| 虚函数去虚拟化 | `obj->vf()` → 直接调用 | Clang (需 LTO) |

### IR 优化（架构无关）

这是优化的主战场。所有支持 IR 的项目都在这里发力。

#### 死代码消除 (DCE — Dead Code Elimination)

移除永远不会执行到的代码。

```c
// 优化前
int x = 42;
return 0;
// 优化后
return 0;  // x 的赋值被消除
```

#### 常量折叠与传播 (Constant Folding & Propagation)

```c
int x = 3;
int y = x + 4;    // y = 7（传播 x=3，折叠 3+4）
int z = y * 2;    // z = 14（传播 y=7，折叠 7*2）
```

#### 公共子表达式消除 (CSE / GVN)

```c
// 优化前
int a = b + c;
int d = b + c;    // b + c 重复计算
// 优化后
int a = b + c;
int d = a;        // 复用 a
```

GVN (Global Value Numbering) 是 CSE 的更强版本，给每个计算分配一个"值编号"，相同编号的结果可以复用。

#### 内联 (Inlining)

```c
// 优化前
static int add(int a, int b) { return a + b; }
int x = add(3, 4);   // 调用 add
// 优化后
int x = 3 + 4;       // 函数体直接插入，调用开销消失
```

#### 循环不变量外提 (LICM — Loop Invariant Code Motion)

```c
// 优化前
for (int i = 0; i < n; i++) {
    x = a * b;       // a*b 不依赖循环变量，每次迭代都重新计算
    arr[i] = x + i;
}
// 优化后
x = a * b;           // 提到循环外，只算一次
for (int i = 0; i < n; i++) {
    arr[i] = x + i;
}
```

#### 强度削减 (Strength Reduction)

用更廉价的操作替代昂贵的操作：

```c
x * 2  → x << 1       // 乘法 → 移位
x / 8  → x >> 3       // 除法 → 移位（仅无符号）
x * 7  → (x << 3) - x // 乘法 → 移位 + 减法
```

## 五大项目的优化阵容

### GCC — 300+ 优化 Pass

GCC 有最庞大的优化体系，在 GIMPLE (SSA) 上运行 ~250 passes，在 RTL 上运行 ~50 passes。

关键 pass 组：
```
IPA (过程间分析)
├── inline (内联决策)
├── pure-const (纯函数/常量函数分析)
└── cp (常量传播到调用参数)

GIMPLE (SSA)
├── ccp (条件常量传播)
├── dce (死代码消除)
├── dom (支配优化: 跳转线程 + 冗余消除 + const传播 三位一体)
├── gvn (全局值编号)
├── lim (循环不变量外提)
├── ivopts (归纳变量优化)
├── sra (标量替换聚合体: 将 struct 成员拆为标量)
└── ... 200+ 更多

RTL
├── combine (指令合并: 多指令 → 一条)
├── cse (公共子表达式消除)
├── fwprop (前向传播: reg → 立即数)
├── sched (指令调度)
└── peephole2 (窥孔优化)
```

### Clang/LLVM — 模块化 Pass 管线

LLVM 的优化 pass 被组织成 PassManager 管线：

```
-O0: 无优化（但 mem2reg 总是运行以保证 IR 合法）
-O1: ~50 passes（轻量优化，平衡编译时间）
-O2: ~150 passes（标准优化）
-O3: ~170 passes（激进优化：更多内联 + 向量化 + 循环展开）
-Os: ~140 passes（偏向代码大小）
-Oz: ~150 passes（最小化代码大小）
```

核心 pass：
```
InstCombine (指令合并/简化) — 运行 4-6 次
GVN (全局值编号)
LICM (循环不变量外提)
Inline (自底向上内联，基于代价模型)
SLP Vectorizer (超字级并行向量化)
Loop Vectorizer (循环向量化)
SimplifyCFG (控制流图简化)
Jump Threading (跳转穿线)
Correlated Value Propagation
```

### CCC — 15 Passes 的精简设计

CCC 没有 LLVM/GCC 那样的 200+ passes，它的 15 个 pass 覆盖面足以编译真实的大型 C 项目（PostgreSQL, FFmpeg, Linux kernel）：

```
Phase 0: Inline 阶段
  ┌──────────────────────────────────────────────┐
  │ inline → mem2reg → constant_fold → copy_prop │
  │   → simplify → constant_fold → copy_prop     │
  │   → resolve_asm                              │
  └──────────────────────────────────────────────┘

Main Loop (dirty-tracked, 最多 3 轮):
  ┌──────────────────────────────────────────────┐
  │ cfg_simplify → copy_prop → div_by_const      │
  │   → narrow → simplify → constant_fold        │
  │   → gvn → licm → iv_strength_reduce          │
  │   → if_convert → copy_prop → dce             │
  │   → cfg_simplify → ipcp                      │
  └──────────────────────────────────────────────┘

Cleanup:
  ┌──────────────────────────────────────────────┐
  │ dead_statics → phi elimination               │
  └──────────────────────────────────────────────┘
```

**脏追踪 (Dirty Tracking)**：每个 pass 返回是否做了实际修改。如果某个 pass 未做修改，管线可以跳过后续 pass。这让 15 个 pass 在大部分代码上只需 1-2 轮。

### TCC — 局部窥孔

TCC 不在 IR 层面做优化（没有 IR），仅在代码生成时做局部窥孔：

```c
// 编译器不负责管跨语句的优化，但同一表达式内：
int x = 3 + 4 * 5;  // → 直接生成 23
int y = a * 8;      // → sal eax, 3   (用移位替代乘法)
int z = a / 2;      // → sar eax, 1   (仅正数)
```

### XCC — 委托 LLVM

XCC 不实现任何优化 pass。所有优化由 LLVM 工具链 (`llc`) 内置的 pass 管线完成。XCC 生成的 LLVM IR 就是 LLVM 优化的输入。

```
XCC 生成 → LLVM IR → llc (O0/O1/O2/O3) → 机器码
```

---

## 优化传递的关键技巧

### 1. Pass Ordering（Pass 顺序）

优化不是随意堆砌——顺序至关重要。

```
反例：DCE 在 inline 之前 → 内联后的死代码要等下一轮 DCE
正例：
  inline → mem2reg → DCE → GVN
  （内联暴露更多上下文，mem2reg 让它成为 SSA，
   DCE 消除内联冗余，GVN 在完整信息上做等值分析）
```

CCC 的 pass 顺序非常讲究，inline 后立即做 mem2reg + constant_fold + copy_prop，利用内联暴露的信息。

### 2. Fixpoint Iteration（不动点迭代）

某个优化可能为另一个优化创造机会。经典做法是**迭代到不动点**：

```
while changed:
    run_all_passes()
```

LLVM 采取的策略是：核心 pass (InstCombine) 运行 4-6 次，散布在管线中，而不是无限制迭代。

CCC 采用**有界迭代**（最多 3 轮）加**脏追踪**，平衡效果和编译时间。

### 3. 代价模型 (Cost Model)

内联和循环展开不能无脑做——代码膨胀会降低 I-cache 命中率。

LLVM 内联的代价模型考虑：
- 被调用函数的大小（按 IR 指令数）
- 调用参数的常量性（如果参数是常量，内联收益更大）
- 调用次数（热点才值得内联）
- 当前函数的大小（防止主函数膨胀过大）

---

## Pass 类型总结

| Pass 类型 | 作用 | 例 |
|-----------|------|-----|
| 分析 (Analysis) | 不修改 IR，产生分析结果 | 别名分析、支配树、循环检测 |
| 变换 (Transform) | 修改 IR | 内联、DCE、LICM |
| 规范化 (Canonicalize) | 将 IR 化为标准形式，方便后续 pass | mem2reg（alloca→SSA）、SimplifyCFG |

---

下一站：[后端与代码生成](backend.md) — 无论 IR 怎么优化，最终还是要生成 CPU 能执行的机器码。
