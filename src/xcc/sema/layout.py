from dataclasses import dataclass
from typing import TYPE_CHECKING

from xcc.types import Type

if TYPE_CHECKING:
    from . import Analyzer


@dataclass(frozen=True)
class RecordMemberLayout:
    offset: int
    bit_offset: int | None = None
    bit_width: int | None = None
    storage_size: int | None = None


@dataclass(frozen=True)
class RecordLayout:
    size: int
    alignment: int
    members: tuple[RecordMemberLayout, ...]


def _align_to(value: int, alignment: int) -> int:
    return ((value + alignment - 1) // alignment) * alignment


def sizeof_type(a: "Analyzer", type_: Type, limit: int | None = None) -> int | None:
    if not type_.declarator_ops:
        return a._sizeof_object_base_type(type_, limit)
    kind, value = type_.declarator_ops[0]
    if kind == "ptr":
        return a._data_layout.pointer_size
    if kind == "fn":
        return None
    assert kind == "arr"
    assert isinstance(value, int)
    if value <= 0:
        return None
    element_type = Type(type_.name, declarator_ops=type_.declarator_ops[1:])
    element_size = a._sizeof_type(element_type, limit)
    if element_size is None:
        return None
    if limit is not None and element_size > limit // value:
        return limit + 1
    return element_size * value


def alignof_type(a: "Analyzer", type_: Type) -> int | None:
    if not type_.declarator_ops:
        return a._alignof_object_base_type(type_)
    kind, _ = type_.declarator_ops[0]
    if kind == "ptr":
        return a._data_layout.pointer_alignment
    if kind == "fn":
        return None
    element_type = Type(type_.name, declarator_ops=type_.declarator_ops[1:])
    return a._alignof_type(element_type)


def _member_size(a: "Analyzer", type_: Type, flexible: bool = False) -> int | None:
    size = a._sizeof_type(type_)
    return 0 if size is None and flexible and type_.is_array() else size


def _member_alignment(a: "Analyzer", record_name: str, index: int) -> int | None:
    members = a._record_members(record_name)
    assert members is not None
    member = members[index]
    alignment = a._alignof_type(member.type_)
    if alignment is None:
        return None
    if member.alignment is not None:
        alignment = max(alignment, member.alignment)
    pack = a._record_pack.get(record_name)
    return alignment if pack is None else min(alignment, pack)


def _store_bitfield_group(
    positions: list[RecordMemberLayout],
    result: list[RecordMemberLayout],
    indices: list[int],
    start: int,
    end: int,
) -> None:
    for index in indices:
        member = positions[index]
        assert member.bit_offset is not None
        result[index] = RecordMemberLayout(
            start,
            member.bit_offset - start * 8,
            member.bit_width,
            end - start,
        )


def _store_bitfield_run(
    positions: list[RecordMemberLayout],
    result: list[RecordMemberLayout],
    run: list[int],
) -> None:
    group: list[int] = []
    group_start = group_end = 0
    for index in run:
        member = positions[index]
        assert member.bit_offset is not None and member.bit_width is not None
        start = member.bit_offset // 8
        end = (member.bit_offset + member.bit_width + 7) // 8
        if group and start >= group_end:
            _store_bitfield_group(positions, result, group, group_start, group_end)
            group = []
        if not group:
            group_start = start
            group_end = end
        else:
            group_end = max(group_end, end)
        group.append(index)
    if group:
        _store_bitfield_group(positions, result, group, group_start, group_end)


def _bitfield_storage(
    positions: list[RecordMemberLayout],
) -> tuple[RecordMemberLayout, ...]:
    result = positions[:]
    run: list[int] = []

    for index, member in enumerate(positions):
        if member.bit_width is not None and member.bit_width > 0:
            run.append(index)
        else:
            _store_bitfield_run(positions, result, run)
            run = []
    _store_bitfield_run(positions, result, run)
    return tuple(result)


def record_layout(a: "Analyzer", record_name: str) -> RecordLayout | None:
    cached = a._record_layout_cache.get(record_name)
    if cached is not None:
        return cached
    members = a._record_members(record_name)
    if members is None:
        return None
    if record_name.startswith("union "):
        size = 0
        alignment = 1
        layouts: list[RecordMemberLayout] = []
        for index, member in enumerate(members):
            member_size = _member_size(a, member.type_)
            member_alignment = _member_alignment(a, record_name, index)
            if member_size is None or member_alignment is None:
                return None
            if member.bit_width == 0:
                layouts.append(RecordMemberLayout(0, bit_width=0))
                continue
            size = max(size, member_size)
            alignment = max(alignment, member_alignment)
            layouts.append(
                RecordMemberLayout(
                    0,
                    0 if member.bit_width is not None else None,
                    member.bit_width,
                    member_size if member.bit_width is not None else None,
                )
            )
        layout = RecordLayout(_align_to(size, alignment), alignment, tuple(layouts))
        a._record_layout_cache[record_name] = layout
        return layout

    pack = a._record_pack.get(record_name)
    bit_cursor = 0
    alignment = 1
    positions: list[RecordMemberLayout] = []
    for index, member in enumerate(members):
        flexible = index == len(members) - 1
        member_size = _member_size(a, member.type_, flexible)
        member_alignment = _member_alignment(a, record_name, index)
        if member_size is None or member_alignment is None:
            return None
        width = member.bit_width
        if width is not None:
            if width == 0:
                natural_alignment = a._alignof_type(member.type_)
                assert natural_alignment is not None
                bit_cursor = _align_to(bit_cursor, natural_alignment * 8)
                positions.append(RecordMemberLayout(bit_cursor // 8, bit_width=0))
                continue
            alignment = max(alignment, member_alignment)
            if pack is None:
                container_bits = member_size * 8
                alignment_bits = member_alignment * 8
                if bit_cursor % alignment_bits + width > container_bits:
                    bit_cursor = _align_to(bit_cursor, alignment_bits)
            positions.append(RecordMemberLayout(0, bit_cursor, width))
            bit_cursor += width
            continue
        alignment = max(alignment, member_alignment)
        offset = _align_to((bit_cursor + 7) // 8, member_alignment)
        positions.append(RecordMemberLayout(offset))
        bit_cursor = (offset + member_size) * 8
    layout = RecordLayout(
        _align_to((bit_cursor + 7) // 8, alignment),
        alignment,
        _bitfield_storage(positions),
    )
    a._record_layout_cache[record_name] = layout
    return layout


def offsetof_type(a: "Analyzer", type_: Type, member_path: str) -> int | None:
    offset = 0
    for name in member_path.split("."):
        found = _record_member_offset(a, type_, name)
        if found is None:
            return None
        member_offset, type_ = found
        offset += member_offset
    return offset


def _record_member_offset(
    a: "Analyzer",
    type_: Type,
    name: str,
) -> tuple[int, Type] | None:
    if type_.declarator_ops or not a._is_record_name(type_.name):
        return None
    members = a._record_members(type_.name)
    layout = record_layout(a, type_.name)
    if members is None or layout is None:
        return None
    for member, member_layout in zip(members, layout.members, strict=True):
        if member.name == name:
            if member.bit_width is not None:
                return None
            return member_layout.offset, member.type_
        if (
            member.name is None
            and member.bit_width is None
            and a._is_record_name(member.type_.name)
        ):
            found = _record_member_offset(a, member.type_, name)
            if found is not None:
                nested_offset, nested_type = found
                return member_layout.offset + nested_offset, nested_type
    return None


def sizeof_object_base_type(
    a: "Analyzer",
    type_: Type,
    limit: int | None,
) -> int | None:
    base_size = a._data_layout.scalar_size(type_.name)
    if base_size is not None:
        return base_size
    if not a._is_record_name(type_.name):
        return None
    layout = record_layout(a, type_.name)
    if layout is None:
        return None
    if limit is not None and layout.size > limit:
        return limit + 1
    return layout.size


def alignof_object_base_type(a: "Analyzer", type_: Type) -> int | None:
    base_align = a._data_layout.scalar_alignment(type_.name)
    if base_align is not None:
        return base_align
    if not a._is_record_name(type_.name):
        return None
    layout = record_layout(a, type_.name)
    return None if layout is None else layout.alignment
