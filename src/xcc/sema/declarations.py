from typing import Any, cast

from xcc.ast import DeclGroupStmt, DeclStmt, StaticAssertDecl, Stmt, TypedefDecl

from .symbols import SemaError, VarSymbol


def analyze_file_scope_decl(analyzer: object, declaration: Stmt) -> None:
    a = cast(Any, analyzer)
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
        if a._is_invalid_incomplete_record_object_type(declaration.type_spec):
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
        a._file_scope.define(
            VarSymbol(
                declaration.name,
                var_type,
                declaration.alignment if declaration.alignment is not None else var_alignment,
                is_extern=declaration.storage_class == "extern",
            )
        )
        if declaration.init is not None:
            if declaration.storage_class == "extern":
                raise SemaError(a._extern_initializer_message("file-scope"))
            a._analyze_initializer(var_type, declaration.init, a._file_scope)
        return
    if isinstance(declaration, StaticAssertDecl):
        a._check_static_assert(declaration, a._file_scope)
        return
    raise SemaError(
        "Unsupported file-scope declaration node: "
        f"{type(declaration).__name__} (internal sema bug: unexpected AST "
        "file-scope declaration node)"
    )
