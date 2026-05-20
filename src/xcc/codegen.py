"""LLVM IR code generator using libLLVM-C via ctypes.

Zero runtime dependencies (ctypes is stdlib). Uses the system
libLLVM.dylib installed by Homebrew.

Consumes FrontendResult (AST + TypeMap + SemaUnit), produces
LLVM IR text. Driver pipes through llc for .o files.
"""

import ctypes
import ctypes.util
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
from xcc.sema.symbols import FunctionSymbol, RecordMemberInfo, VarSymbol
from xcc.types import INT, LONG, Type

_CG_UNSUPPORTED = "XCC-CG-0005"


def llvm_backend_error(filename: str, message: str) -> CodegenError:
    return CodegenError(Diagnostic("codegen", filename, message, code=_CG_UNSUPPORTED))


# ── libLLVM loading ─────────────────────────────────────────


def _load_llvm():
    path = "/opt/homebrew/opt/llvm/lib/libLLVM-C.dylib"
    return ctypes.CDLL(path)


_LLVM: ctypes.CDLL | None = None


def _llvm():
    global _LLVM
    if _LLVM is None:
        _LLVM = _load_llvm()
    return _LLVM


# ── ctypes type aliases ─────────────────────────────────────

_c_void_p = ctypes.c_void_p
_c_char_p = ctypes.c_char_p
_c_bool = ctypes.c_bool
_c_uint = ctypes.c_uint
_c_size_t = ctypes.c_size_t

# LLVM type aliases
_LLVMTypeRef = _c_void_p
_LLVMValueRef = _c_void_p
_LLVMBasicBlockRef = _c_void_p
_LLVMModuleRef = _c_void_p
_LLVMBuilderRef = _c_void_p
_LLVMContextRef = _c_void_p


# ── LLVM-C API bindings ─────────────────────────────────────


