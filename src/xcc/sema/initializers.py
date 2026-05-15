from xcc.ast import DesignatorRange, Expr, InitList, StringLiteral
from xcc.types import Type

from .symbols import Scope, SemaError


def is_initializer_compatible(
    analyzer: object,
    target_type: Type,
    init_expr: Expr,
    init_type: Type,
    scope: Scope,
) -> bool:
    if analyzer._is_char_array_string_initializer(target_type, init_expr):  # type: ignore[attr-defined]
        return True
    if analyzer._is_assignment_expr_compatible(target_type, init_expr, init_type, scope):  # type: ignore[attr-defined]
        return True
    return False


def analyze_initializer(
    analyzer: object,
    target_type: Type,
    initializer: Expr | InitList,
    scope: Scope,
) -> None:
    if isinstance(initializer, InitList):
        analyzer._analyze_initializer_list(target_type, initializer, scope)  # type: ignore[attr-defined]
        return
    init_type = analyzer._decay_array_value(analyzer._analyze_expr(initializer, scope))  # type: ignore[attr-defined]
    if analyzer._is_initializer_compatible(target_type, initializer, init_type, scope):  # type: ignore[attr-defined]
        return
    # Scalar-to-aggregate: a scalar can initialize a struct/union/array
    # by initializing its first element / member (C11 6.7.9p13, 6.7.9p17).
    # Only try this when the direct compatibility check fails.
    if analyzer._is_record_name(target_type.name) and not target_type.declarator_ops:  # type: ignore[attr-defined]
        members = analyzer._record_members(target_type.name)  # type: ignore[attr-defined]
        if members and members[0].name is not None:
            analyzer._analyze_initializer(members[0].type_, initializer, scope)  # type: ignore[attr-defined]
            return
    if target_type.is_array():
        element_type = target_type.element_type()
        if element_type is not None:
            analyzer._analyze_initializer(element_type, initializer, scope)  # type: ignore[attr-defined]
            return
    raise SemaError("Initializer type mismatch")


def analyze_initializer_list(
    analyzer: object,
    target_type: Type,
    init: InitList,
    scope: Scope,
) -> None:
    if target_type.is_array():
        analyzer._analyze_array_initializer_list(target_type, init, scope)  # type: ignore[attr-defined]
        return
    if analyzer._is_record_name(target_type.name) and not target_type.declarator_ops:  # type: ignore[attr-defined]
        analyzer._analyze_record_initializer_list(target_type, init, scope)  # type: ignore[attr-defined]
        return
    if len(init.items) != 1:
        raise SemaError("Scalar initializer list must contain exactly one item")
    item = init.items[0]
    if item.designators:
        raise SemaError("Scalar initializer list item cannot be designated")
    analyzer._analyze_initializer(target_type, item.initializer, scope)  # type: ignore[attr-defined]


def analyze_array_initializer_list(
    analyzer: object,
    target_type: Type,
    init: InitList,
    scope: Scope,
) -> None:
    assert target_type.declarator_ops and target_type.declarator_ops[0][0] == "arr"
    _, length_value = target_type.declarator_ops[0]
    assert isinstance(length_value, int)
    length = length_value
    if length < 0:
        length = _infer_incomplete_array_length(analyzer, init, scope)
    element_type = target_type.element_type()
    assert element_type is not None
    next_index = 0
    for item in init.items:
        if item.designators:
            kind, value = item.designators[0]
            if kind == "range":
                assert isinstance(value, DesignatorRange)
                low = analyzer._eval_initializer_index(value.low, scope)  # type: ignore[attr-defined]
                high = analyzer._eval_initializer_index(value.high, scope)  # type: ignore[attr-defined]
                if low < 0 or high >= length or low > high:
                    raise SemaError("Initializer range out of bounds")
                for _i in range(low, high + 1):
                    analyzer._analyze_designated_initializer(  # type: ignore[attr-defined]
                        element_type,
                        item.designators[1:],
                        item.initializer,
                        scope,
                    )
                next_index = high + 1
                continue
            if kind != "index":
                raise SemaError("Array initializer designator must use index")
            assert isinstance(value, Expr)
            index = analyzer._eval_initializer_index(value, scope)  # type: ignore[attr-defined]
            if index < 0 or index >= length:
                raise SemaError("Initializer index out of range")
            analyzer._analyze_designated_initializer(  # type: ignore[attr-defined]
                element_type,
                item.designators[1:],
                item.initializer,
                scope,
            )
            next_index = index + 1
            continue
        if next_index >= length:
            if analyzer._excess_init_ok:  # type: ignore[attr-defined]
                continue
            raise SemaError("Initializer index out of range")
        analyzer._analyze_initializer(element_type, item.initializer, scope)  # type: ignore[attr-defined]
        next_index += 1


