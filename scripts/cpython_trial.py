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
        TrialCase(
            "attribute_visibility_function",
            """
int api_export(int x) __attribute__((visibility("default")));
int api_export(int x) {
    return x + 1;
}
""",
            std="gnu11",
        ),
        TrialCase(
            "attribute_visibility_variable",
            """
__attribute__((visibility("default"))) int cpython_visible = 7;
int read_visible(void) {
    return cpython_visible;
}
""",
            std="gnu11",
        ),
        TrialCase(
            "attribute_format_printf",
            """
int py_printf(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
int py_printf(const char *fmt, ...) {
    return fmt != 0;
}
""",
            std="gnu11",
        ),
        TrialCase(
            "attribute_noreturn",
            """
void py_fatal(const char *msg) __attribute__((noreturn));
void py_fatal(const char *msg) {
    (void)msg;
    for (;;) {
    }
}
""",
            std="gnu11",
        ),
        TrialCase(
            "attribute_cold_hot",
            """
__attribute__((cold)) int slow_path(int x) {
    return x - 1;
}
__attribute__((hot)) int fast_path(int x) {
    return x + 1;
}
int call_paths(int x) {
    return x ? fast_path(x) : slow_path(x);
}
""",
            std="gnu11",
        ),
        TrialCase(
            "attribute_aligned",
            """
struct align_pair {
    __attribute__((aligned(32))) int v;
};
int read_align_field(struct align_pair *p) {
    return p->v;
}
""",
            std="gnu11",
        ),
        TrialCase(
            "attribute_packed_struct",
            """
struct __attribute__((packed)) packed_header {
    char tag;
    int value;
};
int read_packed(struct packed_header h) {
    return h.value;
}
""",
            std="gnu11",
        ),
        TrialCase(
            "attribute_constructor_destructor",
            """
static int ctor_state;
static void init_mod(void) __attribute__((constructor));
static void fini_mod(void) __attribute__((destructor));
static void init_mod(void) {
    ctor_state = 1;
}
static void fini_mod(void) {
    ctor_state = 0;
}
int read_ctor_state(void) {
    return ctor_state;
}
""",
            std="gnu11",
        ),
        TrialCase(
            "extension_keyword_statement_expression",
            """
int use_extension(int x) {
    return __extension__ ({
        int y = x + 2;
        y;
    });
}
""",
            std="gnu11",
        ),
        TrialCase(
            "typeof_expression",
            """
int read_typeof(int x) {
    typeof(x) y = x + 3;
    return y;
}
""",
            std="gnu11",
        ),
        TrialCase(
            "double_underscore_typeof_expression",
            """
int read_dunder_typeof(long x) {
    __typeof__(x) y = x + 4;
    return (int)y;
}
""",
            std="gnu11",
        ),
        TrialCase(
            "builtin_expect_pattern",
            """
int branch_hint(int x) {
    if (__builtin_expect(x == 0, 0)) {
        return -1;
    }
    return x;
}
""",
            std="gnu11",
        ),
        TrialCase(
            "builtin_unreachable_pattern",
            """
int impossible_branch(int x) {
    switch (x) {
    case 0:
        return 0;
    case 1:
        return 1;
    default:
        __builtin_unreachable();
    }
}
""",
            std="gnu11",
        ),
        TrialCase(
            "builtin_offsetof_pattern",
            """
struct offset_member {
    int a;
    long b;
};
unsigned long member_offset(void) {
    return __builtin_offsetof(struct offset_member, b);
}
""",
            std="gnu11",
        ),
        TrialCase(
            "flexible_array_embedded",
            """
struct packet {
    int kind;
    char payload[];
};
int packet_kind(struct packet *p) {
    return p->kind;
}
""",
        ),
        TrialCase(
            "anonymous_struct_in_union",
            """
union cell {
    struct {
        int x;
        int y;
    };
    long pair;
};
int cell_sum(union cell *c) {
    return c->x + c->y;
}
""",
            std="gnu11",
        ),
        TrialCase(
            "anonymous_union_in_struct",
            """
struct container {
    int tag;
    union {
        int i;
        struct {
            short s0;
            short s1;
        };
    };
};
int read_container(struct container *c) {
    return c->tag ? c->i : c->s0;
}
""",
            std="gnu11",
        ),
        TrialCase(
            "nested_struct_union_definitions",
            """
struct outer {
    struct inner {
        union nested {
            int i;
            long l;
        } value;
    } in;
};
long read_nested(struct outer *o) {
    return o->in.value.l;
}
""",
        ),
        TrialCase(
            "knr_style_function_definition",
            """
int legacy_add(a, b)
int a;
int b;
{
    return a + b;
}
""",
            std="gnu11",
        ),
        TrialCase(
            "empty_struct_gnu",
            """
struct empty_gnu {};
struct wrap_empty {
    struct empty_gnu e;
    int value;
};
int read_wrap_empty(struct wrap_empty *w) {
    return w->value;
}
""",
            std="gnu11",
        ),
        TrialCase(
            "zero_length_array_gnu",
            """
struct bytes0 {
    int size;
    char data[0];
};
int read_bytes0(struct bytes0 *b) {
    return b->size;
}
""",
            std="gnu11",
        ),
        TrialCase(
            "designated_initializer_nested_struct",
            """
struct inner_point {
    int x;
    int y;
};
struct outer_point {
    int id;
    struct inner_point p;
};
struct outer_point pt = {.p = {.y = 9, .x = 3}, .id = 1};
int read_nested_designator(void) {
    return pt.p.x + pt.p.y;
}
""",
        ),
        TrialCase(
            "compound_literal_assignment",
            """
struct pair2 {
    int a;
    int b;
};
int assign_compound(void) {
    struct pair2 p;
    p = (struct pair2){.a = 5, .b = 6};
    return p.a + p.b;
}
""",
        ),
        TrialCase(
            "compound_literal_function_argument",
            """
struct arg_pair {
    int left;
    int right;
};
int add_pair(struct arg_pair p) {
    return p.left + p.right;
}
int call_add_pair(void) {
    return add_pair((struct arg_pair){.left = 2, .right = 4});
}
""",
        ),
        TrialCase(
            "array_designator_range_gnu",
            """
int dense[6] = {[0 ... 3] = 8, [4] = 1, [5] = 2};
int read_dense(int idx) {
    return dense[idx];
}
""",
            std="gnu11",
        ),
        TrialCase(
            "statement_expression_macro",
            """
#define ID_EXPR(x) ({ int _tmp = (x); _tmp; })
int read_stmt_macro(int x) {
    return ID_EXPR(x + 1);
}
""",
            std="gnu11",
        ),
        TrialCase(
            "computed_goto_dispatch",
            """
int goto_dispatch(int flag) {
    void *target = flag ? &&slow : &&fast;
    goto *target;
slow:
    return -1;
fast:
    return 1;
}
""",
            std="gnu11",
        ),
        TrialCase(
            "labels_as_values_array",
            """
int label_index(int idx) {
    static void *table[] = {&&l0, &&l1};
    if (idx < 0 || idx > 1) {
        return -1;
    }
    goto *table[idx];
l0:
    return 0;
l1:
    return 1;
}
""",
            std="gnu11",
        ),
        TrialCase(
            "asm_volatile_stub",
            """
int asm_identity(int x) {
    __asm__ volatile("" : "+r"(x));
    return x;
}
""",
            std="gnu11",
        ),
        TrialCase(
            "thread_local_storage",
            """
_Thread_local int tls_value = 3;
int read_tls(void) {
    return tls_value;
}
""",
        ),
        TrialCase(
            "nested_function_pointer_declarator",
            """
int *ret_ptr(int *p) {
    return p;
}
int *(*make_handler(void))(int *) {
    return ret_ptr;
}
""",
        ),
        TrialCase(
            "struct_member_function_pointer_complex",
            """
struct callback_table {
    int *(*dispatch)(const char *, int (*)(int, int), void *);
};
int noop_binop(int a, int b) {
    return a + b;
}
int *dispatch_impl(const char *name, int (*fn)(int, int), void *ctx) {
    (void)name;
    (void)ctx;
    static int slot;
    slot = fn(1, 2);
    return &slot;
}
int call_dispatch(void) {
    struct callback_table t = {.dispatch = dispatch_impl};
    return *t.dispatch("x", noop_binop, 0);
}
""",
        ),
        TrialCase(
            "pointer_to_array_declaration",
            """
int read_ptr_array(void) {
    int values[10] = {0};
    int (*p)[10] = &values;
    (*p)[3] = 11;
    return values[3];
}
""",
        ),
        TrialCase(
            "array_of_function_pointers_returning_pointers",
            """
char *id_ptr(char *p) {
    return p;
}
char *alt_ptr(char *p) {
    return p + 1;
}
char *(*ptr_ops[2])(char *) = {id_ptr, alt_ptr};
char *call_ptr_op(int i, char *p) {
    return ptr_ops[i](p);
}
""",
        ),
        TrialCase(
            "multi_dimensional_arrays",
            """
int matrix_sum(void) {
    int m[2][3] = {{1, 2, 3}, {4, 5, 6}};
    return m[0][2] + m[1][0];
}
""",
        ),
        TrialCase(
            "const_volatile_qualified_pointers",
            """
int cv_ptr_cmp(const volatile int *const *a, const volatile int *const *b) {
    return a == b;
}
""",
        ),
        TrialCase(
            "restrict_qualifier_parameters",
            """
int sum_restrict(int *restrict dst, const int *restrict src) {
    dst[0] = src[0] + src[1];
    return dst[0];
}
""",
        ),
        TrialCase(
            "extern_declaration_then_definition",
            """
extern int py_counter;
int py_counter = 42;
int read_counter(void) {
    return py_counter;
}
""",
        ),
        TrialCase(
            "static_inline_function",
            """
static inline int inline_twice(int x) {
    return x * 2;
}
int call_inline_twice(int x) {
    return inline_twice(x);
}
""",
        ),
        TrialCase(
            "variadic_macro_va_args",
            """
#define RET_FIRST(fmt, ...) ((fmt) != 0 ? (__VA_ARGS__) : 0)
int read_variadic_macro(int v) {
    return RET_FIRST("fmt", v);
}
""",
            std="gnu11",
        ),
        TrialCase(
            "macro_stringify_tokenpaste_complex",
            """
#define CAT3(a, b, c) a##b##c
#define STR(x) #x
int CAT3(py, _,value) = 9;
const char *py_value_name = STR(CAT3(py, _,value));
int read_py_value(void) {
    return py_value;
}
""",
        ),
        TrialCase(
            "pragma_once_verification",
            """
#pragma once
int pragma_once_ok(void) {
    return 1;
}
""",
        ),
        TrialCase(
            "if_defined_and_defined",
            """
#define HAVE_ALPHA 1
#define HAVE_BETA 1
#if defined(HAVE_ALPHA) && defined(HAVE_BETA)
int feature_gate(void) { return 1; }
#else
int feature_gate(void) { return 0; }
#endif
""",
        ),
        TrialCase(
            "chained_ternary_expression",
            """
int ternary_chain(int a, int b, int c) {
    return a ? b : c ? (b + c) : (a + c);
}
""",
        ),
        TrialCase(
            "nested_sizeof_expressions",
            """
unsigned long nested_sizeof(void) {
    return sizeof(sizeof(int));
}
""",
        ),
        TrialCase(
            "cast_to_void_unused",
            """
int consume_unused(int x) {
    (void)x;
    return 0;
}
""",
        ),
        TrialCase(
            "null_void_pointer_pattern",
            """
int is_null_ptr(void *p) {
    return p == ((void *)0);
}
""",
        ),
        TrialCase(
            "long_arrow_member_chain",
            """
struct level3 {
    int leaf;
};
struct level2 {
    struct level3 *next;
};
struct level1 {
    struct level2 *next;
};
int read_chain(struct level1 *p) {
    return p->next->next->leaf;
}
""",
        ),
        TrialCase(
            "recursive_struct_types",
            """
struct tree {
    int value;
    struct tree *left;
    struct tree *right;
};
int tree_value(struct tree *t) {
    return t->left ? t->left->value : t->value;
}
""",
        ),
        TrialCase(
            "array_parameter_static_bound",
            """
void fill_static(int a[static 10]) {
    a[0] = 1;
}
""",
        ),
        TrialCase(
            "abstract_declarator_in_sizeof",
            """
unsigned long fnptr_size(void) {
    return sizeof(int (*)(void));
}
""",
        ),
        TrialCase(
            "initializer_trailing_commas",
            """
int trailing_vals[] = {1, 2, 3,};
struct trailing_struct {
    int a;
    int b;
};
struct trailing_struct trailing = {1, 2,};
int read_trailing(void) {
    return trailing_vals[2] + trailing.b;
}
""",
        ),
        TrialCase(
            "enum_explicit_values_gaps",
            """
enum status_code {
    STATUS_OK = 0,
    STATUS_RETRY = 5,
    STATUS_FATAL = 10,
};
int read_status(enum status_code code) {
    return code;
}
""",
        ),
        TrialCase(
            "typedef_function_pointer_type",
            """
typedef int (*cmp_fn)(const void *, const void *);
int call_cmp(cmp_fn fn, const void *a, const void *b) {
    return fn(a, b);
}
""",
        ),
        TrialCase(
            "multiple_declarations_one_statement",
            """
int decl_multi(void) {
    int a = 1, *b = &a, **c = &b;
    return **c;
}
""",
        ),
        TrialCase(
            "complex_macro_multiline_nested",
            """
#define WRAP(x) ((x) + 1)
#define APPLY2(fn, x) fn(fn(x))
#define NESTED_INC(v) APPLY2(WRAP, (v))
int read_nested_macro(int v) {
    return NESTED_INC(v);
}
""",
        ),
        TrialCase(
            "string_literal_concatenation",
            """
const char *joined = "hello" " " "world";
int joined_first(void) {
    return joined[0];
}
""",
        ),
        TrialCase(
            "wide_and_utf8_string_literals",
            """
int read_literal_prefixes(void) {
    return L"cpython"[0] + u8"core"[0];
}
""",
            std="gnu11",
        ),
        TrialCase(
            "implicit_integer_conversions",
            """
unsigned char narrow(unsigned int x) {
    return x;
}
int implicit_conv(int x) {
    long y = x;
    short z = y;
    return z;
}
""",
        ),
        TrialCase(
            "pointer_arithmetic_struct_pointer",
            """
struct cell2 {
    int value;
};
int next_cell_value(struct cell2 *base) {
    struct cell2 *next = base + 1;
    return next->value;
}
""",
        ),
        TrialCase(
            "signed_unsigned_comparison",
            """
int signed_unsigned_cmp(int a, unsigned int b) {
    return a < b;
}
""",
        ),
        TrialCase(
            "string_literal_to_char_pointer",
            """
char *legacy_message = "legacy";
int first_char(void) {
    return legacy_message[0];
}
""",
        ),
        TrialCase(
            "void_pointer_conversion_no_cast",
            """
int read_void_ptr(void *p) {
    int *ip = p;
    return *ip;
}
""",
        ),
        TrialCase(
            "nested_struct_member_access_chain",
            """
struct top_s {
    struct mid_s {
        struct low_s {
            int value;
        } low;
    } mid;
};
int read_nested_chain(struct top_s *t) {
    return t->mid.low.value;
}
""",
        ),
        TrialCase(
            "array_to_pointer_decay_expression",
            """
int decay_sum(int arr[4]) {
    int *p = arr;
    return p[0] + *(arr + 1);
}
""",
        ),
        TrialCase(
            "function_pointer_typedef_invocation",
            """
typedef int (*op_fn)(int, int);
int mul2(int a, int b) {
    return a * b;
}
int invoke_op(op_fn fn) {
    return fn(3, 4);
}
int call_invoke(void) {
    return invoke_op(mul2);
}
""",
        ),
        TrialCase(
            "attribute_aligned_variable",
            """
static int aligned_global __attribute__((aligned(64))) = 1;
int read_aligned_global(void) {
    return aligned_global;
}
""",
            std="gnu11",
        ),
        TrialCase(
            "typeof_macro_pattern",
            """
#define TYPEOF_COPY(dst, src) do { __typeof__(src) _tmp = (src); (dst) = _tmp; } while (0)
int copy_typeof(int x) {
    int y = 0;
    TYPEOF_COPY(y, x);
    return y;
}
""",
            std="gnu11",
        ),
        TrialCase(
            "designated_initializer_nested_array",
            """
struct row {
    int cols[3];
};
struct row table[2] = {
    [0] = {.cols = {[1] = 5}},
    [1] = {.cols = {[2] = 9}},
};
int read_designated_nested_array(void) {
    return table[0].cols[1] + table[1].cols[2];
}
""",
        ),
        TrialCase(
            "packed_aligned_combination",
            """
struct __attribute__((packed, aligned(2))) packed_aligned {
    char c;
    short s;
};
int read_packed_aligned(struct packed_aligned *p) {
    return p->s;
}
""",
            std="gnu11",
        ),
        TrialCase(
            "thread_local_extern_pattern",
            """
extern _Thread_local int tls_counter;
_Thread_local int tls_counter = 2;
int read_tls_counter(void) {
    return tls_counter;
}
""",
        ),
        TrialCase(
            "computed_goto_loop",
            """
int threaded_loop(int v) {
    static void *ops[] = {&&op_inc, &&op_done};
    goto *ops[0];
op_inc:
    v++;
    goto *ops[1];
op_done:
    return v;
}
""",
            std="gnu11",
        ),
        TrialCase(
            "macro_recursive_safe_expansion",
            """
#define ID(x) x
#define NEXT(x) ID(x)
#define VALUE 12
int read_recursive_safe_macro(void) {
    return NEXT(VALUE);
}
""",
        ),
        TrialCase(
            "function_pointer_array_parameter",
            """
typedef int *(*loader_fn)(int);
int *use_loader(loader_fn table[static 1], int x) {
    return table[0](x);
}
""",
        ),
        TrialCase(
            "pointer_to_function_returning_pointer_typedef",
            """
typedef char *(*char_loader)(char *);
char *identity_loader(char *p) {
    return p;
}
char_loader select_loader(int flag) {
    return flag ? identity_loader : identity_loader;
}
""",
        ),
        TrialCase(
            "const_restrict_pointer_combo",
            """
int add_first(const int *restrict a, const int *restrict b) {
    return a[0] + b[0];
}
""",
        ),
        TrialCase(
            "nested_ternary_with_sizeof",
            """
int choose_with_sizeof(int x) {
    return x > 0 ? (int)sizeof(long) : x < 0 ? (int)sizeof(short) : (int)sizeof(int);
}
""",
        ),
        TrialCase(
            "designator_range_with_trailing_comma",
            """
int spread[8] = {[0 ... 2] = 1, [3 ... 5] = 2, [6] = 3, [7] = 4,};
int read_spread(int i) {
    return spread[i];
}
""",
            std="gnu11",
        ),
        TrialCase(
            "asm_with_output_constraint",
            """
int asm_add_one(int v) {
    __asm__("" : "+r"(v));
    return v + 1;
}
""",
            std="gnu11",
        ),
        TrialCase(
            "builtin_offsetof_nested_member",
            """
struct outer_offset {
    int tag;
    struct inner_offset {
        int leaf;
    } in;
};
unsigned long nested_offset(void) {
    return __builtin_offsetof(struct outer_offset, in.leaf);
}
""",
            std="gnu11",
        ),
        TrialCase(
            "old_style_declaration_plus_definition",
            """
int legacy_sub();
int legacy_sub(a, b)
int a;
int b;
{
    return a - b;
}
""",
            std="gnu11",
        ),
        TrialCase(
            "abstract_declarator_fnptr_array_sizeof",
            """
unsigned long fn_array_size(void) {
    return sizeof(int (*[2])(void));
}
""",
        ),
        TrialCase(
            "null_pointer_conditional_chain",
            """
int null_conditional(void *p, int fallback) {
    return p ? *(int *)p : fallback;
}
""",
        ),
        TrialCase(
            "function_returning_function_pointer",
            """
int (*get_handler(int code))(int, int) {
    return 0;
}
""",
        ),
        TrialCase(
            "function_returning_function_pointer_fwd",
            """
int (*get_handler(void))(int);
""",
        ),
        TrialCase(
            "global_pointer_to_array",
            """
int (*matrix_row)[4];
""",
        ),
        TrialCase(
            "enum_with_trailing_comma",
            """
enum color { RED, GREEN, BLUE, };
""",
        ),
        TrialCase(
            "compound_literal_in_expression",
            """
int sum_pair(void) {
    int *p = (int []){1, 2};
    return p[0] + p[1];
}
""",
        ),
        TrialCase(
            "static_inline_function",
            """
static inline int square(int x) { return x * x; }
""",
        ),
        TrialCase(
            "do_while_with_macro_pattern",
            """
int safe_inc(int *p) {
    do { *p += 1; } while (0);
    return *p;
}
""",
        ),
        TrialCase(
            "multiple_declarators_single_stmt",
            """
int a = 1, b = 2, c = 3;
""",
        ),
        TrialCase(
            "nested_function_pointer_typedef",
            """
typedef int (*cmp_fn)(const void *, const void *);
cmp_fn global_cmp;
""",
        ),
        TrialCase(
            "extern_array_incomplete",
            """
extern int table[];
""",
        ),
        TrialCase(
            "variadic_function_with_va_list",
            """
typedef __builtin_va_list va_list;
int vprintf(const char *fmt, va_list ap);
""",
        ),
        TrialCase(
            "bitfield_in_struct",
            """
struct Flags {
    unsigned int readable : 1;
    unsigned int writable : 1;
    unsigned int executable : 1;
    unsigned int : 5;
    unsigned int dirty : 1;
};
""",
        ),
        TrialCase(
            "anonymous_struct_in_union",
            """
typedef union {
    struct { int x; int y; };
    int coords[2];
} Point;
""",
        ),
        TrialCase(
            "flexible_array_member",
            """
struct Buffer {
    int length;
    char data[];
};
""",
        ),
        TrialCase(
            "self_referential_linked_list",
            """
struct Node {
    int value;
    struct Node *next;
};
struct Node *list_prepend(struct Node *head, int val);
""",
        ),
        TrialCase(
            "typedef_function_pointer_variadic",
            """
typedef int (*printf_fn)(const char *, ...);
""",
        ),
        TrialCase(
            "enum_as_array_size",
            """
enum { MAX_ITEMS = 256 };
int items[MAX_ITEMS];
""",
        ),
        TrialCase(
            "nested_struct_with_pointer",
            """
struct Outer {
    struct Inner {
        int *data;
        int count;
    } inner;
    struct Outer *parent;
};
""",
        ),
        TrialCase(
            "const_volatile_pointer",
            """
void mmio_write(volatile int * const reg, int value) {
    *reg = value;
}
""",
        ),
        TrialCase(
            "switch_with_default_fallthrough",
            """
int classify(int c) {
    switch (c) {
    case 0: case 1: return 0;
    case 2: return 1;
    default: return -1;
    }
}
""",
        ),
        TrialCase(
            "designated_initializer_struct",
            """
struct point { int x; int y; int z; };
struct point p = { .y = 10, .x = 5, .z = 20 };
""",
        ),
        TrialCase(
            "designated_initializer_array",
            """
int arr[10] = { [3] = 30, [7] = 70 };
""",
        ),
        TrialCase(
            "compound_literal_as_argument",
            """
struct pair { int a; int b; };
int sum_pair(struct pair p) { return p.a + p.b; }
int test(void) { return sum_pair((struct pair){1, 2}); }
""",
        ),
        TrialCase(
            "static_assert_basic",
            """
_Static_assert(sizeof(int) >= 4, "int too small");
_Static_assert(1, "always true");
""",
        ),
        TrialCase(
            "generic_selection_expr",
            """
#define type_name(x) _Generic((x), \
    int: "int", \
    double: "double", \
    default: "other")
const char *s = type_name(42);
""",
        ),
        TrialCase(
            "alignof_alignas",
            """
_Alignas(16) int aligned_var;
int align = _Alignof(double);
""",
        ),
        TrialCase(
            "nested_designated_init",
            """
struct inner { int a; int b; };
struct outer { struct inner i; int c; };
struct outer o = { .i = { .a = 1, .b = 2 }, .c = 3 };
""",
        ),
        TrialCase(
            "pointer_to_array_of_pointers",
            """
typedef int (*func_t)(void);
func_t (*table)[4];
int call_first(func_t (*t)[4]) { return (*t)[0](); }
""",
        ),
        TrialCase(
            "comma_operator_in_for",
            """
int f(void) {
    int i, j;
    for (i = 0, j = 10; i < j; i++, j--)
        ;
    return i;
}
""",
        ),
        TrialCase(
            "sizeof_vla_expression",
            """
int f(int n) {
    int arr[n];
    return sizeof(arr) / sizeof(arr[0]);
}
""",
        ),
        TrialCase(
            "cast_to_void_pointer",
            """
int x = 42;
void *p = (void *)&x;
int *q = (int *)p;
""",
        ),
        TrialCase(
            "multiline_macro_with_do_while",
            """
#define SWAP(a, b) do { int _t = (a); (a) = (b); (b) = _t; } while(0)
int f(void) { int x = 1, y = 2; SWAP(x, y); return x; }
""",
        ),
        TrialCase(
            "nested_ternary_expression",
            """
int clamp(int v, int lo, int hi) {
    return v < lo ? lo : v > hi ? hi : v;
}
""",
        ),
        TrialCase(
            "array_of_function_pointers",
            """
typedef int (*op_fn)(int, int);
int add(int a, int b) { return a + b; }
int sub(int a, int b) { return a - b; }
op_fn ops[2] = { add, sub };
""",
        ),
        TrialCase(
            "string_literal_concatenation",
            """
const char *msg = "hello" " " "world";
""",
        ),
        TrialCase(
            "struct_assignment_copy",
            """
struct Point { int x; int y; };
struct Point copy_point(struct Point p) {
    struct Point q;
    q = p;
    return q;
}
""",
        ),
        TrialCase(
            "enum_arithmetic",
            """
enum Color { RED, GREEN, BLUE };
int next_color(enum Color c) { return (c + 1) % 3; }
""",
        ),
        TrialCase(
            "typedef_to_pointer_type",
            """
typedef struct Node { int val; struct Node *next; } Node;
typedef Node *NodePtr;
NodePtr make(int v) { return (NodePtr)0; }
""",
        ),
        TrialCase(
            "multi_dimensional_array",
            """
int matrix[3][4];
void set(int r, int c, int v) { matrix[r][c] = v; }
int get(int r, int c) { return matrix[r][c]; }
""",
        ),
        TrialCase(
            "void_function_with_side_effect",
            """
static int counter;
void increment(void) { counter++; }
int read_counter(void) { return counter; }
""",
        ),
        TrialCase(
            "bitfield_struct",
            """
struct Flags {
    unsigned int readable : 1;
    unsigned int writable : 1;
    unsigned int executable : 1;
    unsigned int pad : 29;
};
int check(struct Flags f) { return f.readable && f.writable; }
""",
        ),
        TrialCase(
            "anonymous_struct_in_union",
            """
union Value {
    int i;
    double d;
    struct { char *ptr; int len; };
};
int get_len(union Value *v) { return v->len; }
""",
        ),
        TrialCase(
            "variadic_declaration",
            """
int printf(const char *fmt, ...);
int sprintf(char *buf, const char *fmt, ...);
typedef int (*formatter_fn)(const char *, ...);
""",
        ),
        TrialCase(
            "flexible_array_member",
            """
struct Buffer {
    int size;
    char data[];
};
int buf_size(struct Buffer *b) { return b->size; }
""",
        ),
        TrialCase(
            "nested_union_in_struct",
            """
struct Token {
    int kind;
    union {
        long ival;
        double fval;
        char *sval;
    } u;
};
long get_ival(struct Token *t) { return t->u.ival; }
""",
        ),
        TrialCase(
            "typedef_chain",
            """
typedef int Int32;
typedef Int32 MyInt;
typedef MyInt *MyIntPtr;
MyInt add(MyIntPtr a, MyIntPtr b) { return *a + *b; }
""",
        ),
        TrialCase(
            "extern_declaration",
            """
extern int errno;
extern const char *strerror(int errnum);
int get_errno(void) { return errno; }
""",
        ),
        TrialCase(
            "do_while_loop",
            """
int count_digits(int n) {
    int count = 0;
    do { count++; n /= 10; } while (n != 0);
    return count;
}
""",
        ),
        TrialCase(
            "goto_statement",
            """
int find_nonzero(int *arr, int n) {
    int i;
    for (i = 0; i < n; i++)
        if (arr[i] != 0) goto found;
    return -1;
found:
    return i;
}
""",
        ),
        TrialCase(
            "inline_function",
            """
static inline int max(int a, int b) { return a > b ? a : b; }
static inline int min(int a, int b) { return a < b ? a : b; }
int clamp(int v, int lo, int hi) { return min(max(v, lo), hi); }
""",
        ),
        TrialCase(
            "compound_literal",
            """
struct point { int x; int y; };
struct point *get_origin(void) {
    static struct point p = {0, 0};
    return &p;
}
void use(void) { struct point q = (struct point){3, 4}; }
""",
        ),
        TrialCase(
            "designated_init_array",
            """
int table[256] = { [0] = -1, [255] = -1, [' '] = 1, ['\\n'] = 2 };
""",
        ),
        TrialCase(
            "static_assert_declaration",
            """
_Static_assert(sizeof(int) >= 4, "int too small");
typedef struct { int x; } Foo;
_Static_assert(sizeof(Foo) >= 4, "Foo too small");
""",
        ),
        TrialCase(
            "function_returning_struct",
            """
struct pair { int a; int b; };
struct pair make_pair(int x, int y) {
    struct pair p;
    p.a = x;
    p.b = y;
    return p;
}
int sum_pair(void) { struct pair p = make_pair(1, 2); return p.a + p.b; }
""",
        ),
        TrialCase(
            "pointer_to_incomplete_struct",
            """
struct node;
struct node *alloc_node(void);
struct node {
    int value;
    struct node *next;
};
struct node *alloc_node(void) { static struct node n; return &n; }
""",
        ),
        TrialCase(
            "complex_macro_expansion",
            """
#define CONCAT(a, b) a ## b
#define MAKE_NAME(prefix, id) CONCAT(prefix, id)
int MAKE_NAME(var_, 1) = 10;
int MAKE_NAME(var_, 2) = 20;
int total(void) { return var_1 + var_2; }
""",
        ),
        TrialCase(
            "enum_with_explicit_values",
            """
enum http_status {
    HTTP_OK = 200,
    HTTP_NOT_FOUND = 404,
    HTTP_INTERNAL = 500
};
int is_error(enum http_status s) { return s >= 400; }
""",
        ),
        TrialCase(
            "nested_struct_initializer",
            """
struct inner { int x; int y; };
struct outer { struct inner a; struct inner b; };
struct outer make(void) {
    struct outer o = { {1, 2}, {3, 4} };
    return o;
}
""",
        ),
        TrialCase(
            "switch_fallthrough",
            """
int classify(int c) {
    switch (c) {
    case 'a': case 'e': case 'i': case 'o': case 'u':
        return 1;
    case '0': case '1': case '2': case '3': case '4':
    case '5': case '6': case '7': case '8': case '9':
        return 2;
    default:
        return 0;
    }
}
""",
        ),
        TrialCase(
            "const_volatile_pointer",
            """
void process(const volatile int *reg) {
    int val = *reg;
    while (*reg != val) { val = *reg; }
}
""",
        ),
        TrialCase(
            "comma_operator_in_expr",
            """
int f(void) {
    int a = 1, b = 2;
    int c = (a++, b++, a + b);
    return c;
}
""",
        ),
        TrialCase(
            "sizeof_expression_variants",
            """
typedef struct { int x; double y; } Pair;
int sizes(void) {
    int a = sizeof(int);
    int b = sizeof(Pair);
    Pair p;
    int c = sizeof p;
    int d = sizeof(int *);
    return a + b + c + d;
}
""",
        ),
        TrialCase(
            "conditional_expr_lvalue",
            """
int f(void) {
    int a = 1, b = 2;
    return a > b ? a : b;
}
""",
        ),
        TrialCase(
            "array_of_function_pointers",
            """
typedef int (*binop_fn)(int, int);
int add(int a, int b) { return a + b; }
int sub(int a, int b) { return a - b; }
binop_fn ops[2] = { add, sub };
""",
        ),
        TrialCase(
            "nested_ternary",
            """
int classify(int x) {
    return x > 0 ? 1 : x < 0 ? -1 : 0;
}
""",
        ),
        TrialCase(
            "struct_self_referential_list",
            """
typedef struct node {
    int value;
    struct node *next;
} Node;
Node *prepend(Node *head, int val) {
    static Node n;
    n.value = val;
    n.next = head;
    return &n;
}
""",
        ),
        TrialCase(
            "enum_in_switch",
            """
typedef enum { RED, GREEN, BLUE } Color;
const char *color_name(Color c) {
    switch (c) {
    case RED: return "red";
    case GREEN: return "green";
    case BLUE: return "blue";
    default: return "unknown";
    }
}
""",
        ),
        TrialCase(
            "string_literal_concatenation",
            """
const char *msg = "hello" " " "world";
const char *multiline = "line1\\n"
                        "line2\\n"
                        "line3\\n";
""",
        ),
        TrialCase(
            "cast_expression_complex",
            """
typedef struct { int x; } S;
void f(void) {
    long addr = 0x1000;
    S *p = (S *)(void *)addr;
    int val = (int)(unsigned char)(*((char *)p));
}
""",
        ),
        TrialCase(
            "multiple_declarators_mixed",
            """
int a, *b, **c, arr[10], (*fp)(int);
void f(void) {
    int x = 1, *y = &x, z[3] = {1, 2, 3};
}
""",
        ),
        TrialCase(
            "variadic_macro_with_va_args",
            """
#define DEBUG_PRINT(fmt, ...) ((void)0)
#define LOG(msg, ...) DEBUG_PRINT(msg, __VA_ARGS__)
void f(void) { LOG("hello %d", 42); }
""",
        ),
        TrialCase(
            "anonymous_struct_in_union",
            """
typedef struct {
    union {
        struct { int x; int y; };
        int coords[2];
    };
} Point;
void f(void) { Point p; p.x = 1; p.coords[0] = 2; }
""",
        ),
        TrialCase(
            "flexible_array_member",
            """
typedef struct {
    int len;
    char data[];
} Buffer;
void f(Buffer *b) { b->data[0] = 'a'; }
""",
        ),
        TrialCase(
            "bitfield_declaration",
            """
struct Flags {
    unsigned int readable : 1;
    unsigned int writable : 1;
    unsigned int executable : 1;
    unsigned int : 5;
    unsigned int type : 8;
};
void f(void) { struct Flags fl; fl.readable = 1; }
""",
        ),
        TrialCase(
            "computed_goto_labels_as_values",
            """
void dispatch(int op) {
    static void *table[] = { &&L0, &&L1 };
    goto *table[op];
L0: return;
L1: return;
}
""",
            std="gnu11",
        ),
        TrialCase(
            "typeof_extension",
            """
int f(void) {
    int x = 42;
    __typeof__(x) y = x + 1;
    return y;
}
""",
            std="gnu11",
        ),
        TrialCase(
            "statement_expression",
            """
#define MAX(a, b) ({ __typeof__(a) _a = (a); __typeof__(b) _b = (b); _a > _b ? _a : _b; })
int f(void) { return MAX(3, 5); }
""",
            std="gnu11",
        ),
        TrialCase(
            "attribute_syntax",
            """
__attribute__((unused)) static int helper(void) { return 0; }
__attribute__((noreturn)) void die(void);
int __attribute__((aligned(16))) aligned_var;
""",
            std="gnu11",
        ),
        TrialCase(
            "offsetof_macro",
            """
typedef struct { int a; char b; double c; } S;
#define MY_OFFSETOF(type, member) ((unsigned long)&((type *)0)->member)
unsigned long f(void) { return MY_OFFSETOF(S, c); }
""",
        ),
        TrialCase(
            "nested_function_pointer_typedef",
            """
typedef int (*cmpfunc)(const void *, const void *);
typedef cmpfunc (*cmpfunc_getter)(int);
int compare(const void *a, const void *b) { return *(const int *)a - *(const int *)b; }
cmpfunc get_cmp(int mode) { (void)mode; return compare; }
void f(void) { cmpfunc_getter g = get_cmp; cmpfunc c = g(0); (void)c; }
""",
        ),
        TrialCase(
            "designated_initializer_nested_struct",
            """
struct point { int x; int y; };
struct rect { struct point tl; struct point br; };
struct rect r = { .tl = { .x = 0, .y = 1 }, .br = { .x = 10, .y = 11 } };
""",
        ),
        TrialCase(
            "compound_literal_as_argument",
            """
struct pair { int a; int b; };
int sum(struct pair p) { return p.a + p.b; }
int f(void) { return sum((struct pair){ .a = 3, .b = 4 }); }
""",
        ),
        TrialCase(
            "static_assert_declaration",
            """
_Static_assert(sizeof(int) >= 4, "int too small");
_Static_assert(1, "always true");
""",
        ),
        TrialCase(
            "generic_selection_expr",
            """
#define type_name(x) _Generic((x), \
    int: "int", \
    double: "double", \
    default: "other")
const char *f(void) { int i = 0; return type_name(i); }
""",
        ),
        TrialCase(
            "atomic_type_qualifier",
            """
_Atomic int counter;
void inc(void) { counter = counter + 1; }
""",
        ),
        TrialCase(
            "noreturn_function",
            """
_Noreturn void die(const char *msg);
void f(int x) { if (x < 0) die("negative"); }
""",
        ),
        TrialCase(
            "alignas_and_alignof",
            """
_Alignas(16) char buf[256];
unsigned long a = _Alignof(double);
""",
        ),
        TrialCase(
            "complex_macro_expansion_with_stringize",
            """
#define STR(x) #x
#define XSTR(x) STR(x)
#define VER 3
const char *version = XSTR(VER);
""",
        ),
        TrialCase(
            "function_returning_struct",
            """
struct vec2 { float x; float y; };
struct vec2 make_vec(float x, float y) { struct vec2 v; v.x = x; v.y = y; return v; }
void f(void) { struct vec2 v = make_vec(1.0f, 2.0f); (void)v; }
""",
        ),
        TrialCase(
            "long_long_and_unsigned_literals",
            """
void f(void) {
    long long a = 123456789012345LL;
    unsigned long long b = 0xFFFFFFFFFFFFFFFFULL;
    unsigned u = 42U;
    long l = 100L;
    (void)a; (void)b; (void)u; (void)l;
}
""",
        ),
        TrialCase(
            "conditional_include_guards",
            """
#ifndef MY_HEADER_H
#define MY_HEADER_H
typedef int MyInt;
#endif
MyInt x;
""",
        ),
        TrialCase(
            "multiline_macro_with_do_while",
            """
#define SAFE_FREE(p) do { if (p) { p = (void*)0; } } while (0)
void f(void) { int *p = 0; SAFE_FREE(p); }
""",
        ),
        TrialCase(
            "nested_struct_pointer_chain",
            """
struct A { int val; };
struct B { struct A *a; };
struct C { struct B *b; };
int get(struct C *c) { return c->b->a->val; }
""",
        ),
        TrialCase(
            "array_of_function_pointers",
            """
typedef int (*op_fn)(int, int);
int add(int a, int b) { return a + b; }
int sub(int a, int b) { return a - b; }
op_fn ops[2] = { add, sub };
""",
        ),
        TrialCase(
            "enum_with_explicit_values",
            """
enum color { RED = 1, GREEN = 2, BLUE = 4, WHITE = RED | GREEN | BLUE };
int f(void) { return WHITE; }
""",
        ),
        TrialCase(
            "recursive_struct_with_typedef",
            """
typedef struct node {
    int data;
    struct node *left;
    struct node *right;
} Node;
Node *make(int d) { Node n; n.data = d; n.left = 0; n.right = 0; (void)n; return 0; }
""",
        ),
        TrialCase(
            "void_pointer_arithmetic_cast",
            """
void f(void) {
    char buf[100];
    void *p = buf;
    char *q = (char *)p + 10;
    (void)q;
}
""",
        ),
        TrialCase(
            "static_inline_function",
            """
static inline int max(int a, int b) { return a > b ? a : b; }
int f(void) { return max(3, 5); }
""",
        ),
        TrialCase(
            "const_volatile_pointer",
            """
void f(void) {
    const volatile int * const p = 0;
    (void)p;
}
""",
        ),
        TrialCase(
            "switch_fallthrough_default",
            """
int classify(int x) {
    switch (x) {
    case 0: case 1: return 0;
    case 2: return 1;
    default: return -1;
    }
}
""",
        ),
        TrialCase(
            "bitfield_struct",
            """
struct Flags {
    unsigned int readable : 1;
    unsigned int writable : 1;
    unsigned int executable : 1;
    unsigned int : 5;
    unsigned int type : 8;
};
int get_type(struct Flags f) { return f.type; }
""",
        ),
        TrialCase(
            "flexible_array_member",
            """
typedef struct {
    int length;
    char data[];
} Buffer;
int buf_len(Buffer *b) { return b->length; }
""",
        ),
        TrialCase(
            "anonymous_union_in_struct",
            """
struct Value {
    int kind;
    union {
        int i;
        double d;
        const char *s;
    };
};
int get_int(struct Value *v) { return v->i; }
""",
        ),
        TrialCase(
            "variadic_function_declaration",
            """
int printf(const char *fmt, ...);
int sprintf(char *buf, const char *fmt, ...);
typedef int (*formatter_t)(char *, const char *, ...);
""",
        ),
        TrialCase(
            "typedef_chain_and_pointer_to_array",
            """
typedef int IntArray[10];
typedef IntArray *IntArrayPtr;
typedef const IntArrayPtr ConstIntArrayPtr;
int first(ConstIntArrayPtr p) { return (*p)[0]; }
""",
        ),
        TrialCase(
            "comma_operator_in_for_loop",
            """
int sum_range(int n) {
    int s, i;
    for (s = 0, i = 0; i < n; s += i, i++)
        ;
    return s;
}
""",
        ),
        TrialCase(
            "nested_switch_statement",
            """
int dispatch(int a, int b) {
    switch (a) {
    case 0:
        switch (b) {
        case 0: return 0;
        case 1: return 1;
        }
        return -1;
    case 1: return 10;
    default: return -2;
    }
}
""",
        ),
        TrialCase(
            "sizeof_expression_variants",
            """
typedef struct { int x; double y; } Pair;
int sizes(void) {
    int a = sizeof(int);
    int b = sizeof(Pair);
    Pair p;
    int c = sizeof p;
    int d = sizeof(int *);
    return a + b + c + d;
}
""",
        ),
        TrialCase(
            "ternary_with_side_effects",
            """
int abs_val(int x) {
    return x >= 0 ? x : -x;
}
int max3(int a, int b, int c) {
    return a > b ? (a > c ? a : c) : (b > c ? b : c);
}
""",
        ),
        TrialCase(
            "extern_and_static_linkage",
            """
extern int global_count;
static int local_count = 0;
static int increment(void) { return ++local_count; }
extern int get_global(void);
""",
        ),
        TrialCase(
            "designated_initializer_struct",
            """
struct point { int x; int y; int z; };
struct point p = { .z = 3, .x = 1, .y = 2 };
""",
        ),
        TrialCase(
            "designated_initializer_array",
            """
int arr[10] = { [3] = 30, [7] = 70 };
""",
        ),
        TrialCase(
            "compound_literal",
            """
struct pair { int a; int b; };
struct pair *get_pair(void) {
    return &(struct pair){ .a = 1, .b = 2 };
}
""",
        ),
        TrialCase(
            "generic_selection",
            """
#define type_name(x) _Generic((x), \
    int: "int", \
    double: "double", \
    default: "other")
const char *name = type_name(42);
""",
        ),
        TrialCase(
            "static_assert_declaration",
            """
_Static_assert(sizeof(int) >= 4, "int must be at least 4 bytes");
typedef struct { int x; } checked_t;
""",
        ),
        TrialCase(
            "nested_designated_init",
            """
struct inner { int val; };
struct outer { struct inner a; struct inner b; };
struct outer o = { .a = { .val = 10 }, .b.val = 20 };
""",
        ),
        TrialCase(
            "function_pointer_typedef_complex",
            """
typedef int (*cmp_fn)(const void *, const void *);
typedef cmp_fn (*cmp_factory)(int);
cmp_factory get_factory(void);
""",
        ),
        TrialCase(
            "pragma_once_and_line",
            """
#pragma once
#line 100 "fake.c"
int x = 1;
""",
        ),
        TrialCase(
            "multi_declarator_with_init",
            """
int a = 1, b = 2, *c = &a, d[3] = {1, 2, 3};
""",
        ),
        TrialCase(
            "empty_struct_and_zero_length_array",
            """
struct empty {};
struct flex { int n; char data[]; };
struct flex *make_flex(int n);
""",
        ),
        TrialCase(
            "computed_goto_labels_as_values",
            """
void dispatch(int op) {
    static void *table[] = { &&L_ADD, &&L_SUB, &&L_RET };
    goto *table[op];
L_ADD: return;
L_SUB: return;
L_RET: return;
}
""",
            std="gnu11",
        ),
        TrialCase(
            "typeof_extension",
            """
int x = 42;
__typeof__(x) y = x + 1;
__typeof__(x + 0.5) z = 3.14;
""",
            std="gnu11",
        ),
        TrialCase(
            "statement_expression_gnu",
            """
#define MAX(a, b) ({ __typeof__(a) _a = (a); __typeof__(b) _b = (b); _a > _b ? _a : _b; })
int test(void) { return MAX(3, 5); }
""",
            std="gnu11",
        ),
        TrialCase(
            "attribute_packed_struct",
            """
struct __attribute__((packed)) wire_header {
    unsigned char type;
    unsigned int length;
    unsigned short flags;
};
""",
        ),
        TrialCase(
            "attribute_aligned_variable",
            """
int data __attribute__((aligned(16)));
struct __attribute__((aligned(64))) cacheline { char buf[64]; };
""",
        ),
        TrialCase(
            "nested_function_pointer_param",
            """
typedef int (*cmpfunc)(const void *, const void *);
void sort(void *base, int n, int size, cmpfunc cmp);
int my_cmp(const void *a, const void *b) { return *(const int*)a - *(const int*)b; }
""",
        ),
        TrialCase(
            "multiple_storage_class_extern_inline",
            """
extern inline int fast_add(int a, int b) { return a + b; }
static inline int fast_sub(int a, int b) { return a - b; }
""",
        ),
        TrialCase(
            "complex_cast_chain",
            """
void test(void) {
    void *p = (void*)0;
    int *ip = (int*)(void*)(char*)p;
    const volatile int *cvip = (const volatile int *)ip;
    (void)cvip;
}
""",
        ),
        TrialCase(
            "multiline_string_concat",
            """
const char *msg = "Hello, "
                  "world! "
                  "This is "
                  "a long string.";
""",
        ),
        TrialCase(
            "struct_self_referencing_list",
            """
struct node {
    int value;
    struct node *next;
    struct node *prev;
};
struct node *list_append(struct node *head, int val);
struct node sentinel = { .value = -1, .next = &sentinel, .prev = &sentinel };
""",
        ),
        TrialCase(
            "variadic_macro_with_va_args",
            """
#define PY_DEBUG_LOG(fmt, ...) ((void)0)
void foo(void) { PY_DEBUG_LOG("hello %d", 42); }
""",
        ),
        TrialCase(
            "enum_with_trailing_comma",
            """
enum PyMemberType {
    T_SHORT = 0,
    T_INT,
    T_LONG,
    T_FLOAT,
    T_DOUBLE,
    T_STRING,
};
""",
        ),
        TrialCase(
            "flexible_array_member",
            """
typedef struct {
    long ob_refcnt;
    int ob_size;
    char ob_val[];
} PyBytesObject;
""",
        ),
        TrialCase(
            "anonymous_union_in_struct",
            """
struct PyValue {
    int kind;
    union {
        long i;
        double d;
        void *p;
    };
};
void use(struct PyValue *v) { v->i = 42; }
""",
        ),
        TrialCase(
            "bit_field_declarations",
            """
struct PyFlags {
    unsigned int optimized : 1;
    unsigned int nested : 1;
    unsigned int generator : 1;
    unsigned int coroutine : 1;
    unsigned int : 4;
    unsigned int reserved : 24;
};
""",
        ),
        TrialCase(
            "do_while_zero_macro",
            """
#define Py_INCREF(op) do { (op)->ob_refcnt++; } while (0)
struct _object { long ob_refcnt; };
void inc(struct _object *o) { Py_INCREF(o); }
""",
        ),
        TrialCase(
            "conditional_include_guard",
            """
#ifndef Py_OBJECT_H
#define Py_OBJECT_H
typedef struct _object { long ob_refcnt; } PyObject;
#endif
#ifndef Py_OBJECT_H
typedef int SHOULD_NOT_APPEAR;
#endif
PyObject x;
""",
        ),
        TrialCase(
            "const_volatile_pointer_chain",
            """
const volatile int * const * volatile pp;
void f(const char * const *argv) { (void)argv; }
""",
        ),
        TrialCase(
            "array_of_function_pointers",
            """
typedef int (*initproc)(void *, void *, void *);
typedef void (*destructor)(void *);
typedef struct {
    initproc tp_init;
    destructor tp_dealloc;
} slotdef;
slotdef slots[] = { {0, 0}, {0, 0} };
""",
        ),
        TrialCase(
            "inline_function_definition",
            """
static inline int _Py_IsNone(const void *ob) {
    return ob == 0;
}
int check(void *o) { return _Py_IsNone(o); }
""",
        ),
        TrialCase(
            "designated_initializer_nested_struct",
            """
struct point { int x; int y; };
struct rect { struct point tl; struct point br; };
struct rect r = { .tl = { .x = 0, .y = 0 }, .br = { .x = 10, .y = 20 } };
""",
        ),
        TrialCase(
            "compound_literal_in_expression",
            """
struct pair { int a; int b; };
int sum(void) {
    struct pair p = (struct pair){ .a = 3, .b = 4 };
    return p.a + p.b;
}
""",
        ),
        TrialCase(
            "static_assert_declaration",
            """
_Static_assert(sizeof(int) >= 4, "int too small");
_Static_assert(1, "always true");
""",
        ),
        TrialCase(
            "generic_selection_expression",
            """
#define type_name(x) _Generic((x), \
    int: "int", \
    double: "double", \
    default: "other")
const char *name = type_name(42);
""",
        ),
        TrialCase(
            "variadic_function_declaration",
            """
int printf(const char *fmt, ...);
int snprintf(char *buf, unsigned long size, const char *fmt, ...);
void log_msg(const char *level, const char *fmt, ...);
""",
        ),
        TrialCase(
            "union_with_anonymous_members",
            """
struct value {
    int kind;
    union {
        int i;
        double d;
        const char *s;
    };
};
int get_int(struct value v) { return v.i; }
""",
        ),
        TrialCase(
            "pointer_to_array_parameter",
            """
void fill(int (*arr)[10]) {
    for (int i = 0; i < 10; i++)
        (*arr)[i] = i;
}
""",
        ),
        TrialCase(
            "function_returning_function_pointer",
            """
typedef int (*binop)(int, int);
int add(int a, int b) { return a + b; }
binop get_op(void) { return add; }
""",
        ),
        TrialCase(
            "complex_macro_token_pasting",
            """
#define CONCAT(a, b) a##b
#define MAKE_FUNC(name) int CONCAT(func_, name)(void) { return 0; }
MAKE_FUNC(alpha)
MAKE_FUNC(beta)
""",
        ),
        TrialCase(
            "atomic_type_qualifier",
            """
_Atomic int counter;
_Atomic(unsigned long) flags;
void inc(void) { counter = counter + 1; }
""",
        ),
        TrialCase(
            "typedef_function_pointer_array",
            """
typedef int (*handler_t)(void *, int);
handler_t handlers[16];
int dispatch(int idx, void *ctx, int arg) { return handlers[idx](ctx, arg); }
""",
        ),
        TrialCase(
            "nested_struct_with_bitfields",
            """
struct outer {
    struct inner {
        unsigned int a : 3;
        unsigned int b : 5;
        unsigned int c : 8;
    } fields;
    int tag;
};
""",
        ),
        TrialCase(
            "enum_used_as_array_size",
            """
enum { BUF_SIZE = 256 };
char buffer[BUF_SIZE];
void clear(void) { buffer[0] = 0; }
""",
        ),
        TrialCase(
            "recursive_macro_guard",
            """
#define FOO(x) ((x) + BAR(x))
#define BAR(x) ((x) * 2)
int val = FOO(3);
""",
        ),
        TrialCase(
            "void_pointer_arithmetic_cast",
            """
void *advance(void *p, int n) {
    return (char *)p + n;
}
""",
        ),
        TrialCase(
            "static_inline_with_local_static",
            """
static inline int counter(void) {
    static int n = 0;
    return n++;
}
""",
        ),
        TrialCase(
            "comma_operator_in_for",
            """
void fill(int *a, int n) {
    int i, j;
    for (i = 0, j = n - 1; i < j; i++, j--) {
        int tmp = a[i];
        a[i] = a[j];
        a[j] = tmp;
    }
}
""",
        ),
        TrialCase(
            "sizeof_expression_in_malloc",
            """
typedef struct node { int val; struct node *next; } Node;
void *alloc(void *(*malloc_fn)(unsigned long)) {
    return malloc_fn(sizeof(Node));
}
""",
        ),
        TrialCase(
            "string_literal_concatenation_wide",
            """
const char msg[] = "hello " "world" "!";
const char multi[] = "line1\\n"
                     "line2\\n"
                     "line3\\n";
""",
        ),
        TrialCase(
            "ternary_in_initializer",
            """
int debug = 0;
int level = debug ? 3 : 1;
const char *mode = level > 2 ? "verbose" : "quiet";
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
