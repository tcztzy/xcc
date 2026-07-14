from collections.abc import Sequence
from typing import Literal, NoReturn

from xcc.aot import py_ast as ast
from xcc.aot.analysis import AotAnalysis, analyze_source
from xcc.aot.diag import AotDiagnostic, AotError, node_location
from xcc.aot.ir import (
    IrAssign,
    IrBinary,
    IrBoolType,
    IrBranch,
    IrBreak,
    IrBytesType,
    IrCall,
    IrConstBool,
    IrConstBytes,
    IrConstFloat,
    IrConstInt,
    IrConstNone,
    IrConstructRecord,
    IrConstString,
    IrContinue,
    IrDictType,
    IrEnumMember,
    IrExceptHandler,
    IrExpr,
    IrField,
    IrFloatType,
    IrForEach,
    IrFunction,
    IrGetField,
    IrIf,
    IrIntType,
    IrModule,
    IrName,
    IrNoneType,
    IrParam,
    IrPrint,
    IrRaise,
    IrRecord,
    IrRecordType,
    IrReraise,
    IrReturn,
    IrSetItem,
    IrSourceSpan,
    IrStmt,
    IrStringConcat,
    IrStringJoin,
    IrStringType,
    IrTry,
    IrTuple,
    IrTupleSlice,
    IrTupleType,
    IrType,
    IrWhile,
)
from xcc.aot.types import AotClassInfo, AotFunctionInfo, AotType, annotation_name

_ALLOWED_BUILTIN_CALLS = {
    "bool",
    "bytes",
    "chr",
    "float",
    "id",
    "isinstance",
    "len",
    "ord",
    "range",
    "reversed",
    "str",
    "sum",
    "super",
    "tuple",
}
_ALLOWED_BUILTIN_VALUES = {"bool", "float", "int", "object", "str", "tuple"}
_ALLOWED_MUTATING_TUPLE_CALLS = {"add", "append", "extend", "pop"}
_STRING_PREDICATE_METHODS = frozenset({"isalpha", "isdigit", "isalnum", "isspace"})
_STRIP_WHITESPACE = " \t\n\r\v\f"
_LLVM_API_RECORD = "LLVMApi"
_LLVM_API_VOID_METHODS = frozenset(
    {
        "AddCase",
        "AddIncoming",
        "PositionBuilderAtEnd",
        "PositionBuilderBefore",
        "SetAlignment",
        "SetInitializer",
        "SetLinkage",
        "SetOrdering",
        "SetTarget",
        "SetValueName2",
    }
)
_LLVM_API_BOOL_METHODS = frozenset({"IsAConstantInt", "IsNull", "IsUndef"})
_LLVM_API_INTEGER_METHODS = frozenset(
    {
        "ConstIntGetSExtValue",
        "ConstIntGetZExtValue",
        "GetArrayLength",
        "GetIntTypeWidth",
        "GetNumOperands",
        "GetTypeKind",
    }
)
_LLVM_API_HANDLE_METHODS = frozenset(
    {
        "AddFunction",
        "AddGlobal",
        "AppendBasicBlock",
        "ArrayType",
        "BuildAdd",
        "BuildAlloca",
        "BuildAnd",
        "BuildArrayAlloca",
        "BuildAShr",
        "BuildAtomicCmpXchg",
        "BuildAtomicRMW",
        "BuildBitCast",
        "BuildBr",
        "BuildCall2",
        "BuildCondBr",
        "BuildExtractValue",
        "BuildFAdd",
        "BuildFCmp",
        "BuildFDiv",
        "BuildFMul",
        "BuildFNeg",
        "BuildFPCast",
        "BuildFPToSI",
        "BuildFSub",
        "BuildFence",
        "BuildGEP2",
        "BuildICmp",
        "BuildIntToPtr",
        "BuildLoad2",
        "BuildLShr",
        "BuildMemCpy",
        "BuildMemSet",
        "BuildMul",
        "BuildNeg",
        "BuildOr",
        "BuildPhi",
        "BuildPtrToInt",
        "BuildRet",
        "BuildRetVoid",
        "BuildSDiv",
        "BuildSExt",
        "BuildSelect",
        "BuildShl",
        "BuildSIToFP",
        "BuildSRem",
        "BuildStore",
        "BuildSub",
        "BuildSwitch",
        "BuildTrunc",
        "BuildUDiv",
        "BuildURem",
        "BuildVAArg",
        "BuildXor",
        "BuildZExt",
        "ConstArray",
        "ConstBitCast",
        "ConstGEP2",
        "ConstInt",
        "ConstIntToPtr",
        "ConstNamedStruct",
        "ConstNull",
        "ConstPointerCast",
        "ConstPointerNull",
        "ConstPtrToInt",
        "ConstReal",
        "ConstString",
        "ConstTrunc",
        "ConstTruncOrBitCast",
        "ContextCreate",
        "CreateBuilder",
        "DoubleType",
        "FloatType",
        "FunctionType",
        "GetAggregateElement",
        "GetBasicBlockTerminator",
        "GetInsertBlock",
        "GetNamedFunction",
        "GetNamedGlobal",
        "GetOperand",
        "GetParam",
        "GetReturnType",
        "GetUndef",
        "Int16Type",
        "Int1Type",
        "Int32Type",
        "Int64Type",
        "Int8Type",
        "ModuleCreateWithName",
        "PointerType",
        "StructType",
        "TypeOf",
        "VoidType",
    }
)


def lower_source_to_ir(
    source: str,
    *,
    filename: str = "<input>",
    entry: str | None = None,
    include_records: set[str] | frozenset[str] | None = None,
    include_functions: set[str] | frozenset[str] | None = None,
    bodyless_functions: set[str] | frozenset[str] | None = None,
    extra_classes: dict[str, AotClassInfo] | None = None,
    extra_functions: dict[str, AotFunctionInfo] | None = None,
    extra_aliases: dict[str, AotType] | None = None,
    extra_global_annotations: dict[str, str] | None = None,
    extra_global_string_constants: dict[str, str] | None = None,
    extra_global_string_container_constants: dict[str, IrTuple] | None = None,
) -> IrModule:
    analysis = analyze_source(
        source,
        filename=filename,
        extra_functions=extra_functions,
    )
    return lower_analysis_to_ir(
        analysis,
        entry=entry,
        include_records=include_records,
        include_functions=include_functions,
        bodyless_functions=bodyless_functions,
        extra_classes=extra_classes,
        extra_functions=extra_functions,
        extra_aliases=extra_aliases,
        extra_global_annotations=extra_global_annotations,
        extra_global_string_constants=extra_global_string_constants,
        extra_global_string_container_constants=extra_global_string_container_constants,
    )


def lower_analysis_to_ir(
    analysis: AotAnalysis,
    *,
    entry: str | None = None,
    include_records: set[str] | frozenset[str] | None = None,
    include_functions: set[str] | frozenset[str] | None = None,
    bodyless_functions: set[str] | frozenset[str] | None = None,
    extra_classes: dict[str, AotClassInfo] | None = None,
    extra_functions: dict[str, AotFunctionInfo] | None = None,
    extra_aliases: dict[str, AotType] | None = None,
    extra_global_annotations: dict[str, str] | None = None,
    extra_global_string_constants: dict[str, str] | None = None,
    extra_global_string_container_constants: dict[str, IrTuple] | None = None,
) -> IrModule:
    filename = analysis.module.filename
    class_types = dict(extra_classes or {})
    class_types.update(analysis.types.classes)
    function_types = dict(extra_functions or {})
    function_types.update(analysis.types.functions)
    aliases = dict(extra_aliases or {})
    aliases.update(analysis.types.aliases)
    local_global_annotations = _collect_global_annotations(analysis.module.tree)
    global_annotations = dict(extra_global_annotations or {})
    global_annotations.update(local_global_annotations)
    global_string_constants = dict(extra_global_string_constants or {})
    global_string_constants.update(_collect_global_string_constants(analysis.module.tree))
    local_global_string_container_constants = _collect_global_string_container_constants(
        analysis.module.tree
    )
    global_string_container_constants = dict(extra_global_string_container_constants or {})
    for name in local_global_annotations:
        if name not in local_global_string_container_constants:
            global_string_container_constants.pop(name, None)
    global_string_container_constants.update(local_global_string_container_constants)
    global_record_constructor_maps = _collect_global_record_constructor_maps(
        analysis.module.tree,
        class_types,
    )
    lowerer = _Lowerer(
        filename,
        class_types,
        function_types,
        aliases,
        _collect_global_names(analysis.module.tree),
        global_annotations,
        global_string_constants,
        global_string_container_constants,
        global_record_constructor_maps,
    )
    records = tuple(
        lowerer.lower_record(node)
        for node in analysis.module.tree.body
        if isinstance(node, ast.ClassDef)
        and (include_records is None or node.name in include_records)
    )
    functions: list[IrFunction] = []
    bodyless = bodyless_functions or frozenset()
    for node in analysis.module.tree.body:
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, ast.FunctionDef):
                    function_name = _lowered_function_name(child.name, node.name)
                    if include_functions is None or function_name in include_functions:
                        functions.append(
                            lowerer.lower_function(
                                child,
                                owner=node.name,
                                bodyless=function_name in bodyless,
                            )
                        )
    for node in analysis.module.tree.body:
        if isinstance(node, ast.FunctionDef):
            function_name = _lowered_function_name(node.name, None)
            if include_functions is None or function_name in include_functions:
                functions.append(
                    lowerer.lower_function(
                        node,
                        owner=None,
                        bodyless=function_name in bodyless,
                    )
                )
    return IrModule(filename, records, tuple(functions), entry=entry)


