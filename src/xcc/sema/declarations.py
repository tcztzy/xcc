from typing import Literal, Protocol

from xcc.ast import (
    DeclGroupStmt,
    DeclStmt,
    Expr,
    InitList,
    NullStmt,
    StaticAssertDecl,
    Stmt,
    TypedefDecl,
    TypeSpec,
)
from xcc.types import Type

from .symbols import FunctionSignature, Scope, SemaError, VarSymbol


class _FileScopeAnalyzer(Protocol):
    _file_scope: Scope
    _function_signatures: dict[str, FunctionSignature]

    def _alignof_type(self, type_: Type) -> int | None: ...

    def _analyze_file_scope_decl(self, declaration: Stmt) -> None: ...

    def _analyze_initializer(
        self,
        target_type: Type,
        initializer: Expr | InitList,
        scope: Scope,
    ) -> None: ...

    def _check_static_assert(self, declaration: StaticAssertDecl, scope: Scope) -> None: ...

    def _define_enum_members(self, type_spec: TypeSpec, scope: Scope) -> None: ...

    def _ensure_array_size_limit(self, type_: Type) -> None: ...

    def _extern_initializer_message(self, scope_label: str) -> str: ...

    def _infer_array_size_from_init(self, initializer: Expr | InitList) -> int | None: ...

    def _invalid_alignment_message(
        self,
        context_label: str,
        alignment: int,
        natural_alignment: int | None,
    ) -> str: ...

    def _invalid_object_type_message(self, scope_label: str, type_label: str) -> str: ...

    def _invalid_typedef_type_message(
        self,
        scope_kind: Literal["file-scope", "block-scope"],
    ) -> str: ...

    def _is_const_qualified(self, type_: Type) -> bool: ...

    def _is_file_scope_vla_type_spec(self, type_spec: TypeSpec) -> bool: ...

    def _is_function_object_type(self, type_spec: TypeSpec) -> bool: ...

    def _is_invalid_atomic_type_spec(self, type_spec: TypeSpec) -> bool: ...

    def _is_invalid_incomplete_record_object_type(self, type_spec: TypeSpec) -> bool: ...

    def _is_invalid_void_object_type(self, type_spec: TypeSpec) -> bool: ...

    def _is_valid_explicit_alignment(
        self,
        alignment: int | None,
        natural_alignment: int | None,
    ) -> bool: ...

    def _missing_identifier_for_alignment_message(
        self,
        scope_label: str,
        declaration: DeclStmt,
    ) -> str: ...

    def _missing_object_identifier_message(
        self,
        scope_label: str,
        declaration: DeclStmt,
    ) -> str: ...

    def _register_function_typed_file_scope_decl(self, declaration: DeclStmt) -> None: ...

    def _register_type_spec(self, type_spec: TypeSpec) -> None: ...

    def _resolve_type(self, type_spec: TypeSpec) -> Type: ...

    def _thread_local_storage_class_message(
        self,
        scope_label: str,
        storage_class: str | None,
    ) -> str: ...

    def _try_eval_scalar_initializer(
        self,
        initializer: Expr | InitList,
        scope: Scope,
    ) -> int | None: ...

    def _typedef_storage_class_object_message(self, scope_label: str) -> str: ...


