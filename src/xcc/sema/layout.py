from xcc.types import Type


def _align_to(value: int, alignment: int) -> int:
    """Round *value* up to the nearest multiple of *alignment*."""
    return ((value + alignment - 1) // alignment) * alignment


POINTER_SIZE = 8
BASE_TYPE_SIZES: dict[str, int] = {
    "_Bool": 1,
    "char": 1,
    "unsigned char": 1,
    "short": 2,
    "unsigned short": 2,
    "int": 4,
    "unsigned int": 4,
    "long": 8,
    "unsigned long": 8,
    "long long": 8,
    "unsigned long long": 8,
    "__int128": 16,
    "__uint128": 16,
    "unsigned __int128": 16,
    "__int128_t": 16,
    "__uint128_t": 16,
    "float": 4,
    "double": 8,
    "long double": 16,
}
BASE_TYPE_ALIGNMENTS: dict[str, int] = dict(BASE_TYPE_SIZES)


def sizeof_type(analyzer: object, type_: Type, limit: int | None = None) -> int | None:
    if not type_.declarator_ops:
        return analyzer._sizeof_object_base_type(type_, limit)  # type: ignore
    kind, value = type_.declarator_ops[0]
    if kind == "ptr":
        return POINTER_SIZE
    if kind == "fn":
        return None
    assert kind == "arr"
    assert isinstance(value, int)
    if value <= 0:
        return None
    element_type = Type(type_.name, declarator_ops=type_.declarator_ops[1:])
    element_size = analyzer._sizeof_type(element_type, limit)  # type: ignore
    if element_size is None:
        return None
    if limit is not None and element_size > limit // value:
        return limit + 1
    return element_size * value


def alignof_type(analyzer: object, type_: Type) -> int | None:
    if not type_.declarator_ops:
        return analyzer._alignof_object_base_type(type_)  # type: ignore
    kind, _ = type_.declarator_ops[0]
    if kind == "ptr":
        return POINTER_SIZE
    if kind == "fn":
        return None
    element_type = Type(type_.name, declarator_ops=type_.declarator_ops[1:])
    return analyzer._alignof_type(element_type)  # type: ignore


def sizeof_object_base_type(
    analyzer: object,
    type_: Type,
    limit: int | None,
) -> int | None:
    base_size = BASE_TYPE_SIZES.get(type_.name)
    if base_size is not None:
        return base_size
    if not analyzer._is_record_name(type_.name):  # type: ignore
        return None
    members = analyzer._record_members(type_.name)  # type: ignore
    if members is None:
        return None
    if type_.name.startswith("struct "):
        # Determine effective pack alignment for this record.
        pack = analyzer._record_pack.get(type_.name)  # type: ignore
        total = 0
        bit_unit_offset = 0
        bit_unit_size = 0
        max_align = 1
        for member in members:
            member_size = analyzer._sizeof_type(member.type_, None)  # type: ignore
            if member_size is None:
                return None
            member_align = analyzer._alignof_type(member.type_) or member_size  # type: ignore
            # Apply #pragma pack: clamp alignment to pack value.
            if pack is not None and pack < member_align:
                member_align = pack
            if member_align > max_align:
                max_align = member_align
            if member.bit_width is not None:
                # Bitfield: pack into current storage unit if it fits.
                if bit_unit_size == 0 or bit_unit_offset + member.bit_width > member_size * 8:
                    # Start a new storage unit.
                    bit_unit_offset = 0
                    bit_unit_size = member_size
                    # Align the storage unit.
                    aligned = _align_to(total, member_align)
                    if aligned > total:
                        total = aligned
                    total += member_size
                bit_unit_offset += member.bit_width
            else:
                bit_unit_offset = 0
                bit_unit_size = 0
                # Align and add regular member.
                aligned = _align_to(total, member_align)
                if aligned > total:
                    total = aligned
                if limit is not None and total + member_size > limit:
                    return limit + 1
                total += member_size
        # Trailing padding to align the struct.
        total = _align_to(total, max_align)
        if limit is not None and total > limit:
            return limit + 1
        return total
    largest = 0
    for member in members:
        member_size = analyzer._sizeof_type(member.type_, limit)  # type: ignore
        if member_size is None:
            return None
        if member_size > largest:
            largest = member_size
        if limit is not None and largest > limit:
            return limit + 1
    return largest


def alignof_object_base_type(analyzer: object, type_: Type) -> int | None:
    base_align = BASE_TYPE_ALIGNMENTS.get(type_.name)
    if base_align is not None:
        return base_align
    if not analyzer._is_record_name(type_.name):  # type: ignore
        return None
    members = analyzer._record_members(type_.name)  # type: ignore
    if members is None:
        return None
    largest = 1
    for member in members:
        member_align = analyzer._alignof_type(member.type_)  # type: ignore
        if member_align is None:
            return None
        if member.alignment is not None and member.alignment > member_align:
            member_align = member.alignment
        if member_align > largest:
            largest = member_align
    return largest
