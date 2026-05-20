"""ClangIR MLIR emitter for XCC.

Consumes FrontendResult (AST + TypeMap + SemaUnit), produces ClangIR
MLIR text. The output is validated with cir-opt --verify when available.
"""

import struct
from dataclasses import dataclass

from xcc.ast import (
    AlignofExpr,
    AssignExpr,
    BinaryExpr,
    BreakStmt,
    CallExpr,
    CaseStmt,
    CastExpr,
    CharLiteral,
    CommaExpr,
    CompoundLiteralExpr,
    CompoundStmt,
    ConditionalExpr,
    ContinueStmt,
    DeclGroupStmt,
    DeclStmt,
    DefaultStmt,
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
    MemberExpr,
    NullStmt,
    ReturnStmt,
    SizeofExpr,
    StaticAssertDecl,
    StatementExpr,
    Stmt,
    StringLiteral,
    SubscriptExpr,
    SwitchStmt,
    TypedefDecl,
    TypeSpec,
    UnaryExpr,
    UpdateExpr,
    WhileStmt,
)
from xcc.diag import CodegenError, Diagnostic
from xcc.frontend import FrontendResult
from xcc.sema.symbols import FunctionSymbol, VarSymbol
from xcc.types import INT, LONG, Type

_CG_UNSUPPORTED = "XCC-CG-0005"


def cir_backend_error(filename: str, message: str) -> CodegenError:
    return CodegenError(Diagnostic("codegen", filename, message, code=_CG_UNSUPPORTED))


def generate_cir(result: FrontendResult) -> str:
    return _CIRCodeGen(result).generate()


# ── type mapping: XCC → CIR ────────────────────────────────

_INT_TYPES = {
    "int": "!cir.int<s, 32>",
    "unsigned int": "!cir.int<u, 32>",
    "long": "!cir.int<s, 64>",
    "unsigned long": "!cir.int<u, 64>",
    "long long": "!cir.int<s, 64>",
    "unsigned long long": "!cir.int<u, 64>",
    "char": "!cir.int<s, 8>",
    "unsigned char": "!cir.int<u, 8>",
    "signed char": "!cir.int<s, 8>",
    "short": "!cir.int<s, 16>",
    "unsigned short": "!cir.int<u, 16>",
    "_Bool": "!cir.bool",
    "float": "!cir.float",
    "double": "!cir.double",
    "long double": "!cir.long_double<!cir.f128>",
    "void": "!cir.void",
    "__builtin_va_list": "!cir.ptr<!cir.void>",
}


def _cir_type(t: Type) -> str:
    """Map XCC Type to CIR MLIR type string."""
    base = _INT_TYPES.get(t.name)
    if base is None:
        raise ValueError(f"Unsupported base type: {t.name}")
    if not t.declarator_ops:
        return base
    result = base
    for kind, value in reversed(t.declarator_ops):
        if kind == "ptr":
            result = f"!cir.ptr<{result}>"
        elif kind == "arr":
            if isinstance(value, int):
                result = f"!cir.array<{result} x {value}>"
            else:
                result = f"!cir.array<{result}>"
        elif kind == "fn":
            params = ()
            is_variadic = False
            if isinstance(value, tuple):
                params = value[0] if value[0] else ()
                is_variadic = value[1]
            param_strs = ", ".join(_cir_type(p) for p in params)
            if is_variadic:
                param_strs = f"{param_strs}, ..." if param_strs else "..."
            result = f"!cir.func<({param_strs}) -> {result}>"
    return result


def _cir_ptr_type(t: Type) -> str:
    """Return CIR pointer type for a given type."""
    return f"!cir.ptr<{_cir_type(t)}>"


# ── value holder ────────────────────────────────────────────

@dataclass
class _V:
    ref: str         # SSA name: %0, %myvar.addr, @global
    cir_type: str    # CIR MLIR type string


# ── code generator ──────────────────────────────────────────