class _Lowerer:
    def __init__(
        self,
        filename: str,
        class_types: dict[str, AotClassInfo],
        function_types: dict[str, AotFunctionInfo] | None = None,
        aliases: dict[str, AotType] | None = None,
        global_names: set[str] | None = None,
        global_annotations: dict[str, str] | None = None,
        global_string_constants: dict[str, str] | None = None,
        global_string_container_constants: dict[str, IrTuple] | None = None,
        global_record_constructor_maps: dict[str, IrTuple] | None = None,
    ) -> None:
        self.filename = filename
        self.class_types = class_types
        self.function_types = function_types or {}
        self.aliases = aliases or {}
        self.global_names = global_names or set()
        self.global_types = self._global_annotation_types(global_annotations or {})
        self.global_string_constants = global_string_constants or {}
        self.global_string_container_constants = global_string_container_constants or {}
        self.global_record_constructor_maps = global_record_constructor_maps or {}
        self.callable_param_targets: dict[str, str] = {}

    def lower_record(self, node: ast.ClassDef) -> IrRecord:
        class_info = self.class_types[node.name]
        fields = tuple(
            IrField(name, self._aot_type_to_ir_type(field_type))
            for name, field_type in class_info.fields.items()
        )
        return IrRecord(node.name, fields, class_info.bases)

    def _except_handler_target_type(self, exceptions: tuple[str, ...]) -> IrType:
        if len(exceptions) == 1 and exceptions[0] in self.class_types:
            return IrRecordType(exceptions[0])
        return IrRecordType("object")

    def _exception_message(
        self,
        exception: str,
        payload: IrExpr | None,
        argument: IrExpr | None,
    ) -> IrExpr:
        if isinstance(payload, IrConstructRecord):
            str_target = self._record_method_target(payload.type, "__str__")
            if str_target in self.function_types:
                return IrCall(str_target, (payload,), IrStringType())
        if argument is None:
            return IrConstString("")
        if isinstance(argument.type, IrStringType):
            return argument
        if isinstance(argument.type, IrIntType):
            return IrStringConcat((argument,))
        return IrConstString(exception)

    def _global_annotation_types(self, annotations: dict[str, str]) -> dict[str, IrType]:
        global_types: dict[str, IrType] = {}
        for name, annotation in annotations.items():
            try:
                global_types[name] = self._type_name_to_ir_type(annotation, ast.Pass())
            except AotError:
                continue
        return global_types

    def lower_function(
        self,
        node: ast.FunctionDef,
        *,
        owner: str | None,
        bodyless: bool = False,
    ) -> IrFunction:
        function_name = _lowered_function_name(node.name, owner)
        params, names = self._lower_params(node, owner)
        return_type = self._annotation_to_ir_type(node.returns)
        if bodyless or _is_ellipsis_body(node.body):
            return IrFunction(function_name, params, return_type, ())
        previous_callable_param_targets = self.callable_param_targets
        self.callable_param_targets = self._callable_param_default_targets(node)
        try:
            body = tuple(
                self._lower_statement(statement, names, return_type) for statement in node.body
            )
        finally:
            self.callable_param_targets = previous_callable_param_targets
        return IrFunction(function_name, params, return_type, body)

    def _lower_params(
        self,
        node: ast.FunctionDef,
        owner: str | None,
    ) -> tuple[tuple[IrParam, ...], dict[str, IrType]]:
        params: list[IrParam] = []
        names: dict[str, IrType] = {}
        args = node.args.posonlyargs + node.args.args
        for index, arg in enumerate(args):
            if owner is not None and index == 0 and arg.annotation is None:
                ir_type: IrType = IrRecordType(owner)
                params.append(IrParam(arg.arg, ir_type))
                names[arg.arg] = ir_type
                continue
            if arg.annotation is None:
                self._error(
                    "XCC-AOT-LOWER-0001",
                    f"Missing lowered parameter annotation: {node.name}.{arg.arg}",
                    arg,
                )
            ir_type = self._annotation_to_ir_type(arg.annotation)
            params.append(IrParam(arg.arg, ir_type))
            names[arg.arg] = ir_type
        for arg in node.args.kwonlyargs:
            if arg.annotation is None:
                self._error(
                    "XCC-AOT-LOWER-0001",
                    f"Missing lowered parameter annotation: {node.name}.{arg.arg}",
                    arg,
                )
            ir_type = self._annotation_to_ir_type(arg.annotation)
            params.append(IrParam(arg.arg, ir_type))
            names[arg.arg] = ir_type
        return tuple(params), names

    def _callable_param_default_targets(self, node: ast.FunctionDef) -> dict[str, str]:
        targets: dict[str, str] = {}
        args = node.args.posonlyargs + node.args.args
        defaults: tuple[ast.expr | None, ...] = (None,) * (
            len(args) - len(node.args.defaults)
        ) + tuple(node.args.defaults)
        for arg, default in zip(args, defaults, strict=True):
            target = self._callable_param_default_target(arg.annotation, default)
            if target is not None:
                targets[arg.arg] = target
        for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults, strict=True):
            target = self._callable_param_default_target(arg.annotation, default)
            if target is not None:
                targets[arg.arg] = target
        return targets

    def _callable_param_default_target(
        self,
        annotation: ast.expr | None,
        default: ast.expr | None,
    ) -> str | None:
        if (
            annotation is None
            or default is None
            or not isinstance(default, ast.Name)
            or not annotation_name(annotation).startswith("Callable[")
        ):
            return None
        if default.id in self.function_types or default.id in self.global_names:
            return default.id
        qualified_target = self._unique_qualified_function_target(default.id)
        if qualified_target is not None:
            return qualified_target
        return None

    def _lower_statement(
        self,
        statement: ast.stmt,
        names: dict[str, IrType],
        return_type: IrType,
    ) -> IrStmt:
        if isinstance(statement, ast.If):
            condition = self._lower_expr(statement.test, names, IrBoolType())
            then_names = dict(names)
            else_names = dict(names)
            narrowed: tuple[str, IrType] | None = (
                self._isinstance_guard_narrowing(
                    statement.test,
                    names,
                )
                or self._not_none_guard_narrowing(
                    statement.test,
                    names,
                )
                or self._truthy_optional_record_narrowing(statement.test, names)
            )
            if narrowed is not None:
                narrowed_name, narrowed_type = narrowed
                then_names[narrowed_name] = narrowed_type
            then_branch = IrBranch(
                tuple(
                    self._lower_statement(child, then_names, return_type)
                    for child in statement.body
                )
            )
            if narrowed is not None and then_names.get(narrowed_name) == narrowed_type:
                if narrowed_name in names:
                    then_names[narrowed_name] = names[narrowed_name]
                else:
                    then_names.pop(narrowed_name, None)
            else_branch = None
            if statement.orelse:
                else_branch = IrBranch(
                    tuple(
                        self._lower_statement(child, else_names, return_type)
                        for child in statement.orelse
                    )
                )
            if _statements_fall_through(statement.body):
                names.update(then_names)
            if statement.orelse and _statements_fall_through(statement.orelse):
                names.update(else_names)
            for name, narrowed_type in self._none_guard_narrowings(
                statement.test,
                statement.body,
                statement.orelse,
                names,
            ):
                names[name] = narrowed_type
            for name, narrowed_type in self._negative_isinstance_guard_narrowings(
                statement.test,
                statement.body,
                statement.orelse,
                names,
            ):
                names[name] = narrowed_type
            return IrIf(condition, then_branch, else_branch)
        if isinstance(statement, ast.While):
            if statement.orelse:
                self._error(
                    "XCC-AOT-LOWER-0004",
                    "Unsupported control-flow lowering: while else",
                    statement,
                )
            condition = self._lower_expr(statement.test, names, IrBoolType())
            body_names = dict(names)
            body = IrBranch(
                tuple(
                    self._lower_statement(child, body_names, return_type)
                    for child in statement.body
                )
            )
            names.update(body_names)
            return IrWhile(condition, body)
        if isinstance(statement, ast.For):
            iterable = self._lower_expr(statement.iter, names, IrTupleType(()))
            body_names = dict(names)
            target_name = ast.unparse(statement.target)
            unpack_statements: tuple[IrStmt, ...] = ()
            if _for_target_needs_temp_unpack(statement.target):
                item_type = _for_iterable_item_type(iterable)
                target_name = f"__for_item_{statement.lineno}_{statement.col_offset}"
                body_names[target_name] = item_type
                unpack_statements = self._lower_for_target_unpack(
                    statement.target,
                    IrName(target_name, item_type),
                    item_type,
                    body_names,
                )
            else:
                self._bind_for_target(statement.target, iterable, body_names)
            body = IrBranch(
                unpack_statements
                + tuple(
                    self._lower_statement(child, body_names, return_type)
                    for child in statement.body
                )
            )
            names.update(body_names)
            return IrForEach(
                target_name,
                iterable,
                body,
            )
        if isinstance(statement, ast.Try):
            body_names = dict(names)
            body = IrBranch(
                tuple(
                    self._lower_statement(child, body_names, return_type)
                    for child in statement.body
                )
            )
            handler_names: list[dict[str, IrType]] = []
            handlers: list[IrExceptHandler] = []
            for handler in statement.handlers:
                exceptions = _except_handler_names(handler)
                child_names = dict(names)
                if handler.name is not None:
                    child_names[handler.name] = self._except_handler_target_type(exceptions)
                handlers.append(
                    IrExceptHandler(
                        exceptions,
                        handler.name,
                        IrBranch(
                            tuple(
                                self._lower_statement(child, child_names, return_type)
                                for child in handler.body
                            )
                        ),
                    )
                )
                handler_names.append(child_names)
            else_names = dict(body_names)
            orelse = IrBranch(
                tuple(
                    self._lower_statement(child, else_names, return_type)
                    for child in statement.orelse
                )
            )
            final_names = dict(names)
            final_names.update(body_names)
            final_names.update(else_names)
            for child_names in handler_names:
                final_names.update(child_names)
            finalbody = IrBranch(
                tuple(
                    self._lower_statement(child, final_names, return_type)
                    for child in statement.finalbody
                )
            )
            names.update(body_names)
            names.update(else_names)
            for child_names in handler_names:
                names.update(child_names)
            names.update(final_names)
            return IrTry(body, tuple(handlers), orelse, finalbody)
        if isinstance(statement, ast.Raise):
            span = _ir_source_span(statement)
            if statement.exc is None:
                return IrReraise(span)
            if not isinstance(statement.exc, ast.Call):
                self._error(
                    "XCC-AOT-LOWER-0001",
                    "Unsupported lowered statement: Raise",
                    statement,
                )
            exception = ast.unparse(statement.exc.func)
            argument: IrExpr | None = None
            if statement.exc.args:
                argument = self._lower_expr(
                    statement.exc.args[0],
                    names,
                    IrRecordType("object"),
                )
            payload = argument
            raised_type = self._infer_assignment_expr_type(
                statement.exc,
                names,
                IrRecordType("object"),
            )
            if isinstance(statement.exc.func, ast.Name) and exception in self.class_types:
                raised_type = IrRecordType(exception)
            if isinstance(raised_type, IrRecordType) and raised_type.name in self.class_types:
                exception = raised_type.name
                payload = self._lower_expr(statement.exc, names, raised_type)
            message = self._exception_message(exception, payload, argument)
            return IrRaise(exception, message, span, payload)
        if isinstance(statement, ast.Assert):
            condition = self._lower_expr(statement.test, names, IrBoolType())
            for narrowed in self._isinstance_guard_narrowings(statement.test, names):
                name, narrowed_type = narrowed
                names[name] = narrowed_type
            return IrAssign("__assert", IrCall("__assert", (condition,), IrNoneType()))
        if isinstance(statement, ast.Pass):
            return IrAssign("__pass", IrConstNone())
        if isinstance(statement, ast.Expr):
            if (
                isinstance(statement.value, ast.Call)
                and isinstance(statement.value.func, ast.Name)
                and statement.value.func.id == "print"
                and len(statement.value.args) == 1
                and not statement.value.keywords
            ):
                return IrPrint(self._lower_expr(statement.value.args[0], names, IrStringType()))
            mutating_tuple_statement = self._lower_mutating_tuple_expr_statement(
                statement.value,
                names,
            )
            if mutating_tuple_statement is not None:
                return mutating_tuple_statement
            value = self._lower_expr(statement.value, names, return_type)
            return IrAssign("__expr", value)
        if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            annotated_type = self._annotation_to_ir_type(statement.annotation)
            value = (
                self._lower_expr(statement.value, names, annotated_type)
                if statement.value is not None
                else self._default_expr(annotated_type)
            )
            if isinstance(value.type, IrNoneType) and isinstance(annotated_type, IrRecordType):
                names[statement.target.id] = annotated_type
            else:
                names[statement.target.id] = value.type
            return IrAssign(statement.target.id, value)
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Subscript)
        ):
            return self._lower_subscript_assignment(
                statement.targets[0],
                statement.value,
                names,
                return_type,
            )
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], (ast.Name, ast.Attribute, ast.Tuple))
        ):
            target = statement.targets[0]
            value = self._lower_expr(
                statement.value,
                names,
                self._assignment_value_type(target, statement.value, names, return_type),
            )
            self._bind_assignment_target(target, value.type, names)
            return IrAssign(ast.unparse(target), value)
        if (
            isinstance(statement, ast.AugAssign)
            and isinstance(statement.target, (ast.Name, ast.Attribute))
            and isinstance(statement.op, (ast.Add, ast.Sub, ast.Mult))
        ):
            current = self._lower_expr(statement.target, names, return_type)
            value_type: IrType = current.type
            if isinstance(statement.op, ast.Mult) and isinstance(
                current.type, (IrBytesType, IrStringType, IrTupleType)
            ):
                value_type = IrIntType(64, signed=True)
            value = self._lower_expr(statement.value, names, value_type)
            op: Literal["+", "-", "*"]
            if isinstance(statement.op, ast.Add):
                op = "+"
            elif isinstance(statement.op, ast.Sub):
                op = "-"
            else:
                op = "*"
            if op == "+" and isinstance(current.type, IrStringType):
                result: IrExpr = IrStringConcat((current, value))
            elif op == "+" and isinstance(current.type, IrBytesType):
                result = IrCall("__bytes_concat", (current, value), current.type)
            elif op == "+" and isinstance(current.type, IrTupleType):
                result = IrCall("__tuple_concat", (current, value), current.type)
            elif op == "*" and isinstance(current.type, IrStringType):
                result = IrCall("__str_repeat", (current, value), current.type)
            elif op == "*" and isinstance(current.type, IrBytesType):
                result = IrCall("__bytes_repeat", (current, value), current.type)
            elif op == "*" and isinstance(current.type, IrTupleType):
                result = IrCall("__tuple_repeat", (current, value), current.type)
            else:
                result = IrBinary(op, current, value, current.type)
            self._bind_assignment_target(statement.target, result.type, names)
            return IrAssign(ast.unparse(statement.target), result)
        if isinstance(statement, ast.Return):
            if statement.value is None:
                return IrReturn(IrConstNone())
            return IrReturn(self._lower_expr(statement.value, names, return_type))
        if isinstance(statement, ast.Break):
            return IrBreak()
        if isinstance(statement, ast.Continue):
            return IrContinue()
        self._error(
            "XCC-AOT-LOWER-0001",
            f"Unsupported lowered statement: {type(statement).__name__}",
            statement,
        )

    def _lower_mutating_tuple_expr_statement(
        self,
        expr: ast.expr,
        names: dict[str, IrType],
    ) -> IrAssign | None:
        if (
            not isinstance(expr, ast.Call)
            or not isinstance(expr.func, ast.Attribute)
            or not isinstance(expr.func.value, (ast.Name, ast.Attribute))
            or expr.func.attr not in _ALLOWED_MUTATING_TUPLE_CALLS
        ):
            return None
        receiver = self._lower_expr(expr.func.value, names, IrRecordType("object"))
        if not isinstance(receiver.type, IrTupleType):
            return None
        target_name = ast.unparse(expr.func.value)
        value = self._lower_expr(expr, names, receiver.type)
        names[target_name] = value.type
        return IrAssign(target_name, value)

    def _lower_subscript_assignment(
        self,
        target: ast.Subscript,
        value_node: ast.expr,
        names: dict[str, IrType],
        return_type: IrType,
    ) -> IrStmt:
        value_type = self._subscript_item_type(target.value, names, return_type)
        target_value = self._lower_expr(target.value, names, IrRecordType("object"))
        value = self._lower_expr(value_node, names, value_type)
        if isinstance(target_value.type, IrDictType):
            key_type = target_value.type.key
            key = self._lower_expr(target.slice, names, key_type)
            updated = IrCall("__dict_set", (target_value, key, value), target_value.type)
            assignment_target = _assignable_target_name(target.value)
            if assignment_target is not None:
                names[assignment_target] = updated.type
                return IrAssign(assignment_target, updated)
            if isinstance(target.value, ast.Subscript):
                outer_target = target.value
                outer_value = self._lower_expr(outer_target.value, names, IrRecordType("object"))
                outer_index = self._lower_expr(
                    outer_target.slice,
                    names,
                    IrIntType(64, signed=True),
                )
                return IrSetItem(outer_value, outer_index, updated)
        return IrSetItem(
            target_value,
            self._lower_expr(target.slice, names, IrIntType(64, signed=True)),
            value,
        )

    def _lower_type_name_attribute(
        self,
        expr: ast.Attribute,
        names: dict[str, IrType],
    ) -> IrConstString | None:
        if expr.attr != "__name__":
            return None
        if (
            not isinstance(expr.value, ast.Call)
            or not isinstance(expr.value.func, ast.Name)
            or expr.value.func.id != "type"
            or expr.value.keywords
            or len(expr.value.args) != 1
        ):
            return None
        value = self._lower_expr(expr.value.args[0], names, IrRecordType("object"))
        if isinstance(value.type, IrRecordType) and value.type.name != "object":
            return IrConstString(value.type.name)
        return IrConstString("<unknown>")

    def _lower_expr(self, expr: ast.expr, names: dict[str, IrType], expected: IrType) -> IrExpr:
        if isinstance(expr, ast.Constant):
            if isinstance(expr.value, bool):
                return IrConstBool(expr.value)
            if expr.value is None:
                return IrConstNone()
            if isinstance(expr.value, int) and isinstance(expected, IrIntType):
                return IrConstInt(expr.value, expected)
            if isinstance(expr.value, int) and isinstance(expected, IrRecordType):
                return IrConstInt(expr.value, IrIntType(64, signed=True))
            if isinstance(expr.value, str):
                return IrConstString(expr.value)
            if isinstance(expr.value, bytes):
                return IrConstBytes(expr.value)
            if isinstance(expr.value, float):
                return IrConstFloat(expr.value)
        if isinstance(expr, ast.Name):
            string_constant = self.global_string_constants.get(expr.id)
            if string_constant is not None:
                return IrConstString(string_constant)
            string_container = self.global_string_container_constants.get(expr.id)
            if string_container is not None:
                return string_container
            constructor_map = self.global_record_constructor_maps.get(expr.id)
            if constructor_map is not None:
                return constructor_map
            value_type = names.get(expr.id)
            if value_type is None:
                global_type = self.global_types.get(expr.id)
                if global_type is not None:
                    return IrName(expr.id, global_type)
                if (
                    isinstance(expected, IrRecordType)
                    and expected.name == "object"
                    and expr.id in self.function_types
                ):
                    return IrConstNone()
                if expr.id in self.global_names or expr.id in _ALLOWED_BUILTIN_VALUES:
                    return IrName(expr.id, expected)
                self._error("XCC-AOT-LOWER-0002", f"Unknown lowered name: {expr.id}", expr)
            refined_type = self._project_role_record_type(expr.id, value_type)
            if refined_type is not None:
                return IrName(expr.id, refined_type)
            return IrName(expr.id, value_type)
        if isinstance(expr, ast.Attribute):
            type_name = self._lower_type_name_attribute(expr, names)
            if type_name is not None:
                return type_name
            if isinstance(expr.value, ast.Name) and expr.value.id not in names:
                record_name = self._project_record_name(ast.unparse(expr))
                if record_name is not None:
                    return IrName(record_name, IrRecordType("object"))
            if isinstance(expr.value, ast.Name):
                class_info = self.class_types.get(expr.value.id)
                if class_info is not None and _is_enum_class(class_info):
                    return IrEnumMember(expr.value.id, expr.attr)
                if class_info is not None and expr.attr in class_info.int_constants:
                    return IrConstInt(
                        class_info.int_constants[expr.attr],
                        expected if isinstance(expected, IrIntType) else IrIntType(64, signed=True),
                    )
            value = self._lower_expr(expr.value, names, IrRecordType("object"))
            if isinstance(value.type, IrRecordType):
                if expr.attr == "parent" and value.type.name in {"object", "Path", "Path | None"}:
                    return IrCall("__path_parent", (value,), IrRecordType("Path"))
                if expr.attr == "name" and value.type.name in {"object", "Path", "Path | None"}:
                    return IrCall("__path_name", (value,), IrStringType())
                field_type = names.get(ast.unparse(expr))
                if field_type is None:
                    property_call = self._lower_property_getter(value, expr.attr)
                    if property_call is not None:
                        return property_call
                    field_type = self._record_field_type(value.type, expr.attr, expr)
                return IrGetField(value, expr.attr, field_type)
            self._error(
                "XCC-AOT-LOWER-0002",
                f"Unsupported field access: {expr.attr}",
                expr,
            )
        if isinstance(expr, ast.Call):
            return self._lower_call(expr, names, expected)
        if isinstance(expr, ast.JoinedStr):
            return self._lower_joined_str(expr, names)
        if isinstance(expr, ast.Compare):
            return self._lower_compare(expr, names)
        if isinstance(expr, ast.BoolOp):
            return self._lower_bool_op(expr, names, expected)
        if isinstance(expr, ast.UnaryOp) and isinstance(expr.op, ast.Not):
            return IrCall(
                "__not",
                (self._lower_expr(expr.operand, names, IrBoolType()),),
                IrBoolType(),
            )
        if (
            isinstance(expr, ast.UnaryOp)
            and isinstance(expr.op, ast.USub)
            and isinstance(expr.operand, ast.Constant)
            and type(expr.operand.value) is int
            and isinstance(expected, IrIntType)
        ):
            return IrConstInt(-expr.operand.value, expected)
        if isinstance(expr, ast.UnaryOp) and isinstance(expr.op, ast.UAdd):
            return self._lower_expr(expr.operand, names, expected)
        if (
            isinstance(expr, ast.UnaryOp)
            and isinstance(expr.op, ast.USub)
            and isinstance(expected, IrIntType)
        ):
            return IrBinary(
                "-",
                IrConstInt(0, expected),
                self._lower_expr(expr.operand, names, expected),
                expected,
            )
        if (
            isinstance(expr, ast.UnaryOp)
            and isinstance(expr.op, ast.USub)
            and isinstance(expected, IrFloatType)
        ):
            return IrBinary(
                "-",
                IrConstFloat(0.0),
                self._lower_expr(expr.operand, names, expected),
                expected,
            )
        if (
            isinstance(expr, ast.UnaryOp)
            and isinstance(expr.op, ast.Invert)
            and isinstance(expected, IrIntType)
        ):
            return IrBinary(
                "-",
                IrConstInt(-1, expected),
                self._lower_expr(expr.operand, names, expected),
                expected,
            )
        if isinstance(expr, ast.IfExp):
            body_names = dict(names)
            orelse_names = dict(names)
            narrowed = self._isinstance_guard_narrowing(
                expr.test,
                names,
            ) or self._not_none_guard_narrowing(expr.test, names)
            if narrowed is not None:
                name, narrowed_type = narrowed
                body_names[name] = narrowed_type
            else_narrowed = self._is_none_guard_narrowing(expr.test, names)
            if else_narrowed is not None:
                name, narrowed_type = else_narrowed
                orelse_names[name] = narrowed_type
            result_type = expected
            inferred_type = self._infer_assignment_expr_type(
                expr,
                names,
                IrRecordType("object"),
            )
            if not isinstance(inferred_type, IrNoneType) and not _is_object_type(inferred_type):
                result_type = inferred_type
            elif _is_object_type(expected):
                inferred_type = self._infer_assignment_expr_type(expr, body_names, expected)
                if not _is_object_type(inferred_type):
                    result_type = inferred_type
            return IrCall(
                "__ifexp",
                (
                    self._lower_expr(expr.test, names, IrBoolType()),
                    self._lower_expr(expr.body, body_names, result_type),
                    self._lower_expr(expr.orelse, orelse_names, result_type),
                ),
                result_type,
            )
        if isinstance(expr, ast.Tuple):
            if any(isinstance(element, ast.Starred) for element in expr.elts):
                return self._lower_starred_container_literal(expr.elts, names, expected)
            if isinstance(expected, IrTupleType) and not expr.elts:
                return IrTuple((), expected)
            if isinstance(expected, IrTupleType) and len(expected.elements) == len(expr.elts):
                elements = tuple(
                    self._lower_expr(element, names, element_type)
                    for element, element_type in zip(expr.elts, expected.elements, strict=True)
                )
            elif isinstance(expected, IrTupleType) and len(expected.elements) == 1:
                elements = tuple(
                    self._lower_expr(element, names, expected.elements[0]) for element in expr.elts
                )
            else:
                elements = tuple(
                    self._lower_expr(
                        element,
                        names,
                        self._infer_assignment_expr_type(
                            element,
                            names,
                            IrRecordType("object"),
                        ),
                    )
                    for element in expr.elts
                )
            tuple_type = IrTupleType(tuple(element.type for element in elements))
            if isinstance(expected, IrTupleType) and len(expected.elements) == 1:
                tuple_type = expected
            return IrTuple(elements, tuple_type)
        if isinstance(expr, (ast.List, ast.Set)):
            if any(isinstance(element, ast.Starred) for element in expr.elts):
                return self._lower_starred_container_literal(expr.elts, names, expected)
            if isinstance(expected, IrTupleType) and not expr.elts:
                return IrTuple((), expected)
            element_type = _literal_element_expected_type(expected)
            elements = tuple(
                self._lower_expr(element, names, element_type) for element in expr.elts
            )
            return IrTuple(elements, IrTupleType(tuple(element.type for element in elements)))
        if isinstance(expr, ast.Dict):
            if not expr.keys and not expr.values:
                return IrTuple(
                    (),
                    (
                        expected
                        if isinstance(expected, IrDictType)
                        else IrDictType(IrRecordType("object"), IrRecordType("object"))
                    ),
                )
            if not isinstance(expected, IrDictType):
                self._error(
                    "XCC-AOT-LOWER-0002",
                    "Nonempty dict literal requires dict key/value types",
                    expr,
                )
            key_type, value_type = expected.key, expected.value
            pair_type = IrTupleType((key_type, value_type))
            pairs: list[IrExpr] = []
            for key_node, value_node in zip(expr.keys, expr.values, strict=True):
                if key_node is None:
                    self._error(
                        "XCC-AOT-LOWER-0002",
                        "Dict unpacking is outside the native subset",
                        expr,
                    )
                pairs.append(
                    IrTuple(
                        (
                            self._lower_expr(key_node, names, key_type),
                            self._lower_expr(value_node, names, value_type),
                        ),
                        pair_type,
                    )
                )
            return IrTuple(tuple(pairs), expected)
        if isinstance(expr, (ast.ListComp, ast.GeneratorExp)):
            return IrCall(
                f"__{type(expr).__name__}",
                (),
                expected if isinstance(expected, IrTupleType) else IrTupleType(()),
            )
        if isinstance(expr, ast.Subscript):
            narrowed_type = names.get(ast.unparse(expr))
            value = self._lower_expr(expr.value, names, expected)
            if isinstance(expr.slice, ast.Slice):
                if isinstance(value.type, IrStringType | IrBytesType):
                    int64 = IrIntType(64, signed=True)
                    start = (
                        self._lower_expr(expr.slice.lower, names, int64)
                        if expr.slice.lower is not None
                        else IrConstInt(0, int64)
                    )
                    stop = (
                        self._lower_expr(expr.slice.upper, names, int64)
                        if expr.slice.upper is not None
                        else IrCall("len", (value,), int64)
                    )
                    if isinstance(value.type, IrBytesType):
                        return IrCall("__bytes_slice", (value, start, stop), IrBytesType())
                    return IrCall("__str_slice", (value, start, stop), IrStringType())
                return IrTupleSlice(
                    value,
                    _constant_int_or_none(expr.slice.lower),
                    _constant_int_or_none(expr.slice.upper),
                )
            int64 = IrIntType(64, signed=True)
            if isinstance(value.type, IrDictType):
                return IrCall(
                    "__dict_get",
                    (value, self._lower_expr(expr.slice, names, value.type.key)),
                    narrowed_type or value.type.value,
                )
            result_type = narrowed_type or expected
            if isinstance(value.type, IrStringType):
                result_type = IrStringType()
            elif isinstance(value.type, IrBytesType):
                result_type = IrIntType(64, signed=True)
            elif isinstance(value.type, IrTupleType) and narrowed_type is None:
                inferred_type = _tuple_subscript_result_type(expr.slice, value.type)
                if not _is_object_type(inferred_type) or _is_object_type(expected):
                    result_type = inferred_type
            return IrCall(
                "__getitem",
                (value, self._lower_expr(expr.slice, names, int64)),
                result_type,
            )
        if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Div):
            left = self._lower_expr(expr.left, names, IrRecordType("Path"))
            if isinstance(left.type, IrRecordType) and left.type.name == "Path":
                return IrCall(
                    "__path_join",
                    (left, self._lower_expr(expr.right, names, IrStringType())),
                    IrRecordType("Path"),
                )
        if isinstance(expr, ast.BinOp) and isinstance(
            expr.op,
            (
                ast.Add,
                ast.Sub,
                ast.Mult,
                ast.FloorDiv,
                ast.Mod,
                ast.LShift,
                ast.RShift,
                ast.BitOr,
                ast.BitAnd,
                ast.BitXor,
            ),
        ):
            if isinstance(expr.op, ast.Mult) and isinstance(expected, IrBytesType):
                int64 = IrIntType(64, signed=True)
                return IrCall(
                    "__bytes_repeat",
                    (
                        self._lower_expr(expr.left, names, IrBytesType()),
                        self._lower_expr(expr.right, names, int64),
                    ),
                    IrBytesType(),
                )
            if isinstance(expr.op, ast.Mult) and isinstance(expected, IrStringType):
                int64 = IrIntType(64, signed=True)
                return IrCall(
                    "__str_repeat",
                    (
                        self._lower_expr(expr.left, names, IrStringType()),
                        self._lower_expr(expr.right, names, int64),
                    ),
                    IrStringType(),
                )
            if isinstance(expr.op, ast.Mult) and isinstance(expected, IrTupleType):
                int64 = IrIntType(64, signed=True)
                return IrCall(
                    "__tuple_repeat",
                    (
                        self._lower_expr(expr.left, names, expected),
                        self._lower_expr(expr.right, names, int64),
                    ),
                    expected,
                )
            if isinstance(expr.op, ast.Add) and isinstance(expected, IrTupleType):
                return IrCall(
                    "__tuple_concat",
                    (
                        self._lower_expr(expr.left, names, expected),
                        self._lower_expr(expr.right, names, expected),
                    ),
                    expected,
                )
            if isinstance(expr.op, ast.Add) and isinstance(expected, IrStringType):
                return IrStringConcat(
                    (
                        self._lower_expr(expr.left, names, expected),
                        self._lower_expr(expr.right, names, expected),
                    )
                )
            if isinstance(expr.op, ast.Add) and isinstance(expected, IrBytesType):
                return IrCall(
                    "__bytes_concat",
                    (
                        self._lower_expr(expr.left, names, IrBytesType()),
                        self._lower_expr(expr.right, names, IrBytesType()),
                    ),
                    IrBytesType(),
                )
            if isinstance(expected, IrFloatType) and isinstance(
                expr.op,
                (ast.Add, ast.Sub, ast.Mult),
            ):
                float_op: Literal["+", "-", "*"]
                if isinstance(expr.op, ast.Add):
                    float_op = "+"
                elif isinstance(expr.op, ast.Sub):
                    float_op = "-"
                else:
                    float_op = "*"
                return IrBinary(
                    float_op,
                    self._lower_expr(expr.left, names, expected),
                    self._lower_expr(expr.right, names, expected),
                    expected,
                )
            if not isinstance(expected, IrIntType):
                inferred_result_type = self._infer_assignment_expr_type(expr, names, expected)
                if isinstance(inferred_result_type, IrIntType):
                    expected = inferred_result_type
            if isinstance(expr.op, ast.Add):
                left = self._lower_expr(expr.left, names, expected)
                right_expected = left.type if isinstance(left.type, IrTupleType) else expected
                right = self._lower_expr(expr.right, names, right_expected)
                if isinstance(left.type, IrTupleType) and isinstance(right.type, IrTupleType):
                    result_type = left.type if left.type.elements else right.type
                    return IrCall("__tuple_concat", (left, right), result_type)
            if isinstance(expr.op, ast.Add) and not isinstance(expected, IrIntType):
                return IrCall(
                    "__add",
                    (
                        self._lower_expr(expr.left, names, expected),
                        self._lower_expr(expr.right, names, expected),
                    ),
                    expected,
                )
            if isinstance(
                expr.op,
                (
                    ast.FloorDiv,
                    ast.Mod,
                    ast.LShift,
                    ast.RShift,
                    ast.BitOr,
                    ast.BitAnd,
                    ast.BitXor,
                ),
            ) and not isinstance(expected, IrIntType):
                self._error(
                    "XCC-AOT-LOWER-0002",
                    "Integer binary operator requires an integer result type",
                    expr,
                )
            op: Literal["+", "-", "*", "//", "%", "<<", ">>", "|", "&", "^"]
            if isinstance(expr.op, ast.Add):
                op = "+"
            elif isinstance(expr.op, ast.Sub):
                op = "-"
            elif isinstance(expr.op, ast.FloorDiv):
                op = "//"
            elif isinstance(expr.op, ast.Mod):
                op = "%"
            elif isinstance(expr.op, ast.LShift):
                op = "<<"
            elif isinstance(expr.op, ast.RShift):
                op = ">>"
            elif isinstance(expr.op, ast.BitOr):
                op = "|"
            elif isinstance(expr.op, ast.BitAnd):
                op = "&"
            elif isinstance(expr.op, ast.BitXor):
                op = "^"
            else:
                op = "*"
            left = self._lower_expr(expr.left, names, expected)
            right_expected = (
                left.type
                if isinstance(left.type, IrIntType) and not isinstance(expected, IrIntType)
                else expected
            )
            right = self._lower_expr(expr.right, names, right_expected)
            result_type = (
                left.type
                if isinstance(left.type, IrIntType) and isinstance(right.type, IrIntType)
                else expected
            )
            return IrBinary(
                op,
                left,
                right,
                result_type,
            )
        self._error(
            "XCC-AOT-LOWER-0002",
            f"Unsupported lowered expression: {type(expr).__name__}",
            expr,
        )

    def _annotation_to_ir_type(self, annotation: ast.expr | None) -> IrType:
        if annotation is None:
            self._error("XCC-AOT-LOWER-0001", "Missing lowered annotation", ast.Pass())
        name = annotation_name(annotation)
        if (
            isinstance(annotation, ast.Constant)
            and isinstance(annotation.value, str)
            and (name in {"bool", "int", "None", "str"} or _width_alias_to_ir_type(name))
        ):
            self._error(
                "XCC-AOT-LOWER-0002",
                f"Unsupported lowered annotation: {name}",
                annotation,
            )
        return self._type_name_to_ir_type(name, annotation)

    def _type_name_to_ir_type(self, name: str, node: ast.AST) -> IrType:
        alias = self.aliases.get(name)
        if alias is not None:
            return self._aot_type_to_ir_type(alias)
        if name == "bytes":
            return IrBytesType()
        if name == "str":
            return IrStringType()
        if name == "int":
            return IrIntType(64, signed=True)
        if name == "float":
            return IrFloatType()
        if name == "bool":
            return IrBoolType()
        if name == "None":
            return IrNoneType()
        if name == "NoReturn":
            return IrNoneType()
        if name in {"Any", "object"}:
            return IrRecordType("object")
        if name.startswith("Callable["):
            return IrRecordType("object")
        if name == "Enum":
            return IrRecordType("Enum")
        if name == "Path":
            return IrRecordType("Path")
        if name == "FunctionParams":
            return IrTupleType((IrRecordType("object"), IrBoolType()))
        if name in {"DeclaratorOp", "TypeOp"}:
            return IrTupleType((IrStringType(), IrRecordType("object")))
        record_name = self._project_record_name(name)
        if record_name is not None:
            return IrRecordType(record_name)
        width_type = _width_alias_to_ir_type(name)
        if width_type is not None:
            return width_type
        if name.startswith("Literal["):
            return IrStringType()
        if _is_optional_int(name):
            return IrIntType(64, signed=True)
        dict_type = self._dict_ir_type(name, node)
        if dict_type is not None:
            return dict_type
        optional_tuple_type = self._optional_tuple_backed_container_type(name, node)
        if optional_tuple_type is not None:
            return optional_tuple_type
        if _has_top_level_union(name):
            return IrRecordType(name)
        if _is_tuple_backed_container_type(name):
            return IrTupleType(self._tuple_backed_container_types(name, node))
        self._error(
            "XCC-AOT-LOWER-0002",
            f"Unsupported lowered annotation: {name}",
            node,
        )

    def _lower_call(
        self,
        expr: ast.Call,
        names: dict[str, IrType],
        expected: IrType,
    ) -> IrExpr:
        if isinstance(expr.func, ast.Name) and expr.func.id == "llvm":
            return self._lower_llvm_api_constructor(expr)
        if isinstance(expr.func, ast.Name) and expr.func.id == "enumerate":
            return self._lower_enumerate_call(expr, names)
        if isinstance(expr.func, ast.Name) and expr.func.id == "zip":
            return self._lower_zip_call(expr, names)
        if isinstance(expr.func, ast.Name) and expr.func.id == "range":
            return self._lower_range_call(expr, names)
        if isinstance(expr.func, ast.Name) and expr.func.id == "reversed":
            return self._lower_reversed_call(expr, names, expected)
        if isinstance(expr.func, ast.Name) and expr.func.id in {
            "dict",
            "frozenset",
            "list",
            "set",
            "tuple",
        }:
            return self._lower_container_constructor(expr, names, expected)
        if isinstance(expr.func, ast.Name) and expr.func.id == "len" and len(expr.args) == 1:
            return IrCall(
                "len",
                (self._lower_expr(expr.args[0], names, IrTupleType(())),),
                IrIntType(64, signed=True),
            )
        if isinstance(expr.func, ast.Name) and expr.func.id == "int":
            return self._lower_int_call(expr, names)
        if isinstance(expr.func, ast.Name) and expr.func.id == "bytes":
            return self._lower_bytes_call(expr, names)
        if isinstance(expr.func, ast.Name) and expr.func.id == "id":
            return self._lower_id_call(expr, names)
        if isinstance(expr.func, ast.Name) and expr.func.id == "chr":
            return self._lower_chr_call(expr, names)
        if isinstance(expr.func, ast.Name) and expr.func.id == "ord":
            return self._lower_ord_call(expr, names)
        if isinstance(expr.func, ast.Name) and expr.func.id == "float":
            return self._lower_float_call(expr, names)
        if isinstance(expr.func, ast.Name) and expr.func.id == "Path":
            return self._lower_path_constructor_call(expr, names)
        if isinstance(expr.func, ast.Name) and expr.func.id == "str":
            path_string = self._lower_path_str_call(expr, names)
            if path_string is not None:
                return path_string
        if isinstance(expr.func, ast.Name) and expr.func.id == "cast":
            return self._lower_cast_call(expr, names, expected)
        if isinstance(expr.func, ast.Name) and expr.func.id in {"min", "max"}:
            return self._lower_minmax_call(expr, names, expected)
        if isinstance(expr.func, ast.Name) and expr.func.id in self.class_types:
            record_name = expr.func.id
            record_type = IrRecordType(record_name)
            args = self._lower_constructor_args(record_name, expr, names)
            return IrConstructRecord(record_name, args, record_type)
        if isinstance(expr.func, ast.Name):
            callable_type = names.get(expr.func.id)
            constructor_base = _record_constructor_type_base(callable_type)
            if constructor_base is not None:
                if expr.args or expr.keywords:
                    self._error(
                        "XCC-AOT-LOWER-0003",
                        f"Dynamic record constructor requires zero arguments: {expr.func.id}",
                        expr,
                    )
                return IrCall(
                    "__record_construct0",
                    (IrName(expr.func.id, callable_type),),
                    IrRecordType(constructor_base),
                )
            callable_target = self.callable_param_targets.get(expr.func.id)
            if callable_target is not None:
                return_type = self._function_return_type(callable_target, expected)
                return IrCall(
                    callable_target,
                    self._lower_call_args_for_signature(
                        expr,
                        names,
                        callable_target,
                        0,
                        expected,
                    ),
                    return_type,
                )
            if expr.func.id not in self.global_names and expr.func.id not in _ALLOWED_BUILTIN_CALLS:
                self._error(
                    "XCC-AOT-LOWER-0003",
                    f"Unsupported call target: {ast.unparse(expr.func)}",
                    expr,
                )
            return_type = self._function_return_type(expr.func.id, expected)
            return IrCall(
                expr.func.id,
                self._lower_call_args_for_signature(expr, names, expr.func.id, 0, expected),
                return_type,
            )
        if isinstance(expr.func, ast.Attribute):
            target = ast.unparse(expr.func)
            if isinstance(expr.func.value, ast.Name) and expr.func.value.id not in names:
                record_name = self._project_record_name(target)
                if record_name is not None:
                    record_type = IrRecordType(record_name)
                    args = self._lower_constructor_args(record_name, expr, names)
                    return IrConstructRecord(record_name, args, record_type)
            if target in self.function_types:
                return_type = self._function_return_type(target, expected)
                return IrCall(
                    target,
                    self._lower_call_args_for_signature(expr, names, target, 0, expected),
                    return_type,
                )
        if isinstance(expr.func, ast.Attribute) and _is_string_join_call(expr.func):
            receiver = self._lower_string_receiver(expr.func.value, names)
            values = (
                self._lower_expr(expr.args[0], names, IrTupleType(()))
                if expr.args
                else IrTuple((), IrTupleType(()))
            )
            return IrStringJoin(receiver, values)
        if _is_float_fromhex_call(expr):
            return self._lower_float_fromhex_call(expr, names)
        if _is_object_setattr_call(expr):
            value = (
                self._lower_expr(expr.args[2], names, expected)
                if len(expr.args) >= 3
                else IrConstNone()
            )
            return IrCall("object.__setattr__", (value,), value.type)
        if isinstance(expr.func, ast.Attribute) and expr.func.attr == "startswith":
            receiver = self._lower_string_receiver(expr.func.value, names)
            if isinstance(receiver.type, IrStringType):
                return self._lower_string_startswith_call(expr, receiver, names)
        if isinstance(expr.func, ast.Attribute) and expr.func.attr == "endswith":
            receiver = self._lower_string_receiver(expr.func.value, names)
            if isinstance(receiver.type, IrStringType):
                return self._lower_string_endswith_call(expr, receiver, names)
        if isinstance(expr.func, ast.Attribute) and expr.func.attr == "ljust":
            receiver = self._lower_expr(expr.func.value, names, IrRecordType("object"))
            if isinstance(receiver.type, IrBytesType):
                return self._lower_bytes_ljust_call(expr, receiver, names)
            receiver = self._lower_string_receiver(expr.func.value, names)
            if isinstance(receiver.type, IrStringType):
                return self._lower_string_ljust_call(expr, receiver, names)
        if isinstance(expr.func, ast.Attribute) and expr.func.attr in {"lstrip", "rstrip", "strip"}:
            receiver = self._lower_string_receiver(expr.func.value, names)
            if isinstance(receiver.type, IrStringType):
                return self._lower_string_strip_call(expr, receiver, names)
        if isinstance(expr.func, ast.Attribute) and expr.func.attr == "to_bytes":
            int64 = IrIntType(64, signed=True)
            receiver = self._lower_expr(expr.func.value, names, int64)
            if isinstance(receiver.type, IrIntType):
                return self._lower_int_to_bytes_call(expr, receiver, names)
        if isinstance(expr.func, ast.Attribute) and expr.func.attr == "split":
            receiver = self._lower_string_receiver(expr.func.value, names)
            if isinstance(receiver.type, IrStringType):
                return self._lower_string_split_call(expr, receiver, names)
        if isinstance(expr.func, ast.Attribute) and expr.func.attr == "splitlines":
            receiver = self._lower_string_receiver(expr.func.value, names)
            if isinstance(receiver.type, IrStringType):
                return self._lower_string_splitlines_call(expr, receiver, names)
        if isinstance(expr.func, ast.Attribute) and expr.func.attr == "replace":
            receiver = self._lower_string_receiver(expr.func.value, names)
            if isinstance(receiver.type, IrStringType):
                return self._lower_string_replace_call(expr, receiver, names)
        if isinstance(expr.func, ast.Attribute) and expr.func.attr in {
            "removeprefix",
            "removesuffix",
        }:
            receiver = self._lower_string_receiver(expr.func.value, names)
            if isinstance(receiver.type, IrStringType):
                return self._lower_string_remove_affix_call(expr, receiver, names)
        if isinstance(expr.func, ast.Attribute) and expr.func.attr == "lower":
            receiver = self._lower_string_receiver(expr.func.value, names)
            if isinstance(receiver.type, IrStringType):
                return self._lower_string_lower_call(expr, receiver)
        if isinstance(expr.func, ast.Attribute) and expr.func.attr == "resolve":
            receiver = self._lower_expr(expr.func.value, names, IrRecordType("Path"))
            if isinstance(receiver.type, IrRecordType) and receiver.type.name in {
                "object",
                "Path",
                "Path | None",
            }:
                return self._lower_path_resolve_call(expr, receiver)
        if isinstance(expr.func, ast.Attribute) and expr.func.attr == "read_text":
            receiver = self._lower_expr(expr.func.value, names, IrRecordType("Path"))
            if isinstance(receiver.type, IrRecordType) and receiver.type.name in {
                "object",
                "Path",
                "Path | None",
            }:
                return self._lower_path_read_text_call(expr, receiver)
        if isinstance(expr.func, ast.Attribute) and expr.func.attr == "is_file":
            receiver = self._lower_expr(expr.func.value, names, IrRecordType("Path"))
            if isinstance(receiver.type, IrRecordType) and receiver.type.name in {
                "object",
                "Path",
                "Path | None",
            }:
                return self._lower_path_is_file_call(expr, receiver)
        if isinstance(expr.func, ast.Attribute) and expr.func.attr == "find":
            receiver = self._lower_string_receiver(expr.func.value, names)
            if isinstance(receiver.type, IrStringType):
                return self._lower_string_find_call(expr, receiver, names)
        if isinstance(expr.func, ast.Attribute) and expr.func.attr == "setdefault":
            receiver = self._lower_expr(
                expr.func.value,
                names,
                IrDictType(IrRecordType("object"), IrRecordType("object")),
            )
            if isinstance(receiver.type, IrDictType):
                return self._lower_dict_setdefault_call(expr, receiver, names)
        if isinstance(expr.func, ast.Attribute) and expr.func.attr == "encode":
            receiver = self._lower_string_receiver(expr.func.value, names)
            if isinstance(receiver.type, IrStringType):
                return self._lower_string_encode_call(expr, receiver, names)
        if isinstance(expr.func, ast.Attribute) and expr.func.attr in _STRING_PREDICATE_METHODS:
            receiver = self._lower_string_receiver(expr.func.value, names)
            if isinstance(receiver.type, IrStringType):
                return self._lower_string_predicate_call(expr, expr.func.attr, receiver)
        if isinstance(expr.func, ast.Attribute):
            receiver = self._lower_expr(expr.func.value, names, expected)
            receiver_type = receiver.type
            if isinstance(receiver_type, IrRecordType) and receiver_type.name == _LLVM_API_RECORD:
                return self._lower_llvm_api_call(expr, names, expected)
            if isinstance(receiver_type, IrRecordType):
                target = self._record_method_target(receiver_type, expr.func.attr)
                skip_parameters = 1
                receiver_args: tuple[IrExpr, ...] = (receiver,)
                function_info = self.function_types.get(target)
                if function_info is not None and (
                    not function_info.parameters
                    or function_info.parameters[0][0] not in {"self", "cls"}
                ):
                    skip_parameters = 0
                    receiver_args = ()
                return_type = self._function_return_type(target, expected)
                args = receiver_args + tuple(
                    self._lower_call_args_for_signature(
                        expr,
                        names,
                        target,
                        skip_parameters,
                        expected,
                    )
                )
                return IrCall(target, args, return_type)
            if isinstance(receiver_type, IrDictType) and expr.func.attr == "get":
                return self._lower_dict_get_call(expr, receiver, names)
            if isinstance(receiver_type, IrDictType) and expr.func.attr == "items":
                return self._lower_dict_items_call(expr, receiver)
            if (
                isinstance(receiver_type, IrTupleType)
                and expr.func.attr in _ALLOWED_MUTATING_TUPLE_CALLS
            ):
                arg_expected = expected
                if expr.func.attr in {"add", "append"}:
                    arg_expected = _literal_element_expected_type(receiver_type)
                elif expr.func.attr == "extend":
                    arg_expected = receiver_type
                return IrCall(
                    ast.unparse(expr.func),
                    (receiver,) + self._lower_call_args(expr, names, arg_expected),
                    expected,
                )
            if expr.func.attr == "__init__" and _is_super_call(expr.func.value):
                return IrCall(
                    ast.unparse(expr.func),
                    (receiver,) + self._lower_call_args(expr, names, expected),
                    expected,
                )
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        self._error(
            "XCC-AOT-LOWER-0003",
            f"Unsupported call target: {ast.unparse(expr.func)}",
            expr,
        )

    def _lower_int_call(
        self,
        expr: ast.Call,
        names: dict[str, IrType],
    ) -> IrExpr:
        int64 = IrIntType(64, signed=True)
        if not expr.keywords and len(expr.args) == 1:
            return IrCall(
                "__ifexp",
                (
                    self._lower_expr(expr.args[0], names, IrBoolType()),
                    IrConstInt(1, int64),
                    IrConstInt(0, int64),
                ),
                int64,
            )
        if expr.keywords or len(expr.args) != 2:
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        return IrCall(
            "__int_parse",
            (
                self._lower_expr(expr.args[0], names, IrStringType()),
                self._lower_expr(expr.args[1], names, int64),
            ),
            int64,
        )

    def _lower_chr_call(self, expr: ast.Call, names: dict[str, IrType]) -> IrExpr:
        if expr.keywords or len(expr.args) != 1:
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        return IrCall(
            "__chr",
            (self._lower_expr(expr.args[0], names, IrIntType(64, signed=True)),),
            IrStringType(),
        )

    def _lower_ord_call(self, expr: ast.Call, names: dict[str, IrType]) -> IrExpr:
        if expr.keywords or len(expr.args) != 1:
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        value = self._lower_expr(expr.args[0], names, IrStringType())
        if isinstance(value.type, IrIntType):
            return value
        return IrCall(
            "__ord",
            (value,),
            IrIntType(64, signed=True),
        )

    def _lower_cast_call(
        self,
        expr: ast.Call,
        names: dict[str, IrType],
        expected: IrType,
    ) -> IrExpr:
        if expr.keywords or len(expr.args) != 2:
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        try:
            cast_name = annotation_name(expr.args[0])
            cast_type = self._type_name_to_ir_type(cast_name, expr.args[0])
        except AotError:
            cast_name = ""
            cast_type = expected
        if cast_name in {"Any", "object"}:
            refined_value = self._refined_any_cast_value(expr.args[1], names)
            if refined_value is not None:
                return refined_value
        value = self._lower_expr(expr.args[1], names, cast_type)
        if not _is_object_type(cast_type) and value.type != cast_type and isinstance(value, IrName):
            return IrName(value.name, cast_type)
        return value

    def _refined_any_cast_value(
        self,
        expr: ast.expr,
        names: dict[str, IrType],
    ) -> IrExpr | None:
        if not isinstance(expr, ast.Name):
            return None
        if expr.id not in names and expr.id not in self.global_names:
            return None
        existing_type = names.get(expr.id) or self.global_types.get(expr.id)
        if isinstance(existing_type, IrRecordType) and existing_type.name != "object":
            return IrName(expr.id, existing_type)
        refined_type = self._project_role_record_type(expr.id, existing_type)
        if refined_type is not None:
            return IrName(expr.id, refined_type)
        return None

    def _project_role_record_type(
        self,
        name: str,
        current_type: IrType | None,
    ) -> IrRecordType | None:
        if not _is_object_type(current_type or IrRecordType("object")):
            return None
        class_name = name[:1].upper() + name[1:]
        if class_name in self.class_types:
            return IrRecordType(class_name)
        return None

    def _lower_bytes_call(self, expr: ast.Call, names: dict[str, IrType]) -> IrExpr:
        if expr.keywords or len(expr.args) != 1:
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        return IrCall(
            "__bytes",
            (self._lower_expr(expr.args[0], names, IrIntType(64, signed=True)),),
            IrBytesType(),
        )

    def _lower_int_to_bytes_call(
        self,
        expr: ast.Call,
        receiver: IrExpr,
        names: dict[str, IrType],
    ) -> IrExpr:
        signed_keywords = tuple(keyword for keyword in expr.keywords if keyword.arg == "signed")
        unsupported_keywords = tuple(
            keyword for keyword in expr.keywords if keyword.arg != "signed"
        )
        signed_false = not signed_keywords or (
            len(signed_keywords) == 1
            and isinstance(signed_keywords[0].value, ast.Constant)
            and signed_keywords[0].value.value is False
        )
        if unsupported_keywords or not signed_false or len(expr.args) != 2:
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        int64 = IrIntType(64, signed=True)
        return IrCall(
            "__int_to_bytes",
            (
                receiver,
                self._lower_expr(expr.args[0], names, int64),
                self._lower_expr(expr.args[1], names, IrStringType()),
            ),
            IrBytesType(),
        )

    def _lower_id_call(self, expr: ast.Call, names: dict[str, IrType]) -> IrExpr:
        if expr.keywords or len(expr.args) != 1:
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        return IrCall(
            "__id",
            (self._lower_expr(expr.args[0], names, IrRecordType("object")),),
            IrIntType(64, signed=True),
        )

    def _lower_float_call(self, expr: ast.Call, names: dict[str, IrType]) -> IrExpr:
        if expr.keywords or len(expr.args) != 1:
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        return IrCall(
            "__float",
            (self._lower_expr(expr.args[0], names, IrRecordType("object")),),
            IrFloatType(),
        )

    def _lower_float_fromhex_call(self, expr: ast.Call, names: dict[str, IrType]) -> IrExpr:
        if expr.keywords or len(expr.args) != 1:
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        return IrCall(
            "__float_fromhex",
            (self._lower_expr(expr.args[0], names, IrStringType()),),
            IrFloatType(),
        )

    def _lower_path_constructor_call(self, expr: ast.Call, names: dict[str, IrType]) -> IrExpr:
        if expr.keywords or len(expr.args) != 1:
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        return IrCall(
            "__path_from_string",
            (self._lower_expr(expr.args[0], names, IrStringType()),),
            IrRecordType("Path"),
        )

    def _lower_path_resolve_call(self, expr: ast.Call, receiver: IrExpr) -> IrExpr:
        if expr.keywords or expr.args:
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        return IrCall("__path_resolve", (receiver,), IrRecordType("Path"))

    def _lower_path_str_call(
        self,
        expr: ast.Call,
        names: dict[str, IrType],
    ) -> IrExpr | None:
        if expr.keywords or len(expr.args) != 1:
            return None
        value = self._lower_expr(expr.args[0], names, IrRecordType("object"))
        if isinstance(value.type, IrIntType):
            return IrStringConcat((value,))
        if isinstance(value.type, IrStringType):
            return value
        if isinstance(value.type, IrRecordType):
            str_target = self._record_method_target(value.type, "__str__")
            function_info = self.function_types.get(str_target)
            if function_info is not None:
                return_type = self._function_return_type(str_target, IrRecordType("object"))
                if isinstance(return_type, IrStringType):
                    return IrCall(str_target, (value,), return_type)
        if isinstance(value.type, IrRecordType) and value.type.name in {
            "object",
            "Path",
            "Path | None",
            "str | None",
        }:
            return IrCall("__path_to_string", (value,), IrStringType())
        return None

    def _lower_string_receiver(self, expr: ast.expr, names: dict[str, IrType]) -> IrExpr:
        receiver = self._lower_expr(expr, names, IrStringType())
        if isinstance(receiver.type, IrRecordType) and receiver.type.name == "str | None":
            return IrCall("__path_to_string", (receiver,), IrStringType())
        return receiver

    def _lower_path_read_text_call(self, expr: ast.Call, receiver: IrExpr) -> IrExpr:
        if expr.args:
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        for keyword in expr.keywords:
            if keyword.arg not in {"encoding", "errors"}:
                self._error(
                    "XCC-AOT-LOWER-0003",
                    f"Unsupported call target: {ast.unparse(expr.func)}",
                    expr,
                )
        return IrCall("__path_read_text", (receiver,), IrStringType())

    def _lower_path_is_file_call(self, expr: ast.Call, receiver: IrExpr) -> IrExpr:
        if expr.args or expr.keywords:
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        return IrCall("__path_is_file", (receiver,), IrBoolType())

    def _lower_range_call(self, expr: ast.Call, names: dict[str, IrType]) -> IrExpr:
        if expr.keywords or len(expr.args) not in {1, 2, 3}:
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        int64 = IrIntType(64, signed=True)
        return IrCall(
            "range",
            tuple(self._lower_expr(arg, names, int64) for arg in expr.args),
            IrTupleType((int64,)),
        )

    def _lower_starred_container_literal(
        self,
        elements: Sequence[ast.expr],
        names: dict[str, IrType],
        expected: IrType,
    ) -> IrExpr:
        result_type = expected if isinstance(expected, IrTupleType) else IrTupleType(())
        element_type = _literal_element_expected_type(result_type)
        parts: list[IrExpr] = []
        pending: list[IrExpr] = []
        for element in elements:
            if isinstance(element, ast.Starred):
                if pending:
                    parts.append(
                        IrTuple(
                            tuple(pending),
                            IrTupleType(tuple(item.type for item in pending)),
                        )
                    )
                    pending = []
                value = self._lower_expr(element.value, names, result_type)
                if not isinstance(value.type, IrTupleType):
                    self._error(
                        "XCC-AOT-LOWER-0002",
                        "Starred container literal expects tuple-backed values",
                        element,
                    )
                parts.append(value)
            else:
                pending.append(self._lower_expr(element, names, element_type))
        if pending:
            parts.append(IrTuple(tuple(pending), IrTupleType(tuple(item.type for item in pending))))
        if not parts:
            return IrTuple((), result_type)
        result = parts[0]
        for part in parts[1:]:
            result = IrCall("__tuple_concat", (result, part), result_type)
        return result

    def _lower_reversed_call(
        self,
        expr: ast.Call,
        names: dict[str, IrType],
        expected: IrType,
    ) -> IrExpr:
        if expr.keywords or len(expr.args) != 1:
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        value = self._lower_expr(
            expr.args[0],
            names,
            expected if isinstance(expected, IrTupleType) else IrTupleType(()),
        )
        if not isinstance(value.type, IrTupleType):
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        return IrCall("reversed", (value,), value.type)

    def _lower_container_constructor(
        self,
        expr: ast.Call,
        names: dict[str, IrType],
        expected: IrType,
    ) -> IrExpr:
        if (
            isinstance(expr.func, ast.Name)
            and expr.func.id in {"dict", "frozenset", "list", "set", "tuple"}
            and not expr.keywords
            and len(expr.args) == 1
        ):
            return self._lower_expr(expr.args[0], names, expected)
        if expr.args or expr.keywords:
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        result_type = (
            expected if isinstance(expected, IrTupleType | IrDictType) else IrTupleType(())
        )
        return IrTuple((), result_type)

    def _lower_minmax_call(
        self,
        expr: ast.Call,
        names: dict[str, IrType],
        expected: IrType,
    ) -> IrExpr:
        if (
            not isinstance(expr.func, ast.Name)
            or expr.keywords
            or len(expr.args) != 2
            or not isinstance(expected, IrIntType | IrRecordType)
        ):
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        result_type = expected if isinstance(expected, IrIntType) else IrIntType(64, signed=True)
        left = self._lower_expr(expr.args[0], names, result_type)
        right = self._lower_expr(expr.args[1], names, result_type)
        if not isinstance(left.type, IrIntType) or not isinstance(right.type, IrIntType):
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        compare_target = "__cmp_GtE" if expr.func.id == "max" else "__cmp_LtE"
        return IrCall(
            "__ifexp",
            (IrCall(compare_target, (left, right), IrBoolType()), left, right),
            left.type,
        )

    def _lower_string_startswith_call(
        self,
        expr: ast.Call,
        receiver: IrExpr,
        names: dict[str, IrType],
    ) -> IrExpr:
        if expr.keywords or len(expr.args) not in {1, 2}:
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        int64 = IrIntType(64, signed=True)
        start = (
            self._lower_expr(expr.args[1], names, int64)
            if len(expr.args) == 2
            else IrConstInt(0, int64)
        )
        return IrCall(
            "__str_startswith",
            (
                receiver,
                self._lower_expr(expr.args[0], names, IrStringType()),
                start,
            ),
            IrBoolType(),
        )

    def _lower_string_endswith_call(
        self,
        expr: ast.Call,
        receiver: IrExpr,
        names: dict[str, IrType],
    ) -> IrExpr:
        if expr.keywords or len(expr.args) != 1:
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        return IrCall(
            "__str_endswith",
            (receiver, self._lower_expr(expr.args[0], names, IrStringType())),
            IrBoolType(),
        )

    def _lower_string_ljust_call(
        self,
        expr: ast.Call,
        receiver: IrExpr,
        names: dict[str, IrType],
    ) -> IrExpr:
        if expr.keywords or len(expr.args) not in {1, 2}:
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        int64 = IrIntType(64, signed=True)
        fill = (
            self._lower_expr(expr.args[1], names, IrStringType())
            if len(expr.args) == 2
            else IrConstString(" ")
        )
        return IrCall(
            "__str_ljust",
            (receiver, self._lower_expr(expr.args[0], names, int64), fill),
            IrStringType(),
        )

    def _lower_bytes_ljust_call(
        self,
        expr: ast.Call,
        receiver: IrExpr,
        names: dict[str, IrType],
    ) -> IrExpr:
        if expr.keywords or len(expr.args) not in {1, 2}:
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        int64 = IrIntType(64, signed=True)
        fill = (
            self._lower_expr(expr.args[1], names, IrBytesType())
            if len(expr.args) == 2
            else IrConstBytes(b" ")
        )
        if isinstance(fill, IrConstBytes) and len(fill.value) != 1:
            self._error(
                "XCC-AOT-LOWER-0003",
                "bytes.ljust fill must be exactly one byte",
                expr,
            )
        return IrCall(
            "__bytes_ljust",
            (receiver, self._lower_expr(expr.args[0], names, int64), fill),
            IrBytesType(),
        )

    def _lower_string_strip_call(
        self,
        expr: ast.Call,
        receiver: IrExpr,
        names: dict[str, IrType],
    ) -> IrExpr:
        if not isinstance(expr.func, ast.Attribute) or expr.keywords or len(expr.args) > 1:
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        chars = (
            self._lower_expr(expr.args[0], names, IrStringType())
            if expr.args
            else IrConstString(_STRIP_WHITESPACE)
        )
        method = expr.func.attr
        return IrCall(
            f"__str_{method}",
            (receiver, chars),
            IrStringType(),
        )

    def _lower_string_split_call(
        self,
        expr: ast.Call,
        receiver: IrExpr,
        names: dict[str, IrType],
    ) -> IrExpr:
        if expr.keywords or len(expr.args) > 2:
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        int64 = IrIntType(64, signed=True)
        if not expr.args or _is_none_constant(expr.args[0]):
            maxsplit = (
                self._lower_expr(expr.args[1], names, int64)
                if len(expr.args) == 2
                else IrConstInt(-1, int64)
            )
            return IrCall(
                "__str_split_whitespace",
                (receiver, maxsplit),
                IrTupleType((IrStringType(),)),
            )
        if len(expr.args) != 1:
            return IrCall(
                "__str_split_limit",
                (
                    receiver,
                    self._lower_expr(expr.args[0], names, IrStringType()),
                    self._lower_expr(expr.args[1], names, int64),
                ),
                IrTupleType((IrStringType(),)),
            )
        return IrCall(
            "__str_split",
            (
                receiver,
                self._lower_expr(expr.args[0], names, IrStringType()),
            ),
            IrTupleType((IrStringType(),)),
        )

    def _lower_string_splitlines_call(
        self,
        expr: ast.Call,
        receiver: IrExpr,
        names: dict[str, IrType],
    ) -> IrExpr:
        if len(expr.args) > 1 or len(expr.keywords) > 1:
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        if expr.args and expr.keywords:
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        keepends_node: ast.expr | None = None
        if expr.args:
            keepends_node = expr.args[0]
        elif expr.keywords:
            if expr.keywords[0].arg != "keepends":
                self._error(
                    "XCC-AOT-LOWER-0003",
                    f"Unsupported call target: {ast.unparse(expr.func)}",
                    expr,
                )
            keepends_node = expr.keywords[0].value
        keepends = (
            self._lower_expr(keepends_node, names, IrBoolType())
            if keepends_node is not None
            else IrConstBool(False)
        )
        return IrCall(
            "__str_splitlines",
            (receiver, keepends),
            IrTupleType((IrStringType(),)),
        )

    def _lower_string_replace_call(
        self,
        expr: ast.Call,
        receiver: IrExpr,
        names: dict[str, IrType],
    ) -> IrExpr:
        if expr.keywords or len(expr.args) != 2:
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        return IrCall(
            "__str_replace",
            (
                receiver,
                self._lower_expr(expr.args[0], names, IrStringType()),
                self._lower_expr(expr.args[1], names, IrStringType()),
            ),
            IrStringType(),
        )

    def _lower_string_remove_affix_call(
        self,
        expr: ast.Call,
        receiver: IrExpr,
        names: dict[str, IrType],
    ) -> IrExpr:
        if not isinstance(expr.func, ast.Attribute) or expr.keywords or len(expr.args) != 1:
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        return IrCall(
            f"__str_{expr.func.attr}",
            (
                receiver,
                self._lower_expr(expr.args[0], names, IrStringType()),
            ),
            IrStringType(),
        )

    def _lower_string_lower_call(self, expr: ast.Call, receiver: IrExpr) -> IrExpr:
        if expr.args or expr.keywords:
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        return IrCall("__str_lower", (receiver,), IrStringType())

    def _lower_string_find_call(
        self,
        expr: ast.Call,
        receiver: IrExpr,
        names: dict[str, IrType],
    ) -> IrExpr:
        if expr.keywords or len(expr.args) not in {1, 2}:
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        int64 = IrIntType(64, signed=True)
        start = (
            self._lower_expr(expr.args[1], names, int64)
            if len(expr.args) == 2
            else IrConstInt(0, int64)
        )
        return IrCall(
            "__str_find",
            (
                receiver,
                self._lower_expr(expr.args[0], names, IrStringType()),
                start,
            ),
            int64,
        )

    def _lower_string_encode_call(
        self,
        expr: ast.Call,
        receiver: IrExpr,
        names: dict[str, IrType],
    ) -> IrExpr:
        if expr.keywords or len(expr.args) > 1:
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        if expr.args:
            self._lower_expr(expr.args[0], names, IrStringType())
        return IrCall("__str_encode", (receiver,), IrBytesType())

    def _lower_string_predicate_call(
        self,
        expr: ast.Call,
        method: str,
        receiver: IrExpr,
    ) -> IrExpr:
        if expr.args or expr.keywords:
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        return IrCall(f"__str_{method}", (receiver,), IrBoolType())

    def _lower_call_args(
        self,
        expr: ast.Call,
        names: dict[str, IrType],
        expected: IrType,
    ) -> tuple[IrExpr, ...]:
        args = [self._lower_expr(arg, names, expected) for arg in expr.args]
        for keyword in expr.keywords:
            if keyword.arg is None:
                self._error(
                    "XCC-AOT-LOWER-0003",
                    "Unsupported call target: **kwargs",
                    keyword,
                )
            args.append(self._lower_expr(keyword.value, names, expected))
        return tuple(args)

    def _lower_call_args_for_signature(
        self,
        expr: ast.Call,
        names: dict[str, IrType],
        target: str,
        skip_parameters: int,
        fallback: IrType,
    ) -> tuple[IrExpr, ...]:
        function_info = self.function_types.get(target)
        if function_info is None:
            return self._lower_call_args(expr, names, fallback)
        parameters = function_info.parameters[skip_parameters:]
        parameter_defaults = function_info.parameter_defaults[skip_parameters:]
        args: list[IrExpr] = []
        parameter_types: dict[str, IrType] = {}
        for parameter_name, parameter_type in parameters:
            try:
                parameter_types[parameter_name] = self._type_name_to_ir_type(parameter_type, expr)
            except AotError:
                continue
        keyword_values: dict[str, ast.expr] = {}
        for keyword in expr.keywords:
            if keyword.arg is None:
                self._error(
                    "XCC-AOT-LOWER-0003",
                    "Unsupported call target: **kwargs",
                    keyword,
                )
            keyword_values[keyword.arg] = keyword.value
        for index, (parameter_name, parameter_type) in enumerate(parameters):
            arg_type = parameter_types.get(parameter_name, fallback)
            if index < len(expr.args):
                args.append(self._lower_expr(expr.args[index], names, arg_type))
            elif parameter_name in keyword_values:
                args.append(self._lower_expr(keyword_values[parameter_name], names, arg_type))
            else:
                default = parameter_defaults[index] if index < len(parameter_defaults) else None
                args.append(self._default_call_arg_expr(parameter_type, arg_type, default))
        if len(expr.args) > len(parameters):
            for arg in expr.args[len(parameters) :]:
                args.append(self._lower_expr(arg, names, fallback))
        return tuple(args)

    def _default_call_arg_expr(
        self,
        annotation: str,
        type_info: IrType,
        default: ast.expr | None,
    ) -> IrExpr:
        if default is not None:
            default_expr = self._lower_default_arg_expr(default, type_info)
            if default_expr is not None:
                return default_expr
        if "None" in _top_level_union_parts(annotation):
            return IrConstNone()
        return self._default_expr(type_info)

    def _lower_default_arg_expr(
        self,
        default: ast.expr,
        type_info: IrType,
    ) -> IrExpr | None:
        if isinstance(default, ast.Constant):
            return self._lower_expr(default, {}, type_info)
        if isinstance(default, ast.UnaryOp) and isinstance(default.op, (ast.UAdd, ast.USub)):
            return self._lower_expr(default, {}, type_info)
        if (
            isinstance(default, (ast.Tuple, ast.List, ast.Set))
            and not default.elts
            and isinstance(type_info, IrTupleType)
        ):
            return IrTuple((), type_info)
        if (
            isinstance(default, ast.Call)
            and isinstance(default.func, ast.Name)
            and default.func.id in {"frozenset", "list", "set", "tuple"}
            and not default.args
            and not default.keywords
            and isinstance(type_info, IrTupleType)
        ):
            return IrTuple((), type_info)
        if isinstance(default, ast.Name):
            string_constant = self.global_string_constants.get(default.id)
            if string_constant is not None:
                return IrConstString(string_constant)
            string_container = self.global_string_container_constants.get(default.id)
            if string_container is not None:
                return string_container
        return None

    def _function_return_type(
        self,
        target: str,
        fallback: IrType,
    ) -> IrType:
        function_info = self.function_types.get(target)
        if function_info is None:
            return fallback
        return self._aot_type_to_ir_type(function_info.return_type)

    def _record_method_target(self, receiver_type: IrRecordType, method: str) -> str:
        target = f"{receiver_type.name}.{method}"
        qualified_target = self._unique_qualified_function_target(target)
        if qualified_target is not None:
            return qualified_target
        if target in self.function_types:
            return target
        candidates: list[str] = []
        for part in _top_level_union_parts(receiver_type.name):
            if part == "None":
                continue
            candidate = f"{part}.{method}"
            qualified_candidate = self._unique_qualified_function_target(candidate)
            if qualified_candidate is not None:
                candidates.append(qualified_candidate)
            elif candidate in self.function_types:
                candidates.append(candidate)
        if len(candidates) == 1:
            return candidates[0]
        return target

    def _lower_property_getter(self, receiver: IrExpr, attr: str) -> IrExpr | None:
        if not isinstance(receiver.type, IrRecordType):
            return None
        target = self._record_method_target(receiver.type, attr)
        function_info = self.function_types.get(target)
        if function_info is None or len(function_info.parameters) > 1:
            return None
        return IrCall(
            target,
            (receiver,),
            self._function_return_type(target, IrRecordType("object")),
        )

    def _unique_qualified_function_target(self, target: str) -> str | None:
        suffix = f".{target}"
        matches = tuple(
            name for name in self.function_types if name != target and name.endswith(suffix)
        )
        if len(matches) == 1:
            return matches[0]
        return None

    def _lower_constructor_args(
        self,
        record_name: str,
        expr: ast.Call,
        names: dict[str, IrType],
    ) -> tuple[IrExpr, ...]:
        class_info = self.class_types[record_name]
        field_items = tuple(class_info.fields.items())
        keyword_values = {
            keyword.arg: keyword.value for keyword in expr.keywords if keyword.arg is not None
        }
        if record_name == "Lexer":
            return self._lower_lexer_constructor_args(expr, names, keyword_values)
        if record_name == "Parser":
            return self._lower_parser_constructor_args(expr, names, keyword_values, field_items)
        if record_name == "_DirectiveCursor":
            return self._lower_directive_cursor_constructor_args(expr, names, field_items)
        if record_name == "_LLVMGen":
            return self._lower_llvmgen_constructor_args(
                expr,
                names,
                keyword_values,
                field_items,
            )
        mapped_args = self._lower_init_mapped_constructor_args(
            record_name,
            expr,
            names,
            keyword_values,
            field_items,
        )
        if mapped_args is not None:
            return mapped_args
        args: list[IrExpr] = []
        for index, (field_name, field_type) in enumerate(field_items):
            ir_type = self._aot_type_to_ir_type(field_type)
            if index < len(expr.args):
                args.append(self._lower_expr(expr.args[index], names, ir_type))
            elif field_name in keyword_values:
                args.append(self._lower_expr(keyword_values[field_name], names, ir_type))
            else:
                args.append(self._default_expr(ir_type))
        return tuple(args)

    def _lower_init_mapped_constructor_args(
        self,
        record_name: str,
        expr: ast.Call,
        names: dict[str, IrType],
        keyword_values: dict[str, ast.expr],
        field_items: tuple[tuple[str, AotType], ...],
    ) -> tuple[IrExpr, ...] | None:
        class_info = self.class_types[record_name]
        field_parameters = class_info.init_field_parameters
        if not field_items or any(
            field_name not in field_parameters for field_name, _ in field_items
        ):
            return None
        init_target = self._record_method_target(IrRecordType(record_name), "__init__")
        function_info = self.function_types.get(init_target)
        if function_info is None:
            return None
        parameters = function_info.parameters
        defaults = function_info.parameter_defaults
        if parameters and parameters[0][0] in {"self", "cls"}:
            parameters = parameters[1:]
            defaults = defaults[1:]
        parameter_indexes = {
            parameter_name: index
            for index, (parameter_name, _parameter_type) in enumerate(parameters)
        }
        if any(parameter not in parameter_indexes for parameter in field_parameters.values()):
            return None
        args: list[IrExpr] = []
        for field_name, field_type in field_items:
            ir_type = self._aot_type_to_ir_type(field_type)
            parameter_name = field_parameters[field_name]
            parameter_index = parameter_indexes[parameter_name]
            parameter_annotation = parameters[parameter_index][1]
            if parameter_index < len(expr.args):
                args.append(self._lower_expr(expr.args[parameter_index], names, ir_type))
            elif parameter_name in keyword_values:
                args.append(self._lower_expr(keyword_values[parameter_name], names, ir_type))
            else:
                default = defaults[parameter_index] if parameter_index < len(defaults) else None
                args.append(self._default_call_arg_expr(parameter_annotation, ir_type, default))
        return tuple(args)

    def _lower_lexer_constructor_args(
        self,
        expr: ast.Call,
        names: dict[str, IrType],
        keyword_values: dict[str, ast.expr],
    ) -> tuple[IrExpr, ...]:
        int64 = IrIntType(64, signed=True)
        source_node = expr.args[0] if expr.args else keyword_values.get("source")
        source = (
            self._lower_expr(source_node, names, IrStringType())
            if source_node is not None
            else IrConstString("")
        )
        translate_target = (
            "translate_source"
            if "translate_source" in self.function_types
            else "xcc.lexer.translate_source"
        )
        translated = IrCall(translate_target, (source,), IrStringType())
        mode_node = keyword_values.get("mode")
        header_names_node = keyword_values.get("header_names")
        mode = (
            self._lower_expr(mode_node, names, IrStringType())
            if mode_node is not None
            else IrConstString("translation")
        )
        header_names = (
            self._lower_expr(header_names_node, names, IrBoolType())
            if header_names_node is not None
            else IrConstBool(False)
        )
        return (
            translated,
            IrCall("len", (translated,), int64),
            IrConstInt(0, int64),
            IrConstInt(1, int64),
            IrConstInt(1, int64),
            mode,
            header_names,
        )

    def _lower_parser_constructor_args(
        self,
        expr: ast.Call,
        names: dict[str, IrType],
        keyword_values: dict[str, ast.expr],
        field_items: tuple[tuple[str, AotType], ...],
    ) -> tuple[IrExpr, ...]:
        int64 = IrIntType(64, signed=True)
        field_types = tuple(
            self._aot_type_to_ir_type(field_type) for _name, field_type in field_items
        )
        tokens = (
            self._lower_expr(expr.args[0], names, field_types[0])
            if expr.args
            else self._default_expr(field_types[0])
        )
        std_node = keyword_values.get("std")
        std = (
            self._lower_expr(std_node, names, IrStringType())
            if std_node is not None
            else IrConstString("c11")
        )
        return (
            tokens,
            IrConstInt(0, int64),
            std,
            self._singleton_empty_container(field_types[3]),
            self._singleton_empty_container(field_types[4]),
            self._singleton_empty_container(field_types[5]),
            self._singleton_empty_container(field_types[6]),
            self._singleton_empty_container(field_types[7]),
            IrConstBool(False),
            IrConstBool(False),
            self._default_expr(field_types[10]),
            IrConstBool(False),
            IrConstBool(False),
        )

    def _lower_directive_cursor_constructor_args(
        self,
        expr: ast.Call,
        names: dict[str, IrType],
        field_items: tuple[tuple[str, AotType], ...],
    ) -> tuple[IrExpr, ...]:
        field_types = tuple(
            self._aot_type_to_ir_type(field_type) for _name, field_type in field_items
        )
        cursor = (
            self._lower_expr(expr.args[0], names, IrRecordType("_LogicalCursor"))
            if expr.args
            else self._default_expr(IrRecordType("_LogicalCursor"))
        )
        count = (
            self._lower_expr(expr.args[1], names, IrIntType(64, signed=True))
            if len(expr.args) > 1
            else self._default_expr(IrIntType(64, signed=True))
        )
        target = (
            "xcc.preprocessor.__init__._directive_cursor_locations"
            if "xcc.preprocessor.__init__._directive_cursor_locations" in self.function_types
            else "_directive_cursor_locations"
        )
        return (IrCall(target, (cursor, count), field_types[0]),)

    def _lower_llvmgen_constructor_args(
        self,
        expr: ast.Call,
        names: dict[str, IrType],
        keyword_values: dict[str, ast.expr],
        field_items: tuple[tuple[str, AotType], ...],
    ) -> tuple[IrExpr, ...]:
        int64 = IrIntType(64, signed=True)
        field_types = tuple(
            self._aot_type_to_ir_type(field_type) for _name, field_type in field_items
        )
        fields = {
            field_name: field_types[index] for index, (field_name, _) in enumerate(field_items)
        }
        result_node = expr.args[0] if expr.args else keyword_values.get("result")
        result = (
            self._lower_expr(result_node, names, fields["_result"])
            if result_node is not None
            else self._default_expr(fields["_result"])
        )
        sema = IrGetField(result, "sema", fields["_sema"])
        overrides: dict[str, IrExpr] = {
            "_result": result,
            "_unit": IrGetField(result, "unit", fields["_unit"]),
            "_type_map": IrGetField(sema, "type_map", fields["_type_map"]),
            "_sema": sema,
            "_ctx": IrCall("__llvm_ContextCreate", (), int64),
            "_mod": IrCall(
                "__llvm_ModuleCreateWithName",
                (IrGetField(result, "filename", IrStringType()),),
                int64,
            ),
            "_builder": IrCall("__llvm_CreateBuilder", (), int64),
        }
        return tuple(
            overrides.get(field_name, self._default_expr(field_types[index]))
            for index, (field_name, _) in enumerate(field_items)
        )

    def _singleton_empty_container(self, type_info: IrType) -> IrExpr:
        if isinstance(type_info, IrTupleType) and type_info.elements:
            element_type = type_info.elements[0]
            if isinstance(element_type, IrTupleType | IrDictType):
                return IrTuple((IrTuple((), element_type),), type_info)
        return self._default_expr(type_info)

    def _record_field_types(self, record_name: str) -> tuple[IrType, ...]:
        class_info = self.class_types[record_name]
        return tuple(self._aot_type_to_ir_type(field) for field in class_info.fields.values())

    def _record_field_type(self, record_type: IrType, field: str, node: ast.AST) -> IrType:
        if isinstance(record_type, IrRecordType):
            class_info = self.class_types.get(record_type.name)
            if class_info is not None:
                field_type = class_info.fields.get(field)
                if field_type is not None:
                    return self._aot_type_to_ir_type(field_type)
            union_field_type = self._record_union_field_type(record_type.name, field, node)
            if union_field_type is not None:
                return union_field_type
        self._error(
            "XCC-AOT-LOWER-0002",
            f"Unsupported field access: {field}",
            node,
        )

    def _record_union_field_type(
        self,
        name: str,
        field: str,
        node: ast.AST,
    ) -> IrType | None:
        parts = _top_level_union_parts(name)
        if not parts or "None" in parts:
            return None
        field_types: list[IrType] = []
        for part in parts:
            class_info = self.class_types.get(part)
            if class_info is None:
                return None
            field_type = class_info.fields.get(field)
            if field_type is None:
                return None
            field_types.append(self._aot_type_to_ir_type(field_type))
        first = field_types[0]
        if all(field_type == first for field_type in field_types):
            return first
        self._error(
            "XCC-AOT-LOWER-0002",
            f"Ambiguous union field access: {field}",
            node,
        )

    def _aot_type_to_ir_type(self, type_info: AotType) -> IrType:
        if type_info.bits is not None and type_info.signed is not None:
            return IrIntType(type_info.bits, type_info.signed)
        if type_info.name == "bytes":
            return IrBytesType()
        if type_info.name == "str":
            return IrStringType()
        if type_info.name == "float":
            return IrFloatType()
        if type_info.name == "int":
            return IrIntType(64, signed=True)
        if type_info.name == "bool":
            return IrBoolType()
        if type_info.name == "None":
            return IrNoneType()
        if type_info.name == "NoReturn":
            return IrNoneType()
        if type_info.name in {"Any", "object"}:
            return IrRecordType("object")
        if type_info.name == "Enum":
            return IrRecordType("Enum")
        if type_info.name == "FunctionParams":
            return IrTupleType((IrRecordType("object"), IrBoolType()))
        if type_info.name in {"DeclaratorOp", "TypeOp"}:
            return IrTupleType((IrStringType(), IrRecordType("object")))
        record_name = self._project_record_name(type_info.name)
        if record_name is not None:
            return IrRecordType(record_name)
        if type_info.name.startswith("Literal["):
            return IrStringType()
        if _is_optional_int(type_info.name):
            return IrIntType(64, signed=True)
        dict_type = self._dict_ir_type(type_info.name, ast.Pass())
        if dict_type is not None:
            return dict_type
        optional_tuple_type = self._optional_tuple_backed_container_type(type_info.name, ast.Pass())
        if optional_tuple_type is not None:
            return optional_tuple_type
        if _has_top_level_union(type_info.name):
            return IrRecordType(type_info.name)
        if _is_tuple_backed_container_type(type_info.name):
            return IrTupleType(self._tuple_backed_container_types(type_info.name, ast.Pass()))
        self._error(
            "XCC-AOT-LOWER-0002",
            f"Unsupported lowered type: {type_info.name}",
            ast.Pass(),
        )

    def _project_record_name(self, name: str) -> str | None:
        if name in self.class_types:
            return name
        unqualified = name.rsplit(".", 1)[-1]
        if unqualified in self.class_types:
            return unqualified
        return None

    def _bind_assignment_target(
        self,
        target: ast.expr,
        value_type: IrType,
        names: dict[str, IrType],
    ) -> None:
        if isinstance(target, ast.Name):
            names[target.id] = value_type
            return
        if isinstance(target, ast.Tuple):
            if isinstance(value_type, IrTupleType) and len(value_type.elements) == len(target.elts):
                element_types = value_type.elements
            else:
                element_types = (IrRecordType("object"),) * len(target.elts)
            for element, element_type in zip(target.elts, element_types, strict=True):
                if isinstance(element, ast.Name) and element.id == "_":
                    continue
                self._bind_assignment_target(element, element_type, names)
            return
        if isinstance(target, ast.Attribute):
            names[ast.unparse(target)] = value_type
            return
        self._error(
            "XCC-AOT-LOWER-0001",
            f"Unsupported assignment target: {type(target).__name__}",
            target,
        )

    def _bind_for_target(
        self,
        target: ast.expr,
        iterable: IrExpr,
        names: dict[str, IrType],
    ) -> None:
        if isinstance(iterable, IrCall) and iterable.target == "__enumerate":
            if not isinstance(target, ast.Tuple):
                self._error(
                    "XCC-AOT-LOWER-0001",
                    "Unsupported enumerate target",
                    target,
                )
            if not isinstance(iterable.type, IrTupleType) or len(iterable.type.elements) != len(
                target.elts
            ):
                self._error(
                    "XCC-AOT-LOWER-0001",
                    "Unsupported enumerate target shape",
                    target,
                )
            for element, element_type in zip(target.elts, iterable.type.elements, strict=True):
                if isinstance(element, ast.Name) and element.id == "_":
                    continue
                if not isinstance(element, ast.Name):
                    self._error(
                        "XCC-AOT-LOWER-0001",
                        "Unsupported enumerate target",
                        element,
                    )
                names[element.id] = element_type
            return
        item_type = _for_each_target_type(iterable.type)
        if isinstance(target, ast.Tuple) and isinstance(item_type, IrTupleType):
            if len(item_type.elements) != len(target.elts):
                self._error(
                    "XCC-AOT-LOWER-0001",
                    "Unsupported tuple for target shape",
                    target,
                )
            for element, element_type in zip(target.elts, item_type.elements, strict=True):
                if isinstance(element, ast.Name) and element.id == "_":
                    continue
                if not isinstance(element, ast.Name):
                    self._error(
                        "XCC-AOT-LOWER-0001",
                        "Unsupported tuple for target",
                        element,
                    )
                names[element.id] = element_type
            return
        self._bind_assignment_target(target, _for_each_target_type(iterable.type), names)

    def _lower_for_target_unpack(
        self,
        target: ast.expr,
        value: IrExpr,
        value_type: IrType,
        names: dict[str, IrType],
    ) -> tuple[IrStmt, ...]:
        if isinstance(target, ast.Name):
            if target.id == "_":
                return ()
            names[target.id] = value_type
            return (IrAssign(target.id, value),)
        if not isinstance(target, ast.Tuple):
            self._error(
                "XCC-AOT-LOWER-0001",
                f"Unsupported for target: {type(target).__name__}",
                target,
            )
        if isinstance(value_type, IrTupleType) and len(value_type.elements) == len(target.elts):
            element_types = value_type.elements
        else:
            element_types = (IrRecordType("object"),) * len(target.elts)
        statements: list[IrStmt] = []
        int64 = IrIntType(64, signed=True)
        for index, (element, element_type) in enumerate(
            zip(target.elts, element_types, strict=True)
        ):
            item = IrCall("__getitem", (value, IrConstInt(index, int64)), element_type)
            statements.extend(self._lower_for_target_unpack(element, item, element_type, names))
        return tuple(statements)

    def _assignment_value_type(
        self,
        target: ast.expr,
        value: ast.expr,
        names: dict[str, IrType],
        fallback: IrType,
    ) -> IrType:
        if isinstance(target, ast.Name):
            return names.get(target.id) or self._infer_assignment_expr_type(value, names, fallback)
        if isinstance(target, ast.Attribute):
            receiver = self._lower_expr(target.value, names, IrRecordType("object"))
            if isinstance(receiver.type, IrRecordType) and receiver.type.name in self.class_types:
                return self._record_field_type(receiver.type, target.attr, target)
        if isinstance(target, ast.Tuple):
            return self._infer_assignment_expr_type(value, names, fallback)
        return fallback

    def _subscript_item_type(
        self,
        target: ast.expr,
        names: dict[str, IrType],
        fallback: IrType,
    ) -> IrType:
        target_expr = self._lower_expr(target, names, IrRecordType("object"))
        if isinstance(target_expr.type, IrTupleType) and len(target_expr.type.elements) == 1:
            return target_expr.type.elements[0]
        return fallback

    def _infer_assignment_expr_type(
        self,
        expr: ast.expr,
        names: dict[str, IrType],
        fallback: IrType,
    ) -> IrType:
        if isinstance(expr, ast.Constant):
            if isinstance(expr.value, bool):
                return IrBoolType()
            if expr.value is None:
                return IrNoneType()
            if isinstance(expr.value, int):
                return IrIntType(64, signed=True)
            if isinstance(expr.value, float):
                if _is_object_type(fallback):
                    return fallback
                return IrFloatType()
            if isinstance(expr.value, str):
                return IrStringType()
            if isinstance(expr.value, bytes):
                return IrBytesType()
        if isinstance(expr, ast.IfExp):
            neutral_fallback = IrRecordType("object")
            body_names = dict(names)
            orelse_names = dict(names)
            body_narrowed = self._isinstance_guard_narrowing(
                expr.test,
                names,
            ) or self._not_none_guard_narrowing(expr.test, names)
            if body_narrowed is not None:
                name, narrowed_type = body_narrowed
                body_names[name] = narrowed_type
            else_narrowed = self._is_none_guard_narrowing(expr.test, names)
            if else_narrowed is not None:
                name, narrowed_type = else_narrowed
                orelse_names[name] = narrowed_type
            body_type = self._infer_assignment_expr_type(
                expr.body,
                body_names,
                neutral_fallback,
            )
            orelse_type = self._infer_assignment_expr_type(
                expr.orelse,
                orelse_names,
                body_type,
            )
            if body_type == neutral_fallback and orelse_type != neutral_fallback:
                body_type = self._infer_assignment_expr_type(
                    expr.body,
                    body_names,
                    orelse_type,
                )
            if body_type == orelse_type:
                return body_type
            if isinstance(body_type, IrNoneType) and not isinstance(orelse_type, IrNoneType):
                return orelse_type
            if isinstance(orelse_type, IrNoneType) and not isinstance(body_type, IrNoneType):
                return body_type
            union_type = _compatible_optional_union_type(body_type, orelse_type)
            if union_type is not None:
                return union_type
        if isinstance(expr, (ast.ListComp, ast.GeneratorExp)):
            return fallback if isinstance(fallback, IrTupleType) else IrTupleType(())
        if isinstance(expr, ast.BoolOp):
            value_types = tuple(
                self._infer_assignment_expr_type(value, names, fallback) for value in expr.values
            )
            if value_types and all(
                isinstance(value_type, IrBoolType) for value_type in value_types
            ):
                return IrBoolType()
            if value_types and all(value_type == value_types[0] for value_type in value_types):
                return value_types[0]
        if isinstance(expr, ast.Compare):
            return IrBoolType()
        if isinstance(expr, ast.UnaryOp) and isinstance(expr.op, ast.Not):
            return IrBoolType()
        if isinstance(expr, ast.UnaryOp) and isinstance(expr.op, (ast.UAdd, ast.USub)):
            operand_type = self._infer_assignment_expr_type(expr.operand, names, fallback)
            if isinstance(operand_type, (IrFloatType, IrIntType)):
                return operand_type
        if isinstance(expr, ast.BinOp):
            left_type = self._infer_assignment_expr_type(expr.left, names, fallback)
            right_type = self._infer_assignment_expr_type(expr.right, names, fallback)
            if isinstance(left_type, IrFloatType) and isinstance(right_type, IrFloatType):
                return left_type
            if isinstance(left_type, IrIntType) and isinstance(right_type, IrIntType):
                return left_type
            if (
                isinstance(expr.op, ast.Add)
                and isinstance(left_type, IrStringType)
                and isinstance(right_type, IrStringType)
            ):
                return IrStringType()
        if (
            isinstance(expr, ast.Call)
            and isinstance(expr.func, ast.Name)
            and expr.func.id == "len"
            and len(expr.args) == 1
        ):
            return IrIntType(64, signed=True)
        if (
            isinstance(expr, ast.Call)
            and isinstance(expr.func, ast.Name)
            and expr.func.id in {"min", "max"}
            and not expr.keywords
            and len(expr.args) == 2
        ):
            return IrIntType(64, signed=True)
        if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name) and expr.func.id == "int":
            return IrIntType(64, signed=True)
        if (
            isinstance(expr, ast.Call)
            and isinstance(expr.func, ast.Name)
            and expr.func.id in self.callable_param_targets
        ):
            return self._function_return_type(self.callable_param_targets[expr.func.id], fallback)
        if (
            isinstance(expr, ast.Call)
            and isinstance(expr.func, ast.Name)
            and expr.func.id in self.function_types
        ):
            return self._function_return_type(expr.func.id, fallback)
        if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Attribute):
            target = ast.unparse(expr.func)
            if target in self.function_types:
                return self._function_return_type(target, fallback)
        if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Attribute):
            try:
                return self._lower_expr(expr, names, fallback).type
            except AotError:
                return fallback
        if (
            isinstance(expr, ast.Call)
            and isinstance(expr.func, ast.Name)
            and expr.func.id in {"bool", "isinstance"}
        ):
            return IrBoolType()
        if isinstance(expr, ast.Subscript):
            try:
                return self._lower_expr(expr, names, IrRecordType("object")).type
            except AotError:
                return fallback
        if isinstance(expr, ast.Attribute):
            try:
                return self._lower_expr(expr, names, IrRecordType("object")).type
            except AotError:
                return fallback
        if (
            isinstance(expr, ast.UnaryOp)
            and isinstance(expr.op, (ast.UAdd, ast.USub))
            and isinstance(expr.operand, ast.Constant)
            and type(expr.operand.value) is int
        ):
            return IrIntType(64, signed=True)
        if isinstance(expr, ast.Name):
            value_type = names.get(expr.id)
            if value_type is not None:
                return value_type
            global_type = self.global_types.get(expr.id)
            if global_type is not None:
                return global_type
            string_container = self.global_string_container_constants.get(expr.id)
            if string_container is not None:
                return string_container.type
            return fallback
        return fallback

    def _default_expr(self, type_info: IrType) -> IrExpr:
        return self._default_expr_with_seen(type_info, frozenset())

    def _default_expr_with_seen(self, type_info: IrType, seen_records: frozenset[str]) -> IrExpr:
        if isinstance(type_info, IrIntType):
            return IrConstInt(0, type_info)
        if isinstance(type_info, IrBoolType):
            return IrConstBool(False)
        if isinstance(type_info, IrStringType):
            return IrConstString("")
        if isinstance(type_info, IrBytesType):
            return IrConstBytes(b"")
        if isinstance(type_info, IrNoneType):
            return IrConstNone()
        if isinstance(type_info, IrTupleType):
            return IrTuple((), type_info)
        if isinstance(type_info, IrDictType):
            return IrTuple((), type_info)
        if isinstance(type_info, IrRecordType) and type_info.name in self.class_types:
            if type_info.name in seen_records:
                return IrConstNone()
            nested_seen = seen_records | {type_info.name}
            class_info = self.class_types[type_info.name]
            args = tuple(
                self._default_expr_with_seen(self._aot_type_to_ir_type(field), nested_seen)
                for field in class_info.fields.values()
            )
            return IrConstructRecord(type_info.name, args, type_info)
        return IrConstNone()

    def _tuple_backed_container_element_type(
        self,
        name: str,
        node: ast.AST,
    ) -> IrType | None:
        element_name = _tuple_backed_container_element_name(name)
        if element_name is None:
            return None
        return self._optional_container_type(element_name, node)

    def _tuple_backed_container_types(
        self,
        name: str,
        node: ast.AST,
    ) -> tuple[IrType, ...]:
        if name.startswith(("tuple[", "Tuple[")) and name.endswith("]"):
            content = name[name.find("[") + 1 : -1]
            args = _annotation_args(content)
            if len(args) > 1 and args[-1] != "...":
                fixed_types: list[IrType] = []
                for arg in args:
                    arg_type = self._optional_container_type(_strip_annotation_quotes(arg), node)
                    if arg_type is None:
                        return ()
                    fixed_types.append(arg_type)
                return tuple(fixed_types)
        dict_names = _dict_container_type_names(name)
        if dict_names is not None:
            key_type = self._optional_container_type(dict_names[0], node)
            value_type = self._optional_container_type(dict_names[1], node)
            if key_type is not None and value_type is not None:
                return (key_type, value_type)
            return ()
        element_type = self._tuple_backed_container_element_type(name, node)
        if element_type is not None:
            return (element_type,)
        return ()

    def _dict_ir_type(self, name: str, node: ast.AST) -> IrDictType | None:
        dict_names = _dict_container_type_names(name)
        if dict_names is None:
            return None
        key_type = self._optional_container_type(dict_names[0], node)
        value_type = self._optional_container_type(dict_names[1], node)
        if key_type is None or value_type is None:
            return None
        return IrDictType(key_type, value_type)

    def _optional_container_type(self, name: str, node: ast.AST) -> IrType | None:
        try:
            return self._type_name_to_ir_type(name, node)
        except AotError:
            return None

    def _optional_tuple_backed_container_type(
        self,
        name: str,
        node: ast.AST,
    ) -> IrTupleType | IrDictType | None:
        parts = _top_level_union_parts(name)
        if not parts:
            return None
        non_none_parts = tuple(part for part in parts if part != "None")
        if len(non_none_parts) != 1 or len(non_none_parts) == len(parts):
            return None
        non_none = non_none_parts[0]
        if not _is_tuple_backed_container_type(non_none):
            return None
        dict_type = self._dict_ir_type(non_none, node)
        if dict_type is not None:
            return dict_type
        return IrTupleType(self._tuple_backed_container_types(non_none, node))

    def _lower_llvm_api_constructor(self, expr: ast.Call) -> IrExpr:
        if expr.args or expr.keywords:
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        return IrCall("__llvm_api", (), IrRecordType(_LLVM_API_RECORD))

    def _lower_llvm_api_call(
        self,
        expr: ast.Call,
        names: dict[str, IrType],
        expected: IrType,
    ) -> IrExpr:
        if not isinstance(expr.func, ast.Attribute):
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        if expr.keywords:
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        method = expr.func.attr
        return IrCall(
            f"__llvm_{method}",
            tuple(
                self._lower_expr(
                    arg,
                    names,
                    _llvm_api_call_arg_type(method, index, IrRecordType("object")),
                )
                for index, arg in enumerate(expr.args)
            ),
            _llvm_api_call_return_type(method, expected),
        )

    def _lower_enumerate_call(self, expr: ast.Call, names: dict[str, IrType]) -> IrExpr:
        if len(expr.args) not in {1, 2} or len(expr.keywords) > 1:
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        if expr.keywords and (len(expr.args) != 1 or expr.keywords[0].arg != "start"):
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        start_node = expr.keywords[0].value if expr.keywords else None
        if len(expr.args) == 2:
            start_node = expr.args[1]
        int64 = IrIntType(64, signed=True)
        iterable = self._lower_expr(expr.args[0], names, IrTupleType(()))
        start: IrExpr
        if start_node is None:
            start = IrConstInt(0, int64)
        else:
            start = self._lower_expr(start_node, names, int64)
        return IrCall(
            "__enumerate",
            (iterable, start),
            IrTupleType((int64, _for_each_target_type(iterable.type))),
        )

    def _lower_zip_call(self, expr: ast.Call, names: dict[str, IrType]) -> IrExpr:
        if not expr.args:
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        for keyword in expr.keywords:
            if (
                keyword.arg != "strict"
                or not isinstance(keyword.value, ast.Constant)
                or not isinstance(keyword.value.value, bool)
            ):
                self._error(
                    "XCC-AOT-LOWER-0003",
                    f"Unsupported call target: {ast.unparse(expr.func)}",
                    expr,
                )
        iterables = tuple(self._lower_expr(arg, names, IrTupleType(())) for arg in expr.args)
        item_types = tuple(_for_each_target_type(iterable.type) for iterable in iterables)
        return IrCall("__zip", iterables, IrTupleType((IrTupleType(item_types),)))

    def _lower_dict_get_call(
        self,
        expr: ast.Call,
        receiver: IrExpr,
        names: dict[str, IrType],
    ) -> IrExpr:
        if expr.keywords or len(expr.args) != 1 or not isinstance(receiver.type, IrDictType):
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        key_type, value_type = receiver.type.key, receiver.type.value
        return IrCall(
            "__dict_get",
            (receiver, self._lower_expr(expr.args[0], names, key_type)),
            _dict_get_result_type(value_type),
        )

    def _lower_dict_setdefault_call(
        self,
        expr: ast.Call,
        receiver: IrExpr,
        names: dict[str, IrType],
    ) -> IrExpr:
        if expr.keywords or len(expr.args) != 2 or not isinstance(receiver.type, IrDictType):
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        key_type, value_type = receiver.type.key, receiver.type.value
        self._lower_expr(expr.args[1], names, value_type)
        return IrCall(
            "__dict_get",
            (receiver, self._lower_expr(expr.args[0], names, key_type)),
            value_type,
        )

    def _lower_dict_items_call(
        self,
        expr: ast.Call,
        receiver: IrExpr,
    ) -> IrExpr:
        if expr.keywords or expr.args or not isinstance(receiver.type, IrDictType):
            self._error(
                "XCC-AOT-LOWER-0003",
                f"Unsupported call target: {ast.unparse(expr.func)}",
                expr,
            )
        return IrCall(
            "__dict_items",
            (receiver,),
            IrTupleType((IrTupleType((receiver.type.key, receiver.type.value)),)),
        )

    def _none_guard_narrowing(
        self,
        test: ast.expr,
        body: Sequence[ast.stmt],
        orelse: Sequence[ast.stmt],
        names: dict[str, IrType],
    ) -> tuple[str, IrType] | None:
        narrowings = self._none_guard_narrowings(test, body, orelse, names)
        return narrowings[0] if narrowings else None

    def _none_guard_narrowings(
        self,
        test: ast.expr,
        body: Sequence[ast.stmt],
        orelse: Sequence[ast.stmt],
        names: dict[str, IrType],
    ) -> tuple[tuple[str, IrType], ...]:
        if orelse or not _statements_exit(body):
            return ()
        narrowings: list[tuple[str, IrType]] = []
        for name in _none_guard_names(test):
            narrowed = self._optional_record_inner(names.get(name))
            if narrowed is not None:
                narrowings.append((name, narrowed))
        return tuple(narrowings)

    def _negative_isinstance_guard_narrowing(
        self,
        test: ast.expr,
        body: Sequence[ast.stmt],
        orelse: Sequence[ast.stmt],
        names: dict[str, IrType],
    ) -> tuple[str, IrType] | None:
        narrowings = self._negative_isinstance_guard_narrowings(test, body, orelse, names)
        return narrowings[0] if narrowings else None

    def _negative_isinstance_guard_narrowings(
        self,
        test: ast.expr,
        body: Sequence[ast.stmt],
        orelse: Sequence[ast.stmt],
        names: dict[str, IrType],
    ) -> tuple[tuple[str, IrType], ...]:
        if orelse or not _statements_exit(body):
            return ()
        return self._negative_isinstance_condition_narrowings(test, names)

    def _negative_isinstance_condition_narrowing(
        self,
        test: ast.expr,
        names: dict[str, IrType],
    ) -> tuple[str, IrType] | None:
        narrowings = self._negative_isinstance_condition_narrowings(test, names)
        return narrowings[0] if narrowings else None

    def _negative_isinstance_condition_narrowings(
        self,
        test: ast.expr,
        names: dict[str, IrType],
    ) -> tuple[tuple[str, IrType], ...]:
        if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or):
            narrowings: list[tuple[str, IrType]] = []
            narrowed_names = dict(names)
            for value in test.values:
                value_narrowings = self._negative_isinstance_condition_narrowings(
                    value,
                    narrowed_names,
                )
                for name, narrowed_type in value_narrowings:
                    narrowed_names[name] = narrowed_type
                narrowings.extend(value_narrowings)
            return tuple(narrowings)
        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
            narrowed = self._isinstance_guard_narrowing(test.operand, names)
            return () if narrowed is None else (narrowed,)
        return ()

    def _optional_record_inner(self, type_info: IrType | None) -> IrType | None:
        if not isinstance(type_info, IrRecordType):
            return None
        parts = tuple(part.strip() for part in type_info.name.split("|"))
        non_none = tuple(part for part in parts if part != "None")
        if not non_none or len(non_none) == len(parts):
            return None
        if len(non_none) == 1 and non_none[0] == "bytes":
            return IrBytesType()
        if len(non_none) == 1 and non_none[0] == "str":
            return IrStringType()
        if len(non_none) == 1 and _record_constructor_type_base_name(non_none[0]) is not None:
            return IrRecordType(non_none[0])
        if any(part not in self.class_types for part in non_none):
            return None
        return IrRecordType(" | ".join(non_none))

    def _isinstance_guard_narrowing(
        self,
        test: ast.expr,
        names: dict[str, IrType],
    ) -> tuple[str, IrType] | None:
        narrowings = self._isinstance_guard_narrowings(test, names)
        return narrowings[0] if narrowings else None

    def _isinstance_guard_narrowings(
        self,
        test: ast.expr,
        names: dict[str, IrType],
    ) -> tuple[tuple[str, IrType], ...]:
        if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And):
            narrowings: list[tuple[str, IrType]] = []
            narrowed_names = dict(names)
            for value in test.values:
                narrowed = self._isinstance_guard_narrowing(value, narrowed_names)
                if narrowed is not None:
                    name, narrowed_type = narrowed
                    narrowed_names[name] = narrowed_type
                    narrowings.append(narrowed)
            return tuple(narrowings)
        narrowed = self._single_isinstance_guard_narrowing(test, names)
        return () if narrowed is None else (narrowed,)

    def _single_isinstance_guard_narrowing(
        self,
        test: ast.expr,
        names: dict[str, IrType],
    ) -> tuple[str, IrType] | None:
        if (
            not isinstance(test, ast.Call)
            or not isinstance(test.func, ast.Name)
            or test.func.id != "isinstance"
            or test.keywords
            or len(test.args) != 2
        ):
            return None
        value, target_type = test.args
        target_names = _isinstance_target_names(target_type)
        if not isinstance(value, ast.Name | ast.Attribute | ast.Subscript) or target_names is None:
            return None
        narrowed_name = ast.unparse(value)
        try:
            current = self._lower_expr(value, names, IrRecordType("object")).type
        except AotError:
            return None
        if target_names == ("int",) and (
            isinstance(value, ast.Attribute) or narrowed_name in names
        ):
            return narrowed_name, IrIntType(64, signed=True)
        if target_names == ("str",) and (
            isinstance(value, ast.Attribute) or narrowed_name in names
        ):
            return narrowed_name, IrStringType()
        if target_names == ("tuple",):
            narrowed_tuple = self._tuple_guard_narrowing_type(current, target_type)
            if narrowed_tuple is not None:
                return narrowed_name, narrowed_tuple
        if any(target_name not in self.class_types for target_name in target_names):
            return None
        narrowed_records = tuple(
            target_name
            for target_name in target_names
            if _can_narrow_to_record(current, target_name, self.class_types)
        )
        if not narrowed_records:
            return None
        return narrowed_name, IrRecordType(" | ".join(narrowed_records))

    def _tuple_guard_narrowing_type(
        self,
        current: IrType,
        node: ast.AST,
    ) -> IrTupleType | None:
        if isinstance(current, IrTupleType):
            return current
        if not isinstance(current, IrRecordType):
            return None
        if current.name == "object":
            return IrTupleType(())
        parts = _top_level_union_parts(current.name)
        if not parts:
            return None
        candidates: list[IrTupleType] = []
        for part in parts:
            narrowed = self._tuple_union_part_type(part, node)
            if narrowed is not None:
                candidates.append(narrowed)
        if len(candidates) == 1:
            return candidates[0]
        return None

    def _tuple_union_part_type(self, part: str, node: ast.AST) -> IrTupleType | None:
        try:
            narrowed = self._type_name_to_ir_type(part, node)
        except AotError:
            return None
        if isinstance(narrowed, IrTupleType):
            return narrowed
        return None

    def _truthy_optional_record_narrowing(
        self,
        test: ast.expr,
        names: dict[str, IrType],
    ) -> tuple[str, IrType] | None:
        if not isinstance(test, ast.Name | ast.Attribute):
            return None
        try:
            value = self._lower_expr(test, names, IrRecordType("object"))
        except AotError:
            return None
        narrowed = self._optional_record_inner(value.type)
        if narrowed is None:
            return None
        return ast.unparse(test), narrowed

    def _not_none_guard_narrowing(
        self,
        test: ast.expr,
        names: dict[str, IrType],
    ) -> tuple[str, IrType] | None:
        if (
            not isinstance(test, ast.Compare)
            or len(test.ops) != 1
            or not isinstance(test.ops[0], ast.IsNot)
            or len(test.comparators) != 1
        ):
            return None
        guarded: ast.expr | None = None
        if _is_none_constant(test.left):
            guarded = test.comparators[0]
        elif _is_none_constant(test.comparators[0]):
            guarded = test.left
        if guarded is None or not isinstance(guarded, ast.Name | ast.Attribute):
            return None
        try:
            value = self._lower_expr(guarded, names, IrRecordType("object"))
        except AotError:
            return None
        narrowed = self._optional_record_inner(value.type)
        if narrowed is None:
            return None
        return ast.unparse(guarded), narrowed

    def _is_none_guard_narrowing(
        self,
        test: ast.expr,
        names: dict[str, IrType],
    ) -> tuple[str, IrType] | None:
        if (
            not isinstance(test, ast.Compare)
            or len(test.ops) != 1
            or not isinstance(test.ops[0], ast.Is)
            or len(test.comparators) != 1
        ):
            return None
        guarded: ast.expr | None = None
        if _is_none_constant(test.left):
            guarded = test.comparators[0]
        elif _is_none_constant(test.comparators[0]):
            guarded = test.left
        if guarded is None or not isinstance(guarded, ast.Name | ast.Attribute):
            return None
        try:
            value = self._lower_expr(guarded, names, IrRecordType("object"))
        except AotError:
            return None
        narrowed = self._optional_record_inner(value.type)
        if narrowed is None:
            return None
        return ast.unparse(guarded), narrowed

    def _none_bool_op_narrowing(
        self,
        test: ast.expr,
        names: dict[str, IrType],
    ) -> tuple[str, IrType] | None:
        name = _none_guard_name(test)
        if name is None:
            return None
        narrowed = self._optional_record_inner(names.get(name))
        if narrowed is None:
            return None
        return name, narrowed

    def _lower_compare(self, expr: ast.Compare, names: dict[str, IrType]) -> IrExpr:
        if len(expr.ops) != len(expr.comparators) or not expr.ops:
            self._error(
                "XCC-AOT-LOWER-0004",
                "Unsupported control-flow lowering: malformed compare",
                expr,
            )
        comparisons: list[IrExpr] = []
        left = expr.left
        for op, right in zip(expr.ops, expr.comparators, strict=True):
            operand_type = self._compare_operand_type(op, left, right, names)
            comparisons.append(
                IrCall(
                    f"__cmp_{type(op).__name__}",
                    (
                        self._lower_expr(left, names, operand_type),
                        self._lower_expr(right, names, operand_type),
                    ),
                    IrBoolType(),
                )
            )
            left = right
        if len(comparisons) == 1:
            return comparisons[0]
        return IrCall("__bool_and", tuple(comparisons), IrBoolType())

    def _compare_operand_type(
        self,
        op: ast.cmpop,
        left: ast.expr,
        right: ast.expr,
        names: dict[str, IrType],
    ) -> IrType:
        if isinstance(op, (ast.Eq, ast.NotEq, ast.Gt, ast.GtE, ast.Lt, ast.LtE)):
            left_type = self._infer_assignment_expr_type(left, names, IrRecordType("object"))
            right_type = self._infer_assignment_expr_type(right, names, IrRecordType("object"))
            if isinstance(left_type, IrIntType):
                return left_type
            if isinstance(right_type, IrIntType):
                return right_type
        return IrRecordType("object")

    def _lower_bool_op(
        self,
        expr: ast.BoolOp,
        names: dict[str, IrType],
        expected: IrType,
    ) -> IrExpr:
        if not isinstance(expected, IrBoolType):
            return self._lower_value_bool_op(expr.op, tuple(expr.values), names, expected)
        target = "__bool_and" if isinstance(expr.op, ast.And) else "__bool_or"
        value_names = dict(names)
        values: list[IrExpr] = []
        for value in expr.values:
            if isinstance(expr.op, ast.And) and self._is_definitely_false_isinstance(
                value,
                value_names,
            ):
                values.append(IrConstBool(False))
                break
            values.append(self._lower_expr(value, value_names, IrBoolType()))
            if isinstance(expr.op, ast.And):
                narrowed = self._isinstance_guard_narrowing(
                    value,
                    value_names,
                ) or self._not_none_guard_narrowing(value, value_names)
                if narrowed is not None:
                    name, narrowed_type = narrowed
                    value_names[name] = narrowed_type
            else:
                narrowed = self._none_bool_op_narrowing(
                    value,
                    value_names,
                ) or self._negative_isinstance_condition_narrowing(value, value_names)
                if narrowed is not None:
                    name, narrowed_type = narrowed
                    value_names[name] = narrowed_type
        return IrCall(
            target,
            tuple(values),
            IrBoolType(),
        )

    def _is_definitely_false_isinstance(
        self,
        expr: ast.expr,
        names: dict[str, IrType],
    ) -> bool:
        if (
            not isinstance(expr, ast.Call)
            or not isinstance(expr.func, ast.Name)
            or expr.func.id != "isinstance"
            or expr.keywords
            or len(expr.args) != 2
        ):
            return False
        value, target_type = expr.args
        target_names = _isinstance_target_names(target_type)
        if target_names is None or any(
            target_name not in self.class_types for target_name in target_names
        ):
            return False
        try:
            current = self._lower_expr(value, names, IrRecordType("object")).type
        except AotError:
            return False
        return not any(
            _can_narrow_to_record(current, target_name, self.class_types)
            for target_name in target_names
        )

    def _lower_value_bool_op(
        self,
        op: ast.boolop,
        values: tuple[ast.expr, ...],
        names: dict[str, IrType],
        expected: IrType,
    ) -> IrExpr:
        first_node = values[0]
        first = self._lower_expr(first_node, names, expected)
        if len(values) == 1:
            return first
        rest_names = dict(names)
        if isinstance(op, ast.And):
            narrowed = self._isinstance_guard_narrowing(
                first_node,
                rest_names,
            ) or self._not_none_guard_narrowing(first_node, rest_names)
            if narrowed is not None:
                name, narrowed_type = narrowed
                rest_names[name] = narrowed_type
            rest = self._lower_value_bool_op(op, values[1:], rest_names, expected)
            result_type = _value_bool_op_result_type(op, first.type, rest.type, expected)
            return IrCall("__ifexp", (first, rest, first), result_type)
        narrowed = self._none_bool_op_narrowing(
            first_node,
            rest_names,
        ) or self._negative_isinstance_condition_narrowing(first_node, rest_names)
        if narrowed is not None:
            name, narrowed_type = narrowed
            rest_names[name] = narrowed_type
        rest = self._lower_value_bool_op(op, values[1:], rest_names, expected)
        result_type = _value_bool_op_result_type(op, first.type, rest.type, expected)
        return IrCall("__ifexp", (first, first, rest), result_type)

    def _lower_joined_str(self, expr: ast.JoinedStr, names: dict[str, IrType]) -> IrExpr:
        parts: list[IrExpr] = []
        for value in expr.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(IrConstString(value.value))
            elif isinstance(value, ast.FormattedValue):
                value_type = self._infer_assignment_expr_type(
                    value.value,
                    names,
                    IrRecordType("object"),
                )
                parts.append(self._lower_expr(value.value, names, value_type))
            else:
                self._error(
                    "XCC-AOT-LOWER-0005",
                    "Unsupported runtime operation lowering: f-string part",
                    value,
                )
        return IrStringConcat(tuple(parts))

    def _error(self, code: str, message: str, node: ast.AST) -> NoReturn:
        line, column = node_location(node)
        raise AotError(
            (
                AotDiagnostic(
                    code,
                    message,
                    filename=self.filename,
                    line=line,
                    column=column,
                ),
            )
        )


