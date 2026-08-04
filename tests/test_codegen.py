import subprocess
import tempfile
import unittest
from pathlib import Path

from tests import _bootstrap  # noqa: F401
from xcc import cc_driver
from xcc.ast import (
    AlignofExpr,
    ArrayDecl,
    AssignExpr,
    BinaryExpr,
    BreakStmt,
    BuiltinOffsetofExpr,
    BuiltinVaArgExpr,
    CallExpr,
    CaseStmt,
    CastExpr,
    CompoundLiteralExpr,
    CompoundStmt,
    ConditionalExpr,
    DeclGroupStmt,
    DeclStmt,
    DefaultStmt,
    DesignatorRange,
    DoWhileStmt,
    ExprStmt,
    FloatLiteral,
    ForStmt,
    FunctionDef,
    GotoStmt,
    Identifier,
    IfStmt,
    InitItem,
    InitList,
    IntLiteral,
    LabelStmt,
    MemberExpr,
    NullStmt,
    Param,
    ReturnStmt,
    SizeofExpr,
    StatementExpr,
    StaticAssertDecl,
    StringLiteral,
    SubscriptExpr,
    SwitchStmt,
    TypedefDecl,
    TypeSpec,
    UnaryExpr,
    UpdateExpr,
    WhileStmt,
)
from xcc.codegen import _LLVMGen, _base_size, _merge_qualifiers, generate_llvm_ir
from xcc.diag import CodegenError
from xcc.frontend import FrontendOptions, compile_path, compile_source
from xcc.llvm_api import (
    ATOMIC_RMW_ADD,
    ATOMIC_RMW_AND,
    ATOMIC_RMW_NAND,
    ATOMIC_RMW_OR,
    ATOMIC_RMW_SUB,
    ATOMIC_RMW_XOR,
    LLVMTypeKind,
    llvm,
)
from xcc.sema.symbols import RecordMemberInfo
from xcc.types import FLOAT, INT, Type


