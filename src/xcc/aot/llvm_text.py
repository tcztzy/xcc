from dataclasses import dataclass

from xcc.aot.diag import AotDiagnostic, AotError
from xcc.aot.ir import (
    IrAssign,
    IrBinary,
    IrCall,
    IrConstInt,
    IrConstructRecord,
    IrConstString,
    IrExpr,
    IrFunction,
    IrGetField,
    IrIntType,
    IrModule,
    IrName,
    IrRecord,
    IrRecordType,
    IrReturn,
    IrStmt,
    IrStringType,
    IrType,
)


@dataclass(frozen=True)
class _EmittedValue:
    value: str
    type: IrType


def emit_llvm_text(module: IrModule) -> str:
    emitter = _Emitter(module)
    return emitter.emit()


class _Emitter:
    def __init__(self, module: IrModule) -> None:
        self.module = module
        self.records = {record.name: record for record in module.records}
        self.functions = {function.name: function for function in module.functions}
        self.index = 0
        self.string_index = 0
        self.string_constants: list[str] = []
        self.needs_puts = False

    def emit(self) -> str:
        declarations = [self._emit_record(record) for record in self.module.records]
        functions = [self._emit_function(function) for function in self.module.functions]
        main = self._emit_main()
        lines: list[str] = []
        if self.string_constants:
            lines.extend(self.string_constants)
            lines.append("")
        lines.extend(declaration for declaration in declarations if declaration)
        if declarations:
            lines.append("")
        if self.needs_puts:
            lines.append("declare i32 @puts(ptr)")
            lines.append("")
        lines.extend(functions)
        if main is not None:
            lines.append(main)
        return "\n".join(lines).rstrip() + "\n"

    def _emit_record(self, record: IrRecord) -> str:
        fields = ", ".join(self._llvm_type(field.type) for field in record.fields)
        return f"%{record.name} = type {{ {fields} }}"

    def _emit_function(self, function: IrFunction) -> str:
        self.index = 0
        params = ", ".join(
            f"{self._param_llvm_type(param.type)} %{param.name}" for param in function.params
        )
        lines = [f"define {self._llvm_type(function.return_type)} @{function.name}({params}) {{"]
        lines.append("entry:")
        names = {
            param.name: _EmittedValue(f"%{param.name}", param.type) for param in function.params
        }
        for statement in function.body:
            self._emit_statement(statement, names, lines, function.return_type)
        lines.append("}")
        return "\n".join(lines)

    def _emit_statement(
        self,
        statement: IrStmt,
        names: dict[str, _EmittedValue],
        lines: list[str],
        return_type: IrType,
    ) -> None:
        if isinstance(statement, IrAssign):
            if isinstance(statement.value, IrConstructRecord):
                value = self._emit_construct_record(statement.value, names, lines, statement.target)
            else:
                value = self._emit_expr(statement.value, names, lines)
            names[statement.target] = value
            return
        if isinstance(statement, IrReturn):
            value = self._emit_expr(statement.value, names, lines)
            lines.append(f"  ret {self._llvm_type(return_type)} {value.value}")
            return
        self._error(f"Unsupported LLVM statement: {type(statement).__name__}")

    def _emit_expr(
        self,
        expr: IrExpr,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if isinstance(expr, IrConstInt):
            return _EmittedValue(str(expr.value), expr.type)
        if isinstance(expr, IrConstString):
            return _EmittedValue(self._string_constant(expr.value), IrStringType())
        if isinstance(expr, IrName):
            value = names.get(expr.name)
            if value is None:
                self._error(f"Unknown LLVM name: {expr.name}")
            return value
        if isinstance(expr, IrBinary):
            return self._emit_binary(expr, names, lines)
        if isinstance(expr, IrConstructRecord):
            return self._emit_construct_record(expr, names, lines)
        if isinstance(expr, IrGetField):
            return self._emit_get_field(expr, names, lines)
        if isinstance(expr, IrCall):
            return self._emit_call(expr, names, lines)
        self._error(f"Unsupported LLVM expression: {type(expr).__name__}")

    def _emit_binary(
        self,
        expr: IrBinary,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        left = self._emit_expr(expr.left, names, lines)
        right = self._emit_expr(expr.right, names, lines)
        opcode = {"+": "add", "-": "sub", "*": "mul"}.get(expr.op)
        if opcode is None:
            self._error(f"Unsupported LLVM binary op: {expr.op}")
        result = self._tmp(opcode)
        lines.append(
            f"  {result} = {opcode} {self._llvm_type(expr.type)} {left.value}, {right.value}"
        )
        return _EmittedValue(result, expr.type)

    def _emit_construct_record(
        self,
        expr: IrConstructRecord,
        names: dict[str, _EmittedValue],
        lines: list[str],
        target: str | None = None,
    ) -> _EmittedValue:
        result = f"%{target}" if target is not None else self._tmp(expr.record.lower())
        lines.append(f"  {result} = alloca %{expr.record}")
        record = self.records[expr.record]
        for index, (arg, field) in enumerate(zip(expr.args, record.fields, strict=True)):
            value = self._emit_expr(arg, names, lines)
            field_ptr = self._tmp("fieldptr")
            lines.append(
                f"  {field_ptr} = getelementptr inbounds %{expr.record}, ptr {result}, "
                f"i32 0, i32 {index}"
            )
            lines.append(f"  store {self._llvm_type(field.type)} {value.value}, ptr {field_ptr}")
        return _EmittedValue(result, expr.type)

    def _emit_get_field(
        self,
        expr: IrGetField,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        value = self._emit_expr(expr.value, names, lines)
        if not isinstance(value.type, IrRecordType):
            self._error(f"Unsupported LLVM field receiver: {expr.field}")
        index = self._field_index(value.type.name, expr.field)
        field_ptr = self._tmp("fieldptr")
        result = self._tmp("load")
        lines.append(
            f"  {field_ptr} = getelementptr inbounds %{value.type.name}, ptr {value.value}, "
            f"i32 0, i32 {index}"
        )
        lines.append(f"  {result} = load {self._llvm_type(expr.type)}, ptr {field_ptr}")
        return _EmittedValue(result, expr.type)

    def _emit_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        args = [self._emit_expr(arg, names, lines) for arg in expr.args]
        rendered_args = ", ".join(f"{self._param_llvm_type(arg.type)} {arg.value}" for arg in args)
        result = self._tmp("call")
        lines.append(
            f"  {result} = call {self._llvm_type(expr.type)} @{expr.target}({rendered_args})"
        )
        return _EmittedValue(result, expr.type)

    def _emit_main(self) -> str | None:
        if self.module.entry is None:
            return None
        function = self.functions[self.module.entry]
        return_type = function.return_type
        lines = ["define i32 @main() {", "entry:"]
        result_type = self._llvm_type(return_type)
        lines.append(f"  %result = call {result_type} @{function.name}()")
        if isinstance(return_type, IrStringType):
            self.needs_puts = True
            lines.append("  %printed = call i32 @puts(ptr %result)")
            lines.append("  ret i32 0")
        elif isinstance(return_type, IrIntType):
            lines.append(f"  %exit = trunc {result_type} %result to i32")
            lines.append("  ret i32 %exit")
        else:
            self._error(f"Unsupported main return type: {type(return_type).__name__}")
        lines.append("}")
        return "\n".join(lines)

    def _string_constant(self, value: str) -> str:
        escaped = _escape_c_string(value)
        name = f"@.str{self.string_index}"
        self.string_index += 1
        size = len(value.encode("utf-8")) + 1
        self.string_constants.append(
            f'{name} = private unnamed_addr constant [{size} x i8] c"{escaped}\\00", align 1'
        )
        return name

    def _field_index(self, record_name: str, field: str) -> int:
        record = self.records[record_name]
        for index, candidate in enumerate(record.fields):
            if candidate.name == field:
                return index
        self._error(f"Unknown LLVM record field: {record_name}.{field}")

    def _llvm_type(self, type_info: IrType) -> str:
        if isinstance(type_info, IrIntType):
            return f"i{type_info.bits}"
        if isinstance(type_info, IrStringType):
            return "ptr"
        if isinstance(type_info, IrRecordType):
            return f"%{type_info.name}"
        self._error(f"Unsupported LLVM type: {type(type_info).__name__}")

    def _param_llvm_type(self, type_info: IrType) -> str:
        if isinstance(type_info, IrRecordType):
            return "ptr"
        return self._llvm_type(type_info)

    def _tmp(self, prefix: str) -> str:
        self.index += 1
        return f"%{prefix}{self.index}"

    def _error(self, message: str) -> None:
        raise AotError(
            (
                AotDiagnostic(
                    "XCC-AOT-LLVM-0001",
                    message,
                    filename=self.module.filename,
                ),
            )
        )


def _escape_c_string(value: str) -> str:
    chunks: list[str] = []
    for byte in value.encode("utf-8"):
        if byte == 34:
            chunks.append("\\22")
        elif byte == 92:
            chunks.append("\\5C")
        elif 32 <= byte <= 126:
            chunks.append(chr(byte))
        else:
            chunks.append(f"\\{byte:02X}")
    return "".join(chunks)