def _width_alias_to_ir_type(name: str) -> IrIntType | None:
    if name.startswith("uint") and name[4:].isdigit():
        return IrIntType(int(name[4:]), signed=False)
    if name.startswith("int") and name[3:].isdigit():
        return IrIntType(int(name[3:]), signed=True)
    if name == "usize":
        return IrIntType(64, signed=False)
    return None


def _lowered_function_name(name: str, owner: str | None) -> str:
    return f"{owner}.{name}" if owner is not None else name


def _is_optional_int(name: str) -> bool:
    return name in {"int | None", "None | int"}


def _top_level_union_parts(name: str) -> tuple[str, ...]:
    depth = 0
    start = 0
    index = 0
    parts: list[str] = []
    while index < len(name):
        char = name[index]
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
        elif depth == 0 and name.startswith(" | ", index):
            parts.append(name[start:index].strip())
            index += 3
            start = index
            continue
        index += 1
    if not parts:
        return ()
    parts.append(name[start:].strip())
    return tuple(parts)


def _has_top_level_union(name: str) -> bool:
    return bool(_top_level_union_parts(name))


def _is_tuple_backed_container_type(name: str) -> bool:
    return name.startswith(
        (
            "Iterable[",
            "Sequence[",
            "dict[",
            "frozenset[",
            "list[",
            "set[",
            "tuple[",
        )
    )


