import platform
from dataclasses import dataclass

from xcc.ast import (
    AlignofExpr,
    AssignExpr,
    BinaryExpr,
    BreakStmt,
    CallExpr,
    CastExpr,
    CharLiteral,
    CommaExpr,
    CompoundStmt,
    ConditionalExpr,
    ContinueStmt,
    DeclGroupStmt,
    DeclStmt,
    DoWhileStmt,
    Expr,
    ExprStmt,
    FloatLiteral,
    ForStmt,
    FunctionDef,
    Identifier,
    IfStmt,
    InitList,
    IntLiteral,
    NullStmt,
    ReturnStmt,
    SizeofExpr,
    StaticAssertDecl,
    Stmt,
    StringLiteral,
    TypedefDecl,
    TypeSpec,
    UnaryExpr,
    UpdateExpr,
    WhileStmt,
)
from xcc.diag import CodegenError, Diagnostic
from xcc.frontend import FrontendResult
from xcc.types import INT, LONG, VOID, Type

_CG_UNSUPPORTED = "XCC-CG-0001"
_CG_TOOLCHAIN = "XCC-CG-0002"
_CG_PLATFORM = "XCC-CG-0003"
_CG_DRIVER = "XCC-CG-0004"
_DARWIN_POINTER_SIZE = 8


def native_backend_available() -> bool:
    return platform.system() == "Darwin" and platform.machine() == "arm64"


def native_backend_error(
    filename: str,
    message: str,
    *,
    code: str = _CG_UNSUPPORTED,
) -> CodegenError:
    return CodegenError(Diagnostic("codegen", filename, message, code=code))


def generate_native_assembly(result: FrontendResult) -> str:
    if not native_backend_available():
        raise native_backend_error(
            result.filename,
            "Native backend is only available on macOS arm64",
            code=_CG_PLATFORM,
        )
    return _NativeCodeGenerator(result).generate()


@dataclass(frozen=True)
class _StackSlot:
    offset: int
    type_: Type


@dataclass(frozen=True)
class _FunctionLayout:
    param_slots: dict[str, _StackSlot]
    decl_slots: dict[int, _StackSlot]
    frame_size: int


@dataclass(frozen=True)
class _GlobalObject:
    name: str
    type_: Type
    initializer: Expr | None
    is_extern: bool


