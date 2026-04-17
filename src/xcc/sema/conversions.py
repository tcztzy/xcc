from xcc.ast import CastExpr, Expr
from xcc.types import INT, VOID, Type

from .symbols import Scope


def is_complete_object_pointer_type(analyzer: object, type_: Type) -> bool:
    pointee = type_.pointee()
    if pointee is None:
        return False
    if pointee.name == VOID.name:
        return False
    if pointee.declarator_ops and pointee.declarator_ops[0][0] == "fn":
        return False
    return not (
        analyzer._is_record_name(pointee.name)  # type: ignore[attr-defined]
        and analyzer._record_members(pointee.name) is None  # type: ignore[attr-defined]
    )


def is_null_pointer_constant(analyzer: object, expr: Expr, scope: Scope) -> bool:
    if analyzer._eval_int_constant_expr(expr, scope) == 0:  # type: ignore[attr-defined]
        return True
    if not isinstance(expr, CastExpr):
        return False
    cast_type = analyzer._type_map.get(expr)  # type: ignore[attr-defined]
    if cast_type is None:
        cast_type = analyzer._resolve_type(expr.type_spec)  # type: ignore[attr-defined]
    return analyzer._is_void_pointer_type(cast_type) and analyzer._is_null_pointer_constant(  # type: ignore[attr-defined]
        expr.expr, scope
    )


def is_assignment_expr_compatible(
    analyzer: object,
    target_type: Type,
    value_expr: Expr,
    value_type: Type,
    scope: Scope,
) -> bool:
    return analyzer._is_assignment_compatible(target_type, value_type) or (  # type: ignore[attr-defined]
        target_type.pointee() is not None and analyzer._is_null_pointer_constant(value_expr, scope)  # type: ignore[attr-defined]
    )


def is_scalar_type(analyzer: object, type_: Type) -> bool:
    return analyzer._is_arithmetic_type(type_) or (  # type: ignore[attr-defined]
        bool(type_.declarator_ops) and type_.declarator_ops[0][0] == "ptr"
    )


def analyze_additive_types(
    analyzer: object,
    left_type: Type,
    right_type: Type,
    op: str,
) -> Type | None:
    arithmetic_result = analyzer._usual_arithmetic_conversion(left_type, right_type)  # type: ignore[attr-defined]
    if arithmetic_result is not None:
        return arithmetic_result
    if op == "+":
        if analyzer._is_complete_object_pointer_type(left_type) and analyzer._is_integer_type(  # type: ignore[attr-defined]
            right_type
        ):
            return left_type
        if analyzer._is_complete_object_pointer_type(right_type) and analyzer._is_integer_type(  # type: ignore[attr-defined]
            left_type
        ):
            return right_type
        return None
    if analyzer._is_complete_object_pointer_type(left_type) and analyzer._is_integer_type(  # type: ignore[attr-defined]
        right_type
    ):
        return left_type
    if analyzer._is_compatible_nonvoid_object_pointer_pair(left_type, right_type):  # type: ignore[attr-defined]
        return INT
    return None


def is_compatible_nonvoid_object_pointer_pair(
    analyzer: object,
    left_type: Type,
    right_type: Type,
) -> bool:
    left_pointee = left_type.pointee()
    right_pointee = right_type.pointee()
    if left_pointee is None or right_pointee is None:
        return False
    if left_pointee.name == VOID.name or right_pointee.name == VOID.name:
        return False
    if left_pointee.declarator_ops and left_pointee.declarator_ops[0][0] == "fn":
        return False
    if right_pointee.declarator_ops and right_pointee.declarator_ops[0][0] == "fn":
        return False
    if analyzer._has_nested_pointer_qualifier_mismatch(left_pointee, right_pointee):  # type: ignore[attr-defined]
        return False
    return analyzer._is_compatible_pointee_type(left_pointee, right_pointee)  # type: ignore[attr-defined]


def is_pointer_relational_compatible(
    analyzer: object,
    left_type: Type,
    right_type: Type,
) -> bool:
    return analyzer._is_compatible_nonvoid_object_pointer_pair(left_type, right_type)  # type: ignore[attr-defined]


def is_pointer_equality_compatible(
    analyzer: object,
    left_type: Type,
    right_type: Type,
) -> bool:
    return analyzer._is_assignment_compatible(  # type: ignore[attr-defined]
        left_type, right_type
    ) or analyzer._is_assignment_compatible(  # type: ignore[attr-defined]
        right_type,
        left_type,
    )


def conditional_pointer_result(
    analyzer: object,
    then_expr: Expr,
    then_type: Type,
    else_expr: Expr,
    else_type: Type,
    scope: Scope,
) -> Type | None:
    then_pointee = then_type.pointee()
    else_pointee = else_type.pointee()
    if then_pointee is not None and analyzer._is_null_pointer_constant(  # type: ignore[attr-defined]
        else_expr, scope
    ):
        return then_type
    if else_pointee is not None and analyzer._is_null_pointer_constant(  # type: ignore[attr-defined]
        then_expr, scope
    ):
        return else_type
    if then_pointee is not None and else_pointee is not None:
        if analyzer._is_compatible_pointee_type(  # type: ignore[attr-defined]
            then_pointee,
            else_pointee,
        ) and not analyzer._has_nested_pointer_qualifier_mismatch(  # type: ignore[attr-defined]
            then_pointee, else_pointee
        ):
            return Type(
                then_type.name,
                declarator_ops=then_type.declarator_ops,
                qualifiers=analyzer._merged_qualifiers(then_pointee, else_pointee),  # type: ignore[attr-defined]
            )
        if analyzer._is_void_pointer_type(then_type) and analyzer._is_object_pointer_type(  # type: ignore[attr-defined]
            else_type
        ):
            return Type(
                VOID.name,
                declarator_ops=then_type.declarator_ops,
                qualifiers=analyzer._merged_qualifiers(then_pointee, else_pointee),  # type: ignore[attr-defined]
            )
        if analyzer._is_void_pointer_type(else_type) and analyzer._is_object_pointer_type(  # type: ignore[attr-defined]
            then_type
        ):
            return Type(
                VOID.name,
                declarator_ops=else_type.declarator_ops,
                qualifiers=analyzer._merged_qualifiers(then_pointee, else_pointee),  # type: ignore[attr-defined]
            )
        return None
    return None