def _tuple_backed_container_element_name(name: str) -> str | None:
    if name.startswith(("dict[", "Dict[")):
        return None
    if not name.startswith(
        (
            "Iterable[",
            "Sequence[",
            "frozenset[",
            "list[",
            "set[",
            "tuple[",
        )
    ):
        return None
    if not name.endswith("]"):
        return None
    content = name[name.find("[") + 1 : -1]
    first = _first_annotation_arg(content)
    if first == "..." or not first:
        return None
    return _strip_annotation_quotes(first)


def _dict_container_type_names(name: str) -> tuple[str, str] | None:
    if not name.startswith(("dict[", "Dict[")) or not name.endswith("]"):
        return None
    content = name[name.find("[") + 1 : -1]
    args = _annotation_args(content)
    if len(args) != 2:
        return None
    return (_strip_annotation_quotes(args[0]), _strip_annotation_quotes(args[1]))


def _annotation_args(content: str) -> tuple[str, ...]:
    args: list[str] = []
    depth = 0
    start = 0
    for index, char in enumerate(content):
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
        elif char == "," and depth == 0:
            args.append(content[start:index].strip())
            start = index + 1
    args.append(content[start:].strip())
    return tuple(arg for arg in args if arg)


def _first_annotation_arg(content: str) -> str:
    depth = 0
    for index, char in enumerate(content):
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
        elif char == "," and depth == 0:
            return content[:index].strip()
    return content.strip()