class _NativeCodeGenerator:
    def __init__(self, result: FrontendResult) -> None:
        self._result = result
        self._unit = result.unit
        self._type_map = result.sema.type_map
        self._lines: list[str] = []
        self._label_counter = 0
        self._string_labels: dict[str, str] = {}
        self._global_objects: dict[str, _GlobalObject] = {}
        self._function_names: set[str] = set()
        self._function_types: dict[str, Type] = {}
        self._current_layout: _FunctionLayout | None = None
        self._current_function: FunctionDef | None = None
        self._current_scopes: list[dict[str, _StackSlot]] = []
        self._loop_labels: list[tuple[str, str]] = []
        self._return_label = ""

    def generate(self) -> str:
        self._reject_asm_source()
        externals = self._unit.externals or [*self._unit.declarations, *self._unit.functions]
        for external in externals:
            self._collect_top_level(external)
        self._emit_globals()
        self._emit_text(externals)
        self._emit_strings()
        return "\n".join(self._lines) + "\n"

    def _reject_asm_source(self) -> None:
        source = self._result.source
        index = 0
        while index < len(source):
            ch = source[index]
            if ch == "/" and index + 1 < len(source) and source[index + 1] == "/":
                index += 2
                while index < len(source) and source[index] != "\n":
                    index += 1
                continue
            if ch == "/" and index + 1 < len(source) and source[index + 1] == "*":
                index += 2
                while index + 1 < len(source) and source[index : index + 2] != "*/":
                    index += 1
                index += 2
                continue
            if ch in {'"', "'"}:
                quote = ch
                index += 1
                while index < len(source):
                    if source[index] == "\\":
                        index += 2
                        continue
                    if source[index] == quote:
                        index += 1
                        break
                    index += 1
                continue
            if ch == "_" or ch.isalpha():
                start = index
                index += 1
                while index < len(source) and (source[index] == "_" or source[index].isalnum()):
                    index += 1
                if source[start:index] in {"asm", "__asm", "__asm__"}:
                    raise native_backend_error(
                        self._result.filename,
                        "GNU asm is not supported by the native backend",
                    )
                continue
            index += 1

    def _collect_top_level(self, external: FunctionDef | Stmt) -> None:
        if isinstance(external, FunctionDef):
            self._check_function_contract(external)
            self._function_names.add(external.name)
            self._function_types[external.name] = self._function_type(external)
            return
        if isinstance(external, DeclGroupStmt):
            for declaration in external.declarations:
                self._collect_top_level(declaration)
            return
        if isinstance(external, (TypedefDecl, StaticAssertDecl)):
            return
        if not isinstance(external, DeclStmt):
            raise native_backend_error(
                self._result.filename,
                f"Unsupported native codegen declaration: {type(external).__name__}",
            )
        if external.name is None:
            return
        if external.storage_class not in {None, "extern"} or external.is_thread_local:
            raise native_backend_error(
                self._result.filename,
                f"Unsupported native codegen storage for global '{external.name}'",
            )
        if isinstance(external.init, InitList):
            raise native_backend_error(
                self._result.filename,
                f"Aggregate initializer is not supported by the native backend: {external.name}",
            )
        global_type = self._resolve_object_type(external.type_spec, f"global '{external.name}'")
        self._global_objects[external.name] = _GlobalObject(
            external.name,
            global_type,
            external.init,
            external.storage_class == "extern",
        )

    def _emit_globals(self) -> None:
        emitted = False
        for global_object in self._global_objects.values():
            if global_object.is_extern:
                continue
            if not emitted:
                self._lines.extend((".data",))
                emitted = True
            align = 3 if self._storage_width(global_object.type_) == 8 else 2
            self._lines.extend(
                (
                    f".globl {self._symbol_name(global_object.name)}",
                    f".p2align {align}",
                    f"{self._symbol_name(global_object.name)}:",
                )
            )
            if global_object.initializer is None:
                self._lines.append(f".zero {self._storage_width(global_object.type_)}")
                continue
            value = self._eval_global_initializer(global_object.initializer, global_object.type_)
            directive = ".quad" if self._storage_width(global_object.type_) == 8 else ".long"
            self._lines.append(f"{directive} {value}")

    def _emit_text(self, externals: list[FunctionDef | Stmt]) -> None:
        self._lines.extend((".text",))
        for external in externals:
            if isinstance(external, FunctionDef) and external.body is not None:
                self._emit_function(external)

    def _emit_strings(self) -> None:
        if not self._string_labels:
            return
        self._lines.extend((".section __TEXT,__cstring,cstring_literals",))
        for literal, label in self._string_labels.items():
            self._lines.extend((f"{label}:", f".asciz {self._asm_string(literal)}"))

    def _emit_function(self, func: FunctionDef) -> None:
        assert func.body is not None
        layout = self._prepare_function_layout(func)
        self._current_layout = layout
        self._current_function = func
        self._current_scopes = [dict(layout.param_slots)]
        self._loop_labels = []
        self._return_label = self._new_label("return")
        symbol = self._symbol_name(func.name)
        self._lines.extend((f".globl {symbol}", ".p2align 2", f"{symbol}:"))
        self._lines.append("stp x29, x30, [sp, #-16]!")
        self._lines.append("mov x29, sp")
        if layout.frame_size:
            self._lines.append(f"sub sp, sp, #{layout.frame_size}")
        for index, param in enumerate(func.params):
            assert param.name is not None
            slot = layout.param_slots[param.name]
            self._store_local(slot, index)
        self._emit_stmt(func.body)
        self._lines.append(f"{self._return_label}:")
        if layout.frame_size:
            self._lines.append(f"add sp, sp, #{layout.frame_size}")
        self._lines.append("ldp x29, x30, [sp], #16")
        self._lines.append("ret")
        self._current_layout = None
        self._current_function = None
        self._current_scopes = []
        self._loop_labels = []
        self._return_label = ""

    def _prepare_function_layout(self, func: FunctionDef) -> _FunctionLayout:
        if len(func.params) > 8:
            raise native_backend_error(
                self._result.filename,
                f"Native backend supports at most 8 parameters: {func.name}",
            )
        next_offset = 0
        param_slots: dict[str, _StackSlot] = {}
        decl_slots: dict[int, _StackSlot] = {}
        for param in func.params:
            assert param.name is not None
            param_type = self._resolve_object_type(param.type_spec, f"parameter '{param.name}'")
            next_offset += 8
            param_slots[param.name] = _StackSlot(next_offset, param_type)
        assert func.body is not None
        for stmt in func.body.statements:
            next_offset = self._reserve_stmt_slots(stmt, decl_slots, next_offset)
        frame_size = ((next_offset + 15) // 16) * 16
        return _FunctionLayout(param_slots, decl_slots, frame_size)

    def _reserve_stmt_slots(
        self,
        stmt: Stmt,
        decl_slots: dict[int, _StackSlot],
        next_offset: int,
    ) -> int:
        if isinstance(stmt, DeclGroupStmt):
            for declaration in stmt.declarations:
                next_offset = self._reserve_stmt_slots(declaration, decl_slots, next_offset)
            return next_offset
        if isinstance(stmt, DeclStmt):
            if stmt.name is None:
                return next_offset
            if stmt.storage_class is not None or stmt.is_thread_local:
                raise native_backend_error(
                    self._result.filename,
                    f"Unsupported native codegen storage for local '{stmt.name}'",
                )
            local_type = self._resolve_object_type(stmt.type_spec, f"local '{stmt.name}'")
            next_offset += 8
            decl_slots[id(stmt)] = _StackSlot(next_offset, local_type)
            return next_offset
        if isinstance(stmt, CompoundStmt):
            for item in stmt.statements:
                next_offset = self._reserve_stmt_slots(item, decl_slots, next_offset)
            return next_offset
        if isinstance(stmt, IfStmt):
            next_offset = self._reserve_stmt_slots(stmt.then_body, decl_slots, next_offset)
            if stmt.else_body is not None:
                next_offset = self._reserve_stmt_slots(stmt.else_body, decl_slots, next_offset)
            return next_offset
        if isinstance(stmt, WhileStmt):
            return self._reserve_stmt_slots(stmt.body, decl_slots, next_offset)
        if isinstance(stmt, DoWhileStmt):
            return self._reserve_stmt_slots(stmt.body, decl_slots, next_offset)
        if isinstance(stmt, ForStmt):
            if isinstance(stmt.init, Stmt):
                next_offset = self._reserve_stmt_slots(stmt.init, decl_slots, next_offset)
            return self._reserve_stmt_slots(stmt.body, decl_slots, next_offset)
        if isinstance(
            stmt,
            (
                ExprStmt,
                ReturnStmt,
                NullStmt,
                StaticAssertDecl,
                TypedefDecl,
                BreakStmt,
                ContinueStmt,
            ),
        ):
            return next_offset
        raise native_backend_error(
            self._result.filename,
            f"Unsupported native codegen statement: {type(stmt).__name__}",
        )

    def _emit_stmt(self, stmt: Stmt) -> None:
        if isinstance(stmt, DeclGroupStmt):
            for declaration in stmt.declarations:
                self._emit_stmt(declaration)
            return
        if isinstance(stmt, DeclStmt):
            if stmt.name is None:
                return
            assert self._current_layout is not None
            slot = self._current_layout.decl_slots[id(stmt)]
            self._current_scopes[-1][stmt.name] = slot
            if stmt.init is not None:
                if isinstance(stmt.init, InitList):
                    raise native_backend_error(
                        self._result.filename,
                        "Aggregate initializer is not supported by the native backend: "
                        f"{stmt.name}",
                    )
                self._emit_expr(stmt.init)
                self._coerce_primary(self._expr_type(stmt.init), slot.type_)
                self._store_local(slot, 0)
            return
        if isinstance(stmt, (TypedefDecl, StaticAssertDecl, NullStmt)):
            return
        if isinstance(stmt, ExprStmt):
            self._emit_expr(stmt.expr)
            return
        if isinstance(stmt, ReturnStmt):
            if stmt.value is not None:
                assert self._current_function is not None
                return_type = self._resolve_return_type(self._current_function)
                self._emit_expr(stmt.value)
                self._coerce_primary(self._expr_type(stmt.value), return_type)
            self._lines.append(f"b {self._return_label}")
            return
        if isinstance(stmt, CompoundStmt):
            self._current_scopes.append({})
            try:
                for item in stmt.statements:
                    self._emit_stmt(item)
            finally:
                self._current_scopes.pop()
            return
        if isinstance(stmt, IfStmt):
            else_label = self._new_label("else")
            end_label = self._new_label("endif")
            self._emit_branch_if_zero(stmt.condition, else_label)
            self._emit_stmt(stmt.then_body)
            if stmt.else_body is None:
                self._lines.append(f"{else_label}:")
                return
            self._lines.append(f"b {end_label}")
            self._lines.append(f"{else_label}:")
            self._emit_stmt(stmt.else_body)
            self._lines.append(f"{end_label}:")
            return
        if isinstance(stmt, WhileStmt):
            cond_label = self._new_label("while_cond")
            end_label = self._new_label("while_end")
            self._loop_labels.append((cond_label, end_label))
            try:
                self._lines.append(f"{cond_label}:")
                self._emit_branch_if_zero(stmt.condition, end_label)
                self._emit_stmt(stmt.body)
                self._lines.append(f"b {cond_label}")
                self._lines.append(f"{end_label}:")
            finally:
                self._loop_labels.pop()
            return
        if isinstance(stmt, DoWhileStmt):
            body_label = self._new_label("do_body")
            cond_label = self._new_label("do_cond")
            end_label = self._new_label("do_end")
            self._loop_labels.append((cond_label, end_label))
            try:
                self._lines.append(f"{body_label}:")
                self._emit_stmt(stmt.body)
                self._lines.append(f"{cond_label}:")
                self._emit_expr(stmt.condition)
                if self._is_wide_type(self._expr_type(stmt.condition)):
                    self._lines.append("cbnz x0, " + body_label)
                else:
                    self._lines.append("cbnz w0, " + body_label)
                self._lines.append(f"{end_label}:")
            finally:
                self._loop_labels.pop()
            return
        if isinstance(stmt, ForStmt):
            self._current_scopes.append({})
            cond_label = self._new_label("for_cond")
            post_label = self._new_label("for_post")
            end_label = self._new_label("for_end")
            self._loop_labels.append((post_label, end_label))
            try:
                if isinstance(stmt.init, Stmt):
                    self._emit_stmt(stmt.init)
                elif stmt.init is not None:
                    self._emit_expr(stmt.init)
                self._lines.append(f"{cond_label}:")
                if stmt.condition is not None:
                    self._emit_branch_if_zero(stmt.condition, end_label)
                self._emit_stmt(stmt.body)
                self._lines.append(f"{post_label}:")
                if stmt.post is not None:
                    self._emit_expr(stmt.post)
                self._lines.append(f"b {cond_label}")
                self._lines.append(f"{end_label}:")
            finally:
                self._loop_labels.pop()
                self._current_scopes.pop()
            return
        if isinstance(stmt, BreakStmt):
            if not self._loop_labels:
                raise native_backend_error(self._result.filename, "break is not supported here")
            self._lines.append(f"b {self._loop_labels[-1][1]}")
            return
        if isinstance(stmt, ContinueStmt):
            if not self._loop_labels:
                raise native_backend_error(self._result.filename, "continue is not supported here")
            self._lines.append(f"b {self._loop_labels[-1][0]}")
            return
        raise native_backend_error(
            self._result.filename,
            f"Unsupported native codegen statement: {type(stmt).__name__}",
        )

    def _emit_expr(self, expr: Expr) -> Type:
        if isinstance(expr, IntLiteral):
            expr_type = self._expr_type(expr)
            self._emit_immediate(0, self._parse_int_literal(expr.value), expr_type)
            return expr_type
        if isinstance(expr, CharLiteral):
            self._emit_immediate(0, self._parse_char_literal(expr.value), INT)
            return INT
        if isinstance(expr, StringLiteral):
            label = self._intern_string(expr.value)
            self._emit_address(label)
            return self._expr_type(expr)
        if isinstance(expr, FloatLiteral):
            raise native_backend_error(
                self._result.filename,
                "Floating-point expressions are not supported by the native backend",
            )
        if isinstance(expr, Identifier):
            return self._emit_identifier(expr.name)
        if isinstance(expr, UnaryExpr):
            operand_type = self._emit_expr(expr.operand)
            result_type = self._expr_type(expr)
            if expr.op == "+":
                self._coerce_primary(operand_type, result_type)
                return result_type
            if expr.op == "-":
                self._coerce_primary(operand_type, result_type)
                reg = self._primary_reg(result_type)
                self._lines.append(f"neg {reg}, {reg}")
                return result_type
            if expr.op == "~":
                self._coerce_primary(operand_type, result_type)
                reg = self._primary_reg(result_type)
                self._lines.append(f"mvn {reg}, {reg}")
                return result_type
            if expr.op == "!":
                self._emit_compare_zero(operand_type, 0)
                self._lines.append("cset w0, eq")
                return INT
            raise native_backend_error(
                self._result.filename,
                f"Unsupported native codegen unary operator: {expr.op}",
            )
        if isinstance(expr, BinaryExpr):
            return self._emit_binary_expr(expr)
        if isinstance(expr, AssignExpr):
            return self._emit_assign_expr(expr)
        if isinstance(expr, UpdateExpr):
            return self._emit_update_expr(expr)
        if isinstance(expr, CallExpr):
            return self._emit_call_expr(expr)
        if isinstance(expr, CommaExpr):
            self._emit_expr(expr.left)
            return self._emit_expr(expr.right)
        if isinstance(expr, ConditionalExpr):
            return self._emit_conditional_expr(expr)
        if isinstance(expr, CastExpr):
            return self._emit_cast_expr(expr)
        if isinstance(expr, SizeofExpr):
            size = self._eval_sizeof(expr)
            self._emit_immediate(0, size, INT)
            return INT
        if isinstance(expr, AlignofExpr):
            align = self._eval_alignof(expr)
            self._emit_immediate(0, align, INT)
            return INT
        raise native_backend_error(
            self._result.filename,
            f"Unsupported native codegen expression: {type(expr).__name__}",
        )

    def _emit_binary_expr(self, expr: BinaryExpr) -> Type:
        if expr.op == "&&":
            false_label = self._new_label("and_false")
            end_label = self._new_label("and_end")
            self._emit_branch_if_zero(expr.left, false_label)
            self._emit_branch_if_zero(expr.right, false_label)
            self._lines.append("mov w0, #1")
            self._lines.append(f"b {end_label}")
            self._lines.append(f"{false_label}:")
            self._lines.append("mov w0, #0")
            self._lines.append(f"{end_label}:")
            return INT
        if expr.op == "||":
            true_label = self._new_label("or_true")
            end_label = self._new_label("or_end")
            self._emit_expr(expr.left)
            if self._is_wide_type(self._expr_type(expr.left)):
                self._lines.append(f"cbnz x0, {true_label}")
            else:
                self._lines.append(f"cbnz w0, {true_label}")
            self._emit_expr(expr.right)
            if self._is_wide_type(self._expr_type(expr.right)):
                self._lines.append(f"cbnz x0, {true_label}")
            else:
                self._lines.append(f"cbnz w0, {true_label}")
            self._lines.append("mov w0, #0")
            self._lines.append(f"b {end_label}")
            self._lines.append(f"{true_label}:")
            self._lines.append("mov w0, #1")
            self._lines.append(f"{end_label}:")
            return INT
        left_type = self._emit_expr(expr.left)
        operand_type = self._binary_operand_type(expr)
        self._coerce_primary(left_type, operand_type)
        self._spill_primary(operand_type)
        right_type = self._emit_expr(expr.right)
        right_operand_type = (
            operand_type if expr.op not in {"<<", ">>"} else self._expr_type(expr.right)
        )
        self._coerce_primary(right_type, right_operand_type)
        self._reload_secondary()
        result_type = self._expr_type(expr)
        if expr.op in {"+", "-", "*", "/", "%", "&", "^", "|", "<<", ">>"}:
            self._emit_binary_op(expr.op, operand_type, right_operand_type)
            return result_type
        if expr.op in {"<", "<=", ">", ">=", "==", "!="}:
            compare_type = operand_type
            self._emit_compare(compare_type)
            cond = {
                "<": "lt",
                "<=": "le",
                ">": "gt",
                ">=": "ge",
                "==": "eq",
                "!=": "ne",
            }[expr.op]
            self._lines.append(f"cset w0, {cond}")
            return INT
        raise native_backend_error(
            self._result.filename,
            f"Unsupported native codegen binary operator: {expr.op}",
        )

    def _emit_binary_op(self, op: str, left_type: Type, right_type: Type) -> None:
        if not self._supported_integer_type(left_type) or not self._supported_integer_type(
            right_type
        ):
            raise native_backend_error(
                self._result.filename,
                f"Unsupported native codegen operand types for '{op}'",
            )
        reg0 = self._primary_reg(left_type)
        reg1 = self._secondary_reg(left_type)
        if op == "+":
            self._lines.append(f"add {reg0}, {reg1}, {reg0}")
            return
        if op == "-":
            self._lines.append(f"sub {reg0}, {reg1}, {reg0}")
            return
        if op == "*":
            self._lines.append(f"mul {reg0}, {reg1}, {reg0}")
            return
        if op == "/":
            self._lines.append(f"sdiv {reg0}, {reg1}, {reg0}")
            return
        if op == "%":
            self._lines.append(f"sdiv {reg0}, {reg1}, {reg0}")
            self._lines.append(f"msub {reg0}, {reg0}, {reg1}, {reg1}")
            return
        if op == "&":
            self._lines.append(f"and {reg0}, {reg1}, {reg0}")
            return
        if op == "^":
            self._lines.append(f"eor {reg0}, {reg1}, {reg0}")
            return
        if op == "|":
            self._lines.append(f"orr {reg0}, {reg1}, {reg0}")
            return
        if op == "<<":
            self._lines.append(f"lsl {reg0}, {reg1}, {self._primary_reg(right_type)}")
            return
        if op == ">>":
            self._lines.append(f"asr {reg0}, {reg1}, {self._primary_reg(right_type)}")
            return
        raise native_backend_error(
            self._result.filename,
            f"Unsupported native codegen binary operator: {op}",
        )

    def _emit_assign_expr(self, expr: AssignExpr) -> Type:
        if not isinstance(expr.target, Identifier):
            raise native_backend_error(
                self._result.filename,
                "Native backend only supports assignments to identifiers",
            )
        target_slot = self._lookup_local(expr.target.name)
        target_global = self._global_objects.get(expr.target.name)
        if target_slot is None and target_global is None:
            raise native_backend_error(
                self._result.filename,
                f"Unsupported native assignment target: {expr.target.name}",
            )
        target_type = self._expr_type(expr.target)
        if expr.op == "=":
            self._emit_expr(expr.value)
            self._coerce_primary(self._expr_type(expr.value), target_type)
            self._store_target(expr.target.name, target_type)
            return target_type
        if expr.op not in {"+=", "-=", "*=", "/=", "%=", "&=", "^=", "|=", "<<=", ">>="}:
            raise native_backend_error(
                self._result.filename,
                f"Unsupported native codegen assignment operator: {expr.op}",
            )
        if not self._supported_integer_type(target_type):
            raise native_backend_error(
                self._result.filename,
                f"Unsupported native codegen assignment target type for '{expr.op}'",
            )
        self._emit_identifier(expr.target.name)
        self._spill_primary(target_type)
        self._emit_expr(expr.value)
        self._coerce_primary(self._expr_type(expr.value), target_type)
        self._reload_secondary()
        self._emit_binary_op(expr.op[:-1], target_type, target_type)
        self._store_target(expr.target.name, target_type)
        return target_type

    def _emit_update_expr(self, expr: UpdateExpr) -> Type:
        if not isinstance(expr.operand, Identifier):
            raise native_backend_error(
                self._result.filename,
                "Native backend only supports updates on identifiers",
            )
        operand_type = self._expr_type(expr)
        if not self._supported_integer_type(operand_type):
            raise native_backend_error(
                self._result.filename,
                f"Unsupported native codegen update operand type: {expr.operand.name}",
            )
        self._emit_identifier(expr.operand.name)
        if expr.is_postfix:
            self._spill_primary(operand_type)
        reg = self._primary_reg(operand_type)
        if expr.op == "++":
            self._lines.append(f"add {reg}, {reg}, #1")
        elif expr.op == "--":
            self._lines.append(f"sub {reg}, {reg}, #1")
        else:
            raise native_backend_error(
                self._result.filename,
                f"Unsupported native codegen update operator: {expr.op}",
            )
        self._store_target(expr.operand.name, operand_type)
        if expr.is_postfix:
            self._reload_primary()
        return operand_type

    def _emit_call_expr(self, expr: CallExpr) -> Type:
        if not isinstance(expr.callee, Identifier):
            raise native_backend_error(
                self._result.filename,
                "Native backend only supports direct function calls",
            )
        callee_type = self._function_types.get(expr.callee.name)
        if callee_type is None:
            raise native_backend_error(
                self._result.filename,
                f"Unknown function for native backend call: {expr.callee.name}",
            )
        signature = callee_type.callable_signature()
        if signature is None:
            raise native_backend_error(
                self._result.filename,
                f"Call target is not supported by the native backend: {expr.callee.name}",
            )
        return_type, params = signature
        parameter_types, is_variadic = params
        if parameter_types is None:
            raise native_backend_error(
                self._result.filename,
                f"Native backend requires a prototype for calls: {expr.callee.name}",
            )
        if is_variadic:
            raise native_backend_error(
                self._result.filename,
                f"Variadic calls are not supported by the native backend: {expr.callee.name}",
            )
        if len(expr.args) > 8:
            raise native_backend_error(
                self._result.filename,
                f"Native backend supports at most 8 call arguments: {expr.callee.name}",
            )
        stack_bytes = len(expr.args) * 16
        for arg, param_type in zip(expr.args, parameter_types, strict=False):
            self._emit_expr(arg)
            self._coerce_primary(self._expr_type(arg), param_type)
            self._extend_primary_to_stack64(param_type)
            self._lines.append("sub sp, sp, #16")
            self._lines.append("str x0, [sp]")
        for index, param_type in enumerate(parameter_types):
            offset = (len(parameter_types) - index - 1) * 16
            reg = self._register_name(index, self._storage_width(param_type))
            self._lines.append(f"ldr {reg}, [sp, #{offset}]")
        self._lines.append(f"bl {self._symbol_name(expr.callee.name)}")
        if stack_bytes:
            self._lines.append(f"add sp, sp, #{stack_bytes}")
        return return_type

    def _emit_conditional_expr(self, expr: ConditionalExpr) -> Type:
        result_type = self._expr_type(expr)
        else_label = self._new_label("cond_else")
        end_label = self._new_label("cond_end")
        self._emit_branch_if_zero(expr.condition, else_label)
        self._emit_expr(expr.then_expr)
        self._coerce_primary(self._expr_type(expr.then_expr), result_type)
        self._lines.append(f"b {end_label}")
        self._lines.append(f"{else_label}:")
        self._emit_expr(expr.else_expr)
        self._coerce_primary(self._expr_type(expr.else_expr), result_type)
        self._lines.append(f"{end_label}:")
        return result_type

    def _emit_cast_expr(self, expr: CastExpr) -> Type:
        target_type = self._expr_type(expr)
        if target_type == VOID:
            self._emit_expr(expr.expr)
            return VOID
        self._emit_expr(expr.expr)
        self._coerce_primary(self._expr_type(expr.expr), target_type)
        return target_type

    def _emit_branch_if_zero(self, expr: Expr, label: str) -> None:
        expr_type = self._emit_expr(expr)
        if self._is_wide_type(expr_type):
            self._lines.append(f"cbz x0, {label}")
            return
        self._lines.append(f"cbz w0, {label}")

    def _emit_compare(self, type_: Type) -> None:
        reg0 = self._primary_reg(type_)
        reg1 = self._secondary_reg(type_)
        self._lines.append(f"cmp {reg1}, {reg0}")

    def _emit_compare_zero(self, type_: Type, reg_index: int) -> None:
        self._lines.append(f"cmp {self._register_name(reg_index, self._storage_width(type_))}, #0")

    def _emit_identifier(self, name: str) -> Type:
        slot = self._lookup_local(name)
        if slot is not None:
            self._load_local(slot, 0)
            return slot.type_
        global_object = self._global_objects.get(name)
        if global_object is not None:
            self._emit_address(self._symbol_name(name), 9)
            self._lines.append(f"ldr {self._primary_reg(global_object.type_)}, [x9]")
            return global_object.type_
        if name in self._function_names:
            raise native_backend_error(
                self._result.filename,
                f"Function designators are not supported as values by the native backend: {name}",
            )
        raise native_backend_error(
            self._result.filename,
            f"Unsupported native identifier reference: {name}",
        )

    def _store_target(self, name: str, type_: Type) -> None:
        slot = self._lookup_local(name)
        if slot is not None:
            self._store_local(slot, 0)
            return
        global_object = self._global_objects.get(name)
        if global_object is None:
            raise native_backend_error(
                self._result.filename,
                f"Unsupported native assignment target: {name}",
            )
        self._emit_address(self._symbol_name(name), 9)
        self._lines.append(f"str {self._primary_reg(type_)}, [x9]")

    def _spill_primary(self, type_: Type) -> None:
        self._extend_primary_to_stack64(type_)
        self._lines.append("sub sp, sp, #16")
        self._lines.append("str x0, [sp]")

    def _reload_secondary(self) -> None:
        self._lines.append("ldr x1, [sp]")
        self._lines.append("add sp, sp, #16")

    def _reload_primary(self) -> None:
        self._lines.append("ldr x0, [sp]")
        self._lines.append("add sp, sp, #16")

    def _emit_immediate(self, reg_index: int, value: int, type_: Type) -> None:
        width = self._storage_width(type_)
        masked = value & ((1 << (width * 8)) - 1)
        reg = self._register_name(reg_index, width)
        chunks = [(masked >> shift) & 0xFFFF for shift in range(0, width * 8, 16)]
        first = True
        for chunk_index, chunk in enumerate(chunks):
            if chunk == 0 and not first:
                continue
            if first:
                self._lines.append(f"movz {reg}, #{chunk}, lsl #{chunk_index * 16}")
                first = False
                continue
            self._lines.append(f"movk {reg}, #{chunk}, lsl #{chunk_index * 16}")
        if first:
            self._lines.append(f"movz {reg}, #0")

    def _emit_address(self, label: str, reg_index: int = 0) -> None:
        reg = self._register_name(reg_index, 8)
        self._lines.append(f"adrp {reg}, {label}@PAGE")
        self._lines.append(f"add {reg}, {reg}, {label}@PAGEOFF")

    def _load_local(self, slot: _StackSlot, reg_index: int) -> None:
        reg = self._register_name(reg_index, self._storage_width(slot.type_))
        self._lines.append(f"ldur {reg}, [x29, #-{slot.offset}]")

    def _store_local(self, slot: _StackSlot, reg_index: int) -> None:
        reg = self._register_name(reg_index, self._storage_width(slot.type_))
        self._lines.append(f"stur {reg}, [x29, #-{slot.offset}]")

    def _coerce_primary(self, source_type: Type, target_type: Type) -> None:
        if target_type == VOID:
            return
        self._ensure_supported_runtime_type(source_type, "source expression")
        self._ensure_supported_runtime_type(target_type, "target expression")
        if self._storage_width(source_type) == self._storage_width(target_type):
            return
        if self._storage_width(source_type) == 4 and self._storage_width(target_type) == 8:
            self._lines.append("sxtw x0, w0")
            return
        if self._storage_width(source_type) == 8 and self._storage_width(target_type) == 4:
            self._lines.append("mov w0, w0")
            return
        raise native_backend_error(
            self._result.filename,
            f"Unsupported native conversion from '{source_type}' to '{target_type}'",
        )

    def _extend_primary_to_stack64(self, type_: Type) -> None:
        if self._storage_width(type_) == 8:
            return
        self._lines.append("sxtw x0, w0")

    def _binary_operand_type(self, expr: BinaryExpr) -> Type:
        left_type = self._expr_type(expr.left)
        right_type = self._expr_type(expr.right)
        if self._is_pointer_type(left_type) or self._is_pointer_type(right_type):
            if expr.op not in {"==", "!="}:
                raise native_backend_error(
                    self._result.filename,
                    f"Pointer operands are not supported for '{expr.op}' in the native backend",
                )
            return left_type if self._is_pointer_type(left_type) else right_type
        result_type = self._expr_type(expr)
        self._ensure_supported_runtime_type(result_type, f"binary '{expr.op}'")
        return result_type

    def _resolve_return_type(self, func: FunctionDef) -> Type:
        if func.return_type.name == "void" and not func.return_type.declarator_ops:
            return VOID
        return self._resolve_object_type(func.return_type, f"return type of {func.name}")

    def _resolve_object_type(self, type_spec: TypeSpec, context: str) -> Type:
        name = type_spec.name
        declarator_ops = type_spec.declarator_ops
        qualifiers = type_spec.qualifiers
        if any(kind in {"arr", "fn"} for kind, _ in declarator_ops):
            raise native_backend_error(
                self._result.filename,
                f"Unsupported native codegen type in {context}: declarator",
            )
        if declarator_ops:
            pointer_ops = tuple(("ptr", 0) for kind, _ in declarator_ops if kind == "ptr")
            return Type(name, declarator_ops=pointer_ops, qualifiers=qualifiers)
        if name == "int":
            return Type("int", qualifiers=qualifiers)
        if name == "long":
            return Type("long", qualifiers=qualifiers)
        if name == "void":
            return VOID
        raise native_backend_error(
            self._result.filename,
            f"Unsupported native codegen type in {context}: {name}",
        )

    def _check_function_contract(self, func: FunctionDef) -> None:
        if func.storage_class not in {None, "extern"}:
            raise native_backend_error(
                self._result.filename,
                f"Unsupported native codegen function storage: {func.name}",
            )
        if func.is_thread_local or func.is_inline or func.is_noreturn or func.is_overloadable:
            raise native_backend_error(
                self._result.filename,
                f"Unsupported native codegen function attributes: {func.name}",
            )
        if func.is_variadic:
            raise native_backend_error(
                self._result.filename,
                f"Variadic functions are not supported by the native backend: {func.name}",
            )
        self._resolve_return_type(func)
        for index, param in enumerate(func.params, start=1):
            label = param.name if param.name is not None else f"parameter {index}"
            self._resolve_object_type(param.type_spec, label)

    def _function_type(self, func: FunctionDef) -> Type:
        return_type = self._resolve_return_type(func)
        params = tuple(
            self._resolve_object_type(
                param.type_spec,
                param.name if param.name is not None else f"parameter {index}",
            )
            for index, param in enumerate(func.params, start=1)
        )
        return return_type.function_of(params, is_variadic=func.is_variadic)

    def _ensure_supported_runtime_type(self, type_: Type, context: str) -> None:
        if type_ == VOID:
            return
        if self._is_pointer_type(type_):
            return
        if self._supported_integer_type(type_):
            return
        raise native_backend_error(
            self._result.filename,
            f"Unsupported native codegen type in {context}: {type_}",
        )

    def _supported_integer_type(self, type_: Type) -> bool:
        return not type_.declarator_ops and type_.name in {INT.name, LONG.name}

    def _is_pointer_type(self, type_: Type) -> bool:
        return bool(type_.declarator_ops) and type_.declarator_ops[0][0] == "ptr"

    def _is_wide_type(self, type_: Type) -> bool:
        return self._storage_width(type_) == 8

    def _storage_width(self, type_: Type) -> int:
        self._ensure_supported_runtime_type(type_, "storage")
        if self._is_pointer_type(type_) or type_.name == LONG.name:
            return 8
        return 4

    def _lookup_local(self, name: str) -> _StackSlot | None:
        for scope in reversed(self._current_scopes):
            slot = scope.get(name)
            if slot is not None:
                return slot
        return None

    def _expr_type(self, expr: Expr) -> Type:
        return self._type_map.require(expr)

    def _register_name(self, index: int, width: int) -> str:
        return f"{'x' if width == 8 else 'w'}{index}"

    def _primary_reg(self, type_: Type) -> str:
        return self._register_name(0, self._storage_width(type_))

    def _secondary_reg(self, type_: Type) -> str:
        return self._register_name(1, self._storage_width(type_))

    def _new_label(self, prefix: str) -> str:
        self._label_counter += 1
        return f"L_xcc_{prefix}_{self._label_counter}"

    def _symbol_name(self, name: str) -> str:
        return f"_{name}"

    def _intern_string(self, literal: str) -> str:
        label = self._string_labels.get(literal)
        if label is None:
            label = self._new_label("str")
            self._string_labels[literal] = label
        return label

    def _parse_int_literal(self, lexeme: str) -> int:
        suffix_start = len(lexeme)
        while suffix_start > 0 and lexeme[suffix_start - 1] in "uUlL":
            suffix_start -= 1
        body = lexeme[:suffix_start]
        if body.startswith(("0x", "0X")):
            return int(body[2:], 16)
        if body.startswith("0") and len(body) > 1:
            return int(body, 8)
        return int(body, 10)

    def _parse_char_literal(self, lexeme: str) -> int:
        if len(lexeme) >= 3 and lexeme[0] == "'" and lexeme[-1] == "'":
            body = lexeme[1:-1]
            if body.startswith("\\"):
                escapes = {
                    "n": 10,
                    "t": 9,
                    "r": 13,
                    "\\": 92,
                    "'": 39,
                    '"': 34,
                    "0": 0,
                }
                value = escapes.get(body[1:])
                if value is not None:
                    return value
            if len(body) == 1:
                return ord(body)
        raise native_backend_error(
            self._result.filename,
            f"Unsupported native character literal: {lexeme}",
        )

    def _eval_global_initializer(self, expr: Expr, target_type: Type) -> int:
        if isinstance(expr, IntLiteral):
            return self._parse_int_literal(expr.value)
        if isinstance(expr, CharLiteral):
            return self._parse_char_literal(expr.value)
        if isinstance(expr, UnaryExpr):
            value = self._eval_global_initializer(expr.operand, target_type)
            if expr.op == "+":
                return value
            if expr.op == "-":
                return -value
            if expr.op == "~":
                return ~value
            if expr.op == "!":
                return 0 if value else 1
        if isinstance(expr, BinaryExpr):
            left = self._eval_global_initializer(expr.left, target_type)
            right = self._eval_global_initializer(expr.right, target_type)
            operations = {
                "+": left + right,
                "-": left - right,
                "*": left * right,
                "/": left // right,
                "%": left % right,
                "&": left & right,
                "^": left ^ right,
                "|": left | right,
                "<<": left << right,
                ">>": left >> right,
                "==": int(left == right),
                "!=": int(left != right),
                "<": int(left < right),
                "<=": int(left <= right),
                ">": int(left > right),
                ">=": int(left >= right),
                "&&": int(bool(left) and bool(right)),
                "||": int(bool(left) or bool(right)),
            }
            if expr.op in operations:
                return operations[expr.op]
        if isinstance(expr, CastExpr):
            return self._eval_global_initializer(expr.expr, target_type)
        if isinstance(expr, SizeofExpr):
            return self._eval_sizeof(expr)
        if isinstance(expr, AlignofExpr):
            return self._eval_alignof(expr)
        raise native_backend_error(
            self._result.filename,
            f"Unsupported global initializer for native backend: {type(expr).__name__}",
        )

    def _eval_sizeof(self, expr: SizeofExpr) -> int:
        if expr.type_spec is not None:
            type_ = self._resolve_object_type(expr.type_spec, "sizeof")
            return self._storage_width(type_)
        assert expr.expr is not None
        return self._storage_width(self._expr_type(expr.expr))

    def _eval_alignof(self, expr: AlignofExpr) -> int:
        if expr.type_spec is not None:
            type_ = self._resolve_object_type(expr.type_spec, "alignof")
            return self._storage_width(type_)
        assert expr.expr is not None
        return self._storage_width(self._expr_type(expr.expr))

    def _asm_string(self, literal: str) -> str:
        body = literal
        if literal.startswith(('u8"', '"')) and literal.endswith('"'):
            body = literal[3:-1] if literal.startswith('u8"') else literal[1:-1]
        escaped = (
            body.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")
        )
        return f'"{escaped}"'
