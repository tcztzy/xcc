import subprocess
import tempfile
import unittest
from pathlib import Path

from tests import _bootstrap  # noqa: F401
from xcc.aarch64_asm import (
    generate_aarch64_asm,
)
from xcc.frontend import compile_source
from xcc.options import FrontendOptions


class AArch64AsmTests(unittest.TestCase):
    def _asm(self, source: str, options: FrontendOptions | None = None) -> str:
        if options is None:
            options = FrontendOptions(target_os="darwin", host_machine="arm64")
        return generate_aarch64_asm(compile_source(source, filename="test.c", options=options))

    def _run(self, source: str, options: FrontendOptions | None = None) -> int:
        asm = self._asm(source, options=options)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            asm_path = root / "input.s"
            exe_path = root / "a.out"
            asm_path.write_text(asm, encoding="utf-8")
            assemble = subprocess.run(
                ["clang", "-target", "aarch64-apple-darwin", str(asm_path), "-o", str(exe_path)],
                capture_output=True,
                check=False,
                text=True,
            )
            self.assertEqual(assemble.returncode, 0, assemble.stderr)
            run = subprocess.run([str(exe_path)], check=False)
            return run.returncode

    def _link_bytes(self, source: str) -> bytes:
        asm = self._asm(source)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            asm_path = root / "input.s"
            exe_path = root / "a.out"
            asm_path.write_text(asm, encoding="utf-8")
            assemble = subprocess.run(
                ["clang", "-target", "aarch64-apple-darwin", str(asm_path), "-o", str(exe_path)],
                capture_output=True,
                check=False,
                text=True,
            )
            self.assertEqual(assemble.returncode, 0, assemble.stderr)
            return exe_path.read_bytes()

    def test_emits_constant_return_function(self) -> None:
        asm = self._asm("int f(void){return 7;}")
        self.assertIn(".section __TEXT,__text,regular,pure_instructions", asm)
        self.assertIn(".globl _f\n_f:", asm)
        self.assertIn("    mov w0, #7", asm)
        self.assertIn("    ret", asm)
        self.assertNotIn("define i32", asm)

    def test_emits_params_locals_and_arithmetic(self) -> None:
        asm = self._asm("int add(int a, int b){ int c=a+b; return c*2; }")
        self.assertIn("    sub sp, sp, #48", asm)
        self.assertIn("    str w0, [sp, #0]", asm)
        self.assertIn("    str w1, [sp, #4]", asm)
        self.assertIn("    add w0, w9, w10", asm)
        self.assertIn("    str w0, [sp, #8]", asm)
        self.assertIn("    mul w0, w9, w10", asm)

    def test_shift_uses_result_register_width(self) -> None:
        asm = self._asm("int shift(int x, long y){ return x << y; }")
        self.assertIn("    lsl w0, w9, w10", asm)
        self.assertNotIn("lsl w0, x9, x10", asm)

    def test_binary_rhs_expression_preserves_left_operand_register(self) -> None:
        source = """
int main(void) {
  unsigned long len = 16;
  if (len > (100 / sizeof(int) - 1)) return 1;
  if ((1u << (2 + 3)) != 32u) return 2;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_large_frame_expression_spills_materialize_stack_address(self) -> None:
        source = """
