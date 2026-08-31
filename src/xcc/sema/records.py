from xcc.ast import TypeSpec
from xcc.types import Type

from .symbols import RecordMemberInfo, SemaError

RecordDefinitions = dict[str, tuple[RecordMemberInfo, ...]]
RecordLookupCache = dict[str, tuple[tuple[RecordMemberInfo, ...], dict[str, tuple[Type, int]]]]


def record_key(kind: str, tag: str) -> str:
    return f"{kind} {tag}"


def _is_record_name(name: str) -> bool:
    return name.startswith("struct ") or name.startswith("union ")


def anonymous_record_key(type_spec: TypeSpec) -> str:
    key = type_spec.name
    for member in type_spec.record_members:
        key = key + ":" + str(id(member))
    return key


def record_type_name(
    type_spec: TypeSpec,
    anon_record_names: dict[str, str],
    anon_record_counter: int,
) -> tuple[str, int]:
    if type_spec.record_tag is not None:
        return record_key(type_spec.name, type_spec.record_tag), anon_record_counter
    key = anonymous_record_key(type_spec)
    name = anon_record_names.get(key)
    if name is None:
        anon_record_counter += 1
        name = f"{type_spec.name} <anon:{anon_record_counter}>"
        anon_record_names[key] = name
    return name, anon_record_counter


def record_members(
    definitions: RecordDefinitions,
    record_name: str,
) -> tuple[RecordMemberInfo, ...] | None:
    return definitions.get(record_name)


def is_anonymous_record_member(member: RecordMemberInfo) -> bool:
    return (
        member.name is None
        and member.bit_width is None
        and not member.type_.declarator_ops
        and _is_record_name(member.type_.name)
    )


def flatten_hoisted_record_members(
    definitions: RecordDefinitions,
    record_type: Type,
    owner_index: int,
) -> list[tuple[str, tuple[Type, int]]]:
    nested_members = record_members(definitions, record_type.name)
    if nested_members is None:
        return []
    flattened: list[tuple[str, tuple[Type, int]]] = []
    for nested in nested_members:
        if nested.name is not None:
            flattened.append((nested.name, (nested.type_, owner_index)))
            continue
        if is_anonymous_record_member(nested):
            flattened.extend(
                flatten_hoisted_record_members(
                    definitions,
                    nested.type_,
                    owner_index,
                )
            )
    return flattened


def record_member_lookup(
    definitions: RecordDefinitions,
    lookup_cache: RecordLookupCache,
    record_name: str,
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
        elif is_anonymous_record_member(member):
            flattened = flatten_hoisted_record_members(
                definitions,
                member.type_,
                index,
            )
        for member_name, member_info in flattened:
            if member_name in lookup:
                raise SemaError(f"Duplicate declaration: {member_name}")
            lookup[member_name] = member_info
    lookup_cache[record_name] = (members, lookup)
    return lookup
