from xcc.aot.analysis import AotAnalysis, analyze_path, analyze_source
from xcc.aot.binder import bind_types
from xcc.aot.diag import AotDiagnostic, AotError
from xcc.aot.ir import (
    IrAssign,
    IrBinary,
    IrCall,
    IrConstInt,
    IrConstructRecord,
    IrConstString,
    IrExpr,
    IrField,
    IrFunction,
    IrGetField,
    IrIntType,
    IrModule,
    IrName,
    IrParam,
    IrRecord,
    IrRecordType,
    IrReturn,
    IrStmt,
    IrStringType,
    IrType,
)
from xcc.aot.llvm_text import emit_llvm_text
from xcc.aot.lower import lower_source_to_ir
from xcc.aot.module import AotModule, parse_path, parse_source
from xcc.aot.native import NativeSmokeResult, run_native_smoke
from xcc.aot.slice import AotSliceInput, collect_slice_inputs
from xcc.aot.subset import AotModuleSummary, check_subset
from xcc.aot.types import AotClassInfo, AotFunctionInfo, AotType, AotTypeAnalysis

__all__ = (
    "AotAnalysis",
    "AotClassInfo",
    "AotDiagnostic",
    "AotError",
    "AotFunctionInfo",
    "AotModule",
    "AotModuleSummary",
    "AotSliceInput",
    "AotType",
    "AotTypeAnalysis",
    "IrAssign",
    "IrBinary",
    "IrCall",
    "IrConstInt",
    "IrConstString",
    "IrConstructRecord",
    "IrExpr",
    "IrField",
    "IrFunction",
    "IrGetField",
    "IrIntType",
    "IrModule",
    "IrName",
    "IrParam",
    "IrRecord",
    "IrRecordType",
    "IrReturn",
    "IrStmt",
    "IrStringType",
    "IrType",
    "NativeSmokeResult",
    "analyze_path",
    "analyze_source",
    "bind_types",
    "check_subset",
    "collect_slice_inputs",
    "emit_llvm_text",
    "lower_source_to_ir",
    "parse_path",
    "parse_source",
    "run_native_smoke",
)
