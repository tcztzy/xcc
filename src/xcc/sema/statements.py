from typing import Any, cast

from xcc.ast import (
    BreakStmt,
    CaseStmt,
    CompoundStmt,
    ContinueStmt,
    DeclGroupStmt,
    DeclStmt,
    DefaultStmt,
    DoWhileStmt,
    Expr,
    ExprStmt,
    ForStmt,
    GotoStmt,
    IfStmt,
    IndirectGotoStmt,
    LabelStmt,
    NullStmt,
    ReturnStmt,
    StaticAssertDecl,
    Stmt,
    SwitchStmt,
    TypedefDecl,
    WhileStmt,
)
from xcc.types import VOID, Type

from .symbols import Scope, SemaError, SwitchContext, VarSymbol


def analyze_stmt(analyzer: object, stmt: Stmt, scope: Scope, return_type: Type) -> None:
    a = cast(Any, analyzer)
    a._current_scope = scope
    if isinstance(stmt, DeclGroupStmt):
        for grouped_decl in stmt.declarations:
            a._analyze_stmt(grouped_decl, scope, return_type)
        return
    if isinstance(stmt, DeclStmt):
        if a._is_function_object_type(stmt.type_spec):
            if stmt.storage_class not in {None, "extern"}:
                storage_class = stmt.storage_class if stmt.storage_class is not None else "<none>"
                raise SemaError(
                    f"Invalid storage class for block-scope function declaration: '{storage_class}'"
                )
            if stmt.is_thread_local:
                raise SemaError(
                    "Invalid declaration specifier for function declaration: '_Thread_local'"
                )
        if stmt.storage_class == "typedef":
            raise SemaError(a._typedef_storage_class_object_message("block-scope"))
        if (
            not a._is_function_object_type(stmt.type_spec)
            and stmt.is_thread_local
            and stmt.storage_class not in {"static", "extern"}
        ):
            raise SemaError(
                a._thread_local_storage_class_message("block-scope", stmt.storage_class)
            )
        a._register_type_spec(stmt.type_spec)
        a._define_enum_members(stmt.type_spec, scope)
        if stmt.alignment is not None and stmt.name is None:
            raise SemaError(a._missing_identifier_for_alignment_message("block-scope", stmt))
        if stmt.name is None:
            if stmt.storage_class is not None or stmt.is_thread_local:
                raise SemaError(a._missing_object_identifier_message("block-scope", stmt))
            return
        if a._is_invalid_atomic_type_spec(stmt.type_spec):
            raise SemaError(a._invalid_object_type_message("block-scope", "atomic"))
        if a._is_invalid_void_object_type(stmt.type_spec):
            raise SemaError(a._invalid_object_type_message("block-scope", "void"))
        if a._is_invalid_incomplete_record_object_type(stmt.type_spec):
            raise SemaError(a._invalid_object_type_message("block-scope", "incomplete"))
        var_type = a._resolve_type(stmt.type_spec)
        var_alignment = a._alignof_type(var_type)
        if not a._is_valid_explicit_alignment(stmt.alignment, var_alignment):
            assert stmt.alignment is not None
            raise SemaError(
                a._invalid_alignment_message(
                    "block-scope object declaration",
                    stmt.alignment,
                    var_alignment,
                )
            )
        a._ensure_array_size_limit(var_type)
        scope.define(
            VarSymbol(
                stmt.name,
                var_type,
                stmt.alignment if stmt.alignment is not None else var_alignment,
                is_extern=stmt.storage_class == "extern",
            )
        )
        if stmt.init is not None:
            if stmt.storage_class == "extern":
                raise SemaError(a._extern_initializer_message("block-scope"))
            a._analyze_initializer(var_type, stmt.init, scope)
        return
    if isinstance(stmt, StaticAssertDecl):
        a._check_static_assert(stmt, scope)
        return
    if isinstance(stmt, TypedefDecl):
        a._register_type_spec(stmt.type_spec)
        if a._is_invalid_atomic_type_spec(stmt.type_spec):
            raise SemaError(a._invalid_typedef_type_message("block-scope"))
        a._define_enum_members(stmt.type_spec, scope)
        typedef_type = a._resolve_type(stmt.type_spec)
        a._ensure_array_size_limit(typedef_type)
        scope.define_typedef(stmt.name, typedef_type)
        return
    if isinstance(stmt, ExprStmt):
        a._analyze_expr(stmt.expr, scope)
        return
    if isinstance(stmt, ReturnStmt):
        if stmt.value is None:
            if return_type is not VOID:
                raise SemaError("Non-void function must return a value")
            return
        if return_type is VOID:
            raise SemaError("Void function should not return a value")
        value_type = a._decay_array_value(a._analyze_expr(stmt.value, scope))
        if not a._is_assignment_expr_compatible(
            return_type,
            stmt.value,
            value_type,
            scope,
        ):
            raise SemaError("Return value is not compatible with function return type")
        return
    if isinstance(stmt, ForStmt):
        inner_scope = Scope(scope)
        if isinstance(stmt.init, Stmt):
            a._analyze_stmt(stmt.init, inner_scope, return_type)
        elif isinstance(stmt.init, Expr):
            a._analyze_expr(stmt.init, inner_scope)
        if stmt.condition is not None:
            a._check_condition_type(a._analyze_expr(stmt.condition, inner_scope))
        if stmt.post is not None:
            a._analyze_expr(stmt.post, inner_scope)
        a._loop_depth += 1
        try:
            a._analyze_stmt(stmt.body, inner_scope, return_type)
        finally:
            a._loop_depth -= 1
        return
    if isinstance(stmt, SwitchStmt):
        a._check_switch_condition_type(a._analyze_expr(stmt.condition, scope))
        a._switch_stack.append(SwitchContext())
        try:
            a._analyze_stmt(stmt.body, scope, return_type)
        finally:
            a._switch_stack.pop()
        return
    if isinstance(stmt, CaseStmt):
        if not a._switch_stack:
            raise SemaError("case not in switch")
        case_value = a._eval_int_constant_expr(stmt.value, scope)
        if case_value is None:
            raise SemaError("case value is not integer constant")
        context = a._switch_stack[-1]
        case_key = str(case_value)
        if case_key in context.case_values:
            raise SemaError("Duplicate case value")
        context.case_values.add(case_key)
        a._analyze_stmt(stmt.body, scope, return_type)
        return
    if isinstance(stmt, DefaultStmt):
        if not a._switch_stack:
            raise SemaError("default not in switch")
        context = a._switch_stack[-1]
        if context.has_default:
            raise SemaError("Duplicate default label")
        context.has_default = True
        a._analyze_stmt(stmt.body, scope, return_type)
        return
    if isinstance(stmt, LabelStmt):
        if stmt.name in a._function_labels:
            raise SemaError(f"Duplicate label: {stmt.name}")
        a._function_labels.add(stmt.name)
        a._analyze_stmt(stmt.body, scope, return_type)
        return
    if isinstance(stmt, GotoStmt):
        a._pending_goto_labels.append(stmt.label)
        return
    if isinstance(stmt, IndirectGotoStmt):
        target_type = a._decay_array_value(a._analyze_expr(stmt.target, scope))
        if target_type.pointee() is None:
            raise SemaError("Indirect goto target must be pointer")
        if not a._is_void_pointer_type(target_type):
            raise SemaError("Indirect goto target must be pointer to void")
        return
    if isinstance(stmt, CompoundStmt):
        inner_scope = Scope(scope)
        a._analyze_compound(stmt, inner_scope, return_type)
        return
    if isinstance(stmt, IfStmt):
        inner_scope = Scope(scope)
        a._check_condition_type(a._analyze_expr(stmt.condition, inner_scope))
        a._analyze_stmt(stmt.then_body, inner_scope, return_type)
        if stmt.else_body is not None:
            a._analyze_stmt(stmt.else_body, inner_scope, return_type)
        return
    if isinstance(stmt, WhileStmt):
        a._check_condition_type(a._analyze_expr(stmt.condition, scope))
        a._loop_depth += 1
        try:
            a._analyze_stmt(stmt.body, scope, return_type)
        finally:
            a._loop_depth -= 1
        return
    if isinstance(stmt, DoWhileStmt):
        a._loop_depth += 1
        try:
            a._analyze_stmt(stmt.body, scope, return_type)
            a._check_condition_type(a._analyze_expr(stmt.condition, scope))
        finally:
            a._loop_depth -= 1
        return
    if isinstance(stmt, BreakStmt):
        if a._loop_depth == 0 and not a._switch_stack:
            raise SemaError("break not in loop")
        return
    if isinstance(stmt, ContinueStmt):
        if a._loop_depth == 0:
            raise SemaError("continue not in loop")
        return
    if isinstance(stmt, NullStmt):
        return
    node_name = type(stmt).__name__
    raise SemaError(
        f"Unsupported statement node: {node_name} (internal sema bug: unexpected "
        "AST statement node)"
    )
