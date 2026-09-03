import subprocess
import tempfile
import unittest
from pathlib import Path

from tests import _bootstrap  # noqa: F401
from xcc import cc_driver
from xcc.codegen import _LLVMGen, generate_llvm_ir
from xcc.frontend import FrontendOptions, compile_path, compile_source
from xcc.llvm_api import (
    LLVMTypeKind,
    llvm,
)
from xcc.llvm_tools import find_llc


class CodegenTests(unittest.TestCase):
    def _find_test_llc(self) -> str:
        try:
            return find_llc()
        except ValueError as error:
            self.skipTest(str(error))

    def test_long_double_llvm_type_matches_target_data_layout(self) -> None:
        darwin = _LLVMGen(
            compile_source(
                "long double value;",
                options=FrontendOptions(target_os="darwin", host_machine="arm64"),
            )
        )
        linux = _LLVMGen(
            compile_source(
                "long double value;",
                options=FrontendOptions(target_os="linux", host_machine="x86_64"),
            )
        )
        llvm_api = llvm()

        self.assertEqual(
            llvm_api.GetTypeKind(darwin._base_type("long double")),
            LLVMTypeKind.DOUBLE,
        )
        self.assertEqual(
            llvm_api.GetTypeKind(linux._base_type("long double")),
            LLVMTypeKind.X86_FP80,
        )

    def test_aot_bootstrap_profile_uses_darwin_aarch64_data_layout(self) -> None:
        llvm_ir = cc_driver._aot_compile_source_to_llvm_ir_unchecked(
            "bootstrap_layout.c",
            "long double value; char storage[sizeof(long double)];",
            (),
            (),
            (),
            "c11",
        )

        self.assertIn("@value = global double", llvm_ir)
        self.assertIn("@storage = global [8 x i8]", llvm_ir)

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

    def assertProgramReturns(
        self,
        source: str,
        expected: int,
        *link_args: str,
        clang_caller: str | None = None,
    ) -> None:
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
            objects = [str(obj_path)]
            if clang_caller is not None:
                caller_path = tmp_path / "caller.c"
                caller_obj_path = tmp_path / "caller.o"
                caller_path.write_text(clang_caller, encoding="utf-8")
                caller = subprocess.run(
                    ("clang", "-std=gnu11", "-c", str(caller_path), "-o", str(caller_obj_path)),
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(caller.returncode, 0, caller.stderr)
                objects.append(str(caller_obj_path))
            link = subprocess.run(
                ("clang", *objects, *link_args, "-o", str(exe_path)),
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(link.returncode, 0, link.stderr)
            run = subprocess.run((str(exe_path),), cwd=tmp, check=False)
        self.assertEqual(run.returncode, expected)

    def test_large_record_parameter_and_callback_match_clang_abi(self) -> None:
        self.assertProgramReturns(
            """
struct Triple { unsigned long first, second, third; };
void relay(struct Triple value, void (*callback)(struct Triple)) {
  callback(value);
}
""",
            0,
            clang_caller="""
struct Triple { unsigned long first, second, third; };
extern void relay(struct Triple, void (*)(struct Triple));
static int seen;
static void check(struct Triple value) {
  seen = value.first == 11 && value.second == 22 && value.third == 33;
  value.first = value.second = value.third = 0;
}
int main(void) {
  struct Triple value = {11, 22, 33};
  relay(value, check);
  return !seen || value.first != 11 || value.second != 22 || value.third != 33;
}
""",
        )

    def test_large_record_return_matches_clang_abi(self) -> None:
        self.assertProgramReturns(
            """
struct Quad { unsigned long first, second, third, fourth; };
struct Quad make_xcc(unsigned long value) {
  return (struct Quad){value, value + 1, value + 2, value + 3};
}
extern struct Quad make_clang(unsigned long);
int check_clang(void) {
  struct Quad (*make)(unsigned long) = make_clang;
  struct Quad value = make(20);
  return value.first != 20 || value.second != 21 ||
         value.third != 22 || value.fourth != 23;
}
""",
            0,
            clang_caller="""
struct Quad { unsigned long first, second, third, fourth; };
extern struct Quad make_xcc(unsigned long);
extern int check_clang(void);
struct Quad make_clang(unsigned long value) {
  struct Quad result = {value, value + 1, value + 2, value + 3};
  return result;
}
int main(void) {
  struct Quad value = make_xcc(10);
  return value.first != 10 || value.second != 11 ||
         value.third != 12 || value.fourth != 13 || check_clang();
}
""",
        )

    def test_record_argument_does_not_split_between_registers_and_stack(self) -> None:
        self.assertProgramReturns(
            """
struct Pair { unsigned long first, second; };
int xcc_receives(unsigned long a, unsigned long b, unsigned long c,
                 unsigned long d, unsigned long e, unsigned long f,
                 unsigned long g, struct Pair pair) {
  return a != 1 || b != 2 || c != 3 || d != 4 || e != 5 || f != 6 || g != 7 ||
         pair.first != 8 || pair.second != 9;
}
extern int clang_receives(unsigned long, unsigned long, unsigned long,
                          unsigned long, unsigned long, unsigned long,
                          unsigned long, struct Pair);
int call_clang(void) {
  struct Pair pair = {8, 9};
  int (*call)(unsigned long, unsigned long, unsigned long, unsigned long,
              unsigned long, unsigned long, unsigned long,
              struct Pair) = clang_receives;
  return call(1, 2, 3, 4, 5, 6, 7, pair);
}
""",
            0,
            clang_caller="""
struct Pair { unsigned long first, second; };
extern int xcc_receives(unsigned long, unsigned long, unsigned long,
                        unsigned long, unsigned long, unsigned long,
                        unsigned long, struct Pair);
extern int call_clang(void);
int clang_receives(unsigned long a, unsigned long b, unsigned long c,
                   unsigned long d, unsigned long e, unsigned long f,
                   unsigned long g, struct Pair pair) {
  return a != 1 || b != 2 || c != 3 || d != 4 || e != 5 || f != 6 || g != 7 ||
         pair.first != 8 || pair.second != 9;
}
int main(void) {
  struct Pair pair = {8, 9};
  return xcc_receives(1, 2, 3, 4, 5, 6, 7, pair) || call_clang();
}
""",
        )

    def test_float_argument_is_widened_for_double_parameter(self) -> None:
        self.assertProgramReturns(
            """
extern int accepts_double(double);
int call(float value) { return accepts_double(value); }
""",
            0,
            clang_caller="""
extern int call(float);
int accepts_double(double value) { return value == 15.25; }
int main(void) { return !call(15.25f); }
""",
        )

    def test_small_record_return_matches_clang_abi(self) -> None:
        self.assertProgramReturns(
            """
struct Pair { unsigned short first, second; };
struct Pair make_xcc(struct Pair value) {
  value.first *= 2;
  value.second *= 3;
  return value;
}
extern struct Pair make_clang(struct Pair);
int check_clang(void) {
  struct Pair (*make)(struct Pair) = make_clang;
  struct Pair value = make((struct Pair){9, 8});
  return value.first != 18 || value.second != 24;
}
""",
            0,
            clang_caller="""
struct Pair { unsigned short first, second; };
extern struct Pair make_xcc(struct Pair);
extern int check_clang(void);
struct Pair make_clang(struct Pair value) {
  value.first *= 2;
  value.second *= 3;
  return value;
}
int main(void) {
  struct Pair value = make_xcc((struct Pair){11, 7});
  return value.first != 22 || value.second != 21 || check_clang();
}
""",
        )

    def test_small_record_call_in_loop_does_not_grow_stack(self) -> None:
        source = """
typedef union { unsigned long bits; } Ref;
unsigned long unwrap(Ref ref) { return ref.bits; }
int main(void) {
  Ref ref = {1};
  unsigned long i = 0, total = 0;
  while (i < 1000000) {
    total += unwrap(ref);
    i++;
  }
  return total != 1000000;
}
"""
        ir = generate_llvm_ir(
            compile_source(
                source,
                options=FrontendOptions(std="gnu11", target_os="darwin", host_machine="arm64"),
            )
        )

        self.assertLess(ir.index("arg.coerce = alloca"), ir.index("while.cond:"))
        self.assertProgramReturns(source, 0)

    def test_local_declaration_has_one_alloca(self) -> None:
        ir = generate_llvm_ir(compile_source("int f(void) { int value = 1; return value; }"))

        self.assertEqual(ir.count("alloca i32"), 1)

    def test_mixed_bitfield_lvalue_operations_match_clang(self) -> None:
        self.assertProgramReturns(
            """
struct Bits {
  unsigned char guard : 3;
  signed short value : 5;
  unsigned int tail : 7;
};
int read_signed(struct Bits *bits) { return bits->value; }
int mutate(struct Bits *bits) {
  int old = bits->value++;
  bits->value += 3;
  bits->tail = 255;
  return old;
}
""",
            0,
            clang_caller="""
struct Bits {
  unsigned char guard : 3;
  signed short value : 5;
  unsigned int tail : 7;
};
extern int read_signed(struct Bits *);
extern int mutate(struct Bits *);
int main(void) {
  struct Bits bits = { .guard = 6, .value = -5, .tail = 42 };
  if (read_signed(&bits) != -5) return 1;
  if (mutate(&bits) != -5) return 2;
  return bits.guard != 6 || bits.value != -1 || bits.tail != 127;
}
""",
        )

    def test_bitfield_static_and_compound_literal_initializers_match_clang(self) -> None:
        self.assertProgramReturns(
            """
struct Bits {
  unsigned char first : 3;
  unsigned short second : 5;
  unsigned int third : 8;
};
struct Bits global = { .first = 5, .second = 17, .third = 166 };
unsigned int local_bytes(void) {
  struct Bits value = (struct Bits){ .first = 6, .second = 3, .third = 90 };
  unsigned char *bytes = (unsigned char *)&value;
  return bytes[0] | ((unsigned int)bytes[1] << 8);
}
""",
            0,
            clang_caller="""
struct Bits {
  unsigned char first : 3;
  unsigned short second : 5;
  unsigned int third : 8;
};
extern struct Bits global;
extern unsigned int local_bytes(void);
int main(void) {
  unsigned char *bytes = (unsigned char *)&global;
  if (global.first != 5 || global.second != 17 || global.third != 166) return 1;
  if (bytes[0] != 141 || bytes[1] != 166) return 2;
  return local_bytes() != 0x5a1e;
}
""",
        )

    def test_high_bit_character_enum_matches_runtime_char_value(self) -> None:
        self.assertProgramReturns(
            r"""
enum Opcode { PROTO = '\x80' };
int main(void) {
  char value = '\x80';
  switch ((enum Opcode)value) {
  case PROTO: return 0;
  default: return 1;
  }
}
""",
            0,
        )

    def test_thread_local_declarations_and_storage_use_native_tls(self) -> None:
        ir = self.assertLlcAccepts(
            "extern _Thread_local int external_value;\n"
            "int *get_external(void) { return &external_value; }\n"
        )
        self.assertIn("@external_value = external thread_local global i32", ir)
        self.assertProgramReturns(
            """
#include <pthread.h>
static _Thread_local int value = 7;
static int observed;
static void *set_value(void *unused) {
  (void)unused;
  value = 23;
  observed = value;
  return 0;
}
int main(void) {
  pthread_t thread;
  value = 17;
  if (pthread_create(&thread, 0, set_value, 0)) return 1;
  if (pthread_join(thread, 0)) return 2;
  return observed != 23 || value != 17;
}
""",
            0,
            "-pthread",
        )

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
        self.assertIn("ret i64 0", ir)
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

    def test_sizeof_distinguishes_nested_anonymous_record_identities(self) -> None:
        source = """
struct R;
typedef struct {
  union { unsigned x; struct R *r; } u;
  const unsigned char *p;
} A;
typedef struct {
  union { unsigned x; struct R *r; } u;
  const unsigned short *p;
} B;
unsigned long n = sizeof(B);
int main(void) { return n == 16 ? 0 : 1; }
"""

        self.assertProgramReturns(source, 0)

    def test_pragma_pack_controls_runtime_member_offsets(self) -> None:
        source = """
#pragma pack(push, 4)
struct Trailer {
  unsigned words[13];
  unsigned long context;
  int ad;
  unsigned labels;
};
#pragma pack(pop)
static struct Trailer saved = {{0}, 7, 8, 9};

int main(void)
{
  struct Trailer trailer;
  struct Trailer array[2];
  if (sizeof(trailer) != 68) return 1;
  if (_Alignof(struct Trailer) != 4) return 2;
  if ((char *)&trailer.context - (char *)&trailer != 52) return 3;
  if ((char *)&trailer.labels - (char *)&trailer != 64) return 4;
  if ((char *)&array[1] - (char *)&array[0] != 68) return 5;
  return saved.context == 7 && saved.ad == 8 && saved.labels == 9 ? 0 : 6;
}
"""

        self.assertProgramReturns(source, 0)

    def test_nested_local_array_bound_evaluates_offsetof(self) -> None:
        source = """
#define MAX(a, b) ((a) > (b) ? (a) : (b))
struct S { int a; long b; };
int main(void) {
  while (1) {
    char buffer[MAX(__builtin_offsetof(struct S, b) + sizeof(long), 256)];
    return sizeof(buffer) == 256 ? 0 : 1;
  }
}
"""

        self.assertProgramReturns(source, 0)

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

    def test_global_pointer_initializer_accepts_array_pointer_arithmetic(self) -> None:
        source = """
struct Slot { int id; int *value; };
static int values[] = {10, 20, 30, 40};
static struct Slot slots[] = {{64, values + 2}, {0, 0}};

int main(void)
{
  return slots[0].value == &values[2] && *slots[0].value == 30 ? 0 : 1;
}
"""

        ir = self.assertLlcAccepts(source)

        slots_line = "@slots = internal global" + ir.split(
            "@slots = internal global", 1
        )[1].splitlines()[0]
        self.assertIn("getelementptr", slots_line)
        self.assertNotIn("i32 64, ptr null", slots_line)
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

    def test_negative_integer_function_pointer_cast_uses_pointer_width(self) -> None:
        source = """
typedef void (*destructor_type)(void *);
extern int consume(destructor_type destructor);

int pass_transient(void)
{
  return consume((destructor_type)-1);
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("ptr inttoptr (i64 -1 to ptr)", ir)
        self.assertNotIn("ptr inttoptr (i32 -1 to ptr)", ir)

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
  unsigned char bytes[12] = "\a\b\f\v\x41\x80\u00A9\U000000A9\?";
  if (sizeof(bytes) != 12) return 1;
  if (bytes[0] != 7) return 2;
  if (bytes[1] != 8) return 3;
  if (bytes[2] != 12) return 4;
  if (bytes[3] != 11) return 5;
  if (bytes[4] != 'A') return 6;
  if (bytes[5] != 0x80) return 7;
  if (bytes[6] != 0xC2 || bytes[7] != 0xA9) return 8;
  if (bytes[8] != 0xC2 || bytes[9] != 0xA9) return 9;
  if (bytes[10] != '?') return 10;
  if (bytes[11] != 0) return 11;
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

        self.assertIn("ret i16", ir)
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

    def test_unsized_array_compound_literal_infers_bound_before_decay(self) -> None:
        source = """
int main(void)
{
  int *p = 1 + (int[]){0, 17, 29};
  return p[0] != 17 || p[1] != 29;
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

    def test_variadic_call_applies_default_argument_promotions(self) -> None:
        source = """
int promoted(int count, ...)
{
  __builtin_va_list ap;
  int integer;
  double real;
  __builtin_va_start(ap, count);
  integer = __builtin_va_arg(ap, int);
  real = __builtin_va_arg(ap, double);
  __builtin_va_end(ap);
  return integer == 61896 && real == 1.25;
}

int main(void)
{
  unsigned short integer = 61896;
  float real = 1.25f;
  return promoted(2, integer, real) ? 0 : 1;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("call i32 (i32, ...) @promoted(i32 2, i32", ir)
        self.assertIn(", double ", ir)
        self.assertProgramReturns(source, 0)

    def test_indirect_variadic_call_applies_default_argument_promotions(self) -> None:
        source = """
typedef int (*promoted_fn)(int, ...);

int promoted(int count, ...)
{
  __builtin_va_list ap;
  int signed_integer;
  int unsigned_integer;
  double real;
  __builtin_va_start(ap, count);
  signed_integer = __builtin_va_arg(ap, int);
  unsigned_integer = __builtin_va_arg(ap, int);
  real = __builtin_va_arg(ap, double);
  __builtin_va_end(ap);
  return signed_integer == -123 && unsigned_integer == 61896 && real == 1.25;
}

int main(void)
{
  promoted_fn call = promoted;
  short signed_integer = -123;
  unsigned short unsigned_integer = 61896;
  float real = 1.25f;
  return call(3, signed_integer, unsigned_integer, real) ? 0 : 1;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertRegex(ir, r"call i32 \(i32, \.\.\.\) %[^ (]+\(i32 3, i32")
        self.assertIn(", double ", ir)
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

        self.assertIn("call i64 @make_pair()", ir)
        self.assertIn("call void @make_big(ptr sret({ i64, i64, i64 })", ir)
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

    def test_nan_is_unequal_and_truthy(self) -> None:
        source = """
int main(void)
{
  double nan = __builtin_nan("");
  if (nan == nan) return 1;
  if (!(nan != nan)) return 2;
  if (!nan) return 3;
  return 0;
}
"""

        ir = self.assertLlcAccepts(source)

        self.assertIn("fcmp une double", ir)
        self.assertProgramReturns(source, 0)

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

        self.assertIn("call i64 @make_ref()", ir)
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
