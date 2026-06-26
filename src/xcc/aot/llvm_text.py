from dataclasses import dataclass
from typing import NoReturn

from xcc.aot.core_runtime import runtime_prelude
from xcc.aot.diag import AotDiagnostic, AotError
from xcc.aot.ir import (
    IrAssign,
    IrBinary,
    IrBoolType,
    IrBranch,
    IrCall,
    IrConstBool,
    IrConstInt,
    IrConstNone,
    IrConstructRecord,
    IrConstString,
    IrExpr,
    IrForEach,
    IrFunction,
    IrGetField,
    IrIf,
    IrIntType,
    IrModule,
    IrName,
    IrNoneType,
    IrPrint,
    IrRaise,
    IrRecord,
    IrRecordType,
    IrReturn,
    IrStmt,
    IrStringConcat,
    IrStringJoin,
    IrStringType,
    IrTuple,
    IrTupleSlice,
    IrTupleType,
    IrType,
)

_BUILTIN_VALUE_NAMES = {"bool", "int", "object", "str", "tuple"}


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
        self.needs_runtime_prelude = False

    def emit(self) -> str:
        declarations = [self._emit_record(record) for record in self.module.records]
        functions = [self._emit_function(function) for function in self.module.functions]
        main = self._emit_main()
        lines: list[str] = []
        if self.needs_runtime_prelude:
            lines.append(runtime_prelude())
            lines.append("")
        if self.string_constants:
            lines.extend(self.string_constants)
            lines.append("")
        lines.extend(declaration for declaration in declarations if declaration)
        if declarations:
            lines.append("")
        if self.needs_puts and not self.needs_runtime_prelude:
            lines.append("declare i32 @puts(ptr)")
            lines.append("")
        lines.extend(functions)
        if main is not None:
            lines.append(main)
        return "\n".join(lines).rstrip() + "\n"

    def _emit_record(self, record: IrRecord) -> str:
        fields = ", ".join(self._storage_llvm_type(field.type) for field in record.fields)
        return f"%{record.name} = type {{ {fields} }}"

    def _emit_function(self, function: IrFunction) -> str:
        self.index = 0
        params = ", ".join(
            f"{self._param_llvm_type(param.type)} %{param.name}" for param in function.params
        )
        lines = [
            f"define {self._llvm_type(function.return_type)} "
            f"{_llvm_symbol(function.name)}({params}) {{"
        ]
        lines.append("entry:")
        names = {
            param.name: _EmittedValue(f"%{param.name}", param.type) for param in function.params
        }
        for statement in function.body:
            self._emit_statement(statement, names, lines, function.return_type)
        if not _block_is_terminated(lines):
            self._emit_default_return(lines, function.return_type)
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
            _bind_emitted_target(statement.target, value, names)
            return
        if isinstance(statement, IrReturn):
            if isinstance(return_type, IrNoneType):
                lines.append("  ret void")
                return
            value = self._emit_expr(statement.value, names, lines)
            lines.append(f"  ret {self._llvm_type(return_type)} {value.value}")
            return
        if isinstance(statement, IrIf):
            self._emit_if(statement, names, lines, return_type)
            return
        if isinstance(statement, IrForEach):
            self._emit_for_each(statement, names, lines, return_type)
            return
        if isinstance(statement, IrPrint):
            value = self._emit_expr(statement.value, names, lines)
            self.needs_puts = True
            lines.append(f"  {self._tmp('printed')} = call i32 @puts(ptr {value.value})")
            return
        if isinstance(statement, IrRaise):
            value = self._emit_expr(statement.message, names, lines)
            self.needs_puts = True
            lines.append(f"  {self._tmp('raised')} = call i32 @puts(ptr {value.value})")
            self._emit_status_return(lines, return_type)
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
        if isinstance(expr, IrConstBool):
            return _EmittedValue("true" if expr.value else "false", IrBoolType())
        if isinstance(expr, IrConstNone):
            return _EmittedValue("null", IrNoneType())
        if isinstance(expr, IrConstString):
            return _EmittedValue(self._string_constant(expr.value), IrStringType())
        if isinstance(expr, IrName):
            value = names.get(expr.name)
            if value is None:
                if expr.name in _BUILTIN_VALUE_NAMES or expr.name.isupper():
                    return _EmittedValue(self._default_value(expr.type), expr.type)
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
        if isinstance(expr, IrTuple):
            return self._emit_tuple(expr, names, lines)
        if isinstance(expr, IrTupleSlice):
            return self._emit_tuple_slice(expr, names, lines)
        if isinstance(expr, IrStringConcat):
            return self._emit_string_concat(expr, names, lines)
        if isinstance(expr, IrStringJoin):
            return self._emit_string_join(expr, names, lines)
        self._error(f"Unsupported LLVM expression: {type(expr).__name__}")

    def _emit_if(
        self,
        statement: IrIf,
        names: dict[str, _EmittedValue],
        lines: list[str],
        return_type: IrType,
    ) -> None:
        condition = self._emit_expr(statement.condition, names, lines)
        then_label = self._label("if.then")
        else_label = self._label("if.else") if statement.else_branch is not None else None
        end_label = self._label("if.end")
        false_label = else_label or end_label
        lines.append(f"  br i1 {condition.value}, label %{then_label}, label %{false_label}")
        lines.append(f"{then_label}:")
        then_names = dict(names)
        self._emit_branch(statement.then_branch, then_names, lines, return_type)
        if not _block_is_terminated(lines):
            lines.append(f"  br label %{end_label}")
        if statement.else_branch is not None and else_label is not None:
            lines.append(f"{else_label}:")
            else_names = dict(names)
            self._emit_branch(statement.else_branch, else_names, lines, return_type)
            if not _block_is_terminated(lines):
                lines.append(f"  br label %{end_label}")
            names.update(else_names)
        names.update(then_names)
        lines.append(f"{end_label}:")

    def _emit_for_each(
        self,
        statement: IrForEach,
        names: dict[str, _EmittedValue],
        lines: list[str],
        return_type: IrType,
    ) -> None:
        iterable = self._emit_expr(statement.iterable, names, lines)
        self.needs_runtime_prelude = True
        cond_label = self._label("for.cond")
        body_label = self._label("for.body")
        end_label = self._label("for.end")
        current_label = _current_label(lines)
        lines.append(f"  br label %{cond_label}")
        lines.append(f"{cond_label}:")
        index = self._tmp("index")
        lines.append(f"  {index} = phi i64 [ 0, %{current_label} ], [ %next, %{body_label} ]")
        length = self._tmp("len")
        lines.append(f"  {length} = call i64 @__xcc_aot_tuple_len(ptr {iterable.value})")
        condition = self._tmp("forcond")
        lines.append(f"  {condition} = icmp ult i64 {index}, {length}")
        lines.append(f"  br i1 {condition}, label %{body_label}, label %{end_label}")
        lines.append(f"{body_label}:")
        item = self._tmp("item")
        lines.append(f"  {item} = call ptr @__xcc_aot_tuple_get(ptr {iterable.value}, i64 {index})")
        for target in _for_each_targets(statement.target):
            names[target] = _EmittedValue(item, IrRecordType("object"))
        self._emit_branch(statement.body, names, lines, return_type)
        if not _block_is_terminated(lines):
            lines.append(f"  %next = add i64 {index}, 1")
            lines.append(f"  br label %{cond_label}")
        lines.append(f"{end_label}:")

    def _emit_branch(
        self,
        branch: IrBranch,
        names: dict[str, _EmittedValue],
        lines: list[str],
        return_type: IrType,
    ) -> None:
        for child in branch.statements:
            self._emit_statement(child, names, lines, return_type)
            if _block_is_terminated(lines):
                return

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

    def _emit_string_concat(
        self,
        expr: IrStringConcat,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if not expr.parts:
            return _EmittedValue(self._string_constant(""), IrStringType())
        value = self._emit_expr(expr.parts[0], names, lines)
        for part in expr.parts[1:]:
            right = self._emit_expr(part, names, lines)
            result = self._tmp("concat")
            self.needs_runtime_prelude = True
            lines.append(
                f"  {result} = call ptr @__xcc_aot_string_concat2("
                f"ptr {value.value}, ptr {right.value})"
            )
            value = _EmittedValue(result, IrStringType())
        return value

    def _emit_string_join(
        self,
        expr: IrStringJoin,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        separator = self._emit_expr(expr.separator, names, lines)
        values = self._emit_expr(expr.values, names, lines)
        result = self._tmp("join")
        self.needs_runtime_prelude = True
        lines.append(
            f"  {result} = call ptr @__xcc_aot_string_join("
            f"ptr {separator.value}, ptr {values.value})"
        )
        return _EmittedValue(result, IrStringType())

    def _emit_tuple(
        self,
        expr: IrTuple,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        self.needs_runtime_prelude = True
        args = [self._emit_expr(element, names, lines) for element in expr.elements]
        rendered_args = ", ".join(
            [f"i64 {len(args)}"]
            + [f"{self._param_llvm_type(arg.type)} {arg.value}" for arg in args]
        )
        result = self._tmp("tuple")
        lines.append(f"  {result} = call ptr (i64, ...) @__xcc_aot_tuple_pack({rendered_args})")
        return _EmittedValue(result, expr.type)

    def _emit_tuple_slice(
        self,
        expr: IrTupleSlice,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        value = self._emit_expr(expr.value, names, lines)
        start = -1 if expr.start is None else expr.start
        stop = -1 if expr.stop is None else expr.stop
        result = self._tmp("slice")
        self.needs_runtime_prelude = True
        lines.append(
            f"  {result} = call ptr @__xcc_aot_tuple_slice("
            f"ptr {value.value}, i64 {start}, i64 {stop})"
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
            lines.append(
                f"  store {self._storage_llvm_type(field.type)} {value.value}, ptr {field_ptr}"
            )
        return _EmittedValue(result, expr.type)

    def _emit_get_field(
        self,
        expr: IrGetField,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        value = self._emit_expr(expr.value, names, lines)
        record_type = value.type
        if not isinstance(record_type, IrRecordType):
            self._error(f"Unsupported LLVM field receiver: {expr.field}")
        index = self._field_index(record_type.name, expr.field)
        field_ptr = self._tmp("fieldptr")
        result = self._tmp("load")
        lines.append(
            f"  {field_ptr} = getelementptr inbounds %{record_type.name}, ptr {value.value}, "
            f"i32 0, i32 {index}"
        )
        lines.append(f"  {result} = load {self._storage_llvm_type(expr.type)}, ptr {field_ptr}")
        return _EmittedValue(result, expr.type)

    def _emit_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        args = [self._emit_expr(arg, names, lines) for arg in expr.args]
        rendered_args = ", ".join(f"{self._param_llvm_type(arg.type)} {arg.value}" for arg in args)
        target = _llvm_symbol(expr.target)
        if isinstance(expr.type, IrNoneType):
            lines.append(f"  call void {target}({rendered_args})")
            return _EmittedValue("", expr.type)
        result = self._tmp("call")
        lines.append(f"  {result} = call {self._llvm_type(expr.type)} {target}({rendered_args})")
        return _EmittedValue(result, expr.type)

    def _emit_main(self) -> str | None:
        if self.module.entry is None:
            return None
        function = self.functions[self.module.entry]
        return_type = function.return_type
        lines = ["define i32 @main() {", "entry:"]
        result_type = self._llvm_type(return_type)
        if isinstance(return_type, IrNoneType):
            lines.append(f"  call {result_type} {_llvm_symbol(function.name)}()")
            lines.append("  ret i32 0")
        else:
            lines.append(f"  %result = call {result_type} {_llvm_symbol(function.name)}()")
        if isinstance(return_type, IrStringType):
            self.needs_puts = True
            lines.append("  %printed = call i32 @puts(ptr %result)")
            lines.append("  ret i32 0")
        elif isinstance(return_type, IrIntType):
            lines.append(f"  %exit = trunc {result_type} %result to i32")
            lines.append("  ret i32 %exit")
        elif isinstance(return_type, IrBoolType):
            lines.append("  %exit = zext i1 %result to i32")
            lines.append("  ret i32 %exit")
        elif isinstance(return_type, IrNoneType):
            pass
        else:
            self._error(f"Unsupported main return type: {type(return_type).__name__}")
        lines.append("}")
        return "\n".join(lines)

    def _emit_status_return(self, lines: list[str], return_type: IrType) -> None:
        if isinstance(return_type, IrIntType):
            lines.append(f"  ret {self._llvm_type(return_type)} 2")
            return
        if isinstance(return_type, IrBoolType):
            lines.append("  ret i1 false")
            return
        if isinstance(return_type, IrNoneType):
            lines.append("  ret void")
            return
        if isinstance(return_type, (IrRecordType, IrStringType, IrTupleType)):
            lines.append(f"  ret {self._llvm_type(return_type)} null")
            return
        self._error(f"Unsupported raise return type: {type(return_type).__name__}")

    def _emit_default_return(self, lines: list[str], return_type: IrType) -> None:
        if isinstance(return_type, IrNoneType):
            lines.append("  ret void")
            return
        if isinstance(return_type, IrIntType):
            lines.append(f"  ret {self._llvm_type(return_type)} 0")
            return
        if isinstance(return_type, IrBoolType):
            lines.append("  ret i1 false")
            return
        if isinstance(return_type, (IrRecordType, IrStringType, IrTupleType)):
            lines.append(f"  ret {self._llvm_type(return_type)} null")
            return
        self._error(f"Unsupported default return type: {type(return_type).__name__}")

    def _default_value(self, type_info: IrType) -> str:
        if isinstance(type_info, IrBoolType):
            return "false"
        if isinstance(type_info, IrIntType):
            return "0"
        if isinstance(type_info, (IrNoneType, IrRecordType, IrStringType, IrTupleType)):
            return "null"
        self._error(f"Unsupported default value type: {type(type_info).__name__}")

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
        if isinstance(type_info, IrBoolType):
            return "i1"
        if isinstance(type_info, IrStringType):
            return "ptr"
        if isinstance(type_info, IrRecordType):
            return "ptr"
        if isinstance(type_info, IrTupleType):
            return "ptr"
        if isinstance(type_info, IrNoneType):
            return "void"
        self._error(f"Unsupported LLVM type: {type(type_info).__name__}")

    def _storage_llvm_type(self, type_info: IrType) -> str:
        if isinstance(type_info, IrNoneType):
            return "ptr"
        return self._llvm_type(type_info)

    def _param_llvm_type(self, type_info: IrType) -> str:
        if isinstance(type_info, IrRecordType):
            return "ptr"
        if isinstance(type_info, IrNoneType):
            return "ptr"
        return self._llvm_type(type_info)

    def _tmp(self, prefix: str) -> str:
        self.index += 1
        return f"%{prefix}{self.index}"

    def _label(self, prefix: str) -> str:
        self.index += 1
        return f"{prefix}{self.index}"

    def _error(self, message: str) -> NoReturn:
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


def _llvm_symbol(name: str) -> str:
    if name and all(ch.isalnum() or ch in "$._-" for ch in name):
        return f"@{name}"
    escaped = name.replace("\\", "\\5C").replace('"', "\\22")
    return f'@"{escaped}"'


def _block_is_terminated(lines: list[str]) -> bool:
    if not lines:
        return False
    return lines[-1].strip().startswith(("ret ", "br "))


def _current_label(lines: list[str]) -> str:
    for line in reversed(lines):
        if line.endswith(":"):
            return line[:-1]
    return "entry"


def _for_each_targets(target: str) -> tuple[str, ...]:
    stripped = target.strip()
    if stripped.startswith("(") and stripped.endswith(")"):
        stripped = stripped[1:-1]
    names = tuple(
        part.strip() for part in stripped.split(",") if part.strip() and part.strip() != "_"
    )
    return names or (target,)


def _bind_emitted_target(
    target: str,
    value: _EmittedValue,
    names: dict[str, _EmittedValue],
) -> None:
    targets = _for_each_targets(target) if "," in target else (target,)
    for name in targets:
        names[name] = value
