from xcc.ast import DesignatorRange, Expr, InitList, StringLiteral
from xcc.types import Type

from .symbols import RecordMemberInfo, Scope, SemaError


def is_initializer_compatible(
    analyzer: object,
    target_type: Type,
    init_expr: Expr,
    init_type: Type,
    scope: Scope,
) -> bool:
    if analyzer._is_char_array_string_initializer(target_type, init_expr):  # type: ignore
        return True
    if analyzer._is_void_pointer_type(target_type) and init_type.callable_signature() is not None:  # type: ignore
        return True
    if target_type.callable_signature() is not None and analyzer._is_void_pointer_type(init_type):  # type: ignore
        return True
    return analyzer._is_assignment_expr_compatible(  # type: ignore
        target_type,
        init_expr,
        init_type,
        scope,
    )


def analyze_initializer(
    analyzer: object,
    target_type: Type,
    initializer: Expr | InitList,
    scope: Scope,
) -> None:
    if isinstance(initializer, InitList):
        analyzer._analyze_initializer_list(target_type, initializer, scope)  # type: ignore
        return
    init_type = analyzer._decay_array_value(analyzer._analyze_expr(initializer, scope))  # type: ignore
    if analyzer._is_initializer_compatible(target_type, initializer, init_type, scope):  # type: ignore
        return
    # Scalar-to-aggregate: a scalar can initialize a struct/union/array
    # by initializing its first element / member (C11 6.7.9p13, 6.7.9p17).
    # Only try this when the direct compatibility check fails.
    if analyzer._is_record_name(target_type.name) and not target_type.declarator_ops:  # type: ignore
        members = analyzer._record_members(target_type.name)  # type: ignore
        if members:
            analyzer._analyze_initializer(members[0].type_, initializer, scope)  # type: ignore
            return
    if target_type.is_array():
        element_type = target_type.element_type()
        if element_type is not None:
            analyzer._analyze_initializer(element_type, initializer, scope)  # type: ignore
            return
    # In GNU mode, allow pointer↔integer and cross-pointer initializer
    # conversions (GCC -fpermissive).  At least one side must be a pointer.
    if getattr(analyzer, "_std", "c11") == "gnu11" and _either_is_pointer(target_type, init_type):
        return
    raise SemaError("Initializer type mismatch")


def _either_is_pointer(t: Type, i: Type) -> bool:
    """True if either type's first declarator op is 'ptr'."""
    return bool(
        (t.declarator_ops and t.declarator_ops[0][0] == "ptr")
        or (i.declarator_ops and i.declarator_ops[0][0] == "ptr")
    )


