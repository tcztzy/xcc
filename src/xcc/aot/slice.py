from dataclasses import dataclass
from pathlib import Path

from xcc.aot.diag import AotDiagnostic, AotError
from xcc.aot.ir import (
    IrAssign,
    IrCall,
    IrConstBool,
    IrConstInt,
    IrConstNone,
    IrConstructRecord,
    IrConstString,
    IrFunction,
    IrIntType,
    IrModule,
    IrNoneType,
    IrPrint,
    IrRecord,
    IrRecordType,
    IrReturn,
    IrStringType,
    IrTuple,
    IrTupleType,
)
from xcc.aot.lower import lower_source_to_ir


@dataclass(frozen=True)
class AotSliceInput:
    name: str
    path: Path


def collect_slice_inputs(paths: tuple[Path, ...]) -> tuple[AotSliceInput, ...]:
    root = (Path.cwd() / "src" / "xcc").resolve()
    modules: list[AotSliceInput] = []
    for path in paths:
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(root)
        except ValueError as exc:
            raise AotError(
                (
                    AotDiagnostic(
                        "XCC-AOT-SLICE-0001",
                        f"Module is outside src/xcc: {resolved}",
                        filename=str(resolved),
                    ),
                )
            ) from exc
        if relative.suffix != ".py":
            raise AotError(
                (
                    AotDiagnostic(
                        "XCC-AOT-SLICE-0001",
                        f"Module is not Python source: {resolved}",
                        filename=str(resolved),
                    ),
                )
            )
        modules.append(AotSliceInput("xcc." + ".".join(relative.with_suffix("").parts), resolved))
    return tuple(sorted(modules, key=lambda module: module.name))


def lower_core_slice(paths: tuple[Path, ...]) -> IrModule:
    records: list[IrRecord] = []
    functions: list[IrFunction] = []
    for module_input in collect_slice_inputs(paths):
        source = module_input.path.read_text(encoding="utf-8")
        module = lower_source_to_ir(source, filename=str(module_input.path))
        records.extend(module.records)
        prefix = module_input.name
        for function in module.functions:
            functions.append(
                IrFunction(
                    f"{prefix}.{function.name}",
                    function.params,
                    function.return_type,
                    function.body,
                )
            )
    return IrModule("<core-slice>", tuple(records), tuple(functions))


def core_entry_wrapper(entry: str, fixture: str) -> IrFunction:
    if entry == "xcc.diag:Diagnostic.__str__" and fixture == "diag_with_location":
        return _diagnostic_str_wrapper()
    if entry == "xcc.options:FrontendOptions.__post_init__" and fixture == "bad_std":
        return _frontend_options_bad_std_wrapper()
    if entry == "xcc.types:Type.pointer_array_str" and fixture == "int_pointer_array":
        return _type_pointer_array_str_wrapper()
    raise AotError(
        (
            AotDiagnostic(
                "XCC-AOT-SLICE-0002",
                f"Unsupported core entry fixture: {entry} / {fixture}",
                filename="<core-slice>",
            ),
        )
    )


def _diagnostic_str_wrapper() -> IrFunction:
    int32 = IrIntType(32, signed=True)
    diagnostic_type = IrRecordType("Diagnostic")
    return IrFunction(
        "__xcc_aot_core_entry",
        (),
        int32,
        (
            IrPrint(
                IrCall(
                    "xcc.diag.Diagnostic.__str__",
                    (
                        IrConstructRecord(
                            "Diagnostic",
                            (
                                IrConstString("parse"),
                                IrConstString("input.c"),
                                IrConstString("expected ';'"),
                                IrConstInt(7, IrIntType(64, signed=True)),
                                IrConstInt(3, IrIntType(64, signed=True)),
                                IrConstNone(),
                            ),
                            diagnostic_type,
                        ),
                    ),
                    IrStringType(),
                ),
            ),
            IrReturn(IrConstInt(0, int32)),
        ),
    )


def _frontend_options_bad_std_wrapper() -> IrFunction:
    int32 = IrIntType(32, signed=True)
    options_type = IrRecordType("FrontendOptions")
    string_tuple = IrTuple((), IrTupleType((IrStringType(),)))
    return IrFunction(
        "__xcc_aot_core_entry",
        (),
        int32,
        (
            IrAssign(
                "__expr",
                IrCall(
                    "xcc.options.FrontendOptions.__post_init__",
                    (
                        IrConstructRecord(
                            "FrontendOptions",
                            (
                                IrConstString("c99"),
                                IrConstBool(True),
                                string_tuple,
                                string_tuple,
                                string_tuple,
                                string_tuple,
                                string_tuple,
                                string_tuple,
                                string_tuple,
                                string_tuple,
                                string_tuple,
                                IrConstBool(False),
                                IrConstString("human"),
                                IrConstBool(False),
                                IrConstNone(),
                                IrConstNone(),
                                IrConstBool(True),
                            ),
                            options_type,
                        ),
                    ),
                    IrNoneType(),
                ),
            ),
            IrReturn(IrConstInt(0, int32)),
        ),
    )


def _type_pointer_array_str_wrapper() -> IrFunction:
    int32 = IrIntType(32, signed=True)
    type_type = IrRecordType("Type")
    empty_tuple = IrTuple((), IrTupleType(()))
    base = IrConstructRecord(
        "Type",
        (
            IrConstString("int"),
            IrConstInt(0, IrIntType(64, signed=True)),
            empty_tuple,
            empty_tuple,
            empty_tuple,
        ),
        type_type,
    )
    pointer = IrCall("xcc.types.Type.pointer_to", (base,), type_type)
    array = IrCall(
        "xcc.types.Type.array_of",
        (pointer, IrConstInt(4, IrIntType(64, signed=True))),
        type_type,
    )
    rendered = IrCall("xcc.types.Type.__str__", (array,), IrStringType())
    return IrFunction(
        "__xcc_aot_core_entry",
        (),
        int32,
        (
            IrPrint(rendered),
            IrReturn(IrConstInt(0, int32)),
        ),
    )
