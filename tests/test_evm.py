import tempfile
import unittest
from pathlib import Path

import xcc.evm as evm
from tests import _bootstrap  # noqa: F401
from xcc.ast import (
    BinaryExpr,
    Identifier,
)
from xcc.evm import (
    evm_selector,
    generate_evm_asm,
    generate_evm_bytecode,
    keccak256,
)
from xcc.frontend import FrontendOptions, compile_source
from xcc.types import Type


class _MiniEvm:
    def __init__(
        self,
        bytecode: str,
        calldata: bytes,
        storage: dict[int, int] | None = None,
        *,
        address: int = 0,
        balances: dict[int, int] | None = None,
        block_hashes: dict[int, int] | None = None,
        caller: int = 0,
        callvalue: int = 0,
        code_hashes: dict[int, int] | None = None,
        code_sizes: dict[int, int] | None = None,
        codes: dict[int, bytes] | None = None,
        return_data: bytes = b"",
        external_calls: dict[int, tuple[int, bytes]] | None = None,
        create_address: int = 0,
        origin: int = 0,
        gasprice: int = 0,
        coinbase: int = 0,
        timestamp: int = 0,
        number: int = 0,
        prevrandao: int = 0,
        gaslimit: int = 0,
        chainid: int = 0,
        selfbalance: int = 0,
        basefee: int = 0,
        gas: int = 0,
        blob_hashes: dict[int, int] | None = None,
        blobbasefee: int = 0,
        transient_storage: dict[int, int] | None = None,
    ):
        self.code = bytes.fromhex(bytecode)
        self.calldata = calldata
        self.storage = {} if storage is None else storage
        self.transient_storage = {} if transient_storage is None else transient_storage
        self.address = address
        self.balances = {} if balances is None else balances
        self.block_hashes = {} if block_hashes is None else block_hashes
        self.caller = caller
        self.callvalue = callvalue
        self.code_hashes = {} if code_hashes is None else code_hashes
        self.code_sizes = {} if code_sizes is None else code_sizes
        self.codes = {} if codes is None else codes
        self.return_data = return_data
        self.external_calls = {} if external_calls is None else external_calls
        self.create_address = create_address
        self.origin = origin
        self.gasprice = gasprice
        self.coinbase = coinbase
        self.timestamp = timestamp
        self.number = number
        self.prevrandao = prevrandao
        self.gaslimit = gaslimit
        self.chainid = chainid
        self.selfbalance = selfbalance
        self.basefee = basefee
        self.gas = gas
        self.blob_hashes = {} if blob_hashes is None else blob_hashes
        self.blobbasefee = blobbasefee
        self.logs: list[tuple[tuple[int, ...], bytes]] = []
        self.call_trace: list[tuple[int, int, int, bytes, int]] = []
        self.create_trace: list[tuple[int, bytes]] = []
        self.create2_trace: list[tuple[int, bytes, int]] = []
        self.selfdestruct_trace: list[int] = []
        self.stack: list[int] = []
        self.memory = bytearray(256)
        self.memory_size = 0
        self.pc = 0

    @staticmethod
    def _to_signed(value: int) -> int:
        if value >= 1 << 255:
            return value - (1 << 256)
        return value

    @staticmethod
    def _from_signed(value: int) -> int:
        return value & ((1 << 256) - 1)

    def _ensure_memory(self, offset: int, size: int) -> None:
        needed = offset + size
        if size:
            self.memory_size = max(self.memory_size, ((needed + 31) // 32) * 32)
        if needed > len(self.memory):
            self.memory.extend(b"\x00" * (needed - len(self.memory)))

    def _run_external_call(
        self,
        gas: int,
        address: int,
        value: int,
        input_offset: int,
        input_size: int,
        output_offset: int,
        output_size: int,
    ) -> None:
        self._ensure_memory(input_offset, input_size)
        call_input = bytes(self.memory[input_offset : input_offset + input_size])
        success, returned = self.external_calls.get(address, (0, b""))
        self.return_data = returned
        self._ensure_memory(output_offset, output_size)
        self.memory[output_offset : output_offset + output_size] = returned[:output_size].ljust(
            output_size, b"\x00"
        )
        self.call_trace.append((gas, address, value, call_input, output_size))
        self.stack.append(success & ((1 << 256) - 1))

    def run(self) -> bytes:
        while self.pc < len(self.code):
            op = self.code[self.pc]
            self.pc += 1
            if 0x60 <= op <= 0x7F:
                size = op - 0x5F
                value = int.from_bytes(self.code[self.pc : self.pc + size], "big")
                self.pc += size
                self.stack.append(value)
                continue
            if 0x80 <= op <= 0x8F:
                self.stack.append(self.stack[-(op - 0x7F)])
                continue
            if 0x90 <= op <= 0x9F:
                depth = op - 0x8F
                self.stack[-1], self.stack[-1 - depth] = self.stack[-1 - depth], self.stack[-1]
                continue
            if op == 0x00:
                return b""
            if op in {
                0x01,
                0x02,
                0x03,
                0x04,
                0x05,
                0x06,
                0x07,
                0x08,
                0x09,
                0x0A,
                0x10,
                0x11,
                0x12,
                0x13,
                0x14,
                0x16,
                0x17,
                0x18,
            }:
                rhs = self.stack.pop()
                lhs = self.stack.pop()
                if op == 0x01:
                    result = lhs + rhs
                elif op == 0x02:
                    result = lhs * rhs
                elif op == 0x03:
                    result = lhs - rhs
                elif op == 0x04:
                    result = 0 if rhs == 0 else lhs // rhs
                elif op == 0x05:
                    signed_lhs = self._to_signed(lhs)
                    signed_rhs = self._to_signed(rhs)
                    if signed_rhs == 0:
                        result = 0
                    else:
                        result = self._from_signed(abs(signed_lhs) // abs(signed_rhs))
                        if (signed_lhs < 0) != (signed_rhs < 0):
                            result = self._from_signed(-result)
                elif op == 0x06:
                    result = 0 if rhs == 0 else lhs % rhs
                elif op == 0x07:
                    signed_lhs = self._to_signed(lhs)
                    signed_rhs = self._to_signed(rhs)
                    if signed_rhs == 0:
                        result = 0
                    else:
                        result = self._from_signed(abs(signed_lhs) % abs(signed_rhs))
                        if signed_lhs < 0:
                            result = self._from_signed(-result)
                elif op == 0x08:
                    modulus = self.stack.pop()
                    result = 0 if modulus == 0 else (lhs + rhs) % modulus
                elif op == 0x09:
                    modulus = self.stack.pop()
                    result = 0 if modulus == 0 else (lhs * rhs) % modulus
                elif op == 0x0A:
                    result = pow(rhs, lhs, 1 << 256)
                elif op == 0x10:
                    result = int(lhs < rhs)
                elif op == 0x11:
                    result = int(lhs > rhs)
                elif op == 0x12:
                    result = int(self._to_signed(lhs) < self._to_signed(rhs))
                elif op == 0x13:
                    result = int(self._to_signed(lhs) > self._to_signed(rhs))
                elif op == 0x14:
                    result = int(lhs == rhs)
                elif op == 0x16:
                    result = lhs & rhs
                elif op == 0x17:
                    result = lhs | rhs
                else:
                    result = lhs ^ rhs
                self.stack.append(result & ((1 << 256) - 1))
                continue
            if op == 0x15:
                self.stack.append(int(self.stack.pop() == 0))
                continue
            if op == 0x19:
                self.stack.append((~self.stack.pop()) & ((1 << 256) - 1))
                continue
            if op == 0x1A:
                byte_index = self.stack.pop()
                value = self.stack.pop()
                result = 0 if byte_index >= 32 else (value >> (8 * (31 - byte_index))) & 0xFF
                self.stack.append(result)
                continue
            if op == 0x1B:
                shift = self.stack.pop()
                value = self.stack.pop()
                self.stack.append((value << shift) & ((1 << 256) - 1))
                continue
            if op == 0x0B:
                byte_index = self.stack.pop()
                value = self.stack.pop()
                if byte_index >= 32:
                    self.stack.append(value)
                    continue
                bit_index = byte_index * 8 + 7
                mask = (1 << (bit_index + 1)) - 1
                value &= mask
                if value & (1 << bit_index):
                    value |= ((1 << 256) - 1) ^ mask
                self.stack.append(value)
                continue
            if op == 0x1C:
                shift = self.stack.pop()
                value = self.stack.pop()
                self.stack.append(value >> shift)
                continue
            if op == 0x1D:
                shift = self.stack.pop()
                value = self._to_signed(self.stack.pop())
                self.stack.append(self._from_signed(value >> shift))
                continue
            if op == 0x20:
                offset = self.stack.pop()
                size = self.stack.pop()
                self._ensure_memory(offset, size)
                hashed = evm.keccak256(self.memory[offset : offset + size])
                self.stack.append(int.from_bytes(hashed, "big"))
                continue
            if op == 0x30:
                self.stack.append(self.address)
                continue
            if op == 0x31:
                self.stack.append(self.balances.get(self.stack.pop(), 0))
                continue
            if op == 0x32:
                self.stack.append(self.origin)
                continue
            if op == 0x33:
                self.stack.append(self.caller)
                continue
            if op == 0x34:
                self.stack.append(self.callvalue)
                continue
            if op == 0x35:
                offset = self.stack.pop()
                chunk = self.calldata[offset : offset + 32].ljust(32, b"\x00")
                self.stack.append(int.from_bytes(chunk, "big"))
                continue
            if op == 0x36:
                self.stack.append(len(self.calldata))
                continue
            if op == 0x37:
                dest = self.stack.pop()
                offset = self.stack.pop()
                size = self.stack.pop()
                self._ensure_memory(dest, size)
                self.memory[dest : dest + size] = self.calldata[offset : offset + size].ljust(
                    size,
                    b"\x00",
                )
                continue
            if op == 0x38:
                self.stack.append(len(self.code))
                continue
            if op == 0x3A:
                self.stack.append(self.gasprice)
                continue
            if op == 0x3B:
                self.stack.append(self.code_sizes.get(self.stack.pop(), 0))
                continue
            if op == 0x3C:
                address = self.stack.pop()
                dest = self.stack.pop()
                offset = self.stack.pop()
                size = self.stack.pop()
                self._ensure_memory(dest, size)
                code = self.codes.get(address, b"")
                self.memory[dest : dest + size] = code[offset : offset + size].ljust(
                    size,
                    b"\x00",
                )
                continue
            if op == 0x3D:
                self.stack.append(len(self.return_data))
                continue
            if op == 0x3E:
                dest = self.stack.pop()
                offset = self.stack.pop()
                size = self.stack.pop()
                self._ensure_memory(dest, size)
                self.memory[dest : dest + size] = self.return_data[offset : offset + size].ljust(
                    size, b"\x00"
                )
                continue
            if op == 0x3F:
                self.stack.append(self.code_hashes.get(self.stack.pop(), 0))
                continue
            if op == 0x40:
                self.stack.append(self.block_hashes.get(self.stack.pop(), 0))
                continue
            if op == 0x39:
                dest = self.stack.pop()
                offset = self.stack.pop()
                size = self.stack.pop()
                self._ensure_memory(dest, size)
                self.memory[dest : dest + size] = self.code[offset : offset + size].ljust(
                    size, b"\x00"
                )
                continue
            if op == 0x41:
                self.stack.append(self.coinbase)
                continue
            if op == 0x42:
                self.stack.append(self.timestamp)
                continue
            if op == 0x43:
                self.stack.append(self.number)
                continue
            if op == 0x44:
                self.stack.append(self.prevrandao)
                continue
            if op == 0x45:
                self.stack.append(self.gaslimit)
                continue
            if op == 0x46:
                self.stack.append(self.chainid)
                continue
            if op == 0x47:
                self.stack.append(self.selfbalance)
                continue
            if op == 0x48:
                self.stack.append(self.basefee)
                continue
            if op == 0x49:
                self.stack.append(self.blob_hashes.get(self.stack.pop(), 0))
                continue
            if op == 0x4A:
                self.stack.append(self.blobbasefee)
                continue
            if op == 0x50:
                self.stack.pop()
                continue
            if op == 0x51:
                offset = self.stack.pop()
                self._ensure_memory(offset, 32)
                self.stack.append(int.from_bytes(self.memory[offset : offset + 32], "big"))
                continue
            if op == 0x52:
                offset = self.stack.pop()
                value = self.stack.pop()
                self._ensure_memory(offset, 32)
                self.memory[offset : offset + 32] = value.to_bytes(32, "big")
                continue
            if op == 0x53:
                offset = self.stack.pop()
                value = self.stack.pop()
                self._ensure_memory(offset, 1)
                self.memory[offset] = value & 0xFF
                continue
            if op == 0x54:
                self.stack.append(self.storage.get(self.stack.pop(), 0))
                continue
            if op == 0x55:
                key = self.stack.pop()
                value = self.stack.pop()
                self.storage[key] = value
                continue
            if op == 0x56:
                self.pc = self.stack.pop()
                continue
            if op == 0x57:
                dest = self.stack.pop()
                cond = self.stack.pop()
                if cond:
                    self.pc = dest
                continue
            if op == 0x58:
                self.stack.append(self.pc - 1)
                continue
            if op == 0x59:
                self.stack.append(self.memory_size)
                continue
            if op == 0x5A:
                self.stack.append(self.gas)
                continue
            if op == 0x5B:
                continue
            if op == 0x5C:
                self.stack.append(self.transient_storage.get(self.stack.pop(), 0))
                continue
            if op == 0x5D:
                key = self.stack.pop()
                value = self.stack.pop()
                self.transient_storage[key] = value
                continue
            if op == 0x5E:
                dest = self.stack.pop()
                src = self.stack.pop()
                size = self.stack.pop()
                self._ensure_memory(src, size)
                chunk = bytes(self.memory[src : src + size])
                self._ensure_memory(dest, size)
                self.memory[dest : dest + size] = chunk
                continue
            if op == 0x5F:
                self.stack.append(0)
                continue
            if 0xA0 <= op <= 0xA4:
                topic_count = op - 0xA0
                offset = self.stack.pop()
                size = self.stack.pop()
                self._ensure_memory(offset, size)
                topics = tuple(self.stack.pop() for _ in range(topic_count))
                self.logs.append((topics, bytes(self.memory[offset : offset + size])))
                continue
            if op == 0xF0:
                value = self.stack.pop()
                offset = self.stack.pop()
                size = self.stack.pop()
                self._ensure_memory(offset, size)
                initcode = bytes(self.memory[offset : offset + size])
                self.create_trace.append((value, initcode))
                self.stack.append(self.create_address & ((1 << 256) - 1))
                continue
            if op == 0xF1:
                gas = self.stack.pop()
                address = self.stack.pop()
                value = self.stack.pop()
                input_offset = self.stack.pop()
                input_size = self.stack.pop()
                output_offset = self.stack.pop()
                output_size = self.stack.pop()
                self._run_external_call(
                    gas,
                    address,
                    value,
                    input_offset,
                    input_size,
                    output_offset,
                    output_size,
                )
                continue
            if op == 0xF2:
                gas = self.stack.pop()
                address = self.stack.pop()
                value = self.stack.pop()
                input_offset = self.stack.pop()
                input_size = self.stack.pop()
                output_offset = self.stack.pop()
                output_size = self.stack.pop()
                self._run_external_call(
                    gas,
                    address,
                    value,
                    input_offset,
                    input_size,
                    output_offset,
                    output_size,
                )
                continue
            if op == 0xF3:
                offset = self.stack.pop()
                size = self.stack.pop()
                self._ensure_memory(offset, size)
                return bytes(self.memory[offset : offset + size])
            if op == 0xF4:
                gas = self.stack.pop()
                address = self.stack.pop()
                input_offset = self.stack.pop()
                input_size = self.stack.pop()
                output_offset = self.stack.pop()
                output_size = self.stack.pop()
                self._run_external_call(
                    gas,
                    address,
                    self.callvalue,
                    input_offset,
                    input_size,
                    output_offset,
                    output_size,
                )
                continue
            if op == 0xF5:
                value = self.stack.pop()
                offset = self.stack.pop()
                size = self.stack.pop()
                salt = self.stack.pop()
                self._ensure_memory(offset, size)
                initcode = bytes(self.memory[offset : offset + size])
                self.create2_trace.append((value, initcode, salt))
                self.stack.append(self.create_address & ((1 << 256) - 1))
                continue
            if op == 0xFA:
                gas = self.stack.pop()
                address = self.stack.pop()
                input_offset = self.stack.pop()
                input_size = self.stack.pop()
                output_offset = self.stack.pop()
                output_size = self.stack.pop()
                self._run_external_call(
                    gas,
                    address,
                    0,
                    input_offset,
                    input_size,
                    output_offset,
                    output_size,
                )
                continue
            if op == 0xFD:
                offset = self.stack.pop()
                size = self.stack.pop()
                self._ensure_memory(offset, size)
                payload = bytes(self.memory[offset : offset + size])
                raise AssertionError(f"EVM reverted: {payload.hex()}")
            if op == 0xFE:
                raise AssertionError("EVM invalid opcode")
            if op == 0xFF:
                self.selfdestruct_trace.append(self.stack.pop())
                return b""
            raise AssertionError(f"unsupported opcode 0x{op:02x}")
        return b""


def _calldata(signature: str, *args: int) -> bytes:
    data = evm_selector(signature).to_bytes(4, "big")
    for arg in args:
        data += arg.to_bytes(32, "big")
    return data


def _word(value: int) -> int:
    return value & ((1 << 256) - 1)


def _signed_word_value(data: bytes) -> int:
    value = int.from_bytes(data, "big")
    if value >= 1 << 255:
        return value - (1 << 256)
    return value


def _dynamic_uint256_array_calldata(signature: str, values: tuple[int, ...], *tail: int) -> bytes:
    data = evm_selector(signature).to_bytes(4, "big")
    data += (32 * (1 + len(tail))).to_bytes(32, "big")
    for arg in tail:
        data += arg.to_bytes(32, "big")
    data += len(values).to_bytes(32, "big")
    for value in values:
        data += value.to_bytes(32, "big")
    return data


def _decode_uint256_array_return(data: bytes) -> tuple[int, ...]:
    offset = int.from_bytes(data[:32], "big")
    length = int.from_bytes(data[offset : offset + 32], "big")
    values = []
    for index in range(length):
        start = offset + 32 + index * 32
        values.append(int.from_bytes(data[start : start + 32], "big"))
    return tuple(values)


class EvmTargetTests(unittest.TestCase):
    def _compile(self, source: str):
        return compile_source(
            source,
            filename="evm_test.c",
            options=FrontendOptions(std="gnu11", hosted=False, host_machine="evm"),
        )

    def _assert_evm_diagnostic(self, source: str, message: str) -> None:
        result = self._compile(source)

        with self.assertRaises(Exception) as error:
            generate_evm_bytecode(result)

        self.assertEqual(error.exception.diagnostic.code, "XCC-EVM-0001")
        self.assertEqual(error.exception.diagnostic.message, message)

    def _assert_evm_initcode_diagnostic(self, source: str, message: str) -> None:
        result = self._compile(source)

        with self.assertRaises(Exception) as error:
            evm.generate_evm_initcode(result)

        self.assertEqual(error.exception.diagnostic.code, "XCC-EVM-0001")
        self.assertEqual(error.exception.diagnostic.message, message)

    def test_keccak_selector_uses_ethereum_abi_hash(self) -> None:
        self.assertEqual(evm_selector("get()"), 0x6D4CE63C)
        self.assertEqual(evm_selector("set(uint32)"), 0x58E3CA1C)

    def test_keccak256_absorbs_full_rate_blocks(self) -> None:
        self.assertEqual(
            keccak256(b"a" * 136).hex(),
            "a6c4d403279fe3e0af03729caada8374b5ca54d8065329a3ebcaeb4b60aa386e",
        )
        self.assertEqual(
            keccak256(b"a" * 200).hex(),
            "96ea54061def936c4be90b518992fdc6f12f535068a256229aca54267b4d084d",
        )

    def test_evm_assembler_encodes_negative_values_and_push0(self) -> None:
        assembler = evm._Assembler()

        assembler.push(-1)
        assembler.push(0)

        self.assertEqual(assembler.to_bytes(), bytes.fromhex("7f" + "ff" * 32 + "5f"))
        self.assertIn("PUSH32 0x" + "ff" * 32, assembler.to_asm())
        self.assertIn("PUSH0", assembler.to_asm())

    def _typed_binary(
        self,
        gen,
        op: str,
        left_type: Type,
        right_type: Type,
    ) -> BinaryExpr:
        left = Identifier("left")
        right = Identifier("right")
        expr = BinaryExpr(op, left, right)
        gen._type_map.set(left, left_type)
        gen._type_map.set(right, right_type)
        return expr

    def test_generates_dispatcher_for_no_arg_return_function(self) -> None:
        result = self._compile("unsigned int get(void) { return 7; }\n")

        asm = generate_evm_asm(result)
        bytecode = generate_evm_bytecode(result)

        self.assertIn("PUSH4 0x6d4ce63c", asm)
        self.assertIn("CALLDATALOAD", asm)
        self.assertIn("SHR", asm)
        self.assertIn("RETURN", asm)
        self.assertIn("636d4ce63c", bytecode)
        self.assertIn("f3", bytecode)

    def test_generates_storage_builtins(self) -> None:
        source = """
unsigned int get(void) { return __builtin_evm_sload(0); }
void set(unsigned int value) { __builtin_evm_sstore(0, value); }
"""
        result = self._compile(source)

        asm = generate_evm_asm(result)
        bytecode = generate_evm_bytecode(result)

        self.assertIn("PUSH4 0x6d4ce63c", asm)
        self.assertIn("PUSH4 0x58e3ca1c", asm)
        self.assertIn("SLOAD", asm)
        self.assertIn("SSTORE", asm)
        self.assertIn("54", bytecode)
        self.assertIn("55", bytecode)

        storage: dict[int, int] = {}
        _MiniEvm(bytecode, _calldata("set(uint32)", 42), storage).run()
        returned = _MiniEvm(bytecode, _calldata("get()"), storage).run()
        self.assertEqual(int.from_bytes(returned, "big"), 42)

    def test_file_scope_scalar_variables_map_to_storage_slots(self) -> None:
        source = """
typedef __evm_uint256 uint256;

uint256 counter;
uint256 total;

uint256 get_counter(void) { return counter; }
void set_counter(uint256 value) { counter = value; }
void bump(void) { counter += 1; total += counter; }
uint256 get_total(void) { return total; }
"""
        result = self._compile(source)

        asm = generate_evm_asm(result)
        bytecode = generate_evm_bytecode(result)
        storage: dict[int, int] = {}

        _MiniEvm(bytecode, _calldata("set_counter(uint256)", 7), storage).run()
        returned = _MiniEvm(bytecode, _calldata("get_counter()"), storage).run()
        _MiniEvm(bytecode, _calldata("bump()"), storage).run()
        total_returned = _MiniEvm(bytecode, _calldata("get_total()"), storage).run()

        self.assertEqual(int.from_bytes(returned, "big"), 7)
        self.assertEqual(storage[0], 8)
        self.assertEqual(storage[1], 8)
        self.assertEqual(int.from_bytes(total_returned, "big"), 8)
        self.assertIn("SLOAD", asm)
        self.assertIn("SSTORE", asm)

    def test_initialized_storage_global_reports_evm_diagnostic(self) -> None:
        result = self._compile(
            "unsigned int counter = 1; unsigned int get(void) { return counter; }\n"
        )

        with self.assertRaises(Exception) as error:
            generate_evm_asm(result)
        self.assertEqual(error.exception.diagnostic.code, "XCC-EVM-0001")

    def test_non_commutative_binary_ops_preserve_c_operand_order(self) -> None:
        source = """
unsigned int sub(unsigned int a, unsigned int b) { return a - b; }
unsigned int sub_assign(unsigned int a, unsigned int b) { a -= b; return a; }
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)

        returned = _MiniEvm(bytecode, _calldata("sub(uint32,uint32)", 8, 3)).run()
        assigned = _MiniEvm(bytecode, _calldata("sub_assign(uint32,uint32)", 8, 3)).run()

        self.assertEqual(int.from_bytes(returned, "big"), 5)
        self.assertEqual(int.from_bytes(assigned, "big"), 5)

    def test_compound_assignment_ops_use_evm_arithmetic_bitwise_and_shift_opcodes(self) -> None:
        source = """
typedef __evm_uint256 uint256;

uint256 unsigned_ops(uint256 value)
{
  value *= 3;
  value /= 2;
  value %= 7;
  value &= 6;
  value |= 8;
  value ^= 2;
  value <<= 3;
  value >>= 1;
  return value;
}

int signed_ops(int value)
{
  value /= 3;
  value %= 3;
  value >>= 1;
  return value;
}
"""
        result = self._compile(source)
        asm = generate_evm_asm(result)
        bytecode = generate_evm_bytecode(result)

        unsigned_returned = _MiniEvm(bytecode, _calldata("unsigned_ops(uint256)", 10)).run()
        signed_returned = _MiniEvm(bytecode, _calldata("signed_ops(int32)", _word(-16))).run()

        self.assertEqual(int.from_bytes(unsigned_returned, "big"), 40)
        self.assertEqual(_signed_word_value(signed_returned), -1)
        for opcode in (
            "MUL",
            "DIV",
            "MOD",
            "AND",
            "OR",
            "XOR",
            "SHL",
            "SHR",
            "SDIV",
            "SMOD",
            "SAR",
        ):
            self.assertIn(opcode, asm)

    def test_signed_integer_ops_use_signed_evm_opcodes(self) -> None:
        source = """
int less(int a, int b) { return a < b; }
int greater(int a, int b) { return a > b; }
int divide(int a, int b) { return a / b; }
int modulo(int a, int b) { return a % b; }
int sar(int a) { return a >> 1; }
"""
        result = self._compile(source)
        asm = generate_evm_asm(result)
        bytecode = generate_evm_bytecode(result)

        less = _MiniEvm(bytecode, _calldata("less(int32,int32)", _word(-2), 1)).run()
        greater = _MiniEvm(bytecode, _calldata("greater(int32,int32)", _word(-2), 1)).run()
        divided = _MiniEvm(bytecode, _calldata("divide(int32,int32)", _word(-7), 3)).run()
        remainder = _MiniEvm(bytecode, _calldata("modulo(int32,int32)", _word(-7), 3)).run()
        shifted = _MiniEvm(bytecode, _calldata("sar(int32)", _word(-3))).run()

        self.assertEqual(int.from_bytes(less, "big"), 1)
        self.assertEqual(int.from_bytes(greater, "big"), 0)
        self.assertEqual(_signed_word_value(divided), -2)
        self.assertEqual(_signed_word_value(remainder), -1)
        self.assertEqual(_signed_word_value(shifted), -2)
        self.assertIn("SLT", asm)
        self.assertIn("SGT", asm)
        self.assertIn("SDIV", asm)
        self.assertIn("SMOD", asm)
        self.assertIn("SAR", asm)

    def test_runtime_binary_literal_and_pointer_variants_execute(self) -> None:
        source = """
typedef __evm_uint256 uint256;

uint256 compare_bits(uint256 a, uint256 b)
{
  uint256 result = 0;
  if (a != b) result += 1;
  if (a <= b) result += 2;
  if (a >= b) result += 4;
  result += (a | b) * 10;
  result += (a ^ b) * 100;
  return result;
}

int signed_compare(int a, int b)
{
  int result = 0;
  if (a <= b) result += 1;
  if (a >= b) result += 2;
  return result;
}

uint256 pointer_right_sub(void)
{
  uint256 values[4] = {3, 5, 7, 11};
  uint256 *ptr = &values[2];
  ptr = ptr - 1;
  return *ptr;
}

uint256 string_expr(void)
{
  char *p = "AZ";
  return ((uint256)p[0]) * 100 + (uint256)p[1];
}

uint256 scalar_compound(void) { return (uint256){9}; }

uint256 array_compound(void)
{
  uint256 *p = (uint256[2]){4, 5};
  return p[0] * 10 + p[1];
}
"""
        result = self._compile(source)
        asm = generate_evm_asm(result)
        bytecode = generate_evm_bytecode(result)

        compared = _MiniEvm(bytecode, _calldata("compare_bits(uint256,uint256)", 3, 5)).run()
        signed = _MiniEvm(bytecode, _calldata("signed_compare(int32,int32)", _word(-2), 1)).run()
        pointer = _MiniEvm(bytecode, _calldata("pointer_right_sub()")).run()
        string = _MiniEvm(bytecode, _calldata("string_expr()")).run()
        scalar = _MiniEvm(bytecode, _calldata("scalar_compound()")).run()
        array = _MiniEvm(bytecode, _calldata("array_compound()")).run()

        self.assertEqual(int.from_bytes(compared, "big"), 673)
        self.assertEqual(_signed_word_value(signed), 1)
        self.assertEqual(int.from_bytes(pointer, "big"), 5)
        self.assertEqual(int.from_bytes(string, "big"), 6590)
        self.assertEqual(int.from_bytes(scalar, "big"), 9)
        self.assertEqual(int.from_bytes(array, "big"), 45)
        for opcode in ("EQ", "GT", "LT", "ISZERO", "OR", "XOR", "SUB"):
            self.assertIn(opcode, asm)

    def test_runtime_unary_ops_emit_value_pop_and_bitwise_paths(self) -> None:
        source = """
typedef __evm_uint256 uint256;

uint256 unsigned_unary(uint256 value)
{
  return +value + (!value) * 100 + ((~value) & 255);
}

int signed_negate(int value)
{
  return -value;
}
"""
        result = self._compile(source)
        asm = generate_evm_asm(result)
        bytecode = generate_evm_bytecode(result)

        zero = _MiniEvm(bytecode, _calldata("unsigned_unary(uint256)", 0)).run()
        nonzero = _MiniEvm(bytecode, _calldata("unsigned_unary(uint256)", 0xF0)).run()
        negated = _MiniEvm(bytecode, _calldata("signed_negate(int32)", 7)).run()

        self.assertEqual(int.from_bytes(zero, "big"), 355)
        self.assertEqual(int.from_bytes(nonzero, "big"), 255)
        self.assertEqual(_signed_word_value(negated), -7)
        self.assertIn("ISZERO", asm)
        self.assertIn("NOT", asm)
        self.assertIn("SUB", asm)

    def test_integer_conversions_truncate_sign_extend_and_normalize_bool(self) -> None:
        source = """
unsigned char narrow_cast(unsigned int value) { return (unsigned char)value; }
signed char signed_cast(unsigned int value) { return (signed char)value; }
_Bool bool_cast(unsigned int value) { return (_Bool)value; }
unsigned char narrow_local(unsigned int value) { unsigned char local = value; return local; }
unsigned char narrow_assign(unsigned int value)
{
  unsigned char local;
  local = value;
  return local;
}
unsigned int wrap_add(unsigned int value) { return value + 1; }
unsigned int compare_wrapped(unsigned int value) { return value + 1 == 0; }
"""
        result = self._compile(source)
        asm = generate_evm_asm(result)
        bytecode = generate_evm_bytecode(result)

        narrow = _MiniEvm(bytecode, _calldata("narrow_cast(uint32)", 0x1234)).run()
        signed = _MiniEvm(bytecode, _calldata("signed_cast(uint32)", 0xFF)).run()
        bool_zero = _MiniEvm(bytecode, _calldata("bool_cast(uint32)", 0)).run()
        bool_nonzero = _MiniEvm(bytecode, _calldata("bool_cast(uint32)", 0x100)).run()
        local = _MiniEvm(bytecode, _calldata("narrow_local(uint32)", 0x1234)).run()
        assigned = _MiniEvm(bytecode, _calldata("narrow_assign(uint32)", 0x1234)).run()
        wrapped = _MiniEvm(bytecode, _calldata("wrap_add(uint32)", 0xFFFFFFFF)).run()
        compared = _MiniEvm(bytecode, _calldata("compare_wrapped(uint32)", 0xFFFFFFFF)).run()

        self.assertEqual(int.from_bytes(narrow, "big"), 0x34)
        self.assertEqual(_signed_word_value(signed), -1)
        self.assertEqual(int.from_bytes(bool_zero, "big"), 0)
        self.assertEqual(int.from_bytes(bool_nonzero, "big"), 1)
        self.assertEqual(int.from_bytes(local, "big"), 0x34)
        self.assertEqual(int.from_bytes(assigned, "big"), 0x34)
        self.assertEqual(int.from_bytes(wrapped, "big"), 0)
        self.assertEqual(int.from_bytes(compared, "big"), 1)
        self.assertIn("SIGNEXTEND", asm)

    def test_static_helper_function_calls_preserve_caller_locals(self) -> None:
        source = """
static unsigned int scale(unsigned int value)
{
  unsigned int scratch = value * 2;
  return scratch + 1;
}

unsigned int use_helper(unsigned int value)
{
  unsigned int keep = 5;
  return scale(value) + keep;
}
"""
        result = self._compile(source)

        asm = generate_evm_asm(result)
        bytecode = generate_evm_bytecode(result)
        returned = _MiniEvm(bytecode, _calldata("use_helper(uint32)", 3)).run()

        self.assertEqual(int.from_bytes(returned, "big"), 12)
        self.assertIn("internal_scale", asm)
        self.assertIn(f"PUSH4 0x{evm_selector('use_helper(uint32)'):08x}", asm)
        self.assertNotIn(f"PUSH4 0x{evm_selector('scale(uint32)'):08x}", asm)

    def test_block_scope_function_prototype_does_not_allocate_local_storage(self) -> None:
        source = """
typedef __evm_uint256 uint256;

uint256 plus_one(uint256 value)
{
  return value + 1;
}

uint256 use_helper(uint256 value)
{
  uint256 plus_one(uint256);
  uint256 keep = 5;
  return plus_one(value) + keep;
}
"""
        result = self._compile(source)

        bytecode = generate_evm_bytecode(result)
        returned = _MiniEvm(bytecode, _calldata("use_helper(uint256)", 7)).run()

        self.assertEqual(int.from_bytes(returned, "big"), 13)

    def test_file_scope_function_prototype_does_not_allocate_storage_slot(self) -> None:
        source = """
typedef __evm_uint256 uint256;

uint256 helper(uint256 value);

uint256 helper(uint256 value)
{
  return value + 2;
}

uint256 use_helper(uint256 value)
{
  return helper(value);
}
"""
        result = self._compile(source)

        asm = generate_evm_asm(result)
        bytecode = generate_evm_bytecode(result)
        returned = _MiniEvm(bytecode, _calldata("use_helper(uint256)", 7)).run()

        self.assertEqual(int.from_bytes(returned, "big"), 9)
        self.assertIn("internal_helper", asm)
        self.assertNotIn("SSTORE", asm)

    def test_internal_helper_can_return_word_pointer(self) -> None:
        source = """
typedef __evm_uint256 uint256;

static uint256 *skip_first(uint256 *values)
{
  return values + 1;
}

uint256 second(uint256 *values)
{
  return *skip_first(values);
}
"""
        result = self._compile(source)

        bytecode = generate_evm_bytecode(result)
        returned = _MiniEvm(
            bytecode,
            _dynamic_uint256_array_calldata("second(uint256[])", (11, 22, 33)),
        ).run()

        self.assertEqual(int.from_bytes(returned, "big"), 22)

    def test_exported_pointer_return_reports_evm_diagnostic(self) -> None:
        source = """
typedef __evm_uint256 uint256;

uint256 *bad(uint256 *values)
{
  return values;
}
"""
        result = self._compile(source)

        with self.assertRaises(Exception) as error:
            generate_evm_bytecode(result)

        self.assertEqual(error.exception.diagnostic.code, "XCC-EVM-0001")

    def test_sizeof_and_alignof_use_evm_word_object_layout_without_side_effects(self) -> None:
        source = """
typedef __evm_uint256 uint256;

uint256 marker;

uint256 sizes(void)
{
  uint256 values[3];
  marker = 7;
  return sizeof(values) + sizeof(values[0]) + sizeof(uint256 *) +
         _Alignof(unsigned int) + sizeof(marker = 99) + marker;
}

uint256 anonymous_record_size(void)
{
  return sizeof(struct { uint256 left; uint256 right; });
}

uint256 anonymous_record_value(void)
{
  struct { uint256 left; uint256 right; } value = {2, 3};
  return value.left * 10 + value.right;
}

uint256 get_marker(void) { return marker; }

#pragma pack(push, 4)
struct Packed { uint256 first; uint256 second; };
#pragma pack(pop)

uint256 packed_layout(void)
{
  return sizeof(struct Packed) + _Alignof(struct Packed) +
         __builtin_offsetof(struct Packed, second);
}
"""
        result = self._compile(source)

        bytecode = generate_evm_bytecode(result)
        storage: dict[int, int] = {}
        returned = _MiniEvm(bytecode, _calldata("sizes()"), storage).run()
        anonymous_size = _MiniEvm(bytecode, _calldata("anonymous_record_size()"), storage).run()
        anonymous_value = _MiniEvm(bytecode, _calldata("anonymous_record_value()"), storage).run()
        packed_layout = _MiniEvm(bytecode, _calldata("packed_layout()"), storage).run()
        marker = _MiniEvm(bytecode, _calldata("get_marker()"), storage).run()

        self.assertEqual(int.from_bytes(returned, "big"), 231)
        self.assertEqual(int.from_bytes(anonymous_size, "big"), 64)
        self.assertEqual(int.from_bytes(anonymous_value, "big"), 23)
        self.assertEqual(int.from_bytes(packed_layout, "big"), 100)
        self.assertEqual(int.from_bytes(marker, "big"), 7)

    def test_array_bound_sizeof_uses_same_evm_layout_as_backend_storage(self) -> None:
        source = """
typedef __evm_uint256 uint256;

uint256 array_size(void)
{
  char values[sizeof(int)];
  return sizeof(values);
}
"""
        bytecode = generate_evm_bytecode(self._compile(source))

        returned = _MiniEvm(bytecode, _calldata("array_size()")).run()

        self.assertEqual(int.from_bytes(returned, "big"), 1024)

    def test_builtin_offsetof_uses_evm_word_object_layout(self) -> None:
        source = """
typedef __evm_uint256 uint256;

struct Inner {
  uint256 first;
  uint256 second;
};

struct Outer {
  uint256 tag;
  struct Inner inner;
  uint256 tail;
};

uint256 offsets(void)
{
  return __builtin_offsetof(struct Outer, inner) +
         __builtin_offsetof(struct Outer, inner.second) +
         __builtin_offsetof(struct Outer, tail);
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)

        returned = _MiniEvm(bytecode, _calldata("offsets()")).run()

        self.assertEqual(int.from_bytes(returned, "big"), 192)

    def test_type_compat_and_generic_selection_lower_to_constants(self) -> None:
        source = """
typedef __evm_uint256 uint256;
typedef uint256 word;

uint256 marker;

uint256 type_compat(void)
{
  return __builtin_types_compatible_p(word, __evm_uint256) * 10 +
         __builtin_types_compatible_p(unsigned int, int);
}

uint256 generic_uint(uint256 value)
{
  return _Generic(value, uint256: 11, default: 22);
}

uint256 generic_default(unsigned int value)
{
  return _Generic(value, uint256: 11, default: 22);
}

uint256 generic_control_is_not_evaluated(void)
{
  marker = 0;
  return _Generic(marker = 7, uint256: marker + 1, default: 99);
}

uint256 get_marker(void) { return marker; }
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)
        storage: dict[int, int] = {}

        compatible = _MiniEvm(bytecode, _calldata("type_compat()"), storage).run()
        selected = _MiniEvm(bytecode, _calldata("generic_uint(uint256)", 5), storage).run()
        default = _MiniEvm(bytecode, _calldata("generic_default(uint32)", 5), storage).run()
        skipped = _MiniEvm(
            bytecode,
            _calldata("generic_control_is_not_evaluated()"),
            storage,
        ).run()
        marker = _MiniEvm(bytecode, _calldata("get_marker()"), storage).run()

        self.assertEqual(int.from_bytes(compatible, "big"), 10)
        self.assertEqual(int.from_bytes(selected, "big"), 11)
        self.assertEqual(int.from_bytes(default, "big"), 22)
        self.assertEqual(int.from_bytes(skipped, "big"), 1)
        self.assertEqual(int.from_bytes(marker, "big"), 0)

    def test_statement_expression_returns_last_expression_value(self) -> None:
        source = """
typedef __evm_uint256 uint256;

uint256 marker;

uint256 compute(uint256 value)
{
  return ({
    uint256 tmp = value + 2;
    tmp *= 3;
    tmp + 1;
  });
}

uint256 side_effect(void)
{
  marker = 0;
  return ({
    marker = 4;
    marker + 1;
  });
}

uint256 get_marker(void) { return marker; }
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)
        storage: dict[int, int] = {}

        computed = _MiniEvm(bytecode, _calldata("compute(uint256)", 5), storage).run()
        side_effect = _MiniEvm(bytecode, _calldata("side_effect()"), storage).run()
        marker = _MiniEvm(bytecode, _calldata("get_marker()"), storage).run()

        self.assertEqual(int.from_bytes(computed, "big"), 22)
        self.assertEqual(int.from_bytes(side_effect, "big"), 5)
        self.assertEqual(int.from_bytes(marker, "big"), 4)

    def test_goto_and_labels_execute_direct_jumps(self) -> None:
        source = """
typedef __evm_uint256 uint256;

uint256 jump(uint256 value)
{
  uint256 acc = 0;
  goto start;
skipped:
  acc = 99;
start:
  acc += 5;
  if (value) goto done;
  acc += 7;
done:
  return acc;
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)

        zero = _MiniEvm(bytecode, _calldata("jump(uint256)", 0)).run()
        nonzero = _MiniEvm(bytecode, _calldata("jump(uint256)", 1)).run()

        self.assertEqual(int.from_bytes(zero, "big"), 12)
        self.assertEqual(int.from_bytes(nonzero, "big"), 5)

    def test_label_addresses_and_indirect_goto_execute_jumps(self) -> None:
        source = """
typedef __evm_uint256 uint256;

uint256 indirect(uint256 value)
{
  void *target = value ? &&nonzero : &&zero;
  goto *target;
zero:
  return 10;
nonzero:
  return 20;
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)

        zero = _MiniEvm(bytecode, _calldata("indirect(uint256)", 0)).run()
        nonzero = _MiniEvm(bytecode, _calldata("indirect(uint256)", 1)).run()

        self.assertEqual(int.from_bytes(zero, "big"), 10)
        self.assertEqual(int.from_bytes(nonzero, "big"), 20)

    def test_compound_literals_use_word_memory_storage(self) -> None:
        source = """
typedef __evm_uint256 uint256;

uint256 scalar_literal(void)
{
  return (uint256){7};
}

uint256 array_literal(void)
{
  uint256 *values = (uint256[3]){2, 4, 8};
  return values[0] + values[1] + values[2];
}

uint256 assign_literal(void)
{
  return ((uint256){3} = 9);
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)

        scalar = _MiniEvm(bytecode, _calldata("scalar_literal()")).run()
        array = _MiniEvm(bytecode, _calldata("array_literal()")).run()
        assigned = _MiniEvm(bytecode, _calldata("assign_literal()")).run()

        self.assertEqual(int.from_bytes(scalar, "big"), 7)
        self.assertEqual(int.from_bytes(array, "big"), 14)
        self.assertEqual(int.from_bytes(assigned, "big"), 9)

    def test_string_literals_initialize_word_char_storage(self) -> None:
        source = r"""
typedef __evm_uint256 uint256;

uint256 array_init(void)
{
  char text[4] = "A\nB";
  return text[0] + text[1] + text[2] + text[3];
}

uint256 pointer_literal(void)
{
  char *text = "AZ";
  return text[0] + text[1] + text[2];
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)

        array = _MiniEvm(bytecode, _calldata("array_init()")).run()
        pointer = _MiniEvm(bytecode, _calldata("pointer_literal()")).run()

        self.assertEqual(int.from_bytes(array, "big"), 141)
        self.assertEqual(int.from_bytes(pointer, "big"), 155)

    def test_record_initializers_and_compound_literals_use_word_storage(self) -> None:
        source = """
typedef __evm_uint256 uint256;

struct Pair {
  uint256 left;
  uint256 right;
};

uint256 local_record(void)
{
  struct Pair pair = {3, 5};
  return pair.left * 10 + pair.right;
}

uint256 omitted_member_zeroes(void)
{
  struct Pair pair = {7};
  return pair.left * 10 + pair.right;
}

uint256 record_literal(void)
{
  return ((struct Pair){11, 13}).right;
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)

        local = _MiniEvm(bytecode, _calldata("local_record()")).run()
        omitted = _MiniEvm(bytecode, _calldata("omitted_member_zeroes()")).run()
        literal = _MiniEvm(bytecode, _calldata("record_literal()")).run()

        self.assertEqual(int.from_bytes(local, "big"), 35)
        self.assertEqual(int.from_bytes(omitted, "big"), 70)
        self.assertEqual(int.from_bytes(literal, "big"), 13)

    def test_internal_helper_accepts_record_parameter_by_value(self) -> None:
        source = """
typedef __evm_uint256 uint256;

struct Pair {
  uint256 left;
  uint256 right;
};

static uint256 sum_pair(struct Pair pair)
{
  return pair.left * 10 + pair.right;
}

uint256 call_helper(void)
{
  struct Pair pair = {4, 7};
  uint256 result = sum_pair(pair);
  pair.right = 99;
  return result;
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)

        returned = _MiniEvm(bytecode, _calldata("call_helper()")).run()

        self.assertEqual(int.from_bytes(returned, "big"), 47)

    def test_internal_helper_returns_record_by_value(self) -> None:
        source = """
typedef __evm_uint256 uint256;

struct Pair {
  uint256 left;
  uint256 right;
};

static struct Pair make_pair(uint256 left, uint256 right)
{
  return (struct Pair){left, right};
}

uint256 call_helper(void)
{
  struct Pair pair = make_pair(4, 7);
  return pair.left * 10 + pair.right;
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)

        returned = _MiniEvm(bytecode, _calldata("call_helper()")).run()

        self.assertEqual(int.from_bytes(returned, "big"), 47)

    def test_internal_helper_record_return_flows_through_assignment_and_fnptr(self) -> None:
        source = """
typedef __evm_uint256 uint256;

struct Pair {
  uint256 left;
  uint256 right;
};

typedef struct Pair (*Factory)(uint256, uint256);

static struct Pair make_pair(uint256 left, uint256 right)
{
  return (struct Pair){left, right};
}

uint256 call_helper(void)
{
  struct Pair pair = {1, 2};
  Factory factory = make_pair;
  pair = make_pair(4, 7);
  return pair.left * 100 + pair.right * 10 + factory(2, 3).right;
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)

        returned = _MiniEvm(bytecode, _calldata("call_helper()")).run()

        self.assertEqual(int.from_bytes(returned, "big"), 473)

    def test_union_members_alias_word_storage_slots(self) -> None:
        source = """
typedef __evm_uint256 uint256;

union Word {
  uint256 scalar;
  uint256 cells[2];
};

uint256 local_union(void)
{
  union Word word = {.scalar = 7};
  uint256 initial = word.cells[0];
  word.cells[1] = 5;
  word.cells[0] = 9;
  return initial * 1000 + word.scalar * 100 + word.cells[1] * 10 + sizeof(word) / 32;
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)

        returned = _MiniEvm(bytecode, _calldata("local_union()")).run()

        self.assertEqual(int.from_bytes(returned, "big"), 7952)

    def test_anonymous_union_members_use_enclosing_record_slots(self) -> None:
        source = """
typedef __evm_uint256 uint256;

struct Obj {
  union {
    uint256 tag;
    uint256 alt;
  };
  uint256 value;
};

uint256 local_anonymous_union(void)
{
  struct Obj obj;
  obj.tag = 7;
  obj.value = 3;
  obj.alt += 2;
  return obj.tag * 10 + obj.value;
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)

        returned = _MiniEvm(bytecode, _calldata("local_anonymous_union()")).run()

        self.assertEqual(int.from_bytes(returned, "big"), 93)

    def test_anonymous_union_member_position_initializer_uses_record_slot(self) -> None:
        source = """
typedef __evm_uint256 uint256;

struct Obj {
  union {
    uint256 tag;
    uint256 alt;
  };
  uint256 value;
};

uint256 local_anonymous_union_init(void)
{
  struct Obj obj = {{7}, 3};
  return obj.alt * 10 + obj.value;
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)

        returned = _MiniEvm(bytecode, _calldata("local_anonymous_union_init()")).run()

        self.assertEqual(int.from_bytes(returned, "big"), 73)

    def test_local_record_bit_fields_mask_values_in_word_slots(self) -> None:
        source = """
typedef __evm_uint256 uint256;

struct Flags {
  unsigned int low : 4;
  unsigned int high : 4;
  uint256 value;
};

uint256 local_bit_fields(uint256 input)
{
  struct Flags flags = {0};
  flags.low = input;
  flags.high = 0xf;
  flags.value = 9;
  flags.low += 1;
  return flags.low * 1000 + flags.high * 100 + flags.value + sizeof(flags) / 32;
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)

        returned = _MiniEvm(bytecode, _calldata("local_bit_fields(uint256)", 0x23)).run()

        self.assertEqual(int.from_bytes(returned, "big"), 5512)

    def test_local_record_unnamed_bit_fields_do_not_block_initializers(self) -> None:
        source = """
typedef __evm_uint256 uint256;

struct Flags {
  unsigned int low : 4;
  unsigned int : 0;
  unsigned int high : 4;
  uint256 value;
};

uint256 local_unnamed_bit_field(void)
{
  struct Flags flags = {0x23, 0x25, 7};
  flags.low += 1;
  return flags.low * 1000 + flags.high * 100 + flags.value + sizeof(flags) / 32;
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)

        returned = _MiniEvm(bytecode, _calldata("local_unnamed_bit_field()")).run()

        self.assertEqual(int.from_bytes(returned, "big"), 4510)

    def test_designated_local_initializers_use_word_storage_offsets(self) -> None:
        source = """
typedef __evm_uint256 uint256;

struct Pair {
  uint256 left;
  uint256 right;
};

struct Box {
  struct Pair items[2];
  uint256 tail;
};

uint256 local_designators(void)
{
  uint256 local[4] = {[3] = 8, [1] = 4};
  struct Pair pair = {.right = 7, .left = 6};
  return local[1] + local[3] * 10 + pair.left * 100 + pair.right * 1000;
}

uint256 range_and_continuation(void)
{
  uint256 values[5] = {[1 ... 2] = 3, 7, [0] = 1};
  return values[0] + values[1] * 10 + values[2] * 100 + values[3] * 1000;
}

uint256 nested_designators(void)
{
  struct Box box = {.items[1].right = 9, .items[0].left = 2, .tail = 7};
  return box.items[0].left +
         box.items[0].right * 10 +
         box.items[1].left * 100 +
         box.items[1].right * 1000 +
         box.tail * 10000;
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)

        returned = _MiniEvm(bytecode, _calldata("local_designators()")).run()
        ranged = _MiniEvm(bytecode, _calldata("range_and_continuation()")).run()
        nested = _MiniEvm(bytecode, _calldata("nested_designators()")).run()

        self.assertEqual(int.from_bytes(returned, "big"), 7684)
        self.assertEqual(int.from_bytes(ranged, "big"), 7331)
        self.assertEqual(int.from_bytes(nested, "big"), 79002)

    def test_record_assignment_copies_word_storage_slots(self) -> None:
        source = """
typedef __evm_uint256 uint256;

struct Pair {
  uint256 left;
  uint256 right;
};

struct Pair saved;

uint256 copy_local(void)
{
  struct Pair source = {2, 3};
  struct Pair target = {0};
  target = source;
  source.right = 9;
  target = (struct Pair){target.left + 5, target.right + 6};
  return target.left * 10 + target.right;
}

uint256 copy_to_storage(void)
{
  struct Pair source = {4, 6};
  saved = source;
  source.right = 99;
  return saved.left * 10 + saved.right;
}

uint256 copy_from_storage(void)
{
  struct Pair target = {1, 1};
  target = saved;
  return target.left * 10 + target.right;
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)
        storage: dict[int, int] = {}

        local = _MiniEvm(bytecode, _calldata("copy_local()"), storage).run()
        stored = _MiniEvm(bytecode, _calldata("copy_to_storage()"), storage).run()
        loaded = _MiniEvm(bytecode, _calldata("copy_from_storage()"), storage).run()

        self.assertEqual(int.from_bytes(local, "big"), 79)
        self.assertEqual(int.from_bytes(stored, "big"), 46)
        self.assertEqual(int.from_bytes(loaded, "big"), 46)

    def test_function_pointer_calls_dispatch_to_internal_functions(self) -> None:
        source = """
typedef __evm_uint256 uint256;

uint256 plus_one(uint256 value)
{
  return value + 1;
}

uint256 times_three(uint256 value)
{
  return value * 3;
}

uint256 dispatch(uint256 flag, uint256 value)
{
  uint256 (*fn)(uint256) = flag ? plus_one : times_three;
  return fn(value) * 10 + (*fn)(2);
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)

        selected_first = _MiniEvm(bytecode, _calldata("dispatch(uint256,uint256)", 1, 4)).run()
        selected_second = _MiniEvm(bytecode, _calldata("dispatch(uint256,uint256)", 0, 4)).run()

        self.assertEqual(int.from_bytes(selected_first, "big"), 53)
        self.assertEqual(int.from_bytes(selected_second, "big"), 126)

    def test_function_pointer_can_use_explicit_function_address(self) -> None:
        source = """
typedef __evm_uint256 uint256;

uint256 times_three(uint256 value)
{
  return value * 3;
}

uint256 dispatch(uint256 value)
{
  uint256 (*fn)(uint256) = &times_three;
  return fn(value);
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)

        returned = _MiniEvm(bytecode, _calldata("dispatch(uint256)", 7)).run()

        self.assertEqual(int.from_bytes(returned, "big"), 21)

    def test_internal_helper_can_return_function_pointer_for_indirect_call(self) -> None:
        source = """
typedef __evm_uint256 uint256;
typedef uint256 (*Fn)(uint256);

uint256 plus_one(uint256 value)
{
  return value + 1;
}

uint256 times_three(uint256 value)
{
  return value * 3;
}

static Fn choose(uint256 flag)
{
  return flag ? plus_one : times_three;
}

uint256 dispatch(uint256 flag, uint256 value)
{
  return choose(flag)(value);
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)

        selected_first = _MiniEvm(bytecode, _calldata("dispatch(uint256,uint256)", 1, 7)).run()
        selected_second = _MiniEvm(bytecode, _calldata("dispatch(uint256,uint256)", 0, 7)).run()

        self.assertEqual(int.from_bytes(selected_first, "big"), 8)
        self.assertEqual(int.from_bytes(selected_second, "big"), 21)

    def test_internal_helper_accepts_function_pointer_parameter(self) -> None:
        source = """
typedef __evm_uint256 uint256;
typedef uint256 (*Fn)(uint256);

uint256 plus_one(uint256 value)
{
  return value + 1;
}

uint256 times_three(uint256 value)
{
  return value * 3;
}

static uint256 apply(Fn fn, uint256 value)
{
  return fn(value);
}

uint256 dispatch(uint256 flag, uint256 value)
{
  Fn fn = flag ? plus_one : times_three;
  return apply(fn, value);
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)

        selected_first = _MiniEvm(bytecode, _calldata("dispatch(uint256,uint256)", 1, 7)).run()
        selected_second = _MiniEvm(bytecode, _calldata("dispatch(uint256,uint256)", 0, 7)).run()

        self.assertEqual(int.from_bytes(selected_first, "big"), 8)
        self.assertEqual(int.from_bytes(selected_second, "big"), 21)

    def test_void_function_pointer_call_returns_to_dispatch_join(self) -> None:
        source = """
typedef __evm_uint256 uint256;
typedef void (*Action)(uint256 *);

static void inc(uint256 *p)
{
  *p += 1;
}

static void add_two(uint256 *p)
{
  *p += 2;
}

static void apply(Action fn, uint256 *p)
{
  fn(p);
}

uint256 dispatch(uint256 flag)
{
  uint256 value = 10;
  Action fn = flag ? inc : add_two;
  apply(fn, &value);
  fn(&value);
  return value;
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)

        selected_first = _MiniEvm(bytecode, _calldata("dispatch(uint256)", 1)).run()
        selected_second = _MiniEvm(bytecode, _calldata("dispatch(uint256)", 0)).run()

        self.assertEqual(int.from_bytes(selected_first, "big"), 12)
        self.assertEqual(int.from_bytes(selected_second, "big"), 14)

    def test_function_pointer_call_copies_record_parameter_by_value(self) -> None:
        source = """
typedef __evm_uint256 uint256;

struct Pair {
  uint256 left;
  uint256 right;
};

typedef uint256 (*Fn)(struct Pair);

static uint256 adjust_pair(struct Pair pair)
{
  pair.right = pair.right + 1;
  return pair.left * 10 + pair.right;
}

static uint256 sum_pair(struct Pair pair)
{
  return pair.left * 10 + pair.right;
}

uint256 dispatch(uint256 flag)
{
  struct Pair pair = {4, 7};
  Fn fn = flag ? adjust_pair : sum_pair;
  uint256 result = fn(pair);
  return result * 100 + pair.right;
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)

        adjusted = _MiniEvm(bytecode, _calldata("dispatch(uint256)", 1)).run()
        summed = _MiniEvm(bytecode, _calldata("dispatch(uint256)", 0)).run()

        self.assertEqual(int.from_bytes(adjusted, "big"), 4807)
        self.assertEqual(int.from_bytes(summed, "big"), 4707)

    def test_switch_cases_default_break_and_fallthrough_execute_correctly(self) -> None:
        source = """
typedef __evm_uint256 uint256;

uint256 classify(uint256 value)
{
  uint256 acc = 1;
  switch (value) {
  case 0:
    acc += 10;
    break;
  case 1:
    acc += 20;
  case 2:
    acc += 30;
    break;
  default:
    acc += 40;
  }
  return acc;
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)

        zero = _MiniEvm(bytecode, _calldata("classify(uint256)", 0)).run()
        one = _MiniEvm(bytecode, _calldata("classify(uint256)", 1)).run()
        two = _MiniEvm(bytecode, _calldata("classify(uint256)", 2)).run()
        other = _MiniEvm(bytecode, _calldata("classify(uint256)", 9)).run()

        self.assertEqual(int.from_bytes(zero, "big"), 11)
        self.assertEqual(int.from_bytes(one, "big"), 51)
        self.assertEqual(int.from_bytes(two, "big"), 31)
        self.assertEqual(int.from_bytes(other, "big"), 41)

    def test_char_literals_lower_to_integer_values(self) -> None:
        source = r"""
typedef __evm_uint256 uint256;

uint256 ascii(void) { return 'A'; }
uint256 newline(void) { return '\n'; }
uint256 hex_escape(void) { return '\x41'; }
uint256 oct_escape(void) { return '\101'; }

uint256 select_char(uint256 value)
{
  switch (value) {
  case 'A':
    return 1;
  case '\n':
    return 2;
  default:
    return 3;
  }
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)

        ascii_value = _MiniEvm(bytecode, _calldata("ascii()")).run()
        newline = _MiniEvm(bytecode, _calldata("newline()")).run()
        hex_escape = _MiniEvm(bytecode, _calldata("hex_escape()")).run()
        oct_escape = _MiniEvm(bytecode, _calldata("oct_escape()")).run()
        selected_ascii = _MiniEvm(bytecode, _calldata("select_char(uint256)", 65)).run()
        selected_newline = _MiniEvm(bytecode, _calldata("select_char(uint256)", 10)).run()
        selected_other = _MiniEvm(bytecode, _calldata("select_char(uint256)", 66)).run()

        self.assertEqual(int.from_bytes(ascii_value, "big"), 65)
        self.assertEqual(int.from_bytes(newline, "big"), 10)
        self.assertEqual(int.from_bytes(hex_escape, "big"), 65)
        self.assertEqual(int.from_bytes(oct_escape, "big"), 65)
        self.assertEqual(int.from_bytes(selected_ascii, "big"), 1)
        self.assertEqual(int.from_bytes(selected_newline, "big"), 2)
        self.assertEqual(int.from_bytes(selected_other, "big"), 3)

    def test_enum_constants_lower_in_expressions_and_case_values(self) -> None:
        source = """
typedef __evm_uint256 uint256;

enum {
  BASE = 3,
  STEP = 4
};

uint256 enum_values(void)
{
  enum { LOCAL = 5 };
  uint256 value = BASE + LOCAL;
  switch (STEP) {
  case STEP:
    value += 10;
    break;
  default:
    value = 99;
  }
  return value;
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)

        returned = _MiniEvm(bytecode, _calldata("enum_values()")).run()

        self.assertEqual(int.from_bytes(returned, "big"), 18)

    def test_while_break_and_continue_execute_correctly(self) -> None:
        source = """
unsigned int sum(unsigned int n)
{
  unsigned int i = 0;
  unsigned int acc = 0;
  while (i < n) {
    i += 1;
    if (i == 3) continue;
    if (i == 5) break;
    acc += i;
  }
  return acc;
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)

        returned = _MiniEvm(bytecode, _calldata("sum(uint32)", 10)).run()

        self.assertEqual(int.from_bytes(returned, "big"), 7)

    def test_noop_declarations_and_null_statements_emit_no_code(self) -> None:
        source = """
typedef __evm_uint256 uint256;

uint256 noops(void)
{
  _Static_assert(1, "evm word");
  typedef uint256 word;
  ;
  word value = 3;
  if (0) {
    value = 99;
  } else {
    ;
  }
  while (value < 5) {
    ;
    value++;
  }
  return value;
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)

        returned = _MiniEvm(bytecode, _calldata("noops()")).run()

        self.assertEqual(int.from_bytes(returned, "big"), 5)

    def test_for_and_do_while_execute_correctly(self) -> None:
        source = """
unsigned int sum_for(unsigned int n)
{
  unsigned int acc = 0;
  for (unsigned int i = 0; i < n; i += 1) {
    acc += i;
  }
  return acc;
}

unsigned int at_least_once(unsigned int n)
{
  unsigned int i = 0;
  do {
    i += 1;
  } while (i < n);
  return i;
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)

        sum_returned = _MiniEvm(bytecode, _calldata("sum_for(uint32)", 5)).run()
        once_returned = _MiniEvm(bytecode, _calldata("at_least_once(uint32)", 0)).run()

        self.assertEqual(int.from_bytes(sum_returned, "big"), 10)
        self.assertEqual(int.from_bytes(once_returned, "big"), 1)

    def test_for_expression_init_and_void_post_execute_correctly(self) -> None:
        source = """
typedef __evm_uint256 uint256;

uint256 sum_expr_for(uint256 n)
{
  uint256 i;
  uint256 acc;
  for (i = 0, acc = 0; i < n; (void)(i += 1)) {
    acc += i;
  }
  return acc;
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)

        returned = _MiniEvm(bytecode, _calldata("sum_expr_for(uint256)", 5)).run()

        self.assertEqual(int.from_bytes(returned, "big"), 10)

    def test_environment_revert_and_log_builtins(self) -> None:
        source = """
unsigned int who(void) { return __builtin_evm_caller(); }
unsigned int paid(void) { return __builtin_evm_callvalue(); }
void fail(void) { __builtin_evm_revert(); }
void emit_zero(unsigned int value) { __builtin_evm_log0(value); }
void emit_one(unsigned int topic, unsigned int value) { __builtin_evm_log1(topic, value); }
void emit_two(unsigned int a, unsigned int b, unsigned int value)
{
  __builtin_evm_log2(a, b, value);
}
void emit_three(unsigned int a, unsigned int b, unsigned int c, unsigned int value)
{
  __builtin_evm_log3(a, b, c, value);
}
void emit_four(unsigned int a, unsigned int b, unsigned int c, unsigned int d, unsigned int value)
{
  __builtin_evm_log4(a, b, c, d, value);
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)
        asm = generate_evm_asm(result)

        caller_returned = _MiniEvm(bytecode, _calldata("who()"), caller=0x1234).run()
        paid_returned = _MiniEvm(bytecode, _calldata("paid()"), callvalue=99).run()
        log0_vm = _MiniEvm(bytecode, _calldata("emit_zero(uint32)", 0x55))
        log_vm = _MiniEvm(bytecode, _calldata("emit_one(uint32,uint32)", 0xAA, 0xBB))
        log2_vm = _MiniEvm(
            bytecode,
            _calldata("emit_two(uint32,uint32,uint32)", 0xA1, 0xA2, 0xCC),
        )
        log3_vm = _MiniEvm(
            bytecode,
            _calldata("emit_three(uint32,uint32,uint32,uint32)", 0xA1, 0xA2, 0xA3, 0xDD),
        )
        log4_vm = _MiniEvm(
            bytecode,
            _calldata(
                "emit_four(uint32,uint32,uint32,uint32,uint32)",
                0xA1,
                0xA2,
                0xA3,
                0xA4,
                0xEE,
            ),
        )

        log0_vm.run()
        log_vm.run()
        log2_vm.run()
        log3_vm.run()
        log4_vm.run()

        self.assertEqual(int.from_bytes(caller_returned, "big"), 0x1234)
        self.assertEqual(int.from_bytes(paid_returned, "big"), 99)
        self.assertEqual(log0_vm.logs, [((), (0x55).to_bytes(32, "big"))])
        self.assertEqual(log_vm.logs, [((0xAA,), (0xBB).to_bytes(32, "big"))])
        self.assertEqual(log2_vm.logs, [((0xA1, 0xA2), (0xCC).to_bytes(32, "big"))])
        self.assertEqual(log3_vm.logs, [((0xA1, 0xA2, 0xA3), (0xDD).to_bytes(32, "big"))])
        self.assertEqual(
            log4_vm.logs,
            [((0xA1, 0xA2, 0xA3, 0xA4), (0xEE).to_bytes(32, "big"))],
        )
        self.assertIn("CALLER", asm)
        self.assertIn("CALLVALUE", asm)
        self.assertIn("LOG0", asm)
        self.assertIn("LOG1", asm)
        self.assertIn("LOG2", asm)
        self.assertIn("LOG3", asm)
        self.assertIn("LOG4", asm)
        with self.assertRaisesRegex(AssertionError, "EVM reverted"):
            _MiniEvm(bytecode, _calldata("fail()")).run()

    def test_raw_revert_and_log_data_builtins_use_memory_ranges(self) -> None:
        source = """
typedef __evm_uint256 uint256;

void fail_data(void)
{
  uint256 data[1];
  data[0] = 0xAABB;
  __builtin_evm_revert_data((uint256 *)((uint256)data + 30), 2);
  __builtin_evm_stop();
}

void emit_data(void)
{
  uint256 data[2];
  uint256 *slice;
  data[0] = 0xAABB;
  data[1] = ((uint256)0xCCDD) << 240;
  slice = (uint256 *)((uint256)data + 30);
  __builtin_evm_log0_data(slice, 4);
  __builtin_evm_log1_data(0xA1, slice, 4);
  __builtin_evm_log2_data(0xA1, 0xA2, slice, 4);
  __builtin_evm_log3_data(0xA1, 0xA2, 0xA3, slice, 4);
  __builtin_evm_log4_data(0xA1, 0xA2, 0xA3, 0xA4, slice, 4);
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)
        asm = generate_evm_asm(result)
        log_vm = _MiniEvm(bytecode, _calldata("emit_data()"))

        with self.assertRaisesRegex(AssertionError, "aabb"):
            _MiniEvm(bytecode, _calldata("fail_data()")).run()
        log_vm.run()

        self.assertEqual(
            log_vm.logs,
            [
                ((), bytes.fromhex("aabbccdd")),
                ((0xA1,), bytes.fromhex("aabbccdd")),
                ((0xA1, 0xA2), bytes.fromhex("aabbccdd")),
                ((0xA1, 0xA2, 0xA3), bytes.fromhex("aabbccdd")),
                ((0xA1, 0xA2, 0xA3, 0xA4), bytes.fromhex("aabbccdd")),
            ],
        )
        self.assertIn("REVERT", asm)
        self.assertIn("LOG0", asm)
        self.assertIn("LOG4", asm)

    def test_environment_block_and_gas_builtins(self) -> None:
        source = """
typedef __evm_uint256 uint256;

uint256 env(void)
{
  return __builtin_evm_address()
       + __builtin_evm_origin() * 10
       + __builtin_evm_gasprice() * 100
       + __builtin_evm_coinbase() * 1000
       + __builtin_evm_timestamp() * 10000
       + __builtin_evm_number() * 100000
       + __builtin_evm_prevrandao() * 1000000
       + __builtin_evm_gaslimit() * 10000000
       + __builtin_evm_chainid() * 100000000
       + __builtin_evm_selfbalance() * 1000000000
       + __builtin_evm_basefee() * 10000000000
       + __builtin_evm_gas() * 100000000000;
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)
        asm = generate_evm_asm(result)
        returned = _MiniEvm(
            bytecode,
            _calldata("env()"),
            address=1,
            origin=2,
            gasprice=3,
            coinbase=4,
            timestamp=5,
            number=6,
            prevrandao=7,
            gaslimit=8,
            chainid=9,
            selfbalance=10,
            basefee=11,
            gas=12,
        ).run()

        self.assertEqual(int.from_bytes(returned, "big"), 1320987654321)
        self.assertIn("ADDRESS", asm)
        self.assertIn("ORIGIN", asm)
        self.assertIn("GASPRICE", asm)
        self.assertIn("COINBASE", asm)
        self.assertIn("TIMESTAMP", asm)
        self.assertIn("NUMBER", asm)
        self.assertIn("PREVRANDAO", asm)
        self.assertIn("GASLIMIT", asm)
        self.assertIn("CHAINID", asm)
        self.assertIn("SELFBALANCE", asm)
        self.assertIn("BASEFEE", asm)
        self.assertIn("    GAS\n", asm)

    def test_account_and_block_query_builtins(self) -> None:
        source = """
typedef __evm_uint256 uint256;
typedef __evm_address evm_address;

uint256 query(void)
{
  return __builtin_evm_balance((evm_address)0xA)
       + __builtin_evm_blockhash(7) * 10
       + __builtin_evm_extcodesize((evm_address)0xB) * 100
       + __builtin_evm_extcodehash((evm_address)0xC) * 1000;
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)
        asm = generate_evm_asm(result)
        returned = _MiniEvm(
            bytecode,
            _calldata("query()"),
            balances={0xA: 5},
            block_hashes={7: 6},
            code_sizes={0xB: 7},
            code_hashes={0xC: 8},
        ).run()

        self.assertEqual(int.from_bytes(returned, "big"), 8765)
        self.assertIn("BALANCE", asm)
        self.assertIn("BLOCKHASH", asm)
        self.assertIn("EXTCODESIZE", asm)
        self.assertIn("EXTCODEHASH", asm)

    def test_extcodecopy_builtin_copies_account_code_bytes(self) -> None:
        source = """
typedef __evm_uint256 uint256;
typedef __evm_address evm_address;

uint256 copy_external(void)
{
  uint256 buffer[1];
  __builtin_evm_extcodecopy((evm_address)0xB, buffer, 1, 2);
  return buffer[0] >> 240;
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)
        asm = generate_evm_asm(result)
        returned = _MiniEvm(
            bytecode,
            _calldata("copy_external()"),
            codes={0xB: bytes([0xAA, 0x12, 0x34, 0xBB])},
        ).run()

        self.assertEqual(int.from_bytes(returned, "big"), 0x1234)
        self.assertIn("EXTCODECOPY", asm)

    def test_keccak256_builtin_hashes_memory_ranges(self) -> None:
        source = """
typedef __evm_uint256 uint256;

uint256 hash_words(void)
{
  uint256 data[2];
  data[0] = 0x0102;
  data[1] = 0x0304;
  return __builtin_evm_keccak256(data, 64);
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)
        expected = int.from_bytes(
            evm.keccak256((0x0102).to_bytes(32, "big") + (0x0304).to_bytes(32, "big")),
            "big",
        )

        returned = _MiniEvm(bytecode, _calldata("hash_words()")).run()

        self.assertEqual(int.from_bytes(returned, "big"), expected)

    def test_modular_and_exponent_builtins_use_native_opcodes(self) -> None:
        source = """
typedef __evm_uint256 uint256;

uint256 modular_arithmetic(void)
{
  uint256 max = ~(uint256)0;
  return __builtin_evm_addmod(max, 5, 9) * 10000
       + __builtin_evm_mulmod(max, 3, 11) * 100
       + __builtin_evm_exp(3, 5);
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)
        asm = generate_evm_asm(result)

        returned = _MiniEvm(bytecode, _calldata("modular_arithmetic()")).run()

        self.assertEqual(int.from_bytes(returned, "big"), 20443)
        self.assertIn("ADDMOD", asm)
        self.assertIn("MULMOD", asm)
        self.assertIn("EXP", asm)

    def test_byte_mstore8_and_msize_builtins_use_native_opcodes(self) -> None:
        source = """
typedef __evm_uint256 uint256;

uint256 byte_memory(void)
{
  uint256 buffer[1];
  buffer[0] = 0;
  __builtin_evm_mstore8((uint256 *)((uint256)buffer + 31), 0xABCD);
  return __builtin_evm_byte(31, buffer[0]) * 1000000
       + __builtin_evm_byte(0, buffer[0]) * 1000
       + __builtin_evm_msize();
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)
        asm = generate_evm_asm(result)

        returned = _MiniEvm(bytecode, _calldata("byte_memory()")).run()

        self.assertEqual(int.from_bytes(returned, "big"), 205000224)
        self.assertIn("BYTE", asm)
        self.assertIn("MSTORE8", asm)
        self.assertIn("MSIZE", asm)

    def test_low_level_memory_signextend_and_pc_builtins_use_native_opcodes(self) -> None:
        source = """
typedef __evm_uint256 uint256;

uint256 raw_ops(void)
{
  uint256 buffer[1];
  __builtin_evm_mstore(buffer, 0x123456);
  return (__builtin_evm_mload(buffer) == 0x123456) * 1000
       + (__builtin_evm_signextend(0, 0x80) == ((uint256)0 - 128)) * 100
       + (__builtin_evm_pc() > 0);
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)
        asm = generate_evm_asm(result)

        returned = _MiniEvm(bytecode, _calldata("raw_ops()")).run()

        self.assertEqual(int.from_bytes(returned, "big"), 1101)
        self.assertIn("MLOAD", asm)
        self.assertIn("MSTORE", asm)
        self.assertIn("SIGNEXTEND", asm)
        self.assertIn("PC", asm)

    def test_transient_mcopy_and_blob_builtins_use_native_opcodes(self) -> None:
        source = """
typedef __evm_uint256 uint256;

uint256 transient_blob(void)
{
  uint256 src[1];
  uint256 dst[1];
  src[0] = ((uint256)0x12 << 248) + ((uint256)0x34 << 240);
  __builtin_evm_mcopy(dst, src, 2);
  __builtin_evm_tstore(7, 9);
  return (__builtin_evm_mload(dst) >> 240) * 1000
       + __builtin_evm_tload(7) * 10
       + __builtin_evm_blobhash(2)
       + __builtin_evm_blobbasefee();
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)
        asm = generate_evm_asm(result)
        machine = _MiniEvm(
            bytecode,
            _calldata("transient_blob()"),
            blob_hashes={2: 4},
            blobbasefee=5,
        )

        returned = machine.run()

        self.assertEqual(int.from_bytes(returned, "big"), 4660099)
        self.assertEqual(machine.transient_storage[7], 9)
        self.assertIn("MCOPY", asm)
        self.assertIn("TSTORE", asm)
        self.assertIn("TLOAD", asm)
        self.assertIn("BLOBHASH", asm)
        self.assertIn("BLOBBASEFEE", asm)

    def test_terminal_return_stop_and_invalid_builtins_use_native_opcodes(self) -> None:
        source = """
typedef __evm_uint256 uint256;

uint256 raw_return(void)
{
  uint256 out[1];
  out[0] = 0x123;
  __builtin_evm_return(out, 32);
  return 9;
}

void halt(void)
{
  __builtin_evm_stop();
}

void early_return(void)
{
  return;
}

void trap(void)
{
  __builtin_evm_invalid();
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)
        asm = generate_evm_asm(result)

        returned = _MiniEvm(bytecode, _calldata("raw_return()")).run()
        halted = _MiniEvm(bytecode, _calldata("halt()")).run()
        early = _MiniEvm(bytecode, _calldata("early_return()")).run()

        self.assertEqual(int.from_bytes(returned, "big"), 0x123)
        self.assertEqual(halted, b"")
        self.assertEqual(early, b"")
        with self.assertRaisesRegex(AssertionError, "invalid opcode"):
            _MiniEvm(bytecode, _calldata("trap()")).run()
        self.assertIn("RETURN", asm)
        self.assertIn("STOP", asm)
        self.assertIn("INVALID", asm)

    def test_evm_uint256_and_address_abi_types(self) -> None:
        source = """
typedef __evm_uint256 uint256;
typedef __evm_address evm_address;

uint256 id(uint256 value) { return value; }
evm_address who(void) { return __builtin_evm_caller(); }
"""
        result = self._compile(source)
        asm = generate_evm_asm(result)
        bytecode = generate_evm_bytecode(result)
        large = (1 << 255) + 123

        id_returned = _MiniEvm(bytecode, _calldata("id(uint256)", large)).run()
        who_returned = _MiniEvm(bytecode, _calldata("who()"), caller=0xABCDEF).run()

        self.assertIn(f"PUSH4 0x{evm_selector('id(uint256)'):08x}", asm)
        self.assertEqual(int.from_bytes(id_returned, "big"), large)
        self.assertEqual(int.from_bytes(who_returned, "big"), 0xABCDEF)

    def test_unsupported_construct_reports_evm_diagnostic(self) -> None:
        result = self._compile("double bad(void) { return 1.0; }\n")

        with self.assertRaises(Exception) as error:
            generate_evm_asm(result)
        self.assertEqual(error.exception.diagnostic.code, "XCC-EVM-0001")

    def test_bytecode_can_be_written_as_hex_text(self) -> None:
        result = self._compile("unsigned int get(void) { return 7; }\n")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "contract.bin"
            path.write_text(generate_evm_bytecode(result) + "\n", encoding="utf-8")

            text = path.read_text(encoding="utf-8").strip()

        self.assertRegex(text, r"^[0-9a-f]+$")
        self.assertEqual(len(text) % 2, 0)

    def test_assembler_uses_push0_for_implicit_zero_constants(self) -> None:
        source = """
typedef __evm_uint256 uint256;

uint256 zero(void)
{
  return 0;
}
"""
        result = self._compile(source)
        asm = generate_evm_asm(result)
        bytecode = generate_evm_bytecode(result)

        returned = _MiniEvm(bytecode, _calldata("zero()")).run()

        self.assertEqual(int.from_bytes(returned, "big"), 0)
        self.assertIn("PUSH0", asm)
        self.assertIn("5f", bytecode)

    def test_memory_arrays_pointers_and_subscripts_execute_correctly(self) -> None:
        source = """
typedef __evm_uint256 uint256;

uint256 pick(void)
{
  uint256 values[3];
  uint256 *ptr = values;
  values[0] = 11;
  values[1] = 22;
  values[2] = 33;
  ptr += 1;
  *ptr += 5;
  return values[1] + *(values + 2);
}

uint256 pointer_diff(void)
{
  uint256 values[4];
  uint256 *left = &values[3];
  uint256 *right = &values[1];
  return left - right;
}
"""
        result = self._compile(source)

        bytecode = generate_evm_bytecode(result)
        returned = _MiniEvm(bytecode, _calldata("pick()")).run()
        diff = _MiniEvm(bytecode, _calldata("pointer_diff()")).run()

        self.assertEqual(int.from_bytes(returned, "big"), 60)
        self.assertEqual(int.from_bytes(diff, "big"), 2)

    def test_dynamic_uint256_array_abi_parameter_is_copied_to_memory(self) -> None:
        source = """
typedef __evm_uint256 uint256;

uint256 sum(uint256 *values, uint256 n)
{
  uint256 acc = 0;
  for (uint256 i = 0; i < n; i += 1) {
    acc += values[i];
  }
  return acc;
}
"""
        result = self._compile(source)

        asm = generate_evm_asm(result)
        bytecode = generate_evm_bytecode(result)
        returned = _MiniEvm(
            bytecode,
            _dynamic_uint256_array_calldata("sum(uint256[],uint256)", (5, 8, 13), 3),
        ).run()

        self.assertIn(f"PUSH4 0x{evm_selector('sum(uint256[],uint256)'):08x}", asm)
        self.assertEqual(int.from_bytes(returned, "big"), 26)

    def test_dynamic_narrow_integer_array_abi_elements_are_converted(self) -> None:
        source = """
typedef __evm_uint256 uint256;

uint256 first(unsigned int *values)
{
  return values[0];
}
"""
        result = self._compile(source)

        bytecode = generate_evm_bytecode(result)
        returned = _MiniEvm(
            bytecode,
            _dynamic_uint256_array_calldata("first(uint32[])", (0x100000001,)),
        ).run()

        self.assertEqual(int.from_bytes(returned, "big"), 1)

    def test_abi_decoder_reverts_on_truncated_calldata(self) -> None:
        source = """
typedef __evm_uint256 uint256;

uint256 id(uint256 value)
{
  return value;
}

uint256 sum(uint256 *values, uint256 n)
{
  uint256 acc = 0;
  for (uint256 i = 0; i < n; i += 1) {
    acc += values[i];
  }
  return acc;
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)
        truncated_dynamic = _dynamic_uint256_array_calldata(
            "sum(uint256[],uint256)",
            (5, 8),
            2,
        )[:-32]

        with self.assertRaisesRegex(AssertionError, "EVM reverted"):
            _MiniEvm(bytecode, _calldata("id(uint256)")).run()
        with self.assertRaisesRegex(AssertionError, "EVM reverted"):
            _MiniEvm(bytecode, truncated_dynamic).run()

    def test_abi_decoder_reverts_on_invalid_dynamic_offsets(self) -> None:
        source = """
typedef __evm_uint256 uint256;

uint256 sum(uint256 *values, uint256 n)
{
  uint256 acc = 0;
  for (uint256 i = 0; i < n; i += 1) {
    acc += values[i];
  }
  return acc;
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)
        selector = evm_selector("sum(uint256[],uint256)").to_bytes(4, "big")
        head_offset = selector + (0).to_bytes(32, "big") + (0).to_bytes(32, "big")
        misaligned_offset = (
            selector + (65).to_bytes(32, "big") + (0).to_bytes(32, "big") + b"\x00" * 33
        )

        with self.assertRaisesRegex(AssertionError, "EVM reverted"):
            _MiniEvm(bytecode, head_offset).run()
        with self.assertRaisesRegex(AssertionError, "EVM reverted"):
            _MiniEvm(bytecode, misaligned_offset).run()

    def test_raw_calldata_builtins_load_size_and_copy_bytes(self) -> None:
        source = """
typedef __evm_uint256 uint256;

uint256 raw(uint256 offset)
{
  uint256 buffer[1];
  __builtin_evm_calldatacopy(buffer, offset, 32);
  return __builtin_evm_calldatasize()
       + __builtin_evm_calldataload(offset)
       + buffer[0];
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)
        extra = 0x123
        calldata = _calldata("raw(uint256)", 36) + extra.to_bytes(32, "big")

        returned = _MiniEvm(bytecode, calldata).run()

        self.assertEqual(int.from_bytes(returned, "big"), 68 + extra + extra)

    def test_return_data_builtins_report_size_and_copy_bytes(self) -> None:
        source = """
typedef __evm_uint256 uint256;

uint256 returndata(void)
{
  uint256 buffer[1];
  __builtin_evm_returndatacopy(buffer, 1, 2);
  return __builtin_evm_returndatasize() * 0x10000 + (buffer[0] >> 240);
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)
        asm = generate_evm_asm(result)
        returned = _MiniEvm(
            bytecode,
            _calldata("returndata()"),
            return_data=bytes([0xAA, 0x12, 0x34, 0xBB, 0xCC]),
        ).run()

        self.assertEqual(int.from_bytes(returned, "big"), 0x51234)
        self.assertIn("RETURNDATASIZE", asm)
        self.assertIn("RETURNDATACOPY", asm)

    def test_call_builtin_copies_input_and_return_bytes(self) -> None:
        source = """
typedef __evm_uint256 uint256;
typedef __evm_address evm_address;

uint256 call_contract(void)
{
  uint256 input[1];
  uint256 output[1];
  input[0] = 0x010203;
  uint256 ok = __builtin_evm_call(50000, (evm_address)0xCAFE, 7, input, 32, output, 2);
  return ok * 0x10000 + (output[0] >> 240);
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)
        asm = generate_evm_asm(result)
        vm = _MiniEvm(
            bytecode,
            _calldata("call_contract()"),
            external_calls={0xCAFE: (1, bytes([0xAB, 0xCD, 0xEF]))},
        )

        returned = vm.run()

        self.assertEqual(int.from_bytes(returned, "big"), 0x1ABCD)
        self.assertEqual(
            vm.call_trace,
            [(50000, 0xCAFE, 7, (0x010203).to_bytes(32, "big"), 2)],
        )
        self.assertIn("    CALL\n", asm)

    def test_create_builtin_copies_initcode_and_returns_address(self) -> None:
        source = """
typedef __evm_uint256 uint256;
typedef __evm_address evm_address;

evm_address deploy_contract(void)
{
  uint256 initcode[1];
  initcode[0] = ((uint256)0x6001600055) << 216;
  return __builtin_evm_create(9, initcode, 5);
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)
        asm = generate_evm_asm(result)
        vm = _MiniEvm(bytecode, _calldata("deploy_contract()"), create_address=0xC0DE)

        returned = vm.run()

        self.assertEqual(int.from_bytes(returned, "big"), 0xC0DE)
        self.assertEqual(vm.create_trace, [(9, bytes.fromhex("6001600055"))])
        self.assertIn("CREATE", asm)

    def test_create2_builtin_copies_initcode_salt_and_returns_address(self) -> None:
        source = """
typedef __evm_uint256 uint256;
typedef __evm_address evm_address;

evm_address deploy_deterministic_contract(void)
{
  uint256 initcode[1];
  initcode[0] = ((uint256)0x6002600055) << 216;
  return __builtin_evm_create2(11, initcode, 5, 0x1234);
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)
        asm = generate_evm_asm(result)
        vm = _MiniEvm(
            bytecode,
            _calldata("deploy_deterministic_contract()"),
            create_address=0xC2C2,
        )

        returned = vm.run()

        self.assertEqual(int.from_bytes(returned, "big"), 0xC2C2)
        self.assertEqual(vm.create2_trace, [(11, bytes.fromhex("6002600055"), 0x1234)])
        self.assertIn("CREATE2", asm)

    def test_selfdestruct_builtin_records_beneficiary_and_halts(self) -> None:
        source = """
typedef __evm_address evm_address;

void terminate(void)
{
  __builtin_evm_selfdestruct((evm_address)0xBEEF);
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)
        asm = generate_evm_asm(result)
        vm = _MiniEvm(bytecode, _calldata("terminate()"))

        returned = vm.run()

        self.assertEqual(returned, b"")
        self.assertEqual(vm.selfdestruct_trace, [0xBEEF])
        self.assertIn("SELFDESTRUCT", asm)

    def test_callcode_builtin_copies_input_and_return_bytes(self) -> None:
        source = """
typedef __evm_uint256 uint256;
typedef __evm_address evm_address;

uint256 callcode_contract(void)
{
  uint256 input[1];
  uint256 output[1];
  input[0] = 0x0E0F;
  uint256 ok = __builtin_evm_callcode(22222, (evm_address)0xCA11, 13, input, 32, output, 2);
  return ok * 0x10000 + (output[0] >> 240);
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)
        asm = generate_evm_asm(result)
        vm = _MiniEvm(
            bytecode,
            _calldata("callcode_contract()"),
            external_calls={0xCA11: (1, bytes([0x22, 0x33, 0x44]))},
        )

        returned = vm.run()

        self.assertEqual(int.from_bytes(returned, "big"), 0x12233)
        self.assertEqual(
            vm.call_trace,
            [(22222, 0xCA11, 13, (0x0E0F).to_bytes(32, "big"), 2)],
        )
        self.assertIn("CALLCODE", asm)

    def test_staticcall_builtin_copies_input_and_return_bytes(self) -> None:
        source = """
typedef __evm_uint256 uint256;
typedef __evm_address evm_address;

uint256 static_query(void)
{
  uint256 input[1];
  uint256 output[1];
  input[0] = 0x0A0B;
  uint256 ok = __builtin_evm_staticcall(12345, (evm_address)0xBEEF, input, 32, output, 2);
  return ok * 0x10000 + (output[0] >> 240);
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)
        asm = generate_evm_asm(result)
        vm = _MiniEvm(
            bytecode,
            _calldata("static_query()"),
            external_calls={0xBEEF: (1, bytes([0x44, 0x55, 0x66]))},
        )

        returned = vm.run()

        self.assertEqual(int.from_bytes(returned, "big"), 0x14455)
        self.assertEqual(
            vm.call_trace,
            [(12345, 0xBEEF, 0, (0x0A0B).to_bytes(32, "big"), 2)],
        )
        self.assertIn("STATICCALL", asm)

    def test_delegatecall_builtin_copies_input_and_return_bytes(self) -> None:
        source = """
typedef __evm_uint256 uint256;
typedef __evm_address evm_address;

uint256 delegate_query(void)
{
  uint256 input[1];
  uint256 output[1];
  input[0] = 0x0C0D;
  uint256 ok = __builtin_evm_delegatecall(54321, (evm_address)0xD00D, input, 32, output, 2);
  return ok * 0x10000 + (output[0] >> 240);
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)
        asm = generate_evm_asm(result)
        vm = _MiniEvm(
            bytecode,
            _calldata("delegate_query()"),
            callvalue=11,
            external_calls={0xD00D: (1, bytes([0x77, 0x88, 0x99]))},
        )

        returned = vm.run()

        self.assertEqual(int.from_bytes(returned, "big"), 0x17788)
        self.assertEqual(
            vm.call_trace,
            [(54321, 0xD00D, 11, (0x0C0D).to_bytes(32, "big"), 2)],
        )
        self.assertIn("DELEGATECALL", asm)

    def test_runtime_code_builtins_report_size_and_copy_bytes(self) -> None:
        source = """
typedef __evm_uint256 uint256;

uint256 code_info(void)
{
  uint256 buffer[1];
  __builtin_evm_codecopy(buffer, 0, 1);
  return __builtin_evm_codesize() * 1000 + (buffer[0] >> 248);
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)
        expected = (len(bytes.fromhex(bytecode)) * 1000) + bytes.fromhex(bytecode)[0]

        returned = _MiniEvm(bytecode, _calldata("code_info()")).run()

        self.assertEqual(int.from_bytes(returned, "big"), expected)

    def test_dynamic_uint256_array_return_builtin_emits_abi_payload(self) -> None:
        source = """
typedef __evm_uint256 uint256;

void tail(uint256 *values, uint256 n)
{
  __builtin_evm_return_array(values + 1, n - 1);
}
"""
        result = self._compile(source)

        bytecode = generate_evm_bytecode(result)
        returned = _MiniEvm(
            bytecode,
            _dynamic_uint256_array_calldata("tail(uint256[],uint256)", (3, 5, 8), 3),
        ).run()

        self.assertEqual(_decode_uint256_array_return(returned), (5, 8))

    def test_initcode_initializes_storage_globals_and_returns_runtime(self) -> None:
        source = """
typedef __evm_uint256 uint256;

uint256 counter = 7;

uint256 get(void) { return counter; }
"""
        result = self._compile(source)

        self.assertTrue(hasattr(evm, "generate_evm_initcode"))
        initcode = evm.generate_evm_initcode(result)
        storage: dict[int, int] = {}
        runtime = _MiniEvm(initcode, b"", storage).run()
        returned = _MiniEvm(runtime.hex(), _calldata("get()"), storage).run()

        self.assertEqual(storage[0], 7)
        self.assertEqual(int.from_bytes(returned, "big"), 7)

    def test_initcode_initializes_aggregate_storage_globals(self) -> None:
        source = """
typedef __evm_uint256 uint256;

struct Pair {
  uint256 first;
  uint256 second;
};

struct Pair pair = {3, 5};
uint256 values[3] = {2, 4, 8};

uint256 get(void)
{
  return pair.first * 100 + pair.second * 10 + values[2];
}
"""
        result = self._compile(source)

        initcode = evm.generate_evm_initcode(result)
        storage: dict[int, int] = {}
        runtime = _MiniEvm(initcode, b"", storage).run()
        returned = _MiniEvm(runtime.hex(), _calldata("get()"), storage).run()

        self.assertEqual(storage[0], 3)
        self.assertEqual(storage[1], 5)
        self.assertEqual(storage[2], 2)
        self.assertEqual(storage[3], 4)
        self.assertEqual(storage[4], 8)
        self.assertEqual(int.from_bytes(returned, "big"), 358)

    def test_initcode_initializes_storage_char_arrays_from_string_literals(self) -> None:
        source = """
typedef __evm_uint256 uint256;

char text[4] = "A\\nB";

uint256 get(void)
{
  return text[0] + text[1] * 10 + text[2] * 100 + text[3] * 1000;
}
"""
        result = self._compile(source)

        initcode = evm.generate_evm_initcode(result)
        storage: dict[int, int] = {}
        runtime = _MiniEvm(initcode, b"", storage).run()
        returned = _MiniEvm(runtime.hex(), _calldata("get()"), storage).run()

        self.assertEqual(storage[0], 65)
        self.assertEqual(storage[1], 10)
        self.assertEqual(storage[2], 66)
        self.assertEqual(storage[3], 0)
        self.assertEqual(int.from_bytes(returned, "big"), 6765)

    def test_static_local_variables_use_persistent_storage_slots(self) -> None:
        source = """
typedef __evm_uint256 uint256;

uint256 bump(void)
{
  static uint256 value = 1;
  value += 1;
  return value;
}

uint256 add_two(void)
{
  static uint256 count;
  count += 2;
  return count;
}
"""
        result = self._compile(source)

        initcode = evm.generate_evm_initcode(result)
        storage: dict[int, int] = {}
        runtime = _MiniEvm(initcode, b"", storage).run()

        self.assertEqual(storage[0], 1)
        self.assertEqual(storage.get(1, 0), 0)

        first = _MiniEvm(runtime.hex(), _calldata("bump()"), storage).run()
        second = _MiniEvm(runtime.hex(), _calldata("bump()"), storage).run()
        add_first = _MiniEvm(runtime.hex(), _calldata("add_two()"), storage).run()
        add_second = _MiniEvm(runtime.hex(), _calldata("add_two()"), storage).run()

        self.assertEqual(int.from_bytes(first, "big"), 2)
        self.assertEqual(int.from_bytes(second, "big"), 3)
        self.assertEqual(int.from_bytes(add_first, "big"), 2)
        self.assertEqual(int.from_bytes(add_second, "big"), 4)
        self.assertEqual(storage[0], 3)
        self.assertEqual(storage[1], 4)

    def test_nested_static_locals_are_collected_before_runtime_dispatch(self) -> None:
        source = """
typedef __evm_uint256 uint256;

uint256 nested(uint256 n)
{
  uint256 total = 0;
  uint256 i;
  if (n) {
    static uint256 if_value = 3;
    total += if_value;
  } else {
    static uint256 else_value = 5;
    total += else_value;
  }
  switch (n) {
    case 1: {
      static uint256 case_value = 7;
      total += case_value;
      break;
    }
    default: {
      static uint256 default_value = 11;
      total += default_value;
      break;
    }
  }
  i = 0;
  while (i < 1) {
    static uint256 while_value = 13;
    total += while_value;
    i++;
  }
  do {
    static uint256 do_value = 17;
    total += do_value;
  } while (0);
  for (i = 0; i < 1; i++) {
    static uint256 for_value = 19;
    total += for_value;
  }
  return total;
}
"""
        result = self._compile(source)

        initcode = evm.generate_evm_initcode(result)
        storage: dict[int, int] = {}
        runtime = _MiniEvm(initcode, b"", storage).run()
        selected = _MiniEvm(runtime.hex(), _calldata("nested(uint256)", 1), storage).run()
        defaulted = _MiniEvm(runtime.hex(), _calldata("nested(uint256)", 0), storage).run()

        self.assertEqual(tuple(storage[index] for index in range(7)), (3, 5, 7, 11, 13, 17, 19))
        self.assertEqual(int.from_bytes(selected, "big"), 59)
        self.assertEqual(int.from_bytes(defaulted, "big"), 65)

    def test_static_locals_inside_expression_trees_are_collected_before_initcode(self) -> None:
        source = """
typedef __evm_uint256 uint256;

struct Box { uint256 value; };

uint256 identity(uint256 value) { return value; }

uint256 nested_expr(uint256 selector)
{
  uint256 values[2] = {0, 0};
  struct Box box = {0};
  uint256 total = 0;
  values[({ static uint256 index_value = 1; index_value; })] =
    ({ static uint256 subscript_value = 3; subscript_value; });
  box.value = ({ static uint256 member_value = 5; member_value; });
  total += (({ static uint256 left = 7; left; }) +
            ({ static uint256 right = 11; right; }));
  total += (selector ? ({ static uint256 then_value = 13; then_value; })
                     : ({ static uint256 else_value = 17; else_value; }));
  total += (({ static uint256 comma_left = 19; comma_left; }),
            ({ static uint256 comma_right = 23; comma_right; }));
  total += +({ static uint256 unary_value = 29; unary_value; });
  total += (uint256)({ static uint256 cast_value = 31; cast_value; });
  total += identity(({ static uint256 call_value = 37; call_value; }));
  total += _Generic(({ static uint256 generic_control = 41; generic_control; }),
                    uint256: ({ static uint256 generic_selected = 43; generic_selected; }),
                    default: 47);
  return total + values[1] + box.value;
}
"""
        result = self._compile(source)

        initcode = evm.generate_evm_initcode(result)
        storage: dict[int, int] = {}
        runtime = _MiniEvm(initcode, b"", storage).run()
        defaulted = _MiniEvm(runtime.hex(), _calldata("nested_expr(uint256)", 0), storage).run()
        selected = _MiniEvm(runtime.hex(), _calldata("nested_expr(uint256)", 1), storage).run()

        self.assertEqual(
            tuple(storage[index] for index in range(len(storage))),
            (1, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 43),
        )
        self.assertEqual(int.from_bytes(defaulted, "big"), 206)
        self.assertEqual(int.from_bytes(selected, "big"), 202)

    def test_initcode_initializes_designated_storage_globals(self) -> None:
        source = """
typedef __evm_uint256 uint256;

struct Pair {
  uint256 left;
  uint256 right;
};

struct Box {
  struct Pair items[2];
  uint256 tail;
};

uint256 values[5] = {[1 ... 2] = 4, 8, [0] = 3};
struct Pair saved = {.right = 5, .left = 2};
struct Box nested = {.items[1].right = 9, .items[0].left = 2, .tail = 7};

uint256 get(void)
{
  return values[0]
       + values[1] * 10
       + values[2] * 100
       + values[3] * 1000
       + saved.left * 10000
       + saved.right * 100000;
}

uint256 get_nested(void)
{
  return nested.items[0].left
       + nested.items[0].right * 10
       + nested.items[1].left * 100
       + nested.items[1].right * 1000
       + nested.tail * 10000;
}
"""
        result = self._compile(source)

        initcode = evm.generate_evm_initcode(result)
        storage: dict[int, int] = {}
        runtime = _MiniEvm(initcode, b"", storage).run()
        returned = _MiniEvm(runtime.hex(), _calldata("get()"), storage).run()
        nested = _MiniEvm(runtime.hex(), _calldata("get_nested()"), storage).run()

        self.assertEqual(storage[0], 3)
        self.assertEqual(storage[1], 4)
        self.assertEqual(storage[2], 4)
        self.assertEqual(storage[3], 8)
        self.assertEqual(storage[4], 0)
        self.assertEqual(storage[5], 2)
        self.assertEqual(storage[6], 5)
        self.assertEqual(storage[7], 2)
        self.assertEqual(storage[8], 0)
        self.assertEqual(storage[9], 0)
        self.assertEqual(storage[10], 9)
        self.assertEqual(storage[11], 7)
        self.assertEqual(int.from_bytes(returned, "big"), 528443)
        self.assertEqual(int.from_bytes(nested, "big"), 79002)

    def test_initcode_evaluates_storage_constant_expression_operators(self) -> None:
        source = """
typedef __evm_uint256 uint256;

struct Pair {
  uint256 left;
  uint256 right;
};

uint256 values[32] = {
  +7,
  -1,
  !0,
  ~0,
  6 * 7,
  7 / 0,
  7 % 0,
  1 << 5,
  32 >> 2,
  6 & 3,
  4 | 1,
  7 ^ 3,
  1 == 1,
  1 != 2,
  1 < 2,
  2 <= 2,
  3 > 2,
  3 >= 3,
  0 ? 91 : 19,
  (unsigned char)257,
  1 + (1 ? 29 : 31),
  sizeof(struct Pair),
  sizeof(uint256 *),
  sizeof(uint256[2]),
  _Alignof(uint256 *),
  _Alignof(unsigned int),
  __builtin_offsetof(struct Pair, right),
  __builtin_types_compatible_p(uint256, __evm_uint256),
  _Generic((uint256)0, uint256: 23, default: 99),
  _Generic((unsigned int)0, uint256: 23, default: 99),
  (_Bool)2,
  (unsigned short)-1
};

uint256 get(uint256 index)
{
  return values[index];
}
"""
        result = self._compile(source)

        initcode = evm.generate_evm_initcode(result)
        storage: dict[int, int] = {}
        runtime = _MiniEvm(initcode, b"", storage).run()

        expected = (
            7,
            _word(-1),
            1,
            _word(~0),
            42,
            0,
            0,
            32,
            8,
            2,
            5,
            4,
            1,
            1,
            1,
            1,
            1,
            1,
            19,
            1,
            30,
            64,
            32,
            64,
            32,
            32,
            32,
            1,
            23,
            99,
            1,
            65535,
        )
        self.assertEqual(tuple(storage[index] for index in range(len(expected))), expected)
        for index, value in enumerate(expected):
            returned = _MiniEvm(runtime.hex(), _calldata("get(uint256)", index), storage).run()
            self.assertEqual(int.from_bytes(returned, "big"), value)

    def test_initcode_initializes_storage_record_bit_fields_with_masks(self) -> None:
        source = """
typedef __evm_uint256 uint256;

struct Flags {
  unsigned int low : 4;
  unsigned int high : 4;
  uint256 value;
};

struct Flags flags = {.low = 0x23, .high = 0xf, .value = 9};

uint256 get(void)
{
  return flags.low * 1000 + flags.high * 100 + flags.value + sizeof(flags) / 32;
}
"""
        result = self._compile(source)

        initcode = evm.generate_evm_initcode(result)
        storage: dict[int, int] = {}
        runtime = _MiniEvm(initcode, b"", storage).run()
        returned = _MiniEvm(runtime.hex(), _calldata("get()"), storage).run()

        self.assertEqual(storage[0], 3)
        self.assertEqual(storage[1], 15)
        self.assertEqual(storage[2], 9)
        self.assertEqual(int.from_bytes(returned, "big"), 4512)

    def test_initcode_skips_unnamed_storage_record_bit_fields(self) -> None:
        source = """
typedef __evm_uint256 uint256;

struct Flags {
  unsigned int low : 4;
  unsigned int : 0;
  unsigned int high : 4;
  uint256 value;
};

struct Flags flags = {0x23, 0x25, 7};

uint256 get(void)
{
  return flags.low * 1000 + flags.high * 100 + flags.value + sizeof(flags) / 32;
}
"""
        result = self._compile(source)

        initcode = evm.generate_evm_initcode(result)
        storage: dict[int, int] = {}
        runtime = _MiniEvm(initcode, b"", storage).run()
        returned = _MiniEvm(runtime.hex(), _calldata("get()"), storage).run()

        self.assertEqual(storage[0], 3)
        self.assertEqual(storage[1], 5)
        self.assertEqual(storage[2], 7)
        self.assertEqual(int.from_bytes(returned, "big"), 3510)

    def test_initcode_initializes_global_function_pointer_storage(self) -> None:
        source = """
typedef __evm_uint256 uint256;

uint256 plus_one(uint256 value)
{
  return value + 1;
}

uint256 (*saved)(uint256) = plus_one;

uint256 dispatch(uint256 value)
{
  return saved(value);
}
"""
        result = self._compile(source)

        initcode = evm.generate_evm_initcode(result)
        storage: dict[int, int] = {}
        runtime = _MiniEvm(initcode, b"", storage).run()
        returned = _MiniEvm(runtime.hex(), _calldata("dispatch(uint256)", 7), storage).run()

        self.assertNotEqual(storage[0], 0)
        self.assertEqual(int.from_bytes(returned, "big"), 8)

    def test_initcode_initializes_addressed_function_pointer_storage(self) -> None:
        source = """
typedef __evm_uint256 uint256;

uint256 times_three(uint256 value)
{
  return value * 3;
}

uint256 (*saved)(uint256) = &times_three;

uint256 dispatch(uint256 value)
{
  return saved(value);
}
"""
        result = self._compile(source)

        initcode = evm.generate_evm_initcode(result)
        storage: dict[int, int] = {}
        runtime = _MiniEvm(initcode, b"", storage).run()
        returned = _MiniEvm(runtime.hex(), _calldata("dispatch(uint256)", 7), storage).run()

        self.assertNotEqual(storage[0], 0)
        self.assertEqual(int.from_bytes(returned, "big"), 21)

    def test_initcode_initializes_conditional_function_pointer_storage(self) -> None:
        source = """
typedef __evm_uint256 uint256;

uint256 plus_one(uint256 value)
{
  return value + 1;
}

uint256 times_three(uint256 value)
{
  return value * 3;
}

uint256 (*saved)(uint256) = 0 ? plus_one : times_three;

uint256 dispatch(uint256 value)
{
  return saved(value);
}
"""
        result = self._compile(source)

        initcode = evm.generate_evm_initcode(result)
        storage: dict[int, int] = {}
        runtime = _MiniEvm(initcode, b"", storage).run()
        returned = _MiniEvm(runtime.hex(), _calldata("dispatch(uint256)", 7), storage).run()

        self.assertNotEqual(storage[0], 0)
        self.assertEqual(int.from_bytes(returned, "big"), 21)

    def test_initcode_evaluates_generic_types_chars_and_cast_function_labels(self) -> None:
        source = """
typedef __evm_uint256 uint256;
typedef uint256 (*Fn)(uint256);

uint256 plus_two(uint256 value)
{
  return value + 2;
}

uint256 times_four(uint256 value)
{
  return value * 4;
}

uint256 type_value = __builtin_types_compatible_p(uint256, __evm_uint256);
uint256 generic_value = _Generic((uint256)0, uint256: 11, default: 22);
uint256 char_value = 'AZ';
uint256 octal_value = 010;
Fn saved = (Fn)plus_two;
Fn selected = 1 ? (Fn)times_four : (Fn)plus_two;

uint256 get(void)
{
  return type_value * 100000 + generic_value * 1000 + char_value + octal_value;
}

uint256 dispatch_saved(uint256 value)
{
  return saved(value);
}

uint256 dispatch_selected(uint256 value)
{
  return selected(value);
}
"""
        result = self._compile(source)

        initcode = evm.generate_evm_initcode(result)
        storage: dict[int, int] = {}
        runtime = _MiniEvm(initcode, b"", storage).run()
        value = _MiniEvm(runtime.hex(), _calldata("get()"), storage).run()
        saved = _MiniEvm(runtime.hex(), _calldata("dispatch_saved(uint256)", 7), storage).run()
        selected = _MiniEvm(
            runtime.hex(),
            _calldata("dispatch_selected(uint256)", 7),
            storage,
        ).run()

        self.assertEqual(storage[0], 1)
        self.assertEqual(storage[1], 11)
        self.assertEqual(storage[2], (ord("A") << 8) | ord("Z"))
        self.assertEqual(storage[3], 8)
        self.assertNotEqual(storage[4], 0)
        self.assertNotEqual(storage[5], 0)
        self.assertEqual(int.from_bytes(value, "big"), 127738)
        self.assertEqual(int.from_bytes(saved, "big"), 9)
        self.assertEqual(int.from_bytes(selected, "big"), 28)

    def test_struct_storage_members_use_deterministic_slots(self) -> None:
        source = """
typedef __evm_uint256 uint256;

struct Pair {
  uint256 first;
  uint256 second;
};

struct Pair pair;

void set_pair(uint256 first, uint256 second)
{
  pair.first = first;
  pair.second = second;
}

uint256 get_second(void)
{
  return pair.second;
}
"""
        result = self._compile(source)

        asm = generate_evm_asm(result)
        bytecode = generate_evm_bytecode(result)
        storage: dict[int, int] = {}

        _MiniEvm(bytecode, _calldata("set_pair(uint256,uint256)", 9, 12), storage).run()
        returned = _MiniEvm(bytecode, _calldata("get_second()"), storage).run()

        self.assertEqual(storage, {0: 9, 1: 12})
        self.assertEqual(int.from_bytes(returned, "big"), 12)
        self.assertIn("SSTORE", asm)

    def test_logical_operators_short_circuit_side_effects(self) -> None:
        source = """
typedef __evm_uint256 uint256;

uint256 marker;

uint256 logical_and(uint256 flag)
{
  marker = 0;
  if (flag && (marker = 5)) {
    return marker;
  }
  return marker;
}

uint256 logical_or(uint256 flag)
{
  marker = 0;
  if (flag || (marker = 7)) {
    return marker;
  }
  return 99;
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)
        storage: dict[int, int] = {}

        and_false = _MiniEvm(bytecode, _calldata("logical_and(uint256)", 0), storage).run()
        and_true = _MiniEvm(bytecode, _calldata("logical_and(uint256)", 1), storage).run()
        or_true = _MiniEvm(bytecode, _calldata("logical_or(uint256)", 1), storage).run()
        or_false = _MiniEvm(bytecode, _calldata("logical_or(uint256)", 0), storage).run()

        self.assertEqual(int.from_bytes(and_false, "big"), 0)
        self.assertEqual(int.from_bytes(and_true, "big"), 5)
        self.assertEqual(int.from_bytes(or_true, "big"), 0)
        self.assertEqual(int.from_bytes(or_false, "big"), 7)

    def test_conditional_and_comma_expressions_execute_selected_side_effects(self) -> None:
        source = """
typedef __evm_uint256 uint256;

uint256 marker;

uint256 choose(uint256 flag)
{
  marker = 0;
  return flag ? (marker = 11) : (marker = 13);
}

uint256 sequence(void)
{
  marker = 3;
  return (marker += 4, marker + 5);
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)
        storage: dict[int, int] = {}

        selected_true = _MiniEvm(bytecode, _calldata("choose(uint256)", 1), storage).run()
        selected_false = _MiniEvm(bytecode, _calldata("choose(uint256)", 0), storage).run()
        comma_result = _MiniEvm(bytecode, _calldata("sequence()"), storage).run()

        self.assertEqual(int.from_bytes(selected_true, "big"), 11)
        self.assertEqual(int.from_bytes(selected_false, "big"), 13)
        self.assertEqual(int.from_bytes(comma_result, "big"), 12)

    def test_pointer_left_addition_prefix_updates_and_signed_bitfield_update(self) -> None:
        source = """
typedef __evm_uint256 uint256;

struct Flags {
  signed int low : 4;
  uint256 value;
};

uint256 pointer_left_addition(void)
{
  uint256 values[4] = {3, 5, 7, 11};
  uint256 *ptr = 1 + values;
  --ptr;
  ++ptr;
  return *ptr;
}

uint256 signed_bitfield_update(uint256 input)
{
  struct Flags flags = {0};
  flags.low = input;
  int before = flags.low++;
  --flags.low;
  return (uint256)(before + 16) * 100 + (uint256)(flags.low + 16);
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)

        pointer = _MiniEvm(bytecode, _calldata("pointer_left_addition()")).run()
        bitfield = _MiniEvm(bytecode, _calldata("signed_bitfield_update(uint256)", 0xF)).run()

        self.assertEqual(int.from_bytes(pointer, "big"), 5)
        self.assertEqual(int.from_bytes(bitfield, "big"), 1515)

    def test_grouped_storage_declarations_and_static_locals_use_slots(self) -> None:
        source = """
typedef __evm_uint256 uint256;

extern uint256 ignored;
uint256 first, second;

uint256 grouped(void)
{
  uint256 local_a = 1, local_b = 2;
  static uint256 static_a = 3, static_b = 5;
  first = local_a;
  second = local_b;
  static_a += 1;
  static_b += 2;
  return first * 1000 + second * 100 + static_a * 10 + static_b;
}
"""
        result = self._compile(source)
        initcode = evm.generate_evm_initcode(result)
        storage: dict[int, int] = {}
        runtime = _MiniEvm(initcode, b"", storage).run()

        returned = _MiniEvm(runtime.hex(), _calldata("grouped()"), storage).run()

        self.assertEqual(int.from_bytes(returned, "big"), 1247)
        self.assertEqual(storage, {0: 1, 1: 2, 2: 4, 3: 7})

    def test_initialized_static_local_requires_initcode_generation(self) -> None:
        self._assert_evm_diagnostic(
            """
typedef __evm_uint256 uint256;

uint256 get(void)
{
  static uint256 value = 1;
  return value;
}
""",
            "EVM target does not support initialized storage globals",
        )

    def test_statement_expression_without_value_and_member_pointer_access(self) -> None:
        source = """
typedef __evm_uint256 uint256;

struct Pair {
  uint256 left;
  uint256 right;
};

uint256 member_pointer(void)
{
  struct Pair pair = {4, 9};
  struct Pair *ptr = &pair;
  ({ if (ptr->right) { ptr->right += 1; } });
  ({});
  return ptr->left * 10 + ptr->right;
}
"""
        result = self._compile(source)
        bytecode = generate_evm_bytecode(result)

        returned = _MiniEvm(bytecode, _calldata("member_pointer()")).run()

        self.assertEqual(int.from_bytes(returned, "big"), 50)

    def test_unavailable_external_call_reports_evm_diagnostic(self) -> None:
        self._assert_evm_diagnostic(
            """
typedef __evm_uint256 uint256;

uint256 helper(uint256 value);

uint256 entry(uint256 value)
{
  return helper(value);
}
""",
            "unsupported EVM call: helper",
        )

    def test_unprototyped_function_pointer_call_reports_evm_diagnostic(self) -> None:
        self._assert_evm_diagnostic(
            """
typedef __evm_uint256 uint256;
typedef uint256 (*Fn)();

uint256 target(void) { return 1; }

uint256 entry(void)
{
  Fn fn = target;
  return fn();
}
""",
            "EVM function pointer calls need a fixed prototype",
        )

    def test_backend_abi_and_function_pointer_diagnostics(self) -> None:
        cases = (
            (
                """
typedef __evm_uint256 uint256;

uint256 bad(uint256 first, ...)
{
  return first;
}
""",
                "EVM target does not support variadic functions",
            ),
            (
                """
typedef __evm_uint256 uint256;

static uint256 helper(double value)
{
  return 1;
}

uint256 entry(void)
{
  return helper(1.0);
}
""",
                "unsupported EVM parameter type: double",
            ),
            (
                """
typedef __evm_uint256 uint256;

uint256 value;

uint256 *bad(void)
{
  return &value;
}
""",
                "EVM ABI does not support pointer return types",
            ),
            (
                """
typedef __evm_uint256 uint256;

struct Pair {
  uint256 left;
};

uint256 bad(struct Pair value)
{
  return value.left;
}
""",
                "unsupported EVM scalar type: struct Pair",
            ),
            (
                """
typedef __evm_uint256 uint256;
typedef uint256 (*Fn)(double);

static uint256 apply(Fn fn)
{
  return fn(1.0);
}

uint256 entry(void)
{
  return apply((Fn)0);
}
""",
                "unsupported EVM function pointer parameter type: double",
            ),
            (
                """
typedef __evm_uint256 uint256;
typedef uint256 (*Fn)(uint256, uint256);

static uint256 apply(Fn fn)
{
  return fn(1, 2);
}

uint256 entry(void)
{
  return apply((Fn)0);
}
""",
                "EVM function pointer call has no local target with matching prototype",
            ),
        )

        for source, message in cases:
            with self.subTest(message=message):
                self._assert_evm_diagnostic(source, message)

    def test_storage_initializer_diagnostics_are_reported_by_initcode(self) -> None:
        cases = (
            (
                """
typedef __evm_uint256 uint256;
struct Pair { uint256 left; uint256 right; };
struct Pair pair = 1;
uint256 get(void) { return pair.left; }
""",
                "EVM aggregate storage initializer for struct Pair needs braces",
            ),
            (
                """
typedef __evm_uint256 uint256;
uint256 seed(void) { return 1; }
uint256 value = seed();
uint256 get(void) { return value; }
""",
                "EVM initcode requires constant storage initializers",
            ),
            (
                """
char text[2] = "abc";
int get(void) { return text[0]; }
""",
                "EVM string literal storage initializer too long",
            ),
            (
                """
typedef __evm_uint256 uint256;
uint256 text[2] = "a";
uint256 get(void) { return text[0]; }
""",
                (
                    "EVM string literal storage initializer needs a char array target: "
                    "__evm_uint256[2]"
                ),
            ),
            (
                """
typedef __evm_uint256 uint256;
struct Pair { uint256 left; };
struct Pair pair = {1, 2};
uint256 get(void) { return pair.left; }
""",
                "EVM storage record initializer too long",
            ),
            (
                """
char text[0] = "";
int get(void) { return 0; }
""",
                "EVM target needs a complete array type: char[0]",
            ),
        )

        for source, message in cases:
            with self.subTest(message=message):
                self._assert_evm_initcode_diagnostic(source, message)

    def test_local_initializer_and_lvalue_diagnostics_are_reported_by_bytecode(self) -> None:
        cases = (
            (
                """
typedef __evm_uint256 uint256;
struct Pair { uint256 left; };
uint256 get(void)
{
  struct Pair pair = {1, 2};
  return pair.left;
}
""",
                "EVM record initializer too long",
            ),
            (
                """
typedef __evm_uint256 uint256;
uint256 get(void)
{
  char text[2] = "abc";
  return text[0];
}
""",
                "EVM string literal initializer too long",
            ),
            (
                """
typedef __evm_uint256 uint256;
uint256 get(void)
{
  uint256 text[2] = "a";
  return text[0];
}
""",
                "EVM string literal needs a char array target: __evm_uint256[2]",
            ),
            (
                """
typedef __evm_uint256 uint256;
uint256 get(void)
{
  double local;
  return 0;
}
""",
                "unsupported EVM object type: double",
            ),
            (
                """
typedef __evm_uint256 uint256;
uint256 get(void)
{
  uint256 values[2] = 1;
  return values[0];
}
""",
                "EVM scalar initializer cannot initialize __evm_uint256[2]",
            ),
            (
                """
typedef __evm_uint256 uint256;
extern uint256 missing;
uint256 get(void)
{
  missing = 1;
  return 0;
}
""",
                "unknown EVM lvalue: missing",
            ),
            (
                """
typedef __evm_uint256 uint256;
uint256 global;
uint256 get(void)
{
  uint256 *ptr = &global;
  return ptr == 0;
}
""",
                "EVM target only supports addresses of memory objects",
            ),
        )

        for source, message in cases:
            with self.subTest(message=message):
                self._assert_evm_diagnostic(source, message)

    def test_exported_function_shape_diagnostics(self) -> None:
        cases = (
            (
                """
typedef __evm_uint256 uint256;
static uint256 hidden(void) { return 1; }
""",
                "EVM target needs one exported function",
            ),
            (
                """
typedef __evm_uint256 uint256;
uint256 variadic(uint256 first, ...) { return first; }
""",
                "EVM target does not support variadic functions",
            ),
            (
                """
typedef __evm_uint256 uint256;
struct Pair { uint256 left; uint256 right; };
static double helper(void) { return 1.0; }
uint256 entry(void) { return 1; }
""",
                "unsupported EVM scalar type: double",
            ),
        )

        for source, message in cases:
            with self.subTest(message=message):
                self._assert_evm_diagnostic(source, message)
