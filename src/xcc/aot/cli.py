int32 = int

_USAGE = (
    "usage: xcc-aot build --source-root PATH --entry MODULE:FUNCTION "
    "--output PATH --parser=subset [options]"
)
_VERSION = "xcc-aot 0.2 native-contract"


def main(argc: int32, argv: tuple[str, ...]) -> int32:
    if argc <= 1:
        print(_USAGE)
        return 2
    command = argv[1]
    if command in {"-h", "--help"}:
        print(_USAGE)
        return 0
    if command == "--version":
        print(_VERSION)
        return 0
    if command != "build":
        print(f"xcc-aot: unknown command: {command}")
        return 2
    wants_help = False
    index: int32 = 2
    while index < argc:
        argument = argv[index]
        parser = ""
        if argument.startswith("--parser="):
            parser = argument.split("=", 1)[1]
        elif argument == "--parser":
            index += 1
            if index < argc:
                parser = argv[index]
        elif argument in {"-h", "--help"}:
            wants_help = True
        if parser == "cpython":
            print("xcc-aot: native mode rejects --parser=cpython")
            return 2
        if argument.startswith("--parser") and parser != "subset":
            print(f"xcc-aot: native mode rejects parser: {parser}")
            return 2
        index += 1
    if wants_help:
        print(_USAGE)
        return 0
    value_options = (
        "--assembler",
        "--emit-llvm",
        "--emit-normalized-ir",
        "--entry",
        "--linker",
        "--llc",
        "--output",
        "--parser",
        "--source-manifest",
        "--source-root",
    )
    seen_options: tuple[str, ...] = ()
    index = 2
    while index < argc:
        argument = argv[index]
        if argument == "--no-cache":
            if argument in seen_options:
                print(f"xcc-aot: duplicate option: {argument}")
                return 2
            seen_options += (argument,)
            index += 1
            continue
        option = argument
        value = ""
        if "=" in argument:
            parts = argument.split("=", 1)
            option = parts[0]
            value = parts[1]
        elif option in value_options:
            index += 1
            if index >= argc:
                print(f"xcc-aot: missing value for {option}")
                return 2
            value = argv[index]
        else:
            print(f"xcc-aot: unknown option: {option}")
            return 2
        if option not in value_options:
            print(f"xcc-aot: unknown option: {option}")
            return 2
        if option in seen_options:
            print(f"xcc-aot: duplicate option: {option}")
            return 2
        if not value:
            print(f"xcc-aot: empty value for {option}")
            return 2
        seen_options += (option,)
        index += 1
    for required in ("--source-root", "--entry", "--output", "--parser"):
        if required not in seen_options:
            print(f"xcc-aot: missing required option: {required}")
            return 2
    print("xcc-aot: native build pipeline is not reachable before Milestone 5")
    return 1
