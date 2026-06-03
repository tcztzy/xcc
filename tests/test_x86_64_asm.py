import platform
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests import _bootstrap  # noqa: F401
from xcc.frontend import compile_source
from xcc.options import FrontendOptions
from xcc.x86_64_asm import generate_x86_64_asm


class X86_64AsmTests(unittest.TestCase):
    def _asm(self, source: str) -> str:
        options = FrontendOptions(
            std="gnu11",
            no_standard_includes=True,
            host_machine="x86_64",
            target_os="linux",
        )
        return generate_x86_64_asm(compile_source(source, filename="test.c", options=options))

    def _run(self, source: str) -> int:
        if not (platform.system() == "Linux" and platform.machine() == "x86_64"):
            self.skipTest("native x86_64 Linux assembler is not available on this host")
        if shutil.which("cc") is None:
            self.skipTest("cc is not available")
        asm = self._asm(source)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            asm_path = root / "input.s"
            exe_path = root / "a.out"
            asm_path.write_text(asm, encoding="utf-8")
            assemble = subprocess.run(
                ["cc", str(asm_path), "-o", str(exe_path)],
                capture_output=True,
                check=False,
                text=True,
            )
            self.assertEqual(assemble.returncode, 0, assemble.stderr)
            run = subprocess.run([str(exe_path)], check=False)
            return run.returncode

    def test_emits_constant_return_function(self) -> None:
        asm = self._asm("int f(void){return 7;}")
        self.assertIn(".intel_syntax noprefix", asm)
        self.assertIn(".globl f\nf:", asm)
        self.assertIn("    mov eax, 7", asm)
        self.assertNotIn("define i32", asm)

    def test_block_scope_function_declaration_does_not_allocate_local_slot(self) -> None:
        asm = self._asm(
            """
int main(void) {
  long magic(void);
  return magic() == 17 ? 0 : 1;
}
long magic(void) {
  return 17;
}
"""
        )
        self.assertIn("    call magic", asm)
        self.assertNotIn("Unknown local declaration", asm)

    def test_block_scope_extern_function_declaration_emits_direct_call(self) -> None:
        asm = self._asm(
            """
int main(void) {
  extern int callee(int);
  return callee(7);
}
"""
        )
        self.assertIn("    call callee", asm)
        self.assertNotIn("call r11", asm)

    def test_local_function_pointer_shadows_same_named_function(self) -> None:
        asm = self._asm(
            """
int dict_contains(int x) { return x + 100; }
int dictkeys_contains(int x) { return x + 7; }
int caller(int x) {
  int (*dict_contains)(int);
  dict_contains = dictkeys_contains;
  return dict_contains(x);
}
"""
        )
        caller_asm = asm.split("caller:", 1)[1]
        self.assertIn("    call r11", caller_asm)
        self.assertNotIn("    call dict_contains", caller_asm)

    def test_integer_to_bool_normalizes_nonzero_before_store(self) -> None:
        asm = self._asm(
            """
int f(void) {
  _Bool future_annotations = 0x1000000;
  return future_annotations ? 0 : 1;
}
"""
        )
        self.assertIn("    cmp eax, 0", asm)
        self.assertIn("    setne al", asm)
        self.assertIn("    movzx eax, al", asm)
        self.assertNotIn("    and eax, 255", asm)

    def test_transparent_union_parameter_call_accepts_member_pointer(self) -> None:
        asm = self._asm(
            """
struct sockaddr { int family; };
typedef union {
  struct sockaddr *sa;
} SockArg __attribute__((__transparent_union__));
int accept4(int fd, SockArg addr, unsigned int *len, int flags);
int f(struct sockaddr *addr, unsigned int *len) {
  return accept4(3, addr, len, 0);
}
"""
        )
        self.assertIn("    call accept4", asm)

    def test_discarded_indirect_aggregate_call_gets_sret_slot(self) -> None:
        asm = self._asm(
            """
struct Status { long a; long b; long c; };
struct Status init_runtime(void);
void f(void) {
  init_runtime();
}
"""
        )
        self.assertIn("    lea rcx, [rbp -", asm)
        self.assertIn("    push rcx", asm)
        self.assertIn("    mov rdi, QWORD PTR [rsp + 8]", asm)
        self.assertIn("    call init_runtime", asm)

    def test_nested_call_argument_preserves_sysv_stack_alignment(self) -> None:
        asm = self._asm(
            """
long first(void);
long second(void);
void sink(long a, long b);
void f(void) {
  sink(first(), second());
}
"""
        )
        self.assertIn(
            "    call second\n"
            "    push rax\n"
            "    push 0\n"
            "    mov eax, 0\n"
            "    call first\n"
            "    add rsp, 8\n"
            "    push rax",
            asm,
        )

    def test_global_double_initializer_accepts_constant_expression(self) -> None:
        asm = self._asm(
            """
static const double value = 9007199254740992. * 9007199254740992.e-256;
double f(void) { return value; }
"""
        )
        self.assertIn("    .quad 0x1168062864ac6f43", asm)

    def test_local_array_bound_sizeof_prior_local_identifier(self) -> None:
        asm = self._asm(
            """
typedef unsigned long uint64_t;
typedef unsigned char uint8_t;
void f(void) {
  uint64_t marker;
  uint8_t tmp[sizeof(marker)];
  tmp[0] = 0;
}
"""
        )
        self.assertIn("    sub rsp, 16", asm)
        self.assertIn("    lea rcx, [rbp - 16]", asm)
        self.assertIn("    mov BYTE PTR [rcx], al", asm)

    def test_sizeof_completed_local_array_uses_frame_slot_type(self) -> None:
        asm = self._asm(
            """
struct State { unsigned char c[8]; };
struct Obj { struct State state; };
void sink(unsigned long);
void f(struct Obj *self) {
  unsigned char statebytes[1 + 2 * 4 + sizeof(self->state.c)];
  sink(sizeof(statebytes));
}
"""
        )
        self.assertIn("    sub rsp, 32", asm)
        self.assertIn("    mov eax, 17", asm)

    def test_global_integer_initializer_accepts_comma_constant_expression(self) -> None:
        asm = self._asm(
            """
static int handlers[3];
static const unsigned long count =
    sizeof(handlers) / sizeof(handlers[0]) + ((void)sizeof(struct { int dummy; }), 0);
unsigned long f(void) { return count; }
"""
        )
        self.assertIn("    .quad 3", asm)

    def test_global_integer_initializer_accepts_float_to_int_cast(self) -> None:
        asm = self._asm(
            """
static const long max_amp = (long)100.0f;
long f(void) { return max_amp; }
"""
        )
        self.assertIn("    .quad 100", asm)

    def test_global_pointer_initializer_accepts_constant_conditional_subobject(self) -> None:
        asm = self._asm(
            """
struct Obj { int value; };
struct Obj ascii[128];
struct Obj latin1[128];
struct Obj *name = 'n' < 128 ? &ascii['n'] : &latin1['n' - 128];
"""
        )
        self.assertIn("    .quad ascii + 440", asm)

    def test_global_pointer_initializer_accepts_array_symbol_plus_offset(self) -> None:
        asm = self._asm(
            """
static const unsigned short table[] = {1, 2, 3};
struct Index { const unsigned short *map; int lo; int hi; };
static const struct Index indexes[] = {
  {table + 1, 33, 126},
};
const unsigned short *f(void) { return indexes[0].map; }
"""
        )
        self.assertIn("    .quad .L.table + 2", asm)

    def test_emits_params_locals_and_arithmetic(self) -> None:
        asm = self._asm("int add(int a, int b){ int c=a+b; return c*2; }")
        self.assertIn("    mov DWORD PTR [rbp - 4], edi", asm)
        self.assertIn("    mov DWORD PTR [rbp - 8], esi", asm)
        self.assertIn("    add eax, r10d", asm)
        self.assertIn("    imul eax, r10d", asm)

    def test_sizeof_record_with_flexible_array_excludes_tail_array(self) -> None:
        asm = self._asm(
            "struct S { char tag; long values[]; }; long f(void) { return sizeof(struct S); }"
        )
        self.assertIn("    mov eax, 8", asm)
        self.assertIn("    movsxd rax, eax", asm)

    def test_anonymous_typedef_record_matching_uses_member_array_lengths(self) -> None:
        asm = self._asm(
            """
typedef struct { long ref; void *type; } Obj;
#define HEAD Obj ob_base; long hashcode; char hastzinfo;
typedef struct { HEAD unsigned char data[6]; } BaseTime;
typedef struct { HEAD unsigned char data[6]; unsigned char fold; void *tzinfo; } Time;
typedef struct { HEAD unsigned char data[10]; } BaseDateTime;
typedef struct { HEAD unsigned char data[10]; unsigned char fold; void *tzinfo; } DateTime;
long base_size(void) { return sizeof(BaseDateTime); }
long full_size(void) { return sizeof(DateTime); }
long fold_offset(DateTime *p) { return (char *)&p->fold - (char *)p; }
long tz_offset(DateTime *p) { return (char *)&p->tzinfo - (char *)p; }
"""
        )
        self.assertIn("base_size:\n    push rbp\n    mov rbp, rsp\n    mov eax, 40", asm)
        self.assertIn("full_size:\n    push rbp\n    mov rbp, rsp\n    mov eax, 48", asm)
        self.assertIn("    add rax, 35", asm)
        self.assertIn("    add rax, 40", asm)

    def test_anonymous_typedef_record_matching_normalizes_enum_members(self) -> None:
        asm = self._asm(
            """
	typedef struct {
	  enum { STATUS_OK = 0, STATUS_ERR = 1 } kind;
	  const char *message;
	} Status;
	Status make_status(void);
	Status f(void) {
	  Status status = make_status();
	  return status;
	}
"""
        )
        self.assertIn(".globl f\nf:", asm)

    def test_anonymous_typedef_record_matching_preserves_opaque_tagged_pointers(self) -> None:
        asm = self._asm(
            """
	struct Arena;
	typedef struct {
	  int level;
	  struct Arena *arena;
	} Parser;
	long f(void) { return sizeof(Parser); }
"""
        )
        self.assertIn("f:\n    push rbp\n    mov rbp, rsp\n    mov eax, 16", asm)

    def test_flexible_array_member_access_has_offset(self) -> None:
        asm = self._asm(
            "struct S { char tag; long values[]; }; long *f(struct S *s) { return &s->values[1]; }"
        )
        self.assertIn("    add rax, 8", asm)
        self.assertIn("    add rax, r10", asm)

    def test_flexible_array_member_expression_decays_to_pointer(self) -> None:
        asm = self._asm(
            "struct S { int used; char bytes[]; }; "
            "char *f(struct S *s) { return (char *)s->bytes; }"
        )
        self.assertIn("    mov rax, QWORD PTR [rbp - 8]", asm)
        self.assertIn("    add rax, 4", asm)

    def test_global_record_initializer_omits_flexible_array_storage(self) -> None:
        asm = self._asm("struct S { int used; char bytes[]; }; struct S value = { .used = 1 };")
        self.assertIn("value:", asm)
        self.assertIn("    .long 1", asm)
        self.assertNotIn(".zero -1", asm)

    def test_emits_sysv_floating_parameters_calls_and_return(self) -> None:
        asm = self._asm(
            """
double add(double a, double b) { return a + b; }
double ninth(
  double a, double b, double c, double d, double e,
  double f, double g, double h, double i
) { return i; }
int main(void) {
  double x = add(1.25, 2.75);
  double y = ninth(1, 2, 3, 4, 5, 6, 7, 8, 9);
  return x == 4.0 && y == 9.0 ? 0 : 1;
}
"""
        )
        self.assertIn("    movsd [rbp - 8], xmm0", asm)
        self.assertIn("    movsd [rbp - 16], xmm1", asm)
        self.assertIn("    addsd xmm0, xmm1", asm)
        self.assertIn("    movsd xmm0, [rbp + 16]", asm)
        self.assertIn("    mov eax, 8", asm)
        self.assertIn("    ucomisd xmm0, xmm1", asm)

    def test_builtin_isinf_sign_lowers_without_external_call(self) -> None:
        asm = self._asm("int sign_inf(double value) { return __builtin_isinf_sign(value); }")
        self.assertIn("    movq r11, xmm0", asm)
        self.assertIn("    cmp r10, rax", asm)
        self.assertIn("    neg eax", asm)
        self.assertNotIn("call __builtin_isinf_sign", asm)

    def test_builtin_signbit_lowers_without_external_call(self) -> None:
        asm = self._asm("int sign(double value) { return __builtin_signbit(value); }")
        self.assertIn("    movq r11, xmm0", asm)
        self.assertIn("    shr r11, 63", asm)
        self.assertNotIn("call __builtin_signbit", asm)

    def test_builtin_isnormal_lowers_without_external_call(self) -> None:
        asm = self._asm("int normal(double value) { return __builtin_isnormal(value); }")
        self.assertIn("    mov rax, 0x000fffffffffffff", asm)
        self.assertIn("    setb r11b", asm)
        self.assertNotIn("call __builtin_isnormal", asm)

    def test_long_double_literal_uses_double_constant_path(self) -> None:
        asm = self._asm("double value(void) { return (double)1.25L; }")
        self.assertIn("    movsd xmm0, [rip + .LCF0]", asm)
        self.assertIn("    .quad 0x3ff4000000000000", asm)

    def test_builtin_memset_lowers_to_libc_symbol(self) -> None:
        asm = self._asm("void *f(char *p) { return __builtin_memset(p, 0, 4); }")
        self.assertIn("    call memset", asm)
        self.assertNotIn("call __builtin_memset", asm)

    def test_common_gcc_builtins_lower_without_external_symbols(self) -> None:
        asm = self._asm(
            """
typedef __builtin_va_list va_list;
int bits(unsigned x, unsigned long y, unsigned long long z) {
  return __builtin_bswap32(x) + __builtin_ctzll(z)
      + __builtin_popcount(x) + __builtin_clzl(y);
}
void *frame(void) {
  return __builtin_frame_address(0);
}
void *stack_alloc(unsigned long size) {
  return __builtin_alloca(size);
}
float constants(void) {
  return __builtin_inff() + __builtin_nanf("");
}
void copy_va(int marker, ...) {
  va_list src;
  va_list dst;
  __builtin_va_start(src, marker);
  __builtin_va_copy(dst, src);
  __builtin_va_end(dst);
}
void stop(void) {
  __builtin_unreachable();
}
"""
        )
        self.assertIn("    bswap eax", asm)
        self.assertIn("    bsf rax, rax", asm)
        self.assertIn("    bsr rax, rax", asm)
        self.assertIn("popcount_loop", asm)
        self.assertIn("    mov rax, rbp", asm)
        self.assertIn("    sub rsp, rax", asm)
        self.assertIn("    ud2", asm)
        self.assertIn("    mov QWORD PTR [rcx], r10", asm)
        self.assertNotIn("call __builtin_", asm)

    def test_cast_pointer_deref_assignment_uses_requested_address_register(self) -> None:
        asm = self._asm("void f(void *dst, void *src) { *(int *)dst = *(int *)src; }")
        self.assertIn("    mov rax, QWORD PTR [rbp - 8]", asm)
        self.assertIn("    mov rcx, rax", asm)
        self.assertIn("    mov DWORD PTR [rcx], eax", asm)

    def test_statement_expression_with_local_decl_returns_last_expression(self) -> None:
        asm = self._asm(
            """
unsigned long f(unsigned long cpu, unsigned long setsize) {
  return ({ unsigned long __cpu = cpu; __cpu < setsize ? __cpu + 1 : 0; });
}
"""
        )
        self.assertIn("    mov QWORD PTR [rbp -", asm)
        self.assertIn("    add rax, r10", asm)
        self.assertIn("    cmp rax, r10", asm)

    def test_atomic_fetch_and_compare_exchange_lower_without_libatomic_calls(self) -> None:
        asm = self._asm(
            """
unsigned long add(unsigned long *p) {
  return __atomic_fetch_add(p, 1, 5);
}
int cas(int *p, int *expected, int desired) {
  return __atomic_compare_exchange_n(p, expected, desired, 0, 5, 5);
}
"""
        )
        self.assertIn("    lock xadd QWORD PTR [rcx], rax", asm)
        self.assertIn("    lock cmpxchg DWORD PTR [rcx], r11d", asm)
        self.assertNotIn("call __atomic", asm)

    def test_call_arguments_decay_string_literals_to_pointers(self) -> None:
        asm = self._asm(
            """
int first(const char *s) { return s[0]; }
int main(void) { return first("ok") == 'o' ? 0 : 1; }
"""
        )
        self.assertIn("    lea rax, [rip + .LC0]", asm)
        self.assertIn("    pop rdi", asm)
        self.assertIn("    call first", asm)

    def test_array_operands_decay_for_pointer_arithmetic(self) -> None:
        asm = self._asm(
            """
	char *advance(int offset) { return "abcdefghijklmnopqrst" + offset; }
"""
        )
        self.assertIn("    lea rax, [rip + .LC0]", asm)
        self.assertIn("    add rax, r10", asm)

    def test_pointer_compound_assignment_scales_variable_offset(self) -> None:
        asm = self._asm(
            """
	typedef unsigned long size_t;
	void bump(long **cursor, size_t offs) { cursor += offs; }
"""
        )
        self.assertIn("    imul rax, 8", asm)
        self.assertIn("    add rax, r10", asm)

    def test_postfix_pointer_update_under_deref_updates_pointer_slot(self) -> None:
        asm = self._asm(
            """
void f(long **stack, long *value) {
  long **sp = stack;
  *sp++ = value;
}
"""
        )
        self.assertIn("    lea r8, [rbp -", asm)
        self.assertIn("    mov rcx, QWORD PTR [r8]", asm)
        self.assertIn("    add rcx, 8", asm)
        self.assertIn("    mov QWORD PTR [r8], rcx", asm)
        self.assertNotIn("    mov QWORD PTR [rcx], rcx", asm)

    def test_for_init_declaration_scope_does_not_escape(self) -> None:
        asm = self._asm(
            """
int f(int i, int n) {
  for (int i = 0; i < n; i++) {
  }
  return i;
}
"""
        )
        self.assertIn(".L.f.for_end.3:\n    mov eax, DWORD PTR [rbp - 4]", asm)

    def test_shadowed_pointer_local_slot_keeps_pointer_width(self) -> None:
        asm = self._asm(
            """
struct C {
  void *filename;
  void *name;
  void *qualname;
  int flags;
  void *code;
  int first;
};
void *read(void);
void sink(struct C *);
void f(int tag) {
  int code = tag;
  if (tag) {
    void *filename = read();
    void *name = read();
    void *qualname = read();
    void *code = read();
    struct C con = {
      .filename = filename,
      .name = name,
      .qualname = qualname,
      .flags = 7,
      .code = code,
      .first = 11,
    };
    sink(&con);
  }
}
"""
        )
        self.assertIn(
            "    mov rax, QWORD PTR [rbp - 40]\n"
            "    pop rcx\n"
            "    lea r11, [rcx + 32]\n"
            "    mov QWORD PTR [r11], rax",
            asm,
        )
        self.assertNotIn(
            "    movsxd rax, eax\n"
            "    pop rcx\n"
            "    lea r11, [rcx + 32]",
            asm,
        )

    def test_array_operand_decays_for_unary_deref(self) -> None:
        asm = self._asm('int first(void) { return *"x"; }')
        self.assertIn("    lea rax, [rip + .LC0]", asm)
        self.assertIn("    movsx eax, BYTE PTR [rax]", asm)

    def test_wide_string_literal_emits_wchar_sized_units(self) -> None:
        asm = self._asm('int *errors(void) { return L"ab"; }')
        self.assertIn(
            "    .byte 97, 0, 0, 0, 98, 0, 0, 0, 0, 0, 0, 0",
            asm,
        )

    def test_wide_string_literal_is_aligned_after_byte_string(self) -> None:
        asm = self._asm('char *dash(void) { return "-"; } int *wide(void) { return L"strict"; }')
        wide_label = asm.index("    .byte 115, 0, 0, 0, 116, 0, 0, 0")
        self.assertIn(".p2align 2\n.LC1:", asm[:wide_label])

    def test_string_literal_subscript_forms_literal_address(self) -> None:
        asm = self._asm('int second(void) { return "abc"[1]; }')
        self.assertIn("    lea rax, [rip + .LC0]", asm)
        self.assertIn("    add rax, r10", asm)
        self.assertIn("    movsx eax, BYTE PTR [rax]", asm)

    def test_floating_unary_deref_uses_gpr_address_and_xmm_load(self) -> None:
        asm = self._asm("int f(double *value) { return *value < 1.0; }")
        self.assertIn("    mov rax, QWORD PTR [rbp - 8]", asm)
        self.assertIn("    movsd xmm0, [rax]", asm)

    def test_array_operand_decays_before_pointer_cast(self) -> None:
        asm = self._asm('char *empty(void) { return (char *)""; }')
        self.assertIn("    lea rax, [rip + .LC0]", asm)
        self.assertNotIn("cannot scalarize", asm)

    def test_array_operand_decays_before_integer_cast(self) -> None:
        asm = self._asm(
            """
typedef unsigned long uintptr_t;
int f(void) {
  char frame[88];
  return (uintptr_t)frame != 0;
}
"""
        )
        self.assertIn("    lea rax, [rbp -", asm)
        self.assertIn("    cmp rax, r10", asm)

    def test_extern_data_symbols_use_got_relocations(self) -> None:
        asm = self._asm(
            """
extern long PyExc_ValueError;
extern int _Py_NoneStruct;
long value(void) { return PyExc_ValueError; }
int *addr(void) { return &_Py_NoneStruct; }
"""
        )
        self.assertIn(
            "    mov rax, QWORD PTR [rip + PyExc_ValueError@GOTPCREL]\n"
            "    mov rax, QWORD PTR [rax]",
            asm,
        )
        self.assertIn("    mov rax, QWORD PTR [rip + _Py_NoneStruct@GOTPCREL]", asm)

    def test_extern_function_designator_uses_got_relocation(self) -> None:
        asm = self._asm(
            """
int target(void);
int (*addr(void))(void) { return target; }
"""
        )
        self.assertIn("    mov rax, QWORD PTR [rip + target@GOTPCREL]", asm)

    def test_comma_array_expression_address_uses_right_operand(self) -> None:
        asm = self._asm("int second(void) { int values[2]; return (0, values)[1]; }")
        self.assertIn("    lea rax, [rbp - 8]", asm)
        self.assertIn("    add rax, r10", asm)

    def test_file_scope_enum_identifier_lowers_to_constant(self) -> None:
        asm = self._asm(
            """
enum { SOCK_STREAM = 1, AF_INET = 2 };
int main(void) { return SOCK_STREAM + AF_INET == 3 ? 0 : 1; }
"""
        )
        self.assertIn("    mov eax, 1", asm)
        self.assertIn("    mov eax, 2", asm)
        self.assertNotIn("SOCK_STREAM", asm)
        self.assertNotIn("AF_INET", asm)

    def test_c_octal_integer_literals_parse(self) -> None:
        asm = self._asm("int main(void) { return 0377 == 255 ? 0 : 1; }")
        self.assertIn("    mov eax, 255", asm)

    def test_large_unsigned_switch_case_materializes_compare_immediate(self) -> None:
        asm = self._asm(
            """
int f(unsigned long value) {
  switch (value) {
    case 4611686018427387905UL: return 1;
    default: return 0;
  }
}
"""
        )
        self.assertIn("    mov r10, 4611686018427387905", asm)
        self.assertIn("    cmp rax, r10", asm)

    def test_tagged_enum_parameters_use_int_abi_slots(self) -> None:
        asm = self._asm(
            """
enum _expr_context { Load = 1, Store = 2, Del = 3 };
int use(enum _expr_context ctx) { return ctx == Store ? 0 : 1; }
"""
        )
        self.assertIn("    mov DWORD PTR [rbp - 4], edi", asm)
        self.assertIn("    cmp eax, r10d", asm)

    def test_enum_objects_participate_in_pointer_arithmetic_as_ints(self) -> None:
        asm = self._asm(
            """
enum Offset { ONE = 1 };
char *advance(char *p, enum Offset offset) { return p + offset; }
"""
        )
        self.assertIn("    add rax, r10", asm)

    def test_global_pointer_initializer_accepts_compound_literal_array(self) -> None:
        asm = self._asm(
            """
struct Entry { char *str; int type; };
struct Entry *sentinel = (struct Entry[]){ { (void *)0, -1 } };
"""
        )
        self.assertIn("sentinel:\n    .quad .Lcompound0", asm)
        self.assertIn(".Lcompound0:", asm)
        self.assertIn("    .quad 0", asm)
        self.assertIn("    .long 4294967295", asm)

    def test_array_compound_literal_decays_as_call_argument(self) -> None:
        asm = self._asm(
            """
long sum(int *items, long count);
long f(int a, int b, int c) {
  return sum((int[]){a, b, c}, 3);
}
"""
        )
        self.assertIn("    lea rcx, [rbp -", asm)
        self.assertIn("    mov rax, rcx", asm)
        self.assertIn("    call sum", asm)

    def test_global_record_initializer_accepts_function_pointer_address(self) -> None:
        asm = self._asm(
            """
struct Methods { int (*call)(int); };
int invoke(int value) { return value; }
struct Methods methods = { .call = &invoke };
"""
        )
        self.assertIn("methods:", asm)
        self.assertIn("    .quad invoke", asm)

    def test_global_pointer_initializer_accepts_array_element_member_address(self) -> None:
        asm = self._asm(
            """
struct Node { struct Node *next; long value; };
struct Bucket { long tag; struct Node root; struct Node *ptr; };
struct Bucket buckets[1] = { { 7, { 0, 0 }, &buckets[0].root } };
"""
        )
        self.assertIn("buckets:", asm)
        self.assertIn("    .quad buckets + 8", asm)

    def test_global_pointer_initializer_decays_nested_array_member_address(self) -> None:
        asm = self._asm(
            """
struct Dtoa { int tag; double preallocated[4]; };
struct Interp { long head; struct Dtoa dtoa; };
struct Runtime { long prefix; struct Interp main; };
struct Runtime runtime;
struct Holder { double *ptr; };
struct Holder holder = { .ptr = (&runtime.main)->dtoa.preallocated };
"""
        )
        self.assertIn("holder:", asm)
        self.assertIn("    .quad runtime + 24", asm)

    def test_record_compound_literal_assignment_stores_members(self) -> None:
        asm = self._asm(
            """
enum Mode { REGULAR = 1 };
struct ModeState { int kind; char quote; int in_debug; };
int main(void) {
  struct ModeState stack[1];
  stack[0] = (struct ModeState){.kind = REGULAR, .quote = '\\0', .in_debug = 0};
  return stack[0].kind == REGULAR ? 0 : 1;
}
"""
        )
        self.assertIn("    mov DWORD PTR [r11], eax", asm)
        self.assertIn("    mov BYTE PTR [r11], al", asm)
        self.assertIn("    mov QWORD PTR [rcx], 0", asm)

    def test_record_compound_literal_zeroes_aggregate_member(self) -> None:
        asm = self._asm(
            """
union Payload { char bytes[56]; };
struct Holder { union Payload payload; int tag; };
int main(void) {
  struct Holder holder;
  holder = (struct Holder){0};
  return holder.tag;
}
"""
        )
        self.assertIn("    mov QWORD PTR [rcx], 0", asm)
        self.assertNotIn("XMMWORD PTR [r11], rax", asm)

    def test_record_compound_literal_copies_aggregate_member(self) -> None:
        asm = self._asm(
            """
struct Counts { int total; int extra; };
struct Result { int prefix; struct Counts counts; };
int main(void) {
  struct Counts counts = {1, 2};
  struct Result result;
  result = (struct Result){ .prefix = 3, .counts = counts };
  return result.counts.extra;
}
"""
        )
        self.assertIn("    lea rdx, [rbp - 8]", asm)
        self.assertIn("    mov r10, QWORD PTR [rdx]", asm)
        self.assertIn("    mov QWORD PTR [r11], r10", asm)

    def test_record_conditional_assignment_copies_selected_branch(self) -> None:
        asm = self._asm(
            """
struct Pair { long first; long second; };
void choose(int flag, struct Pair *out, struct Pair *left, struct Pair *right) {
  *out = flag ? *left : *right;
}
"""
        )
        self.assertIn(".L.choose.aggregate_cond_false.", asm)
        self.assertIn(".L.choose.aggregate_cond_end.", asm)
        self.assertIn("    mov r10, QWORD PTR [rdx]", asm)
        self.assertIn("    mov QWORD PTR [rcx], r10", asm)

    def test_conditional_union_return_uses_selected_branch_storage(self) -> None:
        asm = self._asm(
            """
union Ref { long value; void *ptr; };
union Ref choose(int flag, union Ref *left, union Ref *right) {
  return flag ? *left : *right;
}
"""
        )
        self.assertIn(".L.choose.aggregate_cond_false.", asm)
        self.assertIn(".L.choose.aggregate_cond_end.", asm)
        self.assertIn("    sub rsp, 16", asm)
        self.assertIn("    mov rax, QWORD PTR [rcx]", asm)

    def test_record_local_initializer_list_stores_members(self) -> None:
        asm = self._asm(
            """
struct View { void *buf; void *obj; };
int main(void) {
  struct View view = { (void *)0, (void *)0 };
  return view.buf == (void *)0 && view.obj == (void *)0 ? 0 : 1;
}
"""
        )
        self.assertIn("    lea rcx, [rbp - 16]", asm)
        self.assertIn("    mov QWORD PTR [rcx], 0", asm)
        self.assertIn("    mov QWORD PTR [rcx + 8], 0", asm)

    def test_record_initializer_accepts_array_member_initializer_list(self) -> None:
        asm = self._asm(
            """
struct Sip { unsigned long v0; unsigned char buf[8]; unsigned long c; };
unsigned long f(void) {
  struct Sip state = {0, {0}, 7};
  return state.c;
}
"""
        )
        self.assertIn("f:", asm)
        self.assertIn("    mov BYTE PTR [r10], al", asm)
        self.assertIn("    mov QWORD PTR [r11], rax", asm)

    def test_local_array_of_records_initializer_lists_store_elements(self) -> None:
        asm = self._asm(
            """
struct Entry { int count; int kind; };
int f(int left, int right) {
  struct Entry entries[3] = {
    {left, 1},
    {right, 2},
    {-1, 0},
  };
  return entries[1].kind;
}
"""
        )
        self.assertIn("    lea rcx, [rbp - 32]", asm)
        self.assertIn("    lea rcx, [rbp - 24]", asm)
        self.assertIn("    mov DWORD PTR [r11], eax", asm)
        self.assertIn("    lea r11, [rcx + 4]", asm)

    def test_local_array_of_unions_accepts_zero_element_initializer(self) -> None:
        asm = self._asm(
            """
union Ref { long value; void *ptr; };
long f(void) {
  union Ref refs[2] = {0};
  return refs[0].value;
}
"""
        )
        self.assertIn("f:", asm)
        self.assertIn("    mov QWORD PTR [rcx], 0", asm)

    def test_block_array_declaration_shadows_outer_pointer_for_initializer(self) -> None:
        asm = self._asm(
            """
void f(unsigned char *b3, int flag) {
  if (flag) {
    unsigned char b3[256] = {0};
    b3[0] = 1;
  }
}
"""
        )
        self.assertIn("f:", asm)
        self.assertIn("    mov BYTE PTR [rcx], al", asm)
        self.assertNotIn("does not support aggregate local initializer", asm)

    def test_nested_block_local_uses_enclosing_tagged_union_type(self) -> None:
        asm = self._asm(
            """
unsigned long f(double x, int flag) {
  union pun { double f; unsigned long i; };
  union pun ux = {x};
  if (flag) {
    union pun result = {.i = ux.i + 1};
    return result.i;
  }
  return ux.i;
}
"""
        )
        self.assertIn("f:", asm)
        self.assertNotIn("cannot size scalar type union", asm)
        self.assertIn("    mov QWORD PTR [r11], rax", asm)

    def test_three_byte_aggregate_parameter_uses_bytewise_integer_chunk(self) -> None:
        asm = self._asm(
            """
struct Tiny { unsigned char key_length; unsigned char digest_length; _Bool last_node; };
int take(struct Tiny index) {
  return index.key_length + index.digest_length + index.last_node;
}
int f(void) {
  struct Tiny index = {1, 2, 1};
  return take(index);
}
"""
        )
        self.assertIn("take:", asm)
        self.assertIn("    mov BYTE PTR [r10 + 2], r11b", asm)
        self.assertIn("    movzx r11d, BYTE PTR [r10 + 2]", asm)

    def test_ansi_const_probe_static_aggregate_initializers_compile(self) -> None:
        asm = self._asm(
            """
int main(void) {
  typedef int charset[2];
  const charset cs = { 0, 0 };
  struct point { int x, y; };
  static struct point const zero = {0, 0};
  return !cs[0] && !zero.x ? 0 : 1;
}
"""
        )
        self.assertIn(".L.main.zero:", asm)
        self.assertGreaterEqual(asm.count("    .long 0"), 2)
        self.assertIn("    mov DWORD PTR [rbp - 8], eax", asm)

    def test_static_local_incomplete_pointer_array_uses_initializer_length(self) -> None:
        asm = self._asm(
            """
int f(int index) {
  static char *keywords[] = {"left", "right", 0};
  return keywords[index] != 0;
}
"""
        )
        self.assertIn(".L.f.keywords:", asm)
        self.assertIn("    .quad .LC0", asm)
        self.assertIn("    .quad .LC1", asm)
        self.assertIn("    .quad 0", asm)
        self.assertIn("    lea rax, [rip + .L.f.keywords]", asm)

    def test_extern_incomplete_record_array_identifier_decays_without_sizing(self) -> None:
        asm = self._asm(
            """
struct Entry { long value; };
extern struct Entry table[];
struct Entry *cursor;
void f(void) { cursor = table; }
"""
        )
        self.assertIn("    mov rax, QWORD PTR [rip + table@GOTPCREL]", asm)
        self.assertIn("    mov rcx, QWORD PTR [rip + cursor@GOTPCREL]", asm)
        self.assertIn("    mov QWORD PTR [rcx], rax", asm)

    def test_local_floating_array_initializer_uses_xmm_store(self) -> None:
        asm = self._asm(
            """
double f(double value) {
  double values[2] = { value, value };
  float narrowed[1] = { (float)value };
  return values[0] + narrowed[0];
}
"""
        )
        self.assertIn("    movsd [rbp - 24], xmm0", asm)
        self.assertIn("    movss [rbp - 28], xmm0", asm)
        self.assertNotIn("movsd [rbp - 24], rax", asm)
        self.assertNotIn("movss [rbp - 28], rax", asm)

    def test_small_record_return_uses_integer_register_chunks(self) -> None:
        asm = self._asm(
            """
struct Pair { int kind; void *object; };
struct Pair make_pair(void) {
  struct Pair pair;
  pair.kind = 2;
  pair.object = (void *)0;
  return pair;
}
"""
        )
        self.assertIn("    mov rax, QWORD PTR [rcx]", asm)
        self.assertIn("    mov rdx, QWORD PTR [rcx + 8]", asm)

    def test_compound_literal_record_return_uses_stack_scratch(self) -> None:
        asm = self._asm(
            """
struct Counter { unsigned short value; };
struct Counter make_counter(unsigned short value) {
  return (struct Counter){ .value = value };
}
struct Counter wrap(unsigned short value) {
  return make_counter(value);
}
"""
        )
        self.assertIn("    sub rsp, 16", asm)
        self.assertIn("    mov WORD PTR [r11], ax", asm)
        self.assertIn("    movzx eax, WORD PTR [rcx]", asm)
        self.assertIn("    call make_counter", asm)

    def test_record_assignment_from_call_stores_return_chunks(self) -> None:
        asm = self._asm(
            """
struct Pair { int kind; void *object; };
struct Pair make_pair(void);
int main(void) {
  struct Pair pair;
  pair = make_pair();
  return pair.kind;
}
"""
        )
        self.assertIn("    call make_pair", asm)
        self.assertIn("    mov QWORD PTR [rcx], rax", asm)
        self.assertIn("    mov QWORD PTR [rcx + 8], rdx", asm)

    def test_record_local_initializer_from_call_stores_return_chunks(self) -> None:
        asm = self._asm(
            """
struct Pair { double real; double imag; };
struct Pair make_pair(void);
double f(void) {
  struct Pair pair = make_pair();
  return pair.imag;
}
"""
        )
        self.assertIn("    call make_pair", asm)
        self.assertIn("    movsd [rcx], xmm0", asm)
        self.assertIn("    movsd [rcx + 8], xmm1", asm)
        self.assertNotIn("XMMWORD PTR", asm)

    def test_record_call_result_can_be_record_call_argument(self) -> None:
        asm = self._asm(
            """
struct Pair { long first; long second; };
struct Pair make_pair(void);
struct Pair use_pair(struct Pair pair);
struct Pair wrap(void) { return use_pair(make_pair()); }
"""
        )
        self.assertEqual(asm.count("call make_pair"), 1)
        self.assertIn("    push rdx", asm)
        self.assertIn("    push rax", asm)
        self.assertIn("    call use_pair", asm)

    def test_record_call_result_member_access_materializes_slot(self) -> None:
        asm = self._asm(
            """
struct Pair { long first; long second; };
struct Pair make_pair(void);
long f(void) { return make_pair().second; }
"""
        )
        self.assertIn("    call make_pair", asm)
        self.assertIn("    mov QWORD PTR [rcx], rax", asm)
        self.assertIn("    mov QWORD PTR [rcx + 8], rdx", asm)
        self.assertIn("    mov rax, QWORD PTR [rax]", asm)

    def test_conditional_record_can_be_record_call_argument(self) -> None:
        asm = self._asm(
            """
struct Pair { long first; long second; };
long use_pair(struct Pair pair);
long choose(int flag, struct Pair *left, struct Pair *right) {
  return use_pair(flag ? *left : *right);
}
"""
        )
        self.assertIn(".L.choose.aggregate_arg_cond_false.", asm)
        self.assertIn(".L.choose.aggregate_arg_cond_end.", asm)
        self.assertIn("    mov r11, QWORD PTR [rbp - 16]", asm)
        self.assertIn("    mov rax, QWORD PTR [r11 + 8]", asm)
        self.assertIn("    call use_pair", asm)

    def test_conditional_aggregate_call_arg_does_not_leave_stale_stack_depth(self) -> None:
        asm = self._asm(
            """
struct S { long value; };
void take(struct S value);
void next(void *a, void *b, long c, void *d);
void f(int flag, struct S a, struct S b, void *p) {
  take(flag ? a : b);
  next(p, p, 1, p);
}
"""
        )
        self.assertIn("    call take\n", asm)
        self.assertNotIn("    call take\n    push 0\n", asm)
        self.assertIn("    call next\n", asm)

    def test_compound_literal_record_can_be_record_call_argument_once(self) -> None:
        asm = self._asm(
            """
struct Pair { long first; long second; };
long next(void);
long use_pair(struct Pair pair);
long f(void) { return use_pair((struct Pair){ next(), 2 }); }
"""
        )
        self.assertEqual(asm.count("call next"), 1)
        self.assertIn("    mov QWORD PTR [r11], rax", asm)
        self.assertIn("    mov rax, QWORD PTR [r11 + 8]", asm)
        self.assertIn("    call use_pair", asm)

    def test_floating_conditional_initializer_keeps_xmm_result(self) -> None:
        asm = self._asm(
            """
double choose(int flag, double left, double right) {
  double value = flag ? left : right;
  return value;
}
"""
        )
        self.assertIn("    movsd [rbp - 32], xmm0", asm)
        self.assertNotIn("movsd [rbp - 32], rax", asm)

    def test_conditional_result_coerces_each_branch_to_result_type(self) -> None:
        asm = self._asm(
            """
long f(int mode, long count) {
  return mode == 2 ? count : -1;
}
"""
        )
        self.assertIn("    movsxd rax, eax", asm)

    def test_large_record_return_uses_indirect_sret_pointer(self) -> None:
        asm = self._asm(
            """
struct Big { long a; long b; long c; };
struct Big make_big(long value) {
  struct Big big = { value, 2, 3 };
  return big;
}
int main(void) {
  struct Big big;
  big = make_big(1);
  return big.c == 3 ? 0 : 1;
}
"""
        )
        self.assertIn("    mov QWORD PTR [rbp - 8], rdi", asm)
        self.assertIn("    mov QWORD PTR [rbp - 16], rsi", asm)
        self.assertIn("    mov rdi, QWORD PTR [rsp + 8]", asm)
        self.assertIn("    call make_big", asm)

    def test_large_record_conditional_return_writes_sret_storage(self) -> None:
        asm = self._asm(
            """
struct Big { long a; long b; long c; };
struct Big choose(int flag, struct Big *left, struct Big *right) {
  return flag ? *left : *right;
}
"""
        )
        self.assertIn(".L.choose.aggregate_cond_false.", asm)
        self.assertIn(".L.choose.aggregate_cond_end.", asm)
        self.assertIn("    mov QWORD PTR [rbp - 8], rdi", asm)
        self.assertIn("    mov r10, QWORD PTR [rdx + 16]", asm)

    def test_floating_compound_assignment_uses_xmm_registers(self) -> None:
        asm = self._asm(
            """
static double values[] = {1.5, 0.0};
double addend(void) { return 2.5; }
int main(void) {
  values[0] += addend();
  return values[0] == 4.0 ? 0 : 1;
}
"""
        )
        self.assertIn("    addsd xmm0, xmm1", asm)
        self.assertIn("    movsd [rcx], xmm0", asm)
        self.assertNotIn("movsd rax", asm)

    def test_integer_rhs_of_floating_compound_assignment_uses_gpr(self) -> None:
        asm = self._asm(
            """
double f(double value, int exponent) {
  value *= 1 - exponent;
  value += exponent;
  value += 1;
  return value;
}
"""
        )
        self.assertIn("    mov eax, 1", asm)
        self.assertIn("    sub eax, r10d", asm)
        self.assertIn("    mov eax, DWORD PTR [rbp - 12]", asm)
        self.assertIn("    cvtsi2sd xmm0, rax", asm)
        self.assertNotIn("mov xmm0, 1", asm)

    def test_uint64_to_double_conversion_handles_high_bit(self) -> None:
        asm = self._asm(
            """
double to_double(unsigned long value) { return (double)value; }
"""
        )
        self.assertIn("    js .L.to_double.uint64_float_slow.", asm)
        self.assertIn("    cvtsi2sd xmm0, rax", asm)
        self.assertIn("    addsd xmm0, xmm0", asm)

    def test_two_double_record_call_argument_uses_sse_chunks(self) -> None:
        asm = self._asm(
            """
typedef struct { double real; double imag; } Py_complex;
double sum_complex(Py_complex value) { return value.real + value.imag; }
int main(void) {
  Py_complex value;
  value.real = 1.25;
  value.imag = 2.75;
  return sum_complex(value) == 4.0 ? 0 : 1;
}
"""
        )
        self.assertIn("    movsd [rbp - 16], xmm0", asm)
        self.assertIn("    movsd [rbp - 8], xmm1", asm)
        self.assertIn("    movsd xmm0, [rsp]", asm)
        self.assertIn("    movsd xmm1, [rsp]", asm)
        self.assertIn("    call sum_complex", asm)

    def test_anonymous_record_member_access_uses_promoted_offset(self) -> None:
        asm = self._asm(
            """
struct Obj {
  union {
    long full;
    struct {
      unsigned int ob_refcnt;
      unsigned short ob_overflow;
    };
  };
  long type;
};
int main(void) {
  struct Obj obj;
  obj.ob_refcnt = 7;
  return obj.ob_refcnt == 7 ? 0 : 1;
}
"""
        )
        self.assertIn("    mov DWORD PTR [rcx], eax", asm)
        self.assertIn("    mov eax, DWORD PTR [rax]", asm)

    def test_bitfield_member_read_write_masks_storage_unit(self) -> None:
        asm = self._asm(
            """
struct State {
  unsigned int interned:2;
  unsigned int kind:3;
  unsigned int compact:1;
};
int main(void) {
  struct State state;
  state.kind = 5;
  state.compact = 1;
  return state.kind == 5 && state.compact == 1 ? 0 : 1;
}
"""
        )
        self.assertIn("    sal r10d, 2", asm)
        self.assertIn("    mov edx, 4294967267", asm)
        self.assertIn("    and r11d, edx", asm)
        self.assertIn("    shr eax, 2", asm)
        self.assertIn("    and eax, 7", asm)

    def test_va_start_for_stack_variadic_args_initializes_va_list_slot(self) -> None:
        asm = self._asm(
            """
void sink(__builtin_va_list);
static inline void wrapper(
  int a, int b, int c, int d, int e, int f, const char *format, ...
) {
  __builtin_va_list va;
  __builtin_va_start(va, format);
  sink(va);
  __builtin_va_end(va);
}
int main(void) {
  wrapper(1, 2, 3, 4, 5, 6, "x", 42);
  return 0;
}
"""
        )
        self.assertIn("    mov DWORD PTR [rcx], 48", asm)
        self.assertIn("    lea r10, [rbp + 24]", asm)
        self.assertIn("    mov QWORD PTR [rcx + 8], r10", asm)
        self.assertIn("    mov QWORD PTR [rcx + 16], r10", asm)
        self.assertIn("    call sink", asm)
        self.assertNotIn("call __builtin_va_start", asm)
        self.assertNotIn("call __builtin_va_end", asm)

    def test_va_arg_reads_register_save_area_and_advances_va_list(self) -> None:
        asm = self._asm(
            """
void *first_reg_arg(char *a, char *b, char *format, ...) {
  __builtin_va_list ap;
  __builtin_va_start(ap, format);
  void *value = __builtin_va_arg(ap, void *);
  __builtin_va_end(ap);
  return value;
}
"""
        )
        self.assertIn("    mov QWORD PTR [rbp -", asm)
        self.assertIn("], rcx", asm)
        self.assertIn("    mov DWORD PTR [rcx], 24", asm)
        self.assertIn("    mov r11, QWORD PTR [rcx + 16]", asm)
        self.assertIn("    add DWORD PTR [rcx + 0], 8", asm)

    def test_va_arg_overflow_path_reads_stack_slot_and_advances_va_list(self) -> None:
        asm = self._asm(
            """
int first_stack_arg(int a, int b, int c, int d, int e, int f, const char *format, ...) {
  __builtin_va_list ap;
  __builtin_va_start(ap, format);
  int value = __builtin_va_arg(ap, int);
  __builtin_va_end(ap);
  return value;
}
"""
        )
        self.assertIn("    mov DWORD PTR [rcx], 48", asm)
        self.assertIn("    mov r11, QWORD PTR [rcx + 8]", asm)
        self.assertIn("    mov eax, DWORD PTR [r11]", asm)
        self.assertIn("    add r11, 8", asm)
        self.assertIn("    mov QWORD PTR [rcx + 8], r11", asm)

    def test_va_copy_from_parameter_uses_pointed_sysv_va_list(self) -> None:
        asm = self._asm(
            """
void use(__builtin_va_list);
void copy_param(const char *format, __builtin_va_list incoming) {
  __builtin_va_list local;
  __builtin_va_copy(local, incoming);
  use(local);
}
"""
        )
        self.assertIn("    mov QWORD PTR [rbp -", asm)
        self.assertIn("], rsi", asm)
        self.assertIn("    lea rcx, [rbp -", asm)
        self.assertIn("    mov rdx, QWORD PTR [rbp -", asm)
        self.assertIn("    mov r10, QWORD PTR [rdx]", asm)
        self.assertIn("    mov QWORD PTR [rcx + 16], rax", asm)

    def test_va_arg_from_parameter_uses_pointed_sysv_va_list(self) -> None:
        asm = self._asm(
            """
void *next_param(__builtin_va_list incoming) {
  return __builtin_va_arg(incoming, void *);
}
"""
        )
        self.assertIn("    mov rcx, QWORD PTR [rbp -", asm)
        self.assertIn("    mov eax, DWORD PTR [rcx + 0]", asm)
        self.assertIn("    mov r11, QWORD PTR [rcx + 16]", asm)

    def test_control_flow_calls_and_pointers_run_on_native_linux(self) -> None:
        source = """
int add(int a, int b) { return a + b; }
int main(void) {
  int values[3] = {1, 2, 3};
  int *p = values;
  int sum = 0;
  for (int i = 0; i < 3; i++) {
    sum += *(p + i);
  }
  if (add(sum, 1) != 7) return 1;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_records_globals_switch_and_offsetof_run_on_native_linux(self) -> None:
        source = """