class CodegenTests(unittest.TestCase):
    def _find_test_llc(self) -> str:
        try:
            return cc_driver._find_llc()
        except ValueError as error:
            self.skipTest(str(error))

    def test_base_size_explicit_branches(self) -> None:
        self.assertEqual(_base_size("int"), 4)
        self.assertEqual(_base_size("long"), 8)
        self.assertEqual(_base_size("char"), 1)
        self.assertEqual(_base_size("short"), 2)
        self.assertEqual(_base_size("double"), 8)
        self.assertEqual(_base_size("long double"), 16)
        self.assertEqual(_base_size("__builtin_va_list"), 8)
        self.assertEqual(_base_size("void"), 0)
        self.assertEqual(_base_size("unknown"), 4)

    def test_merge_qualifiers_preserves_first_occurrence_order(self) -> None:
        self.assertEqual(
            _merge_qualifiers(("const", "volatile", "const"), ("volatile", "restrict")),
            ("const", "volatile", "restrict"),
        )

    def test_debug_ir_has_c_source_metadata_lines_and_unwind_tables(self) -> None:
        source = (
            "static int helper(int value) {\n"
            "  int adjusted = value + 1;\n"
            "  return adjusted;\n"
            "}\n"
            "int main(void) {\n"
            "  return helper(41);\n"
            "}\n"
        )
        result = compile_source(source, filename="/tmp/xcc-debug/sample.c")

        debug_ir = generate_llvm_ir(result, debug=True)
        ordinary_ir = generate_llvm_ir(result)

        for metadata in ("!DIFile", "!DICompileUnit", "!DISubprogram", "!DILocation"):
            self.assertIn(metadata, debug_ir)
        self.assertIn("language: DW_LANG_C11", debug_ir)
        self.assertIn('filename: "sample.c", directory: "/tmp/xcc-debug"', debug_ir)
        self.assertRegex(debug_ir, r'DISubprogram\(name: "helper".*line: 1')
        self.assertRegex(debug_ir, r'DISubprogram\(name: "main".*line: 5')
        for line in (2, 3, 6):
            self.assertRegex(debug_ir, rf"DILocation\(line: {line}, column: [1-9]")
        self.assertRegex(debug_ir, r"define internal i32 @helper\(i32 %0\) uwtable !dbg !\d+")
        self.assertNotIn("!DIFile", ordinary_ir)
        self.assertNotIn("!llvm.dbg.cu", ordinary_ir)
        self.assertNotIn(" uwtable", ordinary_ir)
        self.assertEqual(ordinary_ir, generate_llvm_ir(result))

    def test_debug_ir_maps_included_header_and_main_source_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            header = root / "helper.h"
            source = root / "main.c"
            header.write_text(
                "static int helper(void) {\n  return 7;\n}\n",
                encoding="utf-8",
            )
            source.write_text(
                '#include "helper.h"\nint main(void) { return helper(); }\n',
                encoding="utf-8",
            )

            debug_ir = generate_llvm_ir(
                compile_path(
                    source,
                    options=FrontendOptions(include_dirs=(str(root),)),
                ),
                debug=True,
            )

        self.assertIn('filename: "helper.h"', debug_ir)
        self.assertIn('filename: "main.c"', debug_ir)
        self.assertRegex(debug_ir, r'DISubprogram\(name: "helper".*line: 1')
        self.assertRegex(debug_ir, r'DISubprogram\(name: "main".*line: 2')

    def test_decode_string_escape_branches(self) -> None:
        result = compile_source("int main(void) { return 0; }", filename="decode.c")
        gen = _LLVMGen(result)
        decoded = gen._decode_string(r"\n\t\r\0\\\"\'\a\b\f\v")
        self.assertEqual(decoded, "\n\t\r\0\\\"'\a\b\f\v")

    def assertLlcAccepts(self, source: str) -> str:
        llc = self._find_test_llc()
        result = compile_source(
            source,
            filename="codegen_test.c",
            options=FrontendOptions(std="gnu11"),
        )
        ir = generate_llvm_ir(result)
        with tempfile.TemporaryDirectory() as tmp:
            ll_path = Path(tmp) / "input.ll"
            obj_path = Path(tmp) / "input.o"
            ll_path.write_text(ir, encoding="utf-8")
            completed = subprocess.run(
                (llc, "-filetype=obj", str(ll_path), "-o", str(obj_path)),
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return ir

    def assertProgramReturns(self, source: str, expected: int) -> None:
        llc_path = self._find_test_llc()
        result = compile_source(
            source,
            filename="program_test.c",
            options=FrontendOptions(std="gnu11"),
        )
        ir = generate_llvm_ir(result)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ll_path = tmp_path / "input.ll"
            obj_path = tmp_path / "input.o"
            exe_path = tmp_path / "a.out"
            ll_path.write_text(ir, encoding="utf-8")
            llc = subprocess.run(
                (llc_path, "-filetype=obj", str(ll_path), "-o", str(obj_path)),
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(llc.returncode, 0, llc.stderr)
            link = subprocess.run(
                ("clang", str(obj_path), "-o", str(exe_path)),
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(link.returncode, 0, link.stderr)
            run = subprocess.run((str(exe_path),), cwd=tmp, check=False)
        self.assertEqual(run.returncode, expected)

    def test_incomplete_extern_array_subscript_uses_zero_length_global(self) -> None:
        result = compile_source(
            "extern const unsigned char table[];\nint f(int i) { return table[i]; }\n",
            filename="array.c",
            options=FrontendOptions(std="gnu11"),
        )

        ir = generate_llvm_ir(result)

        self.assertIn("@table = external global [0 x i8]", ir)
        self.assertIn("getelementptr [0 x i8], ptr @table", ir)
        self.assertNotIn("4294967295", ir)
        self.assertNotIn("load [0 x i8]", ir)

    def test_gnu_void_return_call_expression_keeps_argument_typemap(self) -> None:
        ir = self.assertLlcAccepts("void sink(int); void f(int x) { return sink(x); }\n")
        self.assertIn("call void @sink(i32", ir)
        self.assertIn("ret void", ir)
        self.assertNotIn("ret i32", ir)
        self.assertNotIn("alloca [0 x i8]", ir)

    def test_c11_func_identifier_emits_function_name_string(self) -> None:
        result = compile_source(
            "const char *name(void) { return __func__; }\n",
            filename="func_name.c",
            options=FrontendOptions(std="c11"),
        )
        ir = generate_llvm_ir(result)
        self.assertIn('c"name\\00"', ir)
        self.assertIn("ret ptr", ir)

    def test_local_enum_function_pointer_and_pointer_updates_execute(self) -> None:
        source = """
int add_two(int value) { return value + 2; }

int main(void)
{
  enum { LOCAL_VALUE = 4 };
  int (*fp)(int) = add_two;
  int (*same)(int) = *fp;
  int values[3] = { 11, 22, 33 };
  int *cursor = values;
  double total = 1.0;

  ++cursor;
  cursor--;
  total += 2;
  total *= 3.0f;
  total /= 3;

  if (same(LOCAL_VALUE) != 6)
    return 1;
  if (*cursor != 11)
    return 2;
  return (int)total == 3 ? 0 : 3;
}
"""

        self.assertProgramReturns(source, 0)

    def test_block_scope_externs_void_return_and_terminator_edges_execute(self) -> None:
        source = """
int external_value = 7;
int table[3] = {3, 4, 5};

void discard(int x) { return (void)x; }

int scalar_braces(void) {
  int value = {{6}};
  return value;
}

int extern_reads(void) {
  extern int external_value;
  extern int table[];
  return external_value + table[1];
}

int forward_goto(int x) {
  if (x) goto done;
  x = 9;
done:
  return x;
}

int endless_for(void) {
  int i = 0;
  for (;;) {
    i = 2;
    break;
  }
  return i;
}

int after_return_alloca(void) {
  return 3;
  int never;
}

int main(void) {
  discard(1);
  if (scalar_braces() != 6) return 1;
  if (extern_reads() != 11) return 2;
  if (forward_goto(8) != 8) return 3;
  if (forward_goto(0) != 9) return 4;
  if (endless_for() != 2) return 5;
  if (after_return_alloca() != 3) return 6;
  return 0;
}
"""

        self.assertProgramReturns(source, 0)

    def test_unprototyped_function_pointer_initializer_executes(self) -> None:
        source = """
int callee();
int (*fp)() = callee;
int callee(void) { return 4; }
int main(void) { return fp() == 4 ? 0 : 1; }
"""

        self.assertProgramReturns(source, 0)

    def test_mixed_float_pointer_comparisons_and_pointer_difference_execute(self) -> None:
        source = """
int main(void)
{
  int values[4] = { 3, 5, 8, 13 };
  int *cursor = values + 1;
  float f = 1.25f;
  double d = 2.5;
  long diff = &values[3] - values;

  if (!(f < d && d > 2 && 2 <= d && f != d))
    return 1;
  if (cursor == 0)
    return 2;
  if (0 == cursor)
    return 3;
  if (diff != 3)
    return 4;
  cursor = cursor - 1;
  return *cursor == 3 ? 0 : 5;
}
"""

        self.assertProgramReturns(source, 0)

    def test_pointer_null_comparisons_avoid_inttoptr(self) -> None:
        source = """
int main(void)
{
  int *cursor = 0;
  return (cursor == 0) + (0 == cursor) + (cursor != 0);
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("icmp ne ptr", ir)
        self.assertNotIn("inttoptr", ir)

    def test_bool_conversion_uses_nonzero_not_low_bit_truncation(self) -> None:
        self.assertProgramReturns(
            "int main(void) { _Bool b = 0x1000000; return b ? 0 : 1; }",
            0,
        )

    def test_default_returns_emit_zero_values_for_non_integer_result_types(self) -> None:
        source = """
struct Pair {
  int left;
  int right;
};

int *default_pointer(void) {}
double default_double(void) {}
struct Pair default_pair(void) {}

int main(void)
{
  struct Pair pair = default_pair();
  if (default_pointer() != 0) return 1;
  if (default_double() != 0.0) return 2;
  return pair.left == 0 && pair.right == 0 ? 0 : 3;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("ret ptr null", ir)
        self.assertIn("ret double 0.000000e+00", ir)
        self.assertIn("ret { i32, i32 } zeroinitializer", ir)
        self.assertProgramReturns(source, 0)

    def test_local_initializer_designators_and_void_return_execute(self) -> None:
        source = """
void just_return(void) { return; }
int takes_bool(_Bool flag) { return flag ? 0 : 9; }

struct Pair {
  int left;
  int right;
};

union U {
  int i;
  char bytes[4];
};

int main(void)
{
  ;
  just_return();
  typedef int local_int;
  _Static_assert(sizeof(local_int) == sizeof(int), "same");
  int scalar = { 7 };
  local_int raw = 0x100;
  char text[3] = "hi";
  int arr[4] = { [2] = 5, [0] = 1, 9 };
  struct Pair pair = { .right = 4, .left = 3 };
  union U u = { .bytes = { 'A', 0, 0, 0 } };

  if (scalar != 7) return 1;
  if (takes_bool(raw) != 0) return 2;
  if (text[0] != 'h' || text[2] != 0) return 3;
  if (arr[0] != 1 || arr[1] != 9 || arr[2] != 5 || arr[3] != 0) return 4;
  if (pair.left != 3 || pair.right != 4) return 5;
  return u.bytes[0] == 'A' ? 0 : 6;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("define void @just_return()", ir)
        self.assertIn("call i32 @takes_bool(i1 %", ir)
        self.assertIn('store [3 x i8] c"hi\\00"', ir)
        self.assertIn("store { i32, i32 } zeroinitializer", ir)
        self.assertProgramReturns(source, 0)

    def test_control_flow_comma_and_string_literal_cache_execute(self) -> None:
        source = """
int main(void)
{
  int x = 0;
  int y = 0;
  if (x) {
    y = 1;
  } else {
    y = 2;
  }
  x = (y = y + 1, y + 2);

  const char *a = "cache";
  const char *b = "cache";
  const unsigned short *u = u"w";
  const unsigned int *big = U"z";
  const unsigned int *wide = L"q";

  if (a != b) return 1;
  if (x != 5) return 2;
  if (u[0] != 'w') return 3;
  if (big[0] != 'z') return 4;
  return wide[0] == 'q' ? 0 : 5;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertEqual(ir.count('c"cache\\00"'), 1)
        self.assertIn('c"w\\00\\00\\00"', ir)
        self.assertIn('c"z\\00\\00\\00\\00\\00\\00\\00"', ir)
        self.assertProgramReturns(source, 0)

    def test_sizeof_anonymous_typedef_struct_with_bool_member_in_global_init(
        self,
    ) -> None:
        source = """
typedef struct { int a; bool flag; void *p; } Object;
struct Spec { int basicsize; };
static struct Spec spec = { .basicsize = sizeof(Object) };

int main(void)
{
  return spec.basicsize == 16 ? 0 : 1;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("@spec = internal global { i32 } { i32 16 }", ir)

    def test_static_local_initializer_resolves_prior_static_array(self) -> None:
        source = """
struct Slot { int id; void *ptr; };

int f(void)
{
  static struct Slot subslots[] = {
    {1, 0},
    {0, 0},
  };
  static struct Slot slots[] = {
    {2, subslots},
    {0, 0},
  };
  return slots[0].ptr == subslots ? 0 : 1;
}

int main(void)
{
  return f();
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("ptr @.static.f.subslots.", ir)
        self.assertNotIn("@subslots = external global", ir)

    def test_cpython_configure_const_probe_ir_verifies(self) -> None:
        source = """
int main(void)
{
  typedef int charset[2];
  const charset cs = { 0, 0 };
  char const *const *pcpcc;
  char **ppc;
  struct point {int x, y;};
  static struct point const zero = {0,0};
  const char *g = "string";
  pcpcc = &g + (g ? g-g : 0);
  ++pcpcc;
  ppc = (char**) pcpcc;
  pcpcc = (char const *const *) ppc;
  { char tx; char *t = &tx; char const *s = 0 ? (char *) 0 : (char const *) 0;
    *t++ = 0; if (s) return 0; }
  { int x[] = {25, 17}; const int *foo = &x[0]; ++foo; }
  { typedef const int *iptr; iptr p = 0; ++p; }
  { struct s { int j; const int *ap[3]; } bx; struct s *b = &bx; b->j = 5; }
  { const int foo = 10; if (!foo) return 0; }
  return !cs[0] && !zero.x;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("phi i32", ir)

    def test_cpython_configure_run_probe_returns_zero(self) -> None:
        source = """
#include <stdio.h>
int main(void)
{
  FILE *f = fopen("conftest.out", "w");
  if (!f)
    return 1;
  return ferror(f) || fclose(f) != 0;
}
"""

        self.assertProgramReturns(source, 0)

    def test_flattened_nested_record_initializer_consumes_subobject_items(self) -> None:
        source = """
struct Pair { int first; int second; };
struct Outer { struct Pair pair; int tail; };

int main(void)
{
  struct Outer outer = { 9, 4, 2 };
  return outer.pair.first == 9 && outer.pair.second == 4 && outer.tail == 2 ? 0 : 1;
}
"""

        self.assertProgramReturns(source, 0)

    def test_flattened_array_of_records_initializer_consumes_element_items(self) -> None:
        source = """
struct Pair { int first; int second; };

int main(void)
{
  struct Pair pairs[2] = { 1, 2, 3, 4 };
  return pairs[0].first == 1 && pairs[0].second == 2 &&
         pairs[1].first == 3 && pairs[1].second == 4 ? 0 : 1;
}
"""

        self.assertProgramReturns(source, 0)

    def test_global_flattened_array_of_records_initializer_consumes_element_items(self) -> None:
        source = """
struct Pair { int first; int second; };
struct Pair pairs[2] = { 1, 2, 3, 4 };

int main(void)
{
  return pairs[0].first == 1 && pairs[0].second == 2 &&
         pairs[1].first == 3 && pairs[1].second == 4 ? 0 : 1;
}
"""

        self.assertProgramReturns(source, 0)

    def test_flattened_multidimensional_array_initializer_consumes_row_items(self) -> None:
        source = """
int main(void)
{
  int values[2][3] = { 1, 2, 3, 4, 5, 6 };
  return values[0][0] == 1 && values[0][2] == 3 &&
         values[1][0] == 4 && values[1][2] == 6 ? 0 : 1;
}
"""

        self.assertProgramReturns(source, 0)

    def test_global_flattened_multidimensional_array_initializer_consumes_row_items(
        self,
    ) -> None:
        source = """
int values[2][3] = { 1, 2, 3, 4, 5, 6 };

int main(void)
{
  return values[0][0] == 1 && values[0][2] == 3 &&
         values[1][0] == 4 && values[1][2] == 6 ? 0 : 1;
}
"""

        self.assertProgramReturns(source, 0)

    def test_local_designated_initializer_reaches_nested_array_member(self) -> None:
        source = """
struct Cell { int value; };
struct Outer { int prefix; struct Cell cells[4]; int suffix; };

int main(void)
{
  struct Outer outer = {
    .cells[2].value = 7,
    .prefix = 3,
    .suffix = 11,
  };
  return outer.prefix == 3 && outer.cells[0].value == 0 &&
         outer.cells[2].value == 7 && outer.suffix == 11 ? 0 : 1;
}
"""

        self.assertProgramReturns(source, 0)

    def test_gnu_void_pointer_arithmetic_ir_verifies(self) -> None:
        source = """
void *advance(void *p, unsigned long n) { return p + n; }
void *rewind_ptr(void *p, unsigned long n) { return p - n; }
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("getelementptr i8", ir)

    def test_member_array_pointer_arithmetic_scales_by_element(self) -> None:
        source = """
typedef union { unsigned long bits; } Ref;
struct Frame { Ref localsplus[2]; };

Ref *stacktop(struct Frame *frame, int n)
{
  return frame->localsplus + n;
}

int main(void)
{
  struct Frame frame;
  return stacktop(&frame, 1) == &frame.localsplus[1] ? 0 : 1;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("getelementptr { i64 }, ptr", ir)
        self.assertProgramReturns(source, 0)

    def test_record_member_char_pointer_difference_is_byte_count(self) -> None:
        source = """
struct token { const char *start, *end; };

int main(void)
{
  const char *text = "'platlibdir'";
  struct token t = { text, text + 12 };
  return (t.end - t.start) == 12 ? 0 : 1;
}
"""

        self.assertProgramReturns(source, 0)

    def test_unsigned_char_promotes_with_zero_extension(self) -> None:
        source = """
int id(int x) { return x; }
int from_cast(const char *p) { return (unsigned char)*p; }
int from_pointer_cast(const char *p) { return *(const unsigned char *)p; }

int main(void)
{
  char data[1];
  int local;
  data[0] = (char)0xf3;
  local = *(const unsigned char *)data;
  if (from_cast(data) != 243) return 1;
  if (from_pointer_cast(data) != 243) return 2;
  if (id(*(const unsigned char *)data) != 243) return 3;
  if (local != 243) return 4;
  return 0;
}
"""

        self.assertProgramReturns(source, 0)

    def test_unsigned_char_member_array_index_zero_extends(self) -> None:
        source = """
typedef unsigned short _Py_CODEUNIT;
struct Op { unsigned char code; unsigned char arg; };
union CodeUnit { _Py_CODEUNIT cache; struct Op op; };
unsigned char caches[256];

int main(void)
{
  union CodeUnit inst;
  inst.op.code = 200;
  caches[200] = 7;
  return caches[inst.op.code] == 7 ? 0 : 1;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("zext i8", ir)
        self.assertNotIn(", i8 %", ir)
        self.assertProgramReturns(source, 0)

    def test_static_const_union_array_designated_struct_member_keeps_storage_bytes(self) -> None:
        source = """
typedef unsigned char uint8_t;
typedef unsigned short uint16_t;
typedef struct { uint16_t value_and_backoff; } BackoffCounter;
typedef union {
  uint16_t cache;
  struct { uint8_t code; uint8_t arg; } op;
  BackoffCounter counter;
} CodeUnit;
enum { CACHE = 0, NOP = 25, INTERPRETER_EXIT = 18, RESUME = 128 };
#define RESUME_AT_FUNC_START 0
#define RESUME_OPARG_DEPTH1_MASK 0x8
static const CodeUnit instructions[] = {
  { .op.code = NOP, .op.arg = 0 },
  { .op.code = INTERPRETER_EXIT, .op.arg = 0 },
  { .op.code = NOP, .op.arg = 0 },
  { .op.code = INTERPRETER_EXIT, .op.arg = 0 },
  { .op.code = RESUME, .op.arg = RESUME_OPARG_DEPTH1_MASK | RESUME_AT_FUNC_START },
  { .op.code = CACHE, .op.arg = 0 }
};

int main(void)
{
  if (instructions[0].op.code != NOP) return 1;
  if (instructions[1].op.code != INTERPRETER_EXIT) return 2;
  if (instructions[4].op.code != RESUME) return 3;
  if (instructions[4].op.arg != 8) return 4;
  return 0;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("i16 25", ir)
        self.assertIn("i16 18", ir)
        self.assertIn("i16 2176", ir)
        self.assertProgramReturns(source, 0)

    def test_static_union_initializer_copies_nested_union_bytes_to_array_storage(self) -> None:
        source = """
union Inner {
  unsigned int word;
  unsigned char bytes[4];
};

union Outer {
  union Inner inner;
  unsigned char storage[8];
};

static union Outer outer = { .inner = { .bytes = {4, 3, 2, 1} } };

int main(void)
{
  if (outer.storage[0] != 4) return 1;
  if (outer.storage[1] != 3) return 2;
  if (outer.storage[2] != 2) return 3;
  if (outer.storage[3] != 1) return 4;
  return outer.storage[4] == 0 && outer.storage[7] == 0 ? 0 : 5;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("@outer = internal global { [8 x i8] }", ir)
        self.assertProgramReturns(source, 0)

    def test_union_layout_keeps_tail_padding_from_largest_alignment(self) -> None:
        source = """
union Padded {
  char bytes[9];
  long aligned;
};
union Padded padded = { .bytes = {1, 2, 3} };

int main(void)
{
  if (sizeof(union Padded) != 16) return 1;
  if (padded.bytes[0] != 1) return 2;
  if (padded.bytes[2] != 3) return 3;
  if (padded.bytes[8] != 0) return 4;
  return 0;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("@padded = global { [9 x i8], [7 x i8] }", ir)
        self.assertProgramReturns(source, 0)

    def test_global_array_sizeof_bound_allocates_matching_storage(self) -> None:
        source = """
typedef unsigned char uint8_t;
typedef struct { int a; int b; } SlotDef;
static SlotDef slotdefs[] = {{1, 2}, {3, 4}, {0, 0}};
#define LEN(array) (sizeof(array) / sizeof((array)[0]))
static uint8_t slotdefs_dups[LEN(slotdefs)][11];
static unsigned char guard[8];

int main(void)
{
  unsigned char *p = (unsigned char *)slotdefs_dups;
  unsigned long i;
  for (i = 0; i < sizeof(slotdefs_dups); i++)
    p[i] = 0xff;
  for (i = 0; i < sizeof(guard); i++) {
    if (guard[i])
      return 1;
  }
  return sizeof(slotdefs_dups) == 33 ? 0 : 2;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("@slotdefs_dups = internal global [3 x [11 x i8]]", ir)
        self.assertProgramReturns(source, 0)

    def test_grouped_global_declarations_emit_each_object(self) -> None:
        source = """
static int first = 1, second = 2;
static char text[] = "hi";

int main(void)
{
  if (first != 1) return 1;
  if (second != 2) return 2;
  if (sizeof(text) != 3) return 3;
  return text[0] == 'h' && text[2] == 0 ? 0 : 4;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("@first = internal global i32 1", ir)
        self.assertIn("@second = internal global i32 2", ir)
        self.assertIn('@text = internal global [3 x i8] c"hi\\00"', ir)
        self.assertProgramReturns(source, 0)

    def test_file_scope_incomplete_array_definition_keeps_prior_bound(self) -> None:
        source = """
static int values[4];
static int values[] = {1, 2};

int main(void)
{
  if (sizeof(values) / sizeof(values[0]) != 4) return 1;
  if (values[0] != 1 || values[1] != 2) return 2;
  return values[2] == 0 && values[3] == 0 ? 0 : 3;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("@values = internal global [4 x i32]", ir)
        self.assertProgramReturns(source, 0)

    def test_incomplete_array_designator_global_infers_highest_index_bound(self) -> None:
        source = """
unsigned long values[] = { [8] = 56, [16] = 112 };

int main(void)
{
  if (sizeof(values) / sizeof(values[0]) != 17) return 1;
  if (values[8] != 56) return 2;
  if (values[16] != 112) return 3;
  return 0;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("@values = global [17 x i64]", ir)
        self.assertProgramReturns(source, 0)

    def test_global_pointer_initializers_accept_constant_subscript_addresses(self) -> None:
        source = """
static int table[4] = {10, 20, 30, 40};
static int *p = &table[2];
static int *q = &(&table[0])[1];

int main(void)
{
  return *p == 30 && *q == 20 ? 0 : 1;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("@p = internal global ptr getelementptr ([4 x i32], ptr @table", ir)
        self.assertIn("@q = internal global ptr getelementptr (i32, ptr @table", ir)
        self.assertProgramReturns(source, 0)

    def test_gnu_atomic_builtins_lower_to_ir(self) -> None:
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

        result = compile_source(
            source,
            filename="gnu_atomic.c",
            options=FrontendOptions(std="gnu11"),
        )
        ir = generate_llvm_ir(result)

        self.assertNotIn("@__atomic_", ir)
        self.assertNotIn("declare i32 @__atomic", ir)
        self.assertProgramReturns(source, 0)

    def test_gnu_atomic_add_fetch_family_returns_new_values(self) -> None:
        source = """
int main(void)
{
  unsigned long value = 15;
  if (__atomic_add_fetch(&value, 5, 5) != 20) return 1;
  if (__atomic_sub_fetch(&value, 3, 5) != 17) return 2;
  if (__atomic_and_fetch(&value, 7, 5) != 1) return 3;
  if (__atomic_or_fetch(&value, 8, 5) != 9) return 4;
  if (__atomic_xor_fetch(&value, 3, 5) != 10) return 5;
  if (__atomic_nand_fetch(&value, 3, 5) != (~(10UL & 3UL))) return 6;
  return 0;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("atomicrmw add", ir)
        self.assertIn("atomicrmw sub", ir)
        self.assertIn("atomicrmw nand", ir)
        self.assertProgramReturns(source, 0)

    def test_gnu_atomic_pointer_form_builtins_run(self) -> None:
        source = """
int main(void)
{
  unsigned long value = 3;
  unsigned long in = 11;
  unsigned long out = 0;
  unsigned long expected = 0;
  unsigned long desired = 0;

  __atomic_store(&value, &in, 5);
  if (value != 11) return 1;
  __atomic_load(&value, &out, 5);
  if (out != 11) return 2;

  in = 17;
  __atomic_exchange(&value, &in, &out, 5);
  if (out != 11 || value != 17) return 3;

  expected = 17;
  desired = 19;
  if (!__atomic_compare_exchange(&value, &expected, &desired, 0, 5, 5)) return 4;
  if (value != 19 || expected != 17) return 5;

  expected = 17;
  desired = 21;
  if (__atomic_compare_exchange(&value, &expected, &desired, 0, 5, 5)) return 6;
  if (value != 19 || expected != 19) return 7;

  __sync_lock_release(&value);
  return value == 0 ? 0 : 8;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("cmpxchg", ir)
        self.assertIn("atomicrmw xchg", ir)
        self.assertNotIn("@__atomic_", ir)
        self.assertProgramReturns(source, 0)

    def test_gnu_sync_compare_and_swap_builtins_run(self) -> None:
        source = """
int main(void)
{
  int value = 4;
  unsigned char byte = 3;

  if (__sync_val_compare_and_swap(&value, 4L, 9L) != 4) return 1;
  if (value != 9) return 2;
  if (__sync_val_compare_and_swap(&value, 4, 10) != 9) return 3;
  if (value != 9) return 4;
  if (!__sync_bool_compare_and_swap(&value, 9L, 12L)) return 5;
  if (value != 12) return 6;
  if (__sync_bool_compare_and_swap(&value, 9, 13)) return 7;
  if (value != 12) return 8;
  if (__sync_val_compare_and_swap(&byte, 3, 7) != 3) return 9;
  if (byte != 7) return 10;
  return 0;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("cmpxchg", ir)
        self.assertNotIn("@__sync_", ir)
        self.assertProgramReturns(source, 0)

    def test_gnu_lock_free_memory_and_expect_builtins_run(self) -> None:
        source = """
int main(void)
{
  unsigned char buf[8] = {1, 2, 3, 4, 5, 6, 7, 8};
  unsigned long value = 4;

  __builtin_memset(buf, 0x5a, 4);
  __builtin_bzero(buf + 4, 2);
  __builtin___memcpy_chk(buf + 6, "xy", 2, 8);

  if (!__atomic_is_lock_free(4, &value)) return 1;
  if (!__atomic_always_lock_free(8, &value)) return 2;
  if (!__c11_atomic_is_lock_free(1)) return 3;
  if (__builtin_constant_p(buf[0])) return 4;
  if (!__builtin_expect(buf[0] == 0x5a, 1)) return 5;
  if (buf[1] != 0x5a || buf[3] != 0x5a) return 6;
  if (buf[4] != 0 || buf[5] != 0) return 7;
  if (buf[6] != 'x' || buf[7] != 'y') return 8;
  return 0;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("llvm.memset", ir)
        self.assertIn("llvm.memcpy", ir)
        self.assertNotIn("@__builtin_", ir)
        self.assertProgramReturns(source, 0)

    def test_gnu_integer_bit_and_float_builtins_run(self) -> None:
        source = """
int main(void)
{
  double neg = __builtin_copysign(2.5, -1.0);
  float pos = __builtin_copysignf(-3.0f, 1.0f);

  if (__builtin_ffs(0) != 0) return 1;
  if (__builtin_ffs(8) != 4) return 2;
  if (__builtin_ffsl(16L) != 5) return 3;
  if (__builtin_ffsll(1LL << 40) != 41) return 4;
  if (!(neg < 0.0)) return 5;
  if (!(pos > 0.0f)) return 6;
  if (__builtin_isinf(1)) return 7;
  if (!__builtin_isfinite(1)) return 8;
  return 0;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("llvm.cttz", ir)
        self.assertIn("llvm.copysign", ir)
        self.assertNotIn("@__builtin_", ir)
        self.assertProgramReturns(source, 0)

    def test_c11_atomic_header_probe_ir_verifies(self) -> None:
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

        ir = self.assertLlcAccepts(source)

        self.assertNotIn("@__c11_atomic_", ir)

    def test_c11_atomic_pointer_load_ir_verifies(self) -> None:
        source = """
void use(void *);
_Atomic(void*) slot;
void callit(void)
{
  use(__c11_atomic_load(&slot, 2));
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("load atomic ptr", ir)
        self.assertNotIn("@__c11_atomic_load", ir)

    def test_enum_identifier_lowers_to_constant(self) -> None:
        source = """
enum { VALUE_A = 4, VALUE_B = VALUE_A + 3 };
int main(void)
{
  return VALUE_B == 7 ? 0 : 1;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertNotIn("@VALUE_A", ir)
        self.assertNotIn("@VALUE_B", ir)
        self.assertProgramReturns(source, 0)

    def test_typedef_function_declaration_does_not_emit_global_object(self) -> None:
        source = """
typedef int Processor(int value);
static Processor contentProcessor;

static int contentProcessor(int value)
{
  return value + 1;
}

int main(void)
{
  return contentProcessor(2) == 3 ? 0 : 1;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertNotIn("@contentProcessor = internal global", ir)
        self.assertIn("define internal i32 @contentProcessor", ir)
        self.assertProgramReturns(source, 0)

    def test_label_body_and_goto_emit_real_control_flow(self) -> None:
        source = """
int f(int n)
{
  int empty_cnt = 123;
again:
  empty_cnt = 0;
  if (n > 0) {
    n = n - 1;
    empty_cnt = 1;
    goto again;
  }
  return empty_cnt;
}

int main(void)
{
  return f(2);
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("label.again", ir)
        self.assertProgramReturns(source, 0)

    def test_gnu_statement_expression_variants_ir_verify_and_run(self) -> None:
        source = """
void empty(void) { ({ }); }
void decl_last(void) { ({ int x = 1; }); }
int value_last(int a) { return ({ int b = a + 2; b * 3; }); }

int main(void)
{
  empty();
  decl_last();
  return value_last(2) == 12 ? 0 : 1;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("define void @empty()", ir)
        self.assertIn("define void @decl_last()", ir)
        self.assertIn("define i32 @value_last", ir)
        self.assertProgramReturns(source, 0)

    def test_loops_switch_continue_break_and_goto_paths_run(self) -> None:
        source = """
int choose(int x)
{
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
  }
done:
  return total;
}

int main(void)
{
  if (choose(1) != 134) return 1;
  if (choose(2) != 234) return 2;
  if (choose(3) != 34) return 3;
  return 0;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("while.cond", ir)
        self.assertIn("do.body", ir)
        self.assertIn("for.body", ir)
        self.assertIn("switch.default", ir)
        self.assertIn("label.done", ir)
        self.assertProgramReturns(source, 0)

    def test_local_array_and_record_initializer_lists_store_runtime_values(self) -> None:
        source = """
struct Pair { int left; int right; };

int main(void)
{
  int values[4] = {1, [2] = 3, 4};
  struct Pair pair = {.right = 5, .left = 2};
  struct Pair positional = {7, 8};
  if (values[0] != 1) return 1;
  if (values[1] != 0) return 2;
  if (values[2] != 3) return 3;
  if (values[3] != 4) return 4;
  if (pair.left != 2 || pair.right != 5) return 5;
  if (positional.left != 7 || positional.right != 8) return 6;
  return 0;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("getelementptr [4 x i32]", ir)
        self.assertProgramReturns(source, 0)

    def test_unsigned_widened_comparison_uses_unsigned_predicate(self) -> None:
        source = """
int in_unsigned_int_range(long value)
{
  if (value < 0 || (unsigned long)4294967295U < (unsigned long)value) return 1;
  return 0;
}

int main(void)
{
  return in_unsigned_int_range(0);
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("icmp ult i64 4294967295", ir)
        self.assertNotIn("icmp slt i64 -1", ir)
        self.assertProgramReturns(source, 0)

    def test_unsigned_compound_right_shift_uses_logical_shift(self) -> None:
        source = """
unsigned long shrink(unsigned long value)
{
  value >>= 5;
  return value;
}

int main(void)
{
  return shrink(~0UL) == (~0UL >> 5) ? 0 : 1;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("lshr i64", ir)
        self.assertNotIn("ashr i64", ir)
        self.assertProgramReturns(source, 0)

    def test_little_endian_refcount_member_uses_low_word(self) -> None:
        source = """
typedef unsigned int uint32_t;
typedef unsigned short uint16_t;

struct Obj {
  union {
    long full;
    struct {
#ifdef __BIG_ENDIAN__
      uint16_t flags;
      uint16_t overflow;
      uint32_t refcnt;
#else
      uint32_t refcnt;
      uint16_t overflow;
      uint16_t flags;
#endif
    };
  };
  void *type;
};

void incref(struct Obj *op)
{
  op->refcnt++;
}

int main(void)
{
  struct Obj op;
  op.full = 0;
  incref(&op);
  return op.full == 1 ? 0 : 1;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("getelementptr { i32, i16, i16 }, ptr %mem.ptr, i32 0, i32 0", ir)
        self.assertProgramReturns(source, 0)

    def test_static_flexible_array_initializer_allocates_tail_storage(self) -> None:
        source = """
#define EMPTY (-1)
struct Keys {
  long refcnt;
  unsigned char log2_size;
  unsigned char log2_index_bytes;
  unsigned char kind;
  unsigned int version;
  long usable;
  long nentries;
  char indices[];
};

static struct Keys empty = {
  1, 0, 3, 1, 1, 0, 0,
  { EMPTY, EMPTY, EMPTY, EMPTY, EMPTY, EMPTY, EMPTY, EMPTY }
};

int main(void)
{
  return empty.indices[0] == (char)-1 && empty.indices[7] == (char)-1 ? 0 : 1;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("[8 x i8]", ir)
        self.assertProgramReturns(source, 0)

    def test_global_range_designators_initialize_arrays_and_nested_arrays(self) -> None:
        source = """
static int values[6] = { [0 ... 3] = 8, [4] = 1, [5] = 2 };
static int matrix[2][3] = { [0 ... 1] = { 1, 2, 3 } };

int main(void)
{
  if (values[0] != 8 || values[3] != 8) return 1;
  if (values[4] != 1 || values[5] != 2) return 2;
  if (matrix[0][0] != 1 || matrix[0][2] != 3) return 3;
  if (matrix[1][0] != 1 || matrix[1][2] != 3) return 4;
  return 0;
}
"""
        self.assertProgramReturns(source, 0)

    def test_global_designator_indexes_fold_unary_conditional_and_comma_constants(
        self,
    ) -> None:
        source = """
static int values[8] = {
  [+1] = 11,
  [!0 + 1] = 12,
  [~0 + 4] = 13,
  [(0 ? 1 : 2) + 2] = 14,
  [(1, 5)] = 15,
};

int main(void)
{
  if (values[1] != 11) return 1;
  if (values[2] != 12) return 2;
  if (values[3] != 13) return 3;
  if (values[4] != 14) return 4;
  if (values[5] != 15) return 5;
  return values[0] == 0 && values[7] == 0 ? 0 : 6;
}
"""

        self.assertProgramReturns(source, 0)

    def test_global_nested_designators_initialize_named_and_anonymous_members(
        self,
    ) -> None:
        source = """
struct Pair { int left; int right; };
struct NamedOuter { int prefix; struct Pair pair; int suffix; };
struct AnonymousOuter {
  union {
    int full;
    struct { int ref; };
  };
  int type;
};

static struct NamedOuter named = {
  .pair.right = 4,
  .prefix = 2,
  .pair.left = 3,
  .suffix = 5,
};
static struct AnonymousOuter anonymous = {
  .ref = 7,
  .type = 9,
};

int main(void)
{
  if (named.prefix != 2) return 1;
  if (named.pair.left != 3 || named.pair.right != 4) return 2;
  if (named.suffix != 5) return 3;
  if (anonymous.full != 7 || anonymous.ref != 7) return 4;
  return anonymous.type == 9 ? 0 : 5;
}
"""

        self.assertProgramReturns(source, 0)

    def test_global_initializer_evaluates_sizeof_binary_expression(self) -> None:
        source = """
typedef struct { long refcnt; void *type; } Obj;
typedef struct { Obj ob_base; long size; } VarObj;
typedef struct { VarObj ob_base; long hash; void *items[1]; } Tuple;
struct Type { long refcnt; void *type; char *name; long basicsize; long itemsize; };

struct Type Tuple_Type = {
  1, 0, "tuple", sizeof(Tuple) - sizeof(void *), sizeof(void *)
};

int main(void)
{
  return Tuple_Type.basicsize == 32 && Tuple_Type.itemsize == 8 ? 0 : 1;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("@Tuple_Type = global", ir)
        self.assertIn("i64 32", ir)
        self.assertProgramReturns(source, 0)

    def test_global_initializer_folds_integer_constant_operators(self) -> None:
        source = """
static int values[] = {
  17 / 5,
  17 % 5,
  1 << 5,
  32 >> 2,
  5 | 2,
  6 & 3,
  5 ^ 3,
  0 && 7,
  1 || 0,
  4 == 4,
  4 != 5,
  3 < 4,
  5 > 4,
  4 <= 4,
  4 >= 4
};

int main(void)
{
  int expected[] = {3, 2, 32, 8, 7, 2, 6, 0, 1, 1, 1, 1, 1, 1, 1};
  for (int i = 0; i < 15; i++) {
    if (values[i] != expected[i]) return i + 1;
  }
  return 0;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("@values = internal global [15 x i32]", ir)
        self.assertProgramReturns(source, 0)

    def test_global_initializer_folds_float_and_pointer_constant_casts(self) -> None:
        source = """
int global;
static double neg = -1.25;
static void *nullp = (void *)0;
static int *one = (int *)1;
static unsigned long addr = (unsigned long)&global;

int main(void)
{
  if (!(neg < 0.0)) return 1;
  if (nullp != 0) return 2;
  if (one == 0) return 3;
  if (addr == 0) return 4;
  return 0;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("@neg = internal global double -1.250000e+00", ir)
        self.assertIn("@nullp = internal global ptr null", ir)
        self.assertIn("@one = internal global ptr inttoptr", ir)
        self.assertIn("@addr = internal global i64 ptrtoint", ir)
        self.assertProgramReturns(source, 0)

    def test_static_string_literal_sizeof_includes_null_terminator(self) -> None:
        source = """
struct A {
  long len;
  char data[sizeof("n_fields")];
};

static struct A a = { sizeof("n_fields") - 1, "n_fields" };

int main(void)
{
  if (a.len != 8) return 1;
  if (sizeof(a.data) != 9) return 2;
  if (a.data[8] != 0) return 3;
  return 0;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("@a = internal global { i64, [9 x i8] }", ir)
        self.assertIn("i64 8", ir)
        self.assertProgramReturns(source, 0)

    def test_alignof_returns_alignment_not_size(self) -> None:
        source = """
struct WordAligned { char tag; long value; };

int main(void)
{
  if (sizeof(struct WordAligned) != 16) return 1;
  return _Alignof(struct WordAligned) == 8 ? 0 : 2;
}
"""

        self.assertProgramReturns(source, 0)

    def test_alignof_record_respects_aligned_member(self) -> None:
        source = """
struct ExplicitlyAligned { _Alignas(16) char tag; };

int main(void)
{
  return _Alignof(struct ExplicitlyAligned) == 16 ? 0 : 1;
}
"""

        self.assertProgramReturns(source, 0)

    def test_wide_string_literal_uses_wide_storage(self) -> None:
        source = """
int first(const int *text)
{
  return text[0];
}

int main(void)
{
  if (sizeof(L"ab") != 12) return 1;
  if (first(L"ab") != 'a') return 2;
  return 0;
}
"""

        self.assertProgramReturns(source, 0)

    def test_static_pointer_array_can_reference_compound_literal_arrays(self) -> None:
        source = """
typedef struct {
  const char *str;
  int type;
} KeywordToken;

static KeywordToken *reserved_keywords[] = {
  (KeywordToken[]) {{0, -1}},
  (KeywordToken[]) {{"if", 698}, {"as", 696}, {0, -1}},
};

int main(void)
{
  if (reserved_keywords[0][0].str != 0) return 1;
  if (reserved_keywords[0][0].type != -1) return 2;
  if (reserved_keywords[1][0].str[0] != 'i') return 3;
  if (reserved_keywords[1][0].type != 698) return 4;
  if (reserved_keywords[1][1].str[1] != 's') return 5;
  if (reserved_keywords[1][2].type != -1) return 6;
  return 0;
}
"""

        self.assertProgramReturns(source, 0)

    def test_static_function_designator_references_function(self) -> None:
        source = """
static int helper(int x)
{
  return x + 1;
}

int main(void)
{
  int (*fp)(int) = helper;
  if (fp != helper) return 1;
  return fp(2) == 3 ? 0 : 2;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("define internal i32 @helper", ir)
        self.assertNotIn("@helper.", ir)
        self.assertProgramReturns(source, 0)

    def test_dereferenced_function_pointer_call_uses_pointer_value(self) -> None:
        source = """
typedef long (*Hash)(void *);
struct Type { Hash hash; };

long hashfn(void *p)
{
  return p != 0 ? 42 : 1;
}

long call_hash(struct Type *tp, void *p)
{
  return (*tp->hash)(p);
}

int main(void)
{
  struct Type type = { hashfn };
  return call_hash(&type, &type) == 42 ? 0 : 1;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertNotIn("load ptr, ptr %mem.load", ir)
        self.assertProgramReturns(source, 0)

    def test_inline_definition_does_not_export_strong_symbol(self) -> None:
        source = """
inline int helper(int x)
{
  return x + 1;
}

int main(void)
{
  return helper(2) == 3 ? 0 : 1;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("define internal i32 @helper", ir)
        self.assertNotIn("define i32 @helper", ir)
        self.assertProgramReturns(source, 0)

    def test_gnu_extern_inline_definition_does_not_export_strong_symbol(self) -> None:
        source = """
extern __inline__ __attribute__((__gnu_inline__)) int helper(int x)
{
  return x + 1;
}

int main(void)
{
  return helper(2) == 3 ? 0 : 1;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("define internal i32 @helper", ir)
        self.assertNotIn("define i32 @helper", ir)
        self.assertProgramReturns(source, 0)

    def test_array_parameter_local_slot_uses_decayed_pointer_type(self) -> None:
        source = """
int main(int argc, char *argv[])
{
  return argc == 1 && argv[0] ? 0 : 1;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("%argv.addr = alloca ptr", ir)
        self.assertNotIn("%argv.addr = alloca [0 x ptr]", ir)
        self.assertProgramReturns(source, 0)

    def test_address_of_extern_object_declares_global_not_function(self) -> None:
        source = """
struct T { int x; };
extern struct T object;
int takes(struct T *);
int f(void) { return takes(&object); }
int g(void) { return object.x; }
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("@object = external global { i32 }", ir)
        self.assertNotIn("declare void @object", ir)
        self.assertNotIn("@object.", ir)

    def test_nested_global_designated_initializer_keeps_function_and_member_pointers(
        self,
    ) -> None:
        source = """
struct Alloc {
  void *ctx;
  void *(*malloc)(void *, unsigned long);
};
struct DebugAlloc {
  char api;
  struct Alloc alloc;
};
struct Runtime {
  struct { struct Alloc raw; } standard;
  struct { struct DebugAlloc raw; } debug;
};

void *raw_malloc(void *ctx, unsigned long size)
{
  return ctx ? ctx : (void *)size;
}

struct Runtime runtime = {
  .standard = { .raw = { 0, raw_malloc } },
  .debug = { .raw = { 'r', { &runtime.debug.raw, raw_malloc } } },
};

int main(void)
{
  if (runtime.standard.raw.malloc != raw_malloc) return 1;
  if (runtime.debug.raw.alloc.ctx != &runtime.debug.raw) return 2;
  if (runtime.debug.raw.api != 'r') return 3;
  return 0;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("ptr @raw_malloc", ir)
        self.assertIn("getelementptr", ir)
        runtime_line = "@runtime = global" + ir.split("@runtime = global", 1)[1].splitlines()[0]
        self.assertNotIn("zeroinitializer", runtime_line)
        self.assertProgramReturns(source, 0)

    def test_cpython_gcc_builtins_lower_without_externals(self) -> None:
        source = """
void *sink;
int main(void)
{
  char buf[8];
  unsigned short s = 0x1234;
  unsigned int x = 0x01020304U;
  sink = __builtin_assume_aligned(buf, 8);
  (void)__builtin_alloca(4);
  assert(s);
  if (__builtin_bswap16(s) != 0x3412) return 1;
  if (__builtin_bswap32(x) != 0x04030201U) return 2;
  if (__builtin_popcount(0xf0) != 4) return 3;
  if (__builtin_clzl(1UL) != (int)(sizeof(unsigned long) * 8 - 1)) return 4;
  if (__builtin_ctzll(8ULL) != 3) return 5;
  if (!__builtin_isfinite(1.0)) return 6;
  if (!__builtin_isinf(__builtin_inf())) return 7;
  if (!__builtin_isnan(__builtin_nanf(""))) return 8;
  if (__builtin_fabs(-3.0) != 3.0) return 9;
  if (__builtin_flt_rounds() != 1) return 10;
  (void)__builtin_frame_address(0);
  return 0;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertNotIn("@__builtin_", ir)
        self.assertNotIn("@assert", ir)
        self.assertProgramReturns(source, 0)

    def test_aarch64_stack_pointer_asm_rewrites_to_live_address(self) -> None:
        source = """
unsigned long current_stack_address(void)
{
  unsigned long result = 0;
  __asm__ ("mov %0, sp" : "=r" (result));
  return result;
}

int main(void)
{
  return current_stack_address() == 0 ? 1 : 0;
}
"""

        self.assertProgramReturns(source, 0)

    def test_cpython_cast_helpers_parse_as_casts(self) -> None:
        source = """
int main(void)
{
  int values[2] = {3, 4};
  const void *data = values;
  int kind = _Py_STATIC_CAST(int, 1);
  if (kind != 1) return 1;
  return _Py_STATIC_CAST(const int *, data)[1] == 4 ? 0 : 2;
}
"""

        self.assertProgramReturns(source, 0)

    def test_conditional_integer_constant_case_value(self) -> None:
        source = """
#define PACK(nbytes, is_signed) (((nbytes) << 2) + ((is_signed) ? 1 : 0))

int f(int value)
{
  switch (value) {
    case PACK(8, 0):
      return 0;
    default:
      return 1;
  }
}

int main(void)
{
  return f(32);
}
"""

        self.assertProgramReturns(source, 0)

    def test_switch_case_constant_operators_fold(self) -> None:
        source = """
int choose(int value)
{
  switch (value) {
    case (1 << 4) | 3:
      return 1;
    case 7 & 3:
      return 2;
    case 5 ^ 3:
      return 3;
    case 20 / 5:
      return 4;
    case 17 % 5:
      return 5;
    case 32 >> 2:
      return 6;
    case 0 ? 100 : 9:
      return 7;
    case (int)11:
      return 8;
    case 13 - 1:
      return 9;
    case 4 * 5:
      return 10;
    default:
      return 11;
  }
}

int main(void)
{
  if (choose(19) != 1) return 1;
  if (choose(3) != 2) return 2;
  if (choose(6) != 3) return 3;
  if (choose(4) != 4) return 4;
  if (choose(2) != 5) return 5;
  if (choose(8) != 6) return 6;
  if (choose(9) != 7) return 7;
  if (choose(11) != 8) return 8;
  if (choose(12) != 9) return 9;
  if (choose(20) != 10) return 10;
  if (choose(10) != 11) return 11;
  return 0;
}
"""

        self.assertProgramReturns(source, 0)

    def test_switch_case_logical_and_comparison_operators_fold(self) -> None:
        source = """
int choose(int value)
{
  switch (value) {
    case (5 > 3) + 10:
      return 1;
    case (2 == 2) + 20:
      return 2;
    case (2 != 3) + 30:
      return 3;
    case (2 < 3) + 40:
      return 4;
    case (3 <= 3) + 50:
      return 5;
    case (4 >= 3) + 60:
      return 6;
    case (0 || 7) + 70:
      return 7;
    case (1 && 2) + 80:
      return 8;
    default:
      return 9;
  }
}

int main(void)
{
  if (choose(11) != 1) return 1;
  if (choose(21) != 2) return 2;
  if (choose(31) != 3) return 3;
  if (choose(41) != 4) return 4;
  if (choose(51) != 5) return 5;
  if (choose(61) != 6) return 6;
  if (choose(71) != 7) return 7;
  if (choose(81) != 8) return 8;
  if (choose(10) != 9) return 9;
  return 0;
}
"""

        self.assertProgramReturns(source, 0)

    def test_switch_case_unary_conditional_and_comma_constants_fold(self) -> None:
        source = """
int choose(int value)
{
  enum { LOCAL_CASE = 50 };
  switch (value) {
    case +3:
      return 1;
    case !0 + 10:
      return 2;
    case ~0 + 20:
      return 3;
    case (0 ? 1 : 2) + 30:
      return 4;
    case (1, 4) + 40:
      return 5;
    case -2:
      return 6;
    case LOCAL_CASE:
      return 7;
    default:
      return 8;
  }
}

int main(void)
{
  if (choose(3) != 1) return 1;
  if (choose(11) != 2) return 2;
  if (choose(19) != 3) return 3;
  if (choose(32) != 4) return 4;
  if (choose(44) != 5) return 5;
  if (choose(-2) != 6) return 6;
  if (choose(50) != 7) return 7;
  if (choose(9) != 8) return 8;
  return 0;
}
"""

        self.assertProgramReturns(source, 0)

    def test_non_builtin_name_containing_ffs_is_plain_call(self) -> None:
        source = """
void offsets(void *);
void f(void *p)
{
  offsets(p);
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("call void @offsets", ir)
        self.assertNotIn("llvm.cttz", ir)

    def test_struct_lvalue_sizeof_and_array_decay_runtime(self) -> None:
        source = """
void *memset(void *, int, unsigned long);
void poke(char *p) { p[0] = 7; }
struct S { int a; void *p; };
int main(void)
{
  struct S s;
  char buf[1];
  int i;
  memset(&s, 0, sizeof(s));
  s.a = 3;
  s.p = &s;
  poke(buf);
  for (i = 0; i < 2; i++) {
  }
  if (sizeof(s) != 16) return 1;
  if (s.a != 3) return 2;
  if (s.p != &s) return 3;
  if (buf[0] != 7) return 4;
  return i == 2 ? 0 : 5;
}
"""

        self.assertProgramReturns(source, 0)

    def test_nested_builtin_offsetof_uses_full_member_path(self) -> None:
        source = """
typedef unsigned int digit;
typedef unsigned long uintptr_t;
typedef struct { long refcnt; void *type; } PyObject;

typedef struct {
  uintptr_t lv_tag;
  digit ob_digit[1];
} LongValue;

typedef struct {
  PyObject ob_base;
  LongValue long_value;
} LongObject;

unsigned long object_size(unsigned long ndigits)
{
  return __builtin_offsetof(LongObject, long_value.ob_digit) + ndigits * sizeof(digit);
}

int main(void)
{
  if (__builtin_offsetof(LongObject, long_value) != 16) return 1;
  if (__builtin_offsetof(LongObject, long_value.ob_digit) != 24) return 2;
  return object_size(1) == 28 ? 0 : 3;
}
"""

        self.assertProgramReturns(source, 0)

    def test_typeof_expression_decl_preserves_pointer_width(self) -> None:
        source = """
typedef struct Obj Obj;
struct Obj { int value; };

Obj first = {1};
Obj second = {2};
Obj *seen;

void decref(Obj *obj)
{
  seen = obj;
}

#define SETREF(dst, src)          \\
  do {                            \\
    typeof(dst) *_tmp_dst = &(dst);\\
    typeof(dst) _tmp_old = *_tmp_dst;\\
    *_tmp_dst = (src);            \\
    decref(_tmp_old);             \\
  } while (0)

int main(void)
{
  Obj *slot = &first;
  SETREF(slot, &second);
  if (seen != &first) return 1;
  if (slot != &second) return 2;
  return 0;
}
"""

        self.assertProgramReturns(source, 0)

    def test_local_char_array_string_initializer_stores_array_value(self) -> None:
        source = """
int main(void)
{
  char exact[3] = "abc";
  char padded[5] = "x";
  char inferred[] = "yz";
  if (exact[0] != 'a' || exact[2] != 'c') return 1;
  if (padded[0] != 'x' || padded[1] != 0 || padded[4] != 0) return 2;
  if (sizeof(inferred) != 3 || inferred[2] != 0) return 3;
  return 0;
}
"""

        self.assertProgramReturns(source, 0)

    def test_char_array_string_initializer_decodes_extended_escapes(self) -> None:
        source = r"""
int main(void)
{
  unsigned char bytes[11] = "\a\b\f\v\x41\u00A9\U000000A9\?";
  if (sizeof(bytes) != 11) return 1;
  if (bytes[0] != 7) return 2;
  if (bytes[1] != 8) return 3;
  if (bytes[2] != 12) return 4;
  if (bytes[3] != 11) return 5;
  if (bytes[4] != 'A') return 6;
  if (bytes[5] != 0xC2 || bytes[6] != 0xA9) return 7;
  if (bytes[7] != 0xC2 || bytes[8] != 0xA9) return 8;
  if (bytes[9] != '?') return 9;
  if (bytes[10] != 0) return 10;
  return 0;
}
"""

        self.assertProgramReturns(source, 0)

    def test_nested_char_array_string_initializer_stores_array_values(self) -> None:
        source = """
int main(void)
{
  static const char names[2][4] = {"Sun", "Mon"};
  if (names[0][0] != 'S' || names[0][3] != 0) return 1;
  if (names[1][0] != 'M' || names[1][2] != 'n') return 2;
  return 0;
}
"""

        self.assertProgramReturns(source, 0)

    def test_record_char_array_member_string_initializer_stores_array_value(self) -> None:
        source = """
struct Holder {
  char text[4];
  int tag;
};

int main(void)
{
  struct Holder holder = { .text = "ab", .tag = 3 };
  if (holder.text[0] != 'a') return 1;
  if (holder.text[1] != 'b') return 2;
  if (holder.text[2] != 0 || holder.text[3] != 0) return 3;
  return holder.tag == 3 ? 0 : 4;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn('store [4 x i8] c"ab\\00\\00"', ir)
        self.assertProgramReturns(source, 0)

    def test_local_wide_string_array_initializers_store_element_values(self) -> None:
        source = r"""
unsigned short global_u16[] = u"Hi";
unsigned int global_u32[3] = U"Q";
int global_wide[4] = L"R";

int main(void)
{
  unsigned short u16[] = u"A";
  unsigned int u32[] = U"B";
  int wide[] = L"C";
  if ('AB' != 0x4142) return 1;
  if (sizeof(u16) != 4 || u16[0] != 'A' || u16[1] != 0) return 2;
  if (sizeof(u32) != 8 || u32[0] != 'B' || u32[1] != 0) return 3;
  if (sizeof(wide) != 8 || wide[0] != 'C' || wide[1] != 0) return 4;
  if (sizeof(global_u16) != 6 || global_u16[0] != 'H' ||
      global_u16[1] != 'i' || global_u16[2] != 0) return 5;
  if (sizeof(global_u32) != 12 || global_u32[0] != 'Q' ||
      global_u32[1] != 0 || global_u32[2] != 0) return 6;
  if (sizeof(global_wide) != 16 || global_wide[0] != 'R' ||
      global_wide[1] != 0 || global_wide[3] != 0) return 7;
  return 0;
}
"""

        self.assertProgramReturns(source, 0)

    def test_struct_pointer_arithmetic_scales_by_pointee_size(self) -> None:
        source = """
struct Item { int tag; int value; };

int main(void)
{
  struct Item items[4];
  struct Item *first = items;
  struct Item *third = first + 3;
  if (third - first != 3) return 1;
  if ((char *)third - (char *)first != 3 * (long)sizeof(struct Item)) return 2;
  third -= 1;
  if (third - first != 2) return 3;
  ++first;
  return third - first == 1 ? 0 : 4;
}
"""

        self.assertProgramReturns(source, 0)

    def test_anonymous_union_global_initializer_overlays_storage(self) -> None:
        source = """
struct Type { long pad[17]; long (*hash)(void *); };
long hashfn(void *p) { return p != 0 ? 42 : 1; }
struct Type PyUnicode_Type = { .hash = hashfn };

struct Obj {
  union {
    long refcnt_full;
    struct {
      unsigned refcnt;
      unsigned short overflow;
      unsigned short flags;
    };
  };
  struct Type *type;
};

struct Obj obj = { .refcnt = 5, .flags = 1, .type = &PyUnicode_Type };

long object_hash(struct Obj *v)
{
  return v->type->hash(v);
}

int main(void)
{
  if (obj.refcnt != 5 || obj.flags != 1) return 1;
  if (obj.type != &PyUnicode_Type) return 2;
  return object_hash(&obj) == 42 ? 0 : 3;
}
"""

        self.assertProgramReturns(source, 0)

    def test_compound_literal_initializes_positional_anonymous_union(self) -> None:
        source = """
typedef enum { TAG_PTR, TAG_LONG } Tag;
typedef struct {
  Tag tag;
  union {
    int *case_ptr;
    long case_long;
  };
} State;

int main(void)
{
  int value = 7;
  State state = (State){ .tag = TAG_PTR, { .case_ptr = &value } };
  if (state.tag != TAG_PTR) return 1;
  return state.case_ptr == &value ? 0 : 2;
}
"""

        self.assertProgramReturns(source, 0)

    def test_cpython_local_aggregate_initializer_preserves_member_values(self) -> None:
        source = """
struct L { long length; char **items; };
struct A {
  long argc;
  int use_bytes_argv;
  char * const *bytes_argv;
  void *wchar_argv;
};

int check(struct A *args, struct L *cfg)
{
  if (args->argc != cfg->length) return 0;
  if (args->use_bytes_argv != 0) return 0;
  if (args->bytes_argv != 0) return 0;
  return args->wchar_argv == cfg->items;
}

int f(struct L *cfg)
{
  struct A args = {
    .use_bytes_argv = 0,
    .argc = cfg->length,
    .wchar_argv = cfg->items,
  };
  return check(&args, cfg) ? 0 : 1;
}

int main(void)
{
  char *items[3];
  struct L cfg = { 3, items };
  return f(&cfg);
}
"""

        self.assertProgramReturns(source, 0)

    def test_same_aggregate_field_initializer_stores_whole_value(self) -> None:
        source = """
typedef struct { long total; long named; } Part;
typedef struct {
  long total;
  Part locals;
  long numfree;
  Part unbound;
} Counts;

void fill(Counts *counts, Part locals, Part unbound, long numfree)
{
  *counts = (Counts){
    .total = locals.total + numfree + unbound.total,
    .locals = locals,
    .numfree = numfree,
    .unbound = unbound,
  };
}

int main(void)
{
  Counts counts;
  Part locals = { 2, 3 };
  Part unbound = { 5, 7 };
  fill(&counts, locals, unbound, 11);
  if (counts.total != 18) return 1;
  if (counts.locals.total != 2 || counts.locals.named != 3) return 2;
  if (counts.numfree != 11) return 3;
  return counts.unbound.total == 5 && counts.unbound.named == 7 ? 0 : 4;
}
"""

        self.assertProgramReturns(source, 0)

    def test_aggregate_initializers_accept_comma_and_conditional_whole_values(self) -> None:
        source = """
struct Pair { long left; long right; };
struct Pair make_pair(long left, long right)
{
  return (struct Pair){ left, right };
}

int main(void)
{
  struct Pair first = {1, 2};
  struct Pair second = {3, 4};
  struct Pair from_comma = (0, first);
  struct Pair from_cond_true = 1 ? first : second;
  struct Pair from_cond_false = 0 ? first : second;
  struct Pair from_call_cond = 1 ? make_pair(5, 6) : make_pair(7, 8);
  if (from_comma.left != 1 || from_comma.right != 2) return 1;
  if (from_cond_true.left != 1 || from_cond_true.right != 2) return 2;
  if (from_cond_false.left != 3 || from_cond_false.right != 4) return 3;
  if (from_call_cond.left != 5 || from_call_cond.right != 6) return 4;
  return 0;
}
"""

        self.assertProgramReturns(source, 0)

    def test_local_unbraced_nested_aggregate_initializers_consume_member_items(self) -> None:
        source = """
struct Pair { int left; int right; };
struct Wrap {
  struct Pair pairs[2];
  int tail;
};

int main(void)
{
  struct Pair pairs[2] = {1, 2, 3, 4};
  struct Wrap wrap = {5, 6, 7, 8, 9};
  if (pairs[0].left != 1 || pairs[0].right != 2) return 1;
  if (pairs[1].left != 3 || pairs[1].right != 4) return 2;
  if (wrap.pairs[0].left != 5 || wrap.pairs[0].right != 6) return 3;
  if (wrap.pairs[1].left != 7 || wrap.pairs[1].right != 8) return 4;
  return wrap.tail == 9 ? 0 : 5;
}
"""

        self.assertProgramReturns(source, 0)

    def test_global_array_member_decay_initializer_uses_member_address(self) -> None:
        source = """
struct Dtoa {
  void *p5s[8];
  void *freelist[8];
  double preallocated[4];
  double *preallocated_next;
};
struct Interp { struct Dtoa dtoa; };
struct Runtime { struct Interp main; };

struct Runtime runtime = {
  .main = {
    .dtoa = {
      .preallocated_next = runtime.main.dtoa.preallocated,
    },
  },
};

int main(void)
{
  return runtime.main.dtoa.preallocated_next == runtime.main.dtoa.preallocated ? 0 : 1;
}
"""

        self.assertProgramReturns(source, 0)

    def test_indirect_call_preserves_pointer_return_type(self) -> None:
        source = """
typedef struct Entry Entry;
typedef Entry *(*Get)(void *h, const void *key);
struct H { Get f; };
Entry *callit(struct H *h, const void *key)
{
  return h->f(h, key);
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("call ptr", ir)
        self.assertNotIn("bitcast {}", ir)

    def test_compound_literal_struct_return_loads_value(self) -> None:
        source = """
typedef unsigned short uint16_t;
typedef struct { uint16_t value_and_backoff; } Counter;
Counter make(uint16_t value)
{
  return (Counter){ .value_and_backoff = value };
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("ret { i16 }", ir)
        self.assertNotIn("bitcast ptr %compound.lit to { i16 }", ir)

    def test_compound_literal_address_of_keeps_storage(self) -> None:
        source = """
int main(void)
{
  int *p = &(int){7};
  return *p == 7 ? 0 : 1;
}
"""

        self.assertProgramReturns(source, 0)

    def test_typedef_anonymous_struct_with_enum_member_copies_as_aggregate(self) -> None:
        source = """
typedef enum { LT_A } LocaleType;
typedef struct {
  unsigned int fill;
  LocaleType kind;
  long width;
} InternalFormatSpec;
int f(const InternalFormatSpec *format)
{
  InternalFormatSpec tmp_format = *format;
  return tmp_format.kind;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("load { i32, i32, i64 }", ir)
        self.assertNotIn("bitcast { i32, i32, i64 }", ir)

    def test_switch_char_cases_use_literal_body(self) -> None:
        source = r"""
int f(char c)
{
  switch (c) {
    case 0: return 0;
    case '{': return 1;
    case '}': return 2;
    case '!': return 3;
    case ':': return 4;
    case '\n': return 5;
    default: return 6;
  }
}

int main(void)
{
  if (f('{') != 1) return 1;
  if (f('}') != 2) return 2;
  if (f('!') != 3) return 3;
  if (f(':') != 4) return 4;
  if (f('\n') != 5) return 5;
  return 0;
}
"""

        self.assertProgramReturns(source, 0)

    def test_switch_case_fallthrough_labels_share_body(self) -> None:
        source = """
int f(int c)
{
  switch (c) {
    case '(':
    case '[':
    case '{':
      if (c == 0) return 2;
      return 1;
    default:
      return 3;
  }
}

int main(void)
{
  if (f('(') != 1) return 1;
  if (f('[') != 1) return 2;
  if (f('{') != 1) return 3;
  if (f('x') != 3) return 4;
  return 0;
}
"""

        self.assertProgramReturns(source, 0)

    def test_builtin_va_arg_reads_variadic_int(self) -> None:
        source = """
int first(int count, ...)
{
  __builtin_va_list ap;
  int value;
  __builtin_va_start(ap, count);
  value = __builtin_va_arg(ap, int);
  __builtin_va_end(ap);
  return value;
}

int main(void)
{
  return first(1, 7) == 7 ? 0 : 1;
}
"""

        self.assertProgramReturns(source, 0)

    def test_builtin_va_copy_reads_copied_variadic_cursor(self) -> None:
        source = """
int pick_copy(int count, ...)
{
  __builtin_va_list ap;
  __builtin_va_list copy;
  int value;
  __builtin_va_start(ap, count);
  __builtin_va_copy(copy, ap);
  value = __builtin_va_arg(copy, int);
  __builtin_va_end(copy);
  __builtin_va_end(ap);
  return value;
}

int main(void)
{
  return pick_copy(1, 23) == 23 ? 0 : 1;
}
"""

        self.assertProgramReturns(source, 0)

    def test_scalar_aggregate_initializers_store_first_member(self) -> None:
        source = """
struct Box { int x; int y; } global_box = 7;
union Value { int x; long y; } global_value = 5;

int main(void)
{
  struct Box local_box = 11;
  union Value local_value = 13;

  if (global_box.x != 7) return 1;
  if (global_box.y != 0) return 2;
  if (global_value.x != 5) return 3;
  if (local_box.x != 11) return 4;
  if (local_box.y != 0) return 5;
  if (local_value.x != 13) return 6;
  return 0;
}
"""

        self.assertProgramReturns(source, 0)

    def test_c_octal_integer_literals_parse(self) -> None:
        source = """
int main(void)
{
  return 0377 == 255 ? 0 : 1;
}
"""

        self.assertProgramReturns(source, 0)

    def test_array_member_expression_decays_to_storage(self) -> None:
        source = """
struct B { char data[1]; };
int main(void)
{
  struct B b;
  b.data[0] = 5;
  return *b.data == 5 ? 0 : 1;
}
"""

        self.assertProgramReturns(source, 0)

    def test_member_access_of_aggregate_call_results_executes(self) -> None:
        source = """
struct Pair { int a; int b; };
struct Big { long a; long b; long c; };

struct Pair make_pair(void) { return (struct Pair){3, 4}; }
struct Big make_big(void) { return (struct Big){5, 6, 7}; }

int main(void)
{
  if (make_pair().b != 4) return 1;
  if (make_big().c != 7) return 2;
  return 0;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("store { i32, i32 } %call, ptr %mem.tmp", ir)
        self.assertIn("store { i64, i64, i64 } %call", ir)
        self.assertProgramReturns(source, 0)

    def test_function_typed_extern_uses_call_return_type(self) -> None:
        source = """
typedef struct { double real; double imag; } Complex;
typedef Complex ComplexGetter(void);
extern ComplexGetter get_complex;

Complex wrap(void)
{
  return get_complex();
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("declare { double, double } @get_complex()", ir)
        self.assertNotIn("call i32 @get_complex", ir)

    def test_float_comparison_promotes_mixed_float_widths(self) -> None:
        source = """
int f(double d)
{
  return d >= 0x1.0p-126f;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("fcmp oge double", ir)
        self.assertNotIn("fcmp oge double %d, float", ir)

    def test_anonymous_struct_return_prototype_declares_record_type(self) -> None:
        source = """
typedef struct { double real; double imag; } Complex;
Complex get_complex(void);

Complex wrap(void)
{
  return get_complex();
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("declare { double, double } @get_complex()", ir)
        self.assertNotIn("declare i32 @get_complex", ir)

    def test_implicit_aggregate_function_return_uses_zero_value(self) -> None:
        source = """
typedef struct { double real; double imag; } Complex;
Complex zero(void)
{
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("ret { double, double } zeroinitializer", ir)

    def test_float_compound_assignment_promotes_integer_rhs(self) -> None:
        source = """
int main(void)
{
  double d = 5.0;
  d -= 2;
  return d == 3.0 ? 0 : 1;
}
"""

        self.assertProgramReturns(source, 0)

    def test_mixed_float_arithmetic_and_compound_assignments_execute(self) -> None:
        source = """
int main(void)
{
  double left_float = 2.5 + 2;
  double right_float = 2 + 2.5;
  double wide_right = 1.5f + 2.25;
  double wide_left = 2.25 + 1.5f;
  float narrowed = 1.0f;

  narrowed += 2.0;
  narrowed -= 1;
  narrowed *= 3;
  narrowed /= 2.0;

  if (left_float != 4.5) return 1;
  if (right_float != 4.5) return 2;
  if (wide_right != 3.75) return 3;
  if (wide_left != 3.75) return 4;
  return narrowed == 3.0f ? 0 : 5;
}
"""

        self.assertProgramReturns(source, 0)

    def test_shadowed_local_declarations_keep_block_types(self) -> None:
        source = """
typedef union { unsigned long bits; } Ref;
Ref make_ref(void);

Ref f(int flag)
{
  if (flag) {
    Ref result = make_ref();
    return result;
  }
  void *result = 0;
  (void)result;
  return make_ref();
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("call { i64 } @make_ref()", ir)
        self.assertNotIn("bitcast { i64 }", ir)

    def test_nested_anonymous_union_member_access_overlays_storage(self) -> None:
        source = """
struct Object {
  union {
    int full;
    struct {
      int ref;
    };
  };
  int type;
};

int main(void)
{
  struct Object obj;
  obj.full = 0;
  obj.ref = 7;
  return obj.full == 7 ? 0 : 1;
}
"""

        self.assertProgramReturns(source, 0)

    def test_typedef_aggregate_local_init_keeps_struct_type(self) -> None:
        source = """
typedef int (*Basic)(void);
typedef int (*Fallback)(int);
typedef struct {
  Basic basic;
  Fallback fallback;
} GetData;

struct Item {
  GetData getdata;
};

int basic(void)
{
  return 1;
}

int fallback(int value)
{
  return value;
}

GetData lookup(struct Item *matched)
{
  GetData getdata = matched != 0
    ? matched->getdata
    : (GetData){0};
  return getdata;
}

int main(void)
{
  struct Item item;
  item.getdata.basic = basic;
  item.getdata.fallback = fallback;
  GetData data = lookup(&item);
  return data.basic == basic && data.fallback == fallback ? 0 : 1;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertNotIn("bitcast { ptr, ptr }", ir)

    def test_for_scope_locals_in_switch_cases_dominate_uses(self) -> None:
        source = """
int f(int flag)
{
  int total = 0;
  switch (flag) {
    case 0:
      for (long i = 0; i < 2; i++) {
        total += (int)i;
      }
      break;
    default:
      for (long i = 0; i < 3; i++) {
        total += (int)i;
      }
      break;
  }
  return total;
}
"""

        self.assertLlcAccepts(source)

    def test_break_in_loop_nested_inside_switch_targets_loop(self) -> None:
        source = """
int choose(int flag)
{
  switch (flag) {
    case 1:
      do {
        if (flag) {
          break;
        }
        return 2;
      } while (0);
      return 3;
    default:
      return 4;
  }
}

int main(void)
{
  return choose(1);
}
"""

        self.assertProgramReturns(source, 3)

    def test_block_scope_static_local_has_static_storage_duration(self) -> None:
        source = """
int *counter_addr(void)
{
  static int value = 7;
  value += 1;
  return &value;
}

int main(void)
{
  int *first = counter_addr();
  int scratch[16];
  scratch[0] = 123;
  if (*first != 8) return 1;
  int *second = counter_addr();
  if (first != second) return 2;
  return *second == 9 ? 0 : 3;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("@.static.counter_addr.value.", ir)
        self.assertNotIn("alloca i32", ir)
        self.assertProgramReturns(source, 0)

    def test_block_scope_static_aggregate_address_survives_after_return(self) -> None:
        source = """
struct Obj { long ref; void *type; long size; void *items[2]; };
struct Parser {
  void *format;
  void *keywords;
  void *fname;
  void *custom;
  unsigned char once;
  int owned;
  int pos;
  int min;
  int max;
  void *kwtuple;
  struct Parser *next;
};
static struct Parser *head;

struct Parser *register_parser(void)
{
  static struct Obj kwtuple = {1, 0, 2, {0, 0}};
  static struct Parser parser = {.kwtuple = &kwtuple};
  parser.next = head;
  head = &parser;
  return &parser;
}

void churn_stack(void)
{
  long values[32];
  for (int i = 0; i < 32; i++) {
    values[i] = i * 3;
  }
}

int main(void)
{
  struct Parser *parser = register_parser();
  if (head != parser) return 1;
  churn_stack();
  if (head != parser) return 2;
  if (parser->kwtuple == 0) return 3;
  if (parser->owned != 0) return 4;
  return 0;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("@.static.register_parser.parser.", ir)
        self.assertIn("@.static.register_parser.kwtuple.", ir)
        self.assertProgramReturns(source, 0)

    def test_typedef_pointer_record_arrow_on_resolved_record_type(self) -> None:
        source = """
typedef struct Expr *expr_ty;
struct Expr { int kind; };
int f(expr_ty lhs)
{
  expr_ty rhs, copy;
  rhs = lhs;
  copy = rhs;
  return rhs->kind;
}
"""

        self.assertLlcAccepts(source)

    def test_codegen_helper_fallback_paths_are_covered_without_llc(self) -> None:
        result = compile_source(
            """
struct Pair { int left; int right; };
union U { int i; long l; };
struct Aligned { _Alignas(16) char tag; };
int f(void) { return 0; }
""",
            filename="helper_edges.c",
            options=FrontendOptions(std="gnu11"),
        )
        gen = _LLVMGen(result)
        c = llvm()

        self.assertEqual(
            c.GetTypeKind(
                gen._type_to_llvm(
                    Type("int", declarator_ops=(("arr", ArrayDecl(None)),)),
                ),
            ),
            LLVMTypeKind.ARRAY,
        )
        self.assertEqual(
            c.GetTypeKind(gen._type_to_llvm(Type("int").function_of(()))),
            LLVMTypeKind.POINTER,
        )
        self.assertNotEqual(gen._type_to_llvm(Type("int", declarator_ops=(("weird", 0),))), 0)
        group_gen = _LLVMGen(
            compile_source(
                "typedef int GroupAliasOne, GroupAliasTwo; int f(void) { return 0; }",
                filename="helper_decl_group_edges.c",
                options=FrontendOptions(std="gnu11"),
            )
        )
        group_gen._emit_globals()
        self.assertNotEqual(gen._base_type("__unknown"), 0)
        self.assertIsNone(gen._common_integer_c_type(None, INT))
        self.assertIsNone(gen._common_integer_c_type(INT, FLOAT))
        self.assertEqual(gen._field_index("struct Pair", "right"), 1)
        with self.assertRaises(CodegenError):
            gen._field_index("struct Missing", "x")
        with self.assertRaises(CodegenError):
            gen._field_index("struct Pair", "missing")
        self.assertIsNone(gen._member_path("struct Missing", "x"))
        self.assertNotEqual(gen._ptr_type(INT), 0)
        self.assertEqual(gen._type_size(Type("int").function_of(())), 4)
        self.assertEqual(gen._type_align(Type("struct Missing")), 1)
        self.assertEqual(gen._type_align(Type("int").function_of(())), 1)
        self.assertEqual(gen._record_size("struct Missing"), 0)
        self.assertEqual(gen._record_size("struct Aligned"), 16)
        self.assertEqual(gen._union_size("union Missing"), 0)

        self.assertFalse(gen._emit_array_init_list_to_addr(0, Type("int"), InitList(())))
        weird_array = Type("int", declarator_ops=(("arr", ArrayDecl(None)),))
        self.assertFalse(gen._emit_array_init_list_to_addr(0, weird_array, InitList(())))
        bad_designator = InitList((InitItem((("member", "x"),), IntLiteral("1")),))
        self.assertFalse(
            gen._emit_array_init_list_to_addr(0, Type("int").array_of(2), bad_designator),
        )
        nonconst_designator = InitList((InitItem((("index", Identifier("n")),), IntLiteral("1")),))
        self.assertFalse(
            gen._emit_array_init_list_to_addr(0, Type("int").array_of(2), nonconst_designator),
        )
        out_of_bounds_designator = InitList((InitItem((("index", IntLiteral("5")),), IntLiteral("1")),))
        self.assertTrue(
            gen._emit_array_init_list_to_addr(0, Type("int").array_of(2), out_of_bounds_designator),
        )
        self.assertFalse(
            gen._emit_record_init_list_to_addr(0, Type("struct Missing"), InitList(()))
        )
        self.assertFalse(
            gen._emit_record_init_list_to_addr(0, Type("struct Pair"), bad_designator),
        )
        unknown_member = InitList((InitItem((("member", "missing"),), IntLiteral("1")),))
        self.assertFalse(
            gen._emit_record_init_list_to_addr(0, Type("struct Pair"), unknown_member),
        )
        self.assertFalse(
            gen._is_whole_aggregate_value_initializer(Type("struct Pair"), IntLiteral("1")),
        )
        self.assertEqual(gen._emit_unbraced_aggregate_items_to_addr(0, Type("int"), (), 0), 0)
        self.assertEqual(
            gen._emit_unbraced_initializer_item_to_addr(
                0,
                INT,
                (InitItem((("member", "x"),), IntLiteral("1")),),
                0,
            ),
            0,
        )
        self.assertIsNone(
            gen._ensure_static_local(
                DeclStmt(TypeSpec("int"), None, IntLiteral("1"), storage_class="static"),
            ),
        )
        gen._locals = [{}]
        static_stmt = DeclStmt(TypeSpec("int"), "cached", IntLiteral("1"), storage_class="static")
        static_global = gen._ensure_static_local(static_stmt)
        gen._locals = [{}]
        self.assertEqual(gen._ensure_static_local(static_stmt), static_global)

        weird_decl = DeclStmt(
            TypeSpec("char", declarator_ops=(("arr", ArrayDecl(None)),)),
            "text",
            StringLiteral('u"x"'),
        )
        self.assertEqual(gen._decl_type(weird_decl).declarator_ops[0][1], -1)
        with self.assertRaises(CodegenError):
            gen._emit_break()
        with self.assertRaises(CodegenError):
            gen._emit_continue()
        with self.assertRaises(CodegenError):
            gen._emit_expr(object())
        self.assertEqual(gen._parse_int_value("0b1010ULL"), 10)
        self.assertNotEqual(gen._int_literal(IntLiteral("7")), 0)
        self.assertEqual(gen._string_literal_bytes(StringLiteral("no_quote")), b"no_quote\x00")
        self.assertIsNone(
            gen._string_array_element_width(
                Type("char", declarator_ops=(("arr", 2), ("ptr", 0))),
            ),
        )
        self.assertIsNone(gen._string_array_element_width(Type("double").array_of(2)))
        self.assertIsNone(
            gen._string_array_initializer_length(StringLiteral('u"x"'), Type("char").array_of(4)),
        )
        self.assertIsNone(gen._pointer_arith_pointee(None))
        self.assertIsNone(gen._pointer_arith_pointee(INT))
        self.assertIsNone(gen._pointer_arith_pointee(Type("int").function_of(()).pointer_to()))

    def test_codegen_helper_control_and_initializer_edges_without_llc(self) -> None:
        result = compile_source(
            """
struct Pair { int left; int right; };
union U { int i; long l; };
int f(void) { return 0; }
""",
            filename="helper_control_edges.c",
            options=FrontendOptions(std="gnu11"),
        )
        gen = _LLVMGen(result)
        c = llvm()
        fn_type = c.FunctionType(c.VoidType(), None, 0, False)
        fn = c.AddFunction(gen._mod, b"probe_edges", fn_type)
        block = c.AppendBasicBlock(fn, b"entry")
        c.PositionBuilderAtEnd(gen._builder, block)

        array_addr = c.BuildAlloca(
            gen._builder,
            gen._type_to_llvm(Type("int").array_of(0)),
            b"arr",
        )
        union_addr = c.BuildAlloca(
            gen._builder,
            gen._type_to_llvm(Type("union U")),
            b"u",
        )
        pair_addr = c.BuildAlloca(
            gen._builder,
            gen._type_to_llvm(Type("struct Pair")),
            b"p",
        )
        weird_array_addr = c.BuildAlloca(
            gen._builder,
            gen._type_to_llvm(Type("int").array_of(1)),
            b"weird.arr",
        )
        scalar_addr = c.BuildAlloca(gen._builder, c.Int32Type(), b"scalar.init.addr")

        class BrokenArray(Type):
            def element_type(self) -> Type | None:
                return None

        self.assertFalse(_LLVMGen(result)._bb_needs_term())
        fallback_result = compile_source(
            "int fallback_global; int fallback_fn(void) { return 0; }",
            filename="globals_fallback.c",
            options=FrontendOptions(std="gnu11"),
        )
        fallback_gen = _LLVMGen(fallback_result)
        fallback_gen._unit.externals.clear()
        fallback_gen._emit_globals()

        ret_fn_type = c.FunctionType(c.Int32Type(), None, 0, False)
        ret_fn = c.AddFunction(gen._mod, b"probe_default_return_type", ret_fn_type)
        c.PositionBuilderAtEnd(gen._builder, c.AppendBasicBlock(ret_fn, b"entry"))
        ret_expr = IntLiteral("1")
        gen._type_map.set(ret_expr, INT)
        gen._func_sym = None
        gen._emit_return(ReturnStmt(ret_expr))

        c.PositionBuilderAtEnd(gen._builder, block)
        gen._emit_stmt(TypedefDecl(TypeSpec("int"), "Alias"))
        gen._emit_stmt(StaticAssertDecl(IntLiteral("1"), StringLiteral('"ok"')))
        gen._locals = [{}]
        static_stmt = DeclStmt(TypeSpec("int"), "cached2", IntLiteral("1"), storage_class="static")
        static_global = gen._ensure_static_local(static_stmt)
        self.assertEqual(gen._ensure_static_local(static_stmt), static_global)

        excess_items = InitList((InitItem((), IntLiteral("1")),))
        self.assertTrue(
            gen._emit_array_init_list_to_addr(array_addr, Type("int").array_of(0), excess_items),
        )
        gen._emit_initializer_to_addr(
            array_addr,
            Type("int").array_of(1),
            (("member", "bad"),),
            IntLiteral("1"),
        )
        gen._emit_initializer_to_addr(
            array_addr,
            Type("int").array_of(1),
            (("index", Identifier("not_const")),),
            IntLiteral("1"),
        )
        gen._emit_initializer_to_addr(
            array_addr,
            BrokenArray("int", declarator_ops=(("arr", 1),)),
            (("index", IntLiteral("0")),),
            IntLiteral("1"),
        )
        gen._emit_initializer_to_addr(
            scalar_addr,
            INT,
            (("member", "ignored"),),
            IntLiteral("1"),
        )
        bad_record_designator = InitList(
            (InitItem((("index", IntLiteral("0")),), IntLiteral("1")),),
        )
        self.assertFalse(
            gen._emit_record_init_list_to_addr(
                pair_addr,
                Type("struct Pair"),
                bad_record_designator,
            ),
        )
        gen._emit_initializer_to_addr(
            pair_addr,
            Type("struct Pair"),
            (("index", IntLiteral("0")),),
            IntLiteral("1"),
        )
        gen._emit_initializer_to_addr(
            pair_addr,
            Type("struct Pair"),
            (("member", "missing"),),
            IntLiteral("1"),
        )
        union_items = InitList((InitItem((), IntLiteral("1")), InitItem((), IntLiteral("2"))))
        self.assertTrue(
            gen._emit_record_init_list_to_addr(union_addr, Type("union U"), union_items)
        )
        pair_items = InitList(
            (
                InitItem((), IntLiteral("1")),
                InitItem((), IntLiteral("2")),
                InitItem((), IntLiteral("3")),
            ),
        )
        self.assertTrue(
            gen._emit_record_init_list_to_addr(pair_addr, Type("struct Pair"), pair_items)
        )
        self.assertTrue(
            gen._is_whole_aggregate_value_initializer(
                Type("char").array_of(2), StringLiteral('"a"')
            ),
        )
        unsupported_whole_value = IntLiteral("1")
        gen._type_map.set(unsupported_whole_value, Type("struct Pair"))
        self.assertFalse(
            gen._is_whole_aggregate_value_initializer(
                Type("struct Pair"),
                unsupported_whole_value,
            ),
        )
        self.assertEqual(
            gen._emit_unbraced_aggregate_items_to_addr(
                weird_array_addr,
                Type("int", declarator_ops=(("arr", ArrayDecl(None)),)),
                (InitItem((), IntLiteral("1")),),
                0,
            ),
            0,
        )
        self.assertEqual(
            gen._emit_unbraced_aggregate_items_to_addr(
                0,
                Type("struct Missing"),
                (InitItem((), IntLiteral("1")),),
                0,
            ),
            0,
        )
        self.assertEqual(
            gen._emit_unbraced_aggregate_items_to_addr(
                0,
                Type("int"),
                (InitItem((), IntLiteral("1")),),
                0,
            ),
            0,
        )
        self.assertEqual(gen._pointer_arith_element_size(None), 1)

        def fresh_block(name: bytes) -> None:
            c.PositionBuilderAtEnd(gen._builder, c.AppendBasicBlock(fn, name))

        gen._emit_stmt(object())
        fresh_block(b"while.break")
        gen._emit_while(WhileStmt(IntLiteral("1"), BreakStmt()))
        same_label = gen._label_block("same")
        c.PositionBuilderAtEnd(gen._builder, same_label)
        gen._emit_label(LabelStmt("same", NullStmt()))
        fresh_block(b"goto.terminated")
        c.BuildRetVoid(gen._builder)
        gen._emit_goto(GotoStmt("after_terminated"))
        fresh_block(b"switch.default.no.term")
        original_bb_needs_term = gen._bb_needs_term
        gen._bb_needs_term = (
            lambda block=None: False if block is not None else original_bb_needs_term(block)
        )
        try:
            gen._emit_switch(SwitchStmt(IntLiteral("1"), CompoundStmt([])))
        finally:
            gen._bb_needs_term = original_bb_needs_term
        fresh_block(b"switch.empty.bodies")
        gen._emit_switch(
            SwitchStmt(
                IntLiteral("1"),
                CompoundStmt([CaseStmt(IntLiteral("1"), None), DefaultStmt(None)]),
            )
        )

    def test_codegen_helper_unary_builtin_and_call_edges_without_llc(self) -> None:
        result = compile_source(
            """
struct Pair { int left; int right; };
int callee(void) { return 1; }
int global_value;
int f(void) { return 0; }
""",
            filename="helper_call_edges.c",
            options=FrontendOptions(std="gnu11"),
        )
        gen = _LLVMGen(result)
        c = llvm()
        fn_type = c.FunctionType(c.VoidType(), None, 0, False)
        fn = c.AddFunction(gen._mod, b"probe_more_edges", fn_type)
        block = c.AppendBasicBlock(fn, b"entry")
        c.PositionBuilderAtEnd(gen._builder, block)
        gen._func = fn
        gen._entry_block = block
        gen._locals = [{}]

        int_addr = c.BuildAlloca(gen._builder, c.Int32Type(), b"i.addr")
        c.BuildStore(gen._builder, c.ConstInt(c.Int32Type(), 7, False), int_addr)
        gen._locals[-1]["i"] = int_addr
        ptr_t = c.PointerType(c.Int8Type(), 0)
        ptr_addr = c.BuildAlloca(gen._builder, ptr_t, b"p.addr")
        c.BuildStore(gen._builder, c.ConstNull(ptr_t), ptr_addr)
        gen._locals[-1]["p"] = ptr_addr
        pair_addr = c.BuildAlloca(gen._builder, gen._type_to_llvm(Type("struct Pair")), b"pair")
        gen._locals[-1]["pair"] = pair_addr

        def typed_identifier(name: str, type_: Type) -> Identifier:
            expr = Identifier(name)
            gen._type_map.set(expr, type_)
            return expr

        def typed_int(value: str = "1", type_: Type = INT) -> IntLiteral:
            expr = IntLiteral(value)
            gen._type_map.set(expr, type_)
            return expr

        def untyped_identifier(name: str) -> Identifier:
            expr = Identifier(name)
            gen._type_map._map.pop(id(expr), None)
            return expr

        def typed_call(name: str, args: list[IntLiteral], type_: Type = INT) -> CallExpr:
            callee = typed_identifier(name, Type("int").function_of(()))
            expr = CallExpr(callee, args)
            gen._type_map.set(expr, type_)
            return expr

        self.assertNotEqual(gen._unary(UnaryExpr("+", typed_identifier("i", INT))), 0)
        self.assertNotEqual(gen._unary(UnaryExpr("-", typed_identifier("p", INT.pointer_to()))), 0)
        self.assertNotEqual(gen._unary(UnaryExpr("~", typed_identifier("p", INT.pointer_to()))), 0)
        with self.assertRaises(CodegenError):
            gen._unary(UnaryExpr("@", typed_identifier("i", INT)))

        self.assertNotEqual(
            gen._addrof(
                UnaryExpr("&", typed_identifier("callee", Type("int").function_of(()))),
            ),
            0,
        )
        c.AddGlobal(gen._mod, c.Int32Type(), b"known_global_for_addr")
        self.assertNotEqual(
            gen._addrof(UnaryExpr("&", untyped_identifier("known_global_for_addr"))),
            0,
        )
        c.AddFunction(
            gen._mod,
            b"known_fn_for_addr",
            c.FunctionType(c.Int32Type(), None, 0, False),
        )
        self.assertNotEqual(
            gen._addrof(UnaryExpr("&", untyped_identifier("known_fn_for_addr"))),
            0,
        )
        self.assertNotEqual(
            gen._addrof(UnaryExpr("&", untyped_identifier("unknown_addr_target"))),
            0,
        )
        self.assertNotEqual(
            gen._addrof(UnaryExpr("&", UnaryExpr("*", typed_identifier("p", INT.pointer_to())))),
            0,
        )
        with self.assertRaises(CodegenError):
            gen._addrof(UnaryExpr("&", typed_int()))

        unsupported_binary = BinaryExpr("???", typed_int("1"), typed_int("2"))
        gen._type_map.set(unsupported_binary, INT)
        with self.assertRaises(CodegenError):
            gen._binary(unsupported_binary)
        pointer_result_binary = BinaryExpr("+", typed_int("1"), typed_int("2"))
        gen._type_map.set(pointer_result_binary, INT.pointer_to())
        self.assertNotEqual(gen._binary(pointer_result_binary), 0)
        self.assertNotEqual(
            gen._compare(
                "==",
                c.ConstInt(c.Int32Type(), 1, False),
                c.ConstInt(c.Int32Type(), 1, False),
                None,
                None,
                False,
                False,
            ),
            0,
        )
        self.assertNotEqual(
            gen._compare(
                "==",
                c.ConstInt(c.Int64Type(), 1, False),
                c.ConstInt(c.Int32Type(), 1, False),
                None,
                None,
                False,
                False,
            ),
            0,
        )

        atomic_fallbacks = (
            "__atomic_load_n",
            "__atomic_store_n",
            "__atomic_load",
            "__atomic_store",
            "__atomic_fetch_add",
            "__atomic_add_fetch",
            "__atomic_exchange_n",
            "__atomic_exchange",
            "__atomic_compare_exchange_n",
            "__atomic_compare_exchange",
            "__sync_val_compare_and_swap",
            "__sync_lock_release",
        )
        for name in atomic_fallbacks:
            self.assertNotEqual(gen._atomic_builtin_call(name, ()), 0)

        self.assertNotEqual(gen._int_type_for_width(1), 0)
        self.assertNotEqual(gen._int_type_for_width(8), 0)
        self.assertNotEqual(gen._int_type_for_width(128), 0)
        self.assertNotEqual(gen._cast_int_to_width(c.ConstNull(ptr_t), 64, signed=False), 0)
        self.assertNotEqual(
            gen._cast_int_to_width(c.ConstReal(c.DoubleType(), 1.0), 64, signed=False), 0
        )
        self.assertNotEqual(
            gen._cast_int_to_width(c.ConstInt(c.Int8Type(), 1, False), 64, signed=True), 0
        )
        self.assertNotEqual(
            gen._cast_int_to_width(c.ConstInt(c.Int64Type(), 1, False), 8, signed=False), 0
        )
        self.assertNotEqual(gen._result_type_ref(CallExpr(Identifier("x"), []), c.Int32Type()), 0)
        self.assertNotEqual(gen._intrinsic_call("no_arg_intrinsic", c.VoidType(), [], []), 0)
        self.assertNotEqual(
            gen._coerce_builtin_result(
                c.ConstInt(c.Int32Type(), 1, False), CallExpr(Identifier("x"), [])
            ),
            0,
        )
        void_call = CallExpr(Identifier("x"), [])
        gen._type_map.set(void_call, Type("void"))
        self.assertNotEqual(
            gen._coerce_builtin_result(c.ConstInt(c.Int32Type(), 1, False), void_call),
            0,
        )
        self.assertIsNone(
            gen._integer_bit_builtin("__builtin_not_real", CallExpr(Identifier("x"), []))
        )
        self.assertIsNone(gen._integer_bit_builtin("__builtin_ctz", CallExpr(Identifier("x"), [])))
        self.assertNotEqual(
            gen._float_intrinsic_type(
                c.ConstInt(c.Int32Type(), 1, False), CallExpr(Identifier("x"), [])
            ),
            0,
        )
        self.assertIsNone(gen._floating_builtin("__builtin_isinf", CallExpr(Identifier("x"), [])))
        self.assertIsNone(
            gen._floating_builtin("__builtin_copysign", CallExpr(Identifier("x"), [typed_int()])),
        )
        self.assertNotEqual(
            gen._gcc_builtin_call("__builtin_assume_aligned", CallExpr(Identifier("x"), [])), 0
        )
        self.assertNotEqual(
            gen._gcc_builtin_call("__builtin_alloca", CallExpr(Identifier("x"), [])), 0
        )
        self.assertNotEqual(gen._call(typed_call("__builtin_unreachable", [], Type("void"))), 0)
        self.assertNotEqual(gen._call(typed_call("__builtin_bzero", [])), 0)
        self.assertNotEqual(gen._call(typed_call("__builtin___memcpy_chk", [])), 0)

        bad_callee = typed_identifier("i", INT)
        bad_call = CallExpr(bad_callee, [])
        gen._type_map.set(bad_call, INT)
        with self.assertRaises(CodegenError):
            gen._indirect_call(bad_call)
        missing_member = MemberExpr(typed_identifier("pair", Type("struct Pair")), "missing", False)
        with self.assertRaises(CodegenError):
            gen._member_ptr(missing_member)
        self.assertNotEqual(gen._lvalue_addr(typed_identifier("typed_global", INT)), 0)
        self.assertIsNone(
            gen._lvalue_addr(typed_identifier("fn_lvalue", Type("int").function_of(())))
        )

    def test_codegen_helper_type_cast_and_atomic_edges_without_llc(self) -> None:
        result = compile_source(
            """
struct Pair { int left; int right; };
struct Empty { };
struct HasEmpty { struct Empty e; };
union U { int i; char *p; };
int global_array[2];
int f(void) { return 0; }
int define_void_param(void) { return 0; }
int define_duplicate(int dup) { return dup; }
""",
            filename="helper_type_cast_edges.c",
            options=FrontendOptions(std="gnu11"),
        )
        gen = _LLVMGen(result)
        c = llvm()
        fn_type = c.FunctionType(c.VoidType(), None, 0, False)
        fn = c.AddFunction(gen._mod, b"probe_type_cast_edges", fn_type)
        block = c.AppendBasicBlock(fn, b"entry")
        c.PositionBuilderAtEnd(gen._builder, block)
        gen._func = fn
        gen._entry_block = block
        gen._locals = [{}]

        def typed_expr(expr, type_: Type):
            gen._type_map.set(expr, type_)
            return expr

        def typed_identifier(name: str, type_: Type) -> Identifier:
            return typed_expr(Identifier(name), type_)

        def typed_int(value: str = "1", type_: Type = INT) -> IntLiteral:
            return typed_expr(IntLiteral(value), type_)

        def typed_float(value: str = "1.0", type_: Type = FLOAT) -> FloatLiteral:
            return typed_expr(FloatLiteral(value), type_)

        def init_list(items: list[InitItem]) -> InitList:
            return InitList(tuple(items))

        self.assertEqual(
            gen._function_param_types(
                FunctionDef(TypeSpec("int"), "void_proto", [Param(TypeSpec("void"), None)], None),
            ),
            [],
        )
        gen._define_func(FunctionDef(TypeSpec("int"), "missing_definition_symbol", [], None))
        probe_fn = gen._func
        probe_block = gen._entry_block
        gen._define_func(
            FunctionDef(
                TypeSpec("int"),
                "define_void_param",
                [Param(TypeSpec("void"), "unused_void")],
                CompoundStmt([]),
            ),
        )
        gen._define_func(
            FunctionDef(
                TypeSpec("int"),
                "define_duplicate",
                [Param(TypeSpec("int"), "dup")],
                CompoundStmt([DeclStmt(TypeSpec("int"), "dup", None)]),
            ),
        )
        gen._func = probe_fn
        gen._entry_block = probe_block
        gen._func_sym = None
        gen._locals = [{}]
        c.PositionBuilderAtEnd(gen._builder, probe_block)
        float_index = c.ConstReal(c.DoubleType(), 1.0)
        self.assertEqual(gen._gep_index_value(float_index, FLOAT, b"idx"), float_index)
        self.assertEqual(gen._pointer_arith_pointee(Type("int").array_of(2)), INT)
        self.assertIsNone(gen._pointer_arith_pointee(Type("void").pointer_to()))

        manual_numbers = DeclStmt(
            TypeSpec("int", declarator_ops=(("arr", ArrayDecl(None)),)),
            "manual_numbers",
            init_list([InitItem((), typed_int("1")), InitItem((), typed_int("2"))]),
        )
        manual_text = DeclStmt(
            TypeSpec("char", declarator_ops=(("arr", ArrayDecl(None)),)),
            "manual_text",
            StringLiteral('"ok"'),
        )
        gen._emit_global_var(manual_numbers)
        gen._emit_global_var(manual_text)
        file_scope = gen._sema.file_scope
        object.__setattr__(gen._sema, "file_scope", None)
        try:
            gen._emit_global_var(DeclStmt(TypeSpec("int"), "manual_no_scope", None))
        finally:
            object.__setattr__(gen._sema, "file_scope", file_scope)
        gen._emit_global_var(
            DeclStmt(
                TypeSpec("char", declarator_ops=(("arr", ArrayDecl(None)),)),
                "manual_bad_text",
                StringLiteral('u"x"'),
            )
        )
        gen._emit_global_var(DeclStmt(TypeSpec("int"), "manual_missing_init", Identifier("missing")))
        self.assertNotEqual(c.GetNamedGlobal(gen._mod, b"manual_numbers"), 0)
        self.assertNotEqual(c.GetNamedGlobal(gen._mod, b"manual_text"), 0)

        scalar_addr = c.BuildAlloca(gen._builder, c.Int32Type(), b"scalar.addr")
        long_addr = c.BuildAlloca(gen._builder, c.Int64Type(), b"long.addr")
        gen._locals[-1]["scalar"] = scalar_addr
        gen._emit_decl_init(DeclStmt(TypeSpec("int"), "missing_local", typed_int("1")))
        gen._emit_decl_init(
            DeclStmt(
                TypeSpec("int"),
                "scalar",
                init_list([InitItem((("member", "bad"),), typed_int("1"))]),
            ),
        )
        self.assertTrue(
            gen._emit_init_list_to_addr(
                long_addr,
                Type("long"),
                init_list([InitItem((), typed_int("7"))]),
            ),
        )
        gen._emit_initializer_to_addr(scalar_addr, Type("struct Missing"), (), typed_int("1"))
        missing_array_type = Type("struct Missing").array_of(1)
        missing_array_addr = c.BuildAlloca(
            gen._builder,
            gen._type_to_llvm(missing_array_type),
            b"missing.array.addr",
        )
        self.assertTrue(
            gen._emit_array_init_list_to_addr(
                missing_array_addr,
                missing_array_type,
                init_list([InitItem((), typed_int("1"))]),
            ),
        )
        designator_array_type = Type("int").array_of(1)
        designator_array_addr = c.BuildAlloca(
            gen._builder,
            gen._type_to_llvm(designator_array_type),
            b"designator.array.addr",
        )
        self.assertEqual(
            gen._emit_unbraced_aggregate_items_to_addr(
                designator_array_addr,
                designator_array_type,
                (InitItem((("index", typed_int("0")),), typed_int("1")),),
                0,
            ),
            0,
        )
        empty_array_type = Type("struct Empty").array_of(1)
        empty_array_addr = c.BuildAlloca(
            gen._builder,
            gen._type_to_llvm(empty_array_type),
            b"empty.array.addr",
        )
        self.assertEqual(
            gen._emit_unbraced_aggregate_items_to_addr(
                empty_array_addr,
                empty_array_type,
                (InitItem((), typed_int("1")),),
                0,
            ),
            0,
        )
        has_empty_type = Type("struct HasEmpty")
        has_empty_addr = c.BuildAlloca(
            gen._builder,
            gen._type_to_llvm(has_empty_type),
            b"has.empty.addr",
        )
        self.assertTrue(
            gen._emit_record_init_list_to_addr(
                has_empty_addr,
                has_empty_type,
                init_list([InitItem((), typed_int("1"))]),
            ),
        )
        pair_unbraced_addr = c.BuildAlloca(
            gen._builder,
            gen._type_to_llvm(Type("struct Pair")),
            b"pair.unbraced.addr",
        )
        self.assertEqual(
            gen._emit_unbraced_aggregate_items_to_addr(
                pair_unbraced_addr,
                Type("struct Pair"),
                (InitItem((("member", "left"),), typed_int("1")),),
                0,
            ),
            0,
        )
        union_unbraced_addr = c.BuildAlloca(
            gen._builder,
            gen._type_to_llvm(Type("union U")),
            b"union.unbraced.addr",
        )
        self.assertEqual(
            gen._emit_unbraced_aggregate_items_to_addr(
                union_unbraced_addr,
                Type("union U"),
                (InitItem((), typed_int("1")),),
                0,
            ),
            1,
        )

        ptr_t = c.PointerType(c.Int8Type(), 0)
        gen._func_param_types["takes_ptr"] = [ptr_t]
        self.assertEqual(
            c.GetTypeKind(
                c.TypeOf(
                    gen._coerce_call_args([c.ConstInt(c.Int64Type(), 0, False)], "takes_ptr")[0]
                ),
            ),
            LLVMTypeKind.POINTER,
        )
        gen._func_param_types["takes_int"] = [c.Int64Type()]
        self.assertEqual(
            c.GetTypeKind(c.TypeOf(gen._coerce_call_args([c.ConstNull(ptr_t)], "takes_int")[0])),
            LLVMTypeKind.INTEGER,
        )
        array_value = c.ConstNull(c.ArrayType(c.Int32Type(), 2))
        self.assertEqual(
            c.GetTypeKind(c.TypeOf(gen._coerce_call_args([array_value], "takes_ptr")[0])),
            LLVMTypeKind.POINTER,
        )
        self.assertEqual(gen._coerce_call_args([], "takes_ptr"), [])

        pair_addr = c.BuildAlloca(gen._builder, gen._type_to_llvm(Type("struct Pair")), b"pair")
        gen._locals[-1]["pair"] = pair_addr
        pair_ptr_type = Type("struct Pair").pointer_to()
        pair_ptr_addr = c.BuildAlloca(
            gen._builder, gen._type_to_llvm(pair_ptr_type), b"pair.ptr.addr"
        )
        c.BuildStore(gen._builder, pair_addr, pair_ptr_addr)
        gen._locals[-1]["pair_ptr"] = pair_ptr_addr
        self.assertNotEqual(
            gen._member_ptr(
                MemberExpr(typed_identifier("pair", Type("struct Pair")), "left", True)
            ),
            0,
        )
        self.assertNotEqual(
            gen._member_ptr(MemberExpr(typed_identifier("pair_ptr", pair_ptr_type), "right", True)),
            0,
        )

        array_addr = c.BuildAlloca(gen._builder, gen._type_to_llvm(Type("int").array_of(2)), b"arr")
        gen._locals[-1]["arr"] = array_addr
        subscript = SubscriptExpr(typed_identifier("arr", Type("int").array_of(2)), typed_int("0"))
        typed_expr(subscript, INT)
        self.assertNotEqual(gen._lvalue_addr(subscript), 0)
        compound_literal = CompoundLiteralExpr(
            TypeSpec("int"),
            init_list([InitItem((), typed_int("3"))]),
        )
        typed_expr(compound_literal, INT)
        self.assertNotEqual(gen._lvalue_addr(compound_literal), 0)

        int_ptr_addr = c.BuildAlloca(gen._builder, gen._type_to_llvm(INT.pointer_to()), b"p.addr")
        c.BuildStore(gen._builder, c.ConstNull(gen._type_to_llvm(INT.pointer_to())), int_ptr_addr)
        gen._locals[-1]["p"] = int_ptr_addr
        self.assertNotEqual(
            gen._lvalue_addr(UnaryExpr("*", typed_identifier("p", INT.pointer_to()))), 0
        )

        void_call = CallExpr(Identifier("__builtin_unreachable"), [])
        cast_void_to_ptr = CastExpr(TypeSpec("int", pointer_depth=1), void_call)
        typed_expr(cast_void_to_ptr, INT.pointer_to())
        self.assertNotEqual(gen._cast(cast_void_to_ptr), 0)
        cast_to_void = CastExpr(TypeSpec("void"), typed_int("9"))
        typed_expr(cast_to_void, Type("void"))
        self.assertNotEqual(gen._cast(cast_to_void), 0)
        cast_ptr_to_int = CastExpr(TypeSpec("long"), typed_identifier("p", INT.pointer_to()))
        typed_expr(cast_ptr_to_int, Type("long"))
        self.assertNotEqual(gen._cast(cast_ptr_to_int), 0)
        cast_int_to_ptr = CastExpr(TypeSpec("int", pointer_depth=1), typed_int("0"))
        typed_expr(cast_int_to_ptr, INT.pointer_to())
        self.assertNotEqual(gen._cast(cast_int_to_ptr), 0)
        cast_int_to_float = CastExpr(TypeSpec("float"), typed_int("5"))
        typed_expr(cast_int_to_float, FLOAT)
        self.assertNotEqual(gen._cast(cast_int_to_float), 0)

        self.assertNotEqual(gen._build_cast(c.ConstInt(c.Int32Type(), 1, False), c.Int1Type()), 0)
        self.assertNotEqual(
            gen._build_cast(c.ConstNull(c.ArrayType(c.Int32Type(), 0)), ptr_t),
            0,
        )
        self.assertNotEqual(gen._build_cast(c.ConstNull(c.ArrayType(c.Int32Type(), 2)), ptr_t), 0)
        self.assertNotEqual(gen._build_cast(c.ConstNull(ptr_t), c.Int64Type()), 0)
        self.assertNotEqual(gen._build_cast(c.ConstInt(c.Int64Type(), 0, False), ptr_t), 0)
        self.assertNotEqual(gen._build_cast(c.ConstReal(c.DoubleType(), 1.5), c.Int32Type()), 0)
        self.assertNotEqual(gen._build_cast(c.ConstInt(c.Int32Type(), 2, False), c.DoubleType()), 0)
        self.assertNotEqual(gen._build_cast(c.ConstReal(c.FloatType(), 1.5), c.DoubleType()), 0)
        pair_value = c.ConstNull(gen._type_to_llvm(Type("struct Pair")))
        self.assertNotEqual(gen._build_cast(pair_value, gen._type_to_llvm(Type("struct Empty"))), 0)
        self.assertNotEqual(gen._build_cast(pair_value, c.Int64Type()), 0)

        self.assertIsNone(gen._floating_builtin("__builtin_fabs", CallExpr(Identifier("x"), [])))
        self.assertNotEqual(
            gen._floating_builtin(
                "__builtin_copysign",
                CallExpr(Identifier("x"), [FloatLiteral("1.0"), typed_int("2")]),
            ),
            0,
        )
        direct_void_call = CallExpr(Identifier("declared_void"), [])
        typed_expr(direct_void_call.callee, Type("void").function_of(()))
        typed_expr(direct_void_call, Type("void"))
        self.assertNotEqual(gen._call(direct_void_call), 0)

        target_fn_t = c.FunctionType(c.VoidType(), None, 0, False)
        target_fn = c.AddFunction(gen._mod, b"target_void", target_fn_t)
        fp_type = Type("void").function_of(()).pointer_to()
        fp_addr = c.BuildAlloca(gen._builder, gen._type_to_llvm(fp_type), b"fp.addr")
        c.BuildStore(gen._builder, target_fn, fp_addr)
        gen._locals[-1]["fp"] = fp_addr
        indirect_void_call = CallExpr(Identifier("fp"), [])
        typed_expr(indirect_void_call, Type("void"))
        self.assertNotEqual(gen._indirect_call(indirect_void_call, fp_type), 0)

        self.assertNotEqual(
            gen._va_intrinsic_call("__builtin_va_copy", (typed_identifier("p", ptr_t),)), 0
        )
        self.assertNotEqual(
            gen._va_intrinsic_call(
                "__builtin_va_copy",
                (typed_identifier("p", ptr_t), typed_identifier("p", ptr_t)),
            ),
            0,
        )
        self.assertNotEqual(
            gen._va_intrinsic_call("__builtin_va_start", (typed_identifier("p", ptr_t),)), 0
        )

        self.assertNotEqual(gen._atomic_pointer(typed_int("0"))[0], 0)
        void_ptr_type = Type("void").pointer_to()
        void_ptr_addr = c.BuildAlloca(gen._builder, gen._type_to_llvm(void_ptr_type), b"vp.addr")
        c.BuildStore(gen._builder, c.ConstNull(gen._type_to_llvm(void_ptr_type)), void_ptr_addr)
        gen._locals[-1]["vp"] = void_ptr_addr
        _ptr, pointee, pointee_lt = gen._atomic_pointer(typed_identifier("vp", void_ptr_type))
        self.assertEqual(pointee, INT)
        self.assertEqual(c.GetTypeKind(pointee_lt), LLVMTypeKind.INTEGER)
        self.assertNotEqual(
            gen._atomic_promote_result(c.ConstInt(c.Int8Type(), 1, False), Type("unsigned char")),
            0,
        )
        self.assertNotEqual(
            gen._atomic_promote_result(c.ConstInt(c.Int8Type(), 1, False), Type("char")),
            0,
        )
        atomic_int_ptr = typed_identifier("atomic_int", INT.pointer_to())
        gen._locals[-1]["atomic_int"] = c.BuildAlloca(
            gen._builder,
            gen._type_to_llvm(INT.pointer_to()),
            b"atomic.int.addr",
        )
        c.BuildStore(
            gen._builder,
            c.ConstNull(gen._type_to_llvm(INT.pointer_to())),
            gen._locals[-1]["atomic_int"],
        )
        atomic_fetch_add = CallExpr(
            Identifier("__atomic_add_fetch"),
            [atomic_int_ptr, typed_int("1"), typed_int("0")],
        )
        typed_expr(atomic_fetch_add, INT)
        self.assertNotEqual(gen._atomic_builtin_call("__atomic_add_fetch", atomic_fetch_add.args), 0)
        old = c.ConstInt(c.Int32Type(), 6, False)
        value = c.ConstInt(c.Int32Type(), 3, False)
        for op in (
            ATOMIC_RMW_ADD,
            ATOMIC_RMW_SUB,
            ATOMIC_RMW_AND,
            ATOMIC_RMW_OR,
            ATOMIC_RMW_XOR,
            ATOMIC_RMW_NAND,
            999,
        ):
            self.assertNotEqual(gen._atomic_rmw_new_value(op, old, value), 0)
        for name in (
            "__atomic_fetch_sub",
            "__atomic_fetch_and",
            "__atomic_fetch_or",
            "__atomic_fetch_xor",
            "__atomic_fetch_nand",
        ):
            self.assertNotEqual(gen._atomic_builtin_call(name, atomic_fetch_add.args), 0)

        self.assertEqual(_LLVMGen._float_rank(LLVMTypeKind.HALF), 1)
        self.assertEqual(_LLVMGen._float_rank(LLVMTypeKind.FLOAT), 2)
        self.assertEqual(_LLVMGen._float_rank(LLVMTypeKind.DOUBLE), 3)
        self.assertEqual(_LLVMGen._float_rank(LLVMTypeKind.X86_FP80), 4)
        self.assertEqual(_LLVMGen._float_rank(LLVMTypeKind.FP128), 5)
        self.assertEqual(_LLVMGen._float_rank(0), 0)

        for op in ("-", "*", "/"):
            expr = BinaryExpr(op, typed_float("4.0"), typed_float("2.0"))
            typed_expr(expr, FLOAT)
            self.assertNotEqual(gen._binary(expr), 0)
        unsigned_int = Type("unsigned int")
        for op in ("/", "%", "&", "|", "^", "<<", ">>"):
            expr = BinaryExpr(op, typed_int("8", unsigned_int), typed_int("2", unsigned_int))
            typed_expr(expr, unsigned_int)
            self.assertNotEqual(gen._binary(expr), 0)
        signed_mod = BinaryExpr("%", typed_int("8"), typed_int("3"))
        typed_expr(signed_mod, INT)
        self.assertNotEqual(gen._binary(signed_mod), 0)
        signed_shift = BinaryExpr(">>", typed_int("8"), typed_int("1"))
        typed_expr(signed_shift, INT)
        self.assertNotEqual(gen._binary(signed_shift), 0)

        for op in ("<", ">", "<=", ">="):
            self.assertNotEqual(
                gen._compare(
                    op,
                    c.ConstReal(c.FloatType(), 1.0),
                    c.ConstReal(c.FloatType(), 2.0),
                    FLOAT,
                    FLOAT,
                    False,
                    False,
                ),
                0,
            )
            self.assertNotEqual(
                gen._compare(
                    op,
                    c.ConstInt(c.Int32Type(), 1, False),
                    c.ConstInt(c.Int32Type(), 2, False),
                    unsigned_int,
                    unsigned_int,
                    False,
                    False,
                ),
                0,
            )
            self.assertNotEqual(
                gen._compare(
                    op,
                    c.ConstInt(c.Int32Type(), 1, True),
                    c.ConstInt(c.Int32Type(), 2, True),
                    INT,
                    INT,
                    False,
                    False,
                ),
                0,
            )
        with self.assertRaises(CodegenError):
            gen._compare(
                "??",
                c.ConstReal(c.FloatType(), 1.0),
                c.ConstReal(c.FloatType(), 2.0),
                FLOAT,
                FLOAT,
                False,
                False,
            )
        with self.assertRaises(CodegenError):
            gen._compare(
                "??",
                c.ConstInt(c.Int32Type(), 1, True),
                c.ConstInt(c.Int32Type(), 2, True),
                INT,
                INT,
                False,
                False,
            )

        def bind_local(name: str, type_: Type, value_ref: int) -> None:
            addr = c.BuildAlloca(gen._builder, gen._type_to_llvm(type_), name.encode())
            c.BuildStore(gen._builder, value_ref, addr)
            gen._locals[-1][name] = addr

        for op in ("-=", "*=", "/="):
            slot = "float_" + op[0]
            bind_local(slot, FLOAT, c.ConstReal(c.FloatType(), 8.0))
            self.assertNotEqual(
                gen._assign(AssignExpr(op, typed_identifier(slot, FLOAT), typed_float("2.0"))),
                0,
            )
        bind_local("float_add", FLOAT, c.ConstReal(c.FloatType(), 8.0))
        self.assertNotEqual(
            gen._assign(AssignExpr("+=", typed_identifier("float_add", FLOAT), typed_float("2.0"))),
            0,
        )
        for index, op in enumerate(("/=", "%=", "&=", "|=", "^=", "<<=", ">>=")):
            slot = f"uint_compound_{index}"
            bind_local(slot, unsigned_int, c.ConstInt(c.Int32Type(), 8, False))
            self.assertNotEqual(
                gen._assign(
                    AssignExpr(op, typed_identifier(slot, unsigned_int), typed_int("2", unsigned_int))
                ),
                0,
            )
        bind_local("signed_mod_assign", INT, c.ConstInt(c.Int32Type(), 8, True))
        self.assertNotEqual(
            gen._assign(AssignExpr("%=", typed_identifier("signed_mod_assign", INT), typed_int("3"))),
            0,
        )
        for index, op in enumerate(("-=", "*=", "/=", ">>=")):
            slot = f"signed_compound_{index}"
            bind_local(slot, INT, c.ConstInt(c.Int32Type(), 8, True))
            self.assertNotEqual(
                gen._assign(AssignExpr(op, typed_identifier(slot, INT), typed_int("2"))),
                0,
            )

    def test_codegen_helper_expression_control_and_call_edges_without_llc(self) -> None:
        result = compile_source(
            """
struct Pair { int left; int right; };
int global_array[2];
int global_value;
int f(void) { int local_array[2]; return local_array[0]; }
""",
            filename="helper_expression_control_edges.c",
            options=FrontendOptions(std="gnu11"),
        )
        gen = _LLVMGen(result)
        c = llvm()
        fn_type = c.FunctionType(c.VoidType(), None, 0, False)
        fn = c.AddFunction(gen._mod, b"probe_expression_control_edges", fn_type)
        block = c.AppendBasicBlock(fn, b"entry")
        c.PositionBuilderAtEnd(gen._builder, block)
        gen._func = fn
        gen._entry_block = block
        gen._func_sym = result.sema.functions["f"]
        gen._locals = [{}]

        def typed_expr(expr, type_: Type):
            gen._type_map.set(expr, type_)
            return expr

        def typed_identifier(name: str, type_: Type) -> Identifier:
            return typed_expr(Identifier(name), type_)

        def typed_int(value: str = "1", type_: Type = INT) -> IntLiteral:
            return typed_expr(IntLiteral(value), type_)

        def init_list(items: list[InitItem]) -> InitList:
            return InitList(tuple(items))

        def fresh_block(name: bytes) -> None:
            c.PositionBuilderAtEnd(gen._builder, c.AppendBasicBlock(fn, name))

        def untyped_identifier(name: str) -> Identifier:
            expr = Identifier(name)
            gen._type_map._map.pop(id(expr), None)
            return expr

        allocas = gen._collect_allocas(
            CompoundStmt(
                [
                    DeclGroupStmt(
                        [
                            DeclStmt(TypeSpec("int"), "grouped", None),
                            DeclStmt(TypeSpec("int"), "grouped", None),
                        ],
                    ),
                    IfStmt(
                        typed_int("1"),
                        DeclStmt(TypeSpec("int"), "then_local", None),
                        DeclStmt(TypeSpec("int"), "else_local", None),
                    ),
                    WhileStmt(typed_int("1"), DeclStmt(TypeSpec("int"), "while_local", None)),
                    DoWhileStmt(DeclStmt(TypeSpec("int"), "do_local", None), typed_int("0")),
                    ForStmt(None, None, None, DeclStmt(TypeSpec("int"), "for_local", None)),
                    SwitchStmt(typed_int("1"), DeclStmt(TypeSpec("int"), "switch_local", None)),
                    LabelStmt("label", DeclStmt(TypeSpec("int"), "label_local", None)),
                    ExprStmt(
                        StatementExpr(
                            CompoundStmt([DeclStmt(TypeSpec("int"), "stmt_expr_local", None)]),
                        ),
                    ),
                ],
            ),
        )
        self.assertEqual(
            {name for name, _type in allocas},
            {
                "grouped",
                "then_local",
                "else_local",
                "while_local",
                "do_local",
                "for_local",
                "switch_local",
                "label_local",
                "stmt_expr_local",
            },
        )
        self.assertEqual(gen._collect_allocas(ForStmt(None, None, None, None)), [])

        declared_callee = typed_identifier(
            "fresh_declared", Type("int").function_of((Type("long"),))
        )
        declared_call = CallExpr(declared_callee, [typed_int("7", Type("short"))])
        typed_expr(declared_call, INT)
        self.assertNotEqual(gen._call(declared_call), 0)
        self.assertEqual(gen._lookup_symbol_type("local_array"), Type("int").array_of(2))
        self.assertEqual(gen._lookup_symbol_type("global_value"), INT)
        no_scope = gen._sema.file_scope
        object.__setattr__(gen._sema, "file_scope", None)
        try:
            self.assertIsNone(gen._lookup_symbol_type("global_value"))
            no_scope_identifier = typed_identifier("no_scope_identifier", INT)
            self.assertNotEqual(gen._identifier(no_scope_identifier), 0)
        finally:
            object.__setattr__(gen._sema, "file_scope", no_scope)
        not_var_local = typed_identifier("not_var_local", INT)
        gen._func_sym.locals["not_var_local"] = object()
        self.assertNotEqual(gen._identifier(not_var_local), 0)
        self.assertNotEqual(
            gen._identifier(typed_identifier("local_array", Type("int").array_of(2))),
            0,
        )

        fp_type = Type("int").function_of((Type("long"),)).pointer_to()
        target_fn = gen._function_designator("target_i64", Type("int").function_of((Type("long"),)))
        fp_addr = c.BuildAlloca(gen._builder, gen._type_to_llvm(fp_type), b"fp_i64.addr")
        c.BuildStore(gen._builder, target_fn, fp_addr)
        gen._locals[-1]["fp_i64"] = fp_addr
        indirect_call = CallExpr(
            typed_identifier("fp_i64", fp_type), [typed_int("3", Type("short"))]
        )
        typed_expr(indirect_call, INT)
        self.assertNotEqual(gen._indirect_call(indirect_call, fp_type), 0)
        indirect_variadic = CallExpr(
            typed_identifier("fp_i64", fp_type),
            [typed_int("3", Type("short")), typed_int("4", Type("short"))],
        )
        typed_expr(indirect_variadic, INT)
        self.assertNotEqual(gen._indirect_call(indirect_variadic, fp_type), 0)

        scalar_addr = c.BuildAlloca(gen._builder, c.Int32Type(), b"scalar.addr")
        c.BuildStore(gen._builder, c.ConstInt(c.Int32Type(), 1, False), scalar_addr)
        gen._locals[-1]["scalar"] = scalar_addr
        with self.assertRaises(CodegenError):
            gen._assign(AssignExpr("???", typed_identifier("scalar", INT), typed_int("1")))
        self.assertNotEqual(gen._assign_addr(typed_identifier("global_value", INT)), 0)
        self.assertNotEqual(gen._assign_addr(untyped_identifier("unknown_assignment_target")), 0)
        compound_literal_target = CompoundLiteralExpr(
            TypeSpec("int"),
            init_list([InitItem((), typed_int("4"))]),
        )
        typed_expr(compound_literal_target, INT)
        self.assertNotEqual(gen._assign_addr(compound_literal_target), 0)
        with self.assertRaises(CodegenError):
            gen._assign_addr(FloatLiteral("1.0"))

        float_addr = c.BuildAlloca(gen._builder, c.FloatType(), b"float.addr")
        c.BuildStore(gen._builder, c.ConstReal(c.FloatType(), 1.0), float_addr)
        gen._locals[-1]["float_slot"] = float_addr
        self.assertNotEqual(
            gen._update(UpdateExpr("++", typed_identifier("float_slot", FLOAT), False)), 0
        )
        int_ptr_type = INT.pointer_to()
        int_ptr_addr = c.BuildAlloca(gen._builder, gen._type_to_llvm(int_ptr_type), b"int.ptr.addr")
        c.BuildStore(gen._builder, c.ConstNull(gen._type_to_llvm(int_ptr_type)), int_ptr_addr)
        gen._locals[-1]["int_ptr"] = int_ptr_addr
        self.assertNotEqual(
            gen._update(UpdateExpr("--", typed_identifier("int_ptr", int_ptr_type), True)), 0
        )
        self.assertNotEqual(
            gen._assign(AssignExpr("+=", typed_identifier("int_ptr", int_ptr_type), typed_int("1"))),
            0,
        )

        int_ternary = ConditionalExpr(typed_int("1"), typed_int("2"), typed_int("3"))
        typed_expr(int_ternary, Type("long"))
        self.assertNotEqual(gen._ternary(int_ternary), 0)
        void_then = CastExpr(TypeSpec("void"), typed_int("1"))
        void_else = CastExpr(TypeSpec("void"), typed_int("2"))
        typed_expr(void_then, Type("void"))
        typed_expr(void_else, Type("void"))
        void_ternary = ConditionalExpr(typed_int("1"), void_then, void_else)
        typed_expr(void_ternary, Type("void"))
        self.assertNotEqual(gen._ternary(void_ternary), 0)
        fresh_block(b"terminating.ternary")
        unreachable_then = CallExpr(
            typed_identifier("__builtin_unreachable", Type("void").function_of(())), []
        )
        unreachable_else = CallExpr(
            typed_identifier("__builtin_unreachable", Type("void").function_of(())), []
        )
        typed_expr(unreachable_then, Type("void"))
        typed_expr(unreachable_else, Type("void"))
        terminating_ternary = ConditionalExpr(typed_int("1"), unreachable_then, unreachable_else)
        typed_expr(terminating_ternary, Type("void"))
        self.assertNotEqual(gen._ternary(terminating_ternary), 0)
        fresh_block(b"unterminated.ternary")
        original_bb_needs_term = gen._bb_needs_term
        gen._bb_needs_term = (
            lambda block=None: False if block is not None else original_bb_needs_term(block)
        )
        try:
            unterminated_ternary = ConditionalExpr(typed_int("1"), typed_int("2"), typed_int("3"))
            typed_expr(unterminated_ternary, INT)
            self.assertNotEqual(gen._ternary(unterminated_ternary), 0)
        finally:
            gen._bb_needs_term = original_bb_needs_term

        self.assertNotEqual(gen._stmt_expr(StatementExpr(CompoundStmt([]))), 0)
        value_stmt_expr = StatementExpr(CompoundStmt([ExprStmt(typed_int("9"))]))
        self.assertNotEqual(gen._stmt_expr(value_stmt_expr), 0)
        decl_stmt_expr = StatementExpr(
            CompoundStmt([DeclStmt(TypeSpec("int"), "stmt_local", typed_int("5"))]),
        )
        self.assertNotEqual(gen._stmt_expr(decl_stmt_expr), 0)

        array_literal = CompoundLiteralExpr(
            TypeSpec("int", array_lengths=(2,)),
            init_list([InitItem((), typed_int("1")), InitItem((), typed_int("2"))]),
        )
        typed_expr(array_literal, Type("int").array_of(2))
        self.assertNotEqual(gen._compound_literal(array_literal), 0)
        scalar_literal = CompoundLiteralExpr(
            TypeSpec("int"),
            init_list([InitItem((), typed_int("6"))]),
        )
        typed_expr(scalar_literal, INT)
        self.assertNotEqual(gen._compound_literal(scalar_literal), 0)

        self.assertNotEqual(gen._size_const(SizeofExpr(typed_identifier("scalar", INT), None)), 0)
        self.assertNotEqual(gen._to_bool(c.ConstNull(c.ArrayType(c.Int32Type(), 2))), 0)
        self.assertNotEqual(gen._to_bool(c.ConstReal(c.DoubleType(), 1.0)), 0)
        self.assertNotEqual(gen._build_cast(c.ConstInt(c.Int32Type(), 1, False), c.Int32Type()), 0)

        typeof_expr = typed_identifier("scalar", INT)
        self.assertEqual(
            gen._resolve_type(TypeSpec("typeof", pointer_depth=1, typeof_expr=typeof_expr)),
            INT.pointer_to(),
        )
        self.assertEqual(
            gen._resolve_type(TypeSpec("typeof", array_lengths=(2,), typeof_expr=typeof_expr)),
            INT.array_of(2),
        )
        self.assertEqual(
            gen._resolve_type(
                TypeSpec(
                    "typeof",
                    declarator_ops=(("fn", ((TypeSpec("int"),), False)),),
                    typeof_expr=typeof_expr,
                ),
            ),
            INT.function_of((INT,)),
        )
        self.assertEqual(
            gen._resolve_type(
                TypeSpec("typeof", declarator_ops=(("weird", 0),), typeof_expr=typeof_expr)
            ),
            INT,
        )
        missing_typeof = Identifier("missing_typeof")
        gen._type_map._map.pop(id(missing_typeof), None)
        with self.assertRaises(CodegenError):
            gen._resolve_type(TypeSpec("typeof", typeof_expr=missing_typeof))
        self.assertEqual(
            gen._resolve_type(
                TypeSpec("int", declarator_ops=(("arr", ArrayDecl(typed_int("3"))),))
            ),
            INT.array_of(3),
        )
        self.assertEqual(
            gen._resolve_type(TypeSpec("int", declarator_ops=(("weird", 0),))),
            Type("int", declarator_ops=(("weird", 0),)),
        )

    def test_codegen_helper_constant_initializer_edges_without_llc(self) -> None:
        result = compile_source(
            """
struct Pair { int left; int right; };
union U { int i; long l; };
union Ptrs { char *p; int *q; };
struct Flex { int n; char data[]; };
struct FloatBox { float f; };
struct Outer { struct Pair nested; int tail; };
struct Wrapper { struct { int inner; }; int tail; };
struct PtrHolder { char *p; };
struct Empty { };
enum { ENUM_VALUE = -3 };
int g[3];
int f(void) { return 0; }
""",
            filename="helper_constant_edges.c",
            options=FrontendOptions(std="gnu11"),
        )
        gen = _LLVMGen(result)
        c = llvm()
        fn_type = c.FunctionType(c.VoidType(), None, 0, False)
        fn = c.AddFunction(gen._mod, b"probe_constant_edges", fn_type)
        block = c.AppendBasicBlock(fn, b"entry")
        c.PositionBuilderAtEnd(gen._builder, block)
        gen._func = fn
        gen._entry_block = block
        gen._locals = [{}]

        def typed_expr(expr: IntLiteral | Identifier | CompoundLiteralExpr, type_: Type):
            gen._type_map.set(expr, type_)
            return expr

        def typed_int(value: str = "1", type_: Type = INT) -> IntLiteral:
            return typed_expr(IntLiteral(value), type_)

        def init_list(items: list[InitItem]) -> InitList:
            return InitList(tuple(items))

        self.assertNotEqual(
            gen._eval_init(init_list([InitItem((), typed_int("7"))]), INT),
            0,
        )
        self.assertNotEqual(gen._eval_init(FloatLiteral("1.5f"), FLOAT), 0)
        self.assertNotEqual(gen._eval_init(FloatLiteral("1.5"), FLOAT), 0)
        self.assertIsNone(gen._eval_init(Identifier("missing"), INT))
        self.assertIsNone(
            gen._eval_init(
                init_list([InitItem((), typed_int("1")), InitItem((), typed_int("2"))]),
                INT,
            ),
        )
        self.assertEqual(
            gen._infer_array_init_length(
                init_list(
                    [
                        InitItem((("index", Identifier("not_const")),), typed_int("1")),
                        InitItem(
                            (("range", DesignatorRange(typed_int("2"), Identifier("hi"))),),
                            typed_int("2"),
                        ),
                        InitItem((("member", "x"),), typed_int("3")),
                    ],
                ),
                Type("int").array_of(-1),
            ),
            1,
        )
        self.assertEqual(
            gen._infer_array_init_length(
                init_list([InitItem((), typed_int("1"))]),
                Type("struct Missing").array_of(-1),
            ),
            1,
        )
        self.assertEqual(
            gen._infer_array_init_length(
                init_list([InitItem((), typed_int("1")), InitItem((), typed_int("2"))]),
                Type("struct Pair").array_of(-1),
            ),
            1,
        )
        self.assertIsNone(
            gen._flexible_array_member_overrides(INT, init_list([InitItem((), typed_int("1"))])),
        )
        self.assertIsNone(
            gen._flexible_array_member_overrides(
                Type("struct Missing"),
                init_list([InitItem((), typed_int("1"))]),
            ),
        )
        self.assertIsNone(
            gen._flexible_array_member_overrides(
                Type("struct Pair"),
                init_list([InitItem((), typed_int("1"))]),
            ),
        )
        self.assertIsNone(
            gen._flexible_array_member_overrides(
                Type("struct Flex"),
                init_list([InitItem((), typed_int("1"))]),
            ),
        )
        self.assertIsNone(
            gen._flexible_array_member_overrides(
                Type("struct Flex"),
                init_list([InitItem((), typed_int("1")), InitItem((), init_list([]))]),
            ),
        )
        flex_overrides = gen._flexible_array_member_overrides(
            Type("struct Flex"),
            init_list([InitItem((), typed_int("1")), InitItem((), StringLiteral('"hi"'))]),
        )
        self.assertEqual(flex_overrides, {1: Type("char").array_of(3)})
        nested_flex_init = gen._record_member_initializer(
            init_list([InitItem((("member", "data"), ("index", typed_int("1"))), typed_int("7"))]),
            "struct Flex",
            1,
        )
        self.assertIsInstance(nested_flex_init, InitList)
        self.assertIsNone(
            gen._record_member_initializer(
                init_list([InitItem((), typed_int("1"))]),
                "struct Missing",
                0,
            ),
        )
        self.assertIsNone(
            gen._record_member_initializer(
                init_list([InitItem((("index", typed_int("0")),), typed_int("1"))]),
                "struct Pair",
                0,
            ),
        )
        self.assertIsNone(
            gen._record_member_initializer(
                init_list([InitItem((("member", "missing"),), typed_int("1"))]),
                "struct Pair",
                0,
            ),
        )
        direct_member_init = typed_int("10")
        self.assertIs(
            gen._record_member_initializer(
                init_list([InitItem((("member", "right"),), direct_member_init)]),
                "struct Pair",
                1,
            ),
            direct_member_init,
        )
        self.assertEqual(
            gen._infer_flexible_array_init_length(typed_int("5"), Type("char").array_of(-1)),
            1,
        )
        self.assertEqual(
            gen._infer_flexible_array_init_length(StringLiteral('u"x"'), Type("char").array_of(-1)),
            1,
        )
        self.assertNotEqual(gen._struct_type_with_member_overrides("struct Missing", {}), 0)
        self.assertIsNone(gen._eval_array_init(InitList(()), INT))
        self.assertIsNone(
            gen._eval_array_init(
                init_list([InitItem((("range", typed_int("1")),), typed_int("1"))]),
                Type("int").array_of(2),
            ),
        )
        self.assertIsNone(
            gen._eval_array_init(
                init_list([InitItem((("index", Identifier("n")),), typed_int("1"))]),
                Type("int").array_of(2),
            ),
        )
        self.assertIsNone(
            gen._eval_array_init(
                init_list([InitItem((("member", "x"),), typed_int("1"))]),
                Type("int").array_of(2),
            ),
        )
        self.assertNotEqual(
            gen._eval_array_init(
                init_list(
                    [
                        InitItem(
                            (("range", DesignatorRange(typed_int("0"), typed_int("1"))),),
                            Identifier("missing"),
                        ),
                    ],
                ),
                Type("int").array_of(2),
            ),
            0,
        )
        self.assertNotEqual(
            gen._eval_array_init(
                init_list(
                    [
                        InitItem(
                            (("range", DesignatorRange(typed_int("3"), typed_int("4"))),),
                            typed_int("1"),
                        ),
                    ],
                ),
                Type("int").array_of(2),
            ),
            0,
        )
        self.assertNotEqual(
            gen._eval_array_init(
                init_list([InitItem((("index", typed_int("5")),), typed_int("1"))]),
                Type("int").array_of(2),
            ),
            0,
        )
        self.assertIsNone(
            gen._eval_array_init(
                init_list(
                    [
                        InitItem(
                            (("range", DesignatorRange(typed_int("0"), Identifier("hi"))),),
                            typed_int("1"),
                        ),
                    ],
                ),
                Type("int").array_of(2),
            ),
        )
        self.assertNotEqual(
            gen._eval_array_init(
                init_list([InitItem((("index", typed_int("0")),), Identifier("missing"))]),
                Type("int").array_of(2),
            ),
            0,
        )
        self.assertNotEqual(
            gen._eval_array_init(
                init_list([InitItem((), typed_int("1"))]),
                Type("struct Missing").array_of(1),
            ),
            0,
        )
        self.assertNotEqual(
            gen._eval_array_init(
                init_list([InitItem((), typed_int("1")), InitItem((), typed_int("2"))]),
                Type("int").array_of(1),
            ),
            0,
        )
        self.assertNotEqual(
            gen._eval_array_init(
                init_list([InitItem((), Identifier("missing"))]),
                Type("int").array_of(2),
            ),
            0,
        )
        self.assertIsNone(
            gen._eval_record_init(
                init_list([InitItem((("index", typed_int("0")),), typed_int("1"))]),
                Type("struct Pair"),
            ),
        )
        self.assertIsNone(
            gen._eval_record_init(
                init_list([InitItem((("member", "missing"),), typed_int("1"))]),
                Type("struct Pair"),
            ),
        )
        self.assertNotEqual(
            gen._eval_record_init(
                init_list([InitItem((), typed_int("1")), InitItem((), typed_int("2"))]),
                Type("union U"),
            ),
            0,
        )
        self.assertNotEqual(
            gen._eval_record_init(
                init_list(
                    [
                        InitItem((), typed_int("1")),
                        InitItem((), typed_int("2")),
                        InitItem((), typed_int("3")),
                    ],
                ),
                Type("struct Pair"),
            ),
            0,
        )
        self.assertNotEqual(
            gen._eval_record_init(
                init_list([InitItem((), Identifier("missing"))]),
                Type("struct Pair"),
            ),
            0,
        )
        self.assertNotEqual(gen._eval_record_init(InitList(()), Type("union U")), 0)
        self.assertNotEqual(gen._eval_record_init(InitList(()), Type("struct Empty")), 0)
        self.assertNotEqual(
            gen._eval_record_init(
                init_list([InitItem((("member", "nested"), ("member", "right")), typed_int("8"))]),
                Type("struct Outer"),
            ),
            0,
        )
        anonymous_record_init = gen._eval_record_init(
            init_list([InitItem((("member", "inner"),), typed_int("9"))]),
            Type("struct Wrapper"),
        )
        self.assertIsNotNone(anonymous_record_init)
        self.assertNotEqual(anonymous_record_init, 0)
        self.assertNotEqual(
            gen._eval_record_init(
                init_list([InitItem((("member", "right"),), Identifier("missing"))]),
                Type("struct Pair"),
            ),
            0,
        )

        self.assertEqual(
            gen._eval_unbraced_aggregate_initializer_items(Type("int").array_of(2), (), 2),
            (0, None),
        )
        self.assertEqual(
            gen._eval_unbraced_aggregate_initializer_items(
                Type("int", declarator_ops=(("arr", -1),)),
                (InitItem((), typed_int("1")),),
                0,
            ),
            (0, None),
        )
        self.assertEqual(
            gen._eval_unbraced_aggregate_initializer_items(
                Type("int").array_of(2),
                (InitItem((("index", typed_int("0")),), typed_int("1")),),
                0,
            )[0],
            0,
        )
        self.assertEqual(
            gen._eval_unbraced_aggregate_initializer_items(
                INT,
                (InitItem((), typed_int("1")),),
                0,
            ),
            (0, None),
        )
        self.assertEqual(
            gen._eval_unbraced_aggregate_initializer_items(
                Type("struct Missing"),
                (InitItem((), typed_int("1")),),
                0,
            ),
            (0, None),
        )
        consumed, value = gen._eval_unbraced_aggregate_initializer_items(
            Type("union U"),
            (InitItem((), typed_int("1")),),
            0,
        )
        self.assertEqual(consumed, 1)
        self.assertNotEqual(value, 0)
        self.assertEqual(
            gen._eval_unbraced_aggregate_initializer_items(
                Type("struct Pair"),
                (InitItem((("member", "left"),), typed_int("1")),),
                0,
            )[0],
            0,
        )
        self.assertEqual(
            gen._eval_unbraced_aggregate_initializer_items(
                Type("struct Pair"),
                (InitItem((), init_list([InitItem((), typed_int("1"))])),),
                0,
            )[0],
            1,
        )
        consumed, value = gen._eval_unbraced_aggregate_initializer_items(
            Type("int").array_of(1),
            (InitItem((), Identifier("missing")),),
            0,
        )
        self.assertEqual(consumed, 1)
        self.assertNotEqual(value, 0)
        consumed, value = gen._eval_unbraced_aggregate_initializer_items(
            Type("union U"),
            (InitItem((), Identifier("missing")),),
            0,
        )
        self.assertEqual(consumed, 1)
        self.assertNotEqual(value, 0)
        self.assertEqual(
            gen._eval_unbraced_initializer_item(
                INT,
                (InitItem((("index", typed_int("0")),), typed_int("1")),),
                0,
            ),
            (0, None),
        )
        self.assertEqual(
            gen._eval_unbraced_initializer_item(
                Type("int").array_of(1),
                (InitItem((), init_list([InitItem((), typed_int("1"))])),),
                0,
            )[0],
            1,
        )
        self.assertNotEqual(gen._eval_scalar_record_init(typed_int("1"), Type("struct Missing")), 0)
        self.assertIsNone(gen._eval_scalar_record_init(Identifier("missing"), Type("struct Pair")))
        self.assertNotEqual(
            gen._eval_record_path_init(
                [("struct Pair", 1, gen._sema.record_definitions["struct Pair"][1])],
                (),
                typed_int("9"),
            ),
            0,
        )
        self.assertIsNone(
            gen._eval_record_path_init(
                [("struct Pair", 0, gen._sema.record_definitions["struct Pair"][0])],
                (),
                Identifier("missing"),
            ),
        )
        self.assertNotEqual(
            gen._eval_designated_init(Type("struct Pair"), (("member", "right"),), typed_int("3")),
            0,
        )
        self.assertNotEqual(gen._const_array(c.Int32Type(), []), 0)
        self.assertNotEqual(gen._const_struct(Type("struct Pair"), []), 0)
        self.assertNotEqual(
            gen._const_union(
                Type("union Missing"),
                gen._sema.record_definitions["union U"][0],
                c.ConstInt(c.Int32Type(), 1, False),
            ),
            0,
        )
        self.assertNotEqual(
            gen._const_union(
                Type("union U"),
                gen._sema.record_definitions["union U"][0],
                c.ConstReal(c.DoubleType(), 1.0),
            ),
            0,
        )
        ptr_members = gen._sema.record_definitions["union Ptrs"]
        self.assertNotEqual(
            gen._coerce_union_storage_value(
                c.ConstPointerNull(gen._type_to_llvm(ptr_members[0].type_)),
                ptr_members[0],
                ptr_members[1],
                gen._record_member_llvm_type(ptr_members[1]),
            ),
            0,
        )
        bad_ptr_union = gen._const_union(
            Type("union Ptrs"),
            ptr_members[0],
            c.ConstIntToPtr(
                c.ConstInt(c.Int64Type(), 1, False),
                gen._type_to_llvm(ptr_members[0].type_),
            ),
        )
        self.assertIsNone(gen._const_union_bytes(bad_ptr_union, "union Ptrs"))
        self.assertNotEqual(
            gen._coerce_union_storage_value(
                c.ConstInt(c.Int8Type(), 255, False),
                gen._sema.record_definitions["union U"][0],
                gen._sema.record_definitions["union U"][1],
                gen._record_member_llvm_type(gen._sema.record_definitions["union U"][1]),
            ),
            0,
        )
        array_const = gen._const_array(
            c.Int32Type(),
            [c.ConstInt(c.Int32Type(), 1, False), c.ConstInt(c.Int32Type(), 2, False)],
        )
        self.assertEqual(
            gen._const_value_bytes(array_const, Type("int").array_of(2)),
            (1).to_bytes(4, "little") + (2).to_bytes(4, "little"),
        )
        pair_const = gen._eval_record_init(
            init_list([InitItem((), typed_int("1")), InitItem((), typed_int("2"))]),
            Type("struct Pair"),
        )
        self.assertIsNotNone(pair_const)
        assert pair_const is not None
        self.assertEqual(len(gen._const_value_bytes(pair_const, Type("struct Pair")) or b""), 8)
        gen._sema.record_definitions["struct PaddedTail"] = (
            RecordMemberInfo("tag", Type("char")),
            RecordMemberInfo("word", INT),
            RecordMemberInfo("tail", Type("char")),
        )
        padded_const = gen._const_struct(
            Type("struct PaddedTail"),
            [
                c.ConstInt(c.Int8Type(), 1, False),
                c.ConstInt(c.Int32Type(), 2, False),
                c.ConstInt(c.Int8Type(), 3, False),
            ],
        )
        padded_bytes = gen._const_struct_bytes(padded_const, "struct PaddedTail")
        self.assertIsNotNone(padded_bytes)
        self.assertEqual(len(padded_bytes or b""), gen._record_size("struct PaddedTail"))
        self.assertEqual(
            gen._const_value_bytes(c.ConstInt(c.Int32Type(), 0, False), Type("void")),
            b"",
        )
        float_array_const = gen._const_array(
            c.FloatType(),
            [c.ConstReal(c.FloatType(), 1.0)],
        )
        self.assertIsNone(gen._const_value_bytes(float_array_const, FLOAT.array_of(1)))
        self.assertIsNone(gen._const_value_bytes(c.ConstReal(c.DoubleType(), 1.0), Type("double")))
        self.assertIsNone(
            gen._const_value_bytes(array_const, Type("int", declarator_ops=(("ptr", 0),)))
        )
        self.assertIsNone(
            gen._const_struct_bytes(c.ConstInt(c.Int32Type(), 0, False), "struct Missing")
        )
        float_box_const = gen._const_struct(
            Type("struct FloatBox"),
            [c.ConstReal(c.FloatType(), 1.0)],
        )
        self.assertIsNone(gen._const_struct_bytes(float_box_const, "struct FloatBox"))
        self.assertEqual(
            gen._const_union_bytes(c.ConstInt(c.Int32Type(), 0, False), "union Missing"),
            b"",
        )
        self.assertNotEqual(
            gen._const_aggregate_element(c.ConstInt(c.Int32Type(), 1, False), 0, c.Int32Type()), 0
        )
        empty_struct = c.ConstNull(c.StructType(None, 0, False))
        self.assertNotEqual(gen._const_aggregate_element(empty_struct, 0, c.Int32Type()), 0)
        self.assertIsNone(gen._const_from_bytes(b"\0" * 4, FLOAT.array_of(1)))
        self.assertNotEqual(gen._const_from_bytes(b"\0" * 8, INT.pointer_to()), 0)
        self.assertIsNone(gen._const_from_bytes(b"\1" + b"\0" * 7, INT.pointer_to()))
        self.assertIsNone(gen._const_from_bytes(b"\0" * 4, Type("int").function_of(())))
        self.assertIsNone(gen._const_from_bytes(b"\0" * 8, FLOAT))
        self.assertNotEqual(
            gen._const_from_bytes((1).to_bytes(8, "little"), Type("union U")),
            0,
        )
        self.assertIsNone(gen._const_struct_from_bytes(b"", "struct Missing"))
        self.assertIsNone(gen._const_struct_from_bytes(b"\1" + b"\0" * 7, "struct PtrHolder"))
        self.assertNotEqual(gen._const_union_from_bytes(b"", "union Missing"), 0)
        self.assertIsNone(gen._const_union_from_bytes(b"\1" + b"\0" * 7, "union Ptrs"))
        self.assertNotEqual(gen._eval_const_expr(typed_int("7"), Type("double")), 0)
        self.assertNotEqual(gen._eval_const_expr(typed_int("7"), INT), 0)
        self.assertIsNone(gen._eval_const_expr(typed_int("7"), Type("struct Pair")))
        non_array_pointer_expr = typed_expr(Identifier("non_array_pointer_expr"), INT)
        self.assertIsNone(gen._eval_const_expr(non_array_pointer_expr, INT.pointer_to()))

        compound_literal = CompoundLiteralExpr(
            TypeSpec("int"),
            init_list([InitItem((), typed_int("1"))]),
        )
        typed_expr(compound_literal, INT)
        self.assertNotEqual(gen._eval_const_expr(compound_literal, INT.pointer_to()), 0)
        self.assertNotEqual(gen._eval_const_expr(compound_literal), 0)
        self.assertEqual(
            gen._const_compound_literal_addr(compound_literal),
            gen._const_compound_literal_addr(compound_literal),
        )
        fixed_array_literal = CompoundLiteralExpr(
            TypeSpec("int", array_lengths=(2,)),
            init_list([InitItem((), typed_int("1")), InitItem((), typed_int("2"))]),
        )
        typed_expr(fixed_array_literal, Type("int").array_of(2))
        self.assertNotEqual(gen._const_compound_literal_addr(fixed_array_literal), 0)
        self.assertIsNone(gen._eval_const_expr(UnaryExpr("-", FloatLiteral("1.0"))))
        self.assertNotEqual(
            gen._eval_const_expr(UnaryExpr("-", FloatLiteral("1.0")), Type("double")),
            0,
        )
        self.assertIsNone(gen._eval_const_expr(UnaryExpr("+", typed_int("1"))))
        self.assertNotEqual(
            gen._eval_const_expr(CastExpr(TypeSpec("double"), typed_int("3"))),
            0,
        )
        self.assertNotEqual(gen._eval_const_expr(SizeofExpr(None, TypeSpec("int"))), 0)
        self.assertIsNone(gen._eval_const_expr(AlignofExpr(None, None)))
        self.assertNotEqual(gen._eval_const_expr(AlignofExpr(None, TypeSpec("long"))), 0)
        self.assertNotEqual(
            gen._eval_const_expr(
                BuiltinOffsetofExpr(TypeSpec("struct", record_tag="Pair"), "right"),
            ),
            0,
        )

        static_global = c.AddGlobal(gen._mod, c.Int32Type(), b"static_local_const")
        gen._static_local_global_values.add(static_global)
        gen._locals.append({"s": static_global})
        self.assertEqual(gen._eval_const_identifier(Identifier("s")), static_global)
        self.assertNotEqual(gen._eval_const_identifier(Identifier("ENUM_VALUE")), 0)
        file_scope = gen._sema.file_scope
        object.__setattr__(gen._sema, "file_scope", None)
        try:
            self.assertIsNone(gen._eval_const_identifier(Identifier("ENUM_VALUE")))
        finally:
            object.__setattr__(gen._sema, "file_scope", file_scope)
        self.assertNotEqual(
            gen._eval_const_identifier(
                typed_expr(Identifier("arr_global"), Type("int").array_of(3))
            ),
            0,
        )
        self.assertNotEqual(
            gen._eval_const_addr(typed_expr(Identifier("callee2"), Type("int").function_of(()))),
            0,
        )
        c.AddGlobal(gen._mod, c.Int32Type(), b"const_known_global")
        self.assertNotEqual(gen._eval_const_addr(Identifier("const_known_global")), 0)
        c.AddFunction(
            gen._mod,
            b"const_known_fn",
            c.FunctionType(c.Int32Type(), None, 0, False),
        )
        self.assertNotEqual(gen._eval_const_addr(Identifier("const_known_fn")), 0)
        self.assertNotEqual(
            gen._eval_const_addr(
                UnaryExpr("*", typed_expr(Identifier("arr_global"), Type("int").array_of(3))),
            ),
            0,
        )
        literal = StringLiteral('"cache"')
        self.assertEqual(
            gen._const_string_literal_ptr(literal), gen._const_string_literal_ptr(literal)
        )
        self.assertNotEqual(gen._const_cast(c.ConstInt(c.Int32Type(), 1, False), c.VoidType()), 0)
        self.assertNotEqual(
            gen._const_cast(c.ConstInt(c.Int64Type(), 0, False), c.PointerType(c.Int8Type(), 0)),
            0,
        )
        self.assertNotEqual(
            gen._const_cast(c.ConstInt(c.Int64Type(), 1, False), c.PointerType(c.Int8Type(), 0)),
            0,
        )
        self.assertNotEqual(gen._const_cast(c.ConstInt(c.Int32Type(), 2, False), c.Int1Type()), 0)
        self.assertNotEqual(gen._const_cast(c.ConstInt(c.Int64Type(), 2, False), c.Int32Type()), 0)
        ptr_int_expr = c.ConstPtrToInt(
            c.ConstPointerNull(c.PointerType(c.Int8Type(), 0)),
            c.Int64Type(),
        )
        self.assertNotEqual(gen._const_cast(ptr_int_expr, c.Int32Type()), 0)
        dynamic_int_addr = c.BuildAlloca(gen._builder, c.Int64Type(), b"dynamic.const.cast.addr")
        c.BuildStore(gen._builder, c.ConstInt(c.Int64Type(), 2, False), dynamic_int_addr)
        dynamic_int = c.BuildLoad2(
            gen._builder,
            c.Int64Type(),
            dynamic_int_addr,
            b"dynamic.const.cast",
        )
        self.assertNotEqual(gen._const_cast(dynamic_int, c.Int32Type()), 0)
        self.assertNotEqual(gen._const_cast(c.ConstReal(c.DoubleType(), 1.0), c.Int64Type()), 0)
        self.assertIsNone(
            gen._eval_int_constant_value(
                ConditionalExpr(Identifier("missing"), typed_int("1"), typed_int("2")),
            ),
        )
        self.assertEqual(
            gen._eval_int_constant_value(BinaryExpr("*", typed_int("3"), typed_int("4"))),
            12,
        )
        self.assertIsNone(
            gen._eval_int_constant_value(BinaryExpr("???", typed_int("3"), typed_int("4"))),
        )

    def test_codegen_helper_remaining_direct_edges_without_llc(self) -> None:
        result = compile_source(
            """
typedef const int MyInt;
struct Pair { int left; int right; };
struct Outer { struct Pair pair; int tail; };
struct Bits { int flag:1; };
union U { int i; long l; };
int global_array[2];
int global_value;
struct Pair global_pair;
union U global_union;
int (*global_fp)(long);
struct Pair make_pair(void);
int f(void) { return 0; }
""",
            filename="helper_remaining_edges.c",
            options=FrontendOptions(std="gnu11"),
        )
        gen = _LLVMGen(result)
        c = llvm()
        fn_type = c.FunctionType(c.VoidType(), None, 0, False)
        fn = c.AddFunction(gen._mod, b"probe_remaining_edges", fn_type)
        block = c.AppendBasicBlock(fn, b"entry")
        c.PositionBuilderAtEnd(gen._builder, block)
        gen._func = fn
        gen._entry_block = block
        gen._func_sym = result.sema.functions["f"]
        gen._locals = [{}]

        def typed_expr(expr, type_: Type):
            gen._type_map.set(expr, type_)
            return expr

        def typed_identifier(name: str, type_: Type) -> Identifier:
            return typed_expr(Identifier(name), type_)

        def typed_int(value: str = "1", type_: Type = INT) -> IntLiteral:
            return typed_expr(IntLiteral(value), type_)

        def init_list(items: list[InitItem]) -> InitList:
            return InitList(tuple(items))

        ptr_t = c.PointerType(c.Int8Type(), 0)
        ptr_addr = c.BuildAlloca(gen._builder, ptr_t, b"p.addr")
        c.BuildStore(gen._builder, c.ConstNull(ptr_t), ptr_addr)
        gen._locals[-1]["p"] = ptr_addr

        plain_fn = gen._function_designator("plain_fallback", INT)
        self.assertNotEqual(plain_fn, 0)
        self.assertEqual(gen._function_designator("plain_fallback", INT), plain_fn)
        self.assertIsNone(gen._lookup_symbol_type("definitely_missing_symbol"))

        symbol_indirect_call = CallExpr(Identifier("global_fp"), [typed_int("7", Type("short"))])
        typed_expr(symbol_indirect_call, INT)
        self.assertNotEqual(gen._call(symbol_indirect_call), 0)

        make_pair_call = CallExpr(
            typed_identifier("make_pair", Type("struct Pair").function_of(())), []
        )
        typed_expr(make_pair_call, Type("struct Pair"))
        self.assertNotEqual(gen._member_ptr(MemberExpr(make_pair_call, "left", True)), 0)

        scalar_compound = CompoundLiteralExpr(TypeSpec("int"), typed_int("9"))
        typed_expr(scalar_compound, INT)
        self.assertNotEqual(gen._compound_literal_addr(scalar_compound), 0)

        self.assertEqual(
            gen._resolve_type(TypeSpec("MyInt", pointer_depth=1, qualifiers=("volatile",))),
            Type("int", pointer_depth=1, qualifiers=("const", "volatile")),
        )

        void_call = CallExpr(Identifier("__builtin_unreachable"), [])
        cast_void_to_int = CastExpr(TypeSpec("int"), void_call)
        typed_expr(cast_void_to_int, INT)
        self.assertNotEqual(gen._cast(cast_void_to_int), 0)

        va_list_cast = CastExpr(
            TypeSpec("__builtin_va_list"), typed_identifier("p", Type("char").pointer_to())
        )
        typed_expr(va_list_cast, Type("__builtin_va_list"))
        self.assertNotEqual(gen._cast(va_list_cast), 0)

        float_expr = typed_expr(FloatLiteral("1.5f"), Type("float"))
        float_to_double = CastExpr(TypeSpec("double"), float_expr)
        typed_expr(float_to_double, Type("double"))
        self.assertNotEqual(gen._cast(float_to_double), 0)

        int_to_long = CastExpr(TypeSpec("long"), typed_int("5"))
        typed_expr(int_to_long, Type("long"))
        self.assertNotEqual(gen._cast(int_to_long), 0)

        va_pointer_expr = CastExpr(TypeSpec("char", pointer_depth=1), typed_int("0"))
        typed_expr(va_pointer_expr, Type("char").pointer_to())
        self.assertNotEqual(gen._va_arg(BuiltinVaArgExpr(va_pointer_expr, TypeSpec("int"))), 0)
        self.assertNotEqual(gen._va_intrinsic_call("__builtin_va_end", ()), 0)
        self.assertNotEqual(
            gen._va_intrinsic_call("__builtin_va_copy", (va_pointer_expr, va_pointer_expr)),
            0,
        )

        self.assertIsNone(
            gen._eval_array_init(
                InitList(()),
                Type("int", declarator_ops=(("arr", ArrayDecl(None)),)),
            ),
        )

        outer_pair = gen._sema.record_definitions["struct Outer"][0]
        pair_right = gen._sema.record_definitions["struct Pair"][1]
        union_i = gen._sema.record_definitions["union U"][0]
        self.assertIsNone(
            gen._eval_record_path_init([("struct Missing", 0, pair_right)], (), typed_int("1"))
        )
        self.assertNotEqual(
            gen._eval_record_path_init(
                [("struct Outer", 0, outer_pair), ("struct Pair", 1, pair_right)],
                (),
                typed_int("2"),
            ),
            0,
        )
        self.assertNotEqual(
            gen._eval_record_path_init(
                [("struct Outer", 0, outer_pair)],
                (("member", "right"),),
                typed_int("3"),
            ),
            0,
        )
        self.assertNotEqual(
            gen._eval_record_path_init([("union U", 0, union_i)], (), typed_int("4")),
            0,
        )
        self.assertNotEqual(
            gen._eval_record_init(
                init_list([InitItem((("member", "pair"), ("member", "right")), typed_int("5"))]),
                Type("struct Outer"),
            ),
            0,
        )
        self.assertNotEqual(
            gen._const_aggregate_element(c.ConstInt(c.Int32Type(), 1, False), 99, c.Int32Type()), 0
        )

        self.assertNotEqual(gen._eval_const_expr(CastExpr(TypeSpec("long"), typed_int("6"))), 0)
        c.AddGlobal(gen._mod, c.Int32Type(), b"manual_const_global")
        self.assertNotEqual(gen._eval_const_addr(Identifier("manual_const_global")), 0)
        c.AddFunction(
            gen._mod,
            b"manual_const_fn",
            c.FunctionType(c.Int32Type(), None, 0, False),
        )
        self.assertNotEqual(gen._eval_const_addr(Identifier("manual_const_fn")), 0)

        pair_ptr_zero = CastExpr(
            TypeSpec("struct", pointer_depth=1, record_tag="Pair"),
            typed_int("0"),
        )
        typed_expr(pair_ptr_zero, Type("struct Pair").pointer_to())
        self.assertNotEqual(gen._eval_const_member_ptr(MemberExpr(pair_ptr_zero, "right", True)), 0)
        missing_member_base = CallExpr(
            typed_identifier("make_pair", Type("struct Pair").function_of(())),
            [],
        )
        typed_expr(missing_member_base, Type("struct Pair"))
        self.assertIsNone(
            gen._eval_const_member_ptr(MemberExpr(missing_member_base, "left", False))
        )
        self.assertIsNone(
            gen._eval_const_member_ptr(
                MemberExpr(typed_identifier("global_pair", Type("struct Pair")), "missing", False)
            )
        )
        self.assertNotEqual(
            gen._eval_const_member_ptr(
                MemberExpr(typed_identifier("global_union", Type("union U")), "l", False)
            ),
            0,
        )

        self.assertIsNone(
            gen._eval_const_subscript_ptr(
                SubscriptExpr(
                    typed_identifier("global_array", Type("int").array_of(2)),
                    Identifier("i"),
                )
            )
        )
        array_call = CallExpr(
            typed_identifier("array_fn", Type("int").array_of(2).function_of(())), []
        )
        typed_expr(array_call, Type("int").array_of(2))
        self.assertIsNone(gen._eval_const_subscript_ptr(SubscriptExpr(array_call, typed_int("0"))))
        pointer_subscript = SubscriptExpr(
            typed_identifier("p", Type("char").pointer_to()),
            typed_int("0"),
        )
        typed_expr(pointer_subscript, Type("char"))
        self.assertIsNone(gen._eval_const_subscript_ptr(pointer_subscript))

        self.assertIsNone(gen._eval_int_constant_value(UnaryExpr("@", typed_int("1"))))
        self.assertIsNone(
            gen._eval_int_constant_value(BinaryExpr("+", Identifier("missing"), typed_int("1")))
        )
        self.assertIsNone(gen._offsetof_member_path(Type("struct Pair").pointer_to(), ["left"]))
        self.assertIsNone(gen._offsetof_member_path(INT, ["left"]))
        self.assertIsNone(gen._offsetof_member_path(Type("struct Pair"), ["missing"]))
        self.assertIsNone(gen._offsetof_member_path(Type("struct Outer"), ["pair", "missing"]))
        self.assertIsNone(gen._record_member_offset_and_type("struct Missing", "x"))
        self.assertEqual(gen._record_member_offset_and_type("union U", "i"), (0, INT))
        self.assertIsNone(gen._record_member_offset_and_type("union U", "missing"))
        self.assertIsNone(gen._record_member_offset_and_type("struct Bits", "flag"))

        case_expectations = {
            "/": 2,
            "%": 1,
            "<<": 20,
            ">>": 1,
            "|": 7,
            "&": 0,
            "^": 7,
            "==": 0,
            "!=": 1,
            "<": 0,
            ">": 1,
            "<=": 0,
            ">=": 1,
            "&&": 1,
            "||": 1,
            "???": 0,
        }
        for op, expected in case_expectations.items():
            with self.subTest(case_op=op):
                self.assertEqual(
                    gen._eval_case_val(BinaryExpr(op, IntLiteral("5"), IntLiteral("2"))),
                    expected,
                )
        with self.assertRaises(CodegenError):
            gen._eval_case_val(UnaryExpr("@", IntLiteral("1")))
        file_scope = gen._sema.file_scope
        object.__setattr__(gen._sema, "file_scope", None)
        try:
            with self.assertRaises(CodegenError):
                gen._eval_case_val(Identifier("ENUM_VALUE"))
        finally:
            object.__setattr__(gen._sema, "file_scope", file_scope)

    def test_codegen_helper_switch_decay_and_resolution_edges_without_llc(self) -> None:
        result = compile_source(
            """
struct Pair { int left; int right; };
int f(void) { return 0; }
""",
            filename="helper_switch_decay_edges.c",
            options=FrontendOptions(std="gnu11"),
        )
        gen = _LLVMGen(result)
        c = llvm()
        fn_type = c.FunctionType(c.VoidType(), None, 0, False)
        fn = c.AddFunction(gen._mod, b"probe_switch_decay_edges", fn_type)
        block = c.AppendBasicBlock(fn, b"entry")
        c.PositionBuilderAtEnd(gen._builder, block)
        gen._func = fn
        gen._entry_block = block
        gen._func_sym = result.sema.functions["f"]
        gen._locals = [{}]

        def typed_expr(expr, type_: Type):
            gen._type_map.set(expr, type_)
            return expr

        def typed_int(value: str = "1", type_: Type = INT) -> IntLiteral:
            return typed_expr(IntLiteral(value), type_)

        def fresh_block(name: bytes) -> None:
            c.PositionBuilderAtEnd(gen._builder, c.AppendBasicBlock(fn, name))

        self.assertNotEqual(gen._type_to_llvm(Type("int", declarator_ops=(("fn", 0),))), 0)

        gen._emit_switch(
            SwitchStmt(
                typed_int("1"),
                CompoundStmt(
                    [
                        CaseStmt(IntLiteral("1"), NullStmt()),
                        DefaultStmt(NullStmt()),
                    ],
                ),
            )
        )

        fresh_block(b"array.binary.left")
        array_value = c.ConstNull(c.ArrayType(c.Int32Type(), 2))
        left_array = typed_expr(Identifier("left_array"), Type("int").array_of(2))
        one = typed_int("1")
        array_add = BinaryExpr("+", left_array, one)
        typed_expr(array_add, Type("int").pointer_to())
        original_emit_expr = gen._emit_expr

        def emit_left_array(expr):
            if expr is left_array:
                return array_value
            if expr is one:
                return c.ConstInt(c.Int32Type(), 1, False)
            return original_emit_expr(expr)

        gen._emit_expr = emit_left_array
        try:
            self.assertNotEqual(gen._binary(array_add), 0)
        finally:
            gen._emit_expr = original_emit_expr

        fresh_block(b"array.binary.right")
        right_array = typed_expr(Identifier("right_array"), Type("int").array_of(2))
        two = typed_int("2")
        commuted_add = BinaryExpr("+", two, right_array)
        typed_expr(commuted_add, Type("int").pointer_to())

        def emit_right_array(expr):
            if expr is right_array:
                return array_value
            if expr is two:
                return c.ConstInt(c.Int32Type(), 2, False)
            return original_emit_expr(expr)

        gen._emit_expr = emit_right_array
        try:
            self.assertNotEqual(gen._binary(commuted_add), 0)
        finally:
            gen._emit_expr = original_emit_expr

        fresh_block(b"array.compare")
        self.assertNotEqual(
            gen._compare(
                "==",
                c.ConstNull(c.ArrayType(c.Int32Type(), 2)),
                c.ConstNull(c.ArrayType(c.Int32Type(), 2)),
                Type("int").array_of(2),
                Type("int").array_of(2),
                False,
                False,
            ),
            0,
        )

        fresh_block(b"direct.casts")
        self.assertNotEqual(
            gen._cast_int_to_width(c.ConstInt(c.Int32Type(), 3, False), 32, signed=False),
            0,
        )
        self.assertNotEqual(
            gen._build_cast(c.ConstReal(c.DoubleType(), 1.25), c.DoubleType()),
            0,
        )
        self.assertIsNone(
            gen._const_value_bytes(
                c.ConstIntToPtr(
                    c.ConstInt(c.Int64Type(), 1, False),
                    c.PointerType(c.Int8Type(), 0),
                ),
                Type("int").pointer_to(),
            )
        )

        gen._sema.record_definitions["struct <anon:matched>"] = (RecordMemberInfo("left", INT),)
        self.assertEqual(gen._record_name_for_type_spec(TypeSpec("struct")), "struct")
        self.assertEqual(
            gen._record_name_for_type_spec(
                TypeSpec("struct", record_members=((TypeSpec("int"), "left"),))
            ),
            "struct <anon:matched>",
        )
        self.assertEqual(
            gen._record_name_for_type_spec(
                TypeSpec("struct", record_members=((TypeSpec("int"), "right"),))
            ),
            "struct",
        )
        self.assertEqual(
            gen._record_name_for_type_spec(
                TypeSpec("struct", record_members=((TypeSpec("long"), "left"),))
            ),
            "struct",
        )

    def test_codegen_helper_remaining_fallback_edges_without_llc(self) -> None:
        result = compile_source(
            """
	struct Pair { int left; int right; };
	struct Outer { struct Pair nested; int tail; };
	struct Wrapper { struct { int inner; }; int tail; };
	struct HasPair { struct Pair pair; int tail; };
	int f(void) { return 0; }
		""",
            filename="helper_remaining_fallback_edges.c",
            options=FrontendOptions(std="gnu11"),
        )
        gen = _LLVMGen(result)
        c = llvm()
        fn_type = c.FunctionType(c.VoidType(), None, 0, False)
        fn = c.AddFunction(gen._mod, b"probe_remaining_fallback_edges", fn_type)
        block = c.AppendBasicBlock(fn, b"entry")
        c.PositionBuilderAtEnd(gen._builder, block)
        gen._func = fn
        gen._entry_block = block
        gen._func_sym = result.sema.functions["f"]
        gen._locals = [{}]

        def typed_expr(expr, type_: Type):
            gen._type_map.set(expr, type_)
            return expr

        def typed_int(value: str = "1", type_: Type = INT) -> IntLiteral:
            return typed_expr(IntLiteral(value), type_)

        def init_list(items: list[InitItem]) -> InitList:
            return InitList(tuple(items))

        def untyped_identifier(name: str) -> Identifier:
            expr = Identifier(name)
            gen._type_map._map.pop(id(expr), None)
            return expr

        original_emit_expr = gen._emit_expr

        null_cast_source = typed_int("1")
        null_cast = CastExpr(TypeSpec("int"), null_cast_source)
        typed_expr(null_cast, INT)

        def emit_null_cast_source(expr):
            if expr is null_cast_source:
                return 0
            return original_emit_expr(expr)

        gen._emit_expr = emit_null_cast_source
        try:
            with self.assertRaisesRegex(CodegenError, "Cast operand emitted null"):
                gen._cast(null_cast)
        finally:
            gen._emit_expr = original_emit_expr

        struct_source = typed_expr(Identifier("struct_value"), Type("struct Pair"))
        struct_to_int = CastExpr(TypeSpec("int"), struct_source)
        typed_expr(struct_to_int, INT)
        struct_value = c.ConstNull(gen._type_to_llvm(Type("struct Pair")))

        def emit_struct_source(expr):
            if expr is struct_source:
                return struct_value
            return original_emit_expr(expr)

        gen._emit_expr = emit_struct_source
        try:
            self.assertNotEqual(gen._cast(struct_to_int), 0)
        finally:
            gen._emit_expr = original_emit_expr

        va_cast_source = typed_int("0")
        va_cast = CastExpr(TypeSpec("__builtin_va_list"), va_cast_source)
        typed_expr(va_cast, Type("__builtin_va_list"))

        def emit_va_cast_source(expr):
            if expr is va_cast_source:
                return c.ConstPointerNull(c.PointerType(c.Int32Type(), 0))
            return original_emit_expr(expr)

        gen._emit_expr = emit_va_cast_source
        try:
            self.assertNotEqual(gen._cast(va_cast), 0)
        finally:
            gen._emit_expr = original_emit_expr

        va_int_cast_source = typed_int("1", Type("long"))
        va_int_cast = CastExpr(TypeSpec("__builtin_va_list"), va_int_cast_source)
        typed_expr(va_int_cast, Type("__builtin_va_list"))
        self.assertNotEqual(gen._cast(va_int_cast), 0)

        i8_ptr = c.ConstPointerNull(c.PointerType(c.Int8Type(), 0))
        i32_ptr_type = c.PointerType(c.Int32Type(), 0)
        self.assertEqual(gen._build_cast(i8_ptr, i32_ptr_type), i8_ptr)
        self.assertNotEqual(gen._const_cast(i8_ptr, i32_ptr_type), 0)
        self.assertNotEqual(
            gen._compare(
                "==",
                c.ConstInt(c.Int64Type(), 1, False),
                c.ConstInt(c.Int32Type(), 1, False),
                None,
                None,
                False,
                False,
            ),
            0,
        )
        self.assertNotEqual(
            gen._compare(
                "==",
                c.ConstInt(c.Int32Type(), 1, False),
                c.ConstInt(c.Int64Type(), 1, False),
                None,
                None,
                False,
                False,
            ),
            0,
        )
        file_scope = gen._sema.file_scope
        object.__setattr__(gen._sema, "file_scope", None)
        try:
            self.assertEqual(gen._resolve_type(TypeSpec("plain_name")), Type("plain_name"))
        finally:
            object.__setattr__(gen._sema, "file_scope", file_scope)

        pair_addr = c.BuildAlloca(
            gen._builder, gen._type_to_llvm(Type("struct Pair")), b"pair.addr"
        )
        original_emit_unbraced_item = gen._emit_unbraced_initializer_item_to_addr

        def emit_zero_unbraced_item(addr, target_type, items, index):
            return 0

        gen._emit_unbraced_initializer_item_to_addr = emit_zero_unbraced_item
        try:
            self.assertEqual(
                gen._emit_unbraced_aggregate_items_to_addr(
                    pair_addr,
                    Type("struct Pair"),
                    (InitItem((), typed_int("1")),),
                    0,
                ),
                0,
            )
        finally:
            gen._emit_unbraced_initializer_item_to_addr = original_emit_unbraced_item

        array_source = typed_expr(Identifier("array_value"), Type("int").array_of(2))
        array_cast = CastExpr(TypeSpec("int", pointer_depth=1), array_source)
        typed_expr(array_cast, Type("int").pointer_to())
        array_value = c.ConstNull(c.ArrayType(c.Int32Type(), 2))

        def emit_array_source(expr):
            if expr is array_source:
                return array_value
            return original_emit_expr(expr)

        gen._emit_expr = emit_array_source
        try:
            self.assertNotEqual(gen._cast(array_cast), 0)
        finally:
            gen._emit_expr = original_emit_expr

        va_pointer_expr = CastExpr(TypeSpec("char", pointer_depth=1), typed_int("0"))
        typed_expr(va_pointer_expr, Type("char").pointer_to())
        self.assertNotEqual(
            gen._va_intrinsic_call("__builtin_va_start", (va_pointer_expr,)),
            0,
        )

        with self.assertRaisesRegex(CodegenError, "Cannot deref non-ptr in member"):
            gen._member_ptr(MemberExpr(typed_expr(Identifier("not_ptr"), INT), "left", True))

        manual_global = c.AddGlobal(gen._mod, c.Int32Type(), b"fallback_global")
        self.assertEqual(gen._eval_const_addr(untyped_identifier("fallback_global")), manual_global)
        manual_fn = c.AddFunction(
            gen._mod,
            b"fallback_fn",
            c.FunctionType(c.Int32Type(), None, 0, False),
        )
        self.assertEqual(gen._eval_const_addr(untyped_identifier("fallback_fn")), manual_fn)
        self.assertIsNone(gen._eval_const_addr(untyped_identifier("fallback_missing")))

        const_pair_ptr = typed_expr(Identifier("const_pair_ptr"), Type("struct Pair").pointer_to())
        original_eval_const_expr = gen._eval_const_expr

        def eval_const_pair_ptr(expr, target_type=None):
            if expr is const_pair_ptr:
                return c.ConstPointerNull(gen._type_to_llvm(Type("struct Pair").pointer_to()))
            return original_eval_const_expr(expr, target_type)

        gen._eval_const_expr = eval_const_pair_ptr
        try:
            self.assertIsNotNone(
                gen._eval_const_member_ptr(MemberExpr(const_pair_ptr, "left", True))
            )
        finally:
            gen._eval_const_expr = original_eval_const_expr
        self.assertEqual(gen._resolve_declarator_ops((("arr", ArrayDecl(3)),)), (("arr", 3),))
        self.assertEqual(
            gen._record_member_offset_and_type("struct Wrapper", "inner"),
            (0, INT),
        )
        self.assertNotEqual(
            gen._eval_record_init(
                init_list([InitItem((("member", "inner"),), typed_int("5"))]),
                Type("struct Wrapper"),
            ),
            0,
        )
        self.assertNotEqual(
            gen._eval_record_init(
                init_list([InitItem((("member", "nested"), ("member", "right")), typed_int("6"))]),
                Type("struct Outer"),
            ),
            0,
        )
        self.assertNotEqual(
            gen._eval_record_init(
                init_list(
                    [
                        InitItem((), typed_int("1")),
                        InitItem((), typed_int("2")),
                        InitItem((), typed_int("3")),
                    ]
                ),
                Type("struct Outer"),
            ),
            0,
        )
        self.assertNotEqual(
            gen._eval_record_init(
                init_list([InitItem((("member", "inner"),), untyped_identifier("missing"))]),
                Type("struct Wrapper"),
            ),
            0,
        )
        self.assertNotEqual(
            gen._eval_record_init(
                init_list(
                    [InitItem((("member", "left"), ("index", typed_int("0"))), typed_int("7"))]
                ),
                Type("struct Pair"),
            ),
            0,
        )
        original_eval_unbraced_items = gen._eval_unbraced_aggregate_initializer_items

        def eval_zero_unbraced_items(target_type, items, start):
            return (0, None)

        gen._eval_unbraced_aggregate_initializer_items = eval_zero_unbraced_items
        try:
            self.assertNotEqual(
                gen._eval_record_init(
                    init_list([InitItem((), typed_int("8"))]),
                    Type("struct HasPair"),
                ),
                0,
            )
        finally:
            gen._eval_unbraced_aggregate_initializer_items = original_eval_unbraced_items
        self.assertEqual(
            gen._eval_unbraced_aggregate_initializer_items(
                Type("struct Missing").array_of(1),
                (InitItem((), typed_int("1")),),
                0,
            )[0],
            0,
        )
        gen._sema.record_definitions["struct HasMissing"] = (
            RecordMemberInfo("missing", Type("struct Missing")),
        )
        self.assertEqual(
            gen._eval_unbraced_aggregate_initializer_items(
                Type("struct HasMissing"),
                (InitItem((), typed_int("1")),),
                0,
            )[0],
            0,
        )
        self.assertEqual(
            gen._eval_unbraced_initializer_item(
                Type("struct Missing"),
                (InitItem((), typed_int("1")),),
                0,
            ),
            (0, None),
        )

        aggregate_initializer = typed_expr(Identifier("whole_pair"), Type("struct Pair"))
        whole_pair_addr = c.BuildAlloca(
            gen._builder,
            gen._type_to_llvm(Type("struct Pair")),
            b"whole.pair.addr",
        )
        original_emit_expr = gen._emit_expr
        original_build_cast = gen._build_cast
        cast_targets: list[int] = []

        def emit_mismatched_aggregate(expr):
            if expr is aggregate_initializer:
                return c.ConstNull(gen._type_to_llvm(Type("struct Empty")))
            return original_emit_expr(expr)

        def build_matching_aggregate_cast(value, to_type, from_c_type=None):
            cast_targets.append(to_type)
            return c.ConstNull(to_type)

        gen._emit_expr = emit_mismatched_aggregate
        gen._build_cast = build_matching_aggregate_cast
        try:
            gen._emit_initializer_to_addr(
                whole_pair_addr,
                Type("struct Pair"),
                (),
                aggregate_initializer,
            )
        finally:
            gen._build_cast = original_build_cast
            gen._emit_expr = original_emit_expr
        self.assertEqual(cast_targets, [gen._type_to_llvm(Type("struct Pair"))])


if __name__ == "__main__":
    unittest.main()
