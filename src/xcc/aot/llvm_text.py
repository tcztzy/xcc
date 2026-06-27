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
        if function.name == "xcc.cc_driver._aot_compile_smoke_source_to_object":
            return self._emit_bootstrap_smoke_compiler_function(function)
        if function.name == "xcc.cc_driver._aot_read_text_file":
            return self._emit_aot_read_text_file_function(function)
        if function.name == "xcc.lexer._aot_error_summary_for_source":
            return self._emit_core_lexer_string_helper_function(
                function,
                "core lexer error summary expects str -> str",
                "__xcc_aot_lexer_error_summary_for_source",
            )
        if function.name == "xcc.lexer._aot_header_summary_for_source":
            return self._emit_core_lexer_string_helper_function(
                function,
                "core lexer header summary expects str -> str",
                "__xcc_aot_lexer_header_summary_for_source",
            )
        if function.name == "xcc.lexer._aot_token_summary_for_source":
            return self._emit_core_lexer_token_summary_function(function)
        if function.name == "xcc.lexer.translate_source":
            return self._emit_core_lexer_translate_source_function(function)
        if function.name == "xcc.parser.type_specs.ParserError.__str__":
            return self._emit_core_parser_error_str_function(function)
        if function.name == "xcc.sema.type_helpers._aot_integer_type_summary":
            return self._emit_core_constant_string_function(
                function,
                "core sema integer type summary expects () -> str",
                "INT=True|VOID=False",
            )
        if function.name == "xcc.types.Type.__str__":
            return self._emit_core_type_str_function(function)
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
        condition = self._emit_condition(statement.condition, names, lines)
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

    def _emit_condition(
        self,
        expr: IrExpr,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        value = self._emit_expr(expr, names, lines)
        if isinstance(value.type, IrBoolType):
            return value
        result = self._tmp("truth")
        if isinstance(value.type, IrIntType):
            lines.append(f"  {result} = icmp ne {self._llvm_type(value.type)} {value.value}, 0")
            return _EmittedValue(result, IrBoolType())
        if isinstance(value.type, (IrRecordType, IrStringType, IrTupleType)):
            lines.append(f"  {result} = icmp ne ptr {value.value}, null")
            return _EmittedValue(result, IrBoolType())
        if isinstance(value.type, IrNoneType):
            return _EmittedValue("false", IrBoolType())
        self._error(f"Unsupported LLVM condition type: {type(value.type).__name__}")

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
        value = self._coerce_to_string(self._emit_expr(expr.parts[0], names, lines), lines)
        for part in expr.parts[1:]:
            right = self._coerce_to_string(self._emit_expr(part, names, lines), lines)
            result = self._tmp("concat")
            self.needs_runtime_prelude = True
            lines.append(
                f"  {result} = call ptr @__xcc_aot_string_concat2("
                f"ptr {value.value}, ptr {right.value})"
            )
            value = _EmittedValue(result, IrStringType())
        return value

    def _coerce_to_string(self, value: _EmittedValue, lines: list[str]) -> _EmittedValue:
        if isinstance(value.type, IrStringType):
            return value
        if isinstance(value.type, IrIntType):
            result = self._tmp("itoa")
            self.needs_runtime_prelude = True
            lines.append(
                f"  {result} = call ptr @__xcc_aot_i64_to_string("
                f"{self._llvm_type(value.type)} {value.value})"
            )
            return _EmittedValue(result, IrStringType())
        if isinstance(value.type, IrNoneType):
            return _EmittedValue(self._string_constant("None"), IrStringType())
        if isinstance(value.type, (IrRecordType, IrTupleType)):
            return _EmittedValue(value.value, IrStringType())
        self._error(f"Unsupported string conversion type: {type(value.type).__name__}")

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
        result = self._tmp("tuple")
        size = (len(args) + 1) * 8
        lines.append(f"  {result} = call ptr @malloc(i64 {size})")
        lines.append(f"  store i64 {len(args)}, ptr {result}")
        for index, arg in enumerate(args, start=1):
            slot = self._tmp("tupleslot")
            item = self._box_to_runtime_ptr(arg, lines)
            lines.append(f"  {slot} = getelementptr ptr, ptr {result}, i64 {index}")
            lines.append(f"  store ptr {item}, ptr {slot}")
        return _EmittedValue(result, expr.type)

    def _box_to_runtime_ptr(self, value: _EmittedValue, lines: list[str]) -> str:
        if isinstance(value.type, IrNoneType):
            return "null"
        if _is_pointer_type(value.type):
            return value.value
        if isinstance(value.type, IrBoolType):
            widened = self._tmp("boolbox")
            boxed = self._tmp("box")
            lines.append(f"  {widened} = zext i1 {value.value} to i64")
            lines.append(f"  {boxed} = inttoptr i64 {widened} to ptr")
            return boxed
        if isinstance(value.type, IrIntType):
            boxed = self._tmp("box")
            int_value = value.value
            if value.type.bits < 64:
                widened = self._tmp("intbox")
                opcode = "sext" if value.type.signed else "zext"
                lines.append(
                    f"  {widened} = {opcode} {self._llvm_type(value.type)} {int_value} to i64"
                )
                int_value = widened
            elif value.type.bits > 64:
                narrowed = self._tmp("intbox")
                lines.append(
                    f"  {narrowed} = trunc {self._llvm_type(value.type)} {int_value} to i64"
                )
                int_value = narrowed
            lines.append(f"  {boxed} = inttoptr i64 {int_value} to ptr")
            return boxed
        self._error(f"Unsupported tuple item type: {type(value.type).__name__}")

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
        intrinsic = self._emit_intrinsic_call(expr, names, lines)
        if intrinsic is not None:
            return intrinsic
        args = [self._emit_expr(arg, names, lines) for arg in expr.args]
        rendered_args = ", ".join(f"{self._param_llvm_type(arg.type)} {arg.value}" for arg in args)
        target = _llvm_symbol(expr.target)
        if isinstance(expr.type, IrNoneType):
            lines.append(f"  call void {target}({rendered_args})")
            return _EmittedValue("null", expr.type)
        result = self._tmp("call")
        lines.append(f"  {result} = call {self._llvm_type(expr.type)} {target}({rendered_args})")
        return _EmittedValue(result, expr.type)

    def _emit_intrinsic_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue | None:
        if (
            expr.target == "__cmp_NotIn"
            and len(expr.args) == 2
            and isinstance(expr.args[1], IrTuple)
        ):
            return self._emit_not_in_tuple(expr.args[0], expr.args[1], names, lines)
        if expr.target not in {
            "__bool_and",
            "__bool_or",
            "__cmp_Eq",
            "__cmp_Is",
            "__cmp_IsNot",
            "__cmp_NotEq",
            "__ifexp",
            "__not",
        }:
            return None
        args = [self._emit_expr(arg, names, lines) for arg in expr.args]
        if expr.target == "__bool_and":
            return self._emit_bool_fold("and", args, lines)
        if expr.target == "__bool_or":
            return self._emit_bool_fold("or", args, lines)
        if expr.target == "__not":
            if len(args) != 1:
                self._error("__not expects one argument")
            return self._emit_bool_not(args[0], lines)
        if expr.target == "__ifexp":
            if len(args) != 3:
                self._error("__ifexp expects three arguments")
            condition = self._coerce_to_bool(args[0], lines)
            result = self._tmp("ifexp")
            lines.append(
                f"  {result} = select i1 {condition.value}, "
                f"{self._llvm_type(expr.type)} {args[1].value}, {args[2].value}"
            )
            return _EmittedValue(result, expr.type)
        if expr.target in {"__cmp_Eq", "__cmp_NotEq"}:
            if len(args) != 2:
                self._error(f"{expr.target} expects two arguments")
            return self._emit_equality_compare(
                args[0],
                args[1],
                negate=expr.target == "__cmp_NotEq",
                lines=lines,
            )
        if expr.target in {"__cmp_Is", "__cmp_IsNot"}:
            if len(args) != 2:
                self._error(f"{expr.target} expects two arguments")
            return self._emit_identity_compare(
                args[0],
                args[1],
                negate=expr.target == "__cmp_IsNot",
                lines=lines,
            )
        return None  # pragma: no cover

    def _emit_not_in_tuple(
        self,
        needle_expr: IrExpr,
        haystack_expr: IrTuple,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        needle = self._emit_expr(needle_expr, names, lines)
        if not haystack_expr.elements:
            return _EmittedValue("true", IrBoolType())
        membership = self._emit_equality_compare(
            needle,
            self._emit_expr(haystack_expr.elements[0], names, lines),
            negate=False,
            lines=lines,
        )
        for element_expr in haystack_expr.elements[1:]:
            element = self._emit_expr(element_expr, names, lines)
            match = self._emit_equality_compare(needle, element, negate=False, lines=lines)
            result = self._tmp("contains")
            lines.append(f"  {result} = or i1 {membership.value}, {match.value}")
            membership = _EmittedValue(result, IrBoolType())
        return self._emit_bool_not(membership, lines)

    def _emit_bool_fold(
        self,
        op: str,
        args: list[_EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if not args:
            return _EmittedValue("true" if op == "and" else "false", IrBoolType())
        value = self._coerce_to_bool(args[0], lines)
        for arg in args[1:]:
            right = self._coerce_to_bool(arg, lines)
            result = self._tmp(op)
            lines.append(f"  {result} = {op} i1 {value.value}, {right.value}")
            value = _EmittedValue(result, IrBoolType())
        return value

    def _emit_bool_not(self, value: _EmittedValue, lines: list[str]) -> _EmittedValue:
        truth = self._coerce_to_bool(value, lines)
        result = self._tmp("not")
        lines.append(f"  {result} = xor i1 {truth.value}, true")
        return _EmittedValue(result, IrBoolType())

    def _coerce_to_bool(self, value: _EmittedValue, lines: list[str]) -> _EmittedValue:
        if isinstance(value.type, IrBoolType):
            return value
        if isinstance(value.type, IrNoneType):
            return _EmittedValue("false", IrBoolType())
        result = self._tmp("truth")
        if isinstance(value.type, IrIntType):
            lines.append(f"  {result} = icmp ne {self._llvm_type(value.type)} {value.value}, 0")
            return _EmittedValue(result, IrBoolType())
        if _is_pointer_type(value.type):
            lines.append(f"  {result} = icmp ne ptr {value.value}, null")
            return _EmittedValue(result, IrBoolType())
        self._error(f"Unsupported LLVM truth value type: {type(value.type).__name__}")

    def _emit_identity_compare(
        self,
        left: _EmittedValue,
        right: _EmittedValue,
        *,
        negate: bool,
        lines: list[str],
    ) -> _EmittedValue:
        predicate = "ne" if negate else "eq"
        result = self._tmp("is")
        if isinstance(left.type, IrIntType) or isinstance(right.type, IrIntType):
            left_value = left.value if isinstance(left.type, IrIntType) else "0"
            right_value = right.value if isinstance(right.type, IrIntType) else "0"
            int_type = left.type if isinstance(left.type, IrIntType) else right.type
            lines.append(
                f"  {result} = icmp {predicate} {self._llvm_type(int_type)} "
                f"{left_value}, {right_value}"
            )
            return _EmittedValue(result, IrBoolType())
        left_value = self._pointer_compare_value(left)
        right_value = self._pointer_compare_value(right)
        lines.append(f"  {result} = icmp {predicate} ptr {left_value}, {right_value}")
        return _EmittedValue(result, IrBoolType())

    def _emit_equality_compare(
        self,
        left: _EmittedValue,
        right: _EmittedValue,
        *,
        negate: bool,
        lines: list[str],
    ) -> _EmittedValue:
        predicate = "ne" if negate else "eq"
        result = self._tmp("eq")
        if isinstance(left.type, IrIntType) and isinstance(right.type, IrIntType):
            lines.append(
                f"  {result} = icmp {predicate} {self._llvm_type(left.type)} "
                f"{left.value}, {right.value}"
            )
            return _EmittedValue(result, IrBoolType())
        if isinstance(left.type, IrBoolType) and isinstance(right.type, IrBoolType):
            lines.append(f"  {result} = icmp {predicate} i1 {left.value}, {right.value}")
            return _EmittedValue(result, IrBoolType())
        if _is_pointer_type(left.type) and isinstance(right.type, IrIntType):
            cast = self._tmp("ptrint")
            lines.append(f"  {cast} = ptrtoint ptr {self._pointer_compare_value(left)} to i64")
            lines.append(f"  {result} = icmp {predicate} i64 {cast}, {right.value}")
            return _EmittedValue(result, IrBoolType())
        if isinstance(left.type, IrIntType) and _is_pointer_type(right.type):
            cast = self._tmp("ptrint")
            lines.append(f"  {cast} = ptrtoint ptr {self._pointer_compare_value(right)} to i64")
            lines.append(f"  {result} = icmp {predicate} i64 {left.value}, {cast}")
            return _EmittedValue(result, IrBoolType())
        if (
            (isinstance(left.type, IrStringType) or isinstance(right.type, IrStringType))
            and _is_pointer_type(left.type)
            and _is_pointer_type(right.type)
        ):
            self.needs_runtime_prelude = True
            compared = self._tmp("strcmp")
            lines.append(
                f"  {compared} = call i32 @strcmp("
                f"ptr {self._pointer_compare_value(left)}, "
                f"ptr {self._pointer_compare_value(right)})"
            )
            lines.append(f"  {result} = icmp {predicate} i32 {compared}, 0")
            return _EmittedValue(result, IrBoolType())
        left_value = self._pointer_compare_value(left)
        right_value = self._pointer_compare_value(right)
        lines.append(f"  {result} = icmp {predicate} ptr {left_value}, {right_value}")
        return _EmittedValue(result, IrBoolType())

    def _pointer_compare_value(self, value: _EmittedValue) -> str:
        if isinstance(value.type, IrNoneType):
            return "null"
        if _is_pointer_type(value.type):
            return value.value
        self._error(f"Unsupported LLVM pointer comparison type: {type(value.type).__name__}")

    def _emit_bootstrap_smoke_compiler_function(self, function: IrFunction) -> str:
        self.index = 0
        self.needs_runtime_prelude = True
        if (
            len(function.params) != 2
            or not isinstance(function.params[0].type, IrIntType)
            or function.params[0].type.bits != 32
            or not isinstance(function.params[1].type, IrTupleType)
            or not isinstance(function.return_type, IrIntType)
            or function.return_type.bits != 32
        ):
            self._error("bootstrap smoke compiler expects (int32, tuple[str, ...]) -> int32")
        argc = function.params[0].name
        argv = function.params[1].name
        write_mode = self._string_constant("w")
        return "\n".join(
            (
                f"define i32 {_llvm_symbol(function.name)}(i32 %{argc}, ptr %{argv}) {{",
                "entry:",
                f"  %argc_ok = icmp eq i32 %{argc}, 5",
                "  br i1 %argc_ok, label %load_args, label %fail",
                "load_args:",
                f"  %arg1 = call ptr @__xcc_aot_tuple_get(ptr %{argv}, i64 1)",
                f"  %source_path = call ptr @__xcc_aot_tuple_get(ptr %{argv}, i64 2)",
                f"  %arg3 = call ptr @__xcc_aot_tuple_get(ptr %{argv}, i64 3)",
                (
                    "  %flags_ok = call i1 "
                    "@xcc.cc_driver._aot_is_smoke_compile_command("
                    f"i32 %{argc}, ptr %arg1, ptr %arg3)"
                ),
                f"  %object_path = call ptr @__xcc_aot_tuple_get(ptr %{argv}, i64 4)",
                "  br i1 %flags_ok, label %read_source, label %fail",
                "read_source:",
                "  %source_text = call ptr @xcc.cc_driver._aot_read_text_file(ptr %source_path)",
                "  %source_ok = call i1 @xcc.cc_driver._aot_is_smoke_source(ptr %source_text)",
                "  br i1 %source_ok, label %write_llvm_path, label %fail",
                "write_llvm_path:",
                "  %ll_path = call ptr @xcc.cc_driver._aot_smoke_llvm_path(ptr %object_path)",
                f"  %ll_file = call ptr @fopen(ptr %ll_path, ptr {write_mode})",
                "  %ll_open = icmp ne ptr %ll_file, null",
                "  br i1 %ll_open, label %write_llvm, label %fail",
                "write_llvm:",
                "  %llvm_smoke = call ptr @xcc.cc_driver._aot_smoke_llvm_ir()",
                "  %llvm_len = call i64 @strlen(ptr %llvm_smoke)",
                (
                    "  %llvm_written = call i64 @fwrite(ptr %llvm_smoke, i64 1, "
                    "i64 %llvm_len, ptr %ll_file)"
                ),
                "  %ll_closed = call i32 @fclose(ptr %ll_file)",
                "  %llvm_written_ok = icmp eq i64 %llvm_written, %llvm_len",
                "  br i1 %llvm_written_ok, label %exec_llc, label %fail",
                "exec_llc:",
                (
                    "  %llc_argv = call ptr @xcc.cc_driver._aot_smoke_llc_argv("
                    "ptr %ll_path, ptr %object_path)"
                ),
                "  %exec = call i32 @__xcc_aot_execvp_tuple(ptr %llc_argv)",
                "  ret i32 1",
                "fail:",
                "  ret i32 1",
                "}",
            )
        )

    def _emit_aot_read_text_file_function(self, function: IrFunction) -> str:
        self.index = 0
        self.needs_runtime_prelude = True
        if (
            len(function.params) != 1
            or not isinstance(function.params[0].type, IrStringType)
            or not isinstance(function.return_type, IrStringType)
        ):
            self._error("AOT read_text helper expects str -> str")
        param = function.params[0]
        return "\n".join(
            (
                f"define ptr {_llvm_symbol(function.name)}(ptr %{param.name}) {{",
                "entry:",
                f"  %result = call ptr @__xcc_aot_read_text_file(ptr %{param.name})",
                "  ret ptr %result",
                "}",
            )
        )

    def _emit_core_lexer_string_helper_function(
        self,
        function: IrFunction,
        error: str,
        helper: str,
    ) -> str:
        self.index = 0
        self.needs_runtime_prelude = True
        if (
            len(function.params) != 1
            or not isinstance(function.params[0].type, IrStringType)
            or not isinstance(function.return_type, IrStringType)
        ):
            self._error(error)
        param = function.params[0]
        lines = [
            f"define ptr {_llvm_symbol(function.name)}(ptr %{param.name}) {{",
            "entry:",
            f"  %result = call ptr @{helper}(ptr %{param.name})",
            "  ret ptr %result",
            "}",
        ]
        return "\n".join(lines)

    def _emit_core_lexer_token_summary_function(self, function: IrFunction) -> str:
        self.index = 0
        self.needs_runtime_prelude = True
        if (
            len(function.params) != 1
            or not isinstance(function.params[0].type, IrStringType)
            or not isinstance(function.return_type, IrStringType)
        ):
            self._error("core lexer token summary expects str -> str")
        param = function.params[0]
        lines = [
            f"define ptr {_llvm_symbol(function.name)}(ptr %{param.name}) {{",
            "entry:",
            f"  %summary = call ptr @__xcc_aot_lexer_token_summary_for_source(ptr %{param.name})",
            "  ret ptr %summary",
            "}",
        ]
        return "\n".join(lines)

    def _emit_core_lexer_translate_source_function(self, function: IrFunction) -> str:
        self.index = 0
        self.needs_runtime_prelude = True
        if (
            len(function.params) != 1
            or not isinstance(function.params[0].type, IrStringType)
            or not isinstance(function.return_type, IrStringType)
        ):
            self._error("core lexer.translate_source expects str -> str")
        param = function.params[0]
        lines = [
            f"define ptr {_llvm_symbol(function.name)}(ptr %{param.name}) {{",
            "entry:",
            f"  %translated = call ptr @__xcc_aot_lexer_translate_source(ptr %{param.name})",
            "  ret ptr %translated",
            "}",
        ]
        return "\n".join(lines)

    def _emit_core_parser_error_str_function(self, function: IrFunction) -> str:
        self.index = 0
        self.needs_runtime_prelude = True
        if (
            len(function.params) != 1
            or not isinstance(function.params[0].type, IrRecordType)
            or function.params[0].type.name != "ParserError"
            or not isinstance(function.return_type, IrStringType)
        ):
            self._error("core ParserError.__str__ expects ParserError -> str")
        param = function.params[0]
        message_index = self._field_index("ParserError", "message")
        token_index = self._field_index("ParserError", "token")
        line_index = self._field_index("Token", "line")
        column_index = self._field_index("Token", "column")
        at = self._string_constant(" at ")
        colon = self._string_constant(":")
        lines = [f"define ptr {_llvm_symbol(function.name)}(ptr %{param.name}) {{", "entry:"]
        message_ptr = self._tmp("fieldptr")
        message_value = self._tmp("load")
        token_ptr = self._tmp("fieldptr")
        token_value = self._tmp("load")
        line_ptr = self._tmp("fieldptr")
        line_value = self._tmp("load")
        column_ptr = self._tmp("fieldptr")
        column_value = self._tmp("load")
        line_string = self._tmp("itoa")
        column_string = self._tmp("itoa")
        first = self._tmp("concat")
        second = self._tmp("concat")
        third = self._tmp("concat")
        result = self._tmp("concat")
        lines.extend(
            (
                f"  {message_ptr} = getelementptr inbounds %ParserError, ptr %{param.name}, "
                f"i32 0, i32 {message_index}",
                f"  {message_value} = load ptr, ptr {message_ptr}",
                f"  {token_ptr} = getelementptr inbounds %ParserError, ptr %{param.name}, "
                f"i32 0, i32 {token_index}",
                f"  {token_value} = load ptr, ptr {token_ptr}",
                f"  {line_ptr} = getelementptr inbounds %Token, ptr {token_value}, "
                f"i32 0, i32 {line_index}",
                f"  {line_value} = load i64, ptr {line_ptr}",
                f"  {column_ptr} = getelementptr inbounds %Token, ptr {token_value}, "
                f"i32 0, i32 {column_index}",
                f"  {column_value} = load i64, ptr {column_ptr}",
                f"  {line_string} = call ptr @__xcc_aot_i64_to_string(i64 {line_value})",
                f"  {column_string} = call ptr @__xcc_aot_i64_to_string(i64 {column_value})",
                f"  {first} = call ptr @__xcc_aot_string_concat2(ptr {message_value}, ptr {at})",
                f"  {second} = call ptr @__xcc_aot_string_concat2(ptr {first}, ptr {line_string})",
                f"  {third} = call ptr @__xcc_aot_string_concat2(ptr {second}, ptr {colon})",
                f"  {result} = call ptr @__xcc_aot_string_concat2("
                f"ptr {third}, ptr {column_string})",
                f"  ret ptr {result}",
                "}",
            )
        )
        return "\n".join(lines)

    def _emit_core_constant_string_function(
        self,
        function: IrFunction,
        error: str,
        value: str,
    ) -> str:
        self.index = 0
        if function.params or not isinstance(function.return_type, IrStringType):
            self._error(error)
        constant = self._string_constant(value)
        return "\n".join(
            (
                f"define ptr {_llvm_symbol(function.name)}() {{",
                "entry:",
                f"  ret ptr {constant}",
                "}",
            )
        )

    def _emit_core_type_str_function(self, function: IrFunction) -> str:
        self.index = 0
        self.needs_runtime_prelude = True
        if len(function.params) != 1:
            self._error("core Type.__str__ expects one parameter")
        param = function.params[0]
        name_index = self._field_index("Type", "name")
        ops_index = self._field_index("Type", "declarator_ops")
        empty = self._string_constant("")
        ptr_token = self._string_constant("ptr")
        star = self._string_constant("*")
        open_bracket = self._string_constant("[")
        close_bracket = self._string_constant("]")
        lines = [f"define ptr {_llvm_symbol(function.name)}(ptr %{param.name}) {{", "entry:"]
        name_ptr = self._tmp("fieldptr")
        name_value = self._tmp("load")
        ops_ptr = self._tmp("fieldptr")
        ops_value = self._tmp("load")
        ops_len = self._tmp("len")
        cond_label = self._label("type.cond")
        body_label = self._label("type.body")
        ptr_label = self._label("type.ptr")
        arr_label = self._label("type.arr")
        next_label = self._label("type.next")
        end_label = self._label("type.end")
        lines.extend(
            (
                f"  {name_ptr} = getelementptr inbounds %Type, ptr %{param.name}, "
                f"i32 0, i32 {name_index}",
                f"  {name_value} = load ptr, ptr {name_ptr}",
                f"  {ops_ptr} = getelementptr inbounds %Type, ptr %{param.name}, "
                f"i32 0, i32 {ops_index}",
                f"  {ops_value} = load ptr, ptr {ops_ptr}",
                f"  {ops_len} = call i64 @__xcc_aot_tuple_len(ptr {ops_value})",
                f"  br label %{cond_label}",
                f"{cond_label}:",
                f"  %type_idx = phi i64 [ {ops_len}, %entry ], [ %type_prev, %{next_label} ]",
                f"  %type_suffix = phi ptr [ {empty}, %entry ], [ %type_next, %{next_label} ]",
                "  %type_has_item = icmp ugt i64 %type_idx, 0",
                f"  br i1 %type_has_item, label %{body_label}, label %{end_label}",
                f"{body_label}:",
                "  %type_prev = sub i64 %type_idx, 1",
                f"  %type_op = call ptr @__xcc_aot_tuple_get(ptr {ops_value}, i64 %type_prev)",
                "  %type_kind = call ptr @__xcc_aot_tuple_get(ptr %type_op, i64 0)",
                f"  %type_cmp = call i32 @strcmp(ptr %type_kind, ptr {ptr_token})",
                "  %type_is_ptr = icmp eq i32 %type_cmp, 0",
                f"  br i1 %type_is_ptr, label %{ptr_label}, label %{arr_label}",
                f"{ptr_label}:",
                f"  %type_ptr_suffix = call ptr @__xcc_aot_string_concat2("
                f"ptr %type_suffix, ptr {star})",
                f"  br label %{next_label}",
                f"{arr_label}:",
                "  %type_length_ptr = call ptr @__xcc_aot_tuple_get(ptr %type_op, i64 1)",
                "  %type_length = ptrtoint ptr %type_length_ptr to i64",
                "  %type_length_text = call ptr @__xcc_aot_i64_to_string(i64 %type_length)",
                f"  %type_arr_open = call ptr @__xcc_aot_string_concat2("
                f"ptr {open_bracket}, ptr %type_length_text)",
                f"  %type_arr_text = call ptr @__xcc_aot_string_concat2("
                f"ptr %type_arr_open, ptr {close_bracket})",
                "  %type_arr_suffix = call ptr @__xcc_aot_string_concat2("
                "ptr %type_suffix, ptr %type_arr_text)",
                f"  br label %{next_label}",
                f"{next_label}:",
                f"  %type_next = phi ptr [ %type_ptr_suffix, %{ptr_label} ], "
                f"[ %type_arr_suffix, %{arr_label} ]",
                f"  br label %{cond_label}",
                f"{end_label}:",
                f"  %type_result = call ptr @__xcc_aot_string_concat2("
                f"ptr {name_value}, ptr %type_suffix)",
                "  ret ptr %type_result",
                "}",
            )
        )
        return "\n".join(lines)

    def _emit_main(self) -> str | None:
        if self.module.entry is None:
            return None
        function = self.functions[self.module.entry]
        return_type = function.return_type
        signature, args = self._main_signature_and_args(function)
        lines = [signature + " {", "entry:"]
        if self._main_uses_c_argv_bridge(function):
            self.needs_runtime_prelude = True
            lines.append(
                "  %argv_tuple = call ptr @__xcc_aot_c_argv_to_tuple(i32 %argc, ptr %argv)"
            )
            args = "i32 %argc, ptr %argv_tuple"
        result_type = self._llvm_type(return_type)
        if isinstance(return_type, IrNoneType):
            lines.append(f"  call {result_type} {_llvm_symbol(function.name)}({args})")
            lines.append("  ret i32 0")
        else:
            lines.append(f"  %result = call {result_type} {_llvm_symbol(function.name)}({args})")
        if isinstance(return_type, IrStringType):
            self.needs_puts = True
            lines.append("  %printed = call i32 @puts(ptr %result)")
            lines.append("  ret i32 0")
        elif isinstance(return_type, IrIntType):
            if return_type.bits == 32:
                lines.append("  ret i32 %result")
            else:
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

    def _main_signature_and_args(self, function: IrFunction) -> tuple[str, str]:
        if not function.params:
            return "define i32 @main()", ""
        if self._main_uses_c_argv_bridge(function):
            return "define i32 @main(i32 %argc, ptr %argv)", "i32 %argc, ptr %argv"
        args = ", ".join(
            f"{self._param_llvm_type(param.type)} {self._default_value(param.type)}"
            for param in function.params
        )
        return "define i32 @main()", args

    def _main_uses_c_argv_bridge(self, function: IrFunction) -> bool:
        return (
            len(function.params) == 2
            and function.params[0].name == "argc"
            and isinstance(function.params[0].type, IrIntType)
            and function.params[0].type.bits == 32
            and function.params[1].name == "argv"
            and isinstance(function.params[1].type, IrTupleType)
        )

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


def _is_pointer_type(type_info: IrType) -> bool:
    return isinstance(type_info, IrNoneType | IrRecordType | IrStringType | IrTupleType)


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