def _strip_annotation_quotes(name: str) -> str:
    if len(name) >= 2 and name[0] == name[-1] and name[0] in {"'", '"'}:
        return name[1:-1]
    return name


def _for_each_target_type(iterable_type: IrType) -> IrType:
    if isinstance(iterable_type, IrBytesType | IrStringType):
        return IrIntType(64, signed=True)
    if isinstance(iterable_type, IrDictType):
        return iterable_type.key
    if isinstance(iterable_type, IrTupleType) and len(iterable_type.elements) == 1:
        return iterable_type.elements[0]
    if isinstance(iterable_type, IrTupleType) and iterable_type.elements:
        first = iterable_type.elements[0]
        for element in iterable_type.elements:
            if element != first:
                return IrRecordType("object")
        return first
    return IrRecordType("object")


def _for_iterable_item_type(iterable: IrExpr) -> IrType:
    if isinstance(iterable, IrCall) and iterable.target == "__enumerate":
        return iterable.type
    return _for_each_target_type(iterable.type)


def _for_target_needs_temp_unpack(target: ast.expr) -> bool:
    if not isinstance(target, ast.Tuple):
        return False
    return any(not isinstance(element, ast.Name) for element in target.elts)


def _tuple_subscript_result_type(index_expr: ast.expr, tuple_type: IrTupleType) -> IrType:
    if len(tuple_type.elements) == 1:
        return tuple_type.elements[0]
    index = _constant_int_or_none(index_expr)
    if index is None:
        return IrRecordType("object")
    if index < 0:
        index += len(tuple_type.elements)
    if 0 <= index < len(tuple_type.elements):
        return tuple_type.elements[index]
    return IrRecordType("object")


