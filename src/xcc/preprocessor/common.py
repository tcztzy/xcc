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


@dataclass(frozen=True)
class _SourceLocation:
    filename: str
    line: int
    include_level: int = 0


def _location_tuple(location: _SourceLocation) -> tuple[str, int]:
    return location.filename, location.line


class _LineMapBuilder:
    def __init__(self) -> None:
        self._entries: list[tuple[str, int]] = []

    def append_line(self, text: str, location: _SourceLocation) -> None:
        if text:
            self._entries.append(_location_tuple(location))

    def extend(self, mappings: tuple[tuple[str, int], ...]) -> None:
        self._entries.extend(mappings)

    def build(self) -> tuple[tuple[str, int], ...]:
        return tuple(self._entries)


class _OutputBuilder:
    def __init__(self) -> None:
        self._chunks: list[str] = []
        self._line_map = _LineMapBuilder()

    def append(self, text: str, location: _SourceLocation) -> None:
        self._chunks.append(text)
        self._line_map.append_line(text, location)

    def extend_processed(self, processed: _ProcessedText) -> None:
        self._chunks.append(processed.source)
        self._line_map.extend(processed.line_map)

    def build(self) -> _ProcessedText:
        return _ProcessedText("".join(self._chunks), self._line_map.build())


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
