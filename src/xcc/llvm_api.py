"""LLVM-C ctypes bindings for the XCC backend.

This module owns libLLVM loading, enum constants, and raw C API signatures.
AST-to-LLVM lowering stays in xcc.codegen.
"""

import ctypes
from typing import Any

# ── libLLVM loading ─────────────────────────────────────────


def _load_llvm() -> ctypes.CDLL:
    path = "/opt/homebrew/opt/llvm/lib/libLLVM-C.dylib"
    return ctypes.CDLL(path)


class _LLVMState:
    def __init__(self) -> None:
        self.library: Any | None = None
        self.api: Any | None = None


_LLVM_STATE = _LLVMState()


def _llvm() -> Any:
    if _LLVM_STATE.library is None:
        _LLVM_STATE.library = _load_llvm()
    return _LLVM_STATE.library


# ── ctypes type aliases ─────────────────────────────────────

_c_void_p = ctypes.c_void_p
_c_char_p = ctypes.c_char_p
# LLVMBool is a C int, not C99 _Bool.  Using ctypes.c_bool leaves the upper
# register bytes unspecified on arm64 and can turn a false argument into true.
_c_bool = ctypes.c_int
_c_uint = ctypes.c_uint
_c_size_t = ctypes.c_size_t

# LLVM type aliases
_LLVMTypeRef = _c_void_p
_LLVMTypeKind = ctypes.c_int
_LLVMValueRef = _c_void_p
_LLVMMetadataRef = _c_void_p


class LLVMTypeKind:
    """LLVMTypeKind enum values from llvm-c/Core.h."""

    VOID = 0
    HALF = 1
    FLOAT = 2
    DOUBLE = 3
    X86_FP80 = 4
    FP128 = 5
    PPC_FP128 = 6
    LABEL = 7
    INTEGER = 8
    FUNCTION = 9
    STRUCT = 10
    ARRAY = 11
    POINTER = 12
    VECTOR = 13
    METADATA = 14
    X86_AMX = 15
    TOKEN = 16
    SCALABLE_VECTOR = 17
    BFLOAT = 18
    X86_MMX = 19


_LLVMBasicBlockRef = _c_void_p
_LLVMModuleRef = _c_void_p
_LLVMBuilderRef = _c_void_p
_LLVMContextRef = _c_void_p
_LLVMDIBuilderRef = _c_void_p

ATOMIC_ORDER_SEQ_CST = 7

ATOMIC_RMW_XCHG = 0
ATOMIC_RMW_ADD = 1
ATOMIC_RMW_SUB = 2
ATOMIC_RMW_AND = 3
ATOMIC_RMW_NAND = 4
ATOMIC_RMW_OR = 5
ATOMIC_RMW_XOR = 6

LLVM_EXTERNAL_LINKAGE = 0
LLVM_INTERNAL_LINKAGE = 8

LLVM_MODULE_FLAG_BEHAVIOR_WARNING = 1
LLVM_DWARF_SOURCE_LANGUAGE_C11 = 28
LLVM_DWARF_EMISSION_FULL = 1


def ptr_array(values: list[int] | tuple[int, ...]) -> Any:
    return (_c_void_p * len(values))(*values)


def zero_ptr_array(size: int) -> Any:
    return (_c_void_p * size)()


def optional_zero_ptr_array(size: int) -> Any:
    return None if size == 0 else zero_ptr_array(size)


# ── LLVM-C API bindings ─────────────────────────────────────


