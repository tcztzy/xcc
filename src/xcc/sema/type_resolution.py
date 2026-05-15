from typing import Any, cast

from xcc.ast import ArrayDecl, TypeSpec
from xcc.types import (
    BOOL,
    CHAR,
    DOUBLE,
    FLOAT,
    INT,
    INT128,
    LLONG,
    LONG,
    LONGDOUBLE,
    SHORT,
    UCHAR,
    UINT,
    UINT128,
    ULLONG,
    ULONG,
    USHORT,
    VOID,
    Type,
)

from .symbols import EnumConstSymbol, RecordMemberInfo, Scope, SemaError


def register_type_spec(analyzer: object, type_spec: TypeSpec) -> None:
    self = cast(Any, analyzer)
    if type_spec.name not in {"struct", "union"} or not type_spec.has_record_body:
        return
    spec_id = id(type_spec)
    if spec_id in self._seen_record_definitions:
        return
    self._seen_record_definitions.add(spec_id)
    seen_members: set[str] = set()
    member_types: list[RecordMemberInfo] = []
    for member in type_spec.record_members:
        member_spec = member.type_spec
        member_name = member.name
        if member_name is not None and member_name in seen_members:
            raise SemaError(f"Duplicate declaration: {member_name}")
        if member_name is not None:
            seen_members.add(member_name)
        if self._is_invalid_void_object_type(member_spec):
            raise SemaError(self._invalid_record_member_type_message("void"))
        if self._is_invalid_atomic_type_spec(member_spec):
            raise SemaError(self._invalid_record_member_type_message("atomic"))
        if self._is_function_object_type(member_spec):
            raise SemaError(self._invalid_record_member_type_message("function"))
        if self._is_invalid_incomplete_record_object_type(member_spec):
            raise SemaError(self._invalid_record_member_type_message("incomplete"))
        # Anonymous enums inside structs define their members at file scope.
        # Use the scoped-enum tracking to prevent duplicate definitions when
        # the same struct is registered multiple times (e.g. via typedef
        # expansion that re-visits the record type).
        if member_spec.name == "enum" and member_spec.enum_members:
            self._define_scoped_enum_members(member_spec, self._file_scope)
        resolved_member_type = self._resolve_type(member_spec)
        bit_width: int | None = None
        if member.bit_width_expr is not None:
            if not self._is_integer_type(resolved_member_type):
                raise SemaError("Bit-field type must be integer")
            bit_width = self._eval_int_constant_expr(member.bit_width_expr, self._file_scope)
            if bit_width is None:
                raise SemaError("Bit-field width is not integer constant")
            if bit_width < 0:
                raise SemaError("Bit-field width must be non-negative")
            max_width = self._sizeof_type(resolved_member_type)
            assert max_width is not None
            if bit_width > max_width * 8:
                raise SemaError("Bit-field width exceeds type width")
            if member_name is not None and bit_width == 0:
                raise SemaError("Named bit-field width must be greater than zero")
        natural_alignment = self._alignof_type(resolved_member_type)
        if not self._is_valid_explicit_alignment(member.alignment, natural_alignment):
            assert member.alignment is not None
            raise SemaError(
                self._invalid_alignment_message(
                    "record member declaration",
                    member.alignment,
                    natural_alignment,
                )
            )
        if (
            member_name is None
            and bit_width is None
            and not resolved_member_type.declarator_ops
            and self._is_record_name(resolved_member_type.name)
        ):
            nested_lookup = self._record_member_lookup(resolved_member_type.name)
            if nested_lookup is not None:
                for nested_name in nested_lookup:
                    if nested_name in seen_members:
                        raise SemaError(f"Duplicate declaration: {nested_name}")
                    seen_members.add(nested_name)
        member_types.append(
            RecordMemberInfo(
                member_name,
                resolved_member_type,
                member.alignment,
                bit_width,
            )
        )
    key = self._record_type_name(type_spec)
    if key in self._record_definitions:
        existing = self._record_definitions[key]
        if existing != tuple(member_types):
            raise SemaError(f"Duplicate definition: {key}")
        return
    self._record_definitions[key] = tuple(member_types)