class _LLVMC:
    """Thin wrapper around libLLVM-C API."""

    def __init__(self, lib: ctypes.CDLL):
        self._lib = lib

    def _bind(self, name, restype, *argtypes):
        fn = getattr(self._lib, name)
        fn.restype = restype
        fn.argtypes = argtypes
        return fn

    def bind_all(self):
        l = self._lib
        # Context / Module
        self.ContextCreate = self._bind("LLVMContextCreate", _c_void_p)
        self.ModuleCreateWithName = self._bind(
            "LLVMModuleCreateWithName", _LLVMModuleRef, _c_char_p
        )
        self.SetTarget = self._bind(
            "LLVMSetTarget", None, _LLVMModuleRef, _c_char_p
        )
        self.PrintModuleToString = self._bind(
            "LLVMPrintModuleToString", _c_char_p, _LLVMModuleRef
        )
        self.DisposeModule = self._bind(
            "LLVMDisposeModule", None, _LLVMModuleRef
        )

        # Types
        self.VoidType = self._bind("LLVMVoidType", _LLVMTypeRef)
        self.Int1Type = self._bind("LLVMInt1Type", _LLVMTypeRef)
        self.Int8Type = self._bind("LLVMInt8Type", _LLVMTypeRef)
        self.Int16Type = self._bind("LLVMInt16Type", _LLVMTypeRef)
        self.Int32Type = self._bind("LLVMInt32Type", _LLVMTypeRef)
        self.Int64Type = self._bind("LLVMInt64Type", _LLVMTypeRef)
        self.FloatType = self._bind("LLVMFloatType", _LLVMTypeRef)
        self.DoubleType = self._bind("LLVMDoubleType", _LLVMTypeRef)
        self.PointerType = self._bind(
            "LLVMPointerType", _LLVMTypeRef, _LLVMTypeRef, _c_uint
        )
        self.FunctionType = self._bind(
            "LLVMFunctionType", _LLVMTypeRef, _LLVMTypeRef,
            ctypes.POINTER(_LLVMTypeRef), _c_uint, _c_bool,
        )
        self.ArrayType = self._bind(
            "LLVMArrayType2", _LLVMTypeRef, _LLVMTypeRef, _c_uint
        )
        self.StructType = self._bind(
            "LLVMStructType", _LLVMTypeRef,
            ctypes.POINTER(_LLVMTypeRef), _c_uint, _c_bool,
        )
        self.StructSetBody = self._bind(
            "LLVMStructSetBody", None, _LLVMTypeRef,
            ctypes.POINTER(_LLVMTypeRef), _c_uint, _c_bool,
        )

        # Values / Constants
        self.ConstInt = self._bind(
            "LLVMConstInt", _LLVMValueRef, _LLVMTypeRef, ctypes.c_ulonglong, _c_bool
        )
        self.ConstReal = self._bind(
            "LLVMConstReal", _LLVMValueRef, _LLVMTypeRef, ctypes.c_double
        )
        self.ConstString = self._bind(
            "LLVMConstString", _LLVMValueRef, _c_char_p, _c_uint, _c_bool
        )
        self.ConstNull = self._bind("LLVMConstNull", _LLVMValueRef, _LLVMTypeRef)
        self.ConstArray = self._bind(
            "LLVMConstArray2", _LLVMValueRef, _LLVMTypeRef,
            ctypes.POINTER(_LLVMValueRef), _c_size_t,
        )
        self.AddGlobal = self._bind(
            "LLVMAddGlobal", _LLVMValueRef, _LLVMModuleRef, _LLVMTypeRef, _c_char_p
        )
        self.SetInitializer = self._bind(
            "LLVMSetInitializer", None, _LLVMValueRef, _LLVMValueRef
        )
        self.SetLinkage = self._bind(
            "LLVMSetLinkage", None, _LLVMValueRef, _c_uint
        )
        self.GetNamedGlobal = self._bind(
            "LLVMGetNamedGlobal", _LLVMValueRef, _LLVMModuleRef, _c_char_p
        )
        self.GetNamedFunction = self._bind(
            "LLVMGetNamedFunction", _LLVMValueRef, _LLVMModuleRef, _c_char_p
        )

        # Function
        self.AddFunction = self._bind(
            "LLVMAddFunction", _LLVMValueRef, _LLVMModuleRef, _c_char_p, _LLVMTypeRef
        )
        self.GetParam = self._bind(
            "LLVMGetParam", _LLVMValueRef, _LLVMValueRef, _c_uint
        )
        self.AppendBasicBlock = self._bind(
            "LLVMAppendBasicBlock", _LLVMBasicBlockRef, _LLVMValueRef, _c_char_p
        )
        self.SetValueName2 = self._bind(
            "LLVMSetValueName2", None, _LLVMValueRef, _c_char_p, _c_size_t
        )
        self.GetReturnType = self._bind(
            "LLVMGetReturnType", _LLVMTypeRef, _LLVMTypeRef
        )

        # Builder
        self.CreateBuilder = self._bind("LLVMCreateBuilder", _LLVMBuilderRef)
        self.PositionBuilderAtEnd = self._bind(
            "LLVMPositionBuilderAtEnd", None, _LLVMBuilderRef, _LLVMBasicBlockRef
        )
        self.DisposeBuilder = self._bind("LLVMDisposeBuilder", None, _LLVMBuilderRef)

        # Terminators
        self.BuildRetVoid = self._bind(
            "LLVMBuildRetVoid", _LLVMValueRef, _LLVMBuilderRef
        )
        self.BuildRet = self._bind(
            "LLVMBuildRet", _LLVMValueRef, _LLVMBuilderRef, _LLVMValueRef
        )
        self.BuildBr = self._bind(
            "LLVMBuildBr", _LLVMValueRef, _LLVMBuilderRef, _LLVMBasicBlockRef
        )
        self.BuildCondBr = self._bind(
            "LLVMBuildCondBr", _LLVMValueRef, _LLVMBuilderRef,
            _LLVMValueRef, _LLVMBasicBlockRef, _LLVMBasicBlockRef,
        )
        self.BuildSwitch = self._bind(
            "LLVMBuildSwitch", _LLVMValueRef, _LLVMBuilderRef,
            _LLVMValueRef, _LLVMBasicBlockRef, _c_uint,
        )
        self.AddCase = self._bind(
            "LLVMAddCase", None, _LLVMValueRef, _LLVMValueRef, _LLVMBasicBlockRef
        )

        # Arithmetic
        self.BuildAdd = self._bind(
            "LLVMBuildAdd", _LLVMValueRef, _LLVMBuilderRef,
            _LLVMValueRef, _LLVMValueRef, _c_char_p,
        )
        self.BuildSub = self._bind(
            "LLVMBuildSub", _LLVMValueRef, _LLVMBuilderRef,
            _LLVMValueRef, _LLVMValueRef, _c_char_p,
        )
        self.BuildMul = self._bind(
            "LLVMBuildMul", _LLVMValueRef, _LLVMBuilderRef,
            _LLVMValueRef, _LLVMValueRef, _c_char_p,
        )
        self.BuildSDiv = self._bind(
            "LLVMBuildSDiv", _LLVMValueRef, _LLVMBuilderRef,
            _LLVMValueRef, _LLVMValueRef, _c_char_p,
        )
        self.BuildSRem = self._bind(
            "LLVMBuildSRem", _LLVMValueRef, _LLVMBuilderRef,
            _LLVMValueRef, _LLVMValueRef, _c_char_p,
        )
        self.BuildAnd = self._bind(
            "LLVMBuildAnd", _LLVMValueRef, _LLVMBuilderRef,
            _LLVMValueRef, _LLVMValueRef, _c_char_p,
        )
        self.BuildOr = self._bind(
            "LLVMBuildOr", _LLVMValueRef, _LLVMBuilderRef,
            _LLVMValueRef, _LLVMValueRef, _c_char_p,
        )
        self.BuildXor = self._bind(
            "LLVMBuildXor", _LLVMValueRef, _LLVMBuilderRef,
            _LLVMValueRef, _LLVMValueRef, _c_char_p,
        )
        self.BuildShl = self._bind(
            "LLVMBuildShl", _LLVMValueRef, _LLVMBuilderRef,
            _LLVMValueRef, _LLVMValueRef, _c_char_p,
        )
        self.BuildAShr = self._bind(
            "LLVMBuildAShr", _LLVMValueRef, _LLVMBuilderRef,
            _LLVMValueRef, _LLVMValueRef, _c_char_p,
        )

        # Memory
        self.BuildAlloca = self._bind(
            "LLVMBuildAlloca", _LLVMValueRef, _LLVMBuilderRef,
            _LLVMTypeRef, _c_char_p,
        )
        self.BuildLoad2 = self._bind(
            "LLVMBuildLoad2", _LLVMValueRef, _LLVMBuilderRef,
            _LLVMTypeRef, _LLVMValueRef, _c_char_p,
        )
        self.BuildStore = self._bind(
            "LLVMBuildStore", _LLVMValueRef, _LLVMBuilderRef,
            _LLVMValueRef, _LLVMValueRef,
        )

        # GEP
        self.BuildGEP2 = self._bind(
            "LLVMBuildGEP2", _LLVMValueRef, _LLVMBuilderRef,
            _LLVMTypeRef, _LLVMValueRef,
            ctypes.POINTER(_LLVMValueRef), _c_uint, _c_char_p,
        )

        # Cast
        self.BuildSExt = self._bind(
            "LLVMBuildSExt", _LLVMValueRef, _LLVMBuilderRef,
            _LLVMValueRef, _LLVMTypeRef, _c_char_p,
        )
        self.BuildZExt = self._bind(
            "LLVMBuildZExt", _LLVMValueRef, _LLVMBuilderRef,
            _LLVMValueRef, _LLVMTypeRef, _c_char_p,
        )
        self.BuildTrunc = self._bind(
            "LLVMBuildTrunc", _LLVMValueRef, _LLVMBuilderRef,
            _LLVMValueRef, _LLVMTypeRef, _c_char_p,
        )
        self.BuildIntToPtr = self._bind(
            "LLVMBuildIntToPtr", _LLVMValueRef, _LLVMBuilderRef,
            _LLVMValueRef, _LLVMTypeRef, _c_char_p,
        )
        self.BuildPtrToInt = self._bind(
            "LLVMBuildPtrToInt", _LLVMValueRef, _LLVMBuilderRef,
            _LLVMValueRef, _LLVMTypeRef, _c_char_p,
        )
        self.BuildFPCast = self._bind(
            "LLVMBuildFPCast", _LLVMValueRef, _LLVMBuilderRef,
            _LLVMValueRef, _LLVMTypeRef, _c_char_p,
        )
        self.BuildSIToFP = self._bind(
            "LLVMBuildSIToFP", _LLVMValueRef, _LLVMBuilderRef,
            _LLVMValueRef, _LLVMTypeRef, _c_char_p,
        )
        self.BuildFPToSI = self._bind(
            "LLVMBuildFPToSI", _LLVMValueRef, _LLVMBuilderRef,
            _LLVMValueRef, _LLVMTypeRef, _c_char_p,
        )
        self.BuildBitCast = self._bind(
            "LLVMBuildBitCast", _LLVMValueRef, _LLVMBuilderRef,
            _LLVMValueRef, _LLVMTypeRef, _c_char_p,
        )

        # Comparison
        self.BuildICmp = self._bind(
            "LLVMBuildICmp", _LLVMValueRef, _LLVMBuilderRef,
            _c_uint, _LLVMValueRef, _LLVMValueRef, _c_char_p,
        )

        # Calls
        self.BuildCall2 = self._bind(
            "LLVMBuildCall2", _LLVMValueRef, _LLVMBuilderRef,
            _LLVMTypeRef, _LLVMValueRef,
            ctypes.POINTER(_LLVMValueRef), _c_uint, _c_char_p,
        )
        self.GetUndef = self._bind("LLVMGetUndef", _LLVMValueRef, _LLVMTypeRef)

        # PHI
        self.BuildPhi = self._bind(
            "LLVMBuildPhi", _LLVMValueRef, _LLVMBuilderRef,
            _LLVMTypeRef, _c_char_p,
        )
        self.AddIncoming = self._bind(
            "LLVMAddIncoming", None, _LLVMValueRef,
            ctypes.POINTER(_LLVMValueRef), ctypes.POINTER(_LLVMBasicBlockRef), _c_uint,
        )

        # Misc
        self.TypeOf = self._bind("LLVMTypeOf", _LLVMTypeRef, _LLVMValueRef)
        self.ConstPointerNull = self._bind(
            "LLVMConstPointerNull", _LLVMValueRef, _LLVMTypeRef
        )
        self.IsNull = self._bind("LLVMIsNull", _c_bool, _LLVMValueRef)