def _is_object_type(type_info: IrType) -> bool:
    return isinstance(type_info, IrRecordType) and type_info.name == "object"


def _compatible_optional_union_type(left: IrType, right: IrType) -> IrRecordType | None:
    if not isinstance(left, IrRecordType) or not isinstance(right, IrRecordType):
        return None
    if _record_union_contains_type(left.name, right.name):
        return left
    if _record_union_contains_type(right.name, left.name):
        return right
    return None


def _record_union_contains_type(union_name: str, member_name: str) -> bool:
    parts = _top_level_union_parts(union_name)
    return "None" in parts and member_name in parts


def _value_bool_op_result_type(
    _op: ast.boolop,
    first_type: IrType,
    rest_type: IrType,
    expected: IrType,
) -> IrType:
    if isinstance(first_type, IrDictType) and isinstance(rest_type, IrDictType):
        generic_dict = IrDictType(IrRecordType("object"), IrRecordType("object"))
        if first_type == generic_dict:
            return rest_type
        if rest_type == generic_dict or first_type == rest_type:
            return first_type
        if isinstance(expected, IrDictType):
            return expected
    if isinstance(first_type, IrTupleType) and isinstance(rest_type, IrTupleType):
        if not first_type.elements:
            return rest_type
        if not rest_type.elements:
            return first_type
        if first_type == rest_type:
            return first_type
    if isinstance(expected, IrRecordType) and expected in (first_type, rest_type):
        return expected
    if first_type == rest_type:
        return first_type
    if isinstance(first_type, IrNoneType):
        return rest_type
    if isinstance(rest_type, IrNoneType):
        return first_type
    union_type = _compatible_optional_union_type(first_type, rest_type)
    if union_type is not None:
        return union_type
    return expected