def resolve_type(analyzer: object, type_spec: TypeSpec) -> Type:
    self = cast(Any, analyzer)
    self._register_type_spec(type_spec)
    is_unqualified_scalar = not type_spec.declarator_ops and not type_spec.qualifiers
    if type_spec.name == "int" and is_unqualified_scalar:
        return INT
    if type_spec.name == "char" and is_unqualified_scalar:
        return CHAR
    if type_spec.name == "unsigned char" and is_unqualified_scalar:
        return UCHAR
    if type_spec.name == "_Bool" and is_unqualified_scalar:
        return BOOL
    if type_spec.name == "short" and is_unqualified_scalar:
        return SHORT
    if type_spec.name == "unsigned short" and is_unqualified_scalar:
        return USHORT
    if type_spec.name == "long" and is_unqualified_scalar:
        return LONG
    if type_spec.name == "unsigned long" and is_unqualified_scalar:
        return ULONG
    if type_spec.name == "long long" and is_unqualified_scalar:
        return LLONG
    if type_spec.name == "unsigned long long" and is_unqualified_scalar:
        return ULLONG
    if type_spec.name == "__int128_t" and is_unqualified_scalar:
        return INT128
    if type_spec.name == "__uint128_t" and is_unqualified_scalar:
        return UINT128
    if type_spec.name == "float" and is_unqualified_scalar:
        return FLOAT
    if type_spec.name == "double" and is_unqualified_scalar:
        return DOUBLE
    if type_spec.name == "long double" and is_unqualified_scalar:
        return LONGDOUBLE
    if type_spec.name == "unsigned int" and is_unqualified_scalar:
        return UINT
    if type_spec.name == "void" and is_unqualified_scalar:
        return VOID
    if type_spec.name == "typeof" and type_spec.typeof_expr is not None:
        scope = self._current_scope if self._current_scope is not None else self._file_scope
        expr_type = self._analyze_expr(type_spec.typeof_expr, scope)
        if type_spec.declarator_ops:
            base = expr_type
            for kind, value in type_spec.declarator_ops:
                if kind == "ptr":
                    base = base.pointer_to()
                elif kind == "arr":
                    bound = self._resolve_array_bound(value)
                    base = base.array_of(bound)
                else:  # pragma: no cover
                    pass
            return base
        return expr_type
    if type_spec.name == "enum" and is_unqualified_scalar:
        return INT
    if type_spec.name in {"struct", "union"} and not type_spec.declarator_ops:
        return Type(self._record_type_name(type_spec), qualifiers=type_spec.qualifiers)
    resolved_ops: list[tuple[str, int | tuple[tuple[Type, ...] | None, bool]]] = []
    for kind, value in type_spec.declarator_ops:
        if kind != "fn":
            if kind == "arr":
                resolved_ops.append(("arr", self._resolve_array_bound(value)))
                continue
            assert isinstance(value, int)
            resolved_ops.append((kind, value))
            continue
        assert isinstance(value, tuple) and len(value) == 2
        resolved_params = self._resolve_function_param_types(
            cast(tuple[tuple[TypeSpec, ...] | None, bool], value)
        )
        resolved_ops.append((kind, resolved_params))
    if type_spec.name == "enum":
        base_name = "int"
    elif type_spec.name in {"struct", "union"}:
        base_name = self._record_type_name(type_spec)
    else:
        base_name = type_spec.name
    return Type(base_name, declarator_ops=tuple(resolved_ops), qualifiers=type_spec.qualifiers)


def resolve_array_bound(analyzer: object, value: object) -> int:
    self = cast(Any, analyzer)
    if isinstance(value, int):
        return value
    if not isinstance(value, ArrayDecl):
        return -1
    if value.length is None:
        return -1
    if isinstance(value.length, int):
        return value.length
    evaluated = self._eval_int_constant_expr(value.length, self._file_scope)
    if evaluated is None:
        return -1
    return evaluated


def resolve_function_param_types(
    analyzer: object,
    declarator_value: int | tuple[tuple[TypeSpec, ...] | None, bool],
) -> tuple[tuple[Type, ...] | None, bool]:
    self = cast(Any, analyzer)
    assert isinstance(declarator_value, tuple) and len(declarator_value) == 2
    param_specs, is_variadic = declarator_value
    if param_specs is None:
        if is_variadic:
            raise SemaError("Variadic function requires a prototype")
        return None, False
    params: list[Type] = []
    for param_spec in param_specs:
        if self._is_invalid_atomic_type_spec(param_spec):
            raise SemaError("Invalid parameter type: atomic")
        if self._is_invalid_void_parameter_type(param_spec):
            raise SemaError("Invalid parameter type: void")
        if self._is_invalid_incomplete_record_object_type(param_spec):
            raise SemaError("Invalid parameter type: incomplete")
        params.append(self._resolve_param_type(param_spec))
    return tuple(params), is_variadic


def resolve_param_type(analyzer: object, type_spec: TypeSpec) -> Type:
    self = cast(Any, analyzer)
    resolved = self._resolve_type(type_spec)
    return resolved.decay_parameter_type()


def define_enum_members(analyzer: object, type_spec: TypeSpec, scope: Scope) -> None:
    self = cast(Any, analyzer)
    next_value = 0
    for name, expr in type_spec.enum_members:
        value = next_value
        if expr is not None:
            value = self._eval_int_constant_expr(expr, scope)
            if value is None:
                raise SemaError("Enumerator value is not integer constant")
        scope.define(EnumConstSymbol(name, value))
        next_value = value + 1


def define_scoped_enum_members(analyzer: object, type_spec: TypeSpec, scope: Scope) -> None:
    self = cast(Any, analyzer)
    if not type_spec.enum_members:
        return
    binding = (id(scope), id(type_spec))
    if binding in self._seen_scoped_enum_definitions:
        return
    self._seen_scoped_enum_definitions.add(binding)
    self._define_enum_members(type_spec, scope)


