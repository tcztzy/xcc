#!/usr/bin/env python3
"""Run CPython-style frontend trials and summarize blockers."""

from collections import defaultdict
from dataclasses import dataclass

from xcc.diag import FrontendError
from xcc.frontend import compile_source
from xcc.options import FrontendOptions

_STAGE_ORDER = {"pp": 0, "lex": 1, "parse": 2, "sema": 3}


@dataclass(frozen=True)
class TrialCase:
    name: str
    source: str
    std: str = "c11"


@dataclass(frozen=True)
class TrialFailure:
    case_name: str
    stage: str
    message: str


def _cases() -> list[TrialCase]:
    return [
        TrialCase(
            "typedef_pyobject",
            """
typedef struct _typeobject PyTypeObject;
typedef struct _object {
    long ob_refcnt;
    PyTypeObject *ob_type;
} PyObject;
PyObject *borrow(PyObject *o) { return o; }
""",
        ),
        TrialCase(
            "typedef_pytypeobject_with_slots",
            """
typedef struct _object PyObject;
typedef struct _typeobject {
    const char *tp_name;
    int (*tp_init)(PyObject *, PyObject *, PyObject *);
    void (*tp_dealloc)(PyObject *);
} PyTypeObject;
""",
        ),
        TrialCase(
            "enum_send_result",
            """
enum PySendResult { PYGEN_NEXT = 0, PYGEN_RETURN = 1, PYGEN_ERROR = 2 };
enum PySendResult pick_result(int flag) {
    return flag ? PYGEN_NEXT : PYGEN_ERROR;
}
""",
        ),
        TrialCase(
            "macro_do_while",
            """
#define Py_CLEAR(op) do { if ((op) != 0) { (op) = 0; } } while (0)
int clear_value(int *p) {
    Py_CLEAR(*p);
    return *p;
}
""",
        ),
        TrialCase(
            "gnu_statement_expression",
            """
int stmt_expr(int x) {
    return ({
        int y = x + 1;
        y;
    });
}
""",
            std="gnu11",
        ),
        TrialCase(
            "array_of_function_pointers",
            """
typedef int (*binaryfunc)(int, int);
int add_i(int a, int b) { return a + b; }
int sub_i(int a, int b) { return a - b; }
binaryfunc binops[2] = {add_i, sub_i};
int run_binop(int index, int a, int b) {
    return binops[index](a, b);
}
""",
        ),
        TrialCase(
            "const_qualified_pointers",
            """
int ptr_compat(const int *const *lhs, const int *const *rhs) {
    return lhs == rhs;
}
""",
        ),
        TrialCase(
            "variadic_function",
            """
int py_log(const char *fmt, ...) {
    return fmt != 0;
}
""",
        ),
        TrialCase(
            "designated_initializer_struct",
            """
struct pair {
    int a;
    int b;
};
struct pair pair_value = {.b = 2, .a = 1};
int pair_sum(void) {
    return pair_value.a + pair_value.b;
}
""",
        ),
        TrialCase(
            "designated_initializer_array",
            """
int offsets[6] = {[0] = 1, [3] = 4, [5] = 9};
int read_offset(void) {
    return offsets[3];
}
""",
        ),
        TrialCase(
            "static_assert",
            """
_Static_assert(sizeof(long) >= sizeof(int), "long narrower than int");
int static_assert_ok(void) { return 0; }
""",
        ),
        TrialCase(
            "sizeof_offsetof_pattern",
            """
#define OFFSETOF(type, member) ((unsigned long)&(((type *)0)->member))
struct point {
    int x;
    int y;
};
unsigned long point_y_offset = OFFSETOF(struct point, y);
""",
        ),
        TrialCase(
            "conditional_pointer_integer_mix",
            """
int cond_pointer_mix(int *p, int fallback) {
    return p ? (int)(long)p : fallback;
}
""",
        ),
        TrialCase(
            "forward_decl_incomplete_type",
            """
struct node;
struct node *next_node(struct node *n);
struct node {
    struct node *next;
    int value;
};
struct node *next_node(struct node *n) {
    return n->next;
}
""",
        ),
        TrialCase(
            "union_type",
            """
union value {
    long i;
    double d;
    void *p;
};
union value id_value(union value v) {
    return v;
}
""",
        ),
        TrialCase(
            "bit_fields",
            """
struct flags {
    unsigned int ready : 1;
    unsigned int kind : 3;
};
int read_kind(struct flags f) {
    return (int)f.kind;
}
""",
        ),
        TrialCase(
            "function_pointer_cast",
            """
typedef int (*unaryfunc)(int);
int add_one(int x) { return x + 1; }
int casted_call(void) {
    unaryfunc f = (unaryfunc)(void *)add_one;
    return f(4);
}
""",
        ),
        TrialCase(
            "comma_expression",
            """
int comma_eval(int x) {
    return (x += 1, x *= 2, x);
}
""",
        ),
        TrialCase(
            "compound_literal",
            """
struct rec {
    int a;
    int b;
};
int read_compound(void) {
    return ((struct rec){.a = 4, .b = 8}).b;
}
""",
        ),
        TrialCase(
            "anonymous_struct_union",
            """
struct holder {
    union {
        struct {
            int x;
            int y;
        };
        long packed;
    };
};
int read_holder(struct holder h) {
    return h.x + h.y;
}
""",
            std="gnu11",
        ),
        TrialCase(
            "gcc_attribute_unused",
            """
static int helper(int x) __attribute__((unused));
static int helper(int x) {
    return x;
}
int attribute_user(void) {
    return 0;
}
""",
            std="gnu11",
        ),
        TrialCase(
            "flexible_array_member",
            """
struct bytes {
    unsigned long len;
    unsigned char data[];
};
unsigned long payload_len(struct bytes *b) {
    return b->len;
}
""",
        ),
        TrialCase(
            "alignas_alignof",
            """
struct aligned_value {
    _Alignas(16) int x;
};
int query_align(void) {
    return (int)_Alignof(struct aligned_value);
}
""",
        ),
        TrialCase(
            "generic_selection",
            """
int select_long(long x) {
    return _Generic(x, long: 1, default: 0);
}
""",
        ),
        TrialCase(
            "token_paste_and_stringify",
            """
#define JOIN2(a, b) a##b
#define STR1(x) #x
int JOIN2(to, ken) = 5;
const char *macro_name = STR1(PyObject_VAR_HEAD);
int read_token(void) {
    return token;
}
""",
        ),
    ]