struct Pair { int a; long b; };
int g = 4;
static int h = 5;
int pick(int x) {
  switch (x) {
  case 1: return g;
  case 2: return h;
  default: return 9;
  }
}
int main(void) {
  struct Pair p;
  p.a = 3;
  p.b = 8;
  if (__builtin_offsetof(struct Pair, b) != 8) return 1;
  if (sizeof(struct Pair) != 16) return 2;
  if (p.a + (int)p.b != 11) return 3;
  if (pick(1) != 4 || pick(2) != 5 || pick(3) != 9) return 4;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_floating_calls_and_stack_args_run_on_native_linux(self) -> None:
        source = """
double add(double a, double b) { return a + b; }
double ninth(
  double a, double b, double c, double d, double e,
  double f, double g, double h, double i
) { return i; }
int main(void) {
  double x = add(1.25, 2.75);
  double y = ninth(1, 2, 3, 4, 5, 6, 7, 8, 9);
  if (x != 4.0) return 1;
  if (y != 9.0) return 2;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_string_literal_call_argument_decay_runs_on_native_linux(self) -> None:
        source = """
int first(const char *s) { return s[0]; }
int main(void) { return first("ok") == 'o' ? 0 : 1; }
"""
        self.assertEqual(self._run(source), 0)

    def test_floating_compound_assignment_runs_on_native_linux(self) -> None:
        source = """
static double values[] = {1.5, 0.0};
double addend(void) { return 2.5; }
int main(void) {
  values[0] += addend();
  return values[0] == 4.0 ? 0 : 1;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_two_double_record_call_argument_runs_on_native_linux(self) -> None:
        source = """
typedef struct { double real; double imag; } Py_complex;
double sum_complex(Py_complex value) { return value.real + value.imag; }
int main(void) {
  Py_complex value;
  value.real = 1.25;
  value.imag = 2.75;
  return sum_complex(value) == 4.0 ? 0 : 1;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_anonymous_record_member_access_runs_on_native_linux(self) -> None:
        source = """
struct Obj {
  union {
    long full;
    struct {
      unsigned int ob_refcnt;
      unsigned short ob_overflow;
    };
  };
  long type;
};
int main(void) {
  struct Obj obj;
  obj.ob_refcnt = 7;
  return obj.ob_refcnt == 7 ? 0 : 1;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_bitfield_member_access_runs_on_native_linux(self) -> None:
        source = """
struct State {
  unsigned int interned:2;
  unsigned int kind:3;
  unsigned int compact:1;
};
int main(void) {
  struct State state;
  state.interned = 3;
  state.kind = 5;
  state.compact = 1;
  if (state.interned != 3) return 1;
  if (state.kind != 5) return 2;
  if (state.compact != 1) return 3;
  state.kind += 1;
  if (state.kind != 6) return 4;
  state.compact--;
  return state.compact == 0 ? 0 : 5;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_postfix_pointer_update_under_deref_runs_on_native_linux(self) -> None:
        source = """
int main(void) {
  long first = 1;
  long second = 2;
  long *items[2] = {0, 0};
  long **sp = items;
  *sp++ = &first;
  *sp++ = &second;
  if (sp != items + 2) return 1;
  if (items[0] != &first) return 2;
  if (items[1] != &second) return 3;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_for_init_shadow_does_not_overwrite_parameter_on_native_linux(self) -> None:
        source = """
int keep_outer_for_index(int i, int n) {
  for (int i = 0; i < n; i++) {
  }
  return i == 7 ? 0 : 1;
}
int main(void) {
  return keep_outer_for_index(7, 3);
}
"""
        self.assertEqual(self._run(source), 0)


if __name__ == "__main__":
    unittest.main()
