from contextlib import suppress
from typing import Literal

from xcc.ast import (
    ArrayDecl,
    CompoundLiteralExpr,
    CompoundStmt,
    DeclStmt,
    Expr,
    FunctionDef,
    Identifier,
    InitList,
    MemberExpr,
    Param,
    RecordMemberDecl,
    StaticAssertDecl,
    Stmt,
    StringLiteral,
    SubscriptExpr,
    TranslationUnit,
    TypeSpec,
    UnaryExpr,
)
from xcc.types import (
    DOUBLE,
    FLOAT,
    INT,
    LONG,
    LONGDOUBLE,
    VOID,
    Type,
)

from . import type_resolution as _type_resolution
from .calls import check_call_arguments
from .constants import (
    char_const_value,
    char_literal_body,
    decode_escaped_units,
    eval_int_constant_expr,
    fits_integer_literal_value,
    parse_int_literal,
    string_literal_body,
    string_literal_required_length,
)
from .conversions import (
    analyze_additive_types,
    conditional_pointer_result,
    is_assignment_expr_compatible,
    is_compatible_nonvoid_object_pointer_pair,
    is_complete_object_pointer_type,
    is_null_pointer_constant,
    is_pointer_equality_compatible,
    is_pointer_relational_compatible,
    is_scalar_type,
)
from .declarations import analyze_file_scope_decl
from .expressions import analyze_expr
from .initializers import (
    analyze_array_initializer_list,
    analyze_designated_initializer,
    analyze_initializer,
    analyze_initializer_list,
    analyze_record_initializer_list,
    eval_initializer_index,
    is_char_array_string_initializer,
    is_initializer_compatible,
    lookup_initializer_member,
)
from .layout import (
    alignof_object_base_type,
    alignof_type,
    sizeof_object_base_type,
    sizeof_type,
)
from .records import (
    flatten_hoisted_record_members,
    is_anonymous_record_member,
    normalize_record_members,
    record_key,
    record_member_lookup,
    record_members,
    record_type_name,
)
from .statements import analyze_stmt
from .symbols import (
    FunctionSignature,
    FunctionSymbol,
    RecordMemberInfo,
    Scope,
    SemaError,
    SemaUnit,
    SwitchContext,
    TypeMap,
    VarSymbol,
)
from .type_helpers import (
    has_nested_pointer_qualifier_mismatch,
    integer_promotion,
    integer_rank,
    is_arithmetic_type,
    is_assignment_compatible,
    is_compatible_pointee_type,
    is_const_qualified,
    is_floating_type,
    is_integer_type,
    is_object_pointer_type,
    is_pointer_conversion_compatible,
    is_signed_integer_type,
    is_void_pointer_type,
    merged_qualifiers,
    qualifiers_contain,
    signed_can_represent_unsigned,
    signed_range,
    unqualified_type,
    unsigned_max,
    usual_arithmetic_conversion,
)

_MAX_ARRAY_OBJECT_BYTES = (1 << 31) - 1
StdMode = Literal["c11", "gnu11"]
_FLOAT_COMPARE_BUILTINS = (
    "__builtin_isgreater",
    "__builtin_isgreaterequal",
    "__builtin_isless",
    "__builtin_islessequal",
    "__builtin_islessgreater",
    "__builtin_isunordered",
)