def analyze_file_scope_decl(analyzer: _FileScopeAnalyzer, declaration: Stmt) -> None:
    a = analyzer
    if isinstance(declaration, DeclGroupStmt):
        for grouped_decl in declaration.declarations:
            a._analyze_file_scope_decl(grouped_decl)
        return
    if isinstance(declaration, TypedefDecl):
        if declaration.name in a._function_signatures:
            raise SemaError(f"Conflicting declaration: {declaration.name}")
        a._register_type_spec(declaration.type_spec)
        if a._is_invalid_atomic_type_spec(declaration.type_spec):
            raise SemaError(a._invalid_typedef_type_message("file-scope"))
        a._define_enum_members(declaration.type_spec, a._file_scope)
        typedef_type = a._resolve_type(declaration.type_spec)
        a._ensure_array_size_limit(typedef_type)
        a._file_scope.define_typedef(declaration.name, typedef_type)
        return
    if isinstance(declaration, DeclStmt):
        if a._is_function_object_type(declaration.type_spec) and not a._is_invalid_atomic_type_spec(
            declaration.type_spec
        ):
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
        if declaration.is_thread_local and declaration.storage_class not in {
            None,
            "static",
            "extern",
        }:
            raise SemaError(
                a._thread_local_storage_class_message("file-scope", declaration.storage_class)
            )
        if declaration.storage_class in {"auto", "register"}:
            storage_class = (
                declaration.storage_class if declaration.storage_class is not None else "none"
            )
            raise SemaError(
                f"Invalid storage class for file-scope object declaration: '{storage_class}'"
            )
        if declaration.storage_class == "typedef":
            raise SemaError(a._typedef_storage_class_object_message("file-scope"))
        a._register_type_spec(declaration.type_spec)
        a._define_enum_members(declaration.type_spec, a._file_scope)
        if declaration.alignment is not None and declaration.name is None:
            raise SemaError(a._missing_identifier_for_alignment_message("file-scope", declaration))
        if declaration.name is None:
            if declaration.storage_class is not None or declaration.is_thread_local:
                raise SemaError(a._missing_object_identifier_message("file-scope", declaration))
            return
        if a._is_function_object_type(declaration.type_spec) and not a._is_invalid_atomic_type_spec(
            declaration.type_spec
        ):
            a._register_function_typed_file_scope_decl(declaration)
            return
        if declaration.name in a._function_signatures:
            raise SemaError(f"Conflicting declaration: {declaration.name}")
        if a._is_invalid_atomic_type_spec(declaration.type_spec):
            raise SemaError(a._invalid_object_type_message("file-scope", "atomic"))
        if a._is_invalid_void_object_type(declaration.type_spec):
            raise SemaError(a._invalid_object_type_message("file-scope", "void"))
        if declaration.storage_class != "extern" and a._is_invalid_incomplete_record_object_type(
            declaration.type_spec
        ):
            raise SemaError(a._invalid_object_type_message("file-scope", "incomplete"))
        if a._is_file_scope_vla_type_spec(declaration.type_spec):
            raise SemaError("Variable length array not allowed at file scope")
        var_type = a._resolve_type(declaration.type_spec)
        var_alignment = a._alignof_type(var_type)
        if not a._is_valid_explicit_alignment(declaration.alignment, var_alignment):
            assert declaration.alignment is not None
            raise SemaError(
                a._invalid_alignment_message(
                    "file-scope object declaration",
                    declaration.alignment,
                    var_alignment,
                )
            )
        a._ensure_array_size_limit(var_type)
        symbol = VarSymbol(
            declaration.name,
            var_type,
            declaration.alignment if declaration.alignment is not None else var_alignment,
            is_extern=declaration.storage_class == "extern",
        )
        if declaration.init is not None:
            symbol.has_init = True
        a._file_scope.define_file_scope(symbol)
        var_type = symbol.type_
        if declaration.init is not None:
            if declaration.storage_class == "extern":
                raise SemaError(a._extern_initializer_message("file-scope"))
            a._analyze_initializer(var_type, declaration.init, a._file_scope)
            if a._is_const_qualified(var_type):
                symbol.constant_value = a._try_eval_scalar_initializer(
                    declaration.init, a._file_scope
                )
                if isinstance(declaration.init, InitList):
                    symbol._init_expr = declaration.init
            array_bound = var_type.declarator_ops[0][1] if var_type.is_array() else None
            if isinstance(array_bound, int) and array_bound < 0:
                inferred = a._infer_array_size_from_init(declaration.init)
                if inferred is not None:
                    new_ops = (("arr", inferred),) + var_type.declarator_ops[1:]
                    new_type = Type(
                        var_type.name,
                        declarator_ops=new_ops,
                        qualifiers=var_type.qualifiers,
                    )
                    symbol.type_ = new_type
                    var_type = new_type
        return
    if isinstance(declaration, StaticAssertDecl):
        a._check_static_assert(declaration, a._file_scope)
        return
    if isinstance(declaration, NullStmt):
        return  # Empty statement at file scope: nothing to do
    raise SemaError(
        "Unsupported file-scope declaration node: "
        f"{type(declaration).__name__} (internal sema bug: unexpected AST "
        "file-scope declaration node)"
    )
