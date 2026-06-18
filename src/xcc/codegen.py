"""LLVM IR code generator using libLLVM-C.

Zero runtime dependencies. Uses the system libLLVM.dylib through
xcc.llvm_api.

Consumes FrontendResult (AST + TypeMap + SemaUnit), produces
LLVM IR text. Driver pipes through llc for .o files.
"""

from dataclasses import dataclass

from xcc.ast import (
    AlignofExpr,
    ArrayDecl,
    AssignExpr,
    BinaryExpr,
    BreakStmt,
    BuiltinOffsetofExpr,
    BuiltinVaArgExpr,
    CallExpr,
    CaseStmt,
    CastExpr,
    CharLiteral,
    CommaExpr,
    CompoundLiteralExpr,
    CompoundStmt,
    ConditionalExpr,
    ContinueStmt,
    DeclaratorOp,
    DeclGroupStmt,
    DeclStmt,
    DefaultStmt,
    DesignatorRange,
    DoWhileStmt,
    Expr,
    ExprStmt,
    FloatLiteral,
    ForStmt,
    FunctionDef,
    GotoStmt,
    Identifier,
    IfStmt,
    InitItem,
    InitList,
    IntLiteral,
    LabelStmt,
    MemberExpr,
    NullStmt,
    ReturnStmt,
    SizeofExpr,
    StatementExpr,
    StaticAssertDecl,
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
from xcc.llvm_api import (
    ATOMIC_ORDER_SEQ_CST,
    ATOMIC_RMW_ADD,
    ATOMIC_RMW_AND,
    ATOMIC_RMW_NAND,
    ATOMIC_RMW_OR,
    ATOMIC_RMW_SUB,
    ATOMIC_RMW_XCHG,
    ATOMIC_RMW_XOR,
    LLVM_EXTERNAL_LINKAGE,
    LLVM_INTERNAL_LINKAGE,
    LLVMTypeKind,
    llvm,
    optional_zero_ptr_array,
    ptr_array,
    zero_ptr_array,
)
from xcc.sema.constants import char_literal_body, decode_escaped_units
from xcc.sema.symbols import EnumConstSymbol, FunctionSymbol, RecordMemberInfo, VarSymbol
from xcc.sema.type_helpers import (
    is_integer_type,
    is_signed_integer_type,
    usual_arithmetic_conversion,
)
from xcc.types import INT, FunctionParams, Type, TypeOp

_CG_UNSUPPORTED = "XCC-CG-0005"


def llvm_backend_error(filename: str, message: str) -> CodegenError:
    return CodegenError(Diagnostic("codegen", filename, message, code=_CG_UNSUPPORTED))


# ── code generator ──────────────────────────────────────────

_BASE_SIZES = {
    "int": 4,
    "unsigned int": 4,
    "long": 8,
    "unsigned long": 8,
    "long long": 8,
    "unsigned long long": 8,
    "char": 1,
    "unsigned char": 1,
    "signed char": 1,
    "_Bool": 1,
    "bool": 1,
    "short": 2,
    "unsigned short": 2,
    "float": 4,
    "double": 8,
    "long double": 16,
    "__builtin_va_list": 8,
    "void": 0,
}


@dataclass
class _LoopCtx:
    continue_block: int  # _LLVMBasicBlockRef
    break_block: int  # _LLVMBasicBlockRef


class _LLVMGen:
    def __init__(self, result: FrontendResult):
        self._result = result
        self._unit = result.unit
        self._type_map = result.sema.type_map
        self._sema = result.sema

        c = llvm()
        self._ctx = c.ContextCreate()
        self._mod = c.ModuleCreateWithName(result.filename.encode("utf-8"))
        c.SetTarget(self._mod, b"aarch64-apple-darwin")
        self._builder = c.CreateBuilder()
        self._str_constants: dict[str, int] = {}  # literal → _LLVMValueRef
        self._compound_literal_globals: dict[int, int] = {}
        self._func_types: dict[str, int] = {}  # func name → _LLVMTypeRef
        self._func_param_types: dict[str, list[int]] = {}  # func name → list of param _LLVMTypeRef

        # Struct types: record_name → _LLVMTypeRef
        self._struct_types: dict[str, int] = {}
        self._static_local_counter = 0
        self._static_local_globals: dict[int, int] = {}
        self._static_local_global_values: set[int] = set()

        # Function state
        self._func: int = 0  # _LLVMValueRef
        self._func_sym: FunctionSymbol | None = None
        self._locals: list[dict[str, int]] = []
        self._label_blocks: dict[str, int] = {}
        self._loop_stack: list[_LoopCtx] = []
        self._break_stack: list[int] = []
        # (switch_inst, end_block, default_block, default_handled, cond_type)
        self._switch_info: list[tuple[int, int, int | None, bool, int]] = []
        self._entry_block: int = 0

    # ── helpers ──────────────────────────────────────────────

    def _type_to_llvm(self, t: Type) -> int:
        """Map XCC Type to LLVMTypeRef."""
        c = llvm()
        base_name = t.name

        result: int | None = None
        for kind, value in reversed(t.declarator_ops):
            if kind == "ptr":
                result = c.PointerType(c.Int8Type(), 0)
            elif kind == "arr":
                if result is None:
                    result = self._base_type(base_name)
                if isinstance(value, int):
                    result = c.ArrayType(result, max(value, 0))
                else:
                    result = c.ArrayType(result, 0)
            elif kind == "fn":
                if result is None:
                    result = self._base_type(base_name)
                params: tuple[Type, ...] = ()
                is_var = False
                if isinstance(value, tuple):
                    params = value[0] if value[0] else ()
                    is_var = value[1]
                # Filter out void params
                real_params = [pt for pt in params if pt.name != "void" or pt.declarator_ops]
                n = len(real_params)
                if n == 0:
                    param_arr = None
                else:
                    param_arr = zero_ptr_array(n)
                    for i, pt in enumerate(real_params):
                        param_arr[i] = self._type_to_llvm(pt)
                result = c.FunctionType(result, param_arr, n, is_var)
        if result is None:
            result = self._base_type(base_name)
        # C11 6.3.2.1p4: function designator → pointer-to-function.
        if c.GetTypeKind(result) == LLVMTypeKind.FUNCTION:
            result = c.PointerType(c.Int8Type(), 0)
        return result

    def _base_type(self, name: str) -> int:
        c = llvm()
        if name.startswith(("struct ", "union ")):
            return self._struct_type(name)
        if name == "__builtin_va_list":
            return c.PointerType(c.Int8Type(), 0)
        m = {
            "int": c.Int32Type,
            "unsigned int": c.Int32Type,
            "long": c.Int64Type,
            "unsigned long": c.Int64Type,
            "long long": c.Int64Type,
            "unsigned long long": c.Int64Type,
            "char": c.Int8Type,
            "unsigned char": c.Int8Type,
            "signed char": c.Int8Type,
            "_Bool": c.Int1Type,
            "bool": c.Int1Type,
            "short": c.Int16Type,
            "unsigned short": c.Int16Type,
            "float": c.FloatType,
            "double": c.DoubleType,
            "long double": c.DoubleType,
            "void": c.VoidType,
        }
        fn = m.get(name)
        if fn is None:
            return c.Int32Type()
        return fn()

    @staticmethod
    def _is_unsigned_integer_c_type(type_: Type | None) -> bool:
        if type_ is None:
            return False
        return is_integer_type(type_) and not is_signed_integer_type(type_)

    @staticmethod
    def _common_integer_c_type(left: Type | None, right: Type | None) -> Type | None:
        if left is None or right is None:
            return None
        if not is_integer_type(left) or not is_integer_type(right):
            return None
        return usual_arithmetic_conversion(left, right)

    def _cast_integer_value(
        self,
        value: int,
        target_type: int,
        source_type: Type | None,
        name: bytes,
    ) -> int:
        c = llvm()
        source_type_ref = c.TypeOf(value)
        if source_type_ref == target_type:
            return value
        source_width = c.GetIntTypeWidth(source_type_ref)
        target_width = c.GetIntTypeWidth(target_type)
        if target_width == 1:
            return self._to_bool(value)
        if source_width > target_width:
            return c.BuildTrunc(self._builder, value, target_type, name)
        if source_width < target_width:
            if self._is_unsigned_integer_c_type(source_type):
                return c.BuildZExt(self._builder, value, target_type, name)
            return c.BuildSExt(self._builder, value, target_type, name)
        return value

    def _gep_index_value(
        self,
        value: int,
        source_type: Type | None,
        name: bytes,
    ) -> int:
        c = llvm()
        value_type = c.TypeOf(value)
        if c.GetTypeKind(value_type) != LLVMTypeKind.INTEGER:
            return value
        return self._cast_integer_value(value, c.Int64Type(), source_type, name)

    @staticmethod
    def _is_float_kind(kind: int) -> bool:
        return kind in (
            LLVMTypeKind.FLOAT,
            LLVMTypeKind.DOUBLE,
            LLVMTypeKind.HALF,
            LLVMTypeKind.BFLOAT,
            LLVMTypeKind.X86_FP80,
            LLVMTypeKind.FP128,
            LLVMTypeKind.PPC_FP128,
        )

    @staticmethod
    def _float_rank(kind: int) -> int:
        ranks = {
            LLVMTypeKind.HALF: 1,
            LLVMTypeKind.BFLOAT: 1,
            LLVMTypeKind.FLOAT: 2,
            LLVMTypeKind.DOUBLE: 3,
            LLVMTypeKind.X86_FP80: 4,
            LLVMTypeKind.FP128: 5,
            LLVMTypeKind.PPC_FP128: 5,
        }
        return ranks.get(kind, 0)

    def _struct_type(self, record_name: str) -> int:
        c = llvm()
        if record_name in self._struct_types:
            return self._struct_types[record_name]
        members = self._sema.record_definitions.get(record_name)
        if not members:
            st = c.StructType(None, 0, False)
            self._struct_types[record_name] = st
            return st
        if record_name.startswith("union "):
            storage_member = self._union_storage_member(members)
            storage_type = self._record_member_llvm_type(storage_member)
            storage_size = self._type_size(storage_member.type_)
            union_size = self._union_size(record_name)
            field_types: list[int] = [storage_type]
            padding = union_size - storage_size
            if padding > 0:
                field_types.append(c.ArrayType(c.Int8Type(), padding))
            member_types = zero_ptr_array(len(field_types))
            for i, field_type in enumerate(field_types):
                member_types[i] = field_type
            st = c.StructType(member_types, len(field_types), False)
            self._struct_types[record_name] = st
            return st
        member_types = zero_ptr_array(len(members))
        for i, m in enumerate(members):
            member_types[i] = self._record_member_llvm_type(m)
        st = c.StructType(member_types, len(members), False)
        self._struct_types[record_name] = st
        return st

    def _record_member_llvm_type(self, member: RecordMemberInfo) -> int:
        return self._record_field_llvm_type(member.type_)

    def _record_field_llvm_type(self, type_: Type) -> int:
        c = llvm()
        mt = self._type_to_llvm(type_)
        # In opaque-pointer mode, function-pointer members must be ptr
        # not ptr (void (...)).  Force all pointer-typed members to
        # opaque ptr(i8) to avoid typed-pointer IR in struct layouts.
        if c.GetTypeKind(mt) == LLVMTypeKind.POINTER:
            return c.PointerType(c.Int8Type(), 0)
        return mt

    def _field_index(self, record_name: str, member_name: str) -> int:
        members = self._sema.record_definitions.get(record_name)
        if not members:
            raise llvm_backend_error(self._result.filename, f"Unknown record: {record_name}")
        for i, m in enumerate(members):
            if m.name == member_name:
                return i
        raise llvm_backend_error(
            self._result.filename,
            f"Record '{record_name}' has no member '{member_name}'",
        )

    def _member_path(
        self,
        record_name: str,
        member_name: str,
    ) -> list[tuple[str, int, RecordMemberInfo]] | None:
        members = self._sema.record_definitions.get(record_name)
        if not members:
            return None
        for i, member in enumerate(members):
            if member.name == member_name:
                return [(record_name, i, member)]
            if (
                member.name is None
                and member.bit_width is None
                and not member.type_.declarator_ops
                and member.type_.name.startswith(("struct ", "union "))
            ):
                nested = self._member_path(member.type_.name, member_name)
                if nested is not None:
                    return [(record_name, i, member), *nested]
        return None

    def _ptr_type(self, t: Type) -> int:
        return llvm().PointerType(llvm().Int8Type(), 0)

    def _type_size(self, t: Type) -> int:
        if not t.declarator_ops:
            if t.name.startswith("struct "):
                return self._record_size(t.name)
            if t.name.startswith("union "):
                return self._union_size(t.name)
            return _BASE_SIZES.get(t.name, 4)
        for kind, value in t.declarator_ops:
            if kind == "ptr":
                return 8
            if kind == "arr":
                assert isinstance(value, int)
                elem_type = Type(t.name, declarator_ops=t.declarator_ops[1:])
                return max(value, 0) * self._type_size(elem_type)
        return _BASE_SIZES.get(t.name, 4)

    def _type_align(self, t: Type) -> int:
        if not t.declarator_ops:
            if t.name.startswith(("struct ", "union ")):
                members = self._sema.record_definitions.get(t.name)
                if not members:
                    return 1
                return max((self._type_align(member.type_) for member in members), default=1)
            return min(_BASE_SIZES.get(t.name, 4), 8)
        kind, _ = t.declarator_ops[0]
        if kind == "ptr":
            return 8
        if kind == "arr":
            elem_type = Type(t.name, declarator_ops=t.declarator_ops[1:])
            return self._type_align(elem_type)
        return 1

    def _member_align(self, member: RecordMemberInfo) -> int:
        member_align = self._type_align(member.type_)
        if member.alignment is not None and member.alignment > member_align:
            return member.alignment
        return member_align

    @staticmethod
    def _align_to(value: int, alignment: int) -> int:
        return ((value + alignment - 1) // alignment) * alignment

    def _record_size(self, record_name: str) -> int:
        members = self._sema.record_definitions.get(record_name)
        if not members:
            return 0
        offset = 0
        max_align = 1
        for member in members:
            member_align = self._type_align(member.type_)
            if member.alignment is not None and member.alignment > member_align:
                member_align = member.alignment
            max_align = max(max_align, member_align)
            offset = self._align_to(offset, member_align)
            offset += self._type_size(member.type_)
        return self._align_to(offset, max_align)

    def _union_size(self, record_name: str) -> int:
        members = self._sema.record_definitions.get(record_name)
        if not members:
            return 0
        size = max((self._type_size(member.type_) for member in members), default=0)
        align = max((self._member_align(member) for member in members), default=1)
        return self._align_to(size, align)

    def _union_storage_member(self, members: tuple[RecordMemberInfo, ...]) -> RecordMemberInfo:
        def key(member: RecordMemberInfo) -> tuple[int, int, int]:
            type_ = member.type_
            is_record = not type_.declarator_ops and type_.name.startswith(("struct ", "union "))
            return (self._type_size(type_), 1 if is_record else 0, self._member_align(member))

        return max(members, key=key)

    # ── module ───────────────────────────────────────────────

    def generate(self) -> str:
        self._emit_globals()
        self._emit_functions()
        c = llvm()
        ir = c.PrintModuleToString(self._mod)
        result = ir.decode("utf-8") if isinstance(ir, bytes) else str(ir)
        return result

    def _emit_globals(self) -> None:
        llvm()
        externals = self._unit.externals or [*self._unit.declarations, *self._unit.functions]
        for ext in externals:
            if isinstance(ext, FunctionDef):
                continue
            if isinstance(ext, DeclGroupStmt):
                for decl in ext.declarations:
                    if isinstance(decl, DeclStmt):
                        self._emit_global_var(decl)
            elif isinstance(ext, DeclStmt):
                self._emit_global_var(ext)

    def _emit_global_var(self, decl: DeclStmt) -> None:
        c = llvm()
        name = decl.name
        if name is None or decl.storage_class == "extern":
            return
        t = self._resolve_type(decl.type_spec)
        if self._is_function_designator_type(t):
            return
        if self._sema.file_scope is not None:
            symbol = self._sema.file_scope.lookup(name)
            if isinstance(symbol, VarSymbol):
                t = symbol.type_
        if t.is_array():
            array_length = t.declarator_ops[0][1]
            unspecified = (isinstance(array_length, int) and array_length <= 0) or (
                isinstance(array_length, ArrayDecl) and array_length.length is None
            )
            if unspecified and isinstance(decl.init, InitList):
                inferred = self._infer_array_init_length(decl.init)
                new_ops = (("arr", inferred),) + t.declarator_ops[1:]
                t = Type(t.name, declarator_ops=new_ops, qualifiers=t.qualifiers)
            if unspecified and isinstance(decl.init, StringLiteral) and self._is_char_array_type(t):
                inferred = len(self._string_literal_bytes(decl.init))
                new_ops = (("arr", inferred),) + t.declarator_ops[1:]
                t = Type(t.name, declarator_ops=new_ops, qualifiers=t.qualifiers)
        flexible_members: dict[int, Type] | None = None
        lt = self._type_to_llvm(t)
        if isinstance(decl.init, InitList):
            flexible_members = self._flexible_array_member_overrides(t, decl.init)
            if flexible_members:
                lt = self._struct_type_with_member_overrides(t.name, flexible_members)
        gv = c.GetNamedGlobal(self._mod, name.encode())
        if not gv:
            gv = c.AddGlobal(self._mod, lt, name.encode())
        if decl.storage_class == "static":
            c.SetLinkage(gv, LLVM_INTERNAL_LINKAGE)
        if decl.init:
            if flexible_members and isinstance(decl.init, InitList):
                init_value = self._eval_record_init(
                    decl.init,
                    t,
                    member_type_overrides=flexible_members,
                    record_lt=lt,
                )
            else:
                init_value = self._eval_init(decl.init, t)
            if init_value:
                c.SetInitializer(gv, init_value)
                return
        c.SetInitializer(gv, c.ConstNull(lt))

    def _emit_functions(self) -> None:
        for func in self._unit.functions:
            self._declare_func(func)
        for func in self._unit.functions:
            if func.body is not None:
                self._define_func(func)

    def _function_definition_is_internal(self, func: FunctionDef) -> bool:
        return func.storage_class == "static" or (func.body is not None and func.is_inline)

    def _function_param_types(self, func: FunctionDef) -> list[Type]:
        param_types: list[Type] = []
        for param in func.params:
            param_type = self._resolve_type(param.type_spec)
            if param_type.name == "void" and not param_type.declarator_ops:
                continue
            param_types.append(param_type.decay_parameter_type())
        return param_types

    def _declare_func(self, func: FunctionDef) -> None:
        c = llvm()
        func_sym = self._sema.functions.get(func.name)
        if func_sym is not None:
            ret_t = self._type_to_llvm(func_sym.return_type)
        else:
            ret_t = self._type_to_llvm(self._resolve_type(func.return_type))
        real_params = [
            self._type_to_llvm(param_type) for param_type in self._function_param_types(func)
        ]
        n = len(real_params)
        param_ts = zero_ptr_array(n)
        for i, lt in enumerate(real_params):
            param_ts[i] = lt
        fn_t = c.FunctionType(ret_t, param_ts, n, func.is_variadic)
        self._func_types[func.name] = fn_t  # save for later calls
        self._func_param_types[func.name] = [real_params[i] for i in range(n)]
        fn = c.GetNamedFunction(self._mod, func.name.encode())
        if not fn:
            fn = c.AddFunction(self._mod, func.name.encode(), fn_t)
        if self._function_definition_is_internal(func):
            c.SetLinkage(fn, LLVM_INTERNAL_LINKAGE)
        if func.body is None:
            c.SetLinkage(
                fn,
                LLVM_INTERNAL_LINKAGE if func.storage_class == "static" else LLVM_EXTERNAL_LINKAGE,
            )

    def _define_func(self, func: FunctionDef) -> None:
        c = llvm()
        func_sym = self._sema.functions.get(func.name)
        if func_sym is None:
            return
        self._func_sym = func_sym
        self._locals = [{}]
        self._label_blocks = {}
        self._loop_stack = []
        self._break_stack = []
        self._switch_info = []

        ret_t = self._type_to_llvm(func_sym.return_type)
        real_params = [
            self._type_to_llvm(param_type) for param_type in self._function_param_types(func)
        ]
        n = len(real_params)
        param_ts = zero_ptr_array(n)
        for i, lt in enumerate(real_params):
            param_ts[i] = lt
        fn_t = c.FunctionType(ret_t, param_ts, n, func.is_variadic)
        # Reuse existing declaration if present
        fn = c.GetNamedFunction(self._mod, func.name.encode())
        if not fn:
            fn = c.AddFunction(self._mod, func.name.encode(), fn_t)
        if self._function_definition_is_internal(func):
            c.SetLinkage(fn, LLVM_INTERNAL_LINKAGE)
        self._func = fn

        entry = c.AppendBasicBlock(fn, b"entry")
        self._entry_block = entry
        c.PositionBuilderAtEnd(self._builder, entry)

        # Alloca + store params
        param_index = 0
        for param in func.params:
            assert param.name
            pt = self._resolve_type(param.type_spec)
            if pt.name == "void" and not pt.declarator_ops:
                continue
            symbol = func_sym.locals.get(param.name)
            pt = symbol.type_ if isinstance(symbol, VarSymbol) else pt.decay_parameter_type()
            lt = self._type_to_llvm(pt)
            pv = c.GetParam(fn, param_index)
            param_index += 1
            alloca = c.BuildAlloca(self._builder, lt, f"{param.name}.addr".encode())
            c.BuildStore(self._builder, pv, alloca)
            self._locals[-1][param.name] = alloca

        # Pre-collect allocas
        assert func.body is not None
        allocas = self._collect_allocas(func.body)
        for vname, vtype in allocas:
            if vname in self._locals[-1]:
                continue
            lt = self._type_to_llvm(vtype)
            a = c.BuildAlloca(self._builder, lt, f"{vname}.addr".encode())
            self._locals[-1][vname] = a

        self._emit_stmt(func.body)

        if self._bb_needs_term():
            if func_sym.return_type.name == "void" and not func_sym.return_type.declarator_ops:
                c.BuildRetVoid(self._builder)
            elif c.GetTypeKind(ret_t) == LLVMTypeKind.POINTER:
                c.BuildRet(self._builder, c.ConstNull(ret_t))
            elif self._is_float_kind(c.GetTypeKind(ret_t)):
                c.BuildRet(self._builder, c.ConstReal(ret_t, 0.0))
            elif c.GetTypeKind(ret_t) != LLVMTypeKind.INTEGER:
                c.BuildRet(self._builder, c.ConstNull(ret_t))
            else:
                c.BuildRet(self._builder, c.ConstInt(ret_t, 0, False))

    def _build_call_args(self, expr: CallExpr) -> tuple[list[int], list[int], list[Type | None]]:
        """Evaluate call args, return (values, LLVM types, C types)."""
        vals = []
        types = []
        c_types = []
        for arg in expr.args:
            v = self._emit_expr(arg)
            vals.append(v)
            types.append(llvm().TypeOf(v))
            c_types.append(self._type_map.get(arg))
        return vals, types, c_types

    def _coerce_call_args(
        self,
        vals: list[int],
        callee_name: str,
        arg_c_types: list[Type | None] | None = None,
    ) -> list[int]:
        """Coerce argument values to match function parameter types."""
        param_types = self._func_param_types.get(callee_name)
        if not param_types:
            return vals
        c = llvm()
        result = []
        for i, v in enumerate(vals):
            if i < len(param_types):
                pt = param_types[i]
                vt = c.TypeOf(v)
                pk = c.GetTypeKind(pt)
                vk = c.GetTypeKind(vt)
                # Array decay for args
                if vk == LLVMTypeKind.ARRAY:
                    v = self._build_cast(v, c.PointerType(c.Int8Type(), 0))
                    vt = c.TypeOf(v)
                    vk = c.GetTypeKind(vt)
                if pk == LLVMTypeKind.INTEGER and vk == LLVMTypeKind.INTEGER:
                    source_type = None if arg_c_types is None else arg_c_types[i]
                    v = self._cast_integer_value(v, pt, source_type, b"arg.ext")
                elif pk == LLVMTypeKind.POINTER and vk == LLVMTypeKind.INTEGER:
                    v = c.BuildIntToPtr(self._builder, v, pt, b"arg.cast")
                elif pk == LLVMTypeKind.INTEGER and vk == LLVMTypeKind.POINTER:
                    v = c.BuildPtrToInt(self._builder, v, pt, b"arg.cast")
            result.append(v)
        return result

    # ── statement emission ───────────────────────────────────

    def _bb_needs_term(self, bb: int = 0) -> bool:
        """True if the given (or current) basic block has no terminator."""
        c = llvm()
        if not bb:
            bb = c.GetInsertBlock(self._builder)
            if not bb:
                return False
        term = c.GetBasicBlockTerminator(bb)
        return term is None or term == 0

    def _emit_stmt(self, stmt: Stmt) -> None:
        if isinstance(stmt, CompoundStmt):
            self._locals.append({})
            for s in stmt.statements:
                self._emit_stmt(s)
            self._locals.pop()
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
            self._ensure_decl_alloca(stmt)
            self._emit_decl_init(stmt)
        elif isinstance(stmt, DeclGroupStmt):
            for d in stmt.declarations:
                self._emit_stmt(d)
        elif isinstance(stmt, SwitchStmt):
            self._emit_switch(stmt)
        elif isinstance(stmt, CaseStmt):
            self._emit_case(stmt)
        elif isinstance(stmt, DefaultStmt):
            self._emit_default(stmt)
        elif isinstance(stmt, LabelStmt):
            self._emit_label(stmt)
        elif isinstance(stmt, GotoStmt):
            self._emit_goto(stmt)
        elif isinstance(stmt, (TypedefDecl, StaticAssertDecl)):
            pass

    def _emit_return(self, stmt: ReturnStmt) -> None:
        c = llvm()
        if stmt.value is None:
            c.BuildRetVoid(self._builder)
        elif (
            self._func_sym is not None
            and self._func_sym.return_type.name == "void"
            and not self._func_sym.return_type.declarator_ops
        ):
            self._emit_expr(stmt.value)
            c.BuildRetVoid(self._builder)
        else:
            v = self._emit_expr(stmt.value)
            ret_lt = self._type_to_llvm(self._func_sym.return_type if self._func_sym else INT)
            if c.TypeOf(v) != ret_lt:
                v = self._build_cast(v, ret_lt, self._type_map.get(stmt.value))
            c.BuildRet(self._builder, v)
        self._term = True

    def _emit_decl_init(self, stmt: DeclStmt) -> None:
        if stmt.storage_class == "static":
            return
        if stmt.name is None or stmt.init is None:
            return
        addr = self._lookup_local(stmt.name)
        if addr is None:
            return
        if isinstance(stmt.init, InitList):
            target_type = self._decl_type(stmt)
            if self._emit_init_list_to_addr(addr, target_type, stmt.init):
                return
            return
        c = llvm()
        target_type = self._decl_type(stmt)
        if isinstance(stmt.init, StringLiteral) and self._is_char_array_type(target_type):
            val = self._string_array_initializer(stmt.init, target_type)
            c.BuildStore(self._builder, val, addr)
            return
        val = self._emit_expr(stmt.init)
        target_lt = self._type_to_llvm(target_type)
        if c.TypeOf(val) != target_lt:
            val = self._build_cast(val, target_lt, self._type_map.get(stmt.init))
        c.BuildStore(self._builder, val, addr)

    def _emit_init_list_to_addr(self, addr: int, target_type: Type, init: InitList) -> bool:
        c = llvm()
        target_lt = self._type_to_llvm(target_type)
        c.BuildStore(self._builder, c.ConstNull(target_lt), addr)
        if target_type.is_array():
            return self._emit_array_init_list_to_addr(addr, target_type, init)
        if self._is_record_type(target_type):
            return self._emit_record_init_list_to_addr(addr, target_type, init)
        if len(init.items) == 1 and not init.items[0].designators:
            initializer = init.items[0].initializer
            if isinstance(initializer, InitList):
                return self._emit_init_list_to_addr(addr, target_type, initializer)
            val = self._emit_expr(initializer)
            if c.TypeOf(val) != target_lt:
                val = self._build_cast(val, target_lt, self._type_map.get(initializer))
            c.BuildStore(self._builder, val, addr)
            return True
        return False

    def _emit_array_init_list_to_addr(self, addr: int, target_type: Type, init: InitList) -> bool:
        elem_type = target_type.element_type()
        if elem_type is None:
            return False
        length_value = target_type.declarator_ops[0][1]
        if not isinstance(length_value, int):
            return False
        length = max(length_value, 0)
        next_index = 0
        for item in init.items:
            if item.designators:
                kind, value = item.designators[0]
                if kind != "index" or not isinstance(value, Expr):
                    return False
                index = self._eval_int_constant_value(value)
                if index is None:
                    return False
                if 0 <= index < length:
                    elem_ptr = self._array_element_ptr(addr, target_type, index)
                    self._emit_initializer_to_addr(
                        elem_ptr,
                        elem_type,
                        item.designators[1:],
                        item.initializer,
                    )
                next_index = index + 1
                continue
            if next_index >= length:
                continue
            elem_ptr = self._array_element_ptr(addr, target_type, next_index)
            self._emit_initializer_to_addr(elem_ptr, elem_type, (), item.initializer)
            next_index += 1
        return True

    def _emit_record_init_list_to_addr(self, addr: int, target_type: Type, init: InitList) -> bool:
        members = self._sema.record_definitions.get(target_type.name)
        if members is None:
            return False
        next_member = 0
        initialized_union = False
        is_union = target_type.name.startswith("union ")
        for item in init.items:
            if item.designators:
                kind, value = item.designators[0]
                if kind != "member" or not isinstance(value, str):
                    return False
                path = self._member_path(target_type.name, value)
                if path is None:
                    return False
                field_ptr = self._record_path_ptr(addr, path)
                self._emit_initializer_to_addr(
                    field_ptr,
                    path[-1][2].type_,
                    item.designators[1:],
                    item.initializer,
                )
                if is_union:
                    initialized_union = True
                else:
                    next_member = path[0][1] + 1
                continue
            if is_union:
                if initialized_union:
                    continue
                member_index = 0
                initialized_union = True
            else:
                if next_member >= len(members):
                    continue
                member_index = next_member
                next_member += 1
            member = members[member_index]
            field_ptr = self._record_path_ptr(addr, [(target_type.name, member_index, member)])
            self._emit_initializer_to_addr(field_ptr, member.type_, (), item.initializer)
        return True

    def _emit_initializer_to_addr(
        self,
        addr: int,
        target_type: Type,
        designators: tuple[tuple[str, Expr | str | DesignatorRange], ...],
        initializer: Expr | InitList,
    ) -> None:
        c = llvm()
        if designators:
            if target_type.is_array():
                kind, value = designators[0]
                if kind == "index" and isinstance(value, Expr):
                    index = self._eval_int_constant_value(value)
                    if index is not None:
                        elem_type = target_type.element_type()
                        if elem_type is not None:
                            elem_ptr = self._array_element_ptr(addr, target_type, index)
                            self._emit_initializer_to_addr(
                                elem_ptr,
                                elem_type,
                                designators[1:],
                                initializer,
                            )
                return
            if self._is_record_type(target_type):
                kind, value = designators[0]
                if kind == "member" and isinstance(value, str):
                    path = self._member_path(target_type.name, value)
                    if path is not None:
                        field_ptr = self._record_path_ptr(addr, path)
                        self._emit_initializer_to_addr(
                            field_ptr,
                            path[-1][2].type_,
                            designators[1:],
                            initializer,
                        )
                return
        if isinstance(initializer, InitList):
            self._emit_init_list_to_addr(addr, target_type, initializer)
            return
        if isinstance(initializer, StringLiteral) and self._is_char_array_type(target_type):
            val = self._string_array_initializer(initializer, target_type)
            c.BuildStore(self._builder, val, addr)
            return
        initializer_type = self._type_map.get(initializer)
        if (
            initializer_type is not None
            and initializer_type.name == target_type.name
            and initializer_type.declarator_ops == target_type.declarator_ops
        ):
            val = self._emit_expr(initializer)
            target_lt = self._type_to_llvm(target_type)
            if c.TypeOf(val) != target_lt:
                val = self._build_cast(val, target_lt, self._type_map.get(initializer))
            c.BuildStore(self._builder, val, addr)
            return
        if self._is_record_type(target_type):
            members = self._sema.record_definitions.get(target_type.name)
            if not members:
                return
            first = members[0]
            field_ptr = self._record_path_ptr(addr, [(target_type.name, 0, first)])
            self._emit_initializer_to_addr(field_ptr, first.type_, (), initializer)
            return
        val = self._emit_expr(initializer)
        target_lt = self._type_to_llvm(target_type)
        if c.TypeOf(val) != target_lt:
            val = self._build_cast(val, target_lt, self._type_map.get(initializer))
        c.BuildStore(self._builder, val, addr)

    def _array_element_ptr(self, addr: int, array_type: Type, index: int) -> int:
        c = llvm()
        zero = c.ConstInt(c.Int32Type(), 0, False)
        idx = c.ConstInt(c.Int32Type(), index, index < 0)
        indices = ptr_array([zero, idx])
        return c.BuildGEP2(
            self._builder,
            self._type_to_llvm(array_type),
            addr,
            indices,
            2,
            b"init.ptr",
        )

    def _record_path_ptr(
        self,
        addr: int,
        path: list[tuple[str, int, RecordMemberInfo]],
    ) -> int:
        c = llvm()
        zero = c.ConstInt(c.Int32Type(), 0, False)
        ptr = addr
        for step_record, field_idx, _member in path:
            if step_record.startswith("union "):
                continue
            field = c.ConstInt(c.Int32Type(), field_idx, False)
            indices = ptr_array([zero, field])
            ptr = c.BuildGEP2(
                self._builder,
                self._struct_type(step_record),
                ptr,
                indices,
                2,
                b"init.ptr",
            )
        return ptr

    def _ensure_decl_alloca(self, stmt: DeclStmt) -> None:
        if stmt.name is None or not self._locals:
            return
        if stmt.storage_class == "static":
            self._ensure_static_local(stmt)
            return
        if stmt.storage_class == "extern":
            return
        current_scope = self._locals[-1]
        if stmt.name in current_scope:
            return
        var_type = self._decl_type(stmt)
        lt = self._type_to_llvm(var_type)
        current_scope[stmt.name] = self._build_entry_alloca(lt, f"{stmt.name}.addr")

    def _ensure_static_local(self, stmt: DeclStmt) -> int | None:
        if stmt.name is None or not self._locals:
            return None
        current_scope = self._locals[-1]
        existing = current_scope.get(stmt.name)
        if existing is not None:
            return existing

        key = id(stmt)
        gv = self._static_local_globals.get(key)
        if gv is None:
            c = llvm()
            var_type = self._decl_type(stmt)
            lt = self._type_to_llvm(var_type)
            func_name = self._func_sym.name if self._func_sym is not None else "file"
            global_name = f".static.{func_name}.{stmt.name}.{self._static_local_counter}"
            self._static_local_counter += 1
            gv = c.AddGlobal(self._mod, lt, global_name.encode())
            c.SetLinkage(gv, LLVM_INTERNAL_LINKAGE)
            self._static_local_globals[key] = gv
            self._static_local_global_values.add(gv)
            current_scope[stmt.name] = gv

            init = self._eval_init(stmt.init, var_type) if stmt.init is not None else None
            c.SetInitializer(gv, init if init is not None else c.ConstNull(lt))
            return gv

        current_scope[stmt.name] = gv
        return gv

    def _build_entry_alloca(self, llvm_type: int, name: str) -> int:
        c = llvm()
        current_bb = c.GetInsertBlock(self._builder)
        entry_bb = self._entry_block or current_bb
        term = c.GetBasicBlockTerminator(entry_bb)
        if term:
            c.PositionBuilderBefore(self._builder, term)
        else:
            c.PositionBuilderAtEnd(self._builder, entry_bb)
        alloca = c.BuildAlloca(self._builder, llvm_type, name.encode())
        if current_bb:
            c.PositionBuilderAtEnd(self._builder, current_bb)
        return alloca

    def _decl_type(self, stmt: DeclStmt) -> Type:
        t = self._resolve_type(stmt.type_spec)
        if t.is_array():
            val = t.declarator_ops[0][1]
            unspecified = (isinstance(val, int) and val <= 0) or (
                isinstance(val, ArrayDecl) and val.length is None
            )
            if unspecified and isinstance(stmt.init, InitList):
                new_ops = (("arr", self._infer_array_init_length(stmt.init)),) + t.declarator_ops[
                    1:
                ]
                return Type(t.name, declarator_ops=new_ops, qualifiers=t.qualifiers)
            if unspecified and isinstance(stmt.init, StringLiteral) and self._is_char_array_type(t):
                new_ops = (("arr", len(self._string_literal_bytes(stmt.init))),) + t.declarator_ops[
                    1:
                ]
                return Type(t.name, declarator_ops=new_ops, qualifiers=t.qualifiers)
        return t

    # ── control flow ─────────────────────────────────────────

    def _emit_if(self, stmt: IfStmt) -> None:
        c = llvm()
        fn = self._func
        cond_val = self._emit_expr(stmt.condition)
        cond = self._to_bool(cond_val)

        then_bb = c.AppendBasicBlock(fn, b"if.then")
        else_bb = c.AppendBasicBlock(fn, b"if.else") if stmt.else_body else None
        merge_bb = c.AppendBasicBlock(fn, b"if.end")

        if else_bb:
            c.BuildCondBr(self._builder, cond, then_bb, else_bb)
        else:
            c.BuildCondBr(self._builder, cond, then_bb, merge_bb)

        c.PositionBuilderAtEnd(self._builder, then_bb)
        self._emit_stmt(stmt.then_body)
        if self._bb_needs_term():
            c.BuildBr(self._builder, merge_bb)

        if else_bb:
            c.PositionBuilderAtEnd(self._builder, else_bb)
            assert stmt.else_body is not None
            self._emit_stmt(stmt.else_body)
            if self._bb_needs_term():
                c.BuildBr(self._builder, merge_bb)

        c.PositionBuilderAtEnd(self._builder, merge_bb)

    def _emit_while(self, stmt: WhileStmt) -> None:
        c = llvm()
        fn = self._func
        cond_bb = c.AppendBasicBlock(fn, b"while.cond")
        body_bb = c.AppendBasicBlock(fn, b"while.body")
        end_bb = c.AppendBasicBlock(fn, b"while.end")

        c.BuildBr(self._builder, cond_bb)
        c.PositionBuilderAtEnd(self._builder, cond_bb)
        cond = self._to_bool(self._emit_expr(stmt.condition))
        c.BuildCondBr(self._builder, cond, body_bb, end_bb)

        c.PositionBuilderAtEnd(self._builder, body_bb)
        self._loop_stack.append(_LoopCtx(cond_bb, end_bb))
        self._break_stack.append(end_bb)
        try:
            self._emit_stmt(stmt.body)
        finally:
            self._break_stack.pop()
            self._loop_stack.pop()
        if self._bb_needs_term():
            c.BuildBr(self._builder, cond_bb)

        c.PositionBuilderAtEnd(self._builder, end_bb)

    def _emit_do_while(self, stmt: DoWhileStmt) -> None:
        c = llvm()
        fn = self._func
        body_bb = c.AppendBasicBlock(fn, b"do.body")
        cond_bb = c.AppendBasicBlock(fn, b"do.cond")
        end_bb = c.AppendBasicBlock(fn, b"do.end")

        c.BuildBr(self._builder, body_bb)
        c.PositionBuilderAtEnd(self._builder, body_bb)
        self._loop_stack.append(_LoopCtx(cond_bb, end_bb))
        self._break_stack.append(end_bb)
        try:
            self._emit_stmt(stmt.body)
        finally:
            self._break_stack.pop()
            self._loop_stack.pop()
        if self._bb_needs_term():
            c.BuildBr(self._builder, cond_bb)

        c.PositionBuilderAtEnd(self._builder, cond_bb)
        cond = self._to_bool(self._emit_expr(stmt.condition))
        c.BuildCondBr(self._builder, cond, body_bb, end_bb)

        c.PositionBuilderAtEnd(self._builder, end_bb)

    def _emit_for(self, stmt: ForStmt) -> None:
        c = llvm()
        fn = self._func
        self._locals.append({})
        try:
            if isinstance(stmt.init, Expr):
                self._emit_expr(stmt.init)
            elif stmt.init is not None:
                self._emit_stmt(stmt.init)

            cond_bb = c.AppendBasicBlock(fn, b"for.cond")
            body_bb = c.AppendBasicBlock(fn, b"for.body")
            step_bb = c.AppendBasicBlock(fn, b"for.step")
            end_bb = c.AppendBasicBlock(fn, b"for.end")

            c.BuildBr(self._builder, cond_bb)
            c.PositionBuilderAtEnd(self._builder, cond_bb)
            if stmt.condition:
                cond = self._to_bool(self._emit_expr(stmt.condition))
                c.BuildCondBr(self._builder, cond, body_bb, end_bb)
            else:
                c.BuildBr(self._builder, body_bb)

            c.PositionBuilderAtEnd(self._builder, body_bb)
            self._loop_stack.append(_LoopCtx(step_bb, end_bb))
            self._break_stack.append(end_bb)
            try:
                self._emit_stmt(stmt.body)
            finally:
                self._break_stack.pop()
                self._loop_stack.pop()
            if self._bb_needs_term():
                c.BuildBr(self._builder, step_bb)

            c.PositionBuilderAtEnd(self._builder, step_bb)
            if stmt.post:
                self._emit_expr(stmt.post)
            c.BuildBr(self._builder, cond_bb)

            c.PositionBuilderAtEnd(self._builder, end_bb)
        finally:
            self._locals.pop()

    def _emit_break(self) -> None:
        if not self._break_stack:
            raise llvm_backend_error(self._result.filename, "break not within loop or switch")
        llvm().BuildBr(self._builder, self._break_stack[-1])
        self._term = True

    def _emit_continue(self) -> None:
        if not self._loop_stack:
            raise llvm_backend_error(self._result.filename, "continue not within loop")
        llvm().BuildBr(self._builder, self._loop_stack[-1].continue_block)
        self._term = True

    def _label_block(self, name: str) -> int:
        block = self._label_blocks.get(name)
        if block is None:
            block = llvm().AppendBasicBlock(self._func, f"label.{name}".encode())
            self._label_blocks[name] = block
        return block

    def _emit_label(self, stmt: LabelStmt) -> None:
        c = llvm()
        block = self._label_block(stmt.name)
        current = c.GetInsertBlock(self._builder)
        if current and current != block and self._bb_needs_term(current):
            c.BuildBr(self._builder, block)
        c.PositionBuilderAtEnd(self._builder, block)
        self._emit_stmt(stmt.body)

    def _emit_goto(self, stmt: GotoStmt) -> None:
        c = llvm()
        block = self._label_block(stmt.label)
        if self._bb_needs_term():
            c.BuildBr(self._builder, block)
        continuation = c.AppendBasicBlock(self._func, b"goto.cont")
        c.PositionBuilderAtEnd(self._builder, continuation)

    def _emit_switch(self, stmt: SwitchStmt) -> None:
        c = llvm()
        fn = self._func
        cond = self._emit_expr(stmt.condition)
        end_bb = c.AppendBasicBlock(fn, b"switch.end")
        default_bb = c.AppendBasicBlock(fn, b"switch.default")

        cdt = c.TypeOf(cond)
        sw = c.BuildSwitch(self._builder, cond, default_bb, 0)
        self._switch_info.append((sw, end_bb, default_bb, False, cdt))
        self._break_stack.append(end_bb)

        try:
            self._emit_stmt(stmt.body)
        finally:
            self._break_stack.pop()

        if self._bb_needs_term():
            c.BuildBr(self._builder, end_bb)

        # If default block was never entered (no DefaultStmt), add terminator.
        _, _, _, default_handled, _ = self._switch_info[-1]
        if not default_handled:
            c.PositionBuilderAtEnd(self._builder, default_bb)
            if self._bb_needs_term(default_bb):
                c.BuildBr(self._builder, end_bb)
        c.PositionBuilderAtEnd(self._builder, end_bb)
        self._switch_info.pop()

    def _emit_case(self, stmt: CaseStmt) -> None:
        c = llvm()
        fn = self._func
        val = self._eval_case_val(stmt.value)
        case_bb = c.AppendBasicBlock(fn, b"switch.case")
        sw, end_bb, _, _, cond_t = self._switch_info[-1]
        c.AddCase(sw, c.ConstInt(cond_t, val, False), case_bb)
        current_bb = c.GetInsertBlock(self._builder)
        if current_bb and current_bb != case_bb and self._bb_needs_term(current_bb):
            c.BuildBr(self._builder, case_bb)
        c.PositionBuilderAtEnd(self._builder, case_bb)
        if stmt.body:
            self._emit_stmt(stmt.body)

    def _emit_default(self, stmt: DefaultStmt) -> None:
        sw, end_bb, default_bb, _, cond_t = self._switch_info[-1]
        self._switch_info[-1] = (sw, end_bb, default_bb, True, cond_t)
        c = llvm()
        current_bb = c.GetInsertBlock(self._builder)
        if current_bb and current_bb != default_bb and self._bb_needs_term(current_bb):
            c.BuildBr(self._builder, default_bb)
        c.PositionBuilderAtEnd(self._builder, default_bb)
        if stmt.body:
            self._emit_stmt(stmt.body)

    # ── expression emission ──────────────────────────────────

    def _emit_expr(self, expr: Expr) -> int:
        if isinstance(expr, IntLiteral):
            return self._int_literal(expr)
        if isinstance(expr, CharLiteral):
            return self._int_literal(expr)
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
            self._emit_expr(expr.left)
            return self._emit_expr(expr.right)
        if isinstance(expr, SizeofExpr):
            return self._size_const(expr)
        if isinstance(expr, AlignofExpr):
            return self._size_const(expr)
        if isinstance(expr, UpdateExpr):
            return self._update(expr)
        if isinstance(expr, StatementExpr):
            return self._stmt_expr(expr)
        if isinstance(expr, CompoundLiteralExpr):
            return self._compound_literal(expr)
        if isinstance(expr, BuiltinOffsetofExpr):
            return self._offsetof_expr(expr)
        if isinstance(expr, BuiltinVaArgExpr):
            return self._va_arg(expr)
        raise llvm_backend_error(
            self._result.filename,
            f"Unsupported expression: {type(expr).__name__}",
        )

    # ── literals ─────────────────────────────────────────────

    @staticmethod
    def _parse_int_value(lexeme: str) -> int:
        """Parse a C integer literal lexeme, stripping any suffix."""
        s = lexeme
        while s and s[-1] in "uUlL":
            s = s[:-1]
        if s.startswith(("0x", "0X")):
            return int(s, 16)
        if s.startswith(("0b", "0B")):
            return int(s, 2)
        if len(s) > 1 and s.startswith("0"):
            return int(s, 8)
        return int(s or "0", 10)

    def _int_literal(self, expr: IntLiteral | CharLiteral) -> int:
        c = llvm()
        val_type = self._type_map.get(expr)
        if val_type is None:
            val_type = INT
        lt = self._type_to_llvm(val_type)
        val = (
            self._char_value(expr.value)
            if isinstance(expr, CharLiteral)
            else self._parse_int_value(expr.value)
        )
        return c.ConstInt(lt, val, False)

    def _char_value(self, s: str) -> int:
        """Decode a C char literal, including multi-char (GNU extension)."""
        body = char_literal_body(s)
        units = decode_escaped_units(body) if body is not None else [ord(ch) for ch in s]
        if len(units) == 1:
            return units[0]
        val = 0
        for unit in units:
            val = (val << 8) | (unit & 0xFF)
        return val

    def _float_literal(self, expr: FloatLiteral) -> int:
        c = llvm()
        val_type = self._type_map.get(expr)
        lt = self._type_to_llvm(val_type) if val_type else c.DoubleType()
        v = expr.value
        if v and v[-1] in "fFlL":
            v = v[:-1]
        f = float.fromhex(v) if v.startswith(("0x", "0X")) else float(v)
        return c.ConstReal(lt, f)

    def _string_literal(self, expr: StringLiteral) -> int:
        c = llvm()
        if expr.value in self._str_constants:
            gv = self._str_constants[expr.value]
        else:
            data = self._string_literal_bytes(expr)
            lt = c.ArrayType(c.Int8Type(), len(data))
            init = c.ConstString(data, len(data), True)
            gv = c.AddGlobal(self._mod, lt, b".str")
            c.SetInitializer(gv, init)
            c.SetLinkage(gv, LLVM_INTERNAL_LINKAGE)
            self._str_constants[expr.value] = gv
        zero = c.ConstInt(c.Int64Type(), 0, False)
        idx = ptr_array([zero, zero])
        return c.BuildGEP2(self._builder, c.TypeOf(gv), gv, idx, 2, b"str.ptr")

    def _string_literal_bytes(self, expr: StringLiteral) -> bytes:
        raw = expr.value
        qpos = -1
        for i, ch in enumerate(raw):
            if ch in ('"', "'"):
                qpos = i
                break
        prefix = raw[:qpos] if qpos >= 0 else ""
        body = self._decode_string(raw[qpos + 1 : -1] if qpos >= 0 else raw)
        if prefix == "u":
            return self._encode_string_units(body, 2)
        if prefix in {"L", "U"}:
            return self._encode_string_units(body, 4)
        return body.encode() + b"\x00"

    @staticmethod
    def _encode_string_units(body: str, width: int) -> bytes:
        units = [ord(ch) for ch in body]
        units.append(0)
        return b"".join(unit.to_bytes(width, "little", signed=False) for unit in units)

    def _is_char_array_type(self, type_: Type) -> bool:
        if not type_.is_array():
            return False
        elem_type = type_.element_type()
        return (
            elem_type is not None
            and not elem_type.declarator_ops
            and elem_type.name in {"char", "unsigned char"}
        )

    def _string_array_initializer(self, expr: StringLiteral, target_type: Type) -> int:
        c = llvm()
        length = target_type.declarator_ops[0][1]
        assert isinstance(length, int)
        data = self._string_literal_bytes(expr)
        if len(data) < length:
            data += b"\x00" * (length - len(data))
        else:
            data = data[:length]
        return c.ConstString(data, length, True)

    # ── identifier ───────────────────────────────────────────

    def _identifier(self, expr: Identifier) -> int:
        c = llvm()
        name = expr.name
        assert isinstance(name, str)

        if name == "__func__" and self._func_sym is not None:
            return self._string_literal(StringLiteral(f'"{self._func_sym.name}"'))

        addr = self._lookup_local(name)
        if addr is not None:
            val_type = self._type_map.require(expr)
            if val_type.is_array():
                return addr
            lt = self._type_to_llvm(val_type)
            return c.BuildLoad2(self._builder, lt, addr, name.encode())

        # Check function locals (globals)
        if self._func_sym and name in self._func_sym.locals:
            sym = self._func_sym.locals[name]
            if isinstance(sym, EnumConstSymbol):
                return c.ConstInt(c.Int32Type(), sym.value, True)
            if isinstance(sym, VarSymbol):
                val_type = sym.type_
                lt = self._type_to_llvm(val_type)
                gv = self._global_var_ref(name, val_type)
                if val_type.is_array():
                    return gv
                return c.BuildLoad2(self._builder, lt, gv, name.encode())

        val_type = self._type_map.require(expr)
        if self._is_function_designator_type(val_type):
            return self._function_designator(name, val_type)
        if self._sema.file_scope is not None:
            file_symbol = self._sema.file_scope.lookup(name)
            if isinstance(file_symbol, EnumConstSymbol):
                return c.ConstInt(c.Int32Type(), file_symbol.value, True)
        lt = self._type_to_llvm(val_type)
        # Function type → reference the existing function declaration.
        if c.GetTypeKind(lt) == LLVMTypeKind.FUNCTION:
            fn = c.GetNamedFunction(self._mod, name.encode())
            if fn:
                return fn
            # Declare external function.
            fn = c.AddFunction(self._mod, name.encode(), lt)
            c.SetLinkage(fn, 0)
            return fn
        gv = c.GetNamedGlobal(self._mod, name.encode())
        if not gv:
            gv = self._global_var_ref(name, val_type)
        if val_type.is_array():
            return gv
        return c.BuildLoad2(self._builder, lt, gv, name.encode())

    @staticmethod
    def _is_function_designator_type(type_: Type) -> bool:
        return bool(type_.declarator_ops) and type_.declarator_ops[0][0] == "fn"

    def _function_designator(self, name: str, type_: Type) -> int:
        c = llvm()
        fn = c.GetNamedFunction(self._mod, name.encode())
        signature = type_.callable_signature()
        if signature is None:
            if fn:
                return fn
            return_type = INT
            params: FunctionParams = ((), False)
        else:
            return_type, params = signature
        ret_lt = self._type_to_llvm(return_type)
        parameter_types, is_variadic = params
        real_params = [
            self._type_to_llvm(param)
            for param in (parameter_types or ())
            if param.name != "void" or param.declarator_ops
        ]
        n = len(real_params)
        param_arr = optional_zero_ptr_array(n)
        if param_arr is not None:
            for i, param_type in enumerate(real_params):
                param_arr[i] = param_type
        fn_t = c.FunctionType(ret_lt, param_arr, n, is_variadic)
        self._func_types.setdefault(name, fn_t)
        self._func_param_types.setdefault(name, real_params)
        if fn:
            return fn
        fn = c.AddFunction(self._mod, name.encode(), fn_t)
        c.SetLinkage(fn, LLVM_EXTERNAL_LINKAGE)
        return fn

    def _global_var_ref(self, name: str, type_: Type) -> int:
        c = llvm()
        gv = c.GetNamedGlobal(self._mod, name.encode())
        if gv:
            return gv
        lt = self._type_to_llvm(type_)
        return c.AddGlobal(self._mod, lt, name.encode())

    def _pointer_arith_pointee(self, pointer_type: Type | None) -> Type | None:
        if pointer_type is None:
            return None
        if pointer_type.is_array():
            pointee = pointer_type.element_type()
            if pointee is None:
                return None
            return pointee
        pointee = pointer_type.pointee()
        if pointee is None:
            return None
        if pointee.name == "void" and not pointee.declarator_ops:
            return None
        if self._is_function_designator_type(pointee):
            return None
        return pointee

    def _pointer_arith_element_llvm_type(self, pointer_type: Type | None) -> int:
        pointee = self._pointer_arith_pointee(pointer_type)
        if pointee is None:
            return llvm().Int8Type()
        return self._type_to_llvm(pointee)

    def _pointer_arith_element_size(self, pointer_type: Type | None) -> int:
        pointee = self._pointer_arith_pointee(pointer_type)
        if pointee is None:
            return 1
        return max(self._type_size(pointee), 1)

    def _lookup_local(self, name: str) -> int | None:
        for scope in reversed(self._locals):
            if name in scope:
                return scope[name]
        return None

    # ── unary ────────────────────────────────────────────────

    def _unary(self, expr: UnaryExpr) -> int:
        c = llvm()
        op = expr.op
        if op == "&":
            return self._addrof(expr)
        if op == "*":
            return self._deref(expr)
        operand = self._emit_expr(expr.operand)
        if op == "+":
            return operand
        if op == "-":
            ot = c.TypeOf(operand)
            ok = c.GetTypeKind(ot)
            if self._is_float_kind(ok):
                return c.BuildFNeg(self._builder, operand, b"neg")
            if ok == LLVMTypeKind.POINTER:
                # ptr - ptr → i64, or use ptrtoint for -ptr
                op_i64 = c.BuildPtrToInt(self._builder, operand, c.Int64Type(), b"cast")
                return c.BuildSub(
                    self._builder,
                    c.ConstInt(c.Int64Type(), 0, False),
                    op_i64,
                    b"neg",
                )
            zero = c.ConstInt(ot, 0, False)
            return c.BuildSub(self._builder, zero, operand, b"neg")
        if op == "~":
            ot = c.TypeOf(operand)
            if c.GetTypeKind(ot) == LLVMTypeKind.POINTER:
                # Pointer ~: cast to i64 first, then xor.
                op_i64 = c.BuildPtrToInt(self._builder, operand, c.Int64Type(), b"cast")
                m1 = c.ConstInt(c.Int64Type(), -1, True)
                return c.BuildXor(self._builder, op_i64, m1, b"not")
            m1 = c.ConstInt(ot, -1, True)
            return c.BuildXor(self._builder, operand, m1, b"not")
        if op == "!":
            cond = self._to_bool(operand)
            return c.BuildZExt(
                self._builder,
                c.BuildXor(self._builder, cond, c.ConstInt(c.Int1Type(), 1, False), b"lnot"),
                c.Int32Type(),
                b"lnot.ext",
            )
        raise llvm_backend_error(self._result.filename, f"Unsupported unary: {op}")

    def _addrof(self, expr: UnaryExpr) -> int:
        operand = expr.operand
        if isinstance(operand, CompoundLiteralExpr):
            return self._compound_literal_addr(operand)
        if isinstance(operand, Identifier):
            name = operand.name
            assert isinstance(name, str)
            local = self._lookup_local(name)
            if local is not None:
                return local
            c = llvm()
            operand_type = self._type_map.get(operand) or self._lookup_symbol_type(name)
            if operand_type is not None:
                if self._is_function_designator_type(operand_type):
                    return self._function_designator(name, operand_type)
                return self._global_var_ref(name, operand_type)
            gv = c.GetNamedGlobal(self._mod, name.encode())
            if gv:
                return gv
            fn = c.GetNamedFunction(self._mod, name.encode())
            if fn:
                return fn
            # Last-resort undeclared extension path: keep old behavior for
            # sources that got past sema through a builtin fallback.
            fn_t = c.FunctionType(c.VoidType(), None, 0, True)
            return c.AddFunction(self._mod, name.encode(), fn_t)
        if isinstance(operand, SubscriptExpr):
            return self._subscript_ptr(operand)
        if isinstance(operand, MemberExpr):
            return self._member_ptr(operand)
        if isinstance(operand, UnaryExpr) and operand.op == "*":
            return self._emit_expr(operand.operand)
        raise llvm_backend_error(self._result.filename, f"Unsupported &{type(operand).__name__}")

    def _deref(self, expr: UnaryExpr) -> int:
        c = llvm()
        ptr = self._emit_expr(expr.operand)
        operand_type = self._type_map.get(expr.operand)
        pointee = None if operand_type is None else operand_type.pointee()
        if pointee is not None and self._is_function_designator_type(pointee):
            return ptr
        val_type = self._type_map.require(expr)
        lt = self._type_to_llvm(val_type)
        return c.BuildLoad2(self._builder, lt, ptr, b"deref")

    # ── binary ───────────────────────────────────────────────

    def _binary(self, expr: BinaryExpr) -> int:
        c = llvm()
        op = expr.op

        if op in {"&&", "||"}:
            return self._logical(expr)

        left_c_type = self._type_map.get(expr.left)
        right_c_type = self._type_map.get(expr.right)
        left = self._emit_expr(expr.left)
        right = self._emit_expr(expr.right)

        if op in {"==", "!=", "<", ">", "<=", ">="}:
            return self._compare(op, left, right, left_c_type, right_c_type)

        result_type = self._type_map.require(expr)
        self._type_to_llvm(result_type)

        # Pointer arithmetic: ptr ± int → GEP
        lt = c.TypeOf(left)
        rt = c.TypeOf(right)
        # Decay array operands
        if c.GetTypeKind(lt) == LLVMTypeKind.ARRAY:
            left = self._build_cast(left, c.PointerType(c.Int8Type(), 0))
            lt = c.TypeOf(left)
        if c.GetTypeKind(rt) == LLVMTypeKind.ARRAY:
            right = self._build_cast(right, c.PointerType(c.Int8Type(), 0))
            rt = c.TypeOf(right)
        # Commute int + ptr → ptr + int
        rk_ptr = c.GetTypeKind(c.TypeOf(right))
        if (
            op in ("+", "-")
            and rk_ptr == LLVMTypeKind.POINTER
            and c.GetTypeKind(lt) != LLVMTypeKind.POINTER
        ):
            left, right = right, left
            left_c_type, right_c_type = right_c_type, left_c_type
            lt = c.TypeOf(left)
            rt = c.TypeOf(right)
        if op in ("+", "-") and c.GetTypeKind(lt) == LLVMTypeKind.POINTER:
            rk = c.GetTypeKind(rt)
            if rk == LLVMTypeKind.POINTER:
                # ptr - ptr: use ptrtoint + integer arithmetic
                li = c.BuildPtrToInt(self._builder, left, c.Int64Type(), b"cast")
                ri = c.BuildPtrToInt(self._builder, right, c.Int64Type(), b"cast")
                diff = c.BuildSub(self._builder, li, ri, b"ptr.diff")
                elem_size = self._pointer_arith_element_size(left_c_type)
                if elem_size > 1:
                    size_val = c.ConstInt(c.Int64Type(), elem_size, False)
                    diff = c.BuildSDiv(self._builder, diff, size_val, b"ptr.diff.scaled")
                return diff
            right = self._gep_index_value(right, right_c_type, b"ptr.idx")
            if op == "-":
                right = c.BuildNeg(self._builder, right, b"neg")
            idx = ptr_array([right])
            elem_lt = self._pointer_arith_element_llvm_type(left_c_type)
            return c.BuildGEP2(self._builder, elem_lt, left, idx, 1, b"ptr.arith")

        lk = c.GetTypeKind(lt)
        rk = c.GetTypeKind(rt)
        l_float = self._is_float_kind(lk)
        r_float = self._is_float_kind(rk)

        if l_float and not r_float:
            right = c.BuildSIToFP(self._builder, right, lt, b"bin.cast")
            r_float = True
            rk = c.GetTypeKind(c.TypeOf(right))
        elif r_float and not l_float:
            left = c.BuildSIToFP(self._builder, left, rt, b"bin.cast")
            l_float = True
            lk = c.GetTypeKind(c.TypeOf(left))
        elif l_float and r_float and lt != rt:
            if self._float_rank(lk) >= self._float_rank(rk):
                right = c.BuildFPCast(self._builder, right, lt, b"bin.cast")
                rt = lt
                rk = lk
            else:
                left = c.BuildFPCast(self._builder, left, rt, b"bin.cast")
                lt = rt
                lk = rk

        # For integer ops, match operand widths to avoid i32 vs i64 errors.
        both_int = lk == LLVMTypeKind.INTEGER and rk == LLVMTypeKind.INTEGER
        if not l_float and not r_float and both_int:
            target_t = self._type_to_llvm(result_type)
            if c.GetTypeKind(target_t) == LLVMTypeKind.INTEGER:
                left = self._cast_integer_value(left, target_t, left_c_type, b"bin.cast")
                right = self._cast_integer_value(right, target_t, right_c_type, b"bin.cast")
                lt = target_t
                rt = target_t

        if l_float or r_float:
            farith = {
                "+": c.BuildFAdd,
                "-": c.BuildFSub,
                "*": c.BuildFMul,
                "/": c.BuildFDiv,
            }
            fn = farith.get(op)
        else:
            unsigned_result = self._is_unsigned_integer_c_type(result_type)
            arith = {
                "+": c.BuildAdd,
                "-": c.BuildSub,
                "*": c.BuildMul,
                "/": c.BuildUDiv if unsigned_result else c.BuildSDiv,
                "%": c.BuildURem if unsigned_result else c.BuildSRem,
            }
            bit = {
                "&": c.BuildAnd,
                "|": c.BuildOr,
                "^": c.BuildXor,
                "<<": c.BuildShl,
                ">>": c.BuildLShr if unsigned_result else c.BuildAShr,
            }
            fn = arith.get(op) or bit.get(op)

        if fn is None:
            raise llvm_backend_error(self._result.filename, f"Unsupported binary: {op}")
        return fn(self._builder, left, right, b"binop")

    def _compare(
        self,
        op: str,
        left: int,
        right: int,
        left_c_type: Type | None,
        right_c_type: Type | None,
    ) -> int:
        c = llvm()
        lt = c.TypeOf(left)
        rt = c.TypeOf(right)
        lk = c.GetTypeKind(lt)
        rk = c.GetTypeKind(rt)
        # Decay array operands to pointer
        if lk == LLVMTypeKind.ARRAY:
            left = self._build_cast(left, c.PointerType(c.Int8Type(), 0))
            lt = c.TypeOf(left)
            lk = LLVMTypeKind.POINTER
        if rk == LLVMTypeKind.ARRAY:
            right = self._build_cast(right, c.PointerType(c.Int8Type(), 0))
            rt = c.TypeOf(right)
            rk = LLVMTypeKind.POINTER
        l_float = self._is_float_kind(lk)
        r_float = self._is_float_kind(rk)

        if l_float and not r_float:
            right = c.BuildSIToFP(self._builder, right, lt, b"cast")
            r_float = True
            rt = lt
            rk = lk
        elif r_float and not l_float:
            left = c.BuildSIToFP(self._builder, left, rt, b"cast")
            l_float = True
            lt = rt
            lk = rk
        elif l_float and r_float and lt != rt:
            if self._float_rank(lk) >= self._float_rank(rk):
                right = c.BuildFPCast(self._builder, right, lt, b"cast")
                rt = lt
                rk = lk
            else:
                left = c.BuildFPCast(self._builder, left, rt, b"cast")
                lt = rt
                lk = rk

        if l_float:
            fpreds = {"==": 1, "!=": 6, "<": 4, ">": 2, "<=": 5, ">=": 3}
            pred = fpreds[op]
            cmp = c.BuildFCmp(self._builder, pred, left, right, b"cmp")
        else:
            unsigned_compare = False
            # Normalize pointer ↔ integer comparisons: convert
            # the integer operand to a pointer so icmp is valid.
            if lk == LLVMTypeKind.POINTER and rk == LLVMTypeKind.INTEGER:
                right = c.BuildIntToPtr(self._builder, right, lt, b"cmp.cast")
            elif rk == LLVMTypeKind.POINTER and lk == LLVMTypeKind.INTEGER:
                left = c.BuildIntToPtr(self._builder, left, rt, b"cmp.cast")
            elif lk == LLVMTypeKind.INTEGER and rk == LLVMTypeKind.INTEGER:
                common_type = self._common_integer_c_type(left_c_type, right_c_type)
                if common_type is not None:
                    target_t = self._type_to_llvm(common_type)
                    left = self._cast_integer_value(left, target_t, left_c_type, b"cmp.cast")
                    right = self._cast_integer_value(right, target_t, right_c_type, b"cmp.cast")
                    unsigned_compare = self._is_unsigned_integer_c_type(common_type)
                elif lt != rt:
                    # Match integer widths for icmp.
                    lw = c.GetIntTypeWidth(lt)
                    rw = c.GetIntTypeWidth(rt)
                    if lw > rw:
                        right = self._cast_integer_value(right, lt, right_c_type, b"cmp.cast")
                    elif rw > lw:
                        left = self._cast_integer_value(left, rt, left_c_type, b"cmp.cast")
            signed_preds = {"==": 32, "!=": 33, "<": 40, ">": 38, "<=": 41, ">=": 39}
            unsigned_preds = {"==": 32, "!=": 33, "<": 36, ">": 34, "<=": 37, ">=": 35}
            preds = unsigned_preds if unsigned_compare else signed_preds
            pred = preds[op]
            cmp = c.BuildICmp(self._builder, pred, left, right, b"cmp")
        return c.BuildZExt(self._builder, cmp, c.Int32Type(), b"cmp.ext")

    def _logical(self, expr: BinaryExpr) -> int:
        c = llvm()
        fn = self._func
        lhs = self._to_bool(self._emit_expr(expr.left))

        rhs_bb = c.AppendBasicBlock(fn, b"log.rhs")
        short_bb = c.AppendBasicBlock(fn, b"log.short")
        end_bb = c.AppendBasicBlock(fn, b"log.end")

        alloca = c.BuildAlloca(self._builder, c.Int32Type(), b"log.res")
        if expr.op == "&&":
            c.BuildCondBr(self._builder, lhs, rhs_bb, short_bb)
            short_val = 0
        else:
            c.BuildCondBr(self._builder, lhs, short_bb, rhs_bb)
            short_val = 1

        c.PositionBuilderAtEnd(self._builder, short_bb)
        c.BuildStore(self._builder, c.ConstInt(c.Int32Type(), short_val, False), alloca)
        c.BuildBr(self._builder, end_bb)

        c.PositionBuilderAtEnd(self._builder, rhs_bb)
        rhs = self._to_bool(self._emit_expr(expr.right))
        rhs_ext = c.BuildZExt(self._builder, rhs, c.Int32Type(), b"log.rhs.ext")
        c.BuildStore(self._builder, rhs_ext, alloca)
        c.BuildBr(self._builder, end_bb)

        c.PositionBuilderAtEnd(self._builder, end_bb)
        return c.BuildLoad2(self._builder, c.Int32Type(), alloca, b"log.res")

    # ── assign ───────────────────────────────────────────────

    def _assign(self, expr: AssignExpr) -> int:
        c = llvm()
        val = self._emit_expr(expr.value)

        target = expr.target
        addr = self._assign_addr(target)

        if expr.op == "=":
            target_type = self._type_map.require(target)
            target_lt = self._type_to_llvm(target_type)
            if c.TypeOf(val) != target_lt:
                val = self._build_cast(val, target_lt, self._type_map.get(expr.value))
            c.BuildStore(self._builder, val, addr)
            return val

        # Compound: load, compute, store
        target_type = self._type_map.require(target)
        lt = self._type_to_llvm(target_type)
        old = c.BuildLoad2(self._builder, lt, addr, b"load.old")

        lk = c.GetTypeKind(lt)

        # Pointer += / -= : use GEP
        if lk == LLVMTypeKind.POINTER and expr.op in ("+=", "-="):
            val = self._gep_index_value(val, self._type_map.get(expr.value), b"ptr.idx")
            if expr.op == "-=":
                val = c.BuildNeg(self._builder, val, b"neg")
            idx = ptr_array([val])
            elem_lt = self._pointer_arith_element_llvm_type(target_type)
            result = c.BuildGEP2(self._builder, elem_lt, old, idx, 1, b"ptr.arith")
            c.BuildStore(self._builder, result, addr)
            return result

        # Match operand widths for mixed integer types.
        vt = c.TypeOf(val)
        vk = c.GetTypeKind(vt)
        if lk == LLVMTypeKind.INTEGER and vk == LLVMTypeKind.INTEGER and lt != vt:
            val = self._cast_integer_value(val, lt, self._type_map.get(expr.value), b"cmpd.cast")

        is_float = self._is_float_kind(lk)
        if is_float and vt != lt:
            if vk == LLVMTypeKind.INTEGER:
                val = c.BuildSIToFP(self._builder, val, lt, b"cmpd.cast")
            elif self._is_float_kind(vk):
                val = c.BuildFPCast(self._builder, val, lt, b"cmpd.cast")

        if is_float:
            farith = {
                "+=": c.BuildFAdd,
                "-=": c.BuildFSub,
                "*=": c.BuildFMul,
                "/=": c.BuildFDiv,
            }
            fn = farith.get(expr.op)
        else:
            unsigned_target = self._is_unsigned_integer_c_type(target_type)
            arith = {
                "+=": c.BuildAdd,
                "-=": c.BuildSub,
                "*=": c.BuildMul,
                "/=": c.BuildUDiv if unsigned_target else c.BuildSDiv,
                "%=": c.BuildURem if unsigned_target else c.BuildSRem,
            }
            bit = {
                "&=": c.BuildAnd,
                "|=": c.BuildOr,
                "^=": c.BuildXor,
                "<<=": c.BuildShl,
                ">>=": c.BuildLShr if unsigned_target else c.BuildAShr,
            }
            fn = arith.get(expr.op) or bit.get(expr.op)

        if fn is None:
            raise llvm_backend_error(self._result.filename, f"Unsupported compound: {expr.op}")
        result = fn(self._builder, old, val, b"compound")
        c.BuildStore(self._builder, result, addr)
        return result

    def _assign_addr(self, target: Expr) -> int:
        c = llvm()
        if isinstance(target, Identifier):
            name = target.name
            assert isinstance(name, str)
            addr = self._lookup_local(name)
            if addr:
                return addr
            gv = c.GetNamedGlobal(self._mod, name.encode())
            if gv:
                return gv
            target_type = self._type_map.get(target) or self._lookup_symbol_type(name)
            if target_type is not None and not self._is_function_designator_type(target_type):
                return self._global_var_ref(name, target_type)
            # Declare as external global
            gv = c.AddGlobal(self._mod, c.PointerType(c.Int8Type(), 0), name.encode())
            return gv
        if isinstance(target, UnaryExpr) and target.op == "*":
            return self._emit_expr(target.operand)
        if isinstance(target, SubscriptExpr):
            return self._subscript_ptr(target)
        if isinstance(target, MemberExpr):
            return self._member_ptr(target)
        if isinstance(target, CompoundLiteralExpr):
            return self._compound_literal_addr(target)
        raise llvm_backend_error(
            self._result.filename,
            f"Unsupported assign target: {type(target).__name__}",
        )

    # ── update ───────────────────────────────────────────────

    def _update(self, expr: UpdateExpr) -> int:
        c = llvm()
        delta = 1 if expr.op == "++" else -1
        target = expr.operand
        addr = self._assign_addr(target)
        target_type = self._type_map.require(target)
        lt = self._type_to_llvm(target_type)
        old = c.BuildLoad2(self._builder, lt, addr, b"update.old")
        if c.GetTypeKind(lt) == LLVMTypeKind.POINTER:
            # Pointer arithmetic: use i64 delta with GEP
            idx = c.ConstInt(c.Int64Type(), delta, True)
            idx_arr = ptr_array([idx])
            elem_lt = self._pointer_arith_element_llvm_type(target_type)
            new_v = c.BuildGEP2(self._builder, elem_lt, old, idx_arr, 1, b"update.gep")
        elif self._is_float_kind(c.GetTypeKind(lt)):
            delta_v = c.ConstReal(lt, float(delta))
            new_v = c.BuildFAdd(self._builder, old, delta_v, b"update.new")
        else:
            delta_v = c.ConstInt(lt, delta, True)
            new_v = c.BuildAdd(self._builder, old, delta_v, b"update.new")
        c.BuildStore(self._builder, new_v, addr)
        return old if expr.is_postfix else new_v

    # ── atomic builtins ──────────────────────────────────────

    def _atomic_pointer(self, expr: Expr) -> tuple[int, Type, int]:
        c = llvm()
        ptr = self._emit_expr(expr)
        ptr_type = self._type_map.get(expr)
        pointee = None if ptr_type is None else ptr_type.pointee()
        if pointee is None:
            pointee = INT
        lt = self._type_to_llvm(pointee)
        if c.GetTypeKind(lt) == LLVMTypeKind.VOID:
            pointee = INT
            lt = c.Int32Type()
        return ptr, pointee, lt

    def _atomic_align(self, type_: Type) -> int:
        return max(1, self._type_align(type_))

    def _atomic_load_value(self, ptr: int, type_: Type, lt: int) -> int:
        c = llvm()
        load = c.BuildLoad2(self._builder, lt, ptr, b"atomic.load")
        c.SetOrdering(load, ATOMIC_ORDER_SEQ_CST)
        c.SetAlignment(load, self._atomic_align(type_))
        return load

    def _atomic_store_value(self, ptr: int, type_: Type, lt: int, value: int) -> int:
        c = llvm()
        if c.TypeOf(value) != lt:
            value = self._build_cast(value, lt)
        store = c.BuildStore(self._builder, value, ptr)
        c.SetOrdering(store, ATOMIC_ORDER_SEQ_CST)
        c.SetAlignment(store, self._atomic_align(type_))
        return c.ConstInt(c.Int32Type(), 0, False)

    def _atomic_rmw_value(self, op: int, ptr: int, type_: Type, lt: int, value: int) -> int:
        c = llvm()
        if c.TypeOf(value) != lt:
            value = self._build_cast(value, lt)
        rmw = c.BuildAtomicRMW(self._builder, op, ptr, value, ATOMIC_ORDER_SEQ_CST, False)
        c.SetValueName2(rmw, b"atomic.rmw", len(b"atomic.rmw"))
        c.SetAlignment(rmw, self._atomic_align(type_))
        return rmw

    def _atomic_promote_result(self, value: int, type_: Type) -> int:
        c = llvm()
        value_type = c.TypeOf(value)
        if c.GetTypeKind(value_type) != LLVMTypeKind.INTEGER:
            return value
        if c.GetIntTypeWidth(value_type) >= 32:
            return value
        if type_.name.startswith("unsigned") or type_.name == "_Bool":
            return c.BuildZExt(self._builder, value, c.Int32Type(), b"atomic.promote")
        return c.BuildSExt(self._builder, value, c.Int32Type(), b"atomic.promote")

    def _atomic_rmw_new_value(self, op: int, old: int, value: int) -> int:
        c = llvm()
        if op == ATOMIC_RMW_ADD:
            return c.BuildAdd(self._builder, old, value, b"atomic.new")
        if op == ATOMIC_RMW_SUB:
            return c.BuildSub(self._builder, old, value, b"atomic.new")
        if op == ATOMIC_RMW_AND:
            return c.BuildAnd(self._builder, old, value, b"atomic.new")
        if op == ATOMIC_RMW_OR:
            return c.BuildOr(self._builder, old, value, b"atomic.new")
        if op == ATOMIC_RMW_XOR:
            return c.BuildXor(self._builder, old, value, b"atomic.new")
        if op == ATOMIC_RMW_NAND:
            and_value = c.BuildAnd(self._builder, old, value, b"atomic.and")
            return c.BuildXor(
                self._builder,
                and_value,
                c.ConstInt(c.TypeOf(and_value), -1, True),
                b"atomic.new",
            )
        return value

    def _atomic_compare_exchange(
        self,
        ptr: int,
        type_: Type,
        lt: int,
        expected_ptr: int,
        desired: int,
    ) -> int:
        c = llvm()
        if c.TypeOf(desired) != lt:
            desired = self._build_cast(desired, lt)
        expected = c.BuildLoad2(self._builder, lt, expected_ptr, b"atomic.expected")
        cmpxchg = c.BuildAtomicCmpXchg(
            self._builder,
            ptr,
            expected,
            desired,
            ATOMIC_ORDER_SEQ_CST,
            ATOMIC_ORDER_SEQ_CST,
            False,
        )
        c.SetValueName2(cmpxchg, b"atomic.cmpxchg", len(b"atomic.cmpxchg"))
        c.SetAlignment(cmpxchg, self._atomic_align(type_))
        old = c.BuildExtractValue(self._builder, cmpxchg, 0, b"atomic.old")
        success = c.BuildExtractValue(self._builder, cmpxchg, 1, b"atomic.ok")
        c.BuildStore(self._builder, old, expected_ptr)
        return c.BuildZExt(self._builder, success, c.Int32Type(), b"atomic.ok.ext")

    def _atomic_builtin_call(self, callee_name: str, args: tuple[Expr, ...]) -> int | None:
        c = llvm()
        if callee_name in {
            "__atomic_thread_fence",
            "__atomic_signal_fence",
            "__c11_atomic_thread_fence",
            "__c11_atomic_signal_fence",
            "__sync_synchronize",
            "__scoped_atomic_thread_fence",
        }:
            c.BuildFence(self._builder, ATOMIC_ORDER_SEQ_CST, False, b"")
            return c.ConstInt(c.Int32Type(), 0, False)

        if callee_name in {
            "__atomic_is_lock_free",
            "__atomic_always_lock_free",
            "__c11_atomic_is_lock_free",
        }:
            return c.ConstInt(c.Int32Type(), 1, False)

        if callee_name in {"__atomic_load_n", "__c11_atomic_load", "__scoped_atomic_load"}:
            if len(args) < 1:
                return c.ConstInt(c.Int32Type(), 0, False)
            ptr, elem_type, elem_lt = self._atomic_pointer(args[0])
            value = self._atomic_load_value(ptr, elem_type, elem_lt)
            return self._atomic_promote_result(value, elem_type)

        if callee_name in {
            "__atomic_store_n",
            "__c11_atomic_store",
            "__c11_atomic_init",
            "__scoped_atomic_store",
        }:
            if len(args) < 2:
                return c.ConstInt(c.Int32Type(), 0, False)
            ptr, elem_type, elem_lt = self._atomic_pointer(args[0])
            value = self._emit_expr(args[1])
            return self._atomic_store_value(ptr, elem_type, elem_lt, value)

        if callee_name == "__atomic_load":
            if len(args) < 2:
                return c.ConstInt(c.Int32Type(), 0, False)
            ptr, elem_type, elem_lt = self._atomic_pointer(args[0])
            out_ptr = self._emit_expr(args[1])
            value = self._atomic_load_value(ptr, elem_type, elem_lt)
            return self._atomic_store_value(out_ptr, elem_type, elem_lt, value)

        if callee_name == "__atomic_store":
            if len(args) < 2:
                return c.ConstInt(c.Int32Type(), 0, False)
            ptr, elem_type, elem_lt = self._atomic_pointer(args[0])
            in_ptr = self._emit_expr(args[1])
            value = c.BuildLoad2(self._builder, elem_lt, in_ptr, b"atomic.in")
            return self._atomic_store_value(ptr, elem_type, elem_lt, value)

        rmw_ops = {
            "__atomic_fetch_add": ATOMIC_RMW_ADD,
            "__atomic_fetch_sub": ATOMIC_RMW_SUB,
            "__atomic_fetch_and": ATOMIC_RMW_AND,
            "__atomic_fetch_or": ATOMIC_RMW_OR,
            "__atomic_fetch_xor": ATOMIC_RMW_XOR,
            "__atomic_fetch_nand": ATOMIC_RMW_NAND,
            "__sync_fetch_and_add": ATOMIC_RMW_ADD,
            "__sync_fetch_and_sub": ATOMIC_RMW_SUB,
            "__sync_fetch_and_and": ATOMIC_RMW_AND,
            "__sync_fetch_and_or": ATOMIC_RMW_OR,
            "__sync_fetch_and_xor": ATOMIC_RMW_XOR,
            "__c11_atomic_fetch_add": ATOMIC_RMW_ADD,
            "__c11_atomic_fetch_sub": ATOMIC_RMW_SUB,
            "__c11_atomic_fetch_and": ATOMIC_RMW_AND,
            "__c11_atomic_fetch_or": ATOMIC_RMW_OR,
            "__c11_atomic_fetch_xor": ATOMIC_RMW_XOR,
            "__scoped_atomic_fetch_add": ATOMIC_RMW_ADD,
        }
        fetch_op = rmw_ops.get(callee_name)
        if fetch_op is not None:
            if len(args) < 2:
                return c.ConstInt(c.Int32Type(), 0, False)
            ptr, elem_type, elem_lt = self._atomic_pointer(args[0])
            value = self._emit_expr(args[1])
            old = self._atomic_rmw_value(fetch_op, ptr, elem_type, elem_lt, value)
            return self._atomic_promote_result(old, elem_type)

        new_value_ops = {
            "__atomic_add_fetch": ATOMIC_RMW_ADD,
            "__atomic_sub_fetch": ATOMIC_RMW_SUB,
            "__atomic_and_fetch": ATOMIC_RMW_AND,
            "__atomic_or_fetch": ATOMIC_RMW_OR,
            "__atomic_xor_fetch": ATOMIC_RMW_XOR,
            "__atomic_nand_fetch": ATOMIC_RMW_NAND,
            "__sync_add_and_fetch": ATOMIC_RMW_ADD,
            "__sync_sub_and_fetch": ATOMIC_RMW_SUB,
            "__sync_and_and_fetch": ATOMIC_RMW_AND,
            "__sync_or_and_fetch": ATOMIC_RMW_OR,
            "__sync_xor_and_fetch": ATOMIC_RMW_XOR,
        }
        new_op = new_value_ops.get(callee_name)
        if new_op is not None:
            if len(args) < 2:
                return c.ConstInt(c.Int32Type(), 0, False)
            ptr, elem_type, elem_lt = self._atomic_pointer(args[0])
            value = self._emit_expr(args[1])
            if c.TypeOf(value) != elem_lt:
                value = self._build_cast(value, elem_lt)
            old = self._atomic_rmw_value(new_op, ptr, elem_type, elem_lt, value)
            new_value = self._atomic_rmw_new_value(new_op, old, value)
            return self._atomic_promote_result(new_value, elem_type)

        if callee_name in {
            "__atomic_exchange_n",
            "__c11_atomic_exchange",
            "__sync_lock_test_and_set",
        }:
            if len(args) < 2:
                return c.ConstInt(c.Int32Type(), 0, False)
            ptr, elem_type, elem_lt = self._atomic_pointer(args[0])
            value = self._emit_expr(args[1])
            old = self._atomic_rmw_value(ATOMIC_RMW_XCHG, ptr, elem_type, elem_lt, value)
            return self._atomic_promote_result(old, elem_type)

        if callee_name == "__atomic_exchange":
            if len(args) < 3:
                return c.ConstInt(c.Int32Type(), 0, False)
            ptr, elem_type, elem_lt = self._atomic_pointer(args[0])
            in_ptr = self._emit_expr(args[1])
            out_ptr = self._emit_expr(args[2])
            value = c.BuildLoad2(self._builder, elem_lt, in_ptr, b"atomic.in")
            old = self._atomic_rmw_value(ATOMIC_RMW_XCHG, ptr, elem_type, elem_lt, value)
            return self._atomic_store_value(out_ptr, elem_type, elem_lt, old)

        if callee_name in {
            "__atomic_compare_exchange_n",
            "__c11_atomic_compare_exchange_strong",
            "__c11_atomic_compare_exchange_weak",
        }:
            if len(args) < 3:
                return c.ConstInt(c.Int32Type(), 0, False)
            ptr, elem_type, elem_lt = self._atomic_pointer(args[0])
            expected_ptr = self._emit_expr(args[1])
            desired = self._emit_expr(args[2])
            return self._atomic_compare_exchange(ptr, elem_type, elem_lt, expected_ptr, desired)

        if callee_name == "__atomic_compare_exchange":
            if len(args) < 3:
                return c.ConstInt(c.Int32Type(), 0, False)
            ptr, elem_type, elem_lt = self._atomic_pointer(args[0])
            expected_ptr = self._emit_expr(args[1])
            desired_ptr = self._emit_expr(args[2])
            desired = c.BuildLoad2(self._builder, elem_lt, desired_ptr, b"atomic.desired")
            return self._atomic_compare_exchange(ptr, elem_type, elem_lt, expected_ptr, desired)

        if callee_name in {"__sync_val_compare_and_swap", "__sync_bool_compare_and_swap"}:
            if len(args) < 3:
                return c.ConstInt(c.Int32Type(), 0, False)
            ptr, elem_type, elem_lt = self._atomic_pointer(args[0])
            expected = self._emit_expr(args[1])
            desired = self._emit_expr(args[2])
            if c.TypeOf(expected) != elem_lt:
                expected = self._build_cast(expected, elem_lt)
            if c.TypeOf(desired) != elem_lt:
                desired = self._build_cast(desired, elem_lt)
            cmpxchg = c.BuildAtomicCmpXchg(
                self._builder,
                ptr,
                expected,
                desired,
                ATOMIC_ORDER_SEQ_CST,
                ATOMIC_ORDER_SEQ_CST,
                False,
            )
            c.SetValueName2(cmpxchg, b"sync.cmpxchg", len(b"sync.cmpxchg"))
            c.SetAlignment(cmpxchg, self._atomic_align(elem_type))
            old = c.BuildExtractValue(self._builder, cmpxchg, 0, b"sync.old")
            if callee_name == "__sync_val_compare_and_swap":
                return self._atomic_promote_result(old, elem_type)
            success = c.BuildExtractValue(self._builder, cmpxchg, 1, b"sync.ok")
            return c.BuildZExt(self._builder, success, c.Int32Type(), b"sync.ok.ext")

        if callee_name == "__sync_lock_release":
            if len(args) < 1:
                return c.ConstInt(c.Int32Type(), 0, False)
            ptr, elem_type, elem_lt = self._atomic_pointer(args[0])
            return self._atomic_store_value(
                ptr,
                elem_type,
                elem_lt,
                c.ConstInt(elem_lt, 0, False),
            )

        return None

    # ── GCC/Clang builtins ──────────────────────────────────

    def _int_type_for_width(self, width: int) -> int:
        c = llvm()
        if width == 1:
            return c.Int1Type()
        if width == 8:
            return c.Int8Type()
        if width == 16:
            return c.Int16Type()
        if width == 32:
            return c.Int32Type()
        if width == 64:
            return c.Int64Type()
        return c.Int64Type()

    def _cast_int_to_width(self, value: int, width: int, *, signed: bool) -> int:
        c = llvm()
        target_t = self._int_type_for_width(width)
        value_t = c.TypeOf(value)
        value_kind = c.GetTypeKind(value_t)
        if value_t == target_t:
            return value
        if value_kind == LLVMTypeKind.POINTER:
            return c.BuildPtrToInt(self._builder, value, target_t, b"builtin.ptrint")
        if value_kind != LLVMTypeKind.INTEGER:
            return self._build_cast(value, target_t)
        value_width = c.GetIntTypeWidth(value_t)
        if value_width < width:
            if signed:
                return c.BuildSExt(self._builder, value, target_t, b"builtin.ext")
            return c.BuildZExt(self._builder, value, target_t, b"builtin.ext")
        if value_width > width:
            return c.BuildTrunc(self._builder, value, target_t, b"builtin.trunc")
        return value

    def _result_type_ref(self, expr: CallExpr, fallback: int) -> int:
        result_type = self._type_map.get(expr)
        if result_type is None:
            return fallback
        return self._type_to_llvm(result_type)

    def _coerce_builtin_result(self, value: int, expr: CallExpr) -> int:
        result_type = self._type_map.get(expr)
        if result_type is None:
            return value
        target_t = self._type_to_llvm(result_type)
        if llvm().GetTypeKind(target_t) == LLVMTypeKind.VOID:
            return value
        if llvm().TypeOf(value) == target_t:
            return value
        return self._build_cast(value, target_t)

    def _intrinsic_call(
        self,
        name: str,
        return_type: int,
        values: list[int],
        param_types: list[int],
    ) -> int:
        c = llvm()
        n = len(values)
        params = optional_zero_ptr_array(n)
        args = optional_zero_ptr_array(n)
        if n:
            assert params is not None and args is not None
            for i, param_type in enumerate(param_types):
                params[i] = param_type
            for i, value in enumerate(values):
                args[i] = value
        fn_t = c.FunctionType(return_type, params, n, False)
        fn = c.GetNamedFunction(self._mod, name.encode())
        if not fn:
            fn = c.AddFunction(self._mod, name.encode(), fn_t)
        call_name = b"" if c.GetTypeKind(return_type) == LLVMTypeKind.VOID else b"call"
        return c.BuildCall2(self._builder, fn_t, fn, args, n, call_name)

    def _bit_builtin_width(self, callee_name: str) -> int:
        if callee_name.endswith("ll") or callee_name.endswith("64"):
            return 64
        if callee_name.endswith("l"):
            return 64
        if callee_name.endswith("16"):
            return 16
        return 32

    def _integer_bit_builtin(self, callee_name: str, expr: CallExpr) -> int | None:
        supported = {
            "__builtin_bswap16",
            "__builtin_bswap32",
            "__builtin_bswap64",
            "__builtin_clz",
            "__builtin_clzl",
            "__builtin_clzll",
            "__builtin_ctz",
            "__builtin_ctzl",
            "__builtin_ctzll",
            "__builtin_ffs",
            "__builtin_ffsl",
            "__builtin_ffsll",
            "__builtin_popcount",
            "__builtin_popcountl",
            "__builtin_popcountll",
        }
        if callee_name not in supported:
            return None
        if not expr.args:
            return None
        c = llvm()
        width = self._bit_builtin_width(callee_name)
        arg_t = self._int_type_for_width(width)
        arg = self._cast_int_to_width(self._emit_expr(expr.args[0]), width, signed=False)

        if "bswap" in callee_name:
            value = self._intrinsic_call(f"llvm.bswap.i{width}", arg_t, [arg], [arg_t])
            return self._coerce_builtin_result(value, expr)

        if "popcount" in callee_name:
            value = self._intrinsic_call(f"llvm.ctpop.i{width}", arg_t, [arg], [arg_t])
            return self._coerce_builtin_result(value, expr)

        if "clz" in callee_name or "ctz" in callee_name:
            intrinsic = "ctlz" if "clz" in callee_name else "cttz"
            flag = c.ConstInt(c.Int1Type(), 1, False)
            value = self._intrinsic_call(
                f"llvm.{intrinsic}.i{width}",
                arg_t,
                [arg, flag],
                [arg_t, c.Int1Type()],
            )
            return self._coerce_builtin_result(value, expr)

        if "ffs" in callee_name:
            is_zero = c.BuildICmp(
                self._builder,
                32,
                arg,
                c.ConstInt(arg_t, 0, False),
                b"builtin.ffs.zero",
            )
            flag = c.ConstInt(c.Int1Type(), 0, False)
            ctz = self._intrinsic_call(
                f"llvm.cttz.i{width}",
                arg_t,
                [arg, flag],
                [arg_t, c.Int1Type()],
            )
            one_based = c.BuildAdd(
                self._builder,
                ctz,
                c.ConstInt(arg_t, 1, False),
                b"builtin.ffs.index",
            )
            value = c.BuildSelect(
                self._builder,
                is_zero,
                c.ConstInt(arg_t, 0, False),
                one_based,
                b"builtin.ffs",
            )
            return self._coerce_builtin_result(value, expr)

        return None

    def _float_intrinsic_type(self, value: int, expr: CallExpr) -> int:
        c = llvm()
        value_t = c.TypeOf(value)
        if self._is_float_kind(c.GetTypeKind(value_t)):
            return value_t
        return self._result_type_ref(expr, c.DoubleType())

    def _floating_builtin(self, callee_name: str, expr: CallExpr) -> int | None:
        c = llvm()
        if callee_name in {
            "__builtin_inf",
            "__builtin_inff",
            "__builtin_infl",
            "__builtin_huge_val",
            "__builtin_huge_valf",
            "__builtin_huge_vall",
        }:
            result_t = self._result_type_ref(expr, c.DoubleType())
            return c.ConstReal(result_t, float("inf"))
        if callee_name in {"__builtin_nan", "__builtin_nanf", "__builtin_nanl"}:
            result_t = self._result_type_ref(expr, c.DoubleType())
            return c.ConstReal(result_t, float("nan"))
        if callee_name in {"__builtin_isinf", "__builtin_isnan", "__builtin_isfinite"}:
            if not expr.args:
                return None
            value = self._emit_expr(expr.args[0])
            value_t = self._float_intrinsic_type(value, expr)
            if c.TypeOf(value) != value_t:
                value = self._build_cast(value, value_t)
            if callee_name == "__builtin_isnan":
                pred = c.BuildFCmp(self._builder, 8, value, value, b"builtin.isnan")
            else:
                abs_value = self._intrinsic_call(
                    "llvm.fabs.f32"
                    if c.GetTypeKind(value_t) == LLVMTypeKind.FLOAT
                    else "llvm.fabs.f64",
                    value_t,
                    [value],
                    [value_t],
                )
                inf = c.ConstReal(value_t, float("inf"))
                predicate = 1 if callee_name == "__builtin_isinf" else 6
                pred = c.BuildFCmp(self._builder, predicate, abs_value, inf, b"builtin.fpclass")
            result = c.BuildZExt(self._builder, pred, c.Int32Type(), b"builtin.fpclass.ext")
            return self._coerce_builtin_result(result, expr)
        if callee_name in {
            "__builtin_fabs",
            "__builtin_fabsf",
            "__builtin_fabsl",
            "__builtin_copysign",
            "__builtin_copysignf",
            "__builtin_copysignl",
        }:
            if not expr.args:
                return None
            first = self._emit_expr(expr.args[0])
            intrinsic_t = self._float_intrinsic_type(first, expr)
            if c.TypeOf(first) != intrinsic_t:
                first = self._build_cast(first, intrinsic_t)
            values = [first]
            param_types = [intrinsic_t]
            intrinsic = "fabs"
            if "copysign" in callee_name:
                if len(expr.args) < 2:
                    return None
                second = self._emit_expr(expr.args[1])
                if c.TypeOf(second) != intrinsic_t:
                    second = self._build_cast(second, intrinsic_t)
                values.append(second)
                param_types.append(intrinsic_t)
                intrinsic = "copysign"
            suffix = "f32" if c.GetTypeKind(intrinsic_t) == LLVMTypeKind.FLOAT else "f64"
            value = self._intrinsic_call(
                f"llvm.{intrinsic}.{suffix}",
                intrinsic_t,
                values,
                param_types,
            )
            return self._coerce_builtin_result(value, expr)
        return None

    def _gcc_builtin_call(self, callee_name: str, expr: CallExpr) -> int | None:
        c = llvm()
        if callee_name == "assert":
            return c.ConstInt(c.Int32Type(), 0, False)
        if callee_name == "__builtin_assume_aligned":
            if not expr.args:
                return c.ConstNull(c.PointerType(c.Int8Type(), 0))
            return self._coerce_builtin_result(self._emit_expr(expr.args[0]), expr)
        if callee_name in {"__builtin_alloca", "__builtin_alloca_with_align"}:
            if not expr.args:
                return c.ConstNull(c.PointerType(c.Int8Type(), 0))
            count = self._cast_int_to_width(self._emit_expr(expr.args[0]), 64, signed=False)
            alloca = c.BuildArrayAlloca(self._builder, c.Int8Type(), count, b"builtin.alloca")
            return self._coerce_builtin_result(alloca, expr)
        if callee_name == "__builtin_flt_rounds":
            result_t = self._result_type_ref(expr, c.Int32Type())
            return c.ConstInt(result_t, 1, False)
        if callee_name in {"__builtin_frame_address", "__builtin_return_address"}:
            arg = (
                self._cast_int_to_width(self._emit_expr(expr.args[0]), 32, signed=False)
                if expr.args
                else c.ConstInt(c.Int32Type(), 0, False)
            )
            intrinsic = (
                "llvm.frameaddress.p0"
                if callee_name == "__builtin_frame_address"
                else "llvm.returnaddress"
            )
            value = self._intrinsic_call(
                intrinsic,
                c.PointerType(c.Int8Type(), 0),
                [arg],
                [c.Int32Type()],
            )
            return self._coerce_builtin_result(value, expr)

        integer_result = self._integer_bit_builtin(callee_name, expr)
        if integer_result is not None:
            return integer_result
        return self._floating_builtin(callee_name, expr)

    # ── call ─────────────────────────────────────────────────

    def _call(self, expr: CallExpr) -> int:
        c = llvm()
        if isinstance(expr.callee, Identifier):
            callee_name = expr.callee.name
            assert isinstance(callee_name, str)

            if callee_name == "__builtin_unreachable":
                return c.GetUndef(c.VoidType())
            if callee_name == "__builtin_expect":
                return self._emit_expr(expr.args[0])
            if callee_name == "__builtin_constant_p":
                return c.ConstInt(c.Int32Type(), 0, False)
            if callee_name in ("__builtin_bzero", "__builtin_memset"):
                # Lower to direct LLVM memset call.
                args = expr.args
                if len(args) >= 3:
                    dst = self._emit_expr(args[0])
                    val = self._emit_expr(args[1])
                    ln = self._emit_expr(args[2])
                elif len(args) == 2:
                    dst = self._emit_expr(args[0])
                    val = c.ConstInt(c.Int8Type(), 0, False)
                    ln = self._emit_expr(args[1])
                else:
                    return c.ConstInt(c.Int32Type(), 0, False)
                return c.BuildMemSet(self._builder, dst, val, ln, False)
            if callee_name == "__builtin___memcpy_chk":
                args = expr.args
                if len(args) >= 3:
                    return self._build_memcpy_call(args[0], args[1], args[2])
                return c.ConstInt(c.Int32Type(), 0, False)
            if callee_name in {
                "__builtin_va_start",
                "__builtin_va_end",
                "__builtin_va_copy",
            }:
                return self._va_intrinsic_call(callee_name, tuple(expr.args))
            builtin_result = self._gcc_builtin_call(callee_name, expr)
            if builtin_result is not None:
                return builtin_result
            atomic_result = self._atomic_builtin_call(callee_name, tuple(expr.args))
            if atomic_result is not None:
                return atomic_result

            callee_type = self._type_map.get(expr.callee)
            if (
                callee_type is not None
                and not self._is_function_designator_type(callee_type)
                and callee_type.callable_signature() is not None
            ):
                return self._indirect_call(expr, callee_type)
            if callee_type is None:
                symbol_type = self._lookup_symbol_type(callee_name)
                if symbol_type is not None and symbol_type.callable_signature() is not None:
                    return self._indirect_call(expr, symbol_type)

            vals, types, arg_c_types = self._build_call_args(expr)
            fn = c.GetNamedFunction(self._mod, callee_name.encode())
            fn_t = self._func_types.get(callee_name)
            if fn is None or fn_t is None:
                return_type = self._type_map.get(expr) or INT
                ret_lt = self._type_to_llvm(return_type)
                callee_type = self._type_map.get(expr.callee)
                callable_signature = (
                    None if callee_type is None else callee_type.callable_signature()
                )
                is_variadic = False
                if callable_signature is None:
                    param_types = types
                else:
                    _return_type, params = callable_signature
                    parameter_types, is_variadic = params
                    param_types = [
                        self._type_to_llvm(pt)
                        for pt in (parameter_types or ())
                        if pt.name != "void" or pt.declarator_ops
                    ]
                n = len(param_types)
                param_ts = optional_zero_ptr_array(n)
                if param_ts is not None:
                    for i, t in enumerate(param_types):
                        param_ts[i] = t
                fn_t = c.FunctionType(ret_lt, param_ts, n, is_variadic)
                fn = c.AddFunction(self._mod, callee_name.encode(), fn_t)
                self._func_types[callee_name] = fn_t
                self._func_param_types[callee_name] = [param_types[i] for i in range(n)]
            vals = self._coerce_call_args(vals, callee_name, arg_c_types)
            args_arr = zero_ptr_array(len(vals))
            for i, v in enumerate(vals):
                args_arr[i] = v
            # Void-returning calls must not be named in LLVM IR.
            ret_kind = c.GetTypeKind(c.GetReturnType(fn_t))
            call_name = b"" if ret_kind == LLVMTypeKind.VOID else b"call"
            if len(vals) == 0:
                result = c.BuildCall2(self._builder, fn_t, fn, None, 0, call_name)
            else:
                result = c.BuildCall2(self._builder, fn_t, fn, args_arr, len(vals), call_name)
            # Void calls: return dummy value to avoid downstream void errors.
            if ret_kind == LLVMTypeKind.VOID:
                return c.ConstInt(c.Int32Type(), 0, False)
            return result

        return self._indirect_call(expr)

    def _indirect_call(self, expr: CallExpr, callee_type: Type | None = None) -> int:
        c = llvm()
        # Indirect call through function pointer.
        if callee_type is None:
            callee_type = self._type_map.require(expr.callee)
        elif self._type_map.get(expr.callee) is None:
            self._type_map.set(expr.callee, callee_type)
        callee_ptr = self._emit_expr(expr.callee)
        callable_signature = callee_type.callable_signature()
        if callable_signature is None:
            raise llvm_backend_error(self._result.filename, "Indirect call target is not callable")
        return_type, params = callable_signature
        parameter_types, is_var = params
        ret_lt = self._type_to_llvm(return_type)
        param_types = [
            self._type_to_llvm(pt)
            for pt in (parameter_types or ())
            if pt.name != "void" or pt.declarator_ops
        ]
        n = len(param_types)
        param_arr = optional_zero_ptr_array(n)
        if param_arr is not None:
            for i, lt in enumerate(param_types):
                param_arr[i] = lt
        fn_t = c.FunctionType(ret_lt, param_arr, n, is_var)

        vals, _types, arg_c_types = self._build_call_args(expr)
        # Coerce using extracted param types.
        for i, v in enumerate(vals):
            if i < n:
                pt = param_types[i]
                vt = c.TypeOf(v)
                pk = c.GetTypeKind(pt)
                vk = c.GetTypeKind(vt)
                if pk == LLVMTypeKind.INTEGER and vk == LLVMTypeKind.INTEGER:
                    vals[i] = self._cast_integer_value(v, pt, arg_c_types[i], b"arg.ext")
        args_arr = zero_ptr_array(len(vals))
        for i, v in enumerate(vals):
            args_arr[i] = v
        ret_kind = c.GetTypeKind(ret_lt)
        call_name = b"" if ret_kind == LLVMTypeKind.VOID else b"call"
        if len(vals) == 0:
            result = c.BuildCall2(self._builder, fn_t, callee_ptr, None, 0, call_name)
        else:
            result = c.BuildCall2(self._builder, fn_t, callee_ptr, args_arr, len(vals), call_name)
        if ret_kind == LLVMTypeKind.VOID:
            return c.ConstInt(c.Int32Type(), 0, False)
        return result

    def _lookup_symbol_type(self, name: str) -> Type | None:
        if self._func_sym is not None:
            symbol = self._func_sym.locals.get(name)
            if isinstance(symbol, VarSymbol):
                return symbol.type_
        if self._sema.file_scope is not None:
            symbol = self._sema.file_scope.lookup(name)
            if isinstance(symbol, VarSymbol):
                return symbol.type_
        return None

    # ── cast ─────────────────────────────────────────────────

    def _cast(self, expr: CastExpr) -> int:
        c = llvm()
        op = self._emit_expr(expr.expr)
        if not op:
            raise llvm_backend_error(self._result.filename, "Cast operand emitted null")
        result_type = self._type_map.require(expr)
        lt = self._type_to_llvm(result_type)
        from_t = c.TypeOf(op)

        if from_t == lt:
            return op

        from_kind = c.GetTypeKind(from_t)
        to_kind = c.GetTypeKind(lt)

        # Cast from void (e.g., (int)void_call()): return undef/null.
        if from_kind == LLVMTypeKind.VOID:
            if to_kind == LLVMTypeKind.POINTER:
                return c.ConstNull(lt)
            return c.GetUndef(lt)

        if result_type.name == "__builtin_va_list":
            return c.BuildBitCast(self._builder, op, lt, b"cast")

        # Cast to void: discard the value (no-op).
        if to_kind == LLVMTypeKind.VOID:
            return op

        # Array decay: cast to pointer.
        if from_kind == LLVMTypeKind.ARRAY and to_kind == LLVMTypeKind.POINTER:
            return self._build_cast(op, lt)

        # Pointer → Integer
        if from_kind == LLVMTypeKind.POINTER and to_kind != LLVMTypeKind.POINTER:
            return c.BuildPtrToInt(self._builder, op, lt, b"cast")
        # Integer → Pointer
        if from_kind != LLVMTypeKind.POINTER and to_kind == LLVMTypeKind.POINTER:
            return c.BuildIntToPtr(self._builder, op, lt, b"cast")
        # Float ↔ non-float: use bitcast
        from_is_float = self._is_float_kind(from_kind)
        to_is_float = self._is_float_kind(to_kind)

        if from_is_float and not to_is_float:
            return c.BuildFPToSI(self._builder, op, lt, b"cast")
        if not from_is_float and to_is_float:
            return c.BuildSIToFP(self._builder, op, lt, b"cast")
        if from_is_float and to_is_float:
            return c.BuildFPCast(self._builder, op, lt, b"cast")

        if from_kind == LLVMTypeKind.INTEGER and to_kind == LLVMTypeKind.INTEGER:
            operand_type = self._type_map.get(expr.expr)
            return self._cast_integer_value(op, lt, operand_type, b"cast")
        try:
            return c.BuildSExt(self._builder, op, lt, b"cast")
        except Exception:
            return c.BuildBitCast(self._builder, op, lt, b"cast")

    def _va_arg(self, expr: BuiltinVaArgExpr) -> int:
        c = llvm()
        ap = self._lvalue_addr(expr.ap)
        if ap is None:
            ap = self._emit_expr(expr.ap)
        result_type = self._resolve_type(expr.type_spec)
        lt = self._type_to_llvm(result_type)
        return c.BuildVAArg(self._builder, ap, lt, b"vaarg")

    def _va_intrinsic_call(self, callee_name: str, args: tuple[Expr, ...]) -> int:
        c = llvm()
        if not args:
            return c.ConstInt(c.Int32Type(), 0, False)
        ptr_t = c.PointerType(c.Int8Type(), 0)
        if callee_name == "__builtin_va_copy":
            if len(args) < 2:
                return c.ConstInt(c.Int32Type(), 0, False)
            intrinsic_name = "llvm.va_copy.p0"
            dst = self._lvalue_addr(args[0])
            src = self._lvalue_addr(args[1])
            if dst is None:
                dst = self._emit_expr(args[0])
            if src is None:
                src = self._emit_expr(args[1])
            values = [dst, src]
            param_types = [ptr_t, ptr_t]
        else:
            intrinsic_name = (
                "llvm.va_start.p0" if callee_name == "__builtin_va_start" else "llvm.va_end.p0"
            )
            ap = self._lvalue_addr(args[0])
            if ap is None:
                ap = self._emit_expr(args[0])
            values = [ap]
            param_types = [ptr_t]
        n = len(values)
        params = zero_ptr_array(n)
        vals = zero_ptr_array(n)
        for i, value in enumerate(values):
            params[i] = param_types[i]
            vals[i] = value
        fn_t = c.FunctionType(c.VoidType(), params, n, False)
        fn = c.GetNamedFunction(self._mod, intrinsic_name.encode())
        if not fn:
            fn = c.AddFunction(self._mod, intrinsic_name.encode(), fn_t)
        c.BuildCall2(self._builder, fn_t, fn, vals, n, b"")
        return c.ConstInt(c.Int32Type(), 0, False)

    # ── subscript / member ───────────────────────────────────

    def _subscript(self, expr: SubscriptExpr) -> int:
        c = llvm()
        ptr = self._subscript_ptr(expr)
        elem_t = self._type_map.require(expr)
        lt = self._type_to_llvm(elem_t)
        return c.BuildLoad2(self._builder, lt, ptr, b"sub.load")

    def _subscript_ptr(self, expr: SubscriptExpr) -> int:
        c = llvm()
        idx = self._emit_expr(expr.index)
        idx = self._gep_index_value(idx, self._type_map.get(expr.index), b"sub.idx")
        base_t = self._type_map.require(expr.base)
        if base_t.is_array():
            base = self._array_base_pointer(expr.base)
            base_lt = self._type_to_llvm(base_t)
            zero = c.ConstInt(c.Int64Type(), 0, False)
            indices = ptr_array([zero, idx])
            return c.BuildGEP2(self._builder, base_lt, base, indices, 2, b"sub.ptr")

        base = self._emit_expr(expr.base)
        indices = ptr_array([idx])
        elem_t = self._type_map.require(expr)
        lt = self._type_to_llvm(elem_t)
        return c.BuildGEP2(self._builder, lt, base, indices, 1, b"sub.ptr")

    def _array_base_pointer(self, expr: Expr) -> int:
        c = llvm()
        if isinstance(expr, Identifier):
            name = expr.name
            assert isinstance(name, str)
            local = self._lookup_local(name)
            if local is not None:
                return local
            gv = c.GetNamedGlobal(self._mod, name.encode())
            if not gv:
                val_type = self._type_map.require(expr)
                gv = self._global_var_ref(name, val_type)
            return gv

        base = self._emit_expr(expr)
        base_kind = c.GetTypeKind(c.TypeOf(base))
        if base_kind == LLVMTypeKind.ARRAY:
            tmp = c.BuildAlloca(self._builder, c.TypeOf(base), b"sub.tmp")
            c.BuildStore(self._builder, base, tmp)
            return tmp
        return base

    def _member(self, expr: MemberExpr) -> int:
        c = llvm()
        ptr = self._member_ptr(expr)
        val_t = self._type_map.require(expr)
        if val_t.is_array():
            return ptr
        lt = self._type_to_llvm(val_t)
        return c.BuildLoad2(self._builder, lt, ptr, b"mem.load")

    def _member_ptr(self, expr: MemberExpr) -> int:
        c = llvm()
        base_t = self._type_map.require(expr.base)

        if expr.through_pointer:
            base = self._emit_expr(expr.base)
            pointee = base_t.pointee()
            if pointee is None:
                if not base_t.declarator_ops and base_t.name.startswith(("struct ", "union ")):
                    struct_t = base_t
                    struct_ptr = self._lvalue_addr(expr.base)
                    if struct_ptr is None:
                        lt = self._type_to_llvm(struct_t)
                        tmp = c.BuildAlloca(self._builder, lt, b"mem.tmp")
                        c.BuildStore(self._builder, base, tmp)
                        struct_ptr = tmp
                else:
                    raise llvm_backend_error(
                        self._result.filename, "Cannot deref non-ptr in member"
                    )
            else:
                struct_t = pointee
                struct_ptr = base
        else:
            struct_t = base_t
            struct_ptr = self._lvalue_addr(expr.base)
            if struct_ptr is None:
                struct_value = self._emit_expr(expr.base)
                lt = self._type_to_llvm(struct_t)
                tmp = c.BuildAlloca(self._builder, lt, b"mem.tmp")
                c.BuildStore(self._builder, struct_value, tmp)
                struct_ptr = tmp

        record_name = struct_t.name
        path = self._member_path(record_name, expr.member)
        if path is None:
            raise llvm_backend_error(
                self._result.filename,
                f"Record '{record_name}' has no member '{expr.member}'",
            )
        zero = c.ConstInt(c.Int32Type(), 0, False)
        ptr = struct_ptr
        for step_record, field_idx, _member in path:
            if step_record.startswith("union "):
                continue
            st = self._struct_type(step_record)
            fi = c.ConstInt(c.Int32Type(), field_idx, False)
            indices = ptr_array([zero, fi])
            ptr = c.BuildGEP2(self._builder, st, ptr, indices, 2, b"mem.ptr")
        return ptr

    def _lvalue_addr(self, expr: Expr) -> int | None:
        c = llvm()
        if isinstance(expr, Identifier):
            name = expr.name
            assert isinstance(name, str)
            local = self._lookup_local(name)
            if local is not None:
                return local
            gv = c.GetNamedGlobal(self._mod, name.encode())
            if gv:
                return gv
            value_type = self._type_map.get(expr) or self._lookup_symbol_type(name)
            if value_type is not None and not self._is_function_designator_type(value_type):
                return self._global_var_ref(name, value_type)
        if isinstance(expr, MemberExpr):
            return self._member_ptr(expr)
        if isinstance(expr, SubscriptExpr):
            return self._subscript_ptr(expr)
        if isinstance(expr, CompoundLiteralExpr):
            return self._compound_literal_addr(expr)
        if isinstance(expr, UnaryExpr) and expr.op == "*":
            return self._emit_expr(expr.operand)
        return None

    def _build_cast(self, val: int, to_type: int, from_c_type: Type | None = None) -> int:
        c = llvm()
        from_type = c.TypeOf(val)
        fk = c.GetTypeKind(from_type)
        tk = c.GetTypeKind(to_type)
        if from_type == to_type:
            return val
        if tk == LLVMTypeKind.INTEGER and c.GetIntTypeWidth(to_type) == 1:
            return self._to_bool(val)
        if fk == tk and fk != LLVMTypeKind.INTEGER:
            if self._is_float_kind(fk) and self._is_float_kind(tk):
                return c.BuildFPCast(self._builder, val, to_type, b"cast")
            return val  # Same non-integer kind: no cast needed
        if fk == LLVMTypeKind.ARRAY:
            # Array decay: returns pointer to first element.
            # For value-type arrays (loaded from memory/alloca), we need
            # to store to an alloca and GEP.  Zero-length arrays get a
            # null pointer (they have no valid storage).
            elem_count = c.GetArrayLength(from_type)
            if elem_count == 0:
                return c.ConstNull(to_type)
            tmp = c.BuildAlloca(self._builder, from_type, b"cast.tmp")
            c.BuildStore(self._builder, val, tmp)
            zero = c.ConstInt(c.Int32Type(), 0, False)
            idx = ptr_array([zero, zero])
            return c.BuildGEP2(self._builder, from_type, tmp, idx, 2, b"cast.gep")
        if fk == LLVMTypeKind.POINTER and tk == LLVMTypeKind.INTEGER:
            return c.BuildPtrToInt(self._builder, val, to_type, b"cast")
        if fk == LLVMTypeKind.INTEGER and tk == LLVMTypeKind.POINTER:
            return c.BuildIntToPtr(self._builder, val, to_type, b"cast")
        if self._is_float_kind(fk) and not self._is_float_kind(tk):
            return c.BuildFPToSI(self._builder, val, to_type, b"cast")
        if not self._is_float_kind(fk) and self._is_float_kind(tk):
            return c.BuildSIToFP(self._builder, val, to_type, b"cast")
        if self._is_float_kind(fk) and self._is_float_kind(tk):
            return c.BuildFPCast(self._builder, val, to_type, b"cast")
        if fk == LLVMTypeKind.INTEGER and tk == LLVMTypeKind.INTEGER:
            return self._cast_integer_value(val, to_type, from_c_type, b"cast")
        return c.BuildBitCast(self._builder, val, to_type, b"cast")

    # ── ternary ──────────────────────────────────────────────

    def _ternary(self, expr: ConditionalExpr) -> int:
        c = llvm()
        fn = self._func
        cond = self._to_bool(self._emit_expr(expr.condition))
        result_type = self._type_map.require(expr)
        phi_type = self._type_to_llvm(result_type)
        phi_is_void = c.GetTypeKind(phi_type) == LLVMTypeKind.VOID

        then_bb = c.AppendBasicBlock(fn, b"tern.then")
        else_bb = c.AppendBasicBlock(fn, b"tern.else")
        merge_bb = c.AppendBasicBlock(fn, b"tern.end")

        c.BuildCondBr(self._builder, cond, then_bb, else_bb)

        c.PositionBuilderAtEnd(self._builder, then_bb)
        then_val = self._emit_expr(expr.then_expr)
        if not phi_is_void and c.TypeOf(then_val) != phi_type:
            then_val = self._build_cast(then_val, phi_type)
        then_incoming_bb = c.GetInsertBlock(self._builder)
        if self._bb_needs_term(then_incoming_bb):
            c.BuildBr(self._builder, merge_bb)

        c.PositionBuilderAtEnd(self._builder, else_bb)
        else_val = self._emit_expr(expr.else_expr)
        if not phi_is_void and c.TypeOf(else_val) != phi_type:
            else_val = self._build_cast(else_val, phi_type)
        else_incoming_bb = c.GetInsertBlock(self._builder)
        if self._bb_needs_term(else_incoming_bb):
            c.BuildBr(self._builder, merge_bb)

        c.PositionBuilderAtEnd(self._builder, merge_bb)
        if phi_is_void:
            # Void-typed ternary (e.g., assert-like macros): no phi needed.
            return c.GetUndef(c.Int32Type())
        phi = c.BuildPhi(self._builder, phi_type, b"tern")
        vals = ptr_array([then_val, else_val])
        bbs = ptr_array([then_incoming_bb, else_incoming_bb])
        c.AddIncoming(phi, vals, bbs, 2)
        return phi

    # ── statement expr ───────────────────────────────────────

    def _stmt_expr(self, expr: StatementExpr) -> int:
        self._locals.append({})
        allocas = self._collect_allocas(expr.body)
        c = llvm()
        for vname, vtype in allocas:
            lt = self._type_to_llvm(vtype)
            a = c.BuildAlloca(self._builder, lt, f"{vname}.addr".encode())
            self._locals[-1][vname] = a

        stmts = expr.body.statements
        if not stmts:
            self._locals.pop()
            return c.ConstInt(c.Int32Type(), 0, False)
        for s in stmts[:-1]:
            self._emit_stmt(s)
        last = stmts[-1]
        if isinstance(last, ExprStmt):
            result = self._emit_expr(last.expr)
        else:
            self._emit_stmt(last)
            result = c.ConstInt(c.Int32Type(), 0, False)
        self._locals.pop()
        return result

    # ── compound literal ─────────────────────────────────────

    def _compound_literal(self, expr: CompoundLiteralExpr) -> int:
        c = llvm()
        result_t = self._type_map.require(expr)
        tmp = self._compound_literal_addr(expr)
        if result_t.is_array():
            return tmp
        lt = self._type_to_llvm(result_t)
        return c.BuildLoad2(self._builder, lt, tmp, b"compound.load")

    def _compound_literal_addr(self, expr: CompoundLiteralExpr) -> int:
        c = llvm()
        result_t = self._type_map.require(expr)
        lt = self._type_to_llvm(result_t)
        tmp = c.BuildAlloca(self._builder, lt, b"compound.lit")
        if isinstance(expr.initializer, InitList):
            self._emit_init_list_to_addr(tmp, result_t, expr.initializer)
        else:
            val = self._emit_expr(expr.initializer)
            c.BuildStore(self._builder, val, tmp)
        return tmp

    # ── sizeof / alignof ─────────────────────────────────────

    def _size_const(self, expr: SizeofExpr | AlignofExpr) -> int:
        c = llvm()
        # Use the type_spec from the expression (the type being queried),
        # not the result type of the sizeof expression itself.
        if expr.type_spec is not None:
            result_t = self._resolve_type(expr.type_spec)
        else:
            assert expr.expr is not None
            result_t = self._type_map.require(expr.expr)
        size = self._type_size(result_t)
        return c.ConstInt(c.Int64Type(), size, False)

    def _offsetof_expr(self, expr: BuiltinOffsetofExpr) -> int:
        c = llvm()
        offset = self._offsetof_value(expr)
        return c.ConstInt(c.Int64Type(), 0 if offset is None else offset, False)

    # ── helpers ──────────────────────────────────────────────

    def _build_memcpy_call(self, dst_arg, src_arg, len_arg) -> int:
        """Lower memcpy-like intrinsic to LLVM memcpy."""
        c = llvm()
        dst = self._emit_expr(dst_arg)
        src = self._emit_expr(src_arg)
        ln = self._emit_expr(len_arg)
        return c.BuildMemCpy(self._builder, dst, 1, src, 1, ln)

    def _to_bool(self, val: int) -> int:
        c = llvm()
        t = c.TypeOf(val)
        k = c.GetTypeKind(t)
        # Array decay: arrays can't be compared directly.
        if k == LLVMTypeKind.ARRAY:
            val = self._build_cast(val, c.PointerType(c.Int8Type(), 0))
            t = c.TypeOf(val)
            k = c.GetTypeKind(t)
        name = b"tobool"
        if k == LLVMTypeKind.POINTER:
            return c.BuildICmp(self._builder, 33, val, c.ConstNull(t), name)
        if self._is_float_kind(k):
            return c.BuildFCmp(self._builder, 6, val, c.ConstReal(t, 0.0), name)
        return c.BuildICmp(self._builder, 33, val, c.ConstInt(t, 0, False), name)

    def _resolve_type(self, ts: TypeSpec) -> Type:
        resolved_ops = self._resolve_declarator_ops(ts.declarator_ops)
        if ts.name == "typeof" and ts.typeof_expr is not None:
            base_type = self._type_map.get(ts.typeof_expr)
            if base_type is None:
                raise llvm_backend_error(self._result.filename, "Unknown typeof expression type")
            for kind, value in resolved_ops:
                if kind == "ptr":
                    base_type = base_type.pointer_to()
                elif kind == "arr":
                    assert isinstance(value, int)
                    base_type = base_type.array_of(value)
                elif kind == "fn":
                    assert isinstance(value, tuple)
                    base_type = base_type.function_of(value[0], is_variadic=value[1])
            return base_type
        if ts.name in {"struct", "union"}:
            name = self._record_name_for_type_spec(ts)
        elif ts.name == "enum":
            name = "int"
        elif ts.name == "bool":
            name = "_Bool"
        elif self._sema.file_scope is not None:
            typedef_type = self._sema.file_scope.lookup_typedef(ts.name)
            if typedef_type is not None:
                qualifiers = tuple(dict.fromkeys((*typedef_type.qualifiers, *ts.qualifiers)))
                return Type(
                    typedef_type.name,
                    declarator_ops=resolved_ops + typedef_type.declarator_ops,
                    qualifiers=qualifiers,
                )
            name = ts.name
        else:
            name = ts.name
        return Type(name, declarator_ops=resolved_ops, qualifiers=ts.qualifiers)

    def _resolve_declarator_ops(self, ops: tuple[DeclaratorOp, ...]) -> tuple[TypeOp, ...]:
        resolved: list[TypeOp] = []
        for kind, value in ops:
            if kind == "arr":
                if isinstance(value, ArrayDecl):
                    if value.length is None:
                        length = -1
                    elif isinstance(value.length, int):
                        length = value.length
                    else:
                        evaluated = self._eval_int_constant_value(value.length)
                        length = evaluated if evaluated is not None else -1
                else:
                    assert isinstance(value, int)
                    length = value
                resolved.append((kind, length))
                continue
            if kind == "fn":
                assert isinstance(value, tuple) and len(value) == 2
                param_specs, is_variadic = value
                assert param_specs is None or isinstance(param_specs, tuple)
                assert isinstance(is_variadic, bool)
                params: tuple[Type, ...] | None = None
                if param_specs is not None:
                    resolved_params: list[Type] = []
                    for param_spec in param_specs:
                        assert isinstance(param_spec, TypeSpec)
                        resolved_params.append(
                            self._resolve_type(param_spec).decay_parameter_type()
                        )
                    params = tuple(resolved_params)
                function_params: FunctionParams = (params, is_variadic)
                resolved.append((kind, function_params))
                continue
            assert isinstance(value, int)
            resolved.append((kind, value))
        return tuple(resolved)

    def _record_name_for_type_spec(self, ts: TypeSpec) -> str:
        if ts.record_tag is not None:
            return f"{ts.name} {ts.record_tag}"
        if ts.record_members:
            for record_name, members in self._sema.record_definitions.items():
                if not record_name.startswith(f"{ts.name} <anon:"):
                    continue
                if len(members) != len(ts.record_members):
                    continue
                matched = True
                for decl, member in zip(ts.record_members, members, strict=True):
                    if decl.name != member.name:
                        matched = False
                        break
                    if self._resolve_type(decl.type_spec) != member.type_:
                        matched = False
                        break
                if matched:
                    return record_name
        return ts.name

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
            if stmt.storage_class in {"static", "extern"}:
                return
            if stmt.name and stmt.name not in seen:
                seen.add(stmt.name)
                sym = self._func_sym.locals.get(stmt.name) if self._func_sym is not None else None
                if isinstance(sym, VarSymbol):
                    result.append((stmt.name, sym.type_))
                else:
                    result.append((stmt.name, self._resolve_type(stmt.type_spec)))
        elif isinstance(stmt, DeclGroupStmt):
            for d in stmt.declarations:
                self._walk_allocas(d, result, seen)
        elif isinstance(stmt, IfStmt):
            self._walk_allocas(stmt.then_body, result, seen)
            if stmt.else_body:
                self._walk_allocas(stmt.else_body, result, seen)
        elif isinstance(stmt, (WhileStmt, DoWhileStmt, ForStmt)):
            body = getattr(stmt, "body", None)
            if body:
                self._walk_allocas(body, result, seen)
        elif isinstance(stmt, (SwitchStmt, LabelStmt)):
            self._walk_allocas(stmt.body, result, seen)
        elif isinstance(stmt, ExprStmt):
            self._walk_allocas_expr(stmt.expr, result, seen)

    def _walk_allocas_expr(
        self, expr: Expr, result: list[tuple[str, Type]], seen: set[str]
    ) -> None:
        if isinstance(expr, StatementExpr):
            self._walk_allocas(expr.body, result, seen)

    def _eval_init(self, init: Expr | InitList, var_type: Type) -> int | None:
        c = llvm()
        lt = self._type_to_llvm(var_type)
        if isinstance(init, InitList):
            if var_type.is_array():
                return self._eval_array_init(init, var_type)
            if self._is_record_type(var_type):
                return self._eval_record_init(init, var_type)
            if len(init.items) == 1 and not init.items[0].designators:
                return self._eval_init(init.items[0].initializer, var_type)
            return None
        if isinstance(init, StringLiteral) and self._is_char_array_type(var_type):
            return self._string_array_initializer(init, var_type)
        if self._is_record_type(var_type):
            return self._eval_scalar_record_init(init, var_type)
        lt_kind = c.GetTypeKind(lt)
        if isinstance(init, IntLiteral) and lt_kind == LLVMTypeKind.INTEGER:
            return c.ConstInt(lt, self._parse_int_value(init.value), False)
        if isinstance(init, CharLiteral) and lt_kind == LLVMTypeKind.INTEGER:
            return c.ConstInt(lt, self._char_value(init.value), False)
        if isinstance(init, FloatLiteral) and self._is_float_kind(lt_kind):
            v = init.value
            if v and v[-1] in "fFlL":
                v = v[:-1]
            return c.ConstReal(lt, float.fromhex(v) if v.startswith(("0x", "0X")) else float(v))
        value = self._eval_const_expr(init, var_type)
        if value is None:
            return None
        return self._const_cast(value, lt)

    @staticmethod
    def _is_record_type(type_: Type) -> bool:
        return not type_.declarator_ops and type_.name.startswith(("struct ", "union "))

    def _infer_array_init_length(self, init: InitList) -> int:
        max_index = 0
        next_index = 0
        for item in init.items:
            if item.designators:
                kind, value = item.designators[0]
                if kind == "index" and isinstance(value, Expr):
                    index = self._eval_int_constant_value(value)
                    next_index = 0 if index is None else index + 1
                elif kind == "range" and isinstance(value, DesignatorRange):
                    high = self._eval_int_constant_value(value.high)
                    next_index = 0 if high is None else high + 1
                else:
                    next_index += 1
            else:
                next_index += 1
            max_index = max(max_index, next_index)
        return max_index

    def _flexible_array_member_overrides(
        self,
        record_type: Type,
        init: InitList,
    ) -> dict[int, Type] | None:
        if record_type.declarator_ops or not record_type.name.startswith("struct "):
            return None
        members = self._sema.record_definitions.get(record_type.name)
        if not members:
            return None
        last_index = len(members) - 1
        flexible_member = members[last_index]
        flexible_type = flexible_member.type_
        if not flexible_type.is_array():
            return None
        length_value = flexible_type.declarator_ops[0][1]
        if isinstance(length_value, int) and length_value > 0:
            return None
        member_init = self._record_member_initializer(init, record_type.name, last_index)
        if member_init is None:
            return None
        length = self._infer_flexible_array_init_length(member_init, flexible_type)
        if length <= 0:
            return None
        flexible_ops = (("arr", length),) + flexible_type.declarator_ops[1:]
        adjusted = Type(
            flexible_type.name,
            declarator_ops=flexible_ops,
            qualifiers=flexible_type.qualifiers,
        )
        return {last_index: adjusted}

    def _record_member_initializer(
        self,
        init: InitList,
        record_name: str,
        target_index: int,
    ) -> Expr | InitList | None:
        members = self._sema.record_definitions.get(record_name)
        if not members:
            return None
        next_member = 0
        designated_items: list[InitItem] = []
        for item in init.items:
            if item.designators:
                kind, value = item.designators[0]
                if kind != "member" or not isinstance(value, str):
                    continue
                path = self._member_path(record_name, value)
                if path is None or path[0][1] != target_index:
                    continue
                if item.designators[1:]:
                    designated_items.append(InitItem(item.designators[1:], item.initializer))
                    continue
                return item.initializer
            else:
                if next_member == target_index:
                    return item.initializer
                next_member += 1
        if designated_items:
            return InitList(tuple(designated_items))
        return None

    def _infer_flexible_array_init_length(
        self,
        init: Expr | InitList,
        array_type: Type,
    ) -> int:
        if isinstance(init, InitList):
            return self._infer_array_init_length(init)
        if isinstance(init, StringLiteral) and self._is_char_array_type(array_type):
            return len(self._string_literal_bytes(init))
        return 1

    def _struct_type_with_member_overrides(
        self,
        record_name: str,
        member_type_overrides: dict[int, Type],
    ) -> int:
        c = llvm()
        members = self._sema.record_definitions.get(record_name)
        if not members:
            return self._type_to_llvm(Type(record_name))
        member_types = zero_ptr_array(len(members))
        for index, member in enumerate(members):
            member_type = member_type_overrides.get(index, member.type_)
            member_types[index] = self._record_field_llvm_type(member_type)
        return c.StructType(member_types, len(members), False)

    def _eval_array_init(self, init: InitList, array_type: Type) -> int | None:
        c = llvm()
        elem_type = array_type.element_type()
        if elem_type is None:
            return None
        length_value = array_type.declarator_ops[0][1]
        if not isinstance(length_value, int):
            return None
        length = max(length_value, 0)
        elem_lt = self._type_to_llvm(elem_type)
        elems = [c.ConstNull(elem_lt) for _ in range(length)]
        next_index = 0
        for item in init.items:
            if item.designators:
                kind, value = item.designators[0]
                if kind == "range":
                    if not isinstance(value, DesignatorRange):
                        return None
                    low = self._eval_int_constant_value(value.low)
                    high = self._eval_int_constant_value(value.high)
                    if low is None or high is None:
                        return None
                    for index in range(low, high + 1):
                        if 0 <= index < length:
                            val = self._eval_designated_init(
                                elem_type,
                                item.designators[1:],
                                item.initializer,
                            )
                            if val is None:
                                continue
                            elems[index] = val
                    next_index = high + 1
                    continue
                if kind != "index" or not isinstance(value, Expr):
                    return None
                designated_index = self._eval_int_constant_value(value)
                if designated_index is None:
                    return None
                if 0 <= designated_index < length:
                    val = self._eval_designated_init(
                        elem_type,
                        item.designators[1:],
                        item.initializer,
                    )
                    if val is None:
                        continue
                    elems[designated_index] = val
                next_index = designated_index + 1
                continue
            if next_index >= length:
                continue
            val = self._eval_init(item.initializer, elem_type)
            if val is None:
                next_index += 1
                continue
            elems[next_index] = val
            next_index += 1
        return self._const_array(elem_lt, elems)

    def _eval_record_init(
        self,
        init: InitList,
        record_type: Type,
        member_type_overrides: dict[int, Type] | None = None,
        record_lt: int | None = None,
    ) -> int | None:
        c = llvm()
        members = self._sema.record_definitions.get(record_type.name)
        if members is None:
            return None
        if not members:
            return c.ConstNull(self._type_to_llvm(record_type))
        overrides = member_type_overrides or {}

        def member_type(index: int) -> Type:
            return overrides.get(index, members[index].type_)

        next_member = 0
        union_member: RecordMemberInfo | None = None
        union_value: int | None = None
        initialized_union = False
        is_union = record_type.name.startswith("union ")
        fields = (
            []
            if is_union
            else [c.ConstNull(self._type_to_llvm(member_type(i))) for i in range(len(members))]
        )
        nested_items: dict[int, list[InitItem]] = {}
        nested_order: list[int] = []
        for item in init.items:
            if item.designators:
                kind, value = item.designators[0]
                if kind != "member" or not isinstance(value, str):
                    return None
                path = self._member_path(record_type.name, value)
                if path is None:
                    return None
                remaining_designators = item.designators[1:]
                if remaining_designators or (len(path) > 1 and path[0][2].name is None):
                    member_index = path[0][1]
                    if member_index not in nested_items:
                        nested_items[member_index] = []
                        nested_order.append(member_index)
                    nested_designators = (
                        item.designators if path[0][2].name is None else remaining_designators
                    )
                    nested_items[member_index].append(
                        InitItem(nested_designators, item.initializer)
                    )
                    if is_union:
                        initialized_union = True
                    else:
                        next_member = member_index + 1
                    continue
                if len(path) > 1:
                    val = self._eval_record_path_init(
                        path[1:],
                        item.designators[1:],
                        item.initializer,
                    )
                elif item.designators[1:]:
                    val = self._eval_init(
                        InitList((InitItem(item.designators[1:], item.initializer),)),
                        member_type(path[0][1]),
                    )
                else:
                    val = self._eval_init(item.initializer, member_type(path[0][1]))
                if val is None:
                    continue
                if is_union:
                    union_member = path[0][2]
                    union_value = val
                    initialized_union = True
                else:
                    fields[path[0][1]] = val
                    next_member = path[0][1] + 1
                continue
            if is_union:
                if initialized_union:
                    continue
                member_index = 0
                initialized_union = True
            else:
                if next_member >= len(members):
                    continue
                member_index = next_member
                next_member += 1
            val = self._eval_init(item.initializer, member_type(member_index))
            if val is None:
                continue
            if is_union:
                union_member = members[member_index]
                union_value = val
            else:
                fields[member_index] = val
        for member_index in nested_order:
            member = members[member_index]
            val = self._eval_init(
                InitList(tuple(nested_items[member_index])),
                member_type(member_index),
            )
            if val is None:
                continue
            if is_union:
                union_member = member
                union_value = val
            else:
                fields[member_index] = val
        if is_union:
            if union_member is None or union_value is None:
                return c.ConstNull(self._type_to_llvm(record_type))
            return self._const_union(record_type, union_member, union_value)
        return self._const_struct(record_type, fields, record_lt)

    def _eval_scalar_record_init(self, init: Expr, record_type: Type) -> int | None:
        c = llvm()
        members = self._sema.record_definitions.get(record_type.name)
        if not members:
            return c.ConstNull(self._type_to_llvm(record_type))
        val = self._eval_init(init, members[0].type_)
        if val is None:
            return None
        if record_type.name.startswith("union "):
            return self._const_union(record_type, members[0], val)
        fields = [c.ConstNull(self._type_to_llvm(member.type_)) for member in members]
        fields[0] = val
        return self._const_struct(record_type, fields)

    def _eval_record_path_init(
        self,
        path: list[tuple[str, int, RecordMemberInfo]],
        designators: tuple[tuple[str, Expr | str | DesignatorRange], ...],
        initializer: Expr | InitList,
    ) -> int | None:
        c = llvm()
        record_name, field_index, member = path[0]
        record_type = Type(record_name)
        members = self._sema.record_definitions.get(record_name)
        if members is None:
            return None
        fields = [c.ConstNull(self._type_to_llvm(item.type_)) for item in members]
        if len(path) > 1:
            val = self._eval_record_path_init(path[1:], designators, initializer)
        elif designators:
            val = self._eval_init(InitList((InitItem(designators, initializer),)), member.type_)
        else:
            val = self._eval_init(initializer, member.type_)
        if val is None:
            return None
        if record_name.startswith("union "):
            return self._const_union(record_type, member, val)
        fields[field_index] = val
        return self._const_struct(record_type, fields)

    def _eval_designated_init(
        self,
        target_type: Type,
        designators: tuple[tuple[str, Expr | str | DesignatorRange], ...],
        initializer: Expr | InitList,
    ) -> int | None:
        if not designators:
            return self._eval_init(initializer, target_type)
        return self._eval_init(InitList((InitItem(designators, initializer),)), target_type)

    def _const_array(self, elem_lt: int, values: list[int]) -> int:
        c = llvm()
        if not values:
            return c.ConstArray(elem_lt, None, 0)
        arr = zero_ptr_array(len(values))
        for index, value in enumerate(values):
            arr[index] = value
        return c.ConstArray(elem_lt, arr, len(values))

    def _const_struct(
        self,
        record_type: Type,
        fields: list[int],
        record_lt: int | None = None,
    ) -> int:
        c = llvm()
        lt = record_lt if record_lt is not None else self._type_to_llvm(record_type)
        if not fields:
            return c.ConstNull(lt)
        arr = zero_ptr_array(len(fields))
        for index, value in enumerate(fields):
            arr[index] = value
        return c.ConstNamedStruct(lt, arr, len(fields))

    def _const_union(
        self,
        record_type: Type,
        active_member: RecordMemberInfo,
        value: int,
    ) -> int:
        c = llvm()
        members = self._sema.record_definitions.get(record_type.name)
        if not members:
            return c.ConstNull(self._type_to_llvm(record_type))
        storage_member = self._union_storage_member(members)
        storage_type = self._record_member_llvm_type(storage_member)
        if c.TypeOf(value) == storage_type:
            storage_value = value
        else:
            converted = self._coerce_union_storage_value(
                value,
                active_member,
                storage_member,
                storage_type,
            )
            if converted is None:
                return c.ConstNull(self._type_to_llvm(record_type))
            storage_value = converted
        fields = [storage_value]
        padding = self._union_size(record_type.name) - self._type_size(storage_member.type_)
        if padding > 0:
            fields.append(c.ConstNull(c.ArrayType(c.Int8Type(), padding)))
        return self._const_struct(record_type, fields)

    def _coerce_union_storage_value(
        self,
        value: int,
        active_member: RecordMemberInfo,
        storage_member: RecordMemberInfo,
        storage_type: int,
    ) -> int | None:
        c = llvm()
        value_type = c.TypeOf(value)
        if (
            c.GetTypeKind(value_type) == LLVMTypeKind.POINTER
            and c.GetTypeKind(storage_type) == LLVMTypeKind.POINTER
        ):
            return c.ConstPointerCast(value, storage_type)
        if (
            c.GetTypeKind(value_type) == LLVMTypeKind.INTEGER
            and c.GetTypeKind(storage_type) == LLVMTypeKind.INTEGER
            and c.IsAConstantInt(value)
        ):
            signed = not active_member.type_.name.startswith("unsigned ")
            raw = c.ConstIntGetSExtValue(value) if signed else c.ConstIntGetZExtValue(value)
            return c.ConstInt(storage_type, raw, raw < 0)
        data = self._const_value_bytes(value, active_member.type_)
        if data is None:
            return None
        return self._const_from_bytes(data, storage_member.type_, storage_type)

    def _const_value_bytes(self, value: int, value_type: Type) -> bytes | None:
        c = llvm()
        size = self._type_size(value_type)
        if size == 0:
            return b""
        if c.IsNull(value):
            return bytes(size)
        if value_type.declarator_ops:
            kind, length_value = value_type.declarator_ops[0]
            if kind == "arr":
                if not isinstance(length_value, int):
                    return None
                elem_type = value_type.element_type()
                if elem_type is None:
                    return None
                elem_size = self._type_size(elem_type)
                chunks: list[bytes] = []
                operand_count = c.GetNumOperands(value)
                elem_lt = self._type_to_llvm(elem_type)
                for index in range(max(length_value, 0)):
                    elem_value = (
                        c.GetOperand(value, index)
                        if index < operand_count
                        else c.ConstNull(elem_lt)
                    )
                    elem_data = self._const_value_bytes(elem_value, elem_type)
                    if elem_data is None:
                        return None
                    chunks.append(elem_data[:elem_size].ljust(elem_size, b"\0"))
                return b"".join(chunks)
            return None
        if value_type.name.startswith("struct "):
            return self._const_struct_bytes(value, value_type.name)
        if value_type.name.startswith("union "):
            return self._const_union_bytes(value, value_type.name)
        if is_integer_type(value_type) and c.IsAConstantInt(value):
            raw = c.ConstIntGetZExtValue(value)
            mask = (1 << (size * 8)) - 1
            return (raw & mask).to_bytes(size, "little")
        return None

    def _const_struct_bytes(self, value: int, record_name: str) -> bytes | None:
        c = llvm()
        members = self._sema.record_definitions.get(record_name)
        if members is None:
            return None
        data = bytearray(self._record_size(record_name))
        operand_count = c.GetNumOperands(value)
        offset = 0
        for index, member in enumerate(members):
            member_align = self._member_align(member)
            offset = self._align_to(offset, member_align)
            member_size = self._type_size(member.type_)
            member_value = (
                c.GetOperand(value, index)
                if index < operand_count
                else c.ConstNull(self._record_member_llvm_type(member))
            )
            member_data = self._const_value_bytes(member_value, member.type_)
            if member_data is None:
                return None
            data[offset : offset + member_size] = member_data[:member_size].ljust(
                member_size,
                b"\0",
            )
            offset += member_size
        return bytes(data)

    def _const_union_bytes(self, value: int, record_name: str) -> bytes | None:
        c = llvm()
        members = self._sema.record_definitions.get(record_name)
        if not members:
            return bytes(self._union_size(record_name))
        storage_member = self._union_storage_member(members)
        storage_size = self._type_size(storage_member.type_)
        operand_count = c.GetNumOperands(value)
        storage_value = (
            c.GetOperand(value, 0)
            if operand_count
            else c.ConstNull(self._record_member_llvm_type(storage_member))
        )
        storage_data = self._const_value_bytes(storage_value, storage_member.type_)
        if storage_data is None:
            return None
        return storage_data[:storage_size].ljust(self._union_size(record_name), b"\0")

    def _const_from_bytes(
        self,
        data: bytes,
        target_type: Type,
        target_lt: int | None = None,
    ) -> int | None:
        c = llvm()
        size = self._type_size(target_type)
        chunk = data[:size].ljust(size, b"\0")
        if target_type.declarator_ops:
            kind, length_value = target_type.declarator_ops[0]
            if kind == "arr":
                if not isinstance(length_value, int):
                    return None
                elem_type = target_type.element_type()
                if elem_type is None:
                    return None
                elem_size = self._type_size(elem_type)
                elem_lt = self._type_to_llvm(elem_type)
                values: list[int] = []
                for index in range(max(length_value, 0)):
                    offset = index * elem_size
                    elem = self._const_from_bytes(
                        chunk[offset : offset + elem_size],
                        elem_type,
                        elem_lt,
                    )
                    if elem is None:
                        return None
                    values.append(elem)
                return self._const_array(elem_lt, values)
            if kind == "ptr":
                if any(chunk):
                    return None
                lt = target_lt if target_lt is not None else self._type_to_llvm(target_type)
                return c.ConstPointerNull(lt)
            return None
        if target_type.name.startswith("struct "):
            return self._const_struct_from_bytes(chunk, target_type.name, target_lt)
        if target_type.name.startswith("union "):
            return self._const_union_from_bytes(chunk, target_type.name, target_lt)
        if is_integer_type(target_type):
            lt = target_lt if target_lt is not None else self._type_to_llvm(target_type)
            raw = int.from_bytes(chunk, "little")
            return c.ConstInt(lt, raw, False)
        return None

    def _const_struct_from_bytes(
        self,
        data: bytes,
        record_name: str,
        record_lt: int | None = None,
    ) -> int | None:
        members = self._sema.record_definitions.get(record_name)
        if members is None:
            return None
        offset = 0
        fields: list[int] = []
        for member in members:
            member_align = self._member_align(member)
            offset = self._align_to(offset, member_align)
            member_size = self._type_size(member.type_)
            field = self._const_from_bytes(
                data[offset : offset + member_size],
                member.type_,
                self._record_member_llvm_type(member),
            )
            if field is None:
                return None
            fields.append(field)
            offset += member_size
        return self._const_struct(Type(record_name), fields, record_lt)

    def _const_union_from_bytes(
        self,
        data: bytes,
        record_name: str,
        record_lt: int | None = None,
    ) -> int | None:
        members = self._sema.record_definitions.get(record_name)
        if not members:
            return llvm().ConstNull(
                record_lt if record_lt is not None else self._type_to_llvm(Type(record_name))
            )
        storage_member = self._union_storage_member(members)
        storage_size = self._type_size(storage_member.type_)
        storage = self._const_from_bytes(
            data[:storage_size],
            storage_member.type_,
            self._record_member_llvm_type(storage_member),
        )
        if storage is None:
            return None
        return self._const_union(Type(record_name), storage_member, storage)
        return None

    def _eval_const_expr(self, expr: Expr, target_type: Type | None = None) -> int | None:
        c = llvm()
        target_lt = self._type_to_llvm(target_type) if target_type is not None else None
        target_kind = c.GetTypeKind(target_lt) if target_lt is not None else None
        int_value = self._eval_int_constant_value(expr)
        if target_lt is not None and int_value is not None:
            if target_kind == LLVMTypeKind.INTEGER:
                return c.ConstInt(target_lt, int_value, int_value < 0)
            if target_kind == LLVMTypeKind.POINTER:
                if int_value == 0:
                    return c.ConstPointerNull(target_lt)
                raw = c.ConstInt(c.Int64Type(), int_value, int_value < 0)
                return c.ConstIntToPtr(raw, target_lt)
            if target_kind is not None and self._is_float_kind(target_kind):
                return c.ConstReal(target_lt, float(int_value))
        if target_kind == LLVMTypeKind.POINTER:
            value_type = self._type_map.get(expr)
            if value_type is not None and value_type.is_array():
                value = self._eval_const_addr(expr)
                if value is not None:
                    assert target_lt is not None
                    return self._const_cast(value, target_lt)
        if isinstance(expr, CompoundLiteralExpr):
            value = self._const_compound_literal_addr(expr)
            if target_lt is not None:
                return self._const_cast(value, target_lt)
            return value
        if isinstance(expr, StringLiteral):
            return self._const_string_literal_ptr(expr)
        if isinstance(expr, Identifier):
            return self._eval_const_identifier(expr)
        if isinstance(expr, UnaryExpr):
            if expr.op == "&":
                return self._eval_const_addr(expr.operand)
            if expr.op == "-" and isinstance(expr.operand, FloatLiteral):
                if target_lt is None:
                    return None
                text = expr.operand.value.rstrip("fFlL")
                float_value = float.fromhex(text) if text.startswith(("0x", "0X")) else float(text)
                return c.ConstReal(target_lt, -float_value)
        if isinstance(expr, CastExpr):
            result_type = self._resolve_type(expr.type_spec)
            result_lt = self._type_to_llvm(result_type)
            cast_int = self._eval_int_constant_value(expr)
            if cast_int is not None:
                result_kind = c.GetTypeKind(result_lt)
                if result_kind == LLVMTypeKind.INTEGER:
                    return c.ConstInt(result_lt, cast_int, cast_int < 0)
                if self._is_float_kind(result_kind):
                    return c.ConstReal(result_lt, float(cast_int))
            value = self._eval_const_expr(expr.expr)
            if value is None:
                return None
            return self._const_cast(value, result_lt)
        if isinstance(expr, SizeofExpr):
            return self._size_const(expr)
        if isinstance(expr, AlignofExpr):
            if expr.type_spec is None:
                return None
            return c.ConstInt(
                c.Int64Type(),
                self._type_align(self._resolve_type(expr.type_spec)),
                False,
            )
        if isinstance(expr, BuiltinOffsetofExpr):
            return self._offsetof_expr(expr)
        return None

    def _eval_const_identifier(self, expr: Identifier) -> int | None:
        c = llvm()
        name = expr.name
        local = self._lookup_local(name)
        if local is not None and local in self._static_local_global_values:
            return local
        if self._sema.file_scope is not None:
            symbol = self._sema.file_scope.lookup(name)
            if isinstance(symbol, EnumConstSymbol):
                return c.ConstInt(c.Int32Type(), symbol.value, symbol.value < 0)
        value_type = self._type_map.get(expr) or self._lookup_symbol_type(name)
        if value_type is None:
            return None
        if self._is_function_designator_type(value_type):
            return self._function_designator(name, value_type)
        if value_type.is_array():
            return self._global_var_ref(name, value_type)
        return None

    def _eval_const_addr(self, expr: Expr) -> int | None:
        c = llvm()
        if isinstance(expr, Identifier):
            name = expr.name
            local = self._lookup_local(name)
            if local is not None and local in self._static_local_global_values:
                return local
            value_type = self._type_map.get(expr) or self._lookup_symbol_type(name)
            if value_type is not None:
                if self._is_function_designator_type(value_type):
                    return self._function_designator(name, value_type)
                return self._global_var_ref(name, value_type)
            gv = c.GetNamedGlobal(self._mod, name.encode())
            if gv:
                return gv
            fn = c.GetNamedFunction(self._mod, name.encode())
            if fn:
                return fn
            return None
        if isinstance(expr, MemberExpr):
            return self._eval_const_member_ptr(expr)
        if isinstance(expr, SubscriptExpr):
            return self._eval_const_subscript_ptr(expr)
        if isinstance(expr, CompoundLiteralExpr):
            return self._const_compound_literal_addr(expr)
        if isinstance(expr, UnaryExpr) and expr.op == "*":
            return self._eval_const_expr(expr.operand)
        return None

    def _const_compound_literal_addr(self, expr: CompoundLiteralExpr) -> int:
        c = llvm()
        key = id(expr)
        gv = self._compound_literal_globals.get(key)
        if gv is not None:
            return gv
        literal_type = self._type_map.require(expr)
        if literal_type.is_array():
            length_value = literal_type.declarator_ops[0][1]
            if isinstance(length_value, int) and length_value <= 0:
                inferred = (
                    self._infer_array_init_length(expr.initializer)
                    if isinstance(expr.initializer, InitList)
                    else 1
                )
                literal_type = Type(
                    literal_type.name,
                    declarator_ops=(("arr", inferred),) + literal_type.declarator_ops[1:],
                    qualifiers=literal_type.qualifiers,
                )
        lt = self._type_to_llvm(literal_type)
        name = f".compound.{len(self._compound_literal_globals)}".encode()
        gv = c.AddGlobal(self._mod, lt, name)
        c.SetLinkage(gv, LLVM_INTERNAL_LINKAGE)
        init = self._eval_init(expr.initializer, literal_type)
        c.SetInitializer(gv, init if init is not None else c.ConstNull(lt))
        self._compound_literal_globals[key] = gv
        return gv

    def _eval_const_member_ptr(self, expr: MemberExpr) -> int | None:
        c = llvm()
        base_t = self._type_map.require(expr.base)
        if expr.through_pointer:
            base = self._eval_const_expr(expr.base)
            pointee = base_t.pointee()
            if base is None or pointee is None:
                return None
            struct_t = pointee
            struct_ptr = base
        else:
            struct_t = base_t
            struct_ptr_value = self._eval_const_addr(expr.base)
            if struct_ptr_value is None:
                return None
            struct_ptr = struct_ptr_value
        path = self._member_path(struct_t.name, expr.member)
        if path is None:
            return None
        zero = c.ConstInt(c.Int32Type(), 0, False)
        ptr = struct_ptr
        for step_record, field_idx, _member in path:
            if step_record.startswith("union "):
                continue
            st = self._struct_type(step_record)
            fi = c.ConstInt(c.Int32Type(), field_idx, False)
            indices = ptr_array([zero, fi])
            ptr = c.ConstGEP2(st, ptr, indices, 2)
        return ptr

    def _eval_const_subscript_ptr(self, expr: SubscriptExpr) -> int | None:
        c = llvm()
        index = self._eval_int_constant_value(expr.index)
        if index is None:
            return None
        idx = c.ConstInt(c.Int64Type(), index, index < 0)
        base_t = self._type_map.require(expr.base)
        if base_t.is_array():
            base = self._eval_const_addr(expr.base)
            if base is None:
                return None
            zero = c.ConstInt(c.Int64Type(), 0, False)
            indices = ptr_array([zero, idx])
            return c.ConstGEP2(self._type_to_llvm(base_t), base, indices, 2)
        base = self._eval_const_expr(expr.base)
        elem_t = self._type_map.require(expr)
        if base is None:
            return None
        indices = ptr_array([idx])
        return c.ConstGEP2(self._type_to_llvm(elem_t), base, indices, 1)

    def _const_string_literal_ptr(self, expr: StringLiteral) -> int:
        c = llvm()
        if expr.value in self._str_constants:
            return self._str_constants[expr.value]
        data = self._string_literal_bytes(expr)
        lt = c.ArrayType(c.Int8Type(), len(data))
        init = c.ConstString(data, len(data), True)
        gv = c.AddGlobal(self._mod, lt, b".str")
        c.SetInitializer(gv, init)
        c.SetLinkage(gv, LLVM_INTERNAL_LINKAGE)
        self._str_constants[expr.value] = gv
        return gv

    def _const_cast(self, value: int, to_type: int) -> int:
        c = llvm()
        from_type = c.TypeOf(value)
        if from_type == to_type:
            return value
        from_kind = c.GetTypeKind(from_type)
        to_kind = c.GetTypeKind(to_type)
        if to_kind == LLVMTypeKind.VOID:
            return value
        if from_kind == LLVMTypeKind.POINTER and to_kind == LLVMTypeKind.POINTER:
            return c.ConstPointerCast(value, to_type)
        if from_kind == LLVMTypeKind.POINTER and to_kind == LLVMTypeKind.INTEGER:
            return c.ConstPtrToInt(value, to_type)
        if from_kind == LLVMTypeKind.INTEGER and to_kind == LLVMTypeKind.POINTER:
            if c.IsAConstantInt(value) and c.ConstIntGetZExtValue(value) == 0:
                return c.ConstPointerNull(to_type)
            return c.ConstIntToPtr(value, to_type)
        if from_kind == LLVMTypeKind.INTEGER and to_kind == LLVMTypeKind.INTEGER:
            if c.IsAConstantInt(value):
                val = c.ConstIntGetSExtValue(value)
                if c.GetIntTypeWidth(to_type) == 1:
                    return c.ConstInt(to_type, 1 if val != 0 else 0, False)
                return c.ConstInt(to_type, val, val < 0)
            return c.ConstTruncOrBitCast(value, to_type)
        return c.ConstBitCast(value, to_type)

    def _eval_int_constant_value(self, expr: Expr) -> int | None:
        if isinstance(expr, ConditionalExpr):
            condition = self._eval_int_constant_value(expr.condition)
            if condition is None:
                return None
            return self._eval_int_constant_value(expr.then_expr if condition else expr.else_expr)
        if isinstance(expr, CommaExpr):
            return self._eval_int_constant_value(expr.right)
        if isinstance(expr, UnaryExpr):
            operand = self._eval_int_constant_value(expr.operand)
            if operand is None:
                return None
            if expr.op == "-":
                return -operand
            if expr.op == "+":
                return operand
            if expr.op == "!":
                return 0 if operand else 1
            if expr.op == "~":
                return ~operand
            return None
        if isinstance(expr, BinaryExpr):
            left = self._eval_int_constant_value(expr.left)
            right = self._eval_int_constant_value(expr.right)
            if left is None or right is None:
                return None
            if expr.op == "+":
                return left + right
            if expr.op == "-":
                return left - right
            if expr.op == "*":
                return left * right
            if expr.op == "/":
                return 0 if right == 0 else left // right
            if expr.op == "%":
                return 0 if right == 0 else left % right
            if expr.op == "<<":
                return left << right
            if expr.op == ">>":
                return left >> right
            if expr.op == "|":
                return left | right
            if expr.op == "&":
                return left & right
            if expr.op == "^":
                return left ^ right
            if expr.op == "&&":
                return 1 if left and right else 0
            if expr.op == "||":
                return 1 if left or right else 0
            if expr.op == "==":
                return 1 if left == right else 0
            if expr.op == "!=":
                return 1 if left != right else 0
            if expr.op == "<":
                return 1 if left < right else 0
            if expr.op == ">":
                return 1 if left > right else 0
            if expr.op == "<=":
                return 1 if left <= right else 0
            if expr.op == ">=":
                return 1 if left >= right else 0
            return None
        if isinstance(expr, CastExpr):
            return self._eval_int_constant_value(expr.expr)
        if isinstance(expr, SizeofExpr):
            result_t = (
                self._resolve_type(expr.type_spec)
                if expr.type_spec is not None
                else self._type_map.get(expr.expr)
                if expr.expr is not None
                else None
            )
            return None if result_t is None else self._type_size(result_t)
        if isinstance(expr, AlignofExpr):
            if expr.type_spec is None:
                return None
            return self._type_align(self._resolve_type(expr.type_spec))
        if isinstance(expr, BuiltinOffsetofExpr):
            return self._offsetof_value(expr)
        try:
            return self._eval_case_val(expr)
        except CodegenError:
            return None

    def _offsetof_value(self, expr: BuiltinOffsetofExpr) -> int | None:
        root_type = self._resolve_type(expr.type_spec)
        return self._offsetof_member_path(root_type, expr.member.split("."))

    def _offsetof_member_path(self, root_type: Type, parts: list[str]) -> int | None:
        if not parts:
            return 0
        if root_type.declarator_ops:
            return None
        if not root_type.name.startswith(("struct ", "union ")):
            return None
        found = self._record_member_offset_and_type(root_type.name, parts[0])
        if found is None:
            return None
        member_offset, member_type = found
        nested_offset = self._offsetof_member_path(member_type, parts[1:])
        if nested_offset is None:
            return None
        return member_offset + nested_offset

    def _record_member_offset_and_type(
        self,
        record_name: str,
        member_name: str,
    ) -> tuple[int, Type] | None:
        members = self._sema.record_definitions.get(record_name)
        if members is None:
            return None
        if record_name.startswith("union "):
            for member in members:
                found = self._record_member_offset_match(member, member_name)
                if found is not None:
                    return found
            return None

        offset = 0
        for member in members:
            member_align = self._member_align(member)
            offset = self._align_to(offset, member_align)
            found = self._record_member_offset_match(member, member_name)
            if found is not None:
                nested_offset, nested_type = found
                return offset + nested_offset, nested_type
            offset += self._type_size(member.type_)
        return None

    def _record_member_offset_match(
        self,
        member: RecordMemberInfo,
        member_name: str,
    ) -> tuple[int, Type] | None:
        if member.name == member_name:
            if member.bit_width is not None:
                return None
            return 0, member.type_
        if (
            member.name is None
            and member.bit_width is None
            and not member.type_.declarator_ops
            and member.type_.name.startswith(("struct ", "union "))
        ):
            return self._record_member_offset_and_type(member.type_.name, member_name)
        return None

    def _eval_case_val(self, expr: Expr) -> int:
        if isinstance(expr, IntLiteral):
            return self._parse_int_value(expr.value)
        if isinstance(expr, CharLiteral):
            return self._char_value(expr.value)
        if isinstance(expr, UnaryExpr):
            if expr.op == "-":
                return -self._eval_case_val(expr.operand)
            if expr.op == "+":
                return self._eval_case_val(expr.operand)
        if isinstance(expr, Identifier):
            # Check function locals first, then file scope.
            if self._func_sym:
                sym = self._func_sym.locals.get(expr.name)
                if isinstance(sym, EnumConstSymbol):
                    return sym.value
            sym = None
            if self._sema.file_scope is not None:
                sym = self._sema.file_scope.lookup(expr.name)
            if isinstance(sym, EnumConstSymbol):
                return sym.value
        if isinstance(expr, BinaryExpr):
            left = self._eval_case_val(expr.left)
            right = self._eval_case_val(expr.right)
            if expr.op == "+":
                return left + right
            if expr.op == "-":
                return left - right
            if expr.op == "*":
                return left * right
            if expr.op == "/":
                return 0 if right == 0 else left // right
            if expr.op == "%":
                return 0 if right == 0 else left % right
            if expr.op == "<<":
                return left << right
            if expr.op == ">>":
                return left >> right
            if expr.op == "|":
                return left | right
            if expr.op == "&":
                return left & right
            if expr.op == "^":
                return left ^ right
            return 0
        if isinstance(expr, ConditionalExpr):
            condition = self._eval_case_val(expr.condition)
            return self._eval_case_val(expr.then_expr if condition else expr.else_expr)
        if isinstance(expr, CastExpr):
            return self._eval_case_val(expr.expr)
        raise llvm_backend_error(self._result.filename, "Expected integer constant for case")

    def _decode_string(self, s: str) -> str:
        result = []
        i = 0
        while i < len(s):
            if s[i] == "\\" and i + 1 < len(s):
                ch = s[i + 1]
                m = {
                    "n": "\n",
                    "t": "\t",
                    "r": "\r",
                    "0": "\0",
                    "\\": "\\",
                    '"': '"',
                    "'": "'",
                    "a": "\a",
                    "b": "\b",
                    "f": "\f",
                    "v": "\v",
                }
                if ch in m:
                    result.append(m[ch])
                    i += 2
                elif ch == "x":
                    result.append(chr(int(s[i + 2 : i + 4], 16)))
                    i += 4
                elif ch in {"u", "U"}:
                    width = 4 if ch == "u" else 8
                    result.append(chr(int(s[i + 2 : i + 2 + width], 16)))
                    i += 2 + width
                else:
                    result.append(ch)
                    i += 2
            else:
                result.append(s[i])
                i += 1
        return "".join(result)


# ── public API ───────────────────────────────────────────────


def generate_llvm_ir(result: FrontendResult) -> str:
    return _LLVMGen(result).generate()