def analyze_initializer_list(
    analyzer: object,
    target_type: Type,
    init: InitList,
    scope: Scope,
) -> None:
    if target_type.is_array():
        analyzer._analyze_array_initializer_list(target_type, init, scope)  # type: ignore
        return
    if analyzer._is_record_name(target_type.name) and not target_type.declarator_ops:  # type: ignore
        analyzer._analyze_record_initializer_list(target_type, init, scope)  # type: ignore
        return
    if len(init.items) != 1:
        raise SemaError("Scalar initializer list must contain exactly one item")
    item = init.items[0]
    if item.designators:
        raise SemaError("Scalar initializer list item cannot be designated")
    analyzer._analyze_initializer(target_type, item.initializer, scope)  # type: ignore


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
        length = infer_incomplete_array_length(analyzer, init, scope)
    element_type = target_type.element_type()
    assert element_type is not None
    next_index = 0
    for item in init.items:
        if item.designators:
            kind, value = item.designators[0]
            if kind == "range":
                assert isinstance(value, DesignatorRange)
                low = analyzer._eval_initializer_index(value.low, scope)  # type: ignore
                high = analyzer._eval_initializer_index(value.high, scope)  # type: ignore
                if low < 0 or high >= length or low > high:
                    raise SemaError("Initializer range out of bounds")
                for _i in range(low, high + 1):
                    analyzer._analyze_designated_initializer(  # type: ignore
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
            index = analyzer._eval_initializer_index(value, scope)  # type: ignore
            if index < 0 or index >= length:
                raise SemaError("Initializer index out of range")
            analyzer._analyze_designated_initializer(  # type: ignore
                element_type,
                item.designators[1:],
                item.initializer,
                scope,
            )
            next_index = index + 1
            continue
        if next_index >= length:
            if analyzer._excess_init_ok:  # type: ignore
                continue
            raise SemaError("Initializer index out of range")
        analyzer._analyze_initializer(element_type, item.initializer, scope)  # type: ignore
        next_index += 1


def infer_incomplete_array_length(analyzer: object, init: InitList, scope: Scope) -> int:
    max_index = 0
    next_idx = 0
    for item in init.items:
        if item.designators:
            kind, value = item.designators[0]
            if kind == "index":
                assert isinstance(value, Expr)
                idx = analyzer._eval_initializer_index(value, scope)  # type: ignore
                next_idx = idx + 1
            elif kind == "range":
                assert isinstance(value, DesignatorRange)
                high = analyzer._eval_initializer_index(value.high, scope)  # type: ignore
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
    all_members = analyzer._record_members(target_type.name)  # type: ignore
    if all_members is None:
        raise SemaError("Initializer type mismatch")
    if not any(_record_member_takes_initializer(analyzer, member) for member in all_members):
        # In GNU mode, empty/anonymous struct init is silently accepted.
        if getattr(analyzer, "_std", "c11") == "gnu11":
            return
        raise SemaError("Initializer type mismatch")
    is_union = target_type.name.startswith("union ")
    next_member = 0
    initialized_union = False
    initialized_union_member: str | None = None
    for item in init.items:
        if item.designators:
            kind, value = item.designators[0]
            if kind != "member" or not isinstance(value, str):
                raise SemaError("Record initializer designator must use member")
            if is_union and initialized_union and initialized_union_member != value:
                raise SemaError("Initializer type mismatch")
            member_type, member_index = analyzer._lookup_initializer_member(target_type, value)  # type: ignore
            analyzer._analyze_designated_initializer(  # type: ignore
                member_type,
                item.designators[1:],
                item.initializer,
                scope,
            )
            if is_union:
                initialized_union = True
                initialized_union_member = value
            else:
                next_member = member_index + 1
            continue
        if is_union:
            if initialized_union:
                raise SemaError("Initializer type mismatch")
            member_index = _next_initializable_record_member_index(
                analyzer,
                all_members,
                0,
            )
            if member_index is None:
                raise SemaError("Initializer type mismatch")
            analyzer._analyze_initializer(  # type: ignore
                all_members[member_index].type_,
                item.initializer,
                scope,
            )
            initialized_union = True
            continue
        member_index = _next_initializable_record_member_index(
            analyzer,
            all_members,
            next_member,
        )
        if member_index is None:
            if analyzer._excess_init_ok:  # type: ignore
                continue
            # In GNU mode, excess initializer elements are silently ignored.
            if getattr(analyzer, "_std", "c11") == "gnu11":
                continue
            raise SemaError("Initializer type mismatch")
        analyzer._analyze_initializer(all_members[member_index].type_, item.initializer, scope)  # type: ignore
        next_member = member_index + 1


def _record_member_takes_initializer(
    analyzer: object,
    member: RecordMemberInfo,
) -> bool:
    return bool(
        getattr(member, "name", None) is not None or analyzer._is_anonymous_record_member(member)  # type: ignore
    )


def _next_initializable_record_member_index(
    analyzer: object,
    members: tuple[RecordMemberInfo, ...],
    start: int,
) -> int | None:
    for index in range(start, len(members)):
        if _record_member_takes_initializer(analyzer, members[index]):
            return index
    return None


def analyze_designated_initializer(
    analyzer: object,
    target_type: Type,
    designators: tuple[tuple[str, Expr | str], ...],
    initializer: Expr | InitList,
    scope: Scope,
) -> None:
    if not designators:
        analyzer._analyze_initializer(target_type, initializer, scope)  # type: ignore
        return
    kind, value = designators[0]
    if kind == "index":
        if not target_type.is_array():
            raise SemaError("Initializer type mismatch")
        assert isinstance(value, Expr)
        index = analyzer._eval_initializer_index(value, scope)  # type: ignore
        assert target_type.declarator_ops
        _, length_value = target_type.declarator_ops[0]
        assert isinstance(length_value, int)
        if index < 0 or index >= length_value:
            raise SemaError("Initializer index out of range")
        element_type = target_type.element_type()
        assert element_type is not None
        analyzer._analyze_designated_initializer(  # type: ignore
            element_type,
            designators[1:],
            initializer,
            scope,
        )
        return
    if kind != "member" or not isinstance(value, str):
        raise SemaError("Initializer type mismatch")
    member_type, _ = analyzer._lookup_initializer_member(target_type, value)  # type: ignore
    analyzer._analyze_designated_initializer(  # type: ignore
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
    if record_type.declarator_ops or not analyzer._is_record_name(record_type.name):  # type: ignore
        raise SemaError("Initializer type mismatch")
    lookup = analyzer._record_member_lookup(record_type.name)  # type: ignore
    if lookup is None:
        raise SemaError("Initializer type mismatch")
    member = lookup.get(member_name)
    if member is not None:
        return member
    raise SemaError(f"No such member: {member_name}")


def eval_initializer_index(analyzer: object, expr: Expr, scope: Scope) -> int:
    value = analyzer._eval_int_constant_expr(expr, scope)  # type: ignore
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
    if init_expr.value.startswith(('L"', 'u"', 'U"')):
        return False
    elem = target_type.element_type()
    if elem is None or elem.name not in {"char", "unsigned char"} or elem.declarator_ops:
        return False
    body = analyzer._string_literal_body(init_expr.value)  # type: ignore
    if body is None:
        return False
    data_length = len(analyzer._decode_escaped_units(body))  # type: ignore
    assert target_type.declarator_ops
    _, value = target_type.declarator_ops[0]
    assert isinstance(value, int)
    if value < 0:
        return True
    return data_length <= value
