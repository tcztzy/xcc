from dataclasses import dataclass


class PreprocessorError(ValueError):
    def __init__(
        self,
        message: str,
        line: int | None = None,
        column: int | None = None,
        *,
        filename: str | None = None,
        code: str = "XCC-PP-0201",
    ) -> None:
        if line is None or column is None:
            super().__init__(message)
        else:
            location = f"{filename}:{line}:{column}" if filename is not None else f"{line}:{column}"
            super().__init__(f"{message} at {location}")
        self.line = line
        self.column = column
        self.filename = filename
        self.code = code


@dataclass(frozen=True)
class _ProcessedText:
    source: str
    line_map: tuple[tuple[str, int], ...]
    pack_changes: tuple[tuple[int, int | None], ...] = ()


@dataclass(frozen=True)
class _SourceLocation:
    filename: str
    line: int
    include_level: int = 0


class _OutputBuilder:
    _chunks: list[str]
    _line_map: list[tuple[str, int]]
    _pack_changes: list[tuple[int, int | None]]
    _newlines: int

    def __init__(self) -> None:
        self._chunks: list[str] = []
        self._line_map = []
        self._pack_changes = []
        self._newlines = 0

    def append(self, text: str, location: _SourceLocation) -> None:
        self._chunks.append(text)
        self._newlines += text.count("\n")
        if text:
            self._line_map.append((location.filename, location.line))

    def extend_processed(self, processed: _ProcessedText) -> None:
        offset = self._newlines
        self._chunks.append(processed.source)
        self._newlines += processed.source.count("\n")
        self._line_map.extend(processed.line_map)
        for line, alignment in processed.pack_changes:
            self._pack_changes.append((offset + line, alignment))

    def record_pack(self, alignment: int | None) -> None:
        self._pack_changes.append((self._newlines + 1, alignment))

    def build(self) -> _ProcessedText:
        return _ProcessedText(
            "".join(self._chunks), tuple(self._line_map), tuple(self._pack_changes)
        )


class _LogicalCursor:
    def __init__(self, filename: str, *, include_level: int = 0) -> None:
        self.filename = filename
        self.line = 1
        self.include_level = include_level

    def current(self) -> _SourceLocation:
        return _SourceLocation(self.filename, self.line, self.include_level)

    def advance(self, count: int = 1) -> None:
        self.line += count

    def rebase(self, line: int, filename: str | None) -> None:
        self.line = line
        if filename is not None:
            self.filename = filename


class _DirectiveCursor:
    _locations: tuple[_SourceLocation, ...]

    def __init__(self, cursor: _LogicalCursor, count: int) -> None:
        self._locations = tuple(
            _SourceLocation(cursor.filename, cursor.line + index) for index in range(count)
        )

    def line_location(self, index: int) -> _SourceLocation:
        return self._locations[index]

    def first_location(self) -> _SourceLocation:
        return self._locations[0]

    def all_locations(self) -> tuple[_SourceLocation, ...]:
        return self._locations