class _LLVMC:
    """Thin wrapper around libLLVM-C API."""

    def __init__(self, lib: Any) -> None:
        self._lib = lib

    def _bind(self, name: str, restype: Any, *argtypes: Any) -> Any:
        fn = self._lib[name]
        fn.restype = restype
        fn.argtypes = argtypes
        return fn

    def bind_all(self) -> None:
        # Context / Module
        self.ContextCreate = self._bind("LLVMContextCreate", _c_void_p)
        self.ModuleCreateWithName = self._bind(
            "LLVMModuleCreateWithName", _LLVMModuleRef, _c_char_p
        )
        self.SetTarget = self._bind("LLVMSetTarget", None, _LLVMModuleRef, _c_char_p)
        self.AddModuleFlag = self._bind(
            "LLVMAddModuleFlag",
            None,
            _LLVMModuleRef,
            _c_uint,
            _c_char_p,
            _c_size_t,
            _LLVMMetadataRef,
        )
        self.PrintModuleToString = self._bind("LLVMPrintModuleToString", _c_char_p, _LLVMModuleRef)
        self.DisposeModule = self._bind("LLVMDisposeModule", None, _LLVMModuleRef)

        # Types
        self.VoidType = self._bind("LLVMVoidType", _LLVMTypeRef)
        self.GetTypeKind = self._bind("LLVMGetTypeKind", _LLVMTypeKind, _LLVMTypeRef)
        self.GetIntTypeWidth = self._bind("LLVMGetIntTypeWidth", _c_uint, _LLVMTypeRef)
        self.GetArrayLength = self._bind("LLVMGetArrayLength", _c_uint, _LLVMTypeRef)
        self.Int1Type = self._bind("LLVMInt1Type", _LLVMTypeRef)
        self.Int8Type = self._bind("LLVMInt8Type", _LLVMTypeRef)
        self.Int16Type = self._bind("LLVMInt16Type", _LLVMTypeRef)
        self.Int32Type = self._bind("LLVMInt32Type", _LLVMTypeRef)
        self.Int64Type = self._bind("LLVMInt64Type", _LLVMTypeRef)
        self.FloatType = self._bind("LLVMFloatType", _LLVMTypeRef)
        self.DoubleType = self._bind("LLVMDoubleType", _LLVMTypeRef)
        self.X86FP80Type = self._bind("LLVMX86FP80Type", _LLVMTypeRef)
        self.FP128Type = self._bind("LLVMFP128Type", _LLVMTypeRef)
        self.PointerType = self._bind("LLVMPointerType", _LLVMTypeRef, _LLVMTypeRef, _c_uint)
        self.FunctionType = self._bind(
            "LLVMFunctionType",
            _LLVMTypeRef,
            _LLVMTypeRef,
            ctypes.POINTER(_LLVMTypeRef),
            _c_uint,
            _c_bool,
        )
        self.ArrayType = self._bind("LLVMArrayType2", _LLVMTypeRef, _LLVMTypeRef, _c_uint)
        self.StructType = self._bind(
            "LLVMStructType",
            _LLVMTypeRef,
            ctypes.POINTER(_LLVMTypeRef),
            _c_uint,
            _c_bool,
        )
        self.StructSetBody = self._bind(
            "LLVMStructSetBody",
            None,
            _LLVMTypeRef,
            ctypes.POINTER(_LLVMTypeRef),
            _c_uint,
            _c_bool,
        )

        # Values / Constants
        self.ConstInt = self._bind(
            "LLVMConstInt", _LLVMValueRef, _LLVMTypeRef, ctypes.c_ulonglong, _c_bool
        )
        self.ConstReal = self._bind("LLVMConstReal", _LLVMValueRef, _LLVMTypeRef, ctypes.c_double)
        self.ConstString = self._bind("LLVMConstString", _LLVMValueRef, _c_char_p, _c_uint, _c_bool)
        self.ConstNull = self._bind("LLVMConstNull", _LLVMValueRef, _LLVMTypeRef)
        self.ConstArray = self._bind(
            "LLVMConstArray2",
            _LLVMValueRef,
            _LLVMTypeRef,
            ctypes.POINTER(_LLVMValueRef),
            _c_size_t,
        )
        self.ConstNamedStruct = self._bind(
            "LLVMConstNamedStruct",
            _LLVMValueRef,
            _LLVMTypeRef,
            ctypes.POINTER(_LLVMValueRef),
            _c_uint,
        )
        self.ConstStructInContext = self._bind(
            "LLVMConstStructInContext",
            _LLVMValueRef,
            _LLVMContextRef,
            ctypes.POINTER(_LLVMValueRef),
            _c_uint,
            _c_bool,
        )
        self.ConstGEP2 = self._bind(
            "LLVMConstGEP2",
            _LLVMValueRef,
            _LLVMTypeRef,
            _LLVMValueRef,
            ctypes.POINTER(_LLVMValueRef),
            _c_uint,
        )
        self.ConstPointerCast = self._bind(
            "LLVMConstPointerCast", _LLVMValueRef, _LLVMValueRef, _LLVMTypeRef
        )
        self.ConstBitCast = self._bind(
            "LLVMConstBitCast", _LLVMValueRef, _LLVMValueRef, _LLVMTypeRef
        )
        self.ConstIntToPtr = self._bind(
            "LLVMConstIntToPtr", _LLVMValueRef, _LLVMValueRef, _LLVMTypeRef
        )
        self.ConstPtrToInt = self._bind(
            "LLVMConstPtrToInt", _LLVMValueRef, _LLVMValueRef, _LLVMTypeRef
        )
        self.ConstTrunc = self._bind("LLVMConstTrunc", _LLVMValueRef, _LLVMValueRef, _LLVMTypeRef)
        self.ConstTruncOrBitCast = self._bind(
            "LLVMConstTruncOrBitCast", _LLVMValueRef, _LLVMValueRef, _LLVMTypeRef
        )
        self.AddGlobal = self._bind(
            "LLVMAddGlobal", _LLVMValueRef, _LLVMModuleRef, _LLVMTypeRef, _c_char_p
        )
        self.SetInitializer = self._bind("LLVMSetInitializer", None, _LLVMValueRef, _LLVMValueRef)
        self.SetLinkage = self._bind("LLVMSetLinkage", None, _LLVMValueRef, _c_uint)
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
        self.GetParam = self._bind("LLVMGetParam", _LLVMValueRef, _LLVMValueRef, _c_uint)
        self.AppendBasicBlock = self._bind(
            "LLVMAppendBasicBlock", _LLVMBasicBlockRef, _LLVMValueRef, _c_char_p
        )
        self.GetBasicBlockTerminator = self._bind(
            "LLVMGetBasicBlockTerminator", _LLVMValueRef, _LLVMBasicBlockRef
        )
        self.SetValueName2 = self._bind(
            "LLVMSetValueName2", None, _LLVMValueRef, _c_char_p, _c_size_t
        )
        self.GetReturnType = self._bind("LLVMGetReturnType", _LLVMTypeRef, _LLVMTypeRef)
        self.ValueAsMetadata = self._bind("LLVMValueAsMetadata", _LLVMMetadataRef, _LLVMValueRef)
        self.CountParamTypes = self._bind(
            "LLVMCountParamTypes", None, _LLVMTypeRef, ctypes.POINTER(_c_uint)
        )
        self.GetParamTypes = self._bind(
            "LLVMGetParamTypes", None, _LLVMTypeRef, ctypes.POINTER(_LLVMTypeRef)
        )

        # Builder
        self.CreateBuilder = self._bind("LLVMCreateBuilder", _LLVMBuilderRef)
        self.PositionBuilderAtEnd = self._bind(
            "LLVMPositionBuilderAtEnd", None, _LLVMBuilderRef, _LLVMBasicBlockRef
        )
        self.PositionBuilderBefore = self._bind(
            "LLVMPositionBuilderBefore", None, _LLVMBuilderRef, _LLVMValueRef
        )
        self.GetInsertBlock = self._bind("LLVMGetInsertBlock", _LLVMBasicBlockRef, _LLVMBuilderRef)
        self.DisposeBuilder = self._bind("LLVMDisposeBuilder", None, _LLVMBuilderRef)
        self.GetCurrentDebugLocation2 = self._bind(
            "LLVMGetCurrentDebugLocation2", _LLVMMetadataRef, _LLVMBuilderRef
        )
        self.SetCurrentDebugLocation2 = self._bind(
            "LLVMSetCurrentDebugLocation2", None, _LLVMBuilderRef, _LLVMMetadataRef
        )

        # Debug information
        self.CreateDIBuilder = self._bind("LLVMCreateDIBuilder", _LLVMDIBuilderRef, _LLVMModuleRef)
        self.DisposeDIBuilder = self._bind("LLVMDisposeDIBuilder", None, _LLVMDIBuilderRef)
        self.DIBuilderFinalize = self._bind("LLVMDIBuilderFinalize", None, _LLVMDIBuilderRef)
        self.DIBuilderCreateFile = self._bind(
            "LLVMDIBuilderCreateFile",
            _LLVMMetadataRef,
            _LLVMDIBuilderRef,
            _c_char_p,
            _c_size_t,
            _c_char_p,
            _c_size_t,
        )
        self.DIBuilderCreateCompileUnit = self._bind(
            "LLVMDIBuilderCreateCompileUnit",
            _LLVMMetadataRef,
            _LLVMDIBuilderRef,
            _c_uint,
            _LLVMMetadataRef,
            _c_char_p,
            _c_size_t,
            _c_bool,
            _c_char_p,
            _c_size_t,
            _c_uint,
            _c_char_p,
            _c_size_t,
            _c_uint,
            _c_uint,
            _c_bool,
            _c_bool,
            _c_char_p,
            _c_size_t,
            _c_char_p,
            _c_size_t,
        )
        self.DIBuilderCreateSubroutineType = self._bind(
            "LLVMDIBuilderCreateSubroutineType",
            _LLVMMetadataRef,
            _LLVMDIBuilderRef,
            _LLVMMetadataRef,
            ctypes.POINTER(_LLVMMetadataRef),
            _c_uint,
            _c_uint,
        )
        self.DIBuilderCreateFunction = self._bind(
            "LLVMDIBuilderCreateFunction",
            _LLVMMetadataRef,
            _LLVMDIBuilderRef,
            _LLVMMetadataRef,
            _c_char_p,
            _c_size_t,
            _c_char_p,
            _c_size_t,
            _LLVMMetadataRef,
            _c_uint,
            _LLVMMetadataRef,
            _c_bool,
            _c_bool,
            _c_uint,
            _c_uint,
            _c_bool,
        )
        self.DIBuilderCreateLexicalBlockFile = self._bind(
            "LLVMDIBuilderCreateLexicalBlockFile",
            _LLVMMetadataRef,
            _LLVMDIBuilderRef,
            _LLVMMetadataRef,
            _LLVMMetadataRef,
            _c_uint,
        )
        self.DIBuilderCreateDebugLocation = self._bind(
            "LLVMDIBuilderCreateDebugLocation",
            _LLVMMetadataRef,
            _LLVMContextRef,
            _c_uint,
            _c_uint,
            _LLVMMetadataRef,
            _LLVMMetadataRef,
        )
        self.SetSubprogram = self._bind("LLVMSetSubprogram", None, _LLVMValueRef, _LLVMMetadataRef)

        # Terminators
        self.BuildRetVoid = self._bind("LLVMBuildRetVoid", _LLVMValueRef, _LLVMBuilderRef)
        self.BuildRet = self._bind("LLVMBuildRet", _LLVMValueRef, _LLVMBuilderRef, _LLVMValueRef)
        self.BuildUnreachable = self._bind("LLVMBuildUnreachable", _LLVMValueRef, _LLVMBuilderRef)
        self.BuildBr = self._bind("LLVMBuildBr", _LLVMValueRef, _LLVMBuilderRef, _LLVMBasicBlockRef)
        self.BuildCondBr = self._bind(
            "LLVMBuildCondBr",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMValueRef,
            _LLVMBasicBlockRef,
            _LLVMBasicBlockRef,
        )
        self.BuildSwitch = self._bind(
            "LLVMBuildSwitch",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMValueRef,
            _LLVMBasicBlockRef,
            _c_uint,
        )
        self.AddCase = self._bind(
            "LLVMAddCase", None, _LLVMValueRef, _LLVMValueRef, _LLVMBasicBlockRef
        )

        # Arithmetic
        self.BuildAdd = self._bind(
            "LLVMBuildAdd",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMValueRef,
            _LLVMValueRef,
            _c_char_p,
        )
        self.BuildFAdd = self._bind(
            "LLVMBuildFAdd",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMValueRef,
            _LLVMValueRef,
            _c_char_p,
        )
        self.BuildSub = self._bind(
            "LLVMBuildSub",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMValueRef,
            _LLVMValueRef,
            _c_char_p,
        )
        self.BuildFSub = self._bind(
            "LLVMBuildFSub",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMValueRef,
            _LLVMValueRef,
            _c_char_p,
        )
        self.BuildMul = self._bind(
            "LLVMBuildMul",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMValueRef,
            _LLVMValueRef,
            _c_char_p,
        )
        self.BuildFMul = self._bind(
            "LLVMBuildFMul",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMValueRef,
            _LLVMValueRef,
            _c_char_p,
        )
        self.BuildNeg = self._bind(
            "LLVMBuildNeg",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMValueRef,
            _c_char_p,
        )
        self.BuildFNeg = self._bind(
            "LLVMBuildFNeg",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMValueRef,
            _c_char_p,
        )
        self.BuildSDiv = self._bind(
            "LLVMBuildSDiv",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMValueRef,
            _LLVMValueRef,
            _c_char_p,
        )
        self.BuildUDiv = self._bind(
            "LLVMBuildUDiv",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMValueRef,
            _LLVMValueRef,
            _c_char_p,
        )
        self.BuildFDiv = self._bind(
            "LLVMBuildFDiv",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMValueRef,
            _LLVMValueRef,
            _c_char_p,
        )
        self.BuildSRem = self._bind(
            "LLVMBuildSRem",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMValueRef,
            _LLVMValueRef,
            _c_char_p,
        )
        self.BuildURem = self._bind(
            "LLVMBuildURem",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMValueRef,
            _LLVMValueRef,
            _c_char_p,
        )
        self.BuildFRem = self._bind(
            "LLVMBuildFRem",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMValueRef,
            _LLVMValueRef,
            _c_char_p,
        )
        self.BuildAnd = self._bind(
            "LLVMBuildAnd",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMValueRef,
            _LLVMValueRef,
            _c_char_p,
        )
        self.BuildOr = self._bind(
            "LLVMBuildOr",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMValueRef,
            _LLVMValueRef,
            _c_char_p,
        )
        self.BuildXor = self._bind(
            "LLVMBuildXor",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMValueRef,
            _LLVMValueRef,
            _c_char_p,
        )
        self.BuildShl = self._bind(
            "LLVMBuildShl",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMValueRef,
            _LLVMValueRef,
            _c_char_p,
        )
        self.BuildAShr = self._bind(
            "LLVMBuildAShr",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMValueRef,
            _LLVMValueRef,
            _c_char_p,
        )
        self.BuildLShr = self._bind(
            "LLVMBuildLShr",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMValueRef,
            _LLVMValueRef,
            _c_char_p,
        )

        # Memory
        self.BuildAlloca = self._bind(
            "LLVMBuildAlloca",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMTypeRef,
            _c_char_p,
        )
        self.BuildArrayAlloca = self._bind(
            "LLVMBuildArrayAlloca",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMTypeRef,
            _LLVMValueRef,
            _c_char_p,
        )
        self.BuildLoad2 = self._bind(
            "LLVMBuildLoad2",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMTypeRef,
            _LLVMValueRef,
            _c_char_p,
        )
        self.BuildStore = self._bind(
            "LLVMBuildStore",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMValueRef,
            _LLVMValueRef,
        )

        # GEP
        self.BuildGEP2 = self._bind(
            "LLVMBuildGEP2",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMTypeRef,
            _LLVMValueRef,
            ctypes.POINTER(_LLVMValueRef),
            _c_uint,
            _c_char_p,
        )

        # Cast
        self.BuildSExt = self._bind(
            "LLVMBuildSExt",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMValueRef,
            _LLVMTypeRef,
            _c_char_p,
        )
        self.BuildZExt = self._bind(
            "LLVMBuildZExt",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMValueRef,
            _LLVMTypeRef,
            _c_char_p,
        )
        self.BuildTrunc = self._bind(
            "LLVMBuildTrunc",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMValueRef,
            _LLVMTypeRef,
            _c_char_p,
        )
        self.BuildIntToPtr = self._bind(
            "LLVMBuildIntToPtr",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMValueRef,
            _LLVMTypeRef,
            _c_char_p,
        )
        self.BuildPtrToInt = self._bind(
            "LLVMBuildPtrToInt",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMValueRef,
            _LLVMTypeRef,
            _c_char_p,
        )
        self.BuildFPCast = self._bind(
            "LLVMBuildFPCast",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMValueRef,
            _LLVMTypeRef,
            _c_char_p,
        )
        self.BuildSIToFP = self._bind(
            "LLVMBuildSIToFP",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMValueRef,
            _LLVMTypeRef,
            _c_char_p,
        )
        self.BuildFPToSI = self._bind(
            "LLVMBuildFPToSI",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMValueRef,
            _LLVMTypeRef,
            _c_char_p,
        )
        self.BuildBitCast = self._bind(
            "LLVMBuildBitCast",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMValueRef,
            _LLVMTypeRef,
            _c_char_p,
        )

        # Comparison
        self.BuildICmp = self._bind(
            "LLVMBuildICmp",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _c_uint,
            _LLVMValueRef,
            _LLVMValueRef,
            _c_char_p,
        )
        self.BuildFCmp = self._bind(
            "LLVMBuildFCmp",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _c_uint,
            _LLVMValueRef,
            _LLVMValueRef,
            _c_char_p,
        )
        self.BuildIntCast2 = self._bind(
            "LLVMBuildIntCast2",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMValueRef,
            _LLVMTypeRef,
            _c_bool,
            _c_char_p,
        )
        self.BuildSelect = self._bind(
            "LLVMBuildSelect",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMValueRef,
            _LLVMValueRef,
            _LLVMValueRef,
            _c_char_p,
        )

        # Calls
        self.BuildCall2 = self._bind(
            "LLVMBuildCall2",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMTypeRef,
            _LLVMValueRef,
            ctypes.POINTER(_LLVMValueRef),
            _c_uint,
            _c_char_p,
        )
        self.BuildVAArg = self._bind(
            "LLVMBuildVAArg",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMValueRef,
            _LLVMTypeRef,
            _c_char_p,
        )
        self.BuildExtractValue = self._bind(
            "LLVMBuildExtractValue",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMValueRef,
            _c_uint,
            _c_char_p,
        )
        self.BuildMemSet = self._bind(
            "LLVMBuildMemSet",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMValueRef,
            _LLVMValueRef,
            _LLVMValueRef,
            _c_bool,
        )
        self.BuildMemCpy = self._bind(
            "LLVMBuildMemCpy",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMValueRef,
            _c_uint,
            _LLVMValueRef,
            _c_uint,
            _LLVMValueRef,
        )
        self.GetUndef = self._bind("LLVMGetUndef", _LLVMValueRef, _LLVMTypeRef)
        self.IsUndef = self._bind("LLVMIsUndef", ctypes.c_bool, _LLVMValueRef)
        self.SetAlignment = self._bind("LLVMSetAlignment", None, _LLVMValueRef, _c_uint)
        self.SetOrdering = self._bind("LLVMSetOrdering", None, _LLVMValueRef, _c_uint)
        self.BuildFence = self._bind(
            "LLVMBuildFence",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _c_uint,
            _c_bool,
            _c_char_p,
        )
        self.BuildAtomicRMW = self._bind(
            "LLVMBuildAtomicRMW",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _c_uint,
            _LLVMValueRef,
            _LLVMValueRef,
            _c_uint,
            _c_bool,
        )
        self.BuildAtomicCmpXchg = self._bind(
            "LLVMBuildAtomicCmpXchg",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMValueRef,
            _LLVMValueRef,
            _LLVMValueRef,
            _c_uint,
            _c_uint,
            _c_bool,
        )

        # PHI
        self.BuildPhi = self._bind(
            "LLVMBuildPhi",
            _LLVMValueRef,
            _LLVMBuilderRef,
            _LLVMTypeRef,
            _c_char_p,
        )
        self.AddIncoming = self._bind(
            "LLVMAddIncoming",
            None,
            _LLVMValueRef,
            ctypes.POINTER(_LLVMValueRef),
            ctypes.POINTER(_LLVMBasicBlockRef),
            _c_uint,
        )

        # Misc
        self.TypeOf = self._bind("LLVMTypeOf", _LLVMTypeRef, _LLVMValueRef)
        self.ConstPointerNull = self._bind("LLVMConstPointerNull", _LLVMValueRef, _LLVMTypeRef)
        self.IsNull = self._bind("LLVMIsNull", _c_bool, _LLVMValueRef)
        self.IsAConstantInt = self._bind("LLVMIsAConstantInt", _LLVMValueRef, _LLVMValueRef)
        self.ConstIntGetSExtValue = self._bind(
            "LLVMConstIntGetSExtValue", ctypes.c_longlong, _LLVMValueRef
        )
        self.ConstIntGetZExtValue = self._bind(
            "LLVMConstIntGetZExtValue", ctypes.c_ulonglong, _LLVMValueRef
        )
        self.GetNumOperands = self._bind("LLVMGetNumOperands", _c_uint, _LLVMValueRef)
        self.GetOperand = self._bind("LLVMGetOperand", _LLVMValueRef, _LLVMValueRef, _c_uint)
        self.GetAggregateElement = self._bind(
            "LLVMGetAggregateElement", _LLVMValueRef, _LLVMValueRef, _c_uint
        )


def llvm() -> Any:
    if _LLVM_STATE.api is None:
        api = _LLVMC(_llvm())
        api.bind_all()
        _LLVM_STATE.api = api
    return _LLVM_STATE.api