def is_function_object_type(type_spec: TypeSpec) -> bool:
    return bool(type_spec.declarator_ops) and type_spec.declarator_ops[0][0] == "fn"


def is_invalid_atomic_type_spec(analyzer: object, type_spec: TypeSpec) -> bool:
    self = cast(Any, analyzer)
    if not type_spec.is_atomic:
        return False
    target = type_spec.atomic_target if type_spec.atomic_target is not None else type_spec
    return (
        self._is_invalid_void_object_type(target)
        or self._is_invalid_incomplete_record_object_type(target)
        or self._is_function_object_type(target)
        or (bool(target.declarator_ops) and target.declarator_ops[0][0] == "arr")
    )


def is_invalid_incomplete_record_object_type(analyzer: object, type_spec: TypeSpec) -> bool:
    self = cast(Any, analyzer)
    if type_spec.name not in {"struct", "union"}:
        return False
    if any(kind == "ptr" for kind, _ in type_spec.declarator_ops):
        return False
    if type_spec.record_members:
        return False
    if type_spec.record_tag is None:
        return True
    key = self._record_key(type_spec.name, type_spec.record_tag)
    return key not in self._record_definitions


def is_record_name(name: str) -> bool:
    return name.startswith("struct ") or name.startswith("union ")


def lookup_record_member(analyzer: object, record_type: Type, member_name: str) -> Type:
    self = cast(Any, analyzer)
    lookup = self._record_member_lookup(record_type.name)
    if lookup is None:
        raise SemaError("Member access on incomplete type")
    member = lookup.get(member_name)
    if member is not None:
        return member[0]
    raise SemaError(f"No such member: {member_name}")


def resolve_member_type(
    analyzer: object,
    base_type: Type,
    member_name: str,
    through_pointer: bool,
) -> Type:
    self = cast(Any, analyzer)
    if through_pointer:
        base_value_type = self._decay_array_value(base_type)
        record_type = base_value_type.pointee()
        if (
            record_type is None
            or record_type.declarator_ops
            or not self._is_record_name(record_type.name)
        ):
            raise SemaError("Member access on non-record pointer")
        return self._lookup_record_member(record_type, member_name)
    if base_type.declarator_ops or not self._is_record_name(base_type.name):
        raise SemaError("Member access on non-record type")
    return self._lookup_record_member(base_type, member_name)


def invalid_sizeof_operand_reason_for_type_spec(
    analyzer: object,
    type_spec: TypeSpec,
) -> str | None:
    self = cast(Any, analyzer)
    if self._is_invalid_atomic_type_spec(type_spec):
        return "atomic type"
    if self._is_invalid_void_object_type(type_spec):
        return "void type"
    if self._is_invalid_incomplete_record_object_type(type_spec):
        return "incomplete type"
    if self._is_function_object_type(type_spec):
        return "function type"
    return None


def invalid_sizeof_operand_reason_for_type(analyzer: object, type_: Type) -> str | None:
    self = cast(Any, analyzer)
    if type_ == VOID:
        return "void type"
    if type_.declarator_ops and type_.declarator_ops[0][0] == "fn":
        return "function type"
    if (
        self._is_record_name(type_.name)
        and not any(kind == "ptr" for kind, _ in type_.declarator_ops)
        and type_.name not in self._record_definitions
    ):
        return "incomplete type"
    return None


def invalid_generic_association_type_reason(
    analyzer: object,
    type_spec: TypeSpec,
) -> str | None:
    self = cast(Any, analyzer)
    sizeof_reason = self._invalid_sizeof_operand_reason_for_type_spec(type_spec)
    if sizeof_reason is not None:
        return sizeof_reason
    if self._is_variably_modified_type_spec(type_spec):
        return "variably modified type"
    return None


def describe_generic_association_type(type_spec: TypeSpec, resolved_type: Type) -> str:
    spelled_type = f"{' '.join(type_spec.qualifiers)} {type_spec.name}".strip()
    if not type_spec.declarator_ops and not type_spec.is_atomic:
        return spelled_type
    return str(resolved_type)


def is_variably_modified_type_spec(analyzer: object, type_spec: TypeSpec) -> bool:
    self = cast(Any, analyzer)
    for kind, value in type_spec.declarator_ops:
        if kind != "arr":
            continue
        if isinstance(value, int):
            if value < 0:
                return True
            continue
        if not isinstance(value, ArrayDecl):
            return True
        if value.length is None:
            return True
        if isinstance(value.length, int):
            continue
        if self._eval_int_constant_expr(value.length, self._file_scope) is None:
            return True
    return False


def is_valid_explicit_alignment(alignment: int | None, natural_alignment: int | None) -> bool:
    if alignment is None:
        return True
    if alignment <= 0 or (alignment & (alignment - 1)) != 0:
        return False
    return natural_alignment is not None and alignment >= natural_alignment
