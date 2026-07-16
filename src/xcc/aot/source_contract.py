from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, NoReturn

from xcc.aot import py_ast as ast
from xcc.aot.diag import AotDiagnostic, AotError
from xcc.aot.module import AotModule
from xcc.aot.py_parser import parse_subset_source
from xcc.aot.sha256 import sha256_hex

ParserKind = Literal["cpython", "subset"]
ModuleParser = Callable[[str, str], AotModule]

ALLOWED_STDLIB_ROOTS = frozenset(
    {
        "argparse",
        "ast",
        "collections",
        "contextlib",
        "ctypes",
        "dataclasses",
        "datetime",
        "enum",
        "functools",
        "hashlib",
        "json",
        "os",
        "pathlib",
        "pickle",
        "platform",
        "re",
        "shutil",
        "struct",
        "subprocess",
        "sys",
        "tempfile",
        "typing",
    }
)

# These modules are Stage 0 process adapters.  They remain ordinary CPython
# modules, but are deliberately outside the source set admitted for native AOT.
HOSTED_ONLY_MODULES = frozenset(
    {
        "xcc.aot.__main__",
        "xcc.aot.cpython_ast_adapter",
        "xcc.aot.hosted_cli",
        "xcc.aot.parser_oracle",
    }
)


@dataclass(frozen=True)
class CachePolicy:
    requested_no_cache: bool
    read_enabled: bool = False
    write_enabled: bool = False
    directory: str | None = None


@dataclass(frozen=True)
class ParserBackend:
    kind: ParserKind
    parse: ModuleParser


@dataclass(frozen=True)
class SourceUnit:
    module: str
    relative_path: str
    canonical_path: str
    sha256: str
    dependencies: tuple[str, ...]
    external_dependencies: tuple[str, ...]
    order: int
    source: str = field(repr=False, compare=False)
    parsed: AotModule = field(repr=False, compare=False)


@dataclass(frozen=True)
class SourceSet:
    source_root: str
    entry_module: str
    parser: ParserKind
    cache_policy: CachePolicy
    units: tuple[SourceUnit, ...]


