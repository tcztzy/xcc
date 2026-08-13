from dataclasses import dataclass

_COMMON_SCALAR_LAYOUTS: tuple[tuple[str, int, int], ...] = (
    ("_Bool", 1, 1),
    ("bool", 1, 1),
    ("char", 1, 1),
    ("signed char", 1, 1),
    ("unsigned char", 1, 1),
    ("short", 2, 2),
    ("unsigned short", 2, 2),
    ("int", 4, 4),
    ("unsigned int", 4, 4),
    ("long", 8, 8),
    ("unsigned long", 8, 8),
    ("long long", 8, 8),
    ("unsigned long long", 8, 8),
    ("__int128", 16, 16),
    ("__uint128", 16, 16),
    ("unsigned __int128", 16, 16),
    ("__int128_t", 16, 16),
    ("__uint128_t", 16, 16),
    ("float", 4, 4),
    ("double", 8, 8),
    ("enum", 4, 4),
    ("_Float16", 2, 2),
    ("__bf16", 2, 2),
    ("__fp16", 2, 2),
    ("_Float32", 4, 4),
    ("_Float64", 8, 8),
    ("_Float128", 16, 16),
    ("_Float32x", 8, 8),
    ("_Float64x", 16, 16),
)


@dataclass(frozen=True)
class TargetDataLayout:
    name: str
    pointer_size: int
    pointer_alignment: int
    long_double_size: int
    long_double_alignment: int
    long_double_mantissa_bits: int
    uniform_scalar_size: int | None = None
    extra_scalar_names: tuple[str, ...] = ()
    predefined_macros: tuple[str, ...] = ()

    def scalar_size(self, name: str) -> int | None:
        if self.uniform_scalar_size is not None and self._is_uniform_scalar(name):
            return self.uniform_scalar_size
        if name == "long double":
            return self.long_double_size
        for candidate, size, _alignment in _COMMON_SCALAR_LAYOUTS:
            if name == candidate:
                return size
        return None

    def scalar_alignment(self, name: str) -> int | None:
        if self.uniform_scalar_size is not None and self._is_uniform_scalar(name):
            return self.uniform_scalar_size
        if name == "long double":
            return self.long_double_alignment
        for candidate, _size, alignment in _COMMON_SCALAR_LAYOUTS:
            if name == candidate:
                return alignment
        return None

    def _is_uniform_scalar(self, name: str) -> bool:
        if name == "long double":
            return True
        for candidate, _size, _alignment in _COMMON_SCALAR_LAYOUTS:
            if name == candidate:
                return True
        index = 0
        while index < len(self.extra_scalar_names):
            if name == self.extra_scalar_names[index]:
                return True
            index += 1
        return False


def _generic_lp64_data_layout() -> TargetDataLayout:
    return TargetDataLayout(
        name="generic-lp64",
        pointer_size=8,
        pointer_alignment=8,
        long_double_size=16,
        long_double_alignment=16,
        long_double_mantissa_bits=113,
    )


def _darwin_aarch64_data_layout() -> TargetDataLayout:
    return TargetDataLayout(
        name="aarch64-apple-darwin",
        pointer_size=8,
        pointer_alignment=8,
        long_double_size=8,
        long_double_alignment=8,
        long_double_mantissa_bits=53,
        predefined_macros=(
            "__SIZEOF_LONG_DOUBLE__=8",
            "__LDBL_MANT_DIG__=53",
            "__LDBL_DIG__=15",
            "__LDBL_DECIMAL_DIG__=17",
            "__DECIMAL_DIG__=17",
            "__LDBL_EPSILON__=2.2204460492503131e-16L",
            "__LDBL_MIN__=2.2250738585072014e-308L",
            "__LDBL_DENORM_MIN__=4.9406564584124654e-324L",
            "__LDBL_MAX__=1.7976931348623157e+308L",
            "__LDBL_MIN_EXP__=-1021",
            "__LDBL_MAX_EXP__=1024",
            "__LDBL_MIN_10_EXP__=-307",
            "__LDBL_MAX_10_EXP__=308",
        ),
    )


def _x86_64_data_layout() -> TargetDataLayout:
    return TargetDataLayout(
        name="x86_64-sysv",
        pointer_size=8,
        pointer_alignment=8,
        long_double_size=16,
        long_double_alignment=16,
        long_double_mantissa_bits=64,
        predefined_macros=(
            "__SIZEOF_LONG_DOUBLE__=16",
            "__LDBL_MANT_DIG__=64",
            "__LDBL_DIG__=18",
            "__LDBL_DECIMAL_DIG__=21",
            "__DECIMAL_DIG__=21",
        ),
    )


def _evm_word_data_layout() -> TargetDataLayout:
    return TargetDataLayout(
        name="evm-word",
        pointer_size=32,
        pointer_alignment=32,
        long_double_size=32,
        long_double_alignment=32,
        long_double_mantissa_bits=113,
        uniform_scalar_size=32,
        extra_scalar_names=("__evm_uint256", "__evm_address"),
        predefined_macros=(
            "__SIZEOF_BOOL__=32",
            "__SIZEOF_SHORT__=32",
            "__SIZEOF_INT__=32",
            "__SIZEOF_FLOAT__=32",
            "__SIZEOF_DOUBLE__=32",
            "__SIZEOF_LONG_DOUBLE__=32",
            "__SIZEOF_POINTER__=32",
            "__SIZEOF_LONG__=32",
            "__SIZEOF_LONG_LONG__=32",
            "__SIZEOF_SIZE_T__=32",
            "__SIZEOF_PTRDIFF_T__=32",
            "__SIZEOF_INTMAX_T__=32",
            "__SIZEOF_UINTMAX_T__=32",
            "__SIZEOF_WCHAR_T__=32",
            "__SIZEOF_WINT_T__=32",
            "__SIZEOF_CHAR16_T__=32",
            "__SIZEOF_CHAR32_T__=32",
        ),
    )


GENERIC_LP64_DATA_LAYOUT = _generic_lp64_data_layout()
DARWIN_AARCH64_DATA_LAYOUT = _darwin_aarch64_data_layout()
X86_64_DATA_LAYOUT = _x86_64_data_layout()
EVM_WORD_DATA_LAYOUT = _evm_word_data_layout()


def data_layout_for_target(
    target_os: str | None,
    host_machine: str | None,
) -> TargetDataLayout:
    normalized_machine = "" if host_machine is None else host_machine.lower()
    if target_os == "evm" or normalized_machine == "evm":
        return _evm_word_data_layout()
    if target_os == "darwin" and normalized_machine in {"aarch64", "arm64"}:
        return _darwin_aarch64_data_layout()
    if normalized_machine in {"amd64", "x86_64"}:
        return _x86_64_data_layout()
    return _generic_lp64_data_layout()