class Analyzer:
    def __init__(self, *, std: StdMode = "c11", excess_init_ok: bool = False) -> None:
        self._std = std
        self._excess_init_ok = excess_init_ok
        self._functions: dict[str, FunctionSymbol] = {}
        self._type_map = TypeMap()
        self._function_signatures: dict[str, FunctionSignature] = {}
        self._function_overloads: dict[str, list[FunctionSignature]] = {}
        self._overloadable_functions: set[str] = set()
        self._overload_expr_names: dict[Expr, str] = {}
        self._overload_expr_ids: dict[int, str] = {}
        self._defined_functions: set[str] = set()
        self._record_definitions: dict[str, tuple[RecordMemberInfo, ...]] = {}
        self._record_member_lookup_cache: dict[
            str,
            tuple[tuple[RecordMemberInfo, ...], dict[str, tuple[Type, int]]],
        ] = {}
        self._seen_record_definitions: set[int] = set()
        self._seen_scoped_enum_definitions: set[tuple[int, int]] = set()
        self._file_scope = Scope()
        self._loop_depth = 0
        self._switch_stack: list[SwitchContext] = []
        self._function_labels: set[str] = set()
        self._pending_goto_labels: list[str] = []
        self._current_return_type: Type | None = None
        self._current_scope: Scope | None = None
        self._anon_record_counter = 0
        self._anon_record_names: dict[tuple[str, tuple[RecordMemberDecl, ...]], str] = {}
        self._register_builtin_functions()

    def _register_builtin_functions(self) -> None:
        """Pre-register builtin functions accepted by the frontend."""
        self._function_signatures["__builtin_expect"] = FunctionSignature(
            return_type=LONG, params=(LONG, LONG), is_variadic=False
        )
        self._function_signatures["__builtin_unreachable"] = FunctionSignature(
            return_type=VOID, params=(), is_variadic=False
        )
        for name in _FLOAT_COMPARE_BUILTINS:
            self._function_signatures[name] = FunctionSignature(
                return_type=INT,
                params=(LONGDOUBLE, LONGDOUBLE),
                is_variadic=False,
            )

        # GCC atomic builtins — generic (params=None accepts any args).
        # Return type INT is a pragmatic default; callers wrap these in
        # static inline functions whose return types provide the real type.
        _ATOMIC_BUILTINS = (
            "__atomic_load",
            "__atomic_load_n",
            "__atomic_store",
            "__atomic_store_n",
            "__atomic_fetch_add",
            "__atomic_fetch_sub",
            "__atomic_fetch_and",
            "__atomic_fetch_or",
            "__atomic_fetch_xor",
            "__atomic_exchange",
            "__atomic_exchange_n",
            "__atomic_compare_exchange",
            "__atomic_compare_exchange_n",
            "__atomic_add_fetch",
            "__atomic_sub_fetch",
            "__atomic_and_fetch",
            "__atomic_or_fetch",
            "__atomic_xor_fetch",
            "__atomic_nand_fetch",
            "__atomic_fetch_nand",
            "__atomic_thread_fence",
            "__atomic_signal_fence",
            "__atomic_is_lock_free",
            "__atomic_always_lock_free",
            # C11 <stdatomic.h> macro names — recognised as builtins because the
            # ## token-paste re-scan may leave these unexpanded when they are
            # produced by wrapper macros (e.g. mimalloc's mi_atomic(name)).
            "atomic_fetch_add_explicit",
            "atomic_fetch_sub_explicit",
            "atomic_fetch_and_explicit",
            "atomic_fetch_or_explicit",
            "atomic_fetch_xor_explicit",
            "atomic_fetch_nand_explicit",
            "atomic_load_explicit",
            "atomic_store_explicit",
            "atomic_exchange_explicit",
            "atomic_compare_exchange_strong_explicit",
            "atomic_compare_exchange_weak_explicit",
            "atomic_thread_fence",
            "atomic_signal_fence",
            # C11 atomic functions (used by <stdatomic.h> and clang's atomic builtins)
            "__c11_atomic_init",
            "__c11_atomic_load",
            "__c11_atomic_store",
            "__c11_atomic_exchange",
            "__c11_atomic_compare_exchange_strong",
            "__c11_atomic_compare_exchange_weak",
            "__c11_atomic_fetch_add",
            "__c11_atomic_fetch_sub",
            "__c11_atomic_fetch_and",
            "__c11_atomic_fetch_or",
            "__c11_atomic_fetch_xor",
            "__c11_atomic_thread_fence",
            "__c11_atomic_signal_fence",
            "__c11_atomic_is_lock_free",
            # Clang scoped atomic functions
            "__scoped_atomic_load",
            "__scoped_atomic_store",
            "__scoped_atomic_fetch_add",
            "__scoped_atomic_thread_fence",
            # Legacy __sync builtins
            "__sync_fetch_and_add",
            "__sync_fetch_and_sub",
            "__sync_fetch_and_or",
            "__sync_fetch_and_and",
            "__sync_fetch_and_xor",
            "__sync_add_and_fetch",
            "__sync_sub_and_fetch",
            "__sync_or_and_fetch",
            "__sync_and_and_fetch",
            "__sync_xor_and_fetch",
            "__sync_val_compare_and_swap",
            "__sync_bool_compare_and_swap",
            "__sync_lock_test_and_set",
            "__sync_lock_release",
            "__sync_synchronize",
        )
        _atomic_sig = FunctionSignature(return_type=INT, params=None, is_variadic=True)
        for name in _ATOMIC_BUILTINS:
            self._function_signatures[name] = _atomic_sig

        # Math builtins used by macOS SDK and CPython
        _MATH_BUILTINS = (
            "__builtin_fabs",
            "__builtin_fabsf",
            "__builtin_fabsl",
            "__builtin_inf",
            "__builtin_inff",
            "__builtin_infl",
            "__builtin_nan",
            "__builtin_nanf",
            "__builtin_nanl",
            "__builtin_huge_val",
            "__builtin_huge_valf",
            "__builtin_huge_vall",
            "__builtin_isinf",
            "__builtin_isnan",
            "__builtin_isfinite",
            "__builtin_copysign",
            "__builtin_copysignf",
            "__builtin_copysignl",
        )
        _math_sig = FunctionSignature(return_type=DOUBLE, params=None, is_variadic=True)
        for name in _MATH_BUILTINS:
            self._function_signatures[name] = _math_sig

        # Integer-returning builtins
        _INTEGER_BUILTINS = (
            "__builtin_bswap32",
            "__builtin_bswap64",
        )
        _int_sig = FunctionSignature(return_type=INT, params=None, is_variadic=True)
        for name in _INTEGER_BUILTINS:
            self._function_signatures[name] = _int_sig

    def analyze(self, unit: TranslationUnit) -> SemaUnit:
        externals = unit.externals or [*unit.declarations, *unit.functions]
        for external in externals:
            if isinstance(external, FunctionDef):
                self._register_function_external(external)
                continue
            self._analyze_file_scope_decl(external)
        for external in externals:
            if isinstance(external, FunctionDef) and external.body is not None:
                self._analyze_function(external)
        return SemaUnit(self._functions, self._type_map)

    def _register_function_external(self, func: FunctionDef) -> None:
        if func.storage_class not in {None, "static", "extern"}:
            storage_class = func.storage_class if func.storage_class is not None else "<none>"
            raise SemaError(
                f"Invalid storage class for file-scope function declaration: '{storage_class}'"
            )
        if func.is_thread_local:
            raise SemaError(
                "Invalid declaration specifier for function declaration: '_Thread_local'"
            )
        if self._file_scope.lookup(func.name) is not None:
            raise SemaError(f"Conflicting declaration: {func.name}")
        if self._file_scope.lookup_typedef(func.name) is not None:
            raise SemaError(f"Conflicting declaration: {func.name}")
        signature = self._signature_from(func)
        self._register_function_signature(
            func.name,
            signature,
            is_overloadable=func.is_overloadable,
            allow_incompatible_overload=self._is_compatible_overloadable_redeclaration(func),
        )
        if func.body is not None:
            if func.name in self._defined_functions:
                raise SemaError(f"Duplicate function definition: {func.name}")
            self._defined_functions.add(func.name)

    def _register_function_typed_file_scope_decl(self, declaration: DeclStmt) -> None:
        assert declaration.name is not None
        if declaration.storage_class not in {None, "static", "extern"}:
            storage_class = (
                declaration.storage_class if declaration.storage_class is not None else "<none>"
            )
            raise SemaError(
                f"Invalid storage class for file-scope function declaration: '{storage_class}'"
            )
        if declaration.is_thread_local:
            raise SemaError(
                "Invalid declaration specifier for function declaration: '_Thread_local'"
            )
        if self._file_scope.lookup(declaration.name) is not None:
            raise SemaError(f"Conflicting declaration: {declaration.name}")
        if self._file_scope.lookup_typedef(declaration.name) is not None:
            raise SemaError(f"Conflicting declaration: {declaration.name}")
        resolved_type = self._resolve_type(declaration.type_spec)
        callable_signature = resolved_type.callable_signature()
        assert callable_signature is not None
        return_type, params = callable_signature
        parameter_types, is_variadic = params
        self._register_function_signature(
            declaration.name,
            FunctionSignature(return_type, parameter_types, is_variadic),
        )

    def _register_function_signature(
        self,
        name: str,
        signature: FunctionSignature,
        *,
        is_overloadable: bool = False,
        allow_incompatible_overload: bool = False,
    ) -> None:
        existing = self._function_signatures.get(name)
        if existing is None:
            self._function_signatures[name] = signature
            if is_overloadable:
                self._overloadable_functions.add(name)
                self._add_function_overload(name, signature)
            return
        if not self._signatures_compatible(existing, signature):
            if not allow_incompatible_overload:
                raise SemaError(f"Conflicting declaration: {name}")
            self._add_function_overload(name, signature)
            return
        merged_signature = self._merge_signature(existing, signature, name)
        self._function_signatures[name] = merged_signature
        if is_overloadable:
            self._overloadable_functions.add(name)
            self._add_function_overload(name, merged_signature)

    def _is_compatible_overloadable_redeclaration(self, func: FunctionDef) -> bool:
        return (
            func.is_overloadable
            and func.name in self._overloadable_functions
            and func.body is None
            and func.name not in self._defined_functions
        )

    def _add_function_overload(self, name: str, signature: FunctionSignature) -> None:
        overloads = self._function_overloads.setdefault(name, [])
        if signature not in overloads:
            overloads.append(signature)

    def _set_overload_expr_name(self, expr: Expr, name: str) -> None:
        with suppress(TypeError):
            self._overload_expr_names[expr] = name
            return
        self._overload_expr_ids[id(expr)] = name

    def _get_overload_expr_name(self, expr: Expr) -> str | None:
        try:
            hash(expr)
        except TypeError:
            return self._overload_expr_ids.get(id(expr))
        return self._overload_expr_names.get(expr)

    def _signature_matches_callable_type(
        self,
        signature: FunctionSignature,
        target_type: Type,
    ) -> bool:
        callable_signature = target_type.callable_signature()
        if callable_signature is None:
            return False
        return_type, params = callable_signature
        parameter_types, is_variadic = params
        return (
            signature.return_type == return_type
            and signature.params == parameter_types
            and signature.is_variadic == is_variadic
        )

    def _resolve_overload_for_cast(
        self,
        overload_name: str,
        target_type: Type,
    ) -> FunctionSignature | None:
        overloads = self._function_overloads.get(overload_name)
        if not overloads:
            return None
        matches = [
            signature
            for signature in overloads
            if self._signature_matches_callable_type(signature, target_type)
        ]
        if len(matches) != 1:
            return None
        return matches[0]

    def _merge_signature(
        self,
        existing: FunctionSignature,
        incoming: FunctionSignature,
        name: str,
    ) -> FunctionSignature:
        if not self._signatures_compatible(existing, incoming):
            raise SemaError(f"Conflicting declaration: {name}")
        if existing.params is None and incoming.params is not None:
            return incoming
        return existing

    def _signatures_compatible(
        self,
        existing: FunctionSignature,
        incoming: FunctionSignature,
    ) -> bool:
        if existing.return_type != incoming.return_type:
            return False
        if existing.params is None or incoming.params is None:
            return True
        return existing.params == incoming.params and existing.is_variadic == incoming.is_variadic

    def _analyze_function(self, func: FunctionDef) -> None:
        return_type = self._function_signatures[func.name].return_type
        assert func.body is not None
        scope = Scope(self._file_scope)
        self._function_labels = set()
        self._pending_goto_labels = []
        previous_return_type = self._current_return_type
        self._current_return_type = return_type
        try:
            self._define_params(func.params, scope)
            self._analyze_compound(func.body, scope, return_type)
            for label in self._pending_goto_labels:
                if label not in self._function_labels:
                    raise SemaError(f"Undefined label: {label}")
            self._functions[func.name] = FunctionSymbol(func.name, return_type, scope.symbols)
        finally:
            self._current_return_type = previous_return_type

    def _define_params(self, params: list[Param], scope: Scope) -> None:
        for param in params:
            if param.name is None:
                raise SemaError("Missing parameter name")
            param_type = self._resolve_param_type(param.type_spec)
            scope.define(VarSymbol(param.name, param_type))

    def _declaration_qualifier_text(self, declaration: DeclStmt) -> str | None:
        qualifiers: list[str] = []
        if declaration.storage_class is not None:
            qualifiers.append(f"storage class '{declaration.storage_class}'")
        if declaration.is_thread_local:
            qualifiers.append("'_Thread_local'")
        if not qualifiers:
            return None
        return " and ".join(qualifiers)

    def _missing_object_identifier_message(self, scope_label: str, declaration: DeclStmt) -> str:
        qualifier_text = self._declaration_qualifier_text(declaration)
        if qualifier_text is None:
            return f"Expected identifier for {scope_label} object declaration"
        return f"Expected identifier for {scope_label} object declaration with {qualifier_text}"

    def _missing_identifier_for_alignment_message(
        self,
        scope_label: str,
        declaration: DeclStmt,
    ) -> str:
        context = f"{scope_label} object declaration"
        qualifier_text = self._declaration_qualifier_text(declaration)
        if qualifier_text is None:
            return f"Invalid alignment specifier for {context} without identifier"
        return f"Invalid alignment specifier for {context} without identifier with {qualifier_text}"

    def _extern_initializer_message(self, scope_label: str) -> str:
        return (
            f"Invalid initializer for {scope_label} object declaration with storage class 'extern'"
        )

    def _invalid_object_type_message(self, scope_label: str, type_label: str) -> str:
        return f"Invalid object type for {scope_label} object declaration: {type_label}"

    def _invalid_object_type_for_context_message(self, context_label: str, type_label: str) -> str:
        return f"Invalid object type for {context_label}: {type_label}"

    def _invalid_record_member_type_message(self, type_label: str) -> str:
        return f"Invalid object type for record member declaration: {type_label}"

    def _invalid_typedef_type_message(
        self,
        scope_kind: Literal["file-scope", "block-scope"],
    ) -> str:
        return f"Invalid atomic type for {scope_kind} typedef declaration"

    def _invalid_alignment_message(
        self,
        context_label: str,
        alignment: int,
        natural_alignment: int | None,
    ) -> str:
        if alignment <= 0:
            return f"Invalid alignment specifier for {context_label}: alignment must be positive"
        if (alignment & (alignment - 1)) != 0:
            return (
                f"Invalid alignment specifier for {context_label}: "
                f"alignment {alignment} is not a power of two"
            )
        if natural_alignment is None:
            return (
                f"Invalid alignment specifier for {context_label}: "
                "cannot determine natural alignment"
            )
        return (
            f"Invalid alignment specifier for {context_label}: "
            f"alignment {alignment} is weaker than natural alignment {natural_alignment}"
        )

    def _invalid_object_type_label(self, type_spec: TypeSpec) -> str | None:
        if self._is_invalid_atomic_type_spec(type_spec):
            return "atomic"
        if self._is_invalid_void_object_type(type_spec):
            return "void"
        if self._is_invalid_incomplete_record_object_type(type_spec):
            return "incomplete"
        return None

    def _typedef_storage_class_object_message(self, scope_label: str) -> str:
        return (
            f"Invalid storage class for {scope_label} object declaration: 'typedef'; "
            "use a typedef declaration instead"
        )

    def _thread_local_storage_class_message(
        self,
        scope_label: str,
        storage_class: str | None,
    ) -> str:
        storage_label = storage_class if storage_class is not None else "none"
        return (
            f"Invalid storage class for {scope_label} thread-local object declaration: "
            f"'{storage_label}'; '_Thread_local' requires 'static' or 'extern'"
        )

    def _analyze_file_scope_decl(self, declaration: Stmt) -> None:
        analyze_file_scope_decl(self, declaration)

    def _signature_from(self, func: FunctionDef) -> FunctionSignature:
        if not func.has_prototype:
            if func.is_variadic:
                raise SemaError("Variadic function requires a prototype")
            if self._is_invalid_atomic_type_spec(func.return_type):
                raise SemaError("Invalid return type: atomic")
            if self._is_invalid_incomplete_record_object_type(func.return_type):
                raise SemaError("Invalid return type: incomplete")
            return FunctionSignature(self._resolve_type(func.return_type), None, False)
        params: list[Type] = []
        for param in func.params:
            if self._is_invalid_atomic_type_spec(param.type_spec):
                raise SemaError("Invalid parameter type: atomic")
            if self._is_invalid_void_parameter_type(param.type_spec):
                raise SemaError("Invalid parameter type: void")
            if self._is_invalid_incomplete_record_object_type(param.type_spec):
                raise SemaError("Invalid parameter type: incomplete")
            params.append(self._resolve_param_type(param.type_spec))
        if self._is_invalid_atomic_type_spec(func.return_type):
            raise SemaError("Invalid return type: atomic")
        if self._is_invalid_incomplete_record_object_type(func.return_type):
            raise SemaError("Invalid return type: incomplete")
        return FunctionSignature(
            self._resolve_type(func.return_type),
            tuple(params),
            func.is_variadic,
        )

    def _record_key(self, kind: str, tag: str) -> str:
        return record_key(kind, tag)

    def _record_type_name(self, type_spec: TypeSpec) -> str:
        name, self._anon_record_counter = record_type_name(
            type_spec,
            self._anon_record_names,
            self._anon_record_counter,
        )
        return name

    def _normalize_record_members(
        self,
        members: tuple[RecordMemberInfo, ...] | tuple[tuple[str | None, Type], ...],
    ) -> tuple[RecordMemberInfo, ...]:
        return normalize_record_members(members)

    def _record_members(self, record_name: str) -> tuple[RecordMemberInfo, ...] | None:
        return record_members(self._record_definitions, record_name)

    def _is_anonymous_record_member(self, member: RecordMemberInfo) -> bool:
        return is_anonymous_record_member(member, self._is_record_name)

    def _flatten_hoisted_record_members(
        self,
        record_type: Type,
        owner_index: int,
    ) -> list[tuple[str, tuple[Type, int]]]:
        return flatten_hoisted_record_members(
            self._record_definitions,
            record_type,
            owner_index,
            self._is_record_name,
        )

    def _record_member_lookup(
        self,
        record_name: str,
    ) -> dict[str, tuple[Type, int]] | None:
        return record_member_lookup(
            self._record_definitions,
            self._record_member_lookup_cache,
            record_name,
            self._is_record_name,
        )

    def _register_type_spec(self, type_spec: TypeSpec) -> None:
        _type_resolution.register_type_spec(self, type_spec)

    def _resolve_type(self, type_spec: TypeSpec) -> Type:
        return _type_resolution.resolve_type(self, type_spec)

    def _resolve_array_bound(self, value: object) -> int:
        return _type_resolution.resolve_array_bound(self, value)

    def _resolve_function_param_types(
        self,
        declarator_value: int | tuple[tuple[TypeSpec, ...] | None, bool],
    ) -> tuple[tuple[Type, ...] | None, bool]:
        return _type_resolution.resolve_function_param_types(self, declarator_value)

    def _resolve_param_type(self, type_spec: TypeSpec) -> Type:
        return _type_resolution.resolve_param_type(self, type_spec)

    def _define_enum_members(self, type_spec: TypeSpec, scope: Scope) -> None:
        _type_resolution.define_enum_members(self, type_spec, scope)

    def _define_scoped_enum_members(self, type_spec: TypeSpec, scope: Scope) -> None:
        _type_resolution.define_scoped_enum_members(self, type_spec, scope)

    def _is_function_object_type(self, type_spec: TypeSpec) -> bool:
        return _type_resolution.is_function_object_type(type_spec)

    def _is_invalid_atomic_type_spec(self, type_spec: TypeSpec) -> bool:
        return _type_resolution.is_invalid_atomic_type_spec(self, type_spec)

    def _is_invalid_incomplete_record_object_type(self, type_spec: TypeSpec) -> bool:
        return _type_resolution.is_invalid_incomplete_record_object_type(self, type_spec)

    def _is_record_name(self, name: str) -> bool:
        return _type_resolution.is_record_name(name)

    def _lookup_record_member(self, record_type: Type, member_name: str) -> Type:
        return _type_resolution.lookup_record_member(self, record_type, member_name)

    def _resolve_member_type(
        self,
        base_type: Type,
        member_name: str,
        through_pointer: bool,
    ) -> Type:
        return _type_resolution.resolve_member_type(
            self,
            base_type,
            member_name,
            through_pointer,
        )

    def _invalid_sizeof_operand_reason_for_type_spec(self, type_spec: TypeSpec) -> str | None:
        return _type_resolution.invalid_sizeof_operand_reason_for_type_spec(self, type_spec)

    def _invalid_sizeof_operand_reason_for_type(self, type_: Type) -> str | None:
        return _type_resolution.invalid_sizeof_operand_reason_for_type(self, type_)

    def _invalid_alignof_operand_reason_for_type_spec(self, type_spec: TypeSpec) -> str | None:
        return self._invalid_sizeof_operand_reason_for_type_spec(type_spec)

    def _invalid_alignof_operand_reason_for_type(self, type_: Type) -> str | None:
        return self._invalid_sizeof_operand_reason_for_type(type_)

    def _is_invalid_sizeof_type_spec(self, type_spec: TypeSpec) -> bool:
        return self._invalid_sizeof_operand_reason_for_type_spec(type_spec) is not None

    def _is_invalid_sizeof_type(self, type_: Type) -> bool:
        return self._invalid_sizeof_operand_reason_for_type(type_) is not None

    def _is_invalid_alignof_type_spec(self, type_spec: TypeSpec) -> bool:
        return self._invalid_alignof_operand_reason_for_type_spec(type_spec) is not None

    def _is_invalid_alignof_type(self, type_: Type) -> bool:
        return self._invalid_alignof_operand_reason_for_type(type_) is not None

    def _invalid_generic_association_type_reason(self, type_spec: TypeSpec) -> str | None:
        return _type_resolution.invalid_generic_association_type_reason(self, type_spec)

    def _is_invalid_generic_association_type_spec(self, type_spec: TypeSpec) -> bool:
        return self._invalid_generic_association_type_reason(type_spec) is not None

    def _describe_generic_association_type(self, type_spec: TypeSpec, resolved_type: Type) -> str:
        return _type_resolution.describe_generic_association_type(type_spec, resolved_type)

    def _format_location_details(self, line: int | None, column: int | None) -> str | None:
        if line is not None and column is not None:
            return f"line {line}, column {column}"
        if line is not None:
            return f"line {line}"
        if column is not None:
            return f"column {column}"
        return None

    def _format_location_suffix(self, line: int | None, column: int | None) -> str:
        details = self._format_location_details(line, column)
        if details is None:
            return ""
        return f" at {details}"

    def _is_variably_modified_type_spec(self, type_spec: TypeSpec) -> bool:
        return _type_resolution.is_variably_modified_type_spec(self, type_spec)

    def _is_valid_explicit_alignment(
        self,
        alignment: int | None,
        natural_alignment: int | None,
    ) -> bool:
        return _type_resolution.is_valid_explicit_alignment(alignment, natural_alignment)

    def _is_integer_type(self, type_: Type) -> bool:
        return is_integer_type(type_)

    def _is_floating_type(self, type_: Type) -> bool:
        return is_floating_type(type_)

    def _is_arithmetic_type(self, type_: Type) -> bool:
        return is_arithmetic_type(type_)

    def _unqualified_type(self, type_: Type) -> Type:
        return unqualified_type(type_)

    def _integer_rank(self, type_: Type) -> int:
        return integer_rank(type_)

    def _is_signed_integer_type(self, type_: Type) -> bool:
        return is_signed_integer_type(type_)

    def _integer_promotion(self, type_: Type) -> Type:
        return integer_promotion(type_)

    def _signed_range(self, type_: Type) -> tuple[int, int] | None:
        return signed_range(type_)

    def _unsigned_max(self, type_: Type) -> int | None:
        return unsigned_max(type_)

    def _signed_can_represent_unsigned(self, signed: Type, unsigned: Type) -> bool:
        return signed_can_represent_unsigned(signed, unsigned)

    def _usual_arithmetic_conversion(self, left_type: Type, right_type: Type) -> Type | None:
        return usual_arithmetic_conversion(left_type, right_type)

    def _is_void_pointer_type(self, type_: Type) -> bool:
        return is_void_pointer_type(type_)

    def _is_compatible_pointee_type(self, left_type: Type, right_type: Type) -> bool:
        return is_compatible_pointee_type(left_type, right_type)

    def _merged_qualifiers(self, left_type: Type, right_type: Type) -> tuple[str, ...]:
        return merged_qualifiers(left_type, right_type)

    def _qualifiers_contain(self, target_type: Type, value_type: Type) -> bool:
        return qualifiers_contain(target_type, value_type)

    def _is_object_pointer_type(self, type_: Type) -> bool:
        return is_object_pointer_type(type_)

    def _is_complete_object_pointer_type(self, type_: Type) -> bool:
        return is_complete_object_pointer_type(self, type_)

    def _is_assignment_compatible(self, target_type: Type, value_type: Type) -> bool:
        return is_assignment_compatible(target_type, value_type)

    def _is_pointer_conversion_compatible(self, target_type: Type, value_type: Type) -> bool:
        return is_pointer_conversion_compatible(target_type, value_type)

    def _has_nested_pointer_qualifier_mismatch(self, left_type: Type, right_type: Type) -> bool:
        return has_nested_pointer_qualifier_mismatch(left_type, right_type)

    def _is_null_pointer_constant(self, expr: Expr, scope: Scope) -> bool:
        return is_null_pointer_constant(self, expr, scope)

    def _is_assignment_expr_compatible(
        self,
        target_type: Type,
        value_expr: Expr,
        value_type: Type,
        scope: Scope,
    ) -> bool:
        return is_assignment_expr_compatible(self, target_type, value_expr, value_type, scope)

    def _is_initializer_compatible(
        self,
        target_type: Type,
        init_expr: Expr,
        init_type: Type,
        scope: Scope,
    ) -> bool:
        return is_initializer_compatible(self, target_type, init_expr, init_type, scope)

    def _analyze_initializer(
        self,
        target_type: Type,
        initializer: Expr | InitList,
        scope: Scope,
    ) -> None:
        analyze_initializer(self, target_type, initializer, scope)

    def _analyze_initializer_list(self, target_type: Type, init: InitList, scope: Scope) -> None:
        analyze_initializer_list(self, target_type, init, scope)

    def _analyze_array_initializer_list(
        self,
        target_type: Type,
        init: InitList,
        scope: Scope,
    ) -> None:
        analyze_array_initializer_list(self, target_type, init, scope)

    def _analyze_record_initializer_list(
        self,
        target_type: Type,
        init: InitList,
        scope: Scope,
    ) -> None:
        analyze_record_initializer_list(self, target_type, init, scope)

    def _analyze_designated_initializer(
        self,
        target_type: Type,
        designators: tuple[tuple[str, Expr | str], ...],
        initializer: Expr | InitList,
        scope: Scope,
    ) -> None:
        analyze_designated_initializer(self, target_type, designators, initializer, scope)

    def _lookup_initializer_member(self, record_type: Type, member_name: str) -> tuple[Type, int]:
        return lookup_initializer_member(self, record_type, member_name)

    def _eval_initializer_index(self, expr: Expr, scope: Scope) -> int:
        return eval_initializer_index(self, expr, scope)

    def _check_static_assert(self, declaration: StaticAssertDecl, scope: Scope) -> None:
        self._analyze_expr(declaration.condition, scope)
        self._allow_const_var_folding = True
        try:
            value = self._eval_int_constant_expr(declaration.condition, scope)
        finally:
            self._allow_const_var_folding = False
        if value is None:
            raise SemaError("Static assertion condition is not integer constant")
        if value == 0:
            message = self._static_assert_message(declaration.message)
            raise SemaError(f"Static assertion failed: {message}")

    def _static_assert_message(self, message: StringLiteral) -> str:
        body = self._string_literal_body(message.value)
        return message.value if body is None else body

    def _ensure_array_size_limit(self, type_: Type) -> None:
        if not type_.is_array():
            return
        size = self._sizeof_type(type_, _MAX_ARRAY_OBJECT_BYTES)
        if size is not None and size > _MAX_ARRAY_OBJECT_BYTES:
            raise SemaError("array is too large")

    def _sizeof_type(self, type_: Type, limit: int | None = None) -> int | None:
        return sizeof_type(self, type_, limit)

    def _alignof_type(self, type_: Type) -> int | None:
        return alignof_type(self, type_)

    def _sizeof_object_base_type(self, type_: Type, limit: int | None) -> int | None:
        return sizeof_object_base_type(self, type_, limit)

    def _alignof_object_base_type(self, type_: Type) -> int | None:
        return alignof_object_base_type(self, type_)

    def _is_char_array_string_initializer(self, target_type: Type, init_expr: Expr) -> bool:
        return is_char_array_string_initializer(self, target_type, init_expr)

    def _string_literal_required_length(self, lexeme: str) -> int | None:
        return string_literal_required_length(self, lexeme)

    def _string_literal_body(self, lexeme: str) -> str | None:
        return string_literal_body(lexeme)

    def _is_scalar_type(self, type_: Type) -> bool:
        return is_scalar_type(self, type_)

    def _analyze_additive_types(self, left_type: Type, right_type: Type, op: str) -> Type | None:
        return analyze_additive_types(self, left_type, right_type, op)

    def _is_compatible_nonvoid_object_pointer_pair(self, left_type: Type, right_type: Type) -> bool:
        return is_compatible_nonvoid_object_pointer_pair(self, left_type, right_type)

    def _is_pointer_relational_compatible(self, left_type: Type, right_type: Type) -> bool:
        return is_pointer_relational_compatible(self, left_type, right_type)

    def _is_pointer_equality_compatible(self, left_type: Type, right_type: Type) -> bool:
        return is_pointer_equality_compatible(self, left_type, right_type)

    def _conditional_pointer_result(
        self,
        then_expr: Expr,
        then_type: Type,
        else_expr: Expr,
        else_type: Type,
        scope: Scope,
    ) -> Type | None:
        return conditional_pointer_result(self, then_expr, then_type, else_expr, else_type, scope)

    def _is_invalid_cast_target(self, type_spec: TypeSpec, target_type: Type) -> bool:
        return (
            self._is_function_object_type(type_spec)
            or self._is_invalid_incomplete_record_object_type(type_spec)
            or (target_type != VOID and not self._is_scalar_type(target_type))
        )

    def _is_invalid_cast_operand(self, operand_type: Type, target_type: Type) -> bool:
        return target_type != VOID and (
            operand_type == VOID or not self._is_scalar_type(operand_type)
        )

    def _is_invalid_void_object_type(self, type_spec: TypeSpec) -> bool:
        return type_spec.name == "void" and not any(
            kind == "ptr" for kind, _ in type_spec.declarator_ops
        )

    def _is_invalid_void_parameter_type(self, type_spec: TypeSpec) -> bool:
        return type_spec.name == "void" and not type_spec.declarator_ops

    def _is_file_scope_vla_type_spec(self, type_spec: TypeSpec) -> bool:
        for kind, value in type_spec.declarator_ops:
            if kind != "arr":
                continue
            if isinstance(value, int):
                continue
            if not isinstance(value, ArrayDecl):
                return True
            if value.length is None:
                continue  # incomplete array (e.g. int a[]), not a VLA
            if isinstance(value.length, int):
                continue
            if self._eval_int_constant_expr(value.length, self._file_scope) is None:
                return True
        return False

    def _check_condition_type(self, condition_type: Type) -> None:
        if condition_type is VOID:
            raise SemaError("Condition must be non-void")
        if not self._is_scalar_type(self._decay_array_value(condition_type)):
            raise SemaError("Condition must be scalar")

    def _check_switch_condition_type(self, condition_type: Type) -> None:
        if condition_type is VOID:
            raise SemaError("Condition must be non-void")
        if not self._is_integer_type(self._decay_array_value(condition_type)):
            raise SemaError("Switch condition must be integer")

    def _analyze_compound(self, stmt: CompoundStmt, scope: Scope, return_type: Type) -> None:
        for item in stmt.statements:
            self._analyze_stmt(item, scope, return_type)

    def _analyze_stmt(self, stmt: Stmt, scope: Scope, return_type: Type) -> None:
        analyze_stmt(self, stmt, scope, return_type)

    def _analyze_expr(self, expr: Expr, scope: Scope) -> Type:
        return analyze_expr(self, expr, scope)

    def _resolve_call_signature(
        self,
        name: str,
        args: list[Expr],
        scope: Scope,
        *,
        default: FunctionSignature,
    ) -> FunctionSignature:
        overloads = self._function_overloads.get(name)
        if not overloads:
            for arg in args:
                self._analyze_expr(arg, scope)
            self._check_call_arguments(args, default.params, default.is_variadic, name, scope)
            return default
        analyzed_arg_types = [
            self._decay_array_value(self._analyze_expr(arg, scope)) for arg in args
        ]
        ranked: list[tuple[int, int, FunctionSignature]] = []
        for signature in overloads:
            score = self._match_overload_signature(args, analyzed_arg_types, signature, scope)
            if score is not None:
                ranked.append((score[0], score[1], signature))
        if not ranked:
            self._check_call_arguments(args, default.params, default.is_variadic, name, scope)
            return default
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        if len(ranked) > 1 and ranked[0][:2] == ranked[1][:2]:
            raise SemaError(f"Ambiguous overloaded call: {name}")
        chosen = ranked[0][2]
        self._check_call_arguments(args, chosen.params, chosen.is_variadic, name, scope)
        return chosen

    def _match_overload_signature(
        self,
        args: list[Expr],
        arg_types: list[Type],
        signature: FunctionSignature,
        scope: Scope,
    ) -> tuple[int, int] | None:
        if signature.params is None:
            return 0, 0
        if signature.is_variadic:
            if len(args) < len(signature.params):
                return None
        elif len(args) != len(signature.params):
            return None
        exact_matches = 0
        fixed_params = signature.params
        for arg, arg_type, param_type in zip(args, arg_types, fixed_params, strict=False):
            if not self._is_assignment_expr_compatible(param_type, arg, arg_type, scope):
                return None
            if arg_type == param_type:
                exact_matches += 1
        return exact_matches, int(not signature.is_variadic)

    def _parse_float_literal_type(self, lexeme: str) -> Type:
        if lexeme and lexeme[-1] in "fF":
            return FLOAT
        if lexeme and lexeme[-1] in "lL":
            return LONGDOUBLE
        return DOUBLE

    def _parse_int_literal(self, lexeme: str | int) -> tuple[int, Type] | None:
        return parse_int_literal(self, lexeme)

    def _fits_integer_literal_value(self, value: int, type_: Type) -> bool:
        return fits_integer_literal_value(value, type_)

    def _eval_int_constant_expr(self, expr: Expr, scope: Scope) -> int | None:
        return eval_int_constant_expr(self, expr, scope)

    def _is_const_qualified(self, type_: Type) -> bool:
        return is_const_qualified(type_)

    def _infer_array_size_from_init(
        self, initializer: Expr | InitList
    ) -> int | None:
        from xcc.ast import InitList as _InitList
        if isinstance(initializer, _InitList):
            return len(initializer.items)
        return None

    def _try_eval_scalar_initializer(
        self, initializer: Expr | InitList, scope: Scope
    ) -> int | None:
        from xcc.ast import InitList as _InitList
        if isinstance(initializer, _InitList):
            if len(initializer.items) != 1:
                return None
            item = initializer.items[0]
            if item.designators:
                return None
            return self._try_eval_scalar_initializer(item.initializer, scope)
        return self._eval_int_constant_expr(initializer, scope)

    def _char_const_value(self, lexeme: str) -> int | None:
        return char_const_value(self, lexeme)

    def _char_literal_body(self, lexeme: str) -> str | None:
        return char_literal_body(lexeme)

    def _decode_escaped_units(self, body: str) -> list[int]:
        return decode_escaped_units(body)

    def _check_call_arguments(
        self,
        args: list[Expr],
        parameter_types: tuple[Type, ...] | None,
        is_variadic: bool,
        function_name: str | None,
        scope: Scope,
    ) -> None:
        check_call_arguments(self, args, parameter_types, is_variadic, function_name, scope)

    def _is_assignable(self, expr: Expr) -> bool:
        return isinstance(expr, (Identifier, SubscriptExpr, MemberExpr, CompoundLiteralExpr)) or (
            isinstance(expr, UnaryExpr) and expr.op == "*"
        )

    def _decay_array_value(self, type_: Type) -> Type:
        return type_.decay_parameter_type()


def analyze(unit: TranslationUnit, *, std: StdMode = "c11", excess_init_ok: bool = False) -> SemaUnit:
    return Analyzer(std=std, excess_init_ok=excess_init_ok).analyze(unit)