def _literal_element_expected_type(expected: IrType) -> IrType:
    if isinstance(expected, IrTupleType) and len(expected.elements) == 1:
        return expected.elements[0]
    return expected


def _llvm_api_call_return_type(method: str, expected: IrType) -> IrType:
    if method in _LLVM_API_VOID_METHODS:
        return IrNoneType()
    if method in _LLVM_API_BOOL_METHODS:
        return IrBoolType()
    if method in _LLVM_API_INTEGER_METHODS or method in _LLVM_API_HANDLE_METHODS:
        return IrIntType(64, signed=True)
    if not isinstance(expected, IrNoneType):
        return expected
    return IrIntType(64, signed=True)


def _llvm_api_call_arg_type(method: str, index: int, fallback: IrType) -> IrType:
    if method in {"ArrayType", "ConstNull"} and index == 0:
        return IrIntType(64, signed=True)
    if method == "ConstInt" and index == 1:
        return IrIntType(64, signed=True)
    return fallback


def _dict_get_result_type(value_type: IrType) -> IrType:
    if isinstance(value_type, IrRecordType):
        if "None" in (part.strip() for part in value_type.name.split("|")):
            return value_type
        return IrRecordType(f"{value_type.name} | None")
    return value_type


def _can_narrow_to_record(
    type_info: IrType | None,
    record_name: str,
    class_types: dict[str, AotClassInfo],
) -> bool:
    if not isinstance(type_info, IrRecordType):
        return False
    if type_info.name == "object":
        return True
    if any(part.strip() == "object" for part in type_info.name.split("|")):
        return True
    return any(
        _record_extends(record_name, part.strip(), class_types)
        for part in type_info.name.split("|")
    )


