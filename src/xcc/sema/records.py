from collections.abc import Callable

from xcc.ast import RecordMemberDecl, TypeSpec
from xcc.types import Type

from .symbols import RecordMemberInfo, SemaError

RecordDefinitions = dict[str, tuple[RecordMemberInfo, ...]]
RecordLookupCache = dict[str, tuple[tuple[RecordMemberInfo, ...], dict[str, tuple[Type, int]]]]


def record_key(kind: str, tag: str) -> str:
    return f"{kind} {tag}"


def record_type_name(
    type_spec: TypeSpec,
    anon_record_names: dict[tuple[str, tuple[RecordMemberDecl, ...]], str],
    anon_record_counter: int,
) -> tuple[str, int]:
    if type_spec.record_tag is not None:
        return record_key(type_spec.name, type_spec.record_tag), anon_record_counter
    key = (type_spec.name, type_spec.record_members)
    name = anon_record_names.get(key)
    if name is None:
        anon_record_counter += 1
        name = f"{type_spec.name} <anon:{anon_record_counter}>"
        anon_record_names[key] = name
    return name, anon_record_counter


def normalize_record_members(
    members: tuple[RecordMemberInfo, ...] | tuple[tuple[str | None, Type], ...],
) -> tuple[RecordMemberInfo, ...]:
    if all(isinstance(member, RecordMemberInfo) for member in members):
        return members  # type: ignore[return-value]
    normalized: list[RecordMemberInfo] = []
    for member in members:
        if isinstance(member, RecordMemberInfo):
            normalized.append(member)
            continue
        if isinstance(member, tuple) and len(member) == 2:
            normalized.append(RecordMemberInfo(member[0], member[1]))
            continue
        if isinstance(member, tuple) and len(member) == 3:
            normalized.append(RecordMemberInfo(member[0], member[1], member[2]))
            continue
        raise TypeError("Invalid record member")
    return tuple(normalized)


def record_members(
    definitions: RecordDefinitions,
    record_name: str,
) -> tuple[RecordMemberInfo, ...] | None:
    members = definitions.get(record_name)
    if members is None:
        return None
    normalized = normalize_record_members(members)
    if normalized is not members:
        definitions[record_name] = normalized
    return normalized


def is_anonymous_record_member(
    member: RecordMemberInfo,
    is_record_name: Callable[[str], bool],
) -> bool:
    return (
        member.name is None
        and member.bit_width is None
        and not member.type_.declarator_ops
        and is_record_name(member.type_.name)
    )


def flatten_hoisted_record_members(
    definitions: RecordDefinitions,
    record_type: Type,
    owner_index: int,
    is_record_name: Callable[[str], bool],
) -> list[tuple[str, tuple[Type, int]]]:
    nested_members = record_members(definitions, record_type.name)
    if nested_members is None:
        return []
    flattened: list[tuple[str, tuple[Type, int]]] = []
    for nested in nested_members:
        if nested.name is not None:
            flattened.append((nested.name, (nested.type_, owner_index)))
            continue
        if is_anonymous_record_member(nested, is_record_name):
            flattened.extend(
                flatten_hoisted_record_members(
                    definitions,
                    nested.type_,
                    owner_index,
                    is_record_name,
                )
            )
    return flattened


def record_member_lookup(
    definitions: RecordDefinitions,
    lookup_cache: RecordLookupCache,
    record_name: str,
    is_record_name: Callable[[str], bool],
) -> dict[str, tuple[Type, int]] | None:
    members = record_members(definitions, record_name)
    if members is None:
        return None
    cached = lookup_cache.get(record_name)
    if cached is not None and cached[0] is members:
        return cached[1]
    lookup: dict[str, tuple[Type, int]] = {}
    for index, member in enumerate(members):
        flattened: list[tuple[str, tuple[Type, int]]] = []
        if member.name is not None:
            flattened.append((member.name, (member.type_, index)))
        elif is_anonymous_record_member(member, is_record_name):
            flattened = flatten_hoisted_record_members(
                definitions,
                member.type_,
                index,
                is_record_name,
            )
        for member_name, member_info in flattened:
            if member_name in lookup:
                raise SemaError(f"Duplicate declaration: {member_name}")
            lookup[member_name] = member_info
    lookup_cache[record_name] = (members, lookup)
    return lookup