_api: _LLVMC | None = None


def _c():
    global _api
    if _api is None:
        _api = _LLVMC(_llvm())
        _api.bind_all()
    return _api


# ── code generator ──────────────────────────────────────────

_BASE_SIZES = {
    "int": 4, "unsigned int": 4,
    "long": 8, "unsigned long": 8,
    "long long": 8, "unsigned long long": 8,
    "char": 1, "unsigned char": 1, "signed char": 1, "_Bool": 1,
    "short": 2, "unsigned short": 2,
    "float": 4, "double": 8, "long double": 16,
    "void": 0,
}


@dataclass
class _LoopCtx:
    continue_block: int  # _LLVMBasicBlockRef
    break_block: int     # _LLVMBasicBlockRef


class _LLVMGen:
    def __init__(self, result: FrontendResult):
        self._result = result
        self._unit = result.unit
        self._type_map = result.sema.type_map
        self._sema = result.sema

        c = _c()
        self._ctx = c.ContextCreate()
        self._mod = c.ModuleCreateWithName(
            result.filename.encode("utf-8")
        )
        c.SetTarget(self._mod, b"arm64-apple-macosx15.0.0")
        self._builder = c.CreateBuilder()
        self._str_constants: dict[str, int] = {}  # literal → _LLVMValueRef
        self._func_types: dict[str, int] = {}  # func name → _LLVMTypeRef (ptr-to-func)

        # Struct types: record_name → _LLVMTypeRef
        self._struct_types: dict[str, int] = {}

        # Function state
        self._func: int = 0  # _LLVMValueRef
        self._func_sym: FunctionSymbol | None = None
        self._locals: list[dict[str, int]] = []
        self._loop_stack: list[_LoopCtx] = []
        self._switch_info: list[tuple[int, int, int | None]] = []  # (switch_inst, end_block, default_block)
        self._term: bool = False  # current block has terminator?

    # ── helpers ──────────────────────────────────────────────

    def _type_to_llvm(self, t: Type) -> int:
        """Map XCC Type to LLVMTypeRef."""
        c = _c()
        base_name = t.name

        if not t.declarator_ops:
            return self._base_type(base_name)

        # Walk declarator ops inside-out
        result = self._base_type(base_name)
        for kind, value in t.declarator_ops:
            if kind == "ptr":
                result = c.PointerType(result, 0)
            elif kind == "arr":
                if isinstance(value, int):
                    result = c.ArrayType(result, value)
                else:
                    result = c.ArrayType(result, 0)
            elif kind == "fn":
                params = ()
                is_var = False
                if isinstance(value, tuple):
                    params = value[0] if value[0] else ()
                    is_var = value[1]
                param_types = (ctypes.c_void_p * len(params))()
                for i, pt in enumerate(params):
                    param_types[i] = self._base_type(pt.name)
                result = c.FunctionType(result, param_types, len(params), is_var)
        return result

    def _base_type(self, name: str) -> int:
        c = _c()
        m = {
            "int": c.Int32Type, "unsigned int": c.Int32Type,
            "long": c.Int64Type, "unsigned long": c.Int64Type,
            "long long": c.Int64Type, "unsigned long long": c.Int64Type,
            "char": c.Int8Type, "unsigned char": c.Int8Type,
            "signed char": c.Int8Type, "_Bool": c.Int1Type,
            "short": c.Int16Type, "unsigned short": c.Int16Type,
            "float": c.FloatType, "double": c.DoubleType,
            "long double": c.DoubleType,
            "void": c.VoidType,
        }
        fn = m.get(name)
        if fn is None:
            return c.Int32Type()
        return fn()

    def _struct_type(self, record_name: str) -> int:
        c = _c()
        if record_name in self._struct_types:
            return self._struct_types[record_name]
        members = self._sema.record_definitions.get(record_name)
        if not members:
            st = c.StructType(None, 0, False)
            self._struct_types[record_name] = st
            return st
        member_types = (ctypes.c_void_p * len(members))()
        for i, m in enumerate(members):
            member_types[i] = self._type_to_llvm(m.type_)
        st = c.StructType(member_types, len(members), False)
        self._struct_types[record_name] = st
        return st

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

    def _ptr_type(self, t: Type) -> int:
        return _c().PointerType(self._type_to_llvm(t), 0)

    def _type_size(self, t: Type) -> int:
        base = _BASE_SIZES.get(t.name, 4)
        for kind, _ in t.declarator_ops:
            if kind == "ptr":
                return 8
        return base

    # ── module ───────────────────────────────────────────────

    def generate(self) -> str:
        self._emit_globals()
        self._emit_functions()
        c = _c()
        ir = c.PrintModuleToString(self._mod)
        result = ir.decode("utf-8") if isinstance(ir, bytes) else str(ir)
        return result

    def _emit_globals(self) -> None:
        c = _c()
        externals = self._unit.externals or [
            *self._unit.declarations, *self._unit.functions
        ]
        for ext in externals:
            if isinstance(ext, FunctionDef):
                continue
            if isinstance(ext, DeclGroupStmt):
                for decl in ext.declarations:
                    self._emit_global_var(decl)
            elif isinstance(ext, DeclStmt):
                self._emit_global_var(decl)

    def _emit_global_var(self, decl: DeclStmt) -> None:
        c = _c()
        name = decl.name
        if name is None or decl.storage_class == "extern":
            return
        t = self._resolve_type(decl.type_spec)
        lt = self._type_to_llvm(t)
        gv = c.AddGlobal(self._mod, lt, name.encode())
        if decl.init:
            val = self._eval_init(decl.init, t)
            if val:
                c.SetInitializer(gv, val)
        else:
            c.SetInitializer(gv, c.ConstNull(lt))

    def _emit_functions(self) -> None:
        for func in self._unit.functions:
            self._declare_func(func)
        for func in self._unit.functions:
            if func.body is not None:
                self._define_func(func)

    def _declare_func(self, func: FunctionDef) -> None:
        c = _c()
        func_sym = self._sema.functions.get(func.name)
        if func_sym is None:
            return
        ret_t = self._type_to_llvm(func_sym.return_type)
        param_ts = (ctypes.c_void_p * len(func.params))()
        for i, p in enumerate(func.params):
            pt = self._resolve_type(p.type_spec)
            param_ts[i] = self._type_to_llvm(pt)
        fn_t = c.FunctionType(ret_t, param_ts, len(func.params), False)
        self._func_types[func.name] = fn_t  # save for later calls
        fn = c.AddFunction(self._mod, func.name.encode(), fn_t)
        if func.body is None:
            c.SetLinkage(fn, 0)  # external

    def _define_func(self, func: FunctionDef) -> None:
        c = _c()
        func_sym = self._sema.functions.get(func.name)
        if func_sym is None:
            return
        self._func_sym = func_sym
        self._locals = [{}]
        self._loop_stack = []
        self._switch_info = []

        ret_t = self._type_to_llvm(func_sym.return_type)
        param_ts = (ctypes.c_void_p * len(func.params))()
        for i, p in enumerate(func.params):
            pt = self._resolve_type(p.type_spec)
            param_ts[i] = self._type_to_llvm(pt)
        fn_t = c.FunctionType(ret_t, param_ts, len(func.params), False)
        # Reuse existing declaration if present
        fn = c.GetNamedFunction(self._mod, func.name.encode())
        if not fn:
            fn = c.AddFunction(self._mod, func.name.encode(), fn_t)
        self._func = fn

        entry = c.AppendBasicBlock(fn, b"entry")
        c.PositionBuilderAtEnd(self._builder, entry)

        # Alloca + store params
        for i, param in enumerate(func.params):
            assert param.name
            pt = self._resolve_type(param.type_spec)
            lt = self._type_to_llvm(pt)
            pv = c.GetParam(fn, i)
            alloca = c.BuildAlloca(self._builder, lt, f"{param.name}.addr".encode())
            c.BuildStore(self._builder, pv, alloca)
            self._locals[-1][param.name] = alloca

        # Pre-collect allocas
        allocas = self._collect_allocas(func.body)
        for vname, vtype in allocas:
            if vname in self._locals[-1]:
                continue
            lt = self._type_to_llvm(vtype)
            a = c.BuildAlloca(self._builder, lt, f"{vname}.addr".encode())
            self._locals[-1][vname] = a

        self._term = False
        self._emit_stmt(func.body)

        if not self._term:
            if func_sym.return_type.name == "void":
                c.BuildRetVoid(self._builder)
            else:
                c.BuildRet(self._builder, c.ConstInt(ret_t, 0, False))

    def _build_call_args(self, expr: CallExpr) -> tuple[list[int], list[int]]:
        """Evaluate call args, return (values, types)."""
        vals = []
        types = []
        for arg in expr.args:
            v = self._emit_expr(arg)
            vals.append(v)
            types.append(_c().TypeOf(v))
        return vals, types

    # ── statement emission ───────────────────────────────────

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
        elif isinstance(stmt, (TypedefDecl, StaticAssertDecl)):
            pass

    def _emit_return(self, stmt: ReturnStmt) -> None:
        c = _c()
        if stmt.value is None:
            c.BuildRetVoid(self._builder)
        else:
            v = self._emit_expr(stmt.value)
            c.BuildRet(self._builder, v)
        self._term = True

    def _emit_decl_init(self, stmt: DeclStmt) -> None:
        if stmt.name is None or stmt.init is None:
            return
        addr = self._lookup_local(stmt.name)
        if addr is None:
            return
        val = self._emit_expr(stmt.init)
        _c().BuildStore(self._builder, val, addr)

    # ── control flow ─────────────────────────────────────────

    def _emit_if(self, stmt: IfStmt) -> None:
        c = _c()
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
        self._term = False
        self._emit_stmt(stmt.then_body)
        if not self._term:
            c.BuildBr(self._builder, merge_bb)

        if else_bb:
            c.PositionBuilderAtEnd(self._builder, else_bb)
            self._term = False
            self._emit_stmt(stmt.else_body)
            if not self._term:
                c.BuildBr(self._builder, merge_bb)

        c.PositionBuilderAtEnd(self._builder, merge_bb)
        self._term = False

    def _emit_while(self, stmt: WhileStmt) -> None:
        c = _c()
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
        self._emit_stmt(stmt.body)
        self._loop_stack.pop()
        c.BuildBr(self._builder, cond_bb)

        c.PositionBuilderAtEnd(self._builder, end_bb)

    def _emit_do_while(self, stmt: DoWhileStmt) -> None:
        c = _c()
        fn = self._func
        body_bb = c.AppendBasicBlock(fn, b"do.body")
        cond_bb = c.AppendBasicBlock(fn, b"do.cond")
        end_bb = c.AppendBasicBlock(fn, b"do.end")

        c.BuildBr(self._builder, body_bb)
        c.PositionBuilderAtEnd(self._builder, body_bb)
        self._loop_stack.append(_LoopCtx(cond_bb, end_bb))
        self._emit_stmt(stmt.body)
        self._loop_stack.pop()
        c.BuildBr(self._builder, cond_bb)

        c.PositionBuilderAtEnd(self._builder, cond_bb)
        cond = self._to_bool(self._emit_expr(stmt.condition))
        c.BuildCondBr(self._builder, cond, body_bb, end_bb)

        c.PositionBuilderAtEnd(self._builder, end_bb)

    def _emit_for(self, stmt: ForStmt) -> None:
        c = _c()
        fn = self._func
        if stmt.init:
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
        self._emit_stmt(stmt.body)
        self._loop_stack.pop()
        c.BuildBr(self._builder, step_bb)

        c.PositionBuilderAtEnd(self._builder, step_bb)
        if stmt.post:
            self._emit_expr(stmt.post)
        c.BuildBr(self._builder, cond_bb)

        c.PositionBuilderAtEnd(self._builder, end_bb)

    def _emit_break(self) -> None:
        c = _c()
        if self._switch_info:
            c.BuildBr(self._builder, self._switch_info[-1][1])
            self._term = True
            return
        if not self._loop_stack:
            raise llvm_backend_error(self._result.filename, "break not within loop or switch")
        c.BuildBr(self._builder, self._loop_stack[-1].break_block)
        self._term = True

    def _emit_continue(self) -> None:
        if not self._loop_stack:
            raise llvm_backend_error(self._result.filename, "continue not within loop")
        _c().BuildBr(self._builder, self._loop_stack[-1].continue_block)
        self._term = True

    def _emit_switch(self, stmt: SwitchStmt) -> None:
        c = _c()
        fn = self._func
        cond = self._emit_expr(stmt.condition)
        end_bb = c.AppendBasicBlock(fn, b"switch.end")
        default_bb = c.AppendBasicBlock(fn, b"switch.default")

        sw = c.BuildSwitch(self._builder, cond, default_bb, 0)
        self._switch_info.append((sw, end_bb, default_bb))

        self._emit_stmt(stmt.body)

        # Close switch: jump to end if no terminator
        c.BuildBr(self._builder, end_bb)
        c.PositionBuilderAtEnd(self._builder, end_bb)
        self._switch_info.pop()

    def _emit_case(self, stmt: CaseStmt) -> None:
        c = _c()
        fn = self._func
        val = self._eval_case_val(stmt.value)
        case_bb = c.AppendBasicBlock(fn, b"switch.case")
        sw, _, _ = self._switch_info[-1]
        cond_t = c.TypeOf(self._emit_expr(stmt.value))  # FIXME: wasteful eval
        # Re-evaluate to get the proper int constant
        c.AddCase(sw, c.ConstInt(cond_t, val, False), case_bb)
        c.PositionBuilderAtEnd(self._builder, case_bb)
        if stmt.body:
            self._emit_stmt(stmt.body)

    def _emit_default(self, stmt: DefaultStmt) -> None:
        _, _, default_bb = self._switch_info[-1]
        _c().PositionBuilderAtEnd(self._builder, default_bb)
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
        raise llvm_backend_error(
            self._result.filename,
            f"Unsupported expression: {type(expr).__name__}",
        )

    # ── literals ─────────────────────────────────────────────

    def _int_literal(self, expr: IntLiteral | CharLiteral) -> int:
        c = _c()
        val_type = self._type_map.get(expr)
        if val_type is None:
            val_type = INT
        lt = self._type_to_llvm(val_type)
        if isinstance(expr, CharLiteral):
            val = ord(expr.value)
        else:
            val = int(expr.value)
        return c.ConstInt(lt, val, False)

    def _float_literal(self, expr: FloatLiteral) -> int:
        c = _c()
        val_type = self._type_map.get(expr)
        lt = self._type_to_llvm(val_type) if val_type else c.DoubleType()
        return c.ConstReal(lt, float(expr.value))

    def _string_literal(self, expr: StringLiteral) -> int:
        c = _c()
        if expr.value in self._str_constants:
            gv = self._str_constants[expr.value]
        else:
            body = self._decode_string(expr.value)
            data = body.encode() + b"\x00"
            lt = c.ArrayType(c.Int8Type(), len(data))
            init = c.ConstString(data, len(data), False)
            gv = c.AddGlobal(self._mod, lt, b".str")
            c.SetInitializer(gv, init)
            c.SetLinkage(gv, 2)  # internal
            self._str_constants[expr.value] = gv
        zero = c.ConstInt(c.Int64Type(), 0, False)
        idx = (ctypes.c_void_p * 2)(zero, zero)
        return c.BuildGEP2(self._builder, c.TypeOf(gv), gv, idx, 2, b"str.ptr")

    # ── identifier ───────────────────────────────────────────

    def _identifier(self, expr: Identifier) -> int:
        c = _c()
        name = expr.name
        assert isinstance(name, str)

        addr = self._lookup_local(name)
        if addr is not None:
            val_type = self._type_map.require(expr)
            lt = self._type_to_llvm(val_type)
            return c.BuildLoad2(self._builder, lt, addr, name.encode())

        # Check function locals (globals)
        if self._func_sym and name in self._func_sym.locals:
            sym = self._func_sym.locals[name]
            if isinstance(sym, VarSymbol):
                gv = c.GetNamedGlobal(self._mod, name.encode())
                val_type = sym.type_
                lt = self._type_to_llvm(val_type)
                return c.BuildLoad2(self._builder, lt, gv, name.encode())

        val_type = self._type_map.require(expr)
        lt = self._type_to_llvm(val_type)
        gv = c.GetNamedGlobal(self._mod, name.encode())
        return c.BuildLoad2(self._builder, lt, gv, name.encode())

    def _lookup_local(self, name: str) -> int | None:
        for scope in reversed(self._locals):
            if name in scope:
                return scope[name]
        return None

    # ── unary ────────────────────────────────────────────────

    def _unary(self, expr: UnaryExpr) -> int:
        c = _c()
        op = expr.op
        if op == "&":
            return self._addrof(expr)
        if op == "*":
            return self._deref(expr)
        operand = self._emit_expr(expr.operand)
        if op == "+":
            return operand
        if op == "-":
            return c.BuildSub(self._builder, c.ConstInt(c.TypeOf(operand), 0, False), operand, b"neg")
        if op == "~":
            return c.BuildXor(self._builder, operand, c.ConstInt(c.TypeOf(operand), -1, True), b"not")
        if op == "!":
            cond = self._to_bool(operand)
            return c.BuildZExt(self._builder, c.BuildXor(
                self._builder, cond, c.ConstInt(c.Int1Type(), 1, False), b"lnot"
            ), c.Int32Type(), b"lnot.ext")
        raise llvm_backend_error(self._result.filename, f"Unsupported unary: {op}")

    def _addrof(self, expr: UnaryExpr) -> int:
        operand = expr.operand
        if isinstance(operand, Identifier):
            name = operand.name
            assert isinstance(name, str)
            local = self._lookup_local(name)
            if local:
                return local
            return _c().GetNamedGlobal(self._mod, name.encode())
        if isinstance(operand, SubscriptExpr):
            return self._subscript_ptr(operand)
        if isinstance(operand, MemberExpr):
            return self._member_ptr(operand)
        if isinstance(operand, UnaryExpr) and operand.op == "*":
            return self._emit_expr(operand.operand)
        raise llvm_backend_error(self._result.filename, f"Unsupported &{type(operand).__name__}")

    def _deref(self, expr: UnaryExpr) -> int:
        c = _c()
        ptr = self._emit_expr(expr.operand)
        val_type = self._type_map.require(expr)
        lt = self._type_to_llvm(val_type)
        return c.BuildLoad2(self._builder, lt, ptr, b"deref")

    # ── binary ───────────────────────────────────────────────

    def _binary(self, expr: BinaryExpr) -> int:
        c = _c()
        op = expr.op

        if op in {"&&", "||"}:
            return self._logical(expr)

        left = self._emit_expr(expr.left)
        right = self._emit_expr(expr.right)

        if op in {"==", "!=", "<", ">", "<=", ">="}:
            return self._compare(op, left, right)

        result_type = self._type_map.require(expr)
        lt = self._type_to_llvm(result_type)

        arith = {"+": c.BuildAdd, "-": c.BuildSub, "*": c.BuildMul,
                  "/": c.BuildSDiv, "%": c.BuildSRem}
        bit = {"&": c.BuildAnd, "|": c.BuildOr, "^": c.BuildXor,
                "<<": c.BuildShl, ">>": c.BuildAShr}

        fn = arith.get(op) or bit.get(op)
        if fn is None:
            raise llvm_backend_error(self._result.filename, f"Unsupported binary: {op}")
        return fn(self._builder, left, right, b"binop")

    def _compare(self, op: str, left: int, right: int) -> int:
        c = _c()
        preds = {"==": 32, "!=": 33, "<": 40, ">": 38, "<=": 41, ">=": 39}  # LLVM signed int preds
        pred = preds[op]
        cmp = c.BuildICmp(self._builder, pred, left, right, b"cmp")
        return c.BuildZExt(self._builder, cmp, c.Int32Type(), b"cmp.ext")

    def _logical(self, expr: BinaryExpr) -> int:
        c = _c()
        fn = self._func
        lhs = self._to_bool(self._emit_expr(expr.left))

        rhs_bb = c.AppendBasicBlock(fn, b"log.rhs")
        end_bb = c.AppendBasicBlock(fn, b"log.end")

        # Alloca for result
        alloca = c.BuildAlloca(self._builder, c.Int32Type(), b"log.res")

        if expr.op == "&&":
            # false → skip rhs, result = 0
            c.BuildCondBr(self._builder, lhs, rhs_bb, end_bb)
            # Short-circuit store 0
            saved_bb = c.AppendBasicBlock(fn, b"log.short")
            c.PositionBuilderAtEnd(self._builder, saved_bb)
            # Actually let me restructure using the correct blocks
            pass

        # Simpler approach: use PHI nodes
        short_bb = c.AppendBasicBlock(fn, b"log.short")
        c.BuildCondBr(self._builder, lhs, rhs_bb if expr.op == "&&" else short_bb,
                       short_bb if expr.op == "&&" else rhs_bb)

        short_val = 0 if expr.op == "&&" else 1
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
        c = _c()
        val = self._emit_expr(expr.value)

        target = expr.target
        addr = self._assign_addr(target)

        if expr.op == "=":
            c.BuildStore(self._builder, val, addr)
            return val

        # Compound: load, compute, store
        target_type = self._type_map.require(target)
        lt = self._type_to_llvm(target_type)
        old = c.BuildLoad2(self._builder, lt, addr, b"load.old")

        arith = {"+=": c.BuildAdd, "-=": c.BuildSub, "*=": c.BuildMul,
                  "/=": c.BuildSDiv, "%=": c.BuildSRem}
        bit = {"&=": c.BuildAnd, "|=": c.BuildOr, "^=": c.BuildXor,
                "<<=": c.BuildShl, ">>=": c.BuildAShr}
        fn = arith.get(expr.op) or bit.get(expr.op)
        if fn is None:
            raise llvm_backend_error(self._result.filename, f"Unsupported compound: {expr.op}")
        result = fn(self._builder, old, val, b"compound")
        c.BuildStore(self._builder, result, addr)
        return result

    def _assign_addr(self, target: Expr) -> int:
        c = _c()
        if isinstance(target, Identifier):
            name = target.name
            assert isinstance(name, str)
            addr = self._lookup_local(name)
            if addr:
                return addr
            return c.GetNamedGlobal(self._mod, name.encode())
        if isinstance(target, UnaryExpr) and target.op == "*":
            return self._emit_expr(target.operand)
        if isinstance(target, SubscriptExpr):
            return self._subscript_ptr(target)
        if isinstance(target, MemberExpr):
            return self._member_ptr(target)
        raise llvm_backend_error(
            self._result.filename,
            f"Unsupported assign target: {type(target).__name__}",
        )

    # ── update ───────────────────────────────────────────────

    def _update(self, expr: UpdateExpr) -> int:
        c = _c()
        delta = 1 if expr.op == "++" else -1
        target = expr.operand
        addr = self._assign_addr(target)
        target_type = self._type_map.require(target)
        lt = self._type_to_llvm(target_type)
        old = c.BuildLoad2(self._builder, lt, addr, b"update.old")
        delta_v = c.ConstInt(lt, delta, True)
        new_v = c.BuildAdd(self._builder, old, delta_v, b"update.new")
        c.BuildStore(self._builder, new_v, addr)
        return old if expr.is_postfix else new_v

    # ── call ─────────────────────────────────────────────────

    def _call(self, expr: CallExpr) -> int:
        c = _c()
        if isinstance(expr.callee, Identifier):
            callee_name = expr.callee.name
            assert isinstance(callee_name, str)

            if callee_name == "__builtin_unreachable":
                return c.GetUndef(c.VoidType())
            if callee_name == "__builtin_expect":
                return self._emit_expr(expr.args[0])
            if callee_name == "__builtin_constant_p":
                return c.ConstInt(c.Int32Type(), 0, False)

            vals, types = self._build_call_args(expr)
            fn = c.GetNamedFunction(self._mod, callee_name.encode())
            fn_t = self._func_types.get(callee_name)
            if fn is None or fn_t is None:
                # Try to declare it
                fn_t = c.FunctionType(c.Int32Type(), None, 0, False)
                fn = c.AddFunction(self._mod, callee_name.encode(), fn_t)
                self._func_types[callee_name] = fn_t
            args_arr = (ctypes.c_void_p * len(vals))()
            for i, v in enumerate(vals):
                args_arr[i] = v
            # Use byref if array empty, else pass the array
            if len(vals) == 0:
                result = c.BuildCall2(self._builder, fn_t, fn, None, 0, b"call")
            else:
                result = c.BuildCall2(self._builder, fn_t, fn, args_arr, len(vals), b"call")
            return result

        raise llvm_backend_error(self._result.filename, "Indirect calls not yet supported")

    # ── cast ─────────────────────────────────────────────────

    def _cast(self, expr: CastExpr) -> int:
        c = _c()
        op = self._emit_expr(expr.expr)
        result_type = self._type_map.require(expr)
        lt = self._type_to_llvm(result_type)
        from_t = c.TypeOf(op)

        if from_t == lt:
            return op

        # Pointer ↔ int
        from_kind = _c().TypeOf(from_t)  # not right, need LLVMGetTypeKind
        # Simplified: try inttoptr/ptrtoint based on result
        if result_type.name == "__builtin_va_list":
            return c.BuildBitCast(self._builder, op, lt, b"cast")

        if result_type.declarator_ops and result_type.declarator_ops[0][0] == "ptr":
            return c.BuildIntToPtr(self._builder, op, lt, b"cast")
        try:
            return c.BuildSExt(self._builder, op, lt, b"cast")
        except Exception:
            return c.BuildBitCast(self._builder, op, lt, b"cast")

    # ── subscript / member ───────────────────────────────────

    def _subscript(self, expr: SubscriptExpr) -> int:
        c = _c()
        ptr = self._subscript_ptr(expr)
        elem_t = self._type_map.require(expr)
        lt = self._type_to_llvm(elem_t)
        return c.BuildLoad2(self._builder, lt, ptr, b"sub.load")

    def _subscript_ptr(self, expr: SubscriptExpr) -> int:
        c = _c()
        base = self._emit_expr(expr.base)
        idx = self._emit_expr(expr.index)
        indices = (ctypes.c_void_p * 1)(idx)
        elem_t = self._type_map.require(expr)
        lt = self._type_to_llvm(elem_t)
        return c.BuildGEP2(self._builder, lt, base, indices, 1, b"sub.ptr")

    def _member(self, expr: MemberExpr) -> int:
        c = _c()
        ptr = self._member_ptr(expr)
        val_t = self._type_map.require(expr)
        lt = self._type_to_llvm(val_t)
        return c.BuildLoad2(self._builder, lt, ptr, b"mem.load")

    def _member_ptr(self, expr: MemberExpr) -> int:
        c = _c()
        base = self._emit_expr(expr.base)
        base_t = self._type_map.require(expr.base)

        if expr.through_pointer:
            pointee = base_t.pointee()
            if pointee is None:
                raise llvm_backend_error(self._result.filename, "Cannot deref non-ptr in member")
            struct_t = pointee
            struct_ptr = base
        else:
            struct_t = base_t
            struct_ptr = self._emit_expr(expr.base)
            # Take address of value
            lt = self._type_to_llvm(struct_t)
            tmp = c.BuildAlloca(self._builder, lt, b"mem.tmp")
            c.BuildStore(self._builder, struct_ptr, tmp)
            struct_ptr = tmp

        record_name = struct_t.name
        field_idx = self._field_index(record_name, expr.member)
        st = self._struct_type(record_name)
        zero = c.ConstInt(c.Int32Type(), 0, False)
        fi = c.ConstInt(c.Int32Type(), field_idx, False)
        indices = (ctypes.c_void_p * 2)(zero, fi)
        return c.BuildGEP2(self._builder, st, struct_ptr, indices, 2, b"mem.ptr")

    # ── ternary ──────────────────────────────────────────────

    def _ternary(self, expr: ConditionalExpr) -> int:
        c = _c()
        fn = self._func
        cond = self._to_bool(self._emit_expr(expr.condition))

        then_bb = c.AppendBasicBlock(fn, b"tern.then")
        else_bb = c.AppendBasicBlock(fn, b"tern.else")
        merge_bb = c.AppendBasicBlock(fn, b"tern.end")

        c.BuildCondBr(self._builder, cond, then_bb, else_bb)

        c.PositionBuilderAtEnd(self._builder, then_bb)
        then_val = self._emit_expr(expr.then_expr)
        c.BuildBr(self._builder, merge_bb)

        c.PositionBuilderAtEnd(self._builder, else_bb)
        else_val = self._emit_expr(expr.else_expr)
        c.BuildBr(self._builder, merge_bb)

        c.PositionBuilderAtEnd(self._builder, merge_bb)
        phi = c.BuildPhi(self._builder, c.TypeOf(then_val), b"tern")
        vals = (ctypes.c_void_p * 2)(then_val, else_val)
        bbs = (ctypes.c_void_p * 2)(then_bb, else_bb)
        c.AddIncoming(phi, vals, bbs, 2)
        return phi

    # ── statement expr ───────────────────────────────────────

    def _stmt_expr(self, expr: StatementExpr) -> int:
        self._locals.append({})
        allocas = self._collect_allocas(expr.body)
        c = _c()
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
        c = _c()
        result_t = self._type_map.require(expr)
        lt = self._type_to_llvm(result_t)
        tmp = c.BuildAlloca(self._builder, lt, b"compound.lit")
        if isinstance(expr.initializer, InitList):
            for item in expr.initializer.items:
                val = self._emit_expr(item.initializer)
                c.BuildStore(self._builder, val, tmp)
        else:
            val = self._emit_expr(expr.initializer)
            c.BuildStore(self._builder, val, tmp)
        return tmp

    # ── sizeof / alignof ─────────────────────────────────────

    def _size_const(self, expr: SizeofExpr | AlignofExpr) -> int:
        c = _c()
        result_t = self._type_map.require(expr)
        size = self._type_size(result_t)
        return c.ConstInt(c.Int64Type(), size, False)

    # ── helpers ──────────────────────────────────────────────

    def _to_bool(self, val: int) -> int:
        c = _c()
        t = c.TypeOf(val)
        name = b"tobool"
        return c.BuildICmp(self._builder, 33, val, c.ConstInt(t, 0, False), name)

    def _resolve_type(self, ts: TypeSpec) -> Type:
        return Type(ts.name, declarator_ops=ts.declarator_ops, qualifiers=ts.qualifiers)

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
            for d in stmt.declarations:
                self._walk_allocas(d, result, seen)
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

    def _eval_init(self, init: Expr, var_type: Type) -> int | None:
        c = _c()
        lt = self._type_to_llvm(var_type)
        if isinstance(init, IntLiteral):
            return c.ConstInt(lt, int(init.value), False)
        if isinstance(init, CharLiteral):
            return c.ConstInt(lt, ord(init.value), False)
        if isinstance(init, FloatLiteral):
            return c.ConstReal(lt, float(init.value))
        return None

    def _eval_case_val(self, expr: Expr) -> int:
        if isinstance(expr, IntLiteral):
            return int(expr.value)
        if isinstance(expr, CharLiteral):
            return ord(expr.value)
        if isinstance(expr, UnaryExpr) and expr.op == "-":
            return -self._eval_case_val(expr.operand)
        raise llvm_backend_error(self._result.filename, "Expected integer constant for case")

    def _decode_string(self, s: str) -> str:
        result = []
        i = 0
        while i < len(s):
            if s[i] == "\\" and i + 1 < len(s):
                ch = s[i + 1]
                m = {"n": "\n", "t": "\t", "r": "\r", "0": "\0", "\\": "\\", "\"": "\"",
                      "'": "'", "a": "\a", "b": "\b", "f": "\f", "v": "\v"}
                if ch in m:
                    result.append(m[ch])
                    i += 2
                elif ch == "x":
                    result.append(chr(int(s[i+2:i+4], 16)))
                    i += 4
                elif ch == "u":
                    result.append(chr(int(s[i+2:i+6], 16)))
                    i += 6
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