def _isinstance_target_names(target: ast.expr) -> tuple[str, ...] | None:
    if isinstance(target, ast.Name):
        return (target.id,)
    if isinstance(target, ast.Attribute):
        return (target.attr,)
    if isinstance(target, ast.Tuple):
        names: list[str] = []
        for element in target.elts:
            if isinstance(element, ast.Name):
                names.append(element.id)
            elif isinstance(element, ast.Attribute):
                names.append(element.attr)
            else:
                return None
        return tuple(names) if names else None
    return None


def _record_extends(
    record_name: str,
    base_name: str,
    class_types: dict[str, AotClassInfo],
) -> bool:
    if record_name == base_name:
        return True
    class_info = class_types.get(record_name)
    if class_info is None:
        return False
    return any(
        base == base_name or _record_extends(base, base_name, class_types)
        for base in class_info.bases
    )


def _none_guard_name(test: ast.expr) -> str | None:
    names = _none_guard_names(test)
    return names[0] if names else None


def _assignable_target_name(expr: ast.expr) -> str | None:
    if isinstance(expr, (ast.Name, ast.Attribute)):
        return ast.unparse(expr)
    return None


def _none_guard_names(test: ast.expr) -> tuple[str, ...]:
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or):
        names: list[str] = []
        for value in test.values:
            names.extend(_none_guard_names(value))
        return tuple(names)
    if (
        isinstance(test, ast.Compare)
        and len(test.ops) == 1
        and isinstance(test.ops[0], ast.Is)
        and len(test.comparators) == 1
    ):
        if isinstance(test.left, ast.Name) and _is_none_constant(test.comparators[0]):
            return (test.left.id,)
        if _is_none_constant(test.left) and isinstance(test.comparators[0], ast.Name):
            return (test.comparators[0].id,)
    return ()


def _is_none_constant(expr: ast.expr) -> bool:
    return isinstance(expr, ast.Constant) and expr.value is None


def _statements_exit(statements: Sequence[ast.stmt]) -> bool:
    return bool(statements) and isinstance(statements[-1], (ast.Return, ast.Raise))


def _statements_fall_through(statements: Sequence[ast.stmt]) -> bool:
    if not statements:
        return True
    last = statements[-1]
    if isinstance(last, (ast.Break, ast.Continue, ast.Raise, ast.Return)):
        return False
    if isinstance(last, ast.If) and last.orelse:
        return _statements_fall_through(last.body) or _statements_fall_through(last.orelse)
    return True


def _collect_global_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for statement in tree.body:
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            names.add(statement.target.id)
        elif isinstance(statement, (ast.ClassDef, ast.FunctionDef)):
            names.add(statement.name)
        elif isinstance(statement, ast.ImportFrom):
            for alias in statement.names:
                if alias.name != "*":
                    names.add(alias.asname or alias.name)
        elif isinstance(statement, ast.Import):
            for alias in statement.names:
                names.add(alias.asname or alias.name.split(".", 1)[0])
    return names


def _collect_global_string_constants(tree: ast.Module) -> dict[str, str]:
    constants: dict[str, str] = {}
    for statement in tree.body:
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        ):
            constants[statement.targets[0].id] = statement.value.value
        elif (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        ):
            constants[statement.target.id] = statement.value.value
    return constants


def _collect_global_string_container_constants(tree: ast.Module) -> dict[str, IrTuple]:
    constants: dict[str, IrTuple] = {}
    assignments: list[tuple[str, ast.expr]] = []
    for statement in tree.body:
        value: ast.expr | None = None
        target_name: str | None = None
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
        ):
            target_name = statement.targets[0].id
            value = statement.value
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            target_name = statement.target.id
            value = statement.value
        if target_name is None or value is None:
            continue
        assignments.append((target_name, value))
        if isinstance(value, (ast.List, ast.Set, ast.Tuple)):
            literal = _global_literal_container(value)
            if literal is not None:
                constants[target_name] = literal
    for target_name, value in assignments:
        if target_name in constants:
            continue
        sorted_name = _sorted_string_container_name(value)
        if sorted_name is None:
            continue
        source = constants.get(sorted_name)
        if source is None:
            continue
        sorted_elements = tuple(
            sorted(
                source.elements,
                key=_string_literal_length_sort_key,
                reverse=True,
            )
        )
        if all(isinstance(element, IrConstString) for element in sorted_elements):
            constants[target_name] = IrTuple(sorted_elements, source.type)
    return constants


def _sorted_string_container_name(value: ast.expr) -> str | None:
    call = value
    if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "cast":
        if len(call.args) != 2:
            return None
        call = call.args[1]
    if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "tuple":
        if len(call.args) != 1:
            return None
        call = call.args[0]
    if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
        return None
    if call.func.id != "sorted" or len(call.args) != 1 or not isinstance(call.args[0], ast.Name):
        return None
    key_is_len = False
    reverse_is_true = False
    for keyword in call.keywords:
        if keyword.arg == "key" and isinstance(keyword.value, ast.Name):
            key_is_len = keyword.value.id == "len"
        elif keyword.arg == "reverse" and isinstance(keyword.value, ast.Constant):
            reverse_is_true = keyword.value.value is True
        else:
            return None
    if not key_is_len or not reverse_is_true:
        return None
    return call.args[0].id


def _string_literal_length_sort_key(element: IrExpr) -> int:
    if isinstance(element, IrConstString):
        return len(element.value)
    return 0


def _global_literal_container(value: ast.List | ast.Set | ast.Tuple) -> IrTuple | None:
    elements: list[IrExpr] = []
    for element in value.elts:
        literal = _global_literal_element(element)
        if literal is None:
            return None
        elements.append(literal)
    if not elements:
        return None
    first_type = elements[0].type
    if all(element.type == first_type for element in elements):
        return IrTuple(tuple(elements), IrTupleType((first_type,)))
    return IrTuple(tuple(elements), IrTupleType(tuple(element.type for element in elements)))


def _global_literal_element(value: ast.expr) -> IrExpr | None:
    if isinstance(value, ast.Constant):
        if isinstance(value.value, str):
            return IrConstString(value.value)
        if type(value.value) is int:
            return IrConstInt(value.value, IrIntType(64, signed=True))
    if isinstance(value, (ast.List, ast.Set, ast.Tuple)):
        elements: list[IrExpr] = []
        for element in value.elts:
            literal = _global_literal_element(element)
            if literal is None:
                return None
            elements.append(literal)
        return IrTuple(tuple(elements), IrTupleType(tuple(element.type for element in elements)))
    return None


def _collect_global_record_constructor_maps(
    tree: ast.Module,
    class_types: dict[str, AotClassInfo],
) -> dict[str, IrTuple]:
    constants: dict[str, IrTuple] = {}
    for statement in tree.body:
        if (
            not isinstance(statement, ast.Assign)
            or len(statement.targets) != 1
            or not isinstance(statement.targets[0], ast.Name)
            or not isinstance(statement.value, ast.Dict)
        ):
            continue
        entries: list[tuple[str, str]] = []
        for key, value in zip(statement.value.keys, statement.value.values, strict=True):
            if (
                not isinstance(key, ast.Constant)
                or not isinstance(key.value, str)
                or not isinstance(value, ast.Name | ast.Attribute)
            ):
                entries = []
                break
            record_name = ast.unparse(value).rsplit(".", 1)[-1]
            if record_name not in class_types:
                entries = []
                break
            entries.append((key.value, record_name))
        if not entries:
            continue
        base_name = _common_record_base(
            tuple(record_name for _key, record_name in entries),
            class_types,
        )
        marker_type = IrRecordType(f"type[{base_name}]")
        pair_type = IrTupleType((IrStringType(), marker_type))
        pairs = tuple(
            IrTuple(
                (IrConstString(key), IrName(record_name, marker_type)),
                pair_type,
            )
            for key, record_name in entries
        )
        constants[statement.targets[0].id] = IrTuple(
            pairs,
            IrDictType(IrStringType(), marker_type),
        )
    return constants


def _common_record_base(
    record_names: tuple[str, ...],
    class_types: dict[str, AotClassInfo],
) -> str:
    first = record_names[0]
    candidates = (first,) + class_types[first].bases
    for candidate in candidates:
        if all(
            record_name == candidate or _record_extends(record_name, candidate, class_types)
            for record_name in record_names
        ):
            return candidate
    return "object"


def _record_constructor_type_base(type_info: IrType | None) -> str | None:
    if not isinstance(type_info, IrRecordType):
        return None
    return _record_constructor_type_base_name(type_info.name)


def _record_constructor_type_base_name(name: str) -> str | None:
    if not name.startswith("type[") or not name.endswith("]"):
        return None
    return name[5:-1]


def _collect_global_annotations(tree: ast.Module) -> dict[str, str]:
    annotations: dict[str, str] = {}
    for statement in tree.body:
        if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            annotations[statement.target.id] = annotation_name(statement.annotation)
    return annotations


def _constant_int_or_none(expr: ast.expr | None) -> int | None:
    if isinstance(expr, ast.Constant) and isinstance(expr.value, int):
        return expr.value
    if (
        isinstance(expr, ast.UnaryOp)
        and isinstance(expr.op, ast.USub)
        and isinstance(expr.operand, ast.Constant)
        and isinstance(expr.operand.value, int)
    ):
        return -expr.operand.value
    return None


def _is_string_join_call(expr: ast.Attribute) -> bool:
    return expr.attr == "join"


def _is_float_fromhex_call(expr: ast.Call) -> bool:
    return (
        isinstance(expr.func, ast.Attribute)
        and expr.func.attr == "fromhex"
        and isinstance(expr.func.value, ast.Name)
        and expr.func.value.id == "float"
    )


def _is_object_setattr_call(expr: ast.Call) -> bool:
    return (
        isinstance(expr.func, ast.Attribute)
        and expr.func.attr == "__setattr__"
        and isinstance(expr.func.value, ast.Name)
        and expr.func.value.id == "object"
    )


def _except_handler_names(handler: ast.ExceptHandler) -> tuple[str, ...]:
    if handler.type is None:
        return ()
    if isinstance(handler.type, ast.Tuple):
        return tuple(ast.unparse(item) for item in handler.type.elts)
    return (ast.unparse(handler.type),)


def _ir_source_span(node: ast.AST) -> IrSourceSpan:
    return IrSourceSpan(
        node.span.line,
        node.span.column,
        node.span.end_line,
        node.span.end_column,
    )


def _is_ellipsis_body(statements: Sequence[ast.stmt]) -> bool:
    return (
        len(statements) == 1
        and isinstance(statements[0], ast.Expr)
        and isinstance(statements[0].value, ast.Constant)
        and statements[0].value.value is Ellipsis
    )


def _is_super_call(expr: ast.expr) -> bool:
    return (
        isinstance(expr, ast.Call)
        and isinstance(expr.func, ast.Name)
        and expr.func.id == "super"
        and not expr.args
        and not expr.keywords
    )


def _is_enum_class(class_info: AotClassInfo) -> bool:
    return any(base == "Enum" or base.endswith(".Enum") for base in class_info.bases)