int main(void) {
  char pad[20000];
  unsigned long len = 16;
  pad[0] = 1;
  if (len > (100 / sizeof(int) - 1)) return 1;
  return pad[0] - 1;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_large_frame_aggregate_assignment_preserves_source_address(self) -> None:
        source = """
struct Pair { long first; long second; };
int main(void) {
  char pad[20000];
  struct Pair src;
  struct Pair dst;
  pad[0] = 1;
  src.first = 11;
  src.second = 13;
  dst = src;
  if (pad[0] != 1) return 1;
  if (dst.first != 11) return 2;
  if (dst.second != 13) return 3;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_if_statement_branches(self) -> None:
        self.assertEqual(self._run("int main(void){ if (0) return 1; return 0; }"), 0)
        self.assertEqual(self._run("int main(void){ if (1) return 7; return 0; }"), 7)

    def test_switch_statement_dispatches_cases_default_and_break(self) -> None:
        source = """
int f(int x) {
  int y = 0;
  switch (x) {
  case 1: return 3;
  case 2: y = 4; break;
  default: return 5;
  }
  return y;
}
int main(void) {
  if (f(1) != 3) return 1;
  if (f(2) != 4) return 2;
  if (f(8) != 5) return 3;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_nested_switch_statement_dispatches_inner_cases(self) -> None:
        source = """
int f(int x, int y) {
  switch (x) {
  case 1:
    switch (y) {
    case 2: return 7;
    }
    break;
  }
  return 0;
}
int main(void) {
  if (f(1, 2) != 7) return 1;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_pointer_member_access_loads_scalar_field(self) -> None:
        source = """
struct Parser { int mark; long size; };
int f(struct Parser *p) {
  return p->mark + (int)p->size;
}
"""
        asm = self._asm(source)
        self.assertIn("    add x11, x11, #8", asm)
        self.assertIn("    ldr x10, [x11]", asm)

    def test_pragma_pack_controls_record_layout(self) -> None:
        asm = self._asm(
            """
#pragma pack(push, 4)
struct S { unsigned words[13]; unsigned long context; };
#pragma pack(pop)
unsigned long read(struct S *p) { return p->context; }
int size(void) { return sizeof(struct S); }
"""
        )

        self.assertIn("    add x11, x11, #52", asm)
        self.assertIn("    mov w0, #60", asm)

    def test_pointer_member_assignment_stores_scalar_field(self) -> None:
        source = """
struct Parser { int mark; long size; };
int f(struct Parser *p) {
  p->mark = 5;
  p->size = 9;
  return 0;
}
"""
        asm = self._asm(source)
        self.assertIn("    str w0, [x11]", asm)
        self.assertIn("    add x11, x11, #8", asm)
        self.assertIn("    str x0, [x11]", asm)

    def test_compound_assignment_updates_member_and_member_array_lvalues(self) -> None:
        source = """
struct Bits { unsigned long words[2]; int fill; };
int f(struct Bits *p, int index) {
  p->fill += 1;
  p->words[index] |= 4;
  p->words[index] &= 7;
  return p->fill;
}
"""
        asm = self._asm(source)
        self.assertIn("    add w0, w9, w0", asm)
        self.assertIn("    orr x0, x9, x0", asm)
        self.assertIn("    and x0, x9, x0", asm)

    def test_grouped_globals_and_static_locals_emit_each_object(self) -> None:
        asm = self._asm(
            """
static int first = 1, second = 2;
static char text[] = "hi";

int f(void) {
  static int local_first = 3, local_second = 4;
  return first + second + local_first + local_second + text[0];
}
"""
        )

        self.assertIn("L_.first:\n    .long 1", asm)
        self.assertIn("L_.second:\n    .long 2", asm)
        self.assertIn('L_.text:\n    .ascii "hi\\000"', asm)
        self.assertIn("L_.f.local_first:\n    .long 3", asm)
        self.assertIn("L_.f.local_second:\n    .long 4", asm)

    def test_global_initializer_variants_emit_constants_designators_and_compounds(
        self,
    ) -> None:
        asm = self._asm(
            """
struct Inner { char c; long value; };
struct Outer { int tag; struct Inner inner; };
static double d = 1.5;
static float f = -2.25f;
static long off = __builtin_offsetof(struct Outer, inner.value);
static int scalar = { 7 };
static int sparse[] = { [2] = 5, [4] = 9 };
static struct Outer outer = (struct Outer){ .tag = 3, .inner = { .c = 4, .value = 8 } };
long sum(void) { return off + scalar + sparse[2] + sparse[4] + outer.inner.value; }
"""
        )

        self.assertIn("L_.d:\n    .quad 0x3ff8000000000000", asm)
        self.assertIn("L_.f:\n    .long 0xc0100000", asm)
        self.assertIn("L_.off:\n    .quad 16", asm)
        self.assertIn("L_.scalar:\n    .long 7", asm)
        self.assertIn("L_.sparse:\n    .zero 4\n    .zero 4\n    .long 5", asm)
        self.assertIn("    .zero 4\n    .long 9", asm)
        self.assertIn(
            "L_.outer:\n    .long 3\n    .zero 4\n    .byte 4\n    .zero 7\n    .quad 8",
            asm,
        )

    def test_global_integer_initializer_folds_constant_expression_matrix(self) -> None:
        asm = self._asm(
            """
struct Pair { char x; long y; };
enum { C_ENUM = 9 };
static const int c_char = 'A';
static const int c_enum = C_ENUM;
static const int c_unary = (+7) + (-2) + (!0) + (~0);
static const int c_cast = (int)7;
static const int c_comma = ((void)0, 23);
static const int c_mul = 6 * 7;
static const int c_div = 17 / 4;
static const int c_mod = 17 % 5;
static const int c_shl = 3 << 4;
static const int c_shr = 64 >> 3;
static const int c_cmp = (1 < 2) + (2 <= 2) + (3 > 2) + (3 >= 3) + (4 == 4) + (4 != 5);
static const int c_bitwise = (12 & 10) + (1 | 4) + (7 ^ 2);
static const int c_logic = (0 && 5) + (4 && 5) + (4 || 0) + (0 || 0);
static const int c_cond = (1 ? 11 : 22) + (0 ? 33 : 44);
static const long c_size_align = sizeof(long) + _Alignof(long);
static const long c_offset = __builtin_offsetof(struct Pair, y);
long sum(void) {
  return c_char + c_enum + c_unary + c_cast + c_comma + c_mul + c_div + c_mod
      + c_shl + c_shr + c_cmp + c_bitwise + c_logic + c_cond + c_size_align
      + c_offset;
}
"""
        )

        expected_scalars = {
            "c_char": 65,
            "c_enum": 9,
            "c_unary": 5,
            "c_cast": 7,
            "c_comma": 23,
            "c_mul": 42,
            "c_div": 4,
            "c_mod": 2,
            "c_shl": 48,
            "c_shr": 8,
            "c_cmp": 6,
            "c_bitwise": 18,
            "c_logic": 2,
            "c_cond": 55,
        }
        for name, value in expected_scalars.items():
            with self.subTest(name=name):
                self.assertIn(f"L_.{name}:\n    .long {value}", asm)
        self.assertIn("L_.c_size_align:\n    .quad 16", asm)
        self.assertIn("L_.c_offset:\n    .quad 8", asm)

    def test_global_record_initializer_handles_flexible_zero_and_padding_edges(
        self,
    ) -> None:
        asm = self._asm(
            """
struct FlexNone { char tag; int data[]; };
static struct FlexNone flex_none = { .tag = 1 };

struct FlexZero { char tag; int data[]; };
static struct FlexZero flex_zero = { .tag = 2, .data = 0 };

struct PaddedBits { char prefix; unsigned a:3; int tail; };
static struct PaddedBits padded_bits = { .prefix = 4, .a = 5, .tail = 9 };

struct ZeroWidthPad { char prefix; unsigned :0; int tail; };
static struct ZeroWidthPad zero_width = { .prefix = 6, .tail = 11 };

int f(void) { return flex_none.tag + flex_zero.tag + padded_bits.tail + zero_width.tail; }
"""
        )

        self.assertIn("L_.flex_none:\n    .byte 1\n    .zero 3", asm)
        self.assertIn("L_.flex_zero:\n    .byte 2\n    .zero 3", asm)
        self.assertIn("L_.padded_bits:\n    .byte 4\n    .byte 5\n    .zero 2\n    .long 9", asm)
        self.assertIn("L_.zero_width:\n    .byte 6\n    .zero 3\n    .long 11", asm)

    def test_compound_assignment_supports_integer_arithmetic_bitwise_and_shifts(self) -> None:
        source = """
int main(void) {
  int x = 3;
  x *= 5;
  x /= 3;
  x %= 4;
  x ^= 6;
  x <<= 1;
  x >>= 2;
  if (x != 3) return 1;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_local_compound_assignment_preserves_left_value_across_rhs_evaluation(self) -> None:
        source = """
struct Type { unsigned long basicsize; unsigned long itemsize; };
unsigned long object_size(struct Type *type, long nitems) {
  unsigned long size = type->basicsize;
  size += (unsigned long)nitems * type->itemsize;
  return (size + 7) & ~(unsigned long)7;
}
int main(void) {
  struct Type wrapper;
  wrapper.basicsize = 56;
  wrapper.itemsize = 0;
  if (object_size(&wrapper, 1) != 56) return 1;
  wrapper.itemsize = 3;
  if (object_size(&wrapper, 2) != 64) return 2;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_pointer_deref_load_store_and_address_of_local(self) -> None:
        source = """
int f(void) {
  int x = 1;
  int *p = &x;
  *p = 4;
  return *p;
}
int main(void) {
  if (f() != 4) return 1;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_local_record_slot_supports_address_and_member_access(self) -> None:
        source = """
struct Token { int type; int line; };
void init(struct Token *t) {
  t->type = 5;
  t->line = 7;
}
int main(void) {
  struct Token token;
  init(&token);
  token.line += 1;
  if (token.type != 5) return 1;
  if (token.line != 8) return 2;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_block_scope_same_name_locals_use_distinct_member_types(self) -> None:
        source = """
struct Seq { long size; void **elements; };
struct Token { int type; int end_lineno; };
int f(int n, struct Seq *seq, struct Token *tok) {
  if (n) {
    struct Seq *b = seq;
    if (b->size != 3) return 1;
  }
  if (n) {
    struct Token *b = tok;
    return b->end_lineno;
  }
  return 0;
}
int main(void) {
  struct Seq seq;
  struct Token tok;
  seq.size = 3;
  tok.end_lineno = 7;
  if (f(1, &seq, &tok) != 7) return 2;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_large_record_member_offset_materializes_address(self) -> None:
        source = """
struct Big { char padding[5000]; int value; };
struct Big big;
int main(void) {
  big.value = 7;
  if (big.value != 7) return 1;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_update_expressions_preserve_prefix_and_postfix_results(self) -> None:
        source = """
int main(void) {
  int x = 3;
  int a = x++;
  int b = ++x;
  if (a != 3) return 1;
  if (b != 5) return 2;
  if (x != 5) return 3;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_non_power_of_two_subscript_aggregate_copy_preserves_base_address(self) -> None:
        source = """
struct Instruction {
  int opcode;
  int oparg;
  long payload;
  int a;
  int b;
  int c;
  int d;
  int e;
};
void shift(struct Instruction *items, int pos, int last) {
  for (int i = last - 1; i >= pos; i--) {
    items[i + 1] = items[i];
  }
}
int main(void) {
  struct Instruction items[3] = {0};
  items[0].opcode = 11;
  items[0].payload = 23;
  items[0].e = 31;
  items[1].opcode = 5;
  shift(items, 0, 1);
  if (items[1].opcode != 11) return 1;
  if (items[1].payload != 23) return 2;
  if (items[1].e != 31) return 3;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_postfix_pointer_update_preserves_address_when_result_is_dereferenced(self) -> None:
        source = """
int main(void) {
  char *format = "az";
  char **p_format = &format;
  int first = *(*p_format)++;
  if (first != 'a') return 1;
  if (*format != 'z') return 2;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_global_identifier_update_stores_through_symbol_address(self) -> None:
        source = """
int counter = 0;
int main(void) {
  int first = counter++;
  int second = ++counter;
  if (first != 0) return 1;
  if (second != 2) return 2;
  if (counter != 2) return 3;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_pointer_comparisons_and_scaled_arithmetic(self) -> None:
        source = """
int values[4];
int main(void) {
  int *p = &values[0];
  void *zero = (void *)0;
  if (p == zero) return 1;
  if (zero != (void *)0) return 2;
  if (p + 2 != &values[2]) return 3;
  if (2 + p != &values[2]) return 4;
  if (&values[3] - p != 3) return 5;
  p += 3;
  if (p != &values[3]) return 6;
  p -= 2;
  if (p != &values[1]) return 7;
  if (!(p < &values[3])) return 8;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_pointer_cast_subscript_uses_cast_value_as_base_address(self) -> None:
        source = """
int main(void) {
  int value = 0x12345678;
  unsigned char low = ((unsigned char *)&value)[0];
  if (low != 0x78) return 1;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_array_expression_decays_for_pointer_arithmetic(self) -> None:
        source = """
int main(void) {
  char buffer[4] = {'a', 'b', 'c', 0};
  char *p = buffer + 2;
  if (*p != 'c') return 1;
  if (buffer + 3 != &buffer[3]) return 2;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_comma_expression_forwards_address_to_right_lvalue(self) -> None:
        source = """
int main(void) {
  int values[2] = {3, 4};
  int *p = &((void)0, values)[1];
  if (*p != 4) return 1;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_pointer_call_result_subscript_preserves_index_across_call(self) -> None:
        source = """
char *pick(char *p) {
  int a = 3;
  int b = 4;
  if (a + b != 7) return (void *)0;
  return p;
}
int main(void) {
  char buf[8] = {0};
  int index = 2;
  pick(buf)[index] = 7;
  if (buf[2] != 7) return 1;
  if (buf[4] == 7) return 2;
  if (pick(buf)[index] != 7) return 3;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_member_array_expression_decays_to_base_address(self) -> None:
        source = """
struct Work { unsigned char table[4]; };
int main(void) {
  struct Work work;
  work.table[2] = 9;
  unsigned char *table = work.table;
  if (table[2] != 9) return 1;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_unary_deref_of_member_array_reads_first_element(self) -> None:
        source = """
struct Bytes { char data[2]; };
int main(void) {
  struct Bytes bytes;
  bytes.data[0] = 'x';
  bytes.data[1] = 'y';
  if (*bytes.data != 'x') return 1;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_member_pointer_subscript_loads_pointer_value(self) -> None:
        source = """
struct Box { char **items; };
int main(void) {
  char *items[2] = {"source", (void *)0};
  struct Box box;
  box.items = items;
  if (box.items[0][0] != 's') return 1;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_nested_pointer_subscript_preserves_outer_index_register(self) -> None:
        source = """
int optind = 1;
int is_script(char **argv) {
  return argv[optind][0] != '-' || argv[optind][1] == 0;
}
int main(void) {
  char *script_argv[2] = {"prog", "./script.py"};
  char *option_argv[2] = {"prog", "-c"};
  if (!is_script(script_argv)) return 1;
  if (is_script(option_argv)) return 2;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_nested_subscript_non_power_scale_preserves_outer_index(self) -> None:
        source = """
unsigned char table[2][11];
int get_cell(int row, int col) {
  return table[row][col];
}
int main(void) {
  table[1][7] = 42;
  if (get_cell(1, 7) != 42) return 1;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_extern_global_scalar_load_uses_symbol_relocation(self) -> None:
        asm = self._asm("extern int value;\nint f(void){ return value; }")
        self.assertIn("    adrp x11, _value@GOTPAGE", asm)
        self.assertIn("    ldr x11, [x11, _value@GOTPAGEOFF]", asm)
        self.assertIn("    ldr w0, [x11]", asm)

    def test_extern_incomplete_array_identifier_decays_to_symbol_address(self) -> None:
        source = """
struct Entry { int value; };
struct Entry entries[2] = { {3}, {0} };
int main(void) {
  extern struct Entry entries[];
  struct Entry *p;
  p = entries;
  if (p[0].value != 3) return 1;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_subscript_of_multidimensional_array_decays_to_row_address(self) -> None:
        source = """
static const char names[2][4] = {"Sun", "Mon"};
const char *pick(int index) {
  return names[index];
}
int main(void) {
  const char *name = pick(1);
  if (name[0] != 'M') return 1;
  if (name[1] != 'o') return 2;
  if (name[2] != 'n') return 3;
  if (name[3] != 0) return 4;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_while_statement_supports_break_and_continue(self) -> None:
        source = """
int main(void) {
  int i = 0;
  int total = 0;
  while (i < 6) {
    i += 1;
    if (i == 2) continue;
    if (i == 5) break;
    total += i;
  }
  if (total != 8) return 1;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_do_while_statement_runs_body_before_condition(self) -> None:
        source = """
int main(void) {
  int i = 0;
  int total = 0;
  do {
    i += 1;
    if (i == 2) continue;
    total += i;
  } while (i < 3);
  if (total != 4) return 1;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_for_statement_supports_declaration_post_and_continue(self) -> None:
        source = """
int main(void) {
  int total = 0;
  for (int i = 0; i < 6; i++) {
    if (i == 1) continue;
    if (i == 5) break;
    total += i;
  }
  if (total != 9) return 1;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_control_flow_statements_lower_to_labels_and_branches(self) -> None:
        asm = self._asm(
            """
int flow(int x) {
  int total = 0;
  int i = 0;
  while (i < 5) {
    i++;
    if (i == 2) continue;
    if (i == 4) break;
    total += i;
  }
  do {
    total += 10;
  } while (0);
  for (;;) {
    total += 20;
    break;
  }
  switch (x) {
    case 1:
      total += 100;
      goto done;
    case 2:
      total += 200;
      break;
    default:
      total += 300;
      break;
  }
done:
  return total;
}
"""
        )

        self.assertIn("L_while_cond_", asm)
        self.assertIn("L_while_body_", asm)
        self.assertIn("L_while_end_", asm)
        self.assertIn("L_do_body_", asm)
        self.assertIn("L_do_cond_", asm)
        self.assertIn("L_do_end_", asm)
        self.assertIn("L_for_cond_", asm)
        self.assertIn("L_for_post_", asm)
        self.assertIn("L_for_end_", asm)
        self.assertIn("L_switch_case_", asm)
        self.assertIn("L_switch_default_", asm)
        self.assertIn("L_switch_end_", asm)
        self.assertIn("L_flow_done:", asm)
        self.assertIn("    b L_flow_done", asm)

    def test_goto_branches_to_function_local_label(self) -> None:
        source = """
int main(void) {
  int x = 0;
  goto done;
  x = 1;
done:
  return x;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_function_designator_emits_symbol_address(self) -> None:
        source = """
int callee(int x) { return x; }
int main(void) {
  if (callee == (void *)0) return 1;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_block_scope_function_declaration_does_not_allocate_local_slot(self) -> None:
        source = """
int main(void) {
  long magic(void);
  if (magic() != 17) return 1;
  return 0;
}
long magic(void) {
  return 17;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_gnu_void_return_expression_emits_operand_side_effect(self) -> None:
        source = """
int hit;
int mark(void) {
  hit = 7;
  return 3;
}
void run(void) {
  return mark();
}
int main(void) {
  run();
  if (hit != 7) return 1;
  return 0;
}
"""
        self.assertEqual(self._run(source, options=FrontendOptions(std="gnu11")), 0)

    def test_function_pointer_member_call_uses_indirect_branch(self) -> None:
        source = """
struct Tok { int (*underflow)(struct Tok *); int value; };
int read_value(struct Tok *tok) { return tok->value; }
int call_underflow(struct Tok *tok) { return tok->underflow(tok); }
int main(void) {
  struct Tok tok;
  tok.underflow = read_value;
  tok.value = 9;
  if (call_underflow(&tok) != 9) return 1;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_const_qualified_void_function_pointer_result_is_void(self) -> None:
        source = """
typedef void (*destructor)(void *);
void mark(void *ptr) {
  *(int *)ptr = 7;
}
void close(void *ptr, const destructor destruct) {
  destruct(ptr);
}
int main(void) {
  int value = 0;
  close(&value, mark);
  return value == 7 ? 0 : 1;
}
"""
        asm = self._asm(source)
        self.assertIn("    blr x16", asm)
        self.assertEqual(self._run(source), 0)

    def test_global_function_pointer_assignment_and_deref_call(self) -> None:
        source = """
int read_value(void) { return 11; }
int (*reader)(void) = 0;
int main(void) {
  reader = read_value;
  if ((*reader)() != 11) return 1;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_function_pointer_deref_rvalue_decays_to_pointer(self) -> None:
        source = """
int read_value(void) { return 13; }
int main(void) {
  int (*reader)(void) = read_value;
  int (*again)(void) = *reader;
  if (again() != 13) return 1;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_global_function_pointer_array_initializer_uses_symbol_relocation(self) -> None:
        source = """
int plus_one(int value) { return value + 1; }
int (*table[])(int) = { plus_one };
int main(void) {
  if (table[0](4) != 5) return 1;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_global_pointer_initializers_fold_compound_and_subobject_addresses(self) -> None:
        source = r"""
struct Pair { int first; int second; };
struct Holder { struct Pair pair; int tail; };

static int values[4] = {10, 20, 30, 40};
static int *left_add = 1 + values;
static int *minus_one = values + 3 - 1;
static int *subscript_ptr = &values[2];
static int *decayed = values;
static char *message = "ok";
static void *missing = (void *)0;
static struct Pair *compound_ptr = &(struct Pair){7, 8};
static struct Holder holders[2] = {{{1, 2}, 3}, {{4, 5}, 6}};
static int *member_ptr = &holders[1].pair.second;

int main(void) {
  if (*left_add != 20) return 1;
  if (*minus_one != 30) return 2;
  if (*subscript_ptr != 30) return 3;
  if (*decayed != 10) return 4;
  if (message[0] != 'o' || message[1] != 'k' || message[2] != 0) return 5;
  if (missing != (void *)0) return 6;
  if (compound_ptr->first != 7 || compound_ptr->second != 8) return 7;
  if (*member_ptr != 5) return 8;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_typeof_local_declaration_uses_expression_type(self) -> None:
        source = """
struct Obj { int value; };
int main(void) {
  struct Obj obj;
  struct Obj *p = &obj;
  typeof(p) q = p;
  typeof(p) *slot = &q;
  (*slot)->value = 6;
  if (obj.value != 6) return 1;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_local_typedef_anonymous_record_preserves_member_layout(self) -> None:
        source = """
typedef struct { long (*length)(void *); int tag; } Methods;
struct Type { Methods *methods; };
long get_size(struct Type *type) {
  Methods *m = type->methods;
  return m->tag;
}
int main(void) {
  Methods methods;
  struct Type type;
  methods.tag = 12;
  type.methods = &methods;
  if (get_size(&type) != 12) return 1;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_record_compound_literal_assignment_stores_designated_fields(self) -> None:
        source = """
struct Mode { int kind; char quote; int quote_size; int in_debug; };
struct Tok { struct Mode modes[2]; int index; };
int main(void) {
  struct Tok tok;
  tok.modes[0] = (struct Mode){ .kind = 7, .quote = '\\0', .quote_size = 2 };
  if (tok.modes[0].kind != 7) return 1;
  if (tok.modes[0].quote != '\\0') return 2;
  if (tok.modes[0].quote_size != 2) return 3;
  if (tok.modes[0].in_debug != 0) return 4;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_compound_literals_initialize_scalar_and_array_storage(self) -> None:
        asm = self._asm(
            """
struct Pair { long left; long right; };

int scalar_literal(void) {
  int *p = &(int){7};
  return *p;
}

long array_of_records(void) {
  struct Pair *items = (struct Pair[]){{1, 2}, {3, 4}};
  return items[0].left + items[1].right * 10;
}
"""
        )

        self.assertIn("_scalar_literal:", asm)
        self.assertIn("    str w0, [sp, #8]", asm)
        self.assertIn("    str x0, [sp, #0]", asm)
        self.assertIn("_array_of_records:", asm)
        self.assertIn("    add x11, x11, #8", asm)
        self.assertIn("    str x0, [x11]", asm)
        self.assertIn("    add x11, x11, x10, lsl #4", asm)

    def test_record_compound_literal_assignment_copies_aggregate_field(self) -> None:
        source = """
struct Inner { int a; int b; };
struct Outer { int total; struct Inner inner; };
int main(void) {
  struct Inner inner = { 3, 5 };
  struct Outer outer;
  outer = (struct Outer){ .total = 8, .inner = inner };
  if (outer.total != 8) return 1;
  if (outer.inner.a != 3) return 2;
  if (outer.inner.b != 5) return 3;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_record_compound_literal_assignment_initializes_array_field(self) -> None:
        source = """
struct Holder { int values[3]; int tag; };
struct Pair { int left; int right; };
struct Matrix { struct Pair pairs[2]; int tag; };
int main(void) {
  struct Holder holder;
  struct Matrix matrix;
  holder = (struct Holder){ .values = { 1, 2, 3 }, .tag = 4 };
  matrix = (struct Matrix){ .pairs = { { 5, 6 }, { 7, 8 } }, .tag = 9 };
  if (holder.values[0] != 1) return 1;
  if (holder.values[1] != 2) return 2;
  if (holder.values[2] != 3) return 3;
  if (holder.tag != 4) return 4;
  if (matrix.pairs[0].left != 5) return 5;
  if (matrix.pairs[0].right != 6) return 6;
  if (matrix.pairs[1].left != 7) return 7;
  if (matrix.pairs[1].right != 8) return 8;
  return matrix.tag == 9 ? 0 : 10;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_record_assignment_copies_aggregate_lvalue_bytes(self) -> None:
        source = """
struct Counts { int total; int bound; };
int main(void) {
  struct Counts src = { 3, 5 };
  struct Counts dst = { 0, 0 };
  struct Counts *out = &dst;
  *out = src;
  if (dst.total != 3) return 1;
  if (dst.bound != 5) return 2;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_record_return_paths_execute_conditional_call_and_indirect_returns(self) -> None:
        source = """
struct Small { int a; int b; };
struct Big { long a; long b; long c; };

struct Small choose_small(int flag) {
  struct Small yes = {1, 2};
  struct Small no = {3, 4};
  return flag ? yes : no;
}

struct Small call_small(int flag) {
  return choose_small(flag);
}

struct Big choose_big(int flag) {
  struct Big yes = {5, 6, 7};
  struct Big no = {8, 9, 10};
  return flag ? yes : no;
}

struct Big call_big(int flag) {
  return choose_big(flag);
}

struct Big literal_big(void) {
  return (struct Big){11, 12, 13};
}

int main(void) {
  struct Small a = choose_small(1);
  struct Small b = call_small(0);
  struct Big c = choose_big(1);
  struct Big d = call_big(0);
  struct Big e = literal_big();
  if (a.a != 1 || a.b != 2) return 1;
  if (b.a != 3 || b.b != 4) return 2;
  if (c.a != 5 || c.b != 6 || c.c != 7) return 3;
  if (d.a != 8 || d.b != 9 || d.c != 10) return 4;
  if (e.a != 11 || e.b != 12 || e.c != 13) return 5;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_local_record_initializer_list_stores_fields(self) -> None:
        source = """
struct View { void *buf; long len; };
int main(void) {
  struct View view = { (void *)0, 3 };
  if (view.buf != (void *)0) return 1;
  if (view.len != 3) return 2;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_local_record_initializer_accepts_nested_designated_record_field(self) -> None:
        source = """
struct Inner { int value; };
struct Outer { int tag; struct Inner inner; int tail; };
int main(void) {
  struct Outer outer = { .tag = 1, .inner = { .value = 2 }, .tail = 3 };
  if (outer.tag != 1) return 1;
  if (outer.inner.value != 2) return 2;
  if (outer.tail != 3) return 3;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_local_record_initializer_copies_aggregate_lvalue(self) -> None:
        source = """
struct Complex { double real; double imag; };
int main(void) {
  struct Complex a = { 1.5, 2.5 };
  struct Complex r = a;
  r.real += 1.0;
  if (a.real != 1.5) return 1;
  if (r.real != 2.5) return 2;
  if (r.imag != 2.5) return 3;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_local_record_initializer_accepts_conditional_aggregate(self) -> None:
        source = """
struct Pair { int a; int b; };
int check(int flag) {
  struct Pair first = { 4, 5 };
  struct Pair selected = flag ? first : (struct Pair){ 6, 7 };
  return selected.a * 10 + selected.b;
}
int main(void) {
  if (check(1) != 45) return 1;
  if (check(0) != 67) return 2;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_local_nested_aggregate_zero_initializer_keeps_zeroed_storage(self) -> None:
        source = """
struct Inner { int a; long b; };
struct Outer { struct Inner inner; int c; };
int main(void) {
  struct Outer value = {0};
  if (value.inner.a != 0) return 1;
  if (value.inner.b != 0) return 2;
  if (value.c != 0) return 3;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_conditional_expr_evaluates_selected_scalar_and_void_branch(self) -> None:
        source = """
void mark(int *p, int value) { *p = value; }
int main(void) {
  int hit = 0;
  int x = 1 ? 4 : 9;
  int y = 0 ? 4 : 9;
  if (x != 4) return 1;
  if (y != 9) return 2;
  0 ? mark(&hit, 1) : (void)0;
  if (hit != 0) return 3;
  1 ? mark(&hit, 7) : (void)0;
  if (hit != 7) return 4;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_float_conditions_compare_with_fcmp_zero(self) -> None:
        source = """
int main(void) {
  double value = 0.0;
  if (value) return 1;
  value = 2.0;
  if (!value) return 2;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_float_unary_minus_uses_fneg(self) -> None:
        source = """
int main(void) {
  double x = 1.5;
  float y = 2.0f;
  if (-x != -1.5) return 1;
  if (-y != -2.0f) return 2;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_null_statement_is_noop(self) -> None:
        asm = self._asm("int main(void){ ; return 0; }")
        self.assertIn(".globl _main\n_main:", asm)
        self.assertIn("    mov w0, #0", asm)
        self.assertNotIn("NullStmt", asm)

    def test_static_assert_decl_is_codegen_noop(self) -> None:
        source = """
int main(void) {
  _Static_assert(sizeof(int) == 4, "int size");
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_autoconf_run_probe_calls_and_short_circuit(self) -> None:
        source = """
typedef struct __sFILE FILE;
FILE *fopen(const char *, const char *);
int ferror(FILE *);
int fclose(FILE *);
int main(void) {
  FILE *f = fopen("/tmp/xcc-a64-autoconf-probe", "w");
  if (!f) return 1;
  return ferror(f) || fclose(f) != 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_unused_inline_body_is_not_emitted(self) -> None:
        source = """
extern inline int unused(int x) { while (x) return 1; return 0; }
static inline int also_unused(int x) { while (x) return 2; return 0; }
int main(void) { return 0; }
"""
        asm = self._asm(source)
        self.assertIn(".globl _main\n_main:", asm)
        self.assertNotIn("_unused:", asm)
        self.assertNotIn("_also_unused:", asm)

    def test_used_static_inline_body_is_emitted_as_local_function(self) -> None:
        source = """
static inline unsigned long set_bit(unsigned long *value, unsigned long bit) {
  return __atomic_fetch_or(value, bit, 5);
}
int main(void) {
  unsigned long value = 2;
  if (set_bit(&value, 8) != 2) return 1;
  return value == 10 ? 0 : 2;
}
"""
        asm = self._asm(source, options=FrontendOptions(std="gnu11"))

        self.assertIn("_set_bit:", asm)
        self.assertNotIn(".globl _set_bit", asm)
        self.assertEqual(self._run(source, options=FrontendOptions(std="gnu11")), 0)

    def test_referenced_inline_function_designators_are_emitted(self) -> None:
        source = """
typedef int (*fn)(int);
static inline int add_one(int x) { return x + 1; }
extern inline int add_two(int x) { return x + 2; }
static fn table[] = { add_one, add_two };
int apply(int flag, int x) {
  fn chosen = flag ? add_one : add_two;
  int left = chosen(x);
  int right = table[flag](x);
  return left * 10 + right;
}
int main(void) {
  if (apply(0, 3) != 54) return 1;
  if (apply(1, 3) != 45) return 2;
  return 0;
}
"""
        asm = self._asm(source, options=FrontendOptions(std="gnu11"))

        self.assertIn("_add_one:", asm)
        self.assertNotIn(".globl _add_one", asm)
        self.assertIn("_add_two:", asm)
        self.assertNotIn(".globl _add_two", asm)
        self.assertEqual(self._run(source, options=FrontendOptions(std="gnu11")), 0)

    def test_void_cast_emits_call_but_discards_function_designator(self) -> None:
        source = """
void ac_decl(int, char *);
int main(void) {
  (void) ac_decl(0, (char *) 0);
  (void) ac_decl;
  return 0;
}
void ac_decl(int x, char *p) { (void) x; (void) p; }
"""
        asm = self._asm(source)
        self.assertIn("    bl _ac_decl", asm)
        self.assertEqual(self._run(source), 0)

    def test_func_identifier_returns_function_name_literal(self) -> None:
        asm = self._asm("const char *current(void) { return __func__; }")
        self.assertIn('    .asciz "current"', asm)
        self.assertIn("    adrp x0, L_.cstr0@PAGE", asm)

    def test_sizeof_and_alignof_emit_darwin_aarch64_constants(self) -> None:
        source = """
typedef unsigned long size_t;
struct Pair { char c; long x; };
int main(void) {
  if (sizeof(int) != 4) return 1;
  if (sizeof(long double) != 8) return 2;
  if (sizeof(void *) != 8) return 3;
  if (sizeof(size_t) != 8) return 4;
  if (__alignof__(struct Pair) != 8) return 5;
  if (__builtin_offsetof(struct Pair, x) != 8) return 7;
  if (sizeof(struct Pair) != 16) return 6;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_long_double_array_bound_uses_darwin_data_layout_in_every_stage(self) -> None:
        asm = self._asm(
            "char storage[sizeof(long double)]; long storage_size(void) { return sizeof(storage); }"
        )

        self.assertIn("    .zero 8", asm)
        self.assertNotIn("    .zero 16", asm)
        self.assertIn("    mov w0, #8", asm)

    def test_sizeof_member_chains_and_nested_offsetof_execute(self) -> None:
        source = """
struct Inner { char c; long value; };
struct Outer { int tag; struct Inner inner; };
struct Outer global_outer;

long member_sizes(struct Outer *outer) {
  return sizeof(outer->inner.value) + sizeof(outer->inner);
}

long nested_offset(void) {
  return __builtin_offsetof(struct Outer, inner.value);
}

long global_member_size(void) {
  return sizeof(global_outer.inner.value);
}

int main(void) {
  struct Outer outer;
  if (member_sizes(&outer) != 24) return 1;
  if (nested_offset() != 16) return 2;
  if (global_member_size() != 8) return 3;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_alignof_record_respects_explicit_member_alignment(self) -> None:
        source = """
struct ExplicitlyAligned { _Alignas(16) char tag; };
int main(void) {
  if (__alignof__(struct ExplicitlyAligned) != 16) return 1;
  if (sizeof(struct ExplicitlyAligned) != 16) return 2;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_offsetof_typedef_anonymous_record_uses_registered_layout(self) -> None:
        source = """
typedef struct { char x; long y; } ac__type_alignof_;
int main(void) {
  if (__builtin_offsetof(ac__type_alignof_, y) != 8) return 1;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_offsetof_anonymous_record_with_function_pointer_members(self) -> None:
        source = """
typedef struct { int (*first)(int); long middle; int (*second)(void *); } Methods;
int main(void) {
  if (__builtin_offsetof(Methods, second) != 16) return 1;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_sizeof_anonymous_record_with_enum_member_matches_layout(self) -> None:
        source = """
enum Cmp { Is = 1 };
int main(void) {
  if (sizeof(struct { enum Cmp cmp; void *expr; }) != 16) return 1;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_block_scope_tagged_record_uses_scoped_layout_for_later_tag_uses(self) -> None:
        source = """
int main(void) {
  struct s { int j; const int *ap[3]; } bx;
  struct s *b = &bx;
  b->j = 5;
  if (bx.j != 5) return 1;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_struct_with_flexible_array_member_has_sized_prefix(self) -> None:
        source = """
struct Header {
  long refcnt;
  unsigned char tag;
  unsigned int version;
  long used;
  char bytes[];
};
static struct Header h = {1, 2, 3, 4, {5, 6, 7, 8}};
int main(void) {
  if (sizeof(struct Header) != 24) return 1;
  if (h.bytes[3] != 8) return 2;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_block_local_declarations_in_if_branches_have_slots(self) -> None:
        source = """
int main(void) {
  if (0) {
    long i = 1;
    if (i != 1) return 2;
  } else {
    unsigned long i = 4;
    if (i != sizeof(int)) return 3;
  }
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_darwin_variadic_args_are_passed_on_stack(self) -> None:
        path = Path("/tmp/xcc-a64-varargs.val")
        path.unlink(missing_ok=True)
        source = """
typedef struct __sFILE FILE;
FILE *fopen(const char *, const char *);
int fprintf(FILE *, const char *, ...);
int fclose(FILE *);
int main(void) {
  FILE *f = fopen("/tmp/xcc-a64-varargs.val", "w");
  if (!f) return 1;
  unsigned long value = 4;
  fprintf(f, "%lu", value);
  return fclose(f);
}
"""
        self.assertEqual(self._run(source), 0)
        self.assertEqual(path.read_text(encoding="utf-8"), "4")

    def test_darwin_variadic_aggregate_args_use_stack_abi(self) -> None:
        caller = """
struct Pair { long a; int b; };
struct Large { long a; long b; long c; };
int read_pair(int tag, ...);
int read_large(int tag, ...);
int main(void) {
  struct Pair pair = {4, 5};
  struct Large large = {1, 2, 3};
  if (read_pair(1, pair) != 0) return 1;
  if (read_large(2, large) != 0) return 2;
  return 0;
}
"""
        callee = """
#include <stdarg.h>
struct Pair { long a; int b; };
struct Large { long a; long b; long c; };
int read_pair(int tag, ...) {
  va_list ap;
  va_start(ap, tag);
  struct Pair pair = va_arg(ap, struct Pair);
  va_end(ap);
  return pair.a == 4 && pair.b == 5 ? 0 : 1;
}
int read_large(int tag, ...) {
  va_list ap;
  va_start(ap, tag);
  struct Large large = va_arg(ap, struct Large);
  va_end(ap);
  return large.a == 1 && large.b == 2 && large.c == 3 ? 0 : 1;
}
"""
        caller_asm = self._asm(caller)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            caller_asm_path = root / "caller.s"
            caller_obj = root / "caller.o"
            callee_path = root / "callee.c"
            callee_obj = root / "callee.o"
            exe_path = root / "a.out"
            caller_asm_path.write_text(caller_asm, encoding="utf-8")
            callee_path.write_text(callee, encoding="utf-8")
            assemble = subprocess.run(
                [
                    "clang",
                    "-target",
                    "aarch64-apple-darwin",
                    "-c",
                    str(caller_asm_path),
                    "-o",
                    str(caller_obj),
                ],
                capture_output=True,
                check=False,
                text=True,
            )
            self.assertEqual(assemble.returncode, 0, assemble.stderr)
            compile_callee = subprocess.run(
                [
                    "clang",
                    "-target",
                    "aarch64-apple-darwin",
                    "-c",
                    str(callee_path),
                    "-o",
                    str(callee_obj),
                ],
                capture_output=True,
                check=False,
                text=True,
            )
            self.assertEqual(compile_callee.returncode, 0, compile_callee.stderr)
            link = subprocess.run(
                [
                    "clang",
                    "-target",
                    "aarch64-apple-darwin",
                    str(caller_obj),
                    str(callee_obj),
                    "-o",
                    str(exe_path),
                ],
                capture_output=True,
                check=False,
                text=True,
            )
            self.assertEqual(link.returncode, 0, link.stderr)
            run = subprocess.run([str(exe_path)], check=False)
            self.assertEqual(run.returncode, 0)

    def test_variadic_definition_lowers_va_start_and_va_end(self) -> None:
        source = """
void consume(__builtin_va_list);
void f(const char *format, ...) {
  __builtin_va_list va;
  __builtin_va_start(va, format);
  consume(va);
  __builtin_va_end(va);
}
"""
        asm = self._asm(source)
        self.assertIn("    str x10, [x11]", asm)
        self.assertIn("    bl _consume", asm)
        self.assertNotIn("___builtin_va_end", asm)

    def test_variadic_definition_reads_integer_and_pointer_va_args(self) -> None:
        source = """
int first_int(int count, ...) {
  __builtin_va_list ap;
  __builtin_va_start(ap, count);
  int value = __builtin_va_arg(ap, int);
  __builtin_va_end(ap);
  return value;
}
int first_pointed(int count, ...) {
  __builtin_va_list ap;
  __builtin_va_start(ap, count);
  int *value = __builtin_va_arg(ap, int *);
  __builtin_va_end(ap);
  return *value;
}
int main(void) {
  int value = 9;
  if (first_int(1, 7) != 7) return 1;
  if (first_pointed(1, &value) != 9) return 2;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_variadic_definition_reads_aggregate_va_args(self) -> None:
        source = """
struct Pair { long a; int b; };
struct Large { long a; long b; long c; };

int read_pair(int tag, ...) {
  __builtin_va_list ap;
  __builtin_va_start(ap, tag);
  struct Pair pair = __builtin_va_arg(ap, struct Pair);
  __builtin_va_end(ap);
  return pair.a == 4 && pair.b == 5 ? 0 : 1;
}

int read_large(int tag, ...) {
  __builtin_va_list ap;
  __builtin_va_start(ap, tag);
  struct Large large = __builtin_va_arg(ap, struct Large);
  __builtin_va_end(ap);
  return large.a == 1 && large.b == 2 && large.c == 3 ? 0 : 1;
}

int main(void) {
  struct Pair pair = {4, 5};
  struct Large large = {1, 2, 3};
  if (read_pair(1, pair) != 0) return 1;
  if (read_large(2, large) != 0) return 2;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_gnu_atomic_builtins_lower_without_external_symbols(self) -> None:
        source = """
int main(void)
{
  unsigned long value;
  unsigned char byte;
  unsigned long expected;
  __atomic_store_n(&value, 2, 5);
  if (__atomic_fetch_or(&value, 8, 5) != 2) return 1;
  if (__atomic_load_n(&value, 5) != 10) return 2;
  byte = 0xb8;
  if (__atomic_fetch_or(&byte, 0x2d, 5) != 0xb8) return 3;
  if (__atomic_load_n(&byte, 5) != 0xbd) return 4;
  if (__atomic_exchange_n(&byte, 7, 5) != 0xbd) return 5;
  expected = 10;
  if (!__atomic_compare_exchange_n(&value, &expected, 3, 0, 5, 5)) return 6;
  if (value != 3) return 7;
  __atomic_thread_fence(5);
  return 0;
}
"""
        asm = self._asm(source, options=FrontendOptions(std="gnu11"))

        self.assertNotIn("bl ___atomic", asm)
        self.assertIn("ldaxr", asm)
        self.assertEqual(self._run(source, options=FrontendOptions(std="gnu11")), 0)

    def test_gnu_atomic_variant_builtins_execute_inline(self) -> None:
        source = """
int main(void)
{
  int value = 5;
  int out = 0;
  int old = 0;
  int desired = 13;
  int expected = 0;
  __atomic_store(&value, &desired, 5);
  if (value != 13) return 1;
  desired = 17;
  __atomic_exchange(&value, &desired, &old, 5);
  if (old != 13) return 2;
  if (value != 17) return 3;
  __atomic_load(&value, &out, 5);
  if (out != 17) return 4;
  if (!__atomic_is_lock_free(sizeof(value), &value)) return 5;
  if (!__atomic_always_lock_free(sizeof(value), &value)) return 6;
  __atomic_signal_fence(5);
  __sync_synchronize();

  value = 5;
  if (__atomic_fetch_add(&value, 2, 5) != 5) return 7;
  if (__atomic_add_fetch(&value, 3, 5) != 10) return 8;
  if (__atomic_fetch_sub(&value, 4, 5) != 10) return 9;
  if (__atomic_sub_fetch(&value, 1, 5) != 5) return 10;
  if (__atomic_fetch_and(&value, 6, 5) != 5) return 11;
  if (__atomic_or_fetch(&value, 1, 5) != 5) return 12;
  if (__atomic_fetch_xor(&value, 7, 5) != 5) return 13;
  if (__atomic_nand_fetch(&value, 3, 5) != -3) return 14;

  value = 3;
  expected = 3;
  desired = 8;
  if (!__atomic_compare_exchange(&value, &expected, &desired, 0, 5, 5)) return 15;
  if (value != 8) return 16;
  expected = 3;
  desired = 10;
  if (__atomic_compare_exchange(&value, &expected, &desired, 0, 5, 5)) return 17;
  if (expected != 8) return 18;

  value = 4;
  if (__sync_fetch_and_add(&value, 2) != 4) return 19;
  if (__sync_sub_and_fetch(&value, 1) != 5) return 20;
  if (!__sync_bool_compare_and_swap(&value, 5, 9)) return 21;
  if (__sync_val_compare_and_swap(&value, 9, 11) != 9) return 22;
  return value == 11 ? 0 : 23;
}
"""
        asm = self._asm(source, options=FrontendOptions(std="gnu11"))

        self.assertNotIn("bl ___atomic", asm)
        self.assertNotIn("bl ___sync", asm)
        self.assertIn("dmb ish", asm)
        self.assertIn("ldaxr", asm)
        self.assertEqual(self._run(source, options=FrontendOptions(std="gnu11")), 0)

    def test_common_gcc_builtins_lower_without_external_symbols(self) -> None:
        source = """
void *sink;
int never(int x) {
  if (x) return 7;
  __builtin_unreachable();
}
int copied_va(int count, ...) {
  __builtin_va_list ap;
  __builtin_va_list copy;
  __builtin_va_start(ap, count);
  __builtin_va_copy(copy, ap);
  int value = __builtin_va_arg(copy, int);
  __builtin_va_end(copy);
  __builtin_va_end(ap);
  return value;
}
int main(void)
{
  char buf[16];
  unsigned int x = 0x01020304U;
  unsigned long l = 1UL;
  unsigned long long ll = 8ULL;
  sink = __builtin_assume_aligned(buf, 8);
  sink = __builtin_alloca(4);
  if (__builtin_expect(x == 0, 0)) return 1;
  if (__builtin_bswap32(x) != 0x04030201U) return 2;
  if (__builtin_popcount(0xf0) != 4) return 3;
  if (__builtin_clzl(l) != 63) return 4;
  if (__builtin_ctzll(ll) != 3) return 5;
  if (__builtin_flt_rounds() != 1) return 6;
  if (!__builtin_isinf(__builtin_inff())) return 7;
  if (!__builtin_isnan(__builtin_nanf(""))) return 8;
  if (!__builtin_isfinite(1.0)) return 9;
  if (copied_va(1, 42) != 42) return 10;
  if (never(1) != 7) return 11;
  if (__builtin_fabs(-3.0) != 3.0) return 12;
  (void)__builtin_frame_address(0);
  return 0;
}
"""
        asm = self._asm(source, options=FrontendOptions(std="gnu11"))

        self.assertNotIn("___builtin_", asm)
        self.assertNotIn("bl _assert", asm)
        self.assertEqual(self._run(source, options=FrontendOptions(std="gnu11")), 0)

    def test_builtin_variants_emit_inline_aarch64_text_paths(self) -> None:
        source = """
int isnan_float(float value) { return __builtin_isnan(value); }
int isinf_double(double value) { return __builtin_isinf(value); }
int finite_int(int value) { return __builtin_isfinite(value); }
int first_bit(unsigned value) { return __builtin_ffs(value); }
int count_long(unsigned long value) { return __builtin_popcountl(value); }
unsigned short swap16(unsigned short value) { return __builtin_bswap16(value); }
signed char atomic_load_char(signed char *ptr) { return __atomic_load_n(ptr, 5); }
void atomic_store_short(short *ptr, short value) { __atomic_store_n(ptr, value, 5); }
int atomic_cas_short(short *ptr, short *expected, short desired) {
  return __atomic_compare_exchange_n(ptr, expected, desired, 0, 5, 5);
}
void sync_release_char(signed char *ptr) { __sync_lock_release(ptr); }
"""
        asm = self._asm(source, options=FrontendOptions(std="gnu11"))

        self.assertIn("    fcmp s0, s0", asm)
        self.assertIn("    cset w0, vs", asm)
        self.assertIn("    fabs d0, d0", asm)
        self.assertIn("    cset w0, eq", asm)
        self.assertIn("    scvtf d0, w0", asm)
        self.assertIn("    cbz w0, L_L_ffs_zero", asm)
        self.assertIn("    rbit w0, w0", asm)
        self.assertIn("    clz w0, w0", asm)
        self.assertIn("L_L_popcount_loop", asm)
        self.assertIn("    rev w0, w0", asm)
        self.assertIn("    lsr w0, w0, #16", asm)
        self.assertIn("    ldarb w0, [x11]", asm)
        self.assertIn("    sxtb w0, w0", asm)
        self.assertIn("    stlrh w", asm)
        self.assertIn("    ldaxrh w", asm)
        self.assertIn("    sxth w", asm)
        self.assertIn("    stlrb w10, [x11]", asm)
        self.assertNotIn("bl ___builtin_", asm)
        self.assertNotIn("bl ___atomic", asm)

    def test_global_builtin_float_constant_calls_emit_data(self) -> None:
        source = """
static float pos_inf = __builtin_inff();
static double huge = __builtin_huge_val();
static double abs_d = __builtin_fabs(-1.25);
static float abs_f = __builtin_fabsf(-2.5f);
float get_abs_f(void) { return abs_f; }
double get_abs_d(void) { return abs_d; }
"""
        asm = self._asm(source, options=FrontendOptions(std="gnu11"))

        self.assertIn("L_.pos_inf:", asm)
        self.assertIn("    .long 0x7f800000", asm)
        self.assertIn("L_.huge:", asm)
        self.assertIn("    .quad 0x7ff0000000000000", asm)
        self.assertIn("L_.abs_d:", asm)
        self.assertIn("    .quad 0x3ff4000000000000", asm)
        self.assertIn("L_.abs_f:", asm)
        self.assertIn("    .long 0x40200000", asm)

    def test_extern_data_symbols_use_darwin_got_relocations(self) -> None:
        source = """
extern void *__stderrp;
int main(void) {
  void **slot = &__stderrp;
  void *stream = __stderrp;
  return slot != 0 && stream != 0 ? 0 : 1;
}
"""
        asm = self._asm(source)

        self.assertIn("___stderrp@GOTPAGE", asm)
        self.assertIn("___stderrp@GOTPAGEOFF", asm)
        self.assertEqual(self._run(source), 0)

    def test_extern_function_designators_use_darwin_got_relocations(self) -> None:
        source = """
extern void *malloc(unsigned long);
int main(void) {
  void *(*allocate)(unsigned long) = malloc;
  return allocate(1) != 0 ? 0 : 1;
}
"""
        asm = self._asm(source)

        self.assertIn("_malloc@GOTPAGE", asm)
        self.assertIn("_malloc@GOTPAGEOFF", asm)
        self.assertEqual(self._run(source), 0)

    def test_c11_atomic_header_probe_lowers_without_external_symbols(self) -> None:
        source = """
#include <stdatomic.h>
atomic_int int_var;
atomic_uintptr_t uintptr_var;
int main(void)
{
  atomic_store_explicit(&int_var, 5, memory_order_relaxed);
  atomic_store_explicit(&uintptr_var, 0, memory_order_relaxed);
  return atomic_load_explicit(&int_var, memory_order_seq_cst) == 5 ? 0 : 1;
}
"""
        asm = self._asm(source)

        self.assertNotIn("bl ___c11_atomic", asm)
        self.assertEqual(self._run(source), 0)

    def test_integer_arguments_beyond_eight_use_stack_slots(self) -> None:
        source = """
int sum10(int a0, int a1, int a2, int a3, int a4,
          int a5, int a6, int a7, int a8, int a9) {
  return a0 + a1 + a2 + a3 + a4 + a5 + a6 + a7 + a8 + a9;
}
int main(void) {
  if (sum10(1, 2, 3, 4, 5, 6, 7, 8, 9, 10) != 55) return 1;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_large_calling_frame_materializes_frame_record_address(self) -> None:
        source = """
void sink(void) {}
int main(void) {
  int values[200];
  values[0] = 3;
  sink();
  if (values[0] != 3) return 1;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_large_stack_frame_materializes_sp_adjust_and_slot_offsets(self) -> None:
        source = """
void sink(void) {}
int main(void) {
  char padding[4300];
  char flag = 7;
  padding[0] = 1;
  sink();
  if (flag != 7) return 1;
  if (padding[0] != 1) return 2;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_homogeneous_double_record_argument_uses_fp_registers(self) -> None:
        source = """
struct Complex { double real; double imag; };
void take(struct Complex);
int main(void) {
  struct Complex value;
  value.real = 1.0;
  value.imag = 2.0;
  take(value);
  return 0;
}
"""
        asm = self._asm(source)
        self.assertIn("    ldr d0, [x11, #0]", asm)
        self.assertIn("    ldr d1, [x11, #8]", asm)
        self.assertIn("    bl _take", asm)

    def test_homogeneous_double_record_return_stores_fp_registers(self) -> None:
        source = """
struct Complex { double real; double imag; };
struct Complex make(double real, double imag) {
  struct Complex value;
  value.real = real;
  value.imag = imag;
  return value;
}
int main(void) {
  struct Complex value;
  value = make(1.5, 2.5);
  if (value.real != 1.5) return 1;
  if (value.imag != 2.5) return 2;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_homogeneous_double_record_return_forwards_call_registers(self) -> None:
        source = """
struct Complex { double real; double imag; };
struct Complex make(double real, double imag) {
  struct Complex value;
  value.real = real;
  value.imag = imag;
  return value;
}
struct Complex wrap(double real, double imag) {
  return make(real, imag);
}
int main(void) {
  struct Complex value;
  value = wrap(3.5, 4.5);
  if (value.real != 3.5) return 1;
  if (value.imag != 4.5) return 2;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_homogeneous_double_record_call_argument_uses_fp_cursor(self) -> None:
        source = """
struct Complex { double real; double imag; };
struct Complex one = { 1.0, 2.0 };
struct Complex make(double real, double imag) {
  struct Complex value;
  value.real = real;
  value.imag = imag;
  return value;
}
struct Complex add(struct Complex left, struct Complex right) {
  struct Complex value;
  value.real = left.real + right.real;
  value.imag = left.imag + right.imag;
  return value;
}
int main(void) {
  struct Complex value;
  value = add(one, make(3.0, 4.0));
  if (value.real != 4.0) return 1;
  if (value.imag != 6.0) return 2;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_small_integer_pointer_record_return_uses_x0_x1(self) -> None:
        source = """
struct Pair { void *object; int kind; };
struct Pair make_pair(void *object) {
  struct Pair pair;
  pair.object = object;
  pair.kind = 3;
  return pair;
}
"""
        asm = self._asm(source)
        self.assertIn("    ldr x0, [x11]", asm)
        self.assertIn("    add x12, x11, #8", asm)
        self.assertIn("    ldr w1, [x12]", asm)

    def test_small_integer_record_argument_uses_consecutive_x_registers(self) -> None:
        source = """
struct Pair { long first; long second; };
long sum_pair(struct Pair pair, long extra) {
  return pair.first + pair.second + extra;
}
int main(void) {
  struct Pair pair = { 2, 3 };
  if (sum_pair(pair, 4) != 9) return 1;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_small_record_argument_with_anonymous_union_fields_uses_integer_chunks(self) -> None:
        source = """
struct Slot {
  unsigned short id;
  unsigned short flags;
  union { unsigned int reserved; };
  union { void *ptr; long size; };
};
long use_slot(struct Slot slot) {
  return slot.id + slot.flags + slot.reserved + slot.size;
}
int main(void) {
  struct Slot slot = {0};
  slot.id = 1;
  slot.flags = 2;
  slot.reserved = 3;
  slot.size = 4;
  if (use_slot(slot) != 10) return 1;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_large_record_argument_uses_temporary_copy_pointer(self) -> None:
        source = """
struct Token { long a; long b; long c; };
int inspect(int prefix, struct Token token, int suffix) {
  token.a = 99;
  return prefix + token.c + suffix;
}
int main(void) {
  struct Token token = { 1, 2, 3 };
  if (inspect(4, token, 5) != 12) return 1;
  if (token.a != 1) return 2;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_call_returned_small_union_argument_preserves_earlier_args(self) -> None:
        source = """
union Ref { unsigned long bits; };
union Ref make_ref(unsigned long value) {
  return (union Ref){ .bits = value };
}
unsigned long take(void *ptr, union Ref ref) {
  return (ptr != (void *)0) + ref.bits;
}
int main(void) {
  int marker = 0;
  if (take(&marker, make_ref(4)) != 5) return 1;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_call_returned_record_argument_preserves_stack_based_nested_args(self) -> None:
        source = """
struct Pair { long first; long second; };
struct Pair make_pair(long *value) {
  return (struct Pair){ *value + 1, *value + 2 };
}
int take(long *value, struct Pair pair, long *again) {
  if (value != again) return 1;
  if (*value != 5) return 2;
  if (pair.first != 6) return 3;
  if (pair.second != 7) return 4;
  return 0;
}
int main(void) {
  long value = 5;
  long *ptr = &value;
  return take(ptr, make_pair(ptr), ptr);
}
"""
        self.assertEqual(self._run(source), 0)

    def test_call_returned_hfa_argument_preserves_overlapping_fp_results(self) -> None:
        source = """
struct PairD { double first; double second; };
struct PairD make_pair(double value) {
  return (struct PairD){ value + 1.0, value + 2.0 };
}
double take(double prefix, struct PairD pair) {
  return prefix + pair.first * 10.0 + pair.second;
}
int main(void) {
  double result = take(3.0, make_pair(4.0));
  if (result != 59.0) return 1;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_nested_call_argument_preserves_earlier_scalar_args(self) -> None:
        source = """
int keep(const char *p, int n) {
  if (p[0] != 'x') return 1;
  if (n != 7) return 2;
  return 0;
}
int side(void) {
  return 7;
}
int main(void) {
  const char *s = "x";
  return keep(s, side());
}
"""
        self.assertEqual(self._run(source), 0)

    def test_later_plain_argument_expression_preserves_earlier_scalar_args(self) -> None:
        source = """
int callee(char *s, long n, int mode, char *errors, long *consumed) {
  return s[0] + (int)n + mode + (errors == 0) + (consumed == 0);
}
int f(char *s, char *errors, long *consumed) {
  return callee(s, 8, errors ? 2 : 1, errors, consumed);
}
int main(void) {
  char text[2];
  text[0] = 97;
  text[1] = 0;
  if (f(text, 0, 0) != 108) return 1;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_local_array_initializers_support_nested_scalars_records_and_zero_fill(
        self,
    ) -> None:
        source = """
struct Pair { int left; int right; };

int main(void) {
  int values[4] = {1, {2}, 3};
  struct Pair pairs[3] = {{4, 5}, {0}, {6, 7}};
  if (values[0] != 1) return 1;
  if (values[1] != 2) return 2;
  if (values[2] != 3) return 3;
  if (values[3] != 0) return 4;
  if (pairs[0].left != 4 || pairs[0].right != 5) return 5;
  if (pairs[1].left != 0 || pairs[1].right != 0) return 6;
  if (pairs[2].left != 6 || pairs[2].right != 7) return 7;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_conditional_small_union_argument_loads_selected_branch(self) -> None:
        source = """
union Ref { unsigned long bits; };
unsigned long get_bits(union Ref ref) {
  return ref.bits;
}
int main(void) {
  union Ref refs[2];
  union Ref fallback;
  refs[0].bits = 3;
  refs[1].bits = 5;
  fallback.bits = 7;
  if (get_bits(1 ? refs[0] : fallback) != 3) return 1;
  if (get_bits(0 ? refs[1] : fallback) != 7) return 2;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_conditional_small_union_return_loads_selected_branch(self) -> None:
        source = """
union Ref { unsigned long bits; };
union Ref choose_ref(int pick) {
  union Ref a;
  union Ref b;
  a.bits = 11;
  b.bits = 13;
  return pick ? a : b;
}
int main(void) {
  union Ref first = choose_ref(1);
  union Ref second = choose_ref(0);
  if (first.bits != 11) return 1;
  if (second.bits != 13) return 2;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_record_return_accepts_compound_literal_address(self) -> None:
        source = """
struct Pair { void *object; long index; };
struct Pair make_pair(long index) {
  return (struct Pair){ .object = (void *)0, .index = index };
}
"""
        asm = self._asm(source)
        self.assertIn("    ldr x0, [x11]", asm)
        self.assertIn("    ldr x1, [x12]", asm)

    def test_large_record_return_writes_indirect_result_buffer(self) -> None:
        source = """
struct Status { int type; const char *func; const char *message; int code; };
struct Status ok(void) {
  return (struct Status){ .type = 1, .code = 7 };
}
"""
        asm = self._asm(source)
        self.assertIn("    str x8,", asm)
        self.assertIn("    ldr x11,", asm)
        self.assertIn("    str w0, [x11]", asm)

    def test_large_record_return_local_lvalue_reserves_scratch(self) -> None:
        source = """
struct Big { long a; long b; long c; };
struct Big copy_big(struct Big *value) {
  return *value;
}
int main(void) {
  struct Big input = { 5, 6, 7 };
  struct Big result = copy_big(&input);
  if (result.a != 5) return 1;
  if (result.b != 6) return 2;
  if (result.c != 7) return 3;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_large_record_return_conditional_writes_selected_branch(self) -> None:
        source = """
struct Status { int type; const char *func; const char *message; int code; };
struct Status choose_status(int flag) {
  return flag
    ? (struct Status){ .type = 1, .func = "choose_status", .message = "yes", .code = 5 }
    : (struct Status){ .type = 2, .func = "choose_status", .message = "no", .code = 7 };
}
int main(void) {
  struct Status yes = choose_status(1);
  struct Status no = choose_status(0);
  if (yes.type != 1) return 1;
  if (yes.code != 5) return 2;
  if (no.type != 2) return 3;
  if (no.code != 7) return 4;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_large_record_call_initializes_local_via_indirect_result_buffer(self) -> None:
        source = """
struct Status { int type; const char *func; const char *message; int code; };
struct Status make_status(int code) {
  return (struct Status){ .type = 1, .func = "make_status", .code = code };
}
int main(void) {
  struct Status status = make_status(7);
  if (status.type != 1) return 1;
  if (status.code != 7) return 2;
  if (status.func[0] != 'm') return 3;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_large_record_call_expression_statement_uses_temp_result_buffer(self) -> None:
        source = """
int side_effect;
struct Status { int type; const char *func; const char *message; int code; };
struct Status make_status(int code) {
  side_effect = code;
  return (struct Status){ .type = 1, .code = code };
}
int main(void) {
  make_status(9);
  if (side_effect != 9) return 1;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_large_record_call_assigns_lvalue_via_indirect_result_buffer(self) -> None:
        source = """
struct Status { int type; const char *func; const char *message; int code; };
struct Status make_status(int code) {
  return (struct Status){ .type = 1, .func = "make_status", .code = code };
}
int main(void) {
  struct Status status = { 0 };
  status = make_status(9);
  if (status.type != 1) return 1;
  if (status.code != 9) return 2;
  if (status.func[0] != 'm') return 3;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_large_record_return_forwards_indirect_call_result_buffer(self) -> None:
        source = """
struct Status { int type; const char *func; const char *message; int code; };
struct Status make_status(int code) {
  return (struct Status){ .type = 1, .func = "make_status", .code = code };
}
struct Status forward_status(int code) {
  return make_status(code);
}
int main(void) {
  struct Status status = forward_status(11);
  if (status.type != 1) return 1;
  if (status.code != 11) return 2;
  if (status.func[0] != 'm') return 3;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_large_record_call_member_access_materializes_temporary(self) -> None:
        source = """
struct Instruction { int opcode; int arg; long cache; long extra; };
struct Instruction make_instruction(int arg) {
  return (struct Instruction){ .opcode = 25, .arg = arg, .cache = 3, .extra = 4 };
}
int main(void) {
  if (make_instruction(7).opcode != 25) return 1;
  if (make_instruction(7).arg != 7) return 2;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_small_record_call_member_access_materializes_temporary(self) -> None:
        source = """
struct Counter { unsigned short value_and_backoff; };
struct Counter warmup(void) {
  return (struct Counter){ .value_and_backoff = 42 };
}
int main(void) {
  if (warmup().value_and_backoff != 42) return 1;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_small_union_return_assigns_to_member_lvalue(self) -> None:
        source = """
union Ref { unsigned long bits; };
struct Holder { union Ref ref; };
union Ref make_ref(unsigned long value) {
  return (union Ref){ .bits = value };
}
unsigned long get_bits(union Ref ref) {
  return ref.bits;
}
int main(void) {
  struct Holder holder;
  holder.ref = make_ref(17);
  if (holder.ref.bits != 17) return 1;
  if (get_bits(holder.ref) != 17) return 2;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_same_name_block_locals_use_declared_union_type_for_member_access(self) -> None:
        source = """
union Ref { unsigned long bits; };
int choose(int flag) {
  if (flag) {
    union Ref result;
    result.bits = 9;
    return result.bits == 9 ? 0 : 1;
  }
  void *result = (void *)0;
  return result == (void *)0 ? 0 : 2;
}
int main(void) {
  if (choose(1) != 0) return 1;
  if (choose(0) != 0) return 2;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_autoconf_float_word_order_probe_links_little_endian_data(self) -> None:
        source = """
int atoi(const char *);
double atof(const char *);
static double m[] = {9.090423496703681e+223, 0.0};
int main(int argc, char *argv[]) {
  (void) argc;
  m[atoi(argv[1])] += atof(argv[2]);
  return m[atoi(argv[3])] > 0.0;
}
"""
        self.assertIn(b"seesnoon", self._link_bytes(source))

    def test_global_float_array_initializer_accepts_constant_arithmetic(self) -> None:
        source = """
static const double values[] = {
  2.0 * 0.5,
  8.0 / 2.0,
  1.5 + 2.25,
  4.0 - 0.75,
};
int main(void) {
  if (values[0] != 1.0) return 1;
  if (values[1] != 4.0) return 2;
  if (values[2] != 3.75) return 3;
  if (values[3] != 3.25) return 4;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_mixed_integer_float_conversions_use_aarch64_conversion_ops(self) -> None:
        source = """
int main(void) {
  unsigned long alloc = 8;
  unsigned long size = 9;
  if (!(size <= alloc * 1.125)) return 1;
  if ((int)3.75 != 3) return 2;
  if ((unsigned int)3.75 != 3) return 3;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_global_string_pointer_array_emits_cstring_relocations(self) -> None:
        asm = self._asm(
            'const char * const names[] = {"NAME", "NUMBER"};\nint main(void){return 0;}'
        )
        self.assertIn(".section __DATA,__data", asm)
        self.assertIn("    .quad L_.cstr0", asm)
        self.assertIn("    .quad L_.cstr1", asm)
        self.assertIn('.asciz "NAME"', asm)
        self.assertIn('.asciz "NUMBER"', asm)

    def test_global_pointer_initializer_accepts_extern_object_symbol(self) -> None:
        asm = self._asm(
            """
extern int external_value;
int *ptr = &external_value;
int main(void) { return ptr == 0; }
"""
        )

        self.assertIn(".globl _ptr\n_ptr:", asm)
        self.assertIn("    .quad _external_value", asm)

    def test_string_literal_subscript_uses_addressable_storage(self) -> None:
        source = """
int main(void) {
  if ("kind"[1] != 'i') return 1;
  if (&"kind"[2] == (void *)0) return 2;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_wide_string_literal_pointer_uses_wide_storage(self) -> None:
        source = """
const int *empty = L"";
int main(void) {
  const int *option = L"--";
  if (empty[0] != 0) return 1;
  if (option[0] != '-') return 2;
  if (option[1] != '-') return 3;
  if (option[2] != 0) return 4;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_global_integer_array_initializer_accepts_cast_constant_expr(self) -> None:
        source = """
unsigned short flags[] = { (unsigned short)((1 << 3) | 1), 4 };
int main(void) {
  if (flags[0] != 9) return 1;
  if (flags[1] != 4) return 2;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_global_integer_initializer_accepts_cpython_version_pack_calls(self) -> None:
        source = """
int _Py_PACK_VERSION(int major, int minor);
int _Py_PACK_FULL_VERSION(
    int major, int minor, int micro, int releaselevel, int serial);
int version = _Py_PACK_VERSION(3, 13);
int full = _Py_PACK_FULL_VERSION(3, 13, 2, 7, 9);
int main(void) {
  if (version != 0x030d0000) return 1;
  if (full != 0x030d0279) return 2;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_global_array_initializer_accepts_sparse_index_designators(self) -> None:
        source = """
enum State { CREATED = 0, RUNNING = 2, DONE = 3 };
int states[4] = { [DONE] = 7, [CREATED] = 2 };
int main(void) {
  if (states[0] != 2) return 1;
  if (states[1] != 0) return 2;
  if (states[2] != 0) return 3;
  if (states[3] != 7) return 4;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_global_char_array_string_initializer_null_pads(self) -> None:
        source = """
char doc[6] = "abc";
int main(void) {
  if (doc[0] != 'a') return 1;
  if (doc[3] != 0) return 2;
  if (doc[5] != 0) return 3;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_global_record_initializer_accepts_forward_member_designator(self) -> None:
        source = """
struct Config { int first; long middle; int last; };
struct Config config = { 1, .last = 3 };
int main(void) {
  if (config.first != 1) return 1;
  if (config.middle != 0) return 2;
  if (config.last != 3) return 3;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_global_record_initializer_accepts_backward_member_designator(self) -> None:
        source = """
struct Config { int first; int middle; int last; };
struct Config config = { 1, 2, 3, .middle = 5 };
int main(void) {
  if (config.first != 1) return 1;
  if (config.middle != 5) return 2;
  if (config.last != 3) return 3;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_global_record_initializer_accepts_positional_anonymous_union(self) -> None:
        source = """
struct Obj { union { long tag; void *ptr; }; int value; };
struct Obj obj = { { 7 }, 3 };
int main(void) {
  if (obj.tag != 7) return 1;
  if (obj.value != 3) return 2;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_global_union_initializer_accepts_member_designator(self) -> None:
        source = """
union Ref { void *ptr; unsigned long bits; };
union Ref ref = { .bits = 23 };
int main(void) {
  if (ref.bits != 23) return 1;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_global_union_initializer_preserves_nested_member_designators(self) -> None:
        source = """
union Op {
  struct {
    int code;
    int arg;
  } op;
  long raw;
};
union Op table[] = {
  { .op.code = 25, .op.arg = 7 },
};
int main(void) {
  if (table[0].op.code != 25) return 1;
  if (table[0].op.arg != 7) return 2;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_global_record_initializer_accepts_promoted_anonymous_member_designators(self) -> None:
        source = """
struct Object {
  union {
    unsigned long full;
    struct {
      unsigned int refcnt;
      unsigned short overflow;
      unsigned short flags;
    };
  };
  void *type;
};
int type_value;
struct Object object = {
  .refcnt = 3,
  .flags = 5,
  .type = &type_value,
};
int main(void) {
  if (object.refcnt != 3) return 1;
  if (object.flags != 5) return 2;
  if (object.type != &type_value) return 3;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_global_record_initializer_packs_bitfield_designators(self) -> None:
        source = """
struct State {
  unsigned int interned:2;
  unsigned int kind:3;
  unsigned int compact:1;
  unsigned int ascii:1;
  unsigned int statically_allocated:1;
  unsigned int :24;
};
struct Object { long prefix; struct State state; };
struct Object object = {
  .state = {
    .kind = 5,
    .compact = 1,
    .ascii = 1,
    .statically_allocated = 1,
  },
};
int main(void) {
  unsigned int *raw = (unsigned int *)&object.state;
  if (object.state.interned != 0) return 1;
  if (object.state.kind != 5) return 2;
  if (object.state.compact != 1) return 3;
  if (object.state.ascii != 1) return 4;
  if (object.state.statically_allocated != 1) return 5;
  if (*raw != 244) return 6;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_global_record_initializer_handles_union_bitfield_flex_and_zero_edges(self) -> None:
        source = """
union Big { int tag; char bytes[8]; };
union Big big = { .tag = 7 };
struct Bits { unsigned a:3; unsigned :0; unsigned b:5; int tail; };
struct Bits bits = { 5, 17, 9 };
struct Flex { char tag; int len; char data[]; };
struct Flex flex = { .tag = 1, .len = 3, .data = "abc" };
struct Zeroed { int pad; int pair[2]; int tail; };
struct Zeroed zeroed = { .pair = 0, .tail = 4 };
int main(void) {
  if (big.tag != 7) return 1;
  if (big.bytes[4] != 0) return 2;
  if (bits.a != 5) return 3;
  if (bits.b != 17) return 4;
  if (bits.tail != 9) return 5;
  if (flex.tag != 1) return 6;
  if (flex.len != 3) return 7;
  if (flex.data[0] != 'a') return 8;
  if (flex.data[3] != 0) return 9;
  if (zeroed.pair[0] != 0) return 10;
  if (zeroed.tail != 4) return 11;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_record_compound_literal_skips_unnamed_bitfields_positionally(self) -> None:
        source = """
struct Bits { unsigned a:3; unsigned :0; unsigned b:5; int tail; };
int main(void) {
  struct Bits bits;
  bits = (struct Bits){ 5, 17, 9 };
  if (bits.a != 5) return 1;
  if (bits.b != 17) return 2;
  if (bits.tail != 9) return 3;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_global_pointer_initializer_accepts_compound_literal_storage(self) -> None:
        source = """
struct Entry { char *str; int type; };
struct Entry *sentinel = (struct Entry[]){ { (void *)0, -1 } };
int main(void) {
  if (sentinel->str != (void *)0) return 1;
  if (sentinel->type != -1) return 2;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_global_pointer_initializer_accepts_cast_address_of_compound_literal(self) -> None:
        source = """
struct Info { int version; int flags; };
void *info_ptr = (void *)&(struct Info){ 1, 7 };
int main(void) {
  struct Info *info = (struct Info *)info_ptr;
  if (info->version != 1) return 1;
  if (info->flags != 7) return 2;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_global_pointer_initializer_accepts_address_of_nested_member(self) -> None:
        source = """
struct Inner { int pad; int value; };
struct Outer { char tag; struct Inner inner; };
struct Outer global;
int *value_ptr = &global.inner.value;
int main(void) {
  global.inner.value = 17;
  if (*value_ptr != 17) return 1;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_global_pointer_initializer_accepts_casted_byte_offset_address(self) -> None:
        source = """
struct Inner { int pad; long value; };
struct Outer { char tag; struct Inner inner; };
struct Outer global;
struct Inner *inner_ptr = (struct Inner *)(
    (unsigned char *)&global + __builtin_offsetof(struct Outer, inner));
int main(void) {
  global.inner.value = 17;
  if (inner_ptr->value != 17) return 1;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_global_pointer_initializer_accepts_address_of_array_member(self) -> None:
        source = """
struct Node { struct Node *next; struct Node *prev; };
struct Bucket { int pad; struct Node root; };
struct Bucket buckets[2] = {
  [0] = { .root = { &buckets[0].root, &buckets[0].root } },
  [1] = { .root = { &buckets[1].root, &buckets[1].root } },
};
int main(void) {
  if (buckets[0].root.next != &buckets[0].root) return 1;
  if (buckets[0].root.prev != &buckets[0].root) return 2;
  if (buckets[1].root.next != &buckets[1].root) return 3;
  if (buckets[1].root.prev != &buckets[1].root) return 4;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_global_pointer_initializer_decays_member_array_through_pointer(self) -> None:
        source = """
struct Dtoa { double preallocated[4]; double *next; };
struct Interp { int pad; struct Dtoa dtoa; };
struct Runtime { struct Interp main; };
struct Runtime runtime = {
  .main = {
    .dtoa = {
      .next = (&runtime.main)->dtoa.preallocated,
    },
  },
};
int main(void) {
  if (runtime.main.dtoa.next != runtime.main.dtoa.preallocated) return 1;
  runtime.main.dtoa.next[0] = 3.5;
  if (runtime.main.dtoa.preallocated[0] != 3.5) return 2;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_global_pointer_initializer_accepts_constant_conditional_address(self) -> None:
        source = """
struct Obj { int value; };
struct Obj ascii[128];
struct Obj latin1[128];
struct Obj *selected = 'n' < 128 ? &ascii['n'] : &latin1['n' - 128];
int main(void) {
  ascii['n'].value = 23;
  if (selected != &ascii['n']) return 1;
  if (selected->value != 23) return 2;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_bitfield_member_read_extracts_packed_unsigned_bits(self) -> None:
        source = """
struct State { unsigned int interned:2; unsigned int kind:3; unsigned int compact:1; };
struct Obj { long prefix; struct State state; };
int main(void) {
  struct Obj obj;
  unsigned int *raw = (unsigned int *)&obj.state;
  *raw = (5 << 2) | 1;
  if (obj.state.kind != 5) return 1;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_bitfield_member_assignment_updates_selected_bits(self) -> None:
        source = """
struct State { unsigned int interned:2; unsigned int kind:3; unsigned int compact:1; };
int main(void) {
  struct State state;
  unsigned int *raw = (unsigned int *)&state;
  *raw = 0;
  state.interned = 3;
  state.kind = 5;
  state.compact = 1;
  if (state.interned != 3) return 1;
  if (state.kind != 5) return 2;
  if (state.compact != 1) return 3;
  if ((state.kind = 13) != 5) return 4;
  if (state.kind != 5) return 5;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_bitfield_member_compound_assignment_updates_selected_bits(self) -> None:
        source = """
struct State { unsigned int seen:3; unsigned int pending:1; };
int main(void) {
  struct State state;
  unsigned int *raw = (unsigned int *)&state;
  *raw = 0;
  state.seen |= 4;
  state.seen += 1;
  state.pending |= 1;
  if (state.seen != 5) return 1;
  if (state.pending != 1) return 2;
  if ((*raw & 7) != 5) return 3;
  if (((*raw >> 3) & 1) != 1) return 4;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_bitfield_member_update_updates_selected_bits(self) -> None:
        source = """
struct Page { unsigned char in_full:1; unsigned char retire_expire:7; };
int main(void) {
  struct Page page;
  unsigned char *raw = (unsigned char *)&page;
  *raw = (3 << 1) | 1;
  if (page.retire_expire-- != 3) return 1;
  if (page.retire_expire != 2) return 2;
  if (--page.retire_expire != 1) return 3;
  if (page.in_full != 1) return 4;
  if ((*raw & 1) != 1) return 5;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_mixed_bitfield_members_use_semantic_layout(self) -> None:
        source = """
struct Mixed {
  unsigned char first:3;
  unsigned short second:5;
  unsigned int third:8;
};
int main(void) {
  struct Mixed value;
  unsigned char *bytes = (unsigned char *)&value;
  bytes[0] = (17 << 3) | 5;
  bytes[1] = 166;
  if (value.first != 5 || value.second != 17 || value.third != 166) return 1;
  value.second = 3;
  return bytes[0] == ((3 << 3) | 5) && bytes[1] == 166 ? 0 : 2;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_block_static_pointer_array_and_extern_local_storage(self) -> None:
        source = """
int value = 5;
int main(void) {
  extern int value;
  static const char * const names[] = {"NAME", "NUMBER", (void *)0};
  if (value != 5) return 1;
  if (names[0] == (void *)0) return 2;
  if (names[2] != (void *)0) return 3;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_block_static_initializer_relocates_to_sibling_static_local(self) -> None:
        source = """
struct Parser { char **keywords; };
int main(void) {
  static char *keywords[] = {"source", (void *)0};
  static struct Parser parser = { .keywords = keywords };
  if (parser.keywords != keywords) return 1;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_local_pointer_array_initializer_stores_elements_and_zero_tail(self) -> None:
        source = """
int first_matches(int **items, int *a) {
  return items[0] == a;
}
int f(int *a, int *b) {
  int *items[3] = {a, b};
  if (items[0] != a) return 1;
  if (items[1] != b) return 2;
  if (items[2] != (void *)0) return 3;
  if (!first_matches(items, a)) return 4;
  return 0;
}
int main(void) {
  int a = 1;
  int b = 2;
  return f(&a, &b);
}
"""
        self.assertEqual(self._run(source), 0)

    def test_local_array_initializer_preserves_element_address_during_expression(self) -> None:
        source = """
int main(void) {
  int values[4] = {0};
  int *base = values;
  int *items[2] = {base + 1, base + 2};
  if (items[0] != &values[1]) return 1;
  if (items[1] != &values[2]) return 2;
  if (base != values) return 3;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_local_record_array_initializer_stores_nested_elements(self) -> None:
        source = """
struct Pair { int count; unsigned char kind; };
int main(void) {
  int flags = 2;
  struct Pair pairs[4] = {
    {1, 2},
    {!!(flags & 2), 3},
    {-1, 0},
  };
  if (pairs[0].count != 1 || pairs[0].kind != 2) return 1;
  if (pairs[1].count != 1 || pairs[1].kind != 3) return 2;
  if (pairs[2].count != -1 || pairs[2].kind != 0) return 3;
  if (pairs[3].count != 0 || pairs[3].kind != 0) return 4;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_local_incomplete_array_initializer_sets_stack_slot_length(self) -> None:
        source = """
int main(void) {
  int a = 1;
  int b = 2;
  int *items[] = { &a, &b };
  if (*items[0] != 1) return 1;
  if (*items[1] != 2) return 2;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_local_incomplete_char_array_string_initializer_sets_stack_slot_length(self) -> None:
        source = """
int main(void) {
  char padding[] = "\\0\\0\\0\\0";
  if (padding[0] != 0) return 1;
  if (padding[4] != 0) return 2;
  padding[3] = 7;
  if (padding[3] != 7) return 3;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_local_array_sizeof_bound_allocates_stack_slot_length(self) -> None:
        source = """
int main(void) {
  unsigned long marker = 0;
  unsigned char tmp[sizeof(marker)];
  tmp[0] = 3;
  tmp[7] = 4;
  if (tmp[0] != 3) return 1;
  if (tmp[7] != 4) return 2;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_extern_then_global_definition_emits_one_data_symbol(self) -> None:
        source = """
extern const char * const names[];
const char * const names[] = {"NAME"};
int main(void){return 0;}
"""
        asm = self._asm(source)
        self.assertEqual(asm.count("_names:"), 1)

    def test_tentative_definition_followed_by_initializer_emits_one_data_symbol(self) -> None:
        source = """
int value;
int read(void) { return value; }
int value = 7;
int main(void) { return read() == 7 ? 0 : 1; }
"""
        asm = self._asm(source)
        self.assertEqual(asm.count("_value:"), 1)
        self.assertEqual(self._run(source), 0)
