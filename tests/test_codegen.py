import subprocess
import tempfile
import unittest
from pathlib import Path

from tests import _bootstrap  # noqa: F401
from xcc.codegen import generate_llvm_ir
from xcc.frontend import FrontendOptions, compile_source

LLC = Path("/opt/homebrew/opt/llvm/bin/llc")


class CodegenTests(unittest.TestCase):
    def assertLlcAccepts(self, source: str) -> str:
        if not LLC.exists():
            self.skipTest(f"llc not found: {LLC}")
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
                (str(LLC), "-filetype=obj", str(ll_path), "-o", str(obj_path)),
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return ir

    def assertProgramReturns(self, source: str, expected: int) -> None:
        if not LLC.exists():
            self.skipTest(f"llc not found: {LLC}")
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
                (str(LLC), "-filetype=obj", str(ll_path), "-o", str(obj_path)),
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
            "extern const unsigned char table[];\n"
            "int f(int i) { return table[i]; }\n",
            filename="array.c",
            options=FrontendOptions(std="gnu11"),
        )

        ir = generate_llvm_ir(result)

        self.assertIn("@table = external global [0 x i8]", ir)
        self.assertIn("getelementptr [0 x i8], ptr @table", ir)
        self.assertNotIn("4294967295", ir)
        self.assertNotIn("load [0 x i8]", ir)
        self.assertNotIn("alloca [0 x i8]", ir)

    def test_bool_conversion_uses_nonzero_not_low_bit_truncation(self) -> None:
        self.assertProgramReturns(
            "int main(void) { _Bool b = 0x1000000; return b ? 0 : 1; }",
            0,
        )

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


if __name__ == "__main__":
    unittest.main()