class _CIRCodeGen:
    def __init__(self, result: FrontendResult) -> None:
        self._result = result
        self._unit = result.unit
        self._type_map = result.sema.type_map
        self._sema = result.sema

        self._lines: list[str] = []
        self._indent = 0
        self._value_counter = 0
        self._label_counter = 0

        # Type alias tracking
        self._type_aliases: dict[str, str] = {}  # CIR type → alias name
        self._struct_names: dict[str, str] = {}  # "struct foo" → "ty_22struct2Efoo22"

        # String interning
        self._string_globals: dict[str, str] = {}

        # Function state (reset per function)
        self._func: FunctionDef | None = None
        self._func_sym: FunctionSymbol | None = None
        self._locals: list[dict[str, _V]] = []
        self._loop_stack: list[_LoopCtx] = []
        self._block_done = False
        self._switch_end_labels: list[tuple[str, str | None]] = []

    # ── helpers ──────────────────────────────────────────────

    def _new_v(self, cir_type: str) -> _V:
        self._value_counter += 1
        return _V(f"%{self._value_counter}", cir_type)

    def _new_label(self, prefix: str = "bb") -> str:
        self._label_counter += 1
        return f"{prefix}{self._label_counter}"

    def _emit(self, line: str) -> None:
        if not line:
            self._lines.append("")
            return
        if line.startswith("}") or line.endswith(":}"):
            self._indent -= 1
        prefix = "  " * self._indent
        self._lines.append(f"{prefix}{line}")
        if line.endswith("{") or line.endswith("({"):
            self._indent += 1

    def _emit_label(self, label: str) -> None:
        if not self._block_done:
            self._emit(f"cir.br ^{label}")
        self._indent = max(0, self._indent - 1)
        self._lines.append(f"^{label}:")
        self._indent += 1
        self._block_done = False

    def _term(self, line: str) -> None:
        self._emit(line)
        self._block_done = True

    # ── type helpers ─────────────────────────────────────────

    def _ensure_type_alias(self, cir_type: str) -> str:
        """Ensure a short alias for a CIR type, return the alias."""
        if cir_type in self._type_aliases:
            return self._type_aliases[cir_type]
        idx = len(self._type_aliases)
        alias = f"!ty{idx}"
        self._type_aliases[cir_type] = alias
        return alias

    def _struct_cir_type(self, record_name: str) -> str:
        """Get CIR record type for a struct/union name (e.g. 'struct foo')."""
        if record_name not in self._struct_names:
            # Encode name: replace spaces and special chars with hex-like encoding
            # Follow ClangIR convention: "struct.foo" → "ty_22struct2Efoo22"
            encoded = record_name.replace(" ", "2E")
            # Actually, let's just count index and assign: struct.N
            idx = len(self._struct_names)
            name = f"ty_22struct{idx}"
            self._struct_names[record_name] = name
        return self._struct_names[record_name]

    def _field_index(self, record_name: str, member_name: str) -> int:
        members = self._sema.record_definitions.get(record_name)
        if not members:
            raise cir_backend_error(
                self._result.filename, f"Unknown record: {record_name}"
            )
        for i, m in enumerate(members):
            if m.name == member_name:
                return i
        raise cir_backend_error(
            self._result.filename,
            f"Record '{record_name}' has no member '{member_name}'",
        )

    # ── module generation ────────────────────────────────────

    def generate(self) -> str:
        self._emit_type_aliases()
        self._emit("module {")
        self._emit_struct_decls()
        self._emit_globals()
        self._emit_function_decls()
        self._emit_function_defs()
        self._emit("}")
        return "\n".join(self._lines) + "\n"

    def _emit_type_aliases(self) -> None:
        """Pre-declare commonly used type aliases."""
        common = [
            ("!s32i", "!cir.int<s, 32>"),
            ("!s64i", "!cir.int<s, 64>"),
            ("!u32i", "!cir.int<u, 32>"),
            ("!u64i", "!cir.int<u, 64>"),
            ("!s8i", "!cir.int<s, 8>"),
            ("!u8i", "!cir.int<u, 8>"),
            ("!s16i", "!cir.int<s, 16>"),
            ("!u16i", "!cir.int<u, 16>"),
            ("!cir_bool", "!cir.bool"),
        ]
        for alias, typ in common:
            self._emit(f"{alias} = {typ}")
            self._type_aliases[typ] = alias
        self._emit("")

    def _emit_struct_decls(self) -> None:
        for record_name, members in self._sema.record_definitions.items():
            cir_name = self._struct_cir_type(record_name)
            field_types = [_cir_type(m.type_) for m in members]
            self._emit(f"{cir_name} = !cir.record<\"{record_name}\" {{{', '.join(field_types)}}}>")
        if self._sema.record_definitions:
            self._emit("")

    def _emit_globals(self) -> None:
        externals = self._unit.externals or [
            *self._unit.declarations, *self._unit.functions
        ]
        for external in externals:
            if isinstance(external, FunctionDef):
                continue
            if isinstance(external, DeclGroupStmt):
                for decl in external.declarations:
                    self._emit_global_var(decl)
            elif isinstance(external, DeclStmt):
                self._emit_global_var(decl)
        # String constant globals
        for literal in self._string_globals:
            glob_name = self._string_globals[literal]
            body = self._decode_string(literal)
            length = len(body) + 1
            escaped = self._escape_string(body)
            self._emit(
                f"{glob_name} = cir.global constant "
                f"@str = #cir.const_array<\"{escaped}\\00\" : !cir.array<!s8i x {length}>>"
            )
        self._emit("")

    def _emit_global_var(self, decl: DeclStmt) -> None:
        name = decl.name
        if name is None or decl.storage_class == "extern":
            return
        var_type = self._resolve_type(decl.type_spec)
        cir_type = _cir_type(var_type)
        if decl.init is not None:
            init_val = self._eval_init_val(decl.init, var_type)
            self._emit(f"cir.global external @{name} = {init_val} : {cir_type}")
        else:
            self._emit(f"cir.global external @{name} = #cir.zero : {cir_type}")

    def _emit_function_decls(self) -> None:
        for func in self._unit.functions:
            if func.body is not None:
                continue
            func_sym = self._sema.functions.get(func.name)
            if func_sym is None:
                continue
            ret_type = _cir_type(func_sym.return_type)
            params = self._build_param_str(func, func_sym)
            self._emit(f"cir.func private @{func.name}({', '.join(params)}) -> {ret_type}")

    def _emit_function_defs(self) -> None:
        for func in self._unit.functions:
            if func.body is None:
                continue
            self._emit_function(func)

    # ── function emission ────────────────────────────────────

    def _emit_function(self, func: FunctionDef) -> None:
        self._func = func
        self._func_sym = self._sema.functions.get(func.name)
        if self._func_sym is None:
            raise cir_backend_error(
                self._result.filename,
                f"No semantic info for function '{func.name}'",
            )

        self._locals = [{}]
        self._loop_stack = []
        self._block_done = False
        self._switch_end_labels = []
        self._value_counter = 0
        self._label_counter = 0

        ret_type = _cir_type(self._func_sym.return_type)
        params = self._build_param_str(func, self._func_sym)

        self._emit(f"cir.func @{func.name}({', '.join(params)}) -> {ret_type} {{")

        # Alloca + store for each parameter
        for i, param in enumerate(func.params):
            assert param.name
            ptype = self._resolve_type(param.type_spec)
            cir_ptype = _cir_type(ptype)
            alloca = self._new_v(_cir_ptr_type(ptype))
            self._emit(
                f"{alloca.ref} = cir.alloca {cir_ptype}, "
                f"{alloca.cir_type}, [\"{param.name}\", init]"
            )
            self._emit(
                f"cir.store %arg{i}, {alloca.ref} : "
                f"{cir_ptype}, {alloca.cir_type}"
            )
            self._locals[-1][param.name] = alloca

        # Pre-collect allocas for local variables
        allocas = self._collect_allocas(func.body)
        for vname, vtype in allocas:
            if vname in self._locals[-1]:
                continue
            cir_ptype = _cir_type(vtype)
            cir_ptr = _cir_ptr_type(vtype)
            alloca = self._new_v(cir_ptr)
            self._emit(
                f"{alloca.ref} = cir.alloca {cir_ptype}, "
                f"{cir_ptr}, [\"{vname}\", init]"
            )
            self._locals[-1][vname] = alloca

        self._emit_stmt(func.body)

        if not self._block_done:
            self._term("cir.return")

        self._emit("}")
        self._emit("")
        self._func = None
        self._func_sym = None

    def _build_param_str(
        self, func: FunctionDef, func_sym: FunctionSymbol
    ) -> list[str]:
        result = []
        for i, param in enumerate(func.params):
            assert param.name
            ptype = self._resolve_type(param.type_spec)
            result.append(f"%arg{i}: {_cir_type(ptype)}")
        return result

    def _collect_allocas(self, stmt: Stmt) -> list[tuple[str, Type]]:
        result: list[tuple[str, Type]] = []
        seen: set[str] = set()
        self._walk_allocas(stmt, result, seen)
        return result

    def _walk_allocas(self, stmt: Stmt, result: list[tuple[str, Type]], seen: set[str]) -> None:
        if isinstance(stmt, CompoundStmt):
            for s in stmt.statements:
                self._walk_allocas(s, result, seen)
        elif isinstance(stmt, DeclStmt):
            if stmt.name and stmt.name not in seen:
                seen.add(stmt.name)
                result.append((stmt.name, self._resolve_type(stmt.type_spec)))
        elif isinstance(stmt, DeclGroupStmt):
            for decl in stmt.declarations:
                self._walk_allocas(decl, result, seen)
        elif isinstance(stmt, IfStmt):
            self._walk_allocas(stmt.then_body, result, seen)
            if stmt.else_body:
                self._walk_allocas(stmt.else_body, result, seen)
        elif isinstance(stmt, (WhileStmt, DoWhileStmt, ForStmt)):
            body = getattr(stmt, 'body', None)
            if body:
                self._walk_allocas(body, result, seen)
        elif isinstance(stmt, SwitchStmt):
            self._walk_allocas(stmt.body, result, seen)
        elif isinstance(stmt, ExprStmt):
            self._walk_allocas_expr(stmt.expr, result, seen)

    def _walk_allocas_expr(self, expr: Expr, result: list[tuple[str, Type]], seen: set[str]) -> None:
        if isinstance(expr, StatementExpr):
            self._walk_allocas(expr.body, result, seen)

    # ── statement emission ───────────────────────────────────

    def _emit_stmt(self, stmt: Stmt) -> None:
        if isinstance(stmt, CompoundStmt):
            self._emit_compound(stmt)
        elif isinstance(stmt, ReturnStmt):
            self._emit_return(stmt)
        elif isinstance(stmt, ExprStmt):
            self._emit_expr(stmt.expr)
        elif isinstance(stmt, NullStmt):
            pass
        elif isinstance(stmt, IfStmt):
            self._emit_if(stmt)
        elif isinstance(stmt, WhileStmt):
            self._emit_while(stmt)
        elif isinstance(stmt, DoWhileStmt):
            self._emit_do_while(stmt)
        elif isinstance(stmt, ForStmt):
            self._emit_for(stmt)
        elif isinstance(stmt, BreakStmt):
            self._emit_break()
        elif isinstance(stmt, ContinueStmt):
            self._emit_continue()
        elif isinstance(stmt, DeclStmt):
            self._emit_decl_init(stmt)
        elif isinstance(stmt, DeclGroupStmt):
            for decl in stmt.declarations:
                self._emit_stmt(decl)
        elif isinstance(stmt, (TypedefDecl, StaticAssertDecl)):
            pass
        else:
            raise cir_backend_error(
                self._result.filename,
                f"Unsupported statement: {type(stmt).__name__}",
            )

    def _emit_compound(self, stmt: CompoundStmt) -> None:
        self._locals.append({})
        for s in stmt.statements:
            self._emit_stmt(s)
        self._locals.pop()

    def _emit_return(self, stmt: ReturnStmt) -> None:
        if stmt.value is None:
            self._term("cir.return")
        else:
            val = self._emit_expr(stmt.value)
            self._term(f"cir.return {val.ref} : {val.cir_type}")

    def _emit_decl_init(self, stmt: DeclStmt) -> None:
        if stmt.name is None or stmt.init is None:
            return
        addr = self._lookup_local(stmt.name)
        if addr is None:
            return
        val = self._emit_expr(stmt.init)
        self._emit(
            f"cir.store {val.ref}, {addr.ref} : "
            f"{val.cir_type}, {addr.cir_type}"
        )

    # ── control flow ─────────────────────────────────────────

    def _emit_if(self, stmt: IfStmt) -> None:
        has_else = stmt.else_body is not None
        cond = self._emit_expr(stmt.condition)
        then_lbl = self._new_label("then")
        else_lbl = self._new_label("else") if has_else else self._new_label("end")
        end_lbl = self._new_label("end") if has_else else else_lbl

        self._term(f"cir.brcond {cond.ref} ^{then_lbl}, ^{else_lbl}")

        self._emit_label(then_lbl)
        self._emit_stmt(stmt.then_body)
        if not self._block_done:
            self._term(f"cir.br ^{end_lbl}")

        if has_else:
            self._emit_label(else_lbl)
            self._emit_stmt(stmt.else_body)
            if not self._block_done:
                self._term(f"cir.br ^{end_lbl}")

        self._emit_label(end_lbl)

    def _emit_while(self, stmt: WhileStmt) -> None:
        cond_lbl = self._new_label("while_cond")
        body_lbl = self._new_label("while_body")
        end_lbl = self._new_label("while_end")

        self._term(f"cir.br ^{cond_lbl}")
        self._emit_label(cond_lbl)
        cond = self._emit_expr(stmt.condition)
        self._term(f"cir.brcond {cond.ref} ^{body_lbl}, ^{end_lbl}")

        self._emit_label(body_lbl)
        self._loop_stack.append(_LoopCtx(cond_lbl, end_lbl))
        self._emit_stmt(stmt.body)
        self._loop_stack.pop()
        if not self._block_done:
            self._term(f"cir.br ^{cond_lbl}")

        self._emit_label(end_lbl)

    def _emit_do_while(self, stmt: DoWhileStmt) -> None:
        body_lbl = self._new_label("do_body")
        cond_lbl = self._new_label("do_cond")
        end_lbl = self._new_label("do_end")

        self._term(f"cir.br ^{body_lbl}")
        self._emit_label(body_lbl)
        self._loop_stack.append(_LoopCtx(cond_lbl, end_lbl))
        self._emit_stmt(stmt.body)
        self._loop_stack.pop()
        if not self._block_done:
            self._term(f"cir.br ^{cond_lbl}")

        self._emit_label(cond_lbl)
        cond = self._emit_expr(stmt.condition)
        self._term(f"cir.brcond {cond.ref} ^{body_lbl}, ^{end_lbl}")

        self._emit_label(end_lbl)

    def _emit_for(self, stmt: ForStmt) -> None:
        cond_lbl = self._new_label("for_cond")
        body_lbl = self._new_label("for_body")
        step_lbl = self._new_label("for_step")
        end_lbl = self._new_label("for_end")

        if stmt.init is not None:
            self._emit_stmt(stmt.init)

        self._term(f"cir.br ^{cond_lbl}")
        self._emit_label(cond_lbl)
        if stmt.condition is not None:
            cond = self._emit_expr(stmt.condition)
            self._term(f"cir.brcond {cond.ref} ^{body_lbl}, ^{end_lbl}")
        else:
            self._term(f"cir.br ^{body_lbl}")

        self._emit_label(body_lbl)
        self._loop_stack.append(_LoopCtx(step_lbl, end_lbl))
        self._emit_stmt(stmt.body)
        self._loop_stack.pop()
        if not self._block_done:
            self._term(f"cir.br ^{step_lbl}")

        self._emit_label(step_lbl)
        if stmt.post is not None:
            self._emit_expr(stmt.post)
        self._term(f"cir.br ^{cond_lbl}")

        self._emit_label(end_lbl)

    def _emit_break(self) -> None:
        if not self._loop_stack and not self._switch_end_labels:
            raise cir_backend_error(
                self._result.filename,
                "break not within loop or switch",
            )
        if self._switch_end_labels:
            end_lbl, _ = self._switch_end_labels[-1]
            self._term(f"cir.br ^{end_lbl}")
            return
        self._term(f"cir.br ^{self._loop_stack[-1].break_label}")

    def _emit_continue(self) -> None:
        if not self._loop_stack:
            raise cir_backend_error(
                self._result.filename,
                "continue not within loop",
            )
        self._term(f"cir.br ^{self._loop_stack[-1].continue_label}")

    # ── expression emission ──────────────────────────────────

    def _emit_expr(self, expr: Expr) -> _V:
        if isinstance(expr, IntLiteral):
            return self._int_literal(expr)
        if isinstance(expr, CharLiteral):
            return self._int_literal(expr)  # char literal → int constant
        if isinstance(expr, FloatLiteral):
            return self._float_literal(expr)
        if isinstance(expr, StringLiteral):
            return self._string_literal(expr)
        if isinstance(expr, Identifier):
            return self._identifier(expr)
        if isinstance(expr, UnaryExpr):
            return self._unary(expr)
        if isinstance(expr, BinaryExpr):
            return self._binary(expr)
        if isinstance(expr, AssignExpr):
            return self._assign(expr)
        if isinstance(expr, UpdateExpr):
            return self._update(expr)
        if isinstance(expr, CallExpr):
            return self._call(expr)
        if isinstance(expr, CastExpr):
            return self._cast(expr)
        if isinstance(expr, SubscriptExpr):
            return self._subscript(expr)
        if isinstance(expr, MemberExpr):
            return self._member(expr)
        if isinstance(expr, ConditionalExpr):
            return self._ternary(expr)
        if isinstance(expr, CommaExpr):
            return self._comma(expr)
        if isinstance(expr, StatementExpr):
            return self._stmt_expr(expr)
        if isinstance(expr, SizeofExpr):
            return self._size_align(expr, "sizeof")
        if isinstance(expr, AlignofExpr):
            return self._size_align(expr, "alignof")
        if isinstance(expr, CompoundLiteralExpr):
            return self._compound_literal(expr)
        raise cir_backend_error(
            self._result.filename,
            f"Unsupported expression: {type(expr).__name__}",
        )

    # ── literals ─────────────────────────────────────────────

    def _int_literal(self, expr: IntLiteral | CharLiteral) -> _V:
        val_type = self._type_map.get(expr)
        if val_type is None:
            val_type = INT
        cir_type = _cir_type(val_type)
        v = self._new_v(cir_type)
        if isinstance(expr, CharLiteral):
            value = ord(expr.value)
        else:
            value = int(expr.value)
        self._emit(f"{v.ref} = cir.const #cir.int<{value}> : {cir_type}")
        return v

    def _float_literal(self, expr: FloatLiteral) -> _V:
        val_type = self._type_map.get(expr)
        cir_type = _cir_type(val_type) if val_type else "!cir.double"
        v = self._new_v(cir_type)
        val = float(expr.value)
        # Use hex float format for precision
        if "float" in cir_type and "double" not in cir_type:
            bits = struct.pack("!f", val)
            raw = struct.unpack("!I", bits)[0]
            hex_str = f"0x{raw:08X}"
            self._emit(f"{v.ref} = cir.const #cir.fp<{hex_str}> : {cir_type}")
        else:
            bits = struct.pack("!d", val)
            raw = struct.unpack("!Q", bits)[0]
            hex_str = f"0x{raw:016X}"
            self._emit(f"{v.ref} = cir.const #cir.fp<{hex_str}> : {cir_type}")
        return v

    def _string_literal(self, expr: StringLiteral) -> _V:
        if expr.value not in self._string_globals:
            idx = len(self._string_globals)
            self._string_globals[expr.value] = f"@.str.{idx}"

        glob_name = self._string_globals[expr.value]
        body = self._decode_string(expr.value)
        length = len(body) + 1

        # Get global pointer, then GEP to first char
        ptr_type = f"!cir.ptr<!cir.array<!s8i x {length}>>"
        elem_ptr = _cir_ptr_type(Type("char"))
        v = self._new_v(elem_ptr)
        self._emit(
            f"{v.ref} = cir.get_global {glob_name} : {ptr_type}"
        )
        # GEP to get char* — use get_member[0] on the array
        # Actually just return the global pointer; it'll be used as ptr to array
        # For simplicity, emit a cast
        cast_v = self._new_v(elem_ptr)
        self._emit(
            f"{cast_v.ref} = cir.cast array_to_ptrdecay {v.ref} : {ptr_type} -> {elem_ptr}"
        )
        return cast_v

    # ── identifier ───────────────────────────────────────────

    def _identifier(self, expr: Identifier) -> _V:
        name = expr.name
        assert isinstance(name, str)

        # Check local scope
        for scope in reversed(self._locals):
            if name in scope:
                addr = scope[name]
                val_type = self._type_map.require(expr)
                cir_type = _cir_type(val_type)
                v = self._new_v(cir_type)
                self._emit(
                    f"{v.ref} = cir.load {addr.ref} : {addr.cir_type}, {cir_type}"
                )
                return v

        # Check function locals (sema-level)
        if self._func_sym and name in self._func_sym.locals:
            sym = self._func_sym.locals[name]
            if isinstance(sym, VarSymbol):
                val_type = sym.type_
                cir_type = _cir_type(val_type)
                v = self._new_v(cir_type)
                ptr_type = _cir_ptr_type(val_type)
                gv = self._new_v(ptr_type)
                self._emit(
                    f"{gv.ref} = cir.get_global @{name} : {ptr_type}"
                )
                self._emit(
                    f"{v.ref} = cir.load {gv.ref} : {ptr_type}, {cir_type}"
                )
                return v

        # Global variable
        val_type = self._type_map.require(expr)
        cir_type = _cir_type(val_type)
        ptr_type = _cir_ptr_type(val_type)
        v = self._new_v(cir_type)
        gv = self._new_v(ptr_type)
        self._emit(f"{gv.ref} = cir.get_global @{name} : {ptr_type}")
        self._emit(f"{v.ref} = cir.load {gv.ref} : {ptr_type}, {cir_type}")
        return v

    def _lookup_local(self, name: str) -> _V | None:
        for scope in reversed(self._locals):
            if name in scope:
                return scope[name]
        return None

    # ── unary ────────────────────────────────────────────────

    def _unary(self, expr: UnaryExpr) -> _V:
        op = expr.op
        if op == "&":
            return self._addrof(expr)
        if op == "*":
            return self._deref(expr)
        operand = self._emit_expr(expr.operand)

        unop_map = {
            "+": "plus",
            "-": "minus",
            "~": "not",  # bitwise not
            "!": "not",  # logical not — CIR models as not on bool
        }
        cir_op = unop_map.get(op)
        if cir_op is None:
            raise cir_backend_error(
                self._result.filename,
                f"Unsupported unary operator: {op}",
            )

        # For !, we need to convert to bool first
        if op == "!":
            bool_type = "!cir.bool"
            cmp_v = self._new_v(bool_type)
            self._emit(
                f"{cmp_v.ref} = cir.cast bool_to_int {operand.ref} : "
                f"{operand.cir_type} -> {bool_type}"
            )
            operand = cmp_v

        result_type = self._type_map.require(expr)
        cir_type = _cir_type(result_type)
        v = self._new_v(cir_type)
        self._emit(
            f"{v.ref} = cir.unary({cir_op}, {operand.ref}) : {operand.cir_type}"
        )
        return v

    def _addrof(self, expr: UnaryExpr) -> _V:
        operand = expr.operand
        if isinstance(operand, Identifier):
            assert isinstance(operand.name, str)
            name = operand.name
            local = self._lookup_local(name)
            if local is not None:
                return local
            # Global
            val_type = self._type_map.require(expr)
            ptr_type = _cir_type(val_type)
            v = self._new_v(ptr_type)
            self._emit(f"{v.ref} = cir.get_global @{name} : {ptr_type}")
            return v
        if isinstance(operand, SubscriptExpr):
            return self._subscript_ptr(operand)
        if isinstance(operand, MemberExpr):
            return self._member_ptr(operand)
        if isinstance(operand, UnaryExpr) and operand.op == "*":
            return self._emit_expr(operand.operand)
        raise cir_backend_error(
            self._result.filename,
            f"Unsupported address-of: {type(operand).__name__}",
        )

    def _deref(self, expr: UnaryExpr) -> _V:
        ptr = self._emit_expr(expr.operand)
        val_type = self._type_map.require(expr)
        cir_type = _cir_type(val_type)
        v = self._new_v(cir_type)
        self._emit(f"{v.ref} = cir.load {ptr.ref} : {ptr.cir_type}, {cir_type}")
        return v

    # ── binary ───────────────────────────────────────────────

    def _binary(self, expr: BinaryExpr) -> _V:
        op = expr.op

        if op in {"&&", "||"}:
            return self._logical(expr)

        left = self._emit_expr(expr.left)
        right = self._emit_expr(expr.right)

        if op in {"==", "!=", "<", ">", "<=", ">="}:
            return self._compare(op, left, right)

        result_type = self._type_map.require(expr)
        cir_type = _cir_type(result_type)

        binop_map = {
            "+": "add",
            "-": "sub",
            "*": "mul",
            "/": "div",
            "%": "rem",
            "&": "and",
            "|": "or",
            "^": "xor",
            "<<": "shl",
            ">>": "shr",
        }
        cir_op = binop_map.get(op)
        if cir_op is None:
            raise cir_backend_error(
                self._result.filename,
                f"Unsupported binary operator: {op}",
            )

        v = self._new_v(cir_type)
        self._emit(
            f"{v.ref} = cir.binop({cir_op}, {left.ref}, {right.ref}) : {cir_type}"
        )
        return v

    def _compare(self, op: str, left: _V, right: _V) -> _V:
        cmp_map = {
            "==": "eq", "!=": "ne",
            "<": "lt", ">": "gt",
            "<=": "le", ">=": "ge",
        }
        cir_cond = cmp_map[op]
        bool_type = "!cir.bool"
        v = self._new_v(bool_type)
        self._emit(
            f"{v.ref} = cir.cmp({cir_cond}, {left.ref}, {right.ref}) : {left.cir_type}"
        )
        # cir.cmp returns !cir.bool — used directly for branch conditions
        return v

    def _logical(self, expr: BinaryExpr) -> _V:
        # Short-circuit evaluation with alloca to store result
        result_type = self._type_map.require(expr)
        cir_type = _cir_type(result_type)
        alloca = self._new_v(_cir_ptr_type(result_type))
        self._emit(f"{alloca.ref} = cir.alloca {cir_type}, {alloca.cir_type}, [\"log.res\"]")

        eval_lbl = self._new_label("log_eval")
        end_lbl = self._new_label("log_end")

        left = self._emit_expr(expr.left)

        if expr.op == "&&":
            short_val = "0"
            short_lbl = end_lbl
        else:
            short_val = "1"
            short_lbl = end_lbl

        # Branch: if left is sufficient, skip right
        self._term(f"cir.brcond {left.ref} ^{eval_lbl}, ^{short_lbl}")

        self._emit_label(short_lbl)
        short_v = self._new_v(cir_type)
        self._emit(f"{short_v.ref} = cir.const #cir.int<{short_val}> : {cir_type}")
        self._emit(f"cir.store {short_v.ref}, {alloca.ref} : {cir_type}, {alloca.cir_type}")
        self._term(f"cir.br ^{end_lbl}")

        self._emit_label(eval_lbl)
        right = self._emit_expr(expr.right)
        self._emit(f"cir.store {right.ref}, {alloca.ref} : {cir_type}, {alloca.cir_type}")
        self._term(f"cir.br ^{end_lbl}")

        self._emit_label(end_lbl)
        v = self._new_v(cir_type)
        self._emit(f"{v.ref} = cir.load {alloca.ref} : {alloca.cir_type}, {cir_type}")
        return v

    # ── assign ───────────────────────────────────────────────

    def _assign(self, expr: AssignExpr) -> _V:
        op = expr.op
        target = expr.target
        val = self._emit_expr(expr.value)

        if isinstance(target, Identifier):
            assert isinstance(target.name, str)
            addr = self._lookup_local(target.name)
            if addr is None:
                # Global
                self._emit(
                    f"cir.store {val.ref}, @{target.name} : "
                    f"{val.cir_type}, {_cir_ptr_type(self._type_map.require(target))}"
                )
                return val
            if op == "=":
                self._emit(
                    f"cir.store {val.ref}, {addr.ref} : "
                    f"{val.cir_type}, {addr.cir_type}"
                )
                return val
            # Compound: load, compute, store
            return self._compound_assign(op, addr, val, target)

        if isinstance(target, UnaryExpr) and target.op == "*":
            ptr = self._emit_expr(target.operand)
            if op == "=":
                self._emit(
                    f"cir.store {val.ref}, {ptr.ref} : "
                    f"{val.cir_type}, {ptr.cir_type}"
                )
                return val
            return self._compound_assign(op, ptr, val, target)

        if isinstance(target, SubscriptExpr):
            ptr = self._subscript_ptr(target)
            if op == "=":
                self._emit(
                    f"cir.store {val.ref}, {ptr.ref} : "
                    f"{val.cir_type}, {ptr.cir_type}"
                )
                return val
            return self._compound_assign(op, ptr, val, target)

        if isinstance(target, MemberExpr):
            ptr = self._member_ptr(target)
            if op == "=":
                self._emit(
                    f"cir.store {val.ref}, {ptr.ref} : "
                    f"{val.cir_type}, {ptr.cir_type}"
                )
                return val
            return self._compound_assign(op, ptr, val, target)

        raise cir_backend_error(
            self._result.filename,
            f"Unsupported assignment target: {type(target).__name__}",
        )

    def _compound_assign(self, op: str, addr: _V, val: _V, target: Expr) -> _V:
        target_type = self._type_map.require(target)
        cir_type = _cir_type(target_type)
        old = self._new_v(cir_type)
        self._emit(f"{old.ref} = cir.load {addr.ref} : {addr.cir_type}, {cir_type}")

        binop_map = {
            "+=": "add", "-=": "sub", "*=": "mul", "/=": "div", "%=": "rem",
            "&=": "and", "|=": "or", "^=": "xor",
            "<<=": "shl", ">>=": "shr",
        }
        cir_op = binop_map.get(op)
        if cir_op is None:
            raise cir_backend_error(self._result.filename, f"Unsupported compound: {op}")

        result = self._new_v(cir_type)
        self._emit(
            f"{result.ref} = cir.binop({cir_op}, {old.ref}, {val.ref}) : {cir_type}"
        )
        self._emit(
            f"cir.store {result.ref}, {addr.ref} : {cir_type}, {addr.cir_type}"
        )
        return result

    # ── update ───────────────────────────────────────────────

    def _update(self, expr: UpdateExpr) -> _V:
        direc = "inc" if expr.op == "++" else "dec"
        target = expr.operand

        if isinstance(target, Identifier):
            assert isinstance(target.name, str)
            addr = self._lookup_local(target.name)
            if addr is None:
                raise cir_backend_error(
                    self._result.filename,
                    "Update on global not yet supported",
                )
            target_type = self._type_map.require(target)
            cir_type = _cir_type(target_type)

            old = self._new_v(cir_type)
            self._emit(f"{old.ref} = cir.load {addr.ref} : {addr.cir_type}, {cir_type}")
            new_v = self._new_v(cir_type)
            self._emit(f"{new_v.ref} = cir.unary({direc}, {old.ref}) : {cir_type}")
            self._emit(f"cir.store {new_v.ref}, {addr.ref} : {cir_type}, {addr.cir_type}")
            return old if expr.is_postfix else new_v

        raise cir_backend_error(
            self._result.filename,
            f"Unsupported update target: {type(target).__name__}",
        )

    # ── call ─────────────────────────────────────────────────

    def _call(self, expr: CallExpr) -> _V:
        result_type = self._type_map.require(expr)
        cir_ret = _cir_type(result_type)

        # Evaluate all arguments once
        arg_vals = [self._emit_expr(a) for a in expr.args]
        arg_str = ", ".join(f"{v.ref}" for v in arg_vals)
        arg_type_str = ", ".join(f"{v.cir_type}" for v in arg_vals)

        if isinstance(expr.callee, Identifier):
            callee_name = expr.callee.name
            assert isinstance(callee_name, str)

            if callee_name in {"__builtin_unreachable", "__builtin_expect",
                               "__builtin_constant_p"}:
                return self._builtin(callee_name, expr, cir_ret)

            if cir_ret == "!cir.void":
                self._emit(
                    f"cir.call @{callee_name}({arg_str}) : "
                    f"({arg_type_str}) -> ()"
                )
                return _V("", "!cir.void")
            v = self._new_v(cir_ret)
            self._emit(
                f"{v.ref} = cir.call @{callee_name}({arg_str}) : "
                f"({arg_type_str}) -> {cir_ret}"
            )
            return v

        raise cir_backend_error(
            self._result.filename,
            "Indirect calls not yet supported",
        )

    def _builtin(self, name: str, expr: CallExpr, cir_ret: str) -> _V:
        if name == "__builtin_unreachable":
            self._term("cir.unreachable")
            return _V("", "!cir.void")
        if name == "__builtin_expect":
            return self._emit_expr(expr.args[0])
        if name == "__builtin_constant_p":
            v = self._new_v(cir_ret)
            self._emit(f"{v.ref} = cir.const #cir.int<0> : {cir_ret}")
            return v
        raise cir_backend_error(
            self._result.filename, f"Unsupported builtin: {name}"
        )

    # ── cast ─────────────────────────────────────────────────

    def _cast(self, expr: CastExpr) -> _V:
        operand = self._emit_expr(expr.expr)
        result_type = self._type_map.require(expr)
        cir_to = _cir_type(result_type)

        if operand.cir_type == cir_to:
            return operand

        # Determine cast kind
        from_t = operand.cir_type
        to_t = cir_to

        is_ptr_from = "ptr" in from_t
        is_ptr_to = "ptr" in to_t
        is_float_from = "float" in from_t or "double" in from_t
        is_float_to = "float" in to_t or "double" in to_t
        is_bool_to = to_t == "!cir.bool"
        is_bool_from = from_t == "!cir.bool"

        if is_ptr_from and is_ptr_to:
            kind = "bitcast"
        elif is_ptr_from and not is_ptr_to:
            kind = "ptr_to_int"
        elif not is_ptr_from and is_ptr_to:
            kind = "int_to_ptr"
        elif is_float_from and is_float_to:
            kind = "floating"
        elif is_float_from and not is_float_to:
            kind = "float_to_int"
        elif not is_float_from and is_float_to:
            kind = "int_to_float"
        elif is_bool_to:
            kind = "int_to_bool"
        elif is_bool_from:
            kind = "bool_to_int"
        else:
            kind = "integral"

        v = self._new_v(cir_to)
        self._emit(
            f"{v.ref} = cir.cast({kind}, {operand.ref}) : "
            f"{from_t} -> {to_t}"
        )
        return v

    # ── subscript ────────────────────────────────────────────

    def _subscript(self, expr: SubscriptExpr) -> _V:
        ptr = self._subscript_ptr(expr)
        val_type = self._type_map.require(expr)
        cir_type = _cir_type(val_type)
        v = self._new_v(cir_type)
        self._emit(f"{v.ref} = cir.load {ptr.ref} : {ptr.cir_type}, {cir_type}")
        return v

    def _subscript_ptr(self, expr: SubscriptExpr) -> _V:
        base = self._emit_expr(expr.base)
        index = self._emit_expr(expr.index)
        elem_type = self._type_map.require(expr)
        cir_elem = _cir_type(elem_type)
        ptr_type = _cir_ptr_type(elem_type)
        v = self._new_v(ptr_type)
        self._emit(
            f"{v.ref} = cir.ptr_stride({base.ref} : {base.cir_type}, "
            f"{index.ref} : {index.cir_type}), {cir_elem}"
        )
        return v

    # ── member ────────────────────────────────────────────────

    def _member(self, expr: MemberExpr) -> _V:
        ptr = self._member_ptr(expr)
        val_type = self._type_map.require(expr)
        cir_type = _cir_type(val_type)
        v = self._new_v(cir_type)
        self._emit(f"{v.ref} = cir.load {ptr.ref} : {ptr.cir_type}, {cir_type}")
        return v

    def _member_ptr(self, expr: MemberExpr) -> _V:
        base = self._emit_expr(expr.base)
        base_type = self._type_map.require(expr.base)

        if expr.through_pointer:
            pointee = base_type.pointee()
            if pointee is None:
                raise cir_backend_error(
                    self._result.filename,
                    "Cannot dereference non-pointer in member access",
                )
            struct_type = pointee
            struct_ptr = base
        else:
            struct_type = base_type
            # Need to take address of base
            struct_ptr_type = _cir_ptr_type(struct_type)
            struct_ptr = self._new_v(struct_ptr_type)
            # base is a value, need to alloca + store to get pointer
            tmp = self._new_v(struct_ptr_type)
            self._emit(
                f"{tmp.ref} = cir.alloca {_cir_type(struct_type)}, "
                f"{struct_ptr_type}, [\"member.tmp\"]"
            )
            self._emit(
                f"cir.store {base.ref}, {tmp.ref} : "
                f"{_cir_type(struct_type)}, {struct_ptr_type}"
            )
            struct_ptr = tmp

        record_name = struct_type.name
        field_idx = self._field_index(record_name, expr.member)
        struct_cir_name = self._struct_cir_type(record_name)
        struct_cir_type = f"!{struct_cir_name}"

        val_type = self._type_map.require(expr)
        cir_result_type = _cir_ptr_type(val_type)
        v = self._new_v(cir_result_type)
        self._emit(
            f"{v.ref} = cir.get_member {struct_ptr.ref}[{field_idx}] "
            f"{{name = \"{expr.member}\"}} : "
            f"({struct_ptr.cir_type}) -> {cir_result_type}"
        )
        return v

    # ── ternary ──────────────────────────────────────────────

    def _ternary(self, expr: ConditionalExpr) -> _V:
        cond = self._emit_expr(expr.condition)
        result_type = self._type_map.require(expr)
        cir_type = _cir_type(result_type)

        v = self._new_v(cir_type)
        self._emit(f"{v.ref} = cir.ternary({cond.ref}, true {{")
        then_val = self._emit_expr(expr.then_expr)
        self._emit(f"cir.yield {then_val.ref} : {cir_type}")
        self._emit("}, false {")
        else_val = self._emit_expr(expr.else_expr)
        self._emit(f"cir.yield {else_val.ref} : {cir_type}")
        self._emit(f"}}) : ({cond.cir_type}) -> {cir_type}")
        return v

    # ── comma ────────────────────────────────────────────────

    def _comma(self, expr: CommaExpr) -> _V:
        self._emit_expr(expr.left)
        return self._emit_expr(expr.right)

    # ── statement expression (GNU) ───────────────────────────

    def _stmt_expr(self, expr: StatementExpr) -> _V:
        """Emit GNU statement expression ({ stmt; stmt; expr; })."""
        # Push scope for locals declared inside this expression
        self._locals.append({})
        # Emit allocas for locals declared in the statement expr body
        allocas = self._collect_allocas(expr.body)
        for vname, vtype in allocas:
            if vname in self._locals[-1]:
                continue
            cir_ptype = _cir_type(vtype)
            cir_ptr = _cir_ptr_type(vtype)
            alloca = self._new_v(cir_ptr)
            self._emit(
                f"{alloca.ref} = cir.alloca {cir_ptype}, "
                f"{cir_ptr}, [\"{vname}\", init]"
            )
            self._locals[-1][vname] = alloca

        stmts = expr.body.statements
        if not stmts:
            self._locals.pop()
            v = self._new_v("!s32i")
            self._emit(f"{v.ref} = cir.const #cir.int<0> : !s32i")
            return v
        for s in stmts[:-1]:
            self._emit_stmt(s)
        last = stmts[-1]
        if isinstance(last, ExprStmt):
            result = self._emit_expr(last.expr)
        else:
            self._emit_stmt(last)
            result = self._new_v("!s32i")
            self._emit(f"{result.ref} = cir.const #cir.int<0> : !s32i")
        self._locals.pop()
        return result

    # ── compound literal ─────────────────────────────────────

    def _compound_literal(self, expr: CompoundLiteralExpr) -> _V:
        """Emit compound literal (Type){init}."""
        result_type = self._type_map.require(expr)
        cir_type = _cir_type(result_type)
        ptr_type = _cir_ptr_type(result_type)
        tmp = self._new_v(ptr_type)
        self._emit(f"{tmp.ref} = cir.alloca {cir_type}, {ptr_type}, [\"compound.literal\"]")
        if isinstance(expr.initializer, InitList):
            self._emit_init_list(tmp, result_type, expr.initializer)
        else:
            val = self._emit_expr(expr.initializer)
            self._emit(
                f"cir.store {val.ref}, {tmp.ref} : {cir_type}, {ptr_type}"
            )
        # Return the pointer (compound literals decay to pointer in C)
        return tmp

    def _emit_init_list(self, dest: _V, dest_type: Type, init_list: InitList) -> None:
        cir_type = _cir_type(dest_type)
        for i, item in enumerate(init_list.items):
            val = self._emit_expr(item.initializer)
            if item.designators:
                # For now, skip designated initializers — emit field-by-field store
                # Get member pointer for the designator and store to it
                raise cir_backend_error(
                    self._result.filename,
                    "Designated initializers not yet supported",
                )
            # Non-designated: scalar init
            self._emit(
                f"cir.store {val.ref}, {dest.ref} : {cir_type}, {cir_type}"
            )

    # ── sizeof / alignof ─────────────────────────────────────

    def _size_align(self, expr: SizeofExpr | AlignofExpr, which: str) -> _V:
        result_type = self._type_map.require(expr)
        cir_type = _cir_type(result_type)
        size = self._calc_size(result_type)
        v = self._new_v(cir_type)
        self._emit(f"{v.ref} = cir.const #cir.int<{size}> : {cir_type}")
        return v

    # ── helpers ──────────────────────────────────────────────

    def _resolve_type(self, type_spec: TypeSpec) -> Type:
        return Type(
            type_spec.name,
            declarator_ops=type_spec.declarator_ops,
            qualifiers=type_spec.qualifiers,
        )

    def _eval_init_val(self, init: Expr, var_type: Type) -> str:
        if isinstance(init, IntLiteral):
            return f"#cir.int<{int(init.value)}>"
        if isinstance(init, CharLiteral):
            return f"#cir.int<{ord(init.value)}>"
        if isinstance(init, FloatLiteral):
            val = float(init.value)
            if "float" in _cir_type(var_type) and "double" not in _cir_type(var_type):
                bits = struct.pack("!f", val)
                raw = struct.unpack("!I", bits)[0]
                return f"#cir.fp<0x{raw:08X}>"
            bits = struct.pack("!d", val)
            raw = struct.unpack("!Q", bits)[0]
            return f"#cir.fp<0x{raw:016X}>"
        return "#cir.zero"

    def _decode_string(self, s: str) -> str:
        result = []
        i = 0
        while i < len(s):
            if s[i] == "\\" and i + 1 < len(s):
                ch = s[i + 1]
                if ch == "n": result.append("\n")
                elif ch == "t": result.append("\t")
                elif ch == "r": result.append("\r")
                elif ch == "0": result.append("\0")
                elif ch == "\\": result.append("\\")
                elif ch == "\"": result.append("\"")
                else: result.append(s[i + 1])
                i += 2
            else:
                result.append(s[i])
                i += 1
        return "".join(result)

    def _escape_string(self, s: str) -> str:
        result = []
        for ch in s:
            if ch == "\\": result.append("\\\\")
            elif ch == "\"": result.append("\\\"")
            elif ch == "\n": result.append("\\0A")
            elif ch == "\t": result.append("\\09")
            elif ch == "\r": result.append("\\0D")
            elif ch == "\0": result.append("\\00")
            elif ord(ch) < 32:
                result.append(f"\\{ord(ch):02X}")
            else:
                result.append(ch)
        return "".join(result)

    def _calc_size(self, t: Type) -> int:
        sizes = {
            "int": 4, "unsigned int": 4,
            "long": 8, "unsigned long": 8,
            "long long": 8, "unsigned long long": 8,
            "char": 1, "unsigned char": 1, "signed char": 1, "_Bool": 1,
            "short": 2, "unsigned short": 2,
            "float": 4, "double": 8, "long double": 16,
            "void": 0,
        }
        base = sizes.get(t.name, 4)
        for kind, value in reversed(t.declarator_ops):
            if kind == "ptr":
                return 8
            if kind == "arr":
                if isinstance(value, int):
                    return value * self._calc_size(
                        Type(t.name, declarator_ops=t.declarator_ops[:-1])
                    )
                return 0
        return base


@dataclass
class _LoopCtx:
    continue_label: str
    break_label: str