def _normalize_message(message: str) -> str:
    return " ".join(message.split())


def _escape_markdown_cell(text: str, *, limit: int = 140) -> str:
    escaped = text.replace("|", "\\|").replace("\n", " ").strip()
    if len(escaped) <= limit:
        return escaped
    return f"{escaped[: limit - 3]}..."


def run_trial(cases: list[TrialCase]) -> tuple[int, list[TrialFailure]]:
    passed = 0
    failures: list[TrialFailure] = []
    for index, case in enumerate(cases, start=1):
        options = FrontendOptions(std=case.std)
        filename = f"<cpython-trial:{index}:{case.name}>"
        try:
            compile_source(case.source, filename=filename, options=options)
        except FrontendError as error:
            diagnostic = error.diagnostic
            stage = diagnostic.stage if diagnostic.stage in _STAGE_ORDER else "sema"
            message = _normalize_message(diagnostic.message)
            failures.append(TrialFailure(case.name, stage, message))
            print(f"FAIL [{stage}] {case.name}: {message}")
        else:
            passed += 1
            print(f"PASS {case.name}")
    return passed, failures


def _print_failure_summary(failures: list[TrialFailure], total: int) -> None:
    grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
    for failure in failures:
        grouped[(failure.stage, failure.message)].append(failure.case_name)
    ordered = sorted(
        grouped.items(),
        key=lambda item: (
            _STAGE_ORDER.get(item[0][0], 99),
            -len(item[1]),
            item[0][1],
        ),
    )

    print("\nFailure Buckets")
    print("| Category | Frequency | Message | Example Cases |")
    print("| --- | --- | --- | --- |")
    for (stage, message), case_names in ordered:
        examples = ", ".join(case_names[:3])
        print(
            "| "
            f"{stage} | {len(case_names)} | "
            f"{_escape_markdown_cell(message)} | "
            f"{_escape_markdown_cell(examples)}"
            " |"
        )

    print("\nTODO.md Blocker Rows")
    print("| ID | Category (pp/lex/parse/sema) | Description | Frequency | Status |")
    print("| --- | --- | --- | --- | --- |")
    for index, ((stage, message), case_names) in enumerate(ordered, start=1):
        blocker_id = f"B{index:03d}"
        examples = ", ".join(case_names[:2])
        description = f"{message} (examples: {examples})"
        print(
            "| "
            f"{blocker_id} | {stage} | {_escape_markdown_cell(description)} | "
            f"{len(case_names)} / {total} | [ ]"
            " |"
        )


def main() -> int:
    cases = _cases()
    passed, failures = run_trial(cases)
    total = len(cases)
    failed = len(failures)

    print("\nCPython Frontend Trial Summary")
    print(f"Total snippets: {total}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")

    if failures:
        _print_failure_summary(failures, total)
    else:
        print("All snippets passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
