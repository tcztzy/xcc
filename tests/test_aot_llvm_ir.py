import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from tests import _bootstrap  # noqa: F401
from xcc.aot import emit_llvm_text, lower_core_slice
from xcc.aot.core_runtime import RUNTIME_ALLOC, runtime_module, runtime_prelude
from xcc.aot.llvm_ir import (
    LlvmBlock,
    LlvmInstruction,
    LlvmModule,
    LlvmParameter,
    LlvmPart,
    LlvmType,
    _render_parts,
)
from xcc.llvm_tools import find_llc

ROOT = Path(__file__).resolve().parents[1]


def _real_llc() -> str | None:
    try:
        llc = find_llc()
    except ValueError:
        return None
    return llc if Path(llc).is_file() else None


class LlvmIrTests(unittest.TestCase):
    def test_renders_functions_blocks_instructions_and_continuations(self) -> None:
        module = LlvmModule()
        write = module.declare_function(
            "write",
            LlvmType("i64"),
            (
                LlvmParameter(LlvmType("i32")),
                LlvmParameter(LlvmType("ptr")),
                LlvmParameter(LlvmType("i64")),
            ),
        )
        function = module.define_function(
            "emit",
            LlvmType("i64"),
            (LlvmParameter(LlvmType("ptr"), "buffer"),),
            linkage="internal",
        )
        entry = function.append_block("entry")
        call = entry.emit("written", "call", " i64 ", write.symbol, "(")
        entry.continue_("  i32 2, ptr ", function.local("buffer"), ", i64 3)")
        entry.emit(None, "ret", " i64 ", function.local("written"))

        self.assertIs(call.call_target(), write.symbol)
        self.assertEqual(
            module.render(),
            "declare i64 @write(i32, ptr, i64)\n\n"
            "define internal i64 @emit(ptr %buffer) {\n"
            "entry:\n"
            "  %written = call i64 @write(\n"
            "    i32 2, ptr %buffer, i64 3)\n"
            "  ret i64 %written\n"
            "}",
        )

    def test_symbol_rename_updates_declaration_and_every_reference(self) -> None:
        module = LlvmModule()
        puts = module.declare_function(
            "puts",
            LlvmType("i32"),
            (LlvmParameter(LlvmType("ptr")),),
        )
        function = module.define_function("main", LlvmType("i32"), ())
        entry = function.append_block("entry")
        entry.emit("status", "call", " i32 ", puts.symbol, "(ptr null)")
        entry.emit(None, "ret", " i32 ", function.local("status"))

        module.rename_symbol(puts.symbol, "print_line")

        rendered = module.render()
        self.assertIn("declare i32 @print_line(ptr)", rendered)
        self.assertIn("call i32 @print_line(ptr null)", rendered)
        self.assertNotIn("@puts", rendered)
        self.assertEqual(module.symbol("print_line"), puts.symbol)

    def test_global_initializers_reference_symbols_as_objects(self) -> None:
        module = LlvmModule()
        state = module.add_global("state", "internal global i64 0")
        alias = module.add_global("state_alias", "internal alias ptr, ptr ", state.symbol)

        module.rename_symbol(state.symbol, "renamed_state")

        self.assertEqual(alias.definition, "internal alias ptr, ptr @renamed_state")
        self.assertEqual(
            module.render(),
            "@renamed_state = internal global i64 0\n"
            "@state_alias = internal alias ptr, ptr @renamed_state",
        )

    def test_redirect_calls_changes_only_the_callee_symbol(self) -> None:
        module = LlvmModule()
        malloc = module.import_function("malloc")
        allocation = module.define_function(
            RUNTIME_ALLOC,
            LlvmType("ptr"),
            (LlvmParameter(LlvmType("i64"), "size"),),
        )
        allocation_entry = allocation.append_block("entry")
        allocation_entry.emit(None, "ret", " ptr null")
        caller = module.define_function("caller", LlvmType("ptr"), ())
        entry = caller.append_block("entry")
        entry.emit("result", "call", " ptr ", malloc, "(i64 8)")
        entry.emit(None, "ret", " ptr ", caller.local("result"))

        replacements = module.redirect_calls(malloc, allocation.symbol)

        self.assertEqual(replacements, 1)
        self.assertEqual(module.symbol_uses(malloc), ())
        uses = module.symbol_uses(allocation.symbol)
        self.assertEqual(len(uses), 1)
        self.assertEqual(uses[0].function, "caller")
        self.assertEqual(uses[0].opcode, "call")
        self.assertNotIn("@malloc", module.render())

    def test_rejects_duplicate_unresolved_and_foreign_symbols(self) -> None:
        duplicate = LlvmModule()
        duplicate.add_global("state", "internal global i64 0")
        with self.assertRaisesRegex(ValueError, "duplicate LLVM symbol"):
            duplicate.define_function("state", LlvmType("void"), ())
        with self.assertRaisesRegex(ValueError, "unresolved LLVM symbol"):
            duplicate.symbol("missing")

        unresolved = LlvmModule()
        function = unresolved.define_function("broken", LlvmType("i64"), ())
        entry = function.append_block("entry")
        entry.emit(None, "ret", " i64 ", function.local("missing"))
        with self.assertRaisesRegex(ValueError, "unresolved locals.*%missing"):
            unresolved.render()

        owner = LlvmModule()
        foreign = owner.import_function("foreign")
        borrower = LlvmModule()
        function = borrower.define_function("borrower", LlvmType("void"), ())
        entry = function.append_block("entry")
        entry.emit(None, "call", " void ", foreign, "()")
        entry.emit(None, "ret", " void")
        with self.assertRaisesRegex(ValueError, "foreign LLVM symbol"):
            borrower.render()

        local_owner = LlvmModule()
        owner_function = local_owner.define_function(
            "owner",
            LlvmType("void"),
            (LlvmParameter(LlvmType("i64"), "value"),),
        )
        local_borrower = LlvmModule()
        borrower_function = local_borrower.define_function("borrower", LlvmType("i64"), ())
        borrower_function.append_block("entry").emit(
            None,
            "ret",
            " i64 ",
            owner_function.local("value"),
        )
        with self.assertRaisesRegex(ValueError, "foreign LLVM local.*%value"):
            local_borrower.render()

    def test_core_runtime_is_queryable_and_has_no_raw_allocator_calls(self) -> None:
        module = runtime_module()
        allocation = module.symbol(RUNTIME_ALLOC)
        malloc = module.symbol("malloc")

        self.assertEqual(module.symbol_uses(malloc), ())
        self.assertGreaterEqual(len(module.symbol_uses(allocation)), 40)
        self.assertEqual(
            module.global_value("__xcc_aot_phase_allocation_buckets").definition,
            "internal global [2097152 x ptr] zeroinitializer",
        )
        prelude = runtime_prelude()
        self.assertNotIn("call ptr @malloc(", prelude)
        self.assertNotIn("call ptr @calloc(", prelude)
        self.assertIn(f"call ptr @{RUNTIME_ALLOC}(", prelude)
        self.assertIs(runtime_prelude(), prelude)

    def test_instruction_queries_cover_non_calls_and_continuation_uses(self) -> None:
        module = LlvmModule()
        first = module.import_function("first")
        second = module.import_function("second")
        function = module.define_function("caller", LlvmType("void"), ())
        entry = function.append_block("entry")
        branch = entry.emit(None, "br", " label ", function.local("done"))
        call = entry.emit(None, "call", " void ", first, "(")
        entry.continue_("  ptr ", second, ")")
        done = function.append_block("done")
        done.emit(None, "ret", " void")

        self.assertIsNone(branch.call_target())
        self.assertFalse(branch.replace_call_target(first, second))
        self.assertIs(call.call_target(), first)
        self.assertFalse(call.replace_call_target(second, first))
        self.assertTrue(call.references(second))
        self.assertFalse(branch.references(first))
        self.assertEqual(str(LlvmType("i64")), "i64")
        with self.assertRaisesRegex(TypeError, "unsupported LLVM part"):
            _render_parts(cast(tuple[LlvmPart, ...], (object(),)))

    def test_reports_invalid_model_mutations_at_the_owning_boundary(self) -> None:
        empty = LlvmModule()
        self.assertEqual(empty.render(), "")

        declaration_module = LlvmModule()
        declaration = declaration_module.declare_function("decl", LlvmType("void"), ())
        self.assertIs(declaration_module.function("decl"), declaration)
        with self.assertRaisesRegex(ValueError, "cannot add a block to declaration"):
            declaration.append_block("entry")
        declaration.blocks.append(cast(LlvmBlock, object()))
        with self.assertRaisesRegex(ValueError, "declaration @decl has a body"):
            declaration_module.render()

        bodyless = LlvmModule()
        bodyless.define_function("bodyless", LlvmType("void"), ())
        with self.assertRaisesRegex(ValueError, "definition @bodyless has no blocks"):
            bodyless.render()

        duplicate_local = LlvmModule()
        function = duplicate_local.define_function(
            "duplicate_local",
            LlvmType("void"),
            (LlvmParameter(LlvmType("i64"), "value"),),
        )
        entry = function.append_block("entry")
        with self.assertRaisesRegex(ValueError, "duplicate local %value"):
            entry.emit("value", "add", " i64 1, 2")
        empty_block = function.append_block("empty")
        with self.assertRaisesRegex(ValueError, "has no instruction to continue"):
            empty_block.continue_(" continuation")
        with self.assertRaisesRegex(ValueError, "references must use"):
            empty_block.emit(None, "call", " void @raw()")
        empty_block.emit(None, "ret", " void")
        with self.assertRaisesRegex(ValueError, "references must use"):
            empty_block.continue_(" %raw")

        wrong_kind = LlvmModule()
        global_value = wrong_kind.add_global("global", "internal global i64 0")
        function = wrong_kind.define_function("function", LlvmType("void"), ())
        function.append_block("entry").emit(None, "ret", " void")
        with self.assertRaisesRegex(ValueError, "not a function"):
            wrong_kind.function("global")
        with self.assertRaisesRegex(ValueError, "not a global"):
            wrong_kind.global_value("function")
        wrong_kind.globals.clear()
        with self.assertRaisesRegex(ValueError, "global has no definition"):
            wrong_kind.global_value(global_value.symbol.name)
        with self.assertRaisesRegex(ValueError, "global references must use"):
            wrong_kind.add_global("alias", "alias ptr @global")
        with self.assertRaisesRegex(ValueError, "global has no definition"):
            wrong_kind.add_global("empty")

        imported = LlvmModule()
        imported.import_function("external")
        with self.assertRaisesRegex(ValueError, "imported LLVM function has no body"):
            imported.function("external")

    def test_rejects_cross_module_symbol_mutations(self) -> None:
        module = LlvmModule()
        source = module.import_function("source")
        target = module.import_function("target")
        global_value = module.add_global("global", "internal global i64 0")
        foreign_module = LlvmModule()
        foreign = foreign_module.import_function("foreign")

        with self.assertRaisesRegex(ValueError, "symbol does not belong"):
            module.rename_symbol(foreign, "renamed")
        with self.assertRaisesRegex(ValueError, "duplicate LLVM symbol"):
            module.rename_symbol(source, target.name)
        with self.assertRaisesRegex(ValueError, "requires function symbols"):
            module.redirect_calls(global_value.symbol, target)
        with self.assertRaisesRegex(ValueError, "source symbol does not belong"):
            module.redirect_calls(foreign, target)
        with self.assertRaisesRegex(ValueError, "target symbol does not belong"):
            module.redirect_calls(source, foreign)
        with self.assertRaisesRegex(ValueError, "symbol does not belong"):
            module.symbol_uses(foreign)

        instruction = LlvmInstruction(None, "call", (" void",))
        self.assertIsNone(instruction.call_target())

        foreign_global = LlvmModule()
        foreign_global.add_global("borrower", "internal global ptr ", foreign)
        with self.assertRaisesRegex(ValueError, "foreign LLVM symbol in @borrower"):
            foreign_global.render()


@unittest.skipIf(_real_llc() is None, "LLVM llc is not available")
class LlvmIrNativeTests(unittest.TestCase):
    def test_structured_llvm_model_is_itself_native_llvm_parseable(self) -> None:
        module = lower_core_slice(
            (ROOT / "src/xcc/aot/llvm_ir.py",),
            root_targets=("xcc.aot.llvm_ir._render_parts",),
        )
        llvm_ir = emit_llvm_text(module)
        self.assertNotIn('@"LlvmSymbol | LlvmLocal.render"', llvm_ir)
        with TemporaryDirectory() as temp_dir:
            result = subprocess.run(
                (
                    _real_llc() or "llc",
                    "-filetype=obj",
                    "-o",
                    str(Path(temp_dir) / "runtime-builder.o"),
                    "-",
                ),
                input=llvm_ir,
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
