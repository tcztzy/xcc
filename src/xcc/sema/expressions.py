from typing import Any, cast

from xcc.ast import (
    AlignofExpr,
    AssignExpr,
    BinaryExpr,
    BuiltinOffsetofExpr,
    BuiltinTypesCompatExpr,
    CallExpr,
    CastExpr,
    CharLiteral,
    CommaExpr,
    CompoundLiteralExpr,
    ConditionalExpr,
    Expr,
    ExprStmt,
    FloatLiteral,
    GenericExpr,
    Identifier,
    IntLiteral,
    LabelAddressExpr,
    MemberExpr,
    SizeofExpr,
    StatementExpr,
    StringLiteral,
    SubscriptExpr,
    UnaryExpr,
    UpdateExpr,
)
from xcc.types import CHAR, INT, ULONG, VOID, Type

from .format_checking import check_printf_format
from .symbols import EnumConstSymbol, Scope, SemaError


def analyze_expr(analyzer: object, expr: Expr, scope: Scope) -> Type:
    self = cast(Any, analyzer)
    if isinstance(expr, FloatLiteral):
        literal_type = self._parse_float_literal_type(expr.value)
        self._type_map.set(expr, literal_type)
        return literal_type
    if isinstance(expr, IntLiteral):
        parsed = self._parse_int_literal(expr.value)
        if parsed is None:
            raise SemaError("Invalid integer literal")
        literal_type = parsed[1]
        self._type_map.set(expr, literal_type)
        return literal_type
    if isinstance(expr, CharLiteral):
        self._type_map.set(expr, INT)
        return INT
    if isinstance(expr, StringLiteral):
        string_type = CHAR.pointer_to()
        self._type_map.set(expr, string_type)
        return string_type
    if isinstance(expr, Identifier):
        symbol = scope.lookup(expr.name)
        if symbol is not None:
            self._type_map.set(expr, symbol.type_)
            return symbol.type_
        signature = self._function_signatures.get(expr.name)
        if signature is None:
            raise SemaError(f"Undeclared identifier: {expr.name}")
        overloads = self._function_overloads.get(expr.name)
        if overloads is not None and len(overloads) > 1:
            self._set_overload_expr_name(expr, expr.name)
        function_type = signature.return_type.function_of(
            signature.params,
            is_variadic=signature.is_variadic,
        )
        self._type_map.set(expr, function_type)
        return function_type
    if isinstance(expr, LabelAddressExpr):
        target_type = VOID.pointer_to()
        self._type_map.set(expr, target_type)
        return target_type
    if isinstance(expr, StatementExpr):
        if self._current_return_type is None:
            raise SemaError("Statement expression outside of a function")
        inner_scope = Scope(scope)
        result_type: Type = VOID
        result_overload: str | None = None
        for statement in expr.body.statements:
            if isinstance(statement, ExprStmt):
                analyzed_type = self._analyze_expr(statement.expr, inner_scope)
                result_type = self._decay_array_value(analyzed_type)
                result_overload = self._get_overload_expr_name(statement.expr)
                continue
            self._analyze_stmt(statement, inner_scope, self._current_return_type)
            result_type = VOID
            result_overload = None
        if result_overload is not None:
            self._set_overload_expr_name(expr, result_overload)
        self._type_map.set(expr, result_type)
        return result_type
    if isinstance(expr, SubscriptExpr):
        base_type = self._analyze_expr(expr.base, scope)
        index_type = self._analyze_expr(expr.index, scope)
        if not self._is_integer_type(index_type):
            raise SemaError("Array subscript is not an integer")
        element_type = base_type.element_type()
        if element_type is None:
            element_type = base_type.pointee()
        if element_type is None:
            raise SemaError("Subscripted value is not an array or pointer")
        self._type_map.set(expr, element_type)
        return element_type
    if isinstance(expr, MemberExpr):
        base_type = self._analyze_expr(expr.base, scope)
        member_type = self._resolve_member_type(base_type, expr.member, expr.through_pointer)
        self._type_map.set(expr, member_type)
        return member_type
    if isinstance(expr, SizeofExpr):
        if expr.type_spec is not None:
            self._register_type_spec(expr.type_spec)
            self._define_scoped_enum_members(expr.type_spec, scope)
            reason = self._invalid_sizeof_operand_reason_for_type_spec(expr.type_spec)
            if reason is not None:
                raise SemaError(f"Invalid sizeof operand: {reason}")
            self._resolve_type(expr.type_spec)
        else:
            assert expr.expr is not None
            operand_type = self._analyze_expr(expr.expr, scope)
            reason = self._invalid_sizeof_operand_reason_for_type(operand_type)
            if reason is not None:
                raise SemaError(f"Invalid sizeof operand: {reason}")
        self._type_map.set(expr, INT)
        return INT
    if isinstance(expr, AlignofExpr):
        if expr.type_spec is not None:
            self._register_type_spec(expr.type_spec)
            reason = self._invalid_alignof_operand_reason_for_type_spec(expr.type_spec)
            if reason is not None:
                raise SemaError(f"Invalid alignof operand: {reason}")
            resolved = self._resolve_type(expr.type_spec)
            if self._alignof_type(resolved) is None:
                raise SemaError("Invalid alignof operand: unknown or unsupported type")
        else:
            assert expr.expr is not None
            if self._std == "c11":
                raise SemaError("Invalid alignof operand: expression form requires GNU mode")
            operand_type = self._analyze_expr(expr.expr, scope)
            reason = self._invalid_alignof_operand_reason_for_type(operand_type)
            if reason is not None:
                raise SemaError(f"Invalid alignof operand: {reason}")
            if self._alignof_type(operand_type) is None:
                raise SemaError("Invalid alignof operand: unknown or unsupported type")
        self._type_map.set(expr, INT)
        return INT
    if isinstance(expr, BuiltinOffsetofExpr):
        self._register_type_spec(expr.type_spec)
        self._resolve_type(expr.type_spec)
        self._type_map.set(expr, ULONG)
        return ULONG
    if isinstance(expr, BuiltinTypesCompatExpr):
        self._register_type_spec(expr.type1)
        self._resolve_type(expr.type1)
        self._register_type_spec(expr.type2)
        self._resolve_type(expr.type2)
        self._type_map.set(expr, INT)
        return INT
    if isinstance(expr, CastExpr):
        self._register_type_spec(expr.type_spec)
        target_type = self._resolve_type(expr.type_spec)
        if self._is_invalid_cast_target(expr.type_spec, target_type):
            raise SemaError("Cast target type is not castable")
        operand_type = self._decay_array_value(self._analyze_expr(expr.expr, scope))
        overload_name = self._get_overload_expr_name(expr.expr)
        if overload_name is not None:
            selected_signature = self._resolve_overload_for_cast(overload_name, target_type)
            if selected_signature is None:
                raise SemaError("Cast target is not compatible with overload set")
            operand_type = self._decay_array_value(
                selected_signature.return_type.function_of(
                    selected_signature.params,
                    is_variadic=selected_signature.is_variadic,
                )
            )
        if self._is_invalid_cast_operand(operand_type, target_type):
            raise SemaError("Cast operand is not castable to target type")
        self._type_map.set(expr, target_type)
        return target_type
    if isinstance(expr, CompoundLiteralExpr):
        self._register_type_spec(expr.type_spec)
        invalid_object_type = self._invalid_object_type_label(expr.type_spec)
        if invalid_object_type is not None:
            raise SemaError(
                self._invalid_object_type_for_context_message(
                    "compound literal", invalid_object_type
                )
            )
        target_type = self._resolve_type(expr.type_spec)
        self._analyze_initializer(target_type, expr.initializer, scope)
        self._type_map.set(expr, target_type)
        return target_type
    if isinstance(expr, UnaryExpr):
        operand_type = self._analyze_expr(expr.operand, scope)
        value_operand_type = self._decay_array_value(operand_type)
        if expr.op in {"+", "-"}:
            if not self._is_arithmetic_type(value_operand_type):
                message = (
                    "Unary plus operand must be arithmetic"
                    if expr.op == "+"
                    else "Unary minus operand must be arithmetic"
                )
                raise SemaError(message)
            result_type = (
                self._integer_promotion(value_operand_type)
                if self._is_integer_type(value_operand_type)
                else value_operand_type
            )
            self._type_map.set(expr, result_type)
            return result_type
        if expr.op == "~":
            if not self._is_integer_type(value_operand_type):
                raise SemaError("Bitwise not operand must be integer")
            result_type = self._integer_promotion(value_operand_type)
            self._type_map.set(expr, result_type)
            return result_type
        if expr.op == "!":
            if not self._is_scalar_type(value_operand_type):
                raise SemaError("Logical not requires scalar operand")
            self._type_map.set(expr, INT)
            return INT
        if expr.op == "&":
            if not self._is_assignable(expr.operand):
                raise SemaError("Address-of operand is not assignable")
            result = operand_type.pointer_to()
            self._type_map.set(expr, result)
            return result
        if expr.op == "*":
            pointee = value_operand_type.pointee()
            if pointee is None:
                raise SemaError("Cannot dereference non-pointer")
            self._type_map.set(expr, pointee)
            return pointee
        raise SemaError(f"Unsupported unary operator: {expr.op}")
    if isinstance(expr, UpdateExpr):
        if expr.op not in {"++", "--"}:
            raise SemaError(f"Unsupported update operator: {expr.op}")
        if isinstance(expr.operand, Identifier):
            target_symbol = scope.lookup(expr.operand.name)
            if isinstance(target_symbol, EnumConstSymbol):
                raise SemaError("Assignment target is not assignable")
        if not self._is_assignable(expr.operand):
            raise SemaError("Assignment target is not assignable")
        operand_type = self._analyze_expr(expr.operand, scope)
        if self._is_const_qualified(operand_type) and self._std == "c11":
            raise SemaError("Assignment target is not assignable")
        if operand_type.is_array():
            raise SemaError("Assignment target is not assignable")
        value_operand_type = self._decay_array_value(operand_type)
        if not self._is_integer_type(
            value_operand_type
        ) and not self._is_complete_object_pointer_type(value_operand_type):
            raise SemaError("Update operand must be integer or pointer")
        self._type_map.set(expr, operand_type)
        return operand_type
    if isinstance(expr, BinaryExpr):
        left_type = self._decay_array_value(self._analyze_expr(expr.left, scope))
        right_type = self._decay_array_value(self._analyze_expr(expr.right, scope))
        if expr.op in {"+", "-"}:
            result_type = self._analyze_additive_types(left_type, right_type, expr.op)
            if result_type is None:
                if expr.op == "+":
                    raise SemaError("Addition operands must be arithmetic or pointer/integer")
                raise SemaError(
                    "Subtraction operands must be arithmetic, pointer/integer, "
                    "or compatible pointers"
                )
            self._type_map.set(expr, result_type)
            return result_type
        if expr.op == "*":
            if not self._is_arithmetic_type(left_type):
                raise SemaError("Multiplication left operand must be arithmetic")
            if not self._is_arithmetic_type(right_type):
                raise SemaError("Multiplication right operand must be arithmetic")
            result_type = self._usual_arithmetic_conversion(left_type, right_type)
            assert result_type is not None
            self._type_map.set(expr, result_type)
            return result_type
        if expr.op == "/":
            if not self._is_arithmetic_type(left_type):
                raise SemaError("Division left operand must be arithmetic")
            if not self._is_arithmetic_type(right_type):
                raise SemaError("Division right operand must be arithmetic")
            result_type = self._usual_arithmetic_conversion(left_type, right_type)
            assert result_type is not None
            self._type_map.set(expr, result_type)
            return result_type
        if expr.op == "%":
            if not self._is_integer_type(left_type):
                raise SemaError("Modulo left operand must be integer")
            if not self._is_integer_type(right_type):
                raise SemaError("Modulo right operand must be integer")
            result_type = self._usual_arithmetic_conversion(left_type, right_type)
            assert result_type is not None and self._is_integer_type(result_type)
            self._type_map.set(expr, result_type)
            return result_type
        if expr.op in {"<<", ">>"}:
            if not self._is_integer_type(left_type):
                raise SemaError("Shift left operand must be integer")
            if not self._is_integer_type(right_type):
                raise SemaError("Shift right operand must be integer")
            result_type = self._integer_promotion(left_type)
            self._type_map.set(expr, result_type)
            return result_type
        if expr.op in {"&", "^", "|"}:
            if not self._is_integer_type(left_type):
                raise SemaError("Bitwise left operand must be integer")
            if not self._is_integer_type(right_type):
                raise SemaError("Bitwise right operand must be integer")
            result_type = self._usual_arithmetic_conversion(left_type, right_type)
            assert result_type is not None and self._is_integer_type(result_type)
            self._type_map.set(expr, result_type)
            return result_type
        if expr.op in {"<", "<=", ">", ">="}:
            if (
                self._usual_arithmetic_conversion(left_type, right_type) is None
            ) and not self._is_pointer_relational_compatible(left_type, right_type):
                raise SemaError(
                    "Relational operator requires integer or compatible object pointer operands"
                )
        elif expr.op in {"==", "!="}:
            if not self._is_scalar_type(left_type):
                raise SemaError("Equality left operand must be scalar")
            if not self._is_scalar_type(right_type):
                raise SemaError("Equality right operand must be scalar")
            if self._usual_arithmetic_conversion(left_type, right_type) is None:
                left_is_pointer = left_type.pointee() is not None
                right_is_pointer = right_type.pointee() is not None
                if left_is_pointer and right_is_pointer:
                    if not self._is_pointer_equality_compatible(
                        left_type,
                        right_type,
                    ) and not (
                        self._is_null_pointer_constant(expr.left, scope)
                        or self._is_null_pointer_constant(expr.right, scope)
                    ):
                        raise SemaError(
                            "Equality operator requires integer or compatible pointer operands"
                        )
                elif left_is_pointer:
                    if not self._is_null_pointer_constant(expr.right, scope):
                        raise SemaError(
                            "Equality operator requires integer or compatible pointer operands"
                        )
                elif right_is_pointer and not self._is_null_pointer_constant(expr.left, scope):
                    raise SemaError(
                        "Equality operator requires integer or compatible pointer operands"
                    )
        elif expr.op in {"&&", "||"}:
            if not self._is_scalar_type(left_type):
                raise SemaError("Logical left operand must be scalar")
            if not self._is_scalar_type(right_type):
                raise SemaError("Logical right operand must be scalar")
        else:
            raise SemaError(f"Unsupported binary operator: {expr.op}")
        self._type_map.set(expr, INT)
        return INT
    if isinstance(expr, ConditionalExpr):
        self._check_condition_type(self._analyze_expr(expr.condition, scope))
        then_type = self._decay_array_value(self._analyze_expr(expr.then_expr, scope))
        else_type = self._decay_array_value(self._analyze_expr(expr.else_expr, scope))
        if then_type == else_type:
            result_type = then_type
        else:
            arithmetic_result = self._usual_arithmetic_conversion(then_type, else_type)
            if arithmetic_result is not None:
                result_type = arithmetic_result
            else:
                result_type = self._conditional_pointer_result(
                    expr.then_expr,
                    then_type,
                    expr.else_expr,
                    else_type,
                    scope,
                )
                if result_type is None:
                    raise SemaError("Conditional type mismatch")
        then_overload = self._get_overload_expr_name(expr.then_expr)
        else_overload = self._get_overload_expr_name(expr.else_expr)
        if then_overload is not None and then_overload == else_overload:
            self._set_overload_expr_name(expr, then_overload)
        elif then_overload is not None or else_overload is not None:
            condition_value = self._eval_int_constant_expr(expr.condition, scope)
            if condition_value is not None:
                selected = then_overload if condition_value else else_overload
                if selected is not None:
                    self._set_overload_expr_name(expr, selected)
        self._type_map.set(expr, result_type)
        return result_type
    if isinstance(expr, GenericExpr):
        control_type = self._decay_array_value(self._analyze_expr(expr.control, scope))
        selected_expr: Expr | None = None
        default_expr: Expr | None = None
        default_association_index: int | None = None
        seen_type_associations: dict[Type, tuple[int, str, str | None]] = {}
        association_type_descriptions: list[str] = []
        for association_index, (assoc_type_spec, assoc_expr) in enumerate(
            expr.associations, start=1
        ):
            association_line: int | None = None
            association_column: int | None = None
            if assoc_type_spec is not None:
                association_line = assoc_type_spec.source_line
                association_column = assoc_type_spec.source_column
            if (
                association_line is None or association_column is None
            ) and association_index <= len(expr.association_source_locations):
                mapped_line, mapped_column = expr.association_source_locations[
                    association_index - 1
                ]
                if association_line is None:
                    association_line = mapped_line
                if association_column is None:
                    association_column = mapped_column
            if assoc_type_spec is None:
                if default_expr is not None and default_association_index is not None:
                    previous_default_location = None
                    current_default_location = None
                    if default_association_index <= len(expr.association_source_locations):
                        previous_default_location = expr.association_source_locations[
                            default_association_index - 1
                        ]
                    if association_index <= len(expr.association_source_locations):
                        current_default_location = expr.association_source_locations[
                            association_index - 1
                        ]
                    current_location_suffix = ""
                    if current_default_location is not None:
                        line, column = current_default_location
                        current_location_suffix = self._format_location_suffix(line, column)
                    location_suffix = ""
                    if previous_default_location is not None:
                        line, column = previous_default_location
                        location_suffix = self._format_location_suffix(line, column)
                    raise SemaError(
                        "Duplicate default generic association at position "
                        f"{association_index}{current_location_suffix}: previous "
                        "default was at position "
                        f"{default_association_index}{location_suffix}; only one default "
                        "association is allowed"
                    )
                default_expr = assoc_expr
                default_association_index = association_index
                self._analyze_expr(assoc_expr, scope)
                continue
            self._register_type_spec(assoc_type_spec)
            assoc_type = self._resolve_type(assoc_type_spec)
            assoc_type_label = self._describe_generic_association_type(assoc_type_spec, assoc_type)
            invalid_assoc_reason = self._invalid_generic_association_type_reason(assoc_type_spec)
            if invalid_assoc_reason is not None:
                location_suffix = self._format_location_suffix(
                    association_line,
                    association_column,
                )
                raise SemaError(
                    "Invalid generic association type at position "
                    f"{association_index} ('{assoc_type_label}')"
                    f"{location_suffix}: {invalid_assoc_reason}"
                )
            previous_assoc = seen_type_associations.get(assoc_type)
            if previous_assoc is not None:
                (
                    previous_assoc_index,
                    previous_assoc_label,
                    previous_assoc_location,
                ) = previous_assoc
                current_location_suffix = self._format_location_suffix(
                    association_line,
                    association_column,
                )
                location_suffix = ""
                if previous_assoc_location is not None:
                    location_suffix = f" at {previous_assoc_location}"
                raise SemaError(
                    "Duplicate generic association type at position "
                    f"{association_index}{current_location_suffix} ('{assoc_type_label}')"
                    ": previous compatible "
                    f"type was at position {previous_assoc_index}{location_suffix} "
                    f"('{previous_assoc_label}')"
                )
            association_location = self._format_location_details(
                association_line,
                association_column,
            )
            seen_type_associations[assoc_type] = (
                association_index,
                assoc_type_label,
                association_location,
            )
            association_description = f"'{assoc_type_label}' at position {association_index}"
            if association_location is not None:
                association_description += f" ({association_location})"
            association_type_descriptions.append(association_description)
            self._analyze_expr(assoc_expr, scope)
            if assoc_type == control_type:
                selected_expr = assoc_expr
        if selected_expr is None:
            selected_expr = default_expr
        if selected_expr is None:
            if association_type_descriptions:
                available_associations = ", ".join(association_type_descriptions)
                raise SemaError(
                    "No matching generic association for control type "
                    f"'{control_type}'; available association types: {available_associations}"
                )
            raise SemaError(f"No matching generic association for control type '{control_type}'")
        selected_type = self._type_map.require(selected_expr)
        selected_overload = self._get_overload_expr_name(selected_expr)
        if selected_overload is not None:
            self._set_overload_expr_name(expr, selected_overload)
        self._type_map.set(expr, selected_type)
        return selected_type
    if isinstance(expr, CommaExpr):
        self._analyze_expr(expr.left, scope)
        right_type = self._analyze_expr(expr.right, scope)
        right_overload = self._get_overload_expr_name(expr.right)
        if right_overload is not None:
            self._set_overload_expr_name(expr, right_overload)
        self._type_map.set(expr, right_type)
        return right_type
    if isinstance(expr, AssignExpr):
        if isinstance(expr.target, Identifier):
            target_symbol = scope.lookup(expr.target.name)
            if isinstance(target_symbol, EnumConstSymbol):
                raise SemaError("Assignment target is not assignable")
        if not self._is_assignable(expr.target):
            raise SemaError("Assignment target is not assignable")
        target_type = self._analyze_expr(expr.target, scope)
        if self._is_const_qualified(target_type) and self._std == "c11":
            raise SemaError("Assignment target is not assignable")
        value_type = self._decay_array_value(self._analyze_expr(expr.value, scope))
        if target_type.is_array():
            raise SemaError("Assignment target is not assignable")
            raise SemaError("Assignment target is not assignable")
        if expr.op == "=":
            if not self._is_assignment_expr_compatible(
                target_type,
                expr.value,
                value_type,
                scope,
            ):
                # In GNU mode, allow pointer↔integer and cross-pointer
                # assignments (matching initializer behavior).
                if self._std == "gnu11":
                    t_ptr = (target_type.declarator_ops
                             and target_type.declarator_ops[0][0] == "ptr")
                    v_ptr = (value_type.declarator_ops
                             and value_type.declarator_ops[0][0] == "ptr")
                    if not (t_ptr or v_ptr):
                        raise SemaError(
                            "Assignment value is not compatible with target type"
                        )
                else:
                    raise SemaError(
                        "Assignment value is not compatible with target type"
                    )
            self._type_map.set(expr, target_type)
            return target_type
        if expr.op in {"*=", "/="}:
            if not self._is_arithmetic_type(target_type) or not self._is_arithmetic_type(
                value_type
            ):
                raise SemaError("Compound multiplicative assignment requires arithmetic operands")
            self._type_map.set(expr, target_type)
            return target_type
        if expr.op in {"+=", "-="}:
            if self._is_arithmetic_type(target_type) and self._is_arithmetic_type(value_type):
                self._type_map.set(expr, target_type)
                return target_type
            if self._is_complete_object_pointer_type(target_type) and self._is_integer_type(
                value_type
            ):
                self._type_map.set(expr, target_type)
                return target_type
            raise SemaError(
                "Compound additive assignment requires arithmetic operands or pointer/integer"
            )
        if expr.op in {"<<=", ">>=", "%=", "&=", "^=", "|="}:
            if not self._is_integer_type(target_type) or not self._is_integer_type(value_type):
                raise SemaError(
                    "Compound bitwise/shift/modulo assignment requires integer operands"
                )
            self._type_map.set(expr, target_type)
            return target_type
        raise SemaError(f"Unsupported assignment operator: {expr.op}")
    if isinstance(expr, CallExpr):
        if isinstance(expr.callee, Identifier):
            signature = self._function_signatures.get(expr.callee.name)
            if signature is not None:
                signature = self._resolve_call_signature(
                    expr.callee.name,
                    expr.args,
                    scope,
                    default=signature,
                )
                if expr.callee.name == "printf" and expr.args:
                    check_printf_format(
                        self,
                        expr.args[0],
                        expr.args[1:],
                        scope,
                    )
                self._type_map.set(expr, signature.return_type)
                return signature.return_type
            symbol = scope.lookup(expr.callee.name)
            if symbol is None:
                raise SemaError(f"Undeclared function: {expr.callee.name}")
            callee_type = symbol.type_
        else:
            callee_type = self._analyze_expr(expr.callee, scope)
            overload_name = self._get_overload_expr_name(expr.callee)
            if overload_name is not None:
                signature = self._resolve_call_signature(
                    overload_name,
                    expr.args,
                    scope,
                    default=self._function_signatures[overload_name],
                )
                self._type_map.set(expr, signature.return_type)
                return signature.return_type
        callable_signature = self._decay_array_value(callee_type).callable_signature()
        if callable_signature is None:
            raise SemaError("Call target is not a function")
        return_type, function_params = callable_signature
        for arg in expr.args:
            self._analyze_expr(arg, scope)
        self._check_call_arguments(
            expr.args,
            function_params[0],
            function_params[1],
            None,
            scope,
        )
        if (
            isinstance(expr.callee, Identifier) and expr.callee.name == "printf" and expr.args
        ):  # pragma: no cover
            check_printf_format(
                self,
                expr.args[0],
                expr.args[1:],
                scope,
            )
        self._type_map.set(expr, return_type)
        return return_type
    node_name = type(expr).__name__
    raise SemaError(
        f"Unsupported expression node: {node_name} (internal sema bug: unexpected "
        "AST expression node)"
    )