def source_module_name(source_root: Path, path: Path) -> str:
    root = source_root.resolve()
    resolved = path.resolve()
    if root != resolved and root not in resolved.parents:
        _raise_contract_error(
            "XCC-AOT-SOURCE-0005",
            f"Module path escapes source root: {resolved}",
        )
    relative = resolved.relative_to(root)
    if relative.suffix != ".py":
        _raise_contract_error(
            "XCC-AOT-SOURCE-0002",
            f"Module path is not Python source: {resolved}",
        )
    parts = list(relative.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join([root.name, *parts])


def resolve_source_set(
    source_root: Path,
    entry_module: str,
    parser: ParserBackend,
    cache_policy: CachePolicy | None = None,
) -> SourceSet:
    if parser.kind == "subset":
        return resolve_subset_source_set(source_root, entry_module, cache_policy)
    root = source_root.resolve()
    if not root.is_dir():
        _raise_contract_error("XCC-AOT-SOURCE-0001", f"Source root is not a directory: {root}")
    if not _valid_module_name(entry_module):
        _raise_contract_error("XCC-AOT-SOURCE-0002", f"Invalid entry module: {entry_module}")
    root_package = root.name
    if entry_module != root_package and not entry_module.startswith(f"{root_package}."):
        _raise_contract_error(
            "XCC-AOT-SOURCE-0002",
            f"Entry module is outside source package {root_package}: {entry_module}",
        )

    pending = [entry_module]
    sources: dict[str, tuple[Path, str, bytes, AotModule]] = {}
    dependencies: dict[str, tuple[str, ...]] = {}
    external_dependencies: dict[str, tuple[str, ...]] = {}
    while pending:
        module_name = min(pending)
        pending.remove(module_name)
        if module_name in sources:
            continue
        if parser.kind == "subset" and module_name in HOSTED_ONLY_MODULES:
            _raise_contract_error(
                "XCC-AOT-SOURCE-0006",
                f"Hosted-only module is not available to subset parser: {module_name}",
            )
        path = _module_path(root, root_package, module_name)
        try:
            raw = path.read_bytes()
        except OSError as error:
            _raise_contract_error(
                "XCC-AOT-SOURCE-0003",
                f"Cannot read module {module_name}: {path}: {error}",
            )
        try:
            source = raw.decode("utf-8")
        except UnicodeDecodeError:
            _raise_contract_error(
                "XCC-AOT-SOURCE-0004",
                f"Module is not UTF-8: {path}",
            )
        parsed = parser.parse(source, str(path))
        module_dependencies, module_external_dependencies = _module_dependencies(
            parsed.tree,
            module_name,
            root,
            root_package,
        )
        dependencies[module_name] = module_dependencies
        external_dependencies[module_name] = module_external_dependencies
        sources[module_name] = (path, source, raw, parsed)
        for dependency in module_dependencies:
            if dependency not in sources and dependency not in pending:
                pending.append(dependency)

    order = _dependency_order(dependencies)
    units: list[SourceUnit] = []
    for index, module_name in enumerate(order):
        path, source, raw, parsed = sources[module_name]
        units.append(
            SourceUnit(
                module=module_name,
                relative_path=_module_relative_path(root_package, module_name, path),
                canonical_path=str(path),
                sha256=sha256_hex(raw),
                dependencies=dependencies[module_name],
                external_dependencies=external_dependencies[module_name],
                order=index,
                source=source,
                parsed=parsed,
            )
        )
    policy = cache_policy if cache_policy is not None else CachePolicy(False)
    return SourceSet(str(root), entry_module, parser.kind, policy, tuple(units))


def resolve_subset_source_set(
    source_root: Path,
    entry_module: str,
    cache_policy: CachePolicy | None = None,
) -> SourceSet:
    root = source_root.resolve()
    if not (root / "__init__.py").is_file():
        _raise_contract_error("XCC-AOT-SOURCE-0001", f"Source root is not a package: {root}")
    if not _valid_module_name(entry_module):
        _raise_contract_error("XCC-AOT-SOURCE-0002", f"Invalid entry module: {entry_module}")
    root_package = root.name
    if entry_module != root_package and not entry_module.startswith(f"{root_package}."):
        _raise_contract_error(
            "XCC-AOT-SOURCE-0002",
            f"Entry module is outside source package {root_package}: {entry_module}",
        )

    pending = [entry_module]
    sources: dict[str, tuple[Path, str, bytes, AotModule]] = {}
    dependencies: dict[str, tuple[str, ...]] = {}
    external_dependencies: dict[str, tuple[str, ...]] = {}
    while pending:
        module_name = min(pending)
        pending.remove(module_name)
        if module_name in sources:
            continue
        if module_name in HOSTED_ONLY_MODULES:
            _raise_contract_error(
                "XCC-AOT-SOURCE-0006",
                f"Hosted-only module is not available to subset parser: {module_name}",
            )
        path = _module_path(root, root_package, module_name)
        source = path.read_text(encoding="utf-8")
        raw = source.encode("utf-8")
        parsed = parse_subset_source(source, filename=str(path))
        module_dependencies, module_external_dependencies = _module_dependencies(
            parsed.tree,
            module_name,
            root,
            root_package,
        )
        dependencies[module_name] = module_dependencies
        external_dependencies[module_name] = module_external_dependencies
        sources[module_name] = (path, source, raw, parsed)
        for dependency in module_dependencies:
            if dependency not in sources and dependency not in pending:
                pending.append(dependency)

    order = _dependency_order(dependencies)
    units: list[SourceUnit] = []
    for index, module_name in enumerate(order):
        path, source, raw, parsed = sources[module_name]
        units.append(
            SourceUnit(
                module=module_name,
                relative_path=_module_relative_path(root_package, module_name, path),
                canonical_path=str(path),
                sha256=sha256_hex(raw),
                dependencies=dependencies[module_name],
                external_dependencies=external_dependencies[module_name],
                order=index,
                source=source,
                parsed=parsed,
            )
        )
    policy = cache_policy if cache_policy is not None else CachePolicy(False)
    return SourceSet(str(root), entry_module, "subset", policy, tuple(units))


def render_source_manifest(source_set: SourceSet) -> str:
    policy = source_set.cache_policy
    directory = "null" if policy.directory is None else _json_string(policy.directory)
    units = "["
    first = True
    for unit in source_set.units:
        if not first:
            units += ","
        units += (
            '{"canonical_path":'
            + _json_string(unit.canonical_path)
            + ',"dependencies":'
            + _json_string_array(unit.dependencies)
            + ',"external_dependencies":'
            + _json_string_array(unit.external_dependencies)
            + ',"module":'
            + _json_string(unit.module)
            + ',"order":'
            + str(unit.order)
            + ',"relative_path":'
            + _json_string(unit.relative_path)
            + ',"sha256":'
            + _json_string(unit.sha256)
            + "}"
        )
        first = False
    units += "]"
    return (
        '{"cache":{"directory":'
        + directory
        + ',"read_enabled":'
        + _json_bool(policy.read_enabled)
        + ',"requested_no_cache":'
        + _json_bool(policy.requested_no_cache)
        + ',"write_enabled":'
        + _json_bool(policy.write_enabled)
        + '},"entry":'
        + _json_string(source_set.entry_module)
        + ',"parser":'
        + _json_string(source_set.parser)
        + ',"source_root":'
        + _json_string(source_set.source_root)
        + ',"units":'
        + units
        + ',"version":1}\n'
    )


def _json_bool(value: bool) -> str:
    return "true" if value else "false"


def _json_string_array(values: tuple[str, ...]) -> str:
    result = "["
    first = True
    for value in values:
        if not first:
            result += ","
        result += _json_string(value)
        first = False
    return result + "]"


def _json_string(value: str) -> str:
    result = '"'
    digits = "0123456789abcdef"
    for character in value:
        code = ord(character)
        if character == '"':
            result += '\\"'
        elif character == "\\":
            result += "\\\\"
        elif character == "\b":
            result += "\\b"
        elif character == "\f":
            result += "\\f"
        elif character == "\n":
            result += "\\n"
        elif character == "\r":
            result += "\\r"
        elif character == "\t":
            result += "\\t"
        elif code < 0x20:
            result += "\\u00" + digits[(code >> 4) & 0xF] + digits[code & 0xF]
        else:
            result += character
    return result + '"'


def _module_path(root: Path, root_package: str, module_name: str) -> Path:
    suffix = module_name[len(root_package) :].lstrip(".")
    parts = [] if not suffix else suffix.split(".")
    module_path = root
    for part in parts:
        module_path = module_path / part
    package_path = module_path / "__init__.py"
    source_path = Path(str(module_path) + ".py")
    if package_path.is_file():
        path = package_path
    elif source_path.is_file():
        path = source_path
    else:
        _raise_contract_error(
            "XCC-AOT-SOURCE-0003",
            f"Module not found: {module_name}",
        )
    resolved = path.resolve()
    root_text = str(root)
    resolved_text = str(resolved)
    if resolved_text != root_text and not resolved_text.startswith(root_text.rstrip("/") + "/"):
        _raise_contract_error(
            "XCC-AOT-SOURCE-0005",
            f"Module path escapes source root: {module_name}",
        )
    return resolved


def _module_relative_path(root_package: str, module_name: str, path: Path) -> str:
    suffix = module_name[len(root_package) :].lstrip(".").replace(".", "/")
    if path.name == "__init__.py":
        return (suffix + "/" if suffix else "") + "__init__.py"
    return suffix + ".py"


def _module_dependencies(
    tree: ast.Module,
    module_name: str,
    root: Path,
    root_package: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    result: set[str] = set()
    external: set[str] = set()
    for parent in _package_ancestors(module_name, root_package):
        result.add(parent)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for imported in node.names:
                _add_dependency(
                    result,
                    external,
                    imported.name,
                    root,
                    root_package,
                    module_name,
                )
        elif isinstance(node, ast.ImportFrom):
            imported_module = _resolve_import_from(
                module_name,
                node,
                root,
                root_package,
            )
            if imported_module is None:
                continue
            _add_dependency(
                result,
                external,
                imported_module,
                root,
                root_package,
                module_name,
            )
            for imported in node.names:
                if imported.name == "*":
                    continue
                _add_dependency(
                    result,
                    external,
                    f"{imported_module}.{imported.name}",
                    root,
                    root_package,
                    module_name,
                )
    result.discard(module_name)
    return tuple(sorted(result)), tuple(sorted(external))


def _add_dependency(
    dependencies: set[str],
    external: set[str],
    candidate: str,
    root: Path,
    root_package: str,
    importing_module: str,
) -> None:
    if candidate != root_package and not candidate.startswith(f"{root_package}."):
        external_root = candidate.split(".", 1)[0]
        if external_root not in ALLOWED_STDLIB_ROOTS:
            _raise_contract_error(
                "XCC-AOT-SOURCE-0007",
                f"Unsupported external import in {importing_module}: {candidate}",
            )
        external.add(external_root)
        return
    if _module_exists(root, root_package, candidate):
        for parent in _package_ancestors(candidate, root_package):
            dependencies.add(parent)
        dependencies.add(candidate)


def _package_ancestors(module_name: str, root_package: str) -> tuple[str, ...]:
    parts = module_name.split(".")
    result: list[str] = []
    for index in range(1, len(parts)):
        candidate = ".".join(parts[:index])
        if candidate == root_package or candidate.startswith(f"{root_package}."):
            result.append(candidate)
    return tuple(result)


def _module_exists(root: Path, root_package: str, module_name: str) -> bool:
    suffix = module_name[len(root_package) :].lstrip(".")
    parts = [] if not suffix else suffix.split(".")
    path = root
    for part in parts:
        path = path / part
    return (path / "__init__.py").is_file() or Path(str(path) + ".py").is_file()


def _resolve_import_from(
    module_name: str,
    node: ast.ImportFrom,
    root: Path,
    root_package: str,
) -> str | None:
    if node.level == 0:
        return node.module
    parts = module_name.split(".")
    suffix = module_name[len(root_package) :].lstrip(".")
    relative_parts = [] if not suffix else suffix.split(".")
    package_path = root
    for part in relative_parts:
        package_path = package_path / part
    is_package = (package_path / "__init__.py").is_file()
    package = parts if is_package else parts[:-1]
    parent_count = node.level - 1
    if parent_count > len(package):
        return None
    base = package[: len(package) - parent_count]
    if node.module:
        base.extend(node.module.split("."))
    return ".".join(base)


def _dependency_order(graph: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    components = _strongly_connected_components(graph)
    component_by_module: dict[str, int] = {}
    for index, component in enumerate(components):
        for module_name in component:
            component_by_module[module_name] = index
    remaining = set(range(len(components)))
    emitted: set[int] = set()
    result: list[str] = []
    while remaining:
        ready = [
            index
            for index in remaining
            if all(
                component_by_module[dependency] in emitted
                or component_by_module[dependency] == index
                for module_name in components[index]
                for dependency in graph[module_name]
            )
        ]
        if not ready:
            raise AssertionError("SCC condensation graph must be acyclic")
        selected = ready[0]
        for candidate in ready[1:]:
            if components[candidate] < components[selected]:
                selected = candidate
        result.extend(components[selected])
        emitted.add(selected)
        remaining.remove(selected)
    return tuple(result)


def _strongly_connected_components(
    graph: dict[str, tuple[str, ...]],
) -> tuple[tuple[str, ...], ...]:
    forward: dict[str, set[str]] = {name: set(values) for name, values in graph.items()}
    reverse: dict[str, set[str]] = {name: set() for name in graph}
    for name, values in forward.items():
        for dependency in values:
            reverse[dependency].add(name)
    finish_order = _finish_order(forward)
    seen: set[str] = set()
    components: list[tuple[str, ...]] = []
    for start in reversed(finish_order):
        if start in seen:
            continue
        stack = [start]
        component: list[str] = []
        seen.add(start)
        while stack:
            current = stack.pop()
            component.append(current)
            for neighbor in sorted(reverse[current], reverse=True):
                if neighbor not in seen:
                    seen.add(neighbor)
                    stack.append(neighbor)
        components.append(tuple(sorted(component)))
    return tuple(components)


def _finish_order(graph: dict[str, set[str]]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for start in sorted(graph):
        if start in seen:
            continue
        stack: list[tuple[str, bool]] = [(start, False)]
        while stack:
            current, exiting = stack.pop()
            if exiting:
                result.append(current)
                continue
            if current in seen:
                continue
            seen.add(current)
            stack.append((current, True))
            for neighbor in sorted(graph[current], reverse=True):
                if neighbor not in seen:
                    stack.append((neighbor, False))
    return tuple(result)


def _valid_module_name(name: str) -> bool:
    return bool(name) and all(part.isidentifier() for part in name.split("."))


def _raise_contract_error(code: str, message: str) -> NoReturn:
    raise AotError((AotDiagnostic(code, message, filename="<source-contract>"),))