def _infer_incomplete_array_length(analyzer: object, init: InitList, scope: Scope) -> int:
    max_index = 0
    next_idx = 0
    for item in init.items:
        if item.designators:
            kind, value = item.designators[0]
            if kind == "index":
                assert isinstance(value, Expr)
                idx = analyzer._eval_initializer_index(value, scope)  # type: ignore[attr-defined]
                next_idx = idx + 1
            elif kind == "range":
                assert isinstance(value, DesignatorRange)
                high = analyzer._eval_initializer_index(value.high, scope)  # type: ignore[attr-defined]
                next_idx = high + 1
            else:
                next_idx += 1
        else:
            next_idx += 1
        max_index = max(max_index, next_idx)
    return max_index


def analyze_record_initializer_list(
    analyzer: object,
    target_type: Type,
    init: InitList,
    scope: Scope,
) -> None:
    all_members = analyzer._record_members(target_type.name)  # type: ignore[attr-defined]
    members = None if all_members is None else tuple(m for m in all_members if m.name is not None)
    if members is None or not members:
        raise SemaError("Initializer type mismatch")
    is_union = target_type.name.startswith("union ")
    next_member = 0
    initialized_union = False
    for item in init.items:
        if item.designators:
            if is_union and initialized_union:
                raise SemaError("Initializer type mismatch")
            kind, value = item.designators[0]
            if kind != "member" or not isinstance(value, str):
                raise SemaError("Record initializer designator must use member")
            member_type, member_index = analyzer._lookup_initializer_member(target_type, value)  # type: ignore[attr-defined]
            analyzer._analyze_designated_initializer(  # type: ignore[attr-defined]
                member_type,
                item.designators[1:],
                item.initializer,
                scope,
            )
            if is_union:
                initialized_union = True
            else:
                next_member = member_index + 1
            continue
        if is_union:
            if initialized_union:
                raise SemaError("Initializer type mismatch")
            analyzer._analyze_initializer(members[0].type_, item.initializer, scope)  # type: ignore[attr-defined]
            initialized_union = True
            continue
        if next_member >= len(members):
            if analyzer._excess_init_ok:  # type: ignore[attr-defined]
                continue
            raise SemaError("Initializer type mismatch")
        analyzer._analyze_initializer(members[next_member].type_, item.initializer, scope)  # type: ignore[attr-defined]
        next_member += 1


def analyze_designated_initializer(
    analyzer: object,
    target_type: Type,
    designators: tuple[tuple[str, Expr | str], ...],
    initializer: Expr | InitList,
    scope: Scope,
) -> None:
    if not designators:
        analyzer._analyze_initializer(target_type, initializer, scope)  # type: ignore[attr-defined]
        return
    kind, value = designators[0]
    if kind == "index":
        if not target_type.is_array():
            raise SemaError("Initializer type mismatch")
        assert isinstance(value, Expr)
        index = analyzer._eval_initializer_index(value, scope)  # type: ignore[attr-defined]
        assert target_type.declarator_ops
        _, length_value = target_type.declarator_ops[0]
        assert isinstance(length_value, int)
        if index < 0 or index >= length_value:
            raise SemaError("Initializer index out of range")
        element_type = target_type.element_type()
        assert element_type is not None
        analyzer._analyze_designated_initializer(  # type: ignore[attr-defined]
            element_type,
            designators[1:],
            initializer,
            scope,
        )
        return
    if kind != "member" or not isinstance(value, str):
        raise SemaError("Initializer type mismatch")
    member_type, _ = analyzer._lookup_initializer_member(target_type, value)  # type: ignore[attr-defined]
    analyzer._analyze_designated_initializer(  # type: ignore[attr-defined]
        member_type,
        designators[1:],
        initializer,
        scope,
    )


def lookup_initializer_member(
    analyzer: object,
    record_type: Type,
    member_name: str,
) -> tuple[Type, int]:
    if record_type.declarator_ops or not analyzer._is_record_name(record_type.name):  # type: ignore[attr-defined]
        raise SemaError("Initializer type mismatch")
    lookup = analyzer._record_member_lookup(record_type.name)  # type: ignore[attr-defined]
    if lookup is None:
        raise SemaError("Initializer type mismatch")
    member = lookup.get(member_name)
    if member is not None:
        return member
    raise SemaError(f"No such member: {member_name}")


def eval_initializer_index(analyzer: object, expr: Expr, scope: Scope) -> int:
    value = analyzer._eval_int_constant_expr(expr, scope)  # type: ignore[attr-defined]
    if value is None:
        raise SemaError("Initializer index is not integer constant")
    return value


def is_char_array_string_initializer(
    analyzer: object,
    target_type: Type,
    init_expr: Expr,
) -> bool:
    if not target_type.is_array() or not isinstance(init_expr, StringLiteral):
        return False
    elem = target_type.element_type()
    if elem is None or elem.name != "char" or elem.declarator_ops:
        return False
    required_length = analyzer._string_literal_required_length(init_expr.value)  # type: ignore[attr-defined]
    if required_length is None:
        return False
    assert target_type.declarator_ops
    _, value = target_type.declarator_ops[0]
    assert isinstance(value, int)
    if value < 0:
        return True
    return required_length <= value
