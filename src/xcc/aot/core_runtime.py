"""Build the native runtime as a symbol-resolved LLVM object model."""

from xcc.aot.llvm_ir import LlvmModule, LlvmParameter, LlvmType

RUNTIME_ALLOC = "__xcc_aot_alloc"
RUNTIME_CALLOC = "__xcc_aot_calloc"
_RUNTIME_PRELUDE_CACHE: list[str] = []


def _declare_runtime(module: LlvmModule) -> None:
    module.add_global(
        "__xcc_aot_fmt_i64", 'private unnamed_addr constant [5 x i8] c"%lld\\00", align 1'
    )
    module.add_global(
        "__xcc_aot_fmt_hex2_upper", 'private unnamed_addr constant [7 x i8] c"%02llX\\00", align 1'
    )
    module.add_global(
        "__xcc_aot_fmt_hex2_lower", 'private unnamed_addr constant [7 x i8] c"%02llx\\00", align 1'
    )
    module.add_global(
        "__xcc_aot_fmt_hex_upper", 'private unnamed_addr constant [5 x i8] c"%llX\\00", align 1'
    )
    module.add_global(
        "__xcc_aot_fmt_hex_lower", 'private unnamed_addr constant [5 x i8] c"%llx\\00", align 1'
    )
    module.add_global(
        "__xcc_aot_fmt_float", 'private unnamed_addr constant [6 x i8] c"%.17g\\00", align 1'
    )
    module.add_global(
        "__xcc_aot_fmt_complex", 'private unnamed_addr constant [9 x i8] c"(%g%+gj)\\00", align 1'
    )
    module.add_global(
        "__xcc_aot_fmt_imaginary", 'private unnamed_addr constant [4 x i8] c"%gj\\00", align 1'
    )
    module.add_global(
        "__xcc_aot_repr_none", 'private unnamed_addr constant [5 x i8] c"None\\00", align 1'
    )
    module.add_global(
        "__xcc_aot_repr_true", 'private unnamed_addr constant [5 x i8] c"True\\00", align 1'
    )
    module.add_global(
        "__xcc_aot_repr_false", 'private unnamed_addr constant [6 x i8] c"False\\00", align 1'
    )
    module.add_global(
        "__xcc_aot_repr_ellipsis", 'private unnamed_addr constant [9 x i8] c"Ellipsis\\00", align 1'
    )
    module.add_global(
        "__xcc_aot_repr_object", 'private unnamed_addr constant [9 x i8] c"<object>\\00", align 1'
    )
    module.add_global("__xcc_aot_object_ellipsis", "private global { i64, i64 } { i64 7, i64 0 }")
    module.add_global(
        "__xcc_aot_fmt_token",
        'private unnamed_addr constant [18 x i8] c"%s:%.*s:%lld:%lld\\00", align 1',
    )
    module.add_global(
        "__xcc_aot_fmt_eof",
        'private unnamed_addr constant [18 x i8] c"%s:None:%lld:%lld\\00", align 1',
    )
    module.add_global(
        "__xcc_aot_fmt_sep", 'private unnamed_addr constant [2 x i8] c"|\\00", align 1'
    )
    module.add_global(
        "__xcc_aot_byteorder_big", 'private unnamed_addr constant [4 x i8] c"big\\00", align 1'
    )
    module.add_global(
        "__xcc_aot_file_mode_read", 'private unnamed_addr constant [2 x i8] c"r\\00", align 1'
    )
    module.add_global(
        "__xcc_aot_file_mode_write", 'private unnamed_addr constant [2 x i8] c"w\\00", align 1'
    )
    module.add_global(
        "__xcc_aot_stderr_path",
        'private unnamed_addr constant [12 x i8] c"/dev/stderr\\00", align 1',
    )
    module.add_global(
        "__xcc_aot_path_dot", 'private unnamed_addr constant [2 x i8] c".\\00", align 1'
    )
    module.add_global(
        "__xcc_aot_path_slash", 'private unnamed_addr constant [2 x i8] c"/\\00", align 1'
    )
    module.add_global(
        "__xcc_aot_kind_keyword", 'private unnamed_addr constant [8 x i8] c"KEYWORD\\00", align 1'
    )
    module.add_global(
        "__xcc_aot_kind_ident", 'private unnamed_addr constant [6 x i8] c"IDENT\\00", align 1'
    )
    module.add_global(
        "__xcc_aot_kind_int_const",
        'private unnamed_addr constant [10 x i8] c"INT_CONST\\00", align 1',
    )
    module.add_global(
        "__xcc_aot_kind_punctuator",
        'private unnamed_addr constant [11 x i8] c"PUNCTUATOR\\00", align 1',
    )
    module.add_global(
        "__xcc_aot_kind_header_name",
        'private unnamed_addr constant [12 x i8] c"HEADER_NAME\\00", align 1',
    )
    module.add_global(
        "__xcc_aot_kind_eof", 'private unnamed_addr constant [4 x i8] c"EOF\\00", align 1'
    )
    module.add_global(
        "__xcc_aot_error_unterminated_string",
        "private unnamed_addr constant [35 x i8] "
        'c"Unterminated string literal at 1:2\\00", align 1',
    )
    module.add_global(
        "__xcc_aot_allocation_limit_message",
        "private unnamed_addr constant [35 x i8] "
        'c"xcc-aot: allocation limit exceeded\\0A", align 1',
    )
    module.add_global(
        "__xcc_aot_memory_safety_message",
        'private unnamed_addr constant [33 x i8] c"xcc-aot: memory safety violation\\0A", align 1',
    )
    module.add_global("__xcc_aot_allocated_bytes", "internal global i64 0")
    module.add_global("__xcc_aot_allocation_limit", "internal constant i64 536870912")
    # Large generated translation units can retain more than 2 GiB while one
    # compiler phase is active. Keep the unscoped 512 MiB guard above, but give
    # the reclaimable phase arena enough headroom for those units.
    module.add_global("__xcc_aot_phase_allocation_limit", "internal constant i64 4294967296")
    module.add_global("__xcc_aot_allocation_head", "internal global ptr null")
    module.add_global(
        "__xcc_aot_phase_allocation_buckets", "internal global [2097152 x ptr] zeroinitializer"
    )
    module.add_global("__xcc_aot_allocation_tag", "internal constant i64 56945")
    module.add_global("__xcc_aot_phase_mark_magic", "internal constant i64 6361702002")
    module.add_global("__xcc_aot_phase_mark_head", "internal global ptr null")
    module.add_global("__xcc_aot_phase_active", "internal global i1 false")
    module.add_global("__xcc_aot_phase_depth", "internal global i64 0")
    module.add_global("__xcc_aot_phase_mark_generation", "internal global i64 0")
    module.add_global("__xcc_aot_phase_promote_target", "internal global ptr null")
    module.add_global("__xcc_aot_phase_promote_cursor", "internal global ptr null")
    module.add_global("__xcc_aot_phase_capture_cache_valid", "internal global i1 false")
    module.add_global("__xcc_aot_phase_capture_cache_owner", "internal global ptr null")
    module.add_global("__xcc_aot_phase_capture_cache_target", "internal global ptr null")
    module.add_global("__xcc_aot_phase_capture_cache_valid_2", "internal global i1 false")
    module.add_global("__xcc_aot_phase_capture_cache_owner_2", "internal global ptr null")
    module.add_global("__xcc_aot_phase_capture_cache_target_2", "internal global ptr null")
    module.add_global(
        "__xcc_aot_phase_promote_cache_payloads", "internal global [1024 x ptr] zeroinitializer"
    )
    module.add_global(
        "__xcc_aot_phase_promote_cache_targets", "internal global [1024 x ptr] zeroinitializer"
    )
    module.add_global(
        "__xcc_aot_phase_promote_cache_states", "internal global [1024 x i64] zeroinitializer"
    )
    module.add_global("__xcc_aot_startswith_text", "internal global ptr null")
    module.add_global("__xcc_aot_startswith_text_len", "internal global i64 0")
    module.add_global("__xcc_aot_startswith_text_2", "internal global ptr null")
    module.add_global("__xcc_aot_startswith_text_len_2", "internal global i64 0")
    module.add_global("__xcc_aot_single_byte_strings", "internal global [512 x i8] zeroinitializer")
    module.add_global("__xcc_aot_dict_state_counter", "internal global i64 0")
    module.add_global(
        "__xcc_aot_string_dict_cache_dicts", "internal global [16384 x ptr] zeroinitializer"
    )
    module.add_global(
        "__xcc_aot_string_dict_cache_keys", "internal global [16384 x ptr] zeroinitializer"
    )
    module.add_global(
        "__xcc_aot_string_dict_cache_hashes", "internal global [16384 x i64] zeroinitializer"
    )
    module.add_global(
        "__xcc_aot_string_dict_cache_states", "internal global [16384 x i64] zeroinitializer"
    )
    module.add_global(
        "__xcc_aot_string_dict_cache_indices", "internal global [16384 x i64] zeroinitializer"
    )
    module.add_global(
        "__xcc_aot_identity_dict_cache_dicts", "internal global [16384 x ptr] zeroinitializer"
    )
    module.add_global(
        "__xcc_aot_identity_dict_cache_keys", "internal global [16384 x ptr] zeroinitializer"
    )
    module.add_global(
        "__xcc_aot_identity_dict_cache_states", "internal global [16384 x i64] zeroinitializer"
    )
    module.add_global(
        "__xcc_aot_identity_dict_cache_indices", "internal global [16384 x i64] zeroinitializer"
    )
    module.declare_function(
        "puts", LlvmType("i32"), (LlvmParameter(LlvmType("ptr"), None),), variadic=False
    )
    module.declare_function(
        "realloc",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), None), LlvmParameter(LlvmType("i64"), None)),
        variadic=False,
    )
    module.declare_function(
        "free", LlvmType("void"), (LlvmParameter(LlvmType("ptr"), None),), variadic=False
    )
    module.declare_function(
        "strlen", LlvmType("i64"), (LlvmParameter(LlvmType("ptr"), None),), variadic=False
    )
    module.declare_function(
        "strtoll",
        LlvmType("i64"),
        (
            LlvmParameter(LlvmType("ptr"), None),
            LlvmParameter(LlvmType("ptr"), None),
            LlvmParameter(LlvmType("i32"), None),
        ),
        variadic=False,
    )
    module.declare_function(
        "memcpy",
        LlvmType("ptr"),
        (
            LlvmParameter(LlvmType("ptr"), None),
            LlvmParameter(LlvmType("ptr"), None),
            LlvmParameter(LlvmType("i64"), None),
        ),
        variadic=False,
    )
    module.declare_function(
        "memmove",
        LlvmType("ptr"),
        (
            LlvmParameter(LlvmType("ptr"), None),
            LlvmParameter(LlvmType("ptr"), None),
            LlvmParameter(LlvmType("i64"), None),
        ),
        variadic=False,
    )
    module.declare_function(
        "memset",
        LlvmType("ptr"),
        (
            LlvmParameter(LlvmType("ptr"), None),
            LlvmParameter(LlvmType("i32"), None),
            LlvmParameter(LlvmType("i64"), None),
        ),
        variadic=False,
    )
    module.declare_function(
        "memcmp",
        LlvmType("i32"),
        (
            LlvmParameter(LlvmType("ptr"), None),
            LlvmParameter(LlvmType("ptr"), None),
            LlvmParameter(LlvmType("i64"), None),
        ),
        variadic=False,
    )
    module.declare_function(
        "strcmp",
        LlvmType("i32"),
        (LlvmParameter(LlvmType("ptr"), None), LlvmParameter(LlvmType("ptr"), None)),
        variadic=False,
    )
    module.declare_function(
        "strncmp",
        LlvmType("i32"),
        (
            LlvmParameter(LlvmType("ptr"), None),
            LlvmParameter(LlvmType("ptr"), None),
            LlvmParameter(LlvmType("i64"), None),
        ),
        variadic=False,
    )
    module.declare_function(
        "snprintf",
        LlvmType("i32"),
        (
            LlvmParameter(LlvmType("ptr"), None),
            LlvmParameter(LlvmType("i64"), None),
            LlvmParameter(LlvmType("ptr"), None),
        ),
        variadic=True,
    )
    module.declare_function("fork", LlvmType("i32"), (), variadic=False)
    module.declare_function(
        "waitpid",
        LlvmType("i32"),
        (
            LlvmParameter(LlvmType("i32"), None),
            LlvmParameter(LlvmType("ptr"), None),
            LlvmParameter(LlvmType("i32"), None),
        ),
        variadic=False,
    )
    module.declare_function(
        "execvp",
        LlvmType("i32"),
        (LlvmParameter(LlvmType("ptr"), None), LlvmParameter(LlvmType("ptr"), None)),
        variadic=False,
    )
    module.declare_function(
        "_exit", LlvmType("void"), (LlvmParameter(LlvmType("i32"), None),), variadic=False
    )
    module.declare_function(
        "fopen",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), None), LlvmParameter(LlvmType("ptr"), None)),
        variadic=False,
    )
    module.declare_function(
        "fread",
        LlvmType("i64"),
        (
            LlvmParameter(LlvmType("ptr"), None),
            LlvmParameter(LlvmType("i64"), None),
            LlvmParameter(LlvmType("i64"), None),
            LlvmParameter(LlvmType("ptr"), None),
        ),
        variadic=False,
    )
    module.declare_function(
        "fwrite",
        LlvmType("i64"),
        (
            LlvmParameter(LlvmType("ptr"), None),
            LlvmParameter(LlvmType("i64"), None),
            LlvmParameter(LlvmType("i64"), None),
            LlvmParameter(LlvmType("ptr"), None),
        ),
        variadic=False,
    )
    module.declare_function(
        "fclose", LlvmType("i32"), (LlvmParameter(LlvmType("ptr"), None),), variadic=False
    )
    module.declare_function(
        "fseek",
        LlvmType("i32"),
        (
            LlvmParameter(LlvmType("ptr"), None),
            LlvmParameter(LlvmType("i64"), None),
            LlvmParameter(LlvmType("i32"), None),
        ),
        variadic=False,
    )
    module.declare_function(
        "ftell", LlvmType("i64"), (LlvmParameter(LlvmType("ptr"), None),), variadic=False
    )
    module.define_function("__xcc_aot_allocation_fail", LlvmType("void"), (), linkage="internal")
    module.define_function("__xcc_aot_memory_safety_fail", LlvmType("void"), (), linkage="internal")
    module.define_function(
        "__xcc_aot_alloc",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("i64"), "requested"),),
        linkage="internal",
    )
    module.define_function(
        "__xcc_aot_calloc",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("i64"), "count"), LlvmParameter(LlvmType("i64"), "item_size")),
        linkage="internal",
    )
    module.define_function(
        "__xcc_aot_phase_allocation_index_insert",
        LlvmType("void"),
        (LlvmParameter(LlvmType("ptr"), "header"), LlvmParameter(LlvmType("ptr"), "payload")),
        linkage="internal",
    )
    module.define_function(
        "__xcc_aot_phase_allocation_index_remove",
        LlvmType("void"),
        (LlvmParameter(LlvmType("ptr"), "header"), LlvmParameter(LlvmType("ptr"), "payload")),
        linkage="internal",
    )
    module.define_function(
        "__xcc_aot_find_allocation",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "payload"),),
        linkage="internal",
    )
    module.define_function(
        "__xcc_aot_realloc",
        LlvmType("ptr"),
        (
            LlvmParameter(LlvmType("ptr"), "old"),
            LlvmParameter(LlvmType("i64"), "old_size"),
            LlvmParameter(LlvmType("i64"), "new_size"),
        ),
        linkage="internal",
    )
    module.define_function(
        "__xcc_aot_free_allocation",
        LlvmType("void"),
        (LlvmParameter(LlvmType("ptr"), "header"), LlvmParameter(LlvmType("ptr"), "payload")),
        linkage="internal",
    )
    module.define_function(
        "__xcc_aot_free", LlvmType("void"), (LlvmParameter(LlvmType("ptr"), "payload"),), linkage=""
    )
    module.define_function(
        "__xcc_aot_phase_promote_cache_contains",
        LlvmType("i1"),
        (LlvmParameter(LlvmType("ptr"), "payload"), LlvmParameter(LlvmType("ptr"), "target")),
        linkage="internal",
    )
    module.define_function(
        "__xcc_aot_phase_promote_cache_store",
        LlvmType("void"),
        (LlvmParameter(LlvmType("ptr"), "payload"), LlvmParameter(LlvmType("ptr"), "target")),
        linkage="internal",
    )
    module.define_function(
        "__xcc_aot_phase_promote_cache_invalidate_payload",
        LlvmType("void"),
        (LlvmParameter(LlvmType("ptr"), "payload"),),
        linkage="internal",
    )
    module.define_function(
        "__xcc_aot_phase_capture_cache_enter", LlvmType("void"), (), linkage="internal"
    )
    module.define_function(
        "__xcc_aot_phase_capture_cache_exit",
        LlvmType("void"),
        (LlvmParameter(LlvmType("ptr"), "mark"),),
        linkage="internal",
    )
    module.define_function(
        "__xcc_aot_phase_capture_cache_store",
        LlvmType("void"),
        (LlvmParameter(LlvmType("ptr"), "owner"), LlvmParameter(LlvmType("ptr"), "target")),
        linkage="internal",
    )
    module.define_function(
        "__xcc_aot_phase_mark_with_mode",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("i1"), "exact"),),
        linkage="internal",
    )
    module.define_function("__xcc_aot_phase_mark", LlvmType("ptr"), (), linkage="")
    module.define_function("__xcc_aot_phase_iteration_mark", LlvmType("ptr"), (), linkage="")
    module.define_function(
        "__xcc_aot_phase_promote",
        LlvmType("i1"),
        (LlvmParameter(LlvmType("ptr"), "payload"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_phase_promote_begin",
        LlvmType("void"),
        (LlvmParameter(LlvmType("ptr"), "target"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_phase_promote_end",
        LlvmType("void"),
        (LlvmParameter(LlvmType("ptr"), "target"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_phase_promote_allocated_to",
        LlvmType("i1"),
        (LlvmParameter(LlvmType("ptr"), "payload"), LlvmParameter(LlvmType("ptr"), "target")),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_phase_promote_to",
        LlvmType("i1"),
        (LlvmParameter(LlvmType("ptr"), "payload"), LlvmParameter(LlvmType("ptr"), "target")),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_phase_capture_allocated_target",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "owner"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_phase_capture_target",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "owner"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_phase_capture_defer",
        LlvmType("i1"),
        (LlvmParameter(LlvmType("ptr"), "target"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_phase_capture_exact",
        LlvmType("void"),
        (LlvmParameter(LlvmType("ptr"), "owner"), LlvmParameter(LlvmType("ptr"), "value")),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_phase_commit",
        LlvmType("void"),
        (LlvmParameter(LlvmType("ptr"), "mark"),),
        linkage="",
    )
    module.define_function("__xcc_aot_phase_allocated_bytes", LlvmType("i64"), (), linkage="")
    module.define_function(
        "__xcc_aot_single_byte_string",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("i8"), "byte"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_phase_reset",
        LlvmType("void"),
        (LlvmParameter(LlvmType("ptr"), "mark"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_phase_finish",
        LlvmType("void"),
        (LlvmParameter(LlvmType("ptr"), "mark"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_object_repr",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "object"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_object_str",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "object"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_complex_new",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("double"), "real"), LlvmParameter(LlvmType("double"), "imaginary")),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_tuple_new",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("i64"), "length"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_tuple_resolve",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "tuple"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_tuple_capacity",
        LlvmType("i64"),
        (LlvmParameter(LlvmType("ptr"), "tuple"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_tuple_register_capacity",
        LlvmType("void"),
        (LlvmParameter(LlvmType("ptr"), "tuple"), LlvmParameter(LlvmType("i64"), "capacity")),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_tuple_forward",
        LlvmType("void"),
        (LlvmParameter(LlvmType("ptr"), "old"), LlvmParameter(LlvmType("ptr"), "new")),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_tuple_append",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "tuple"), LlvmParameter(LlvmType("ptr"), "item")),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_tuple_extend",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "tuple"), LlvmParameter(LlvmType("ptr"), "items")),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_tuple_len",
        LlvmType("i64"),
        (LlvmParameter(LlvmType("ptr"), "tuple"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_tuple_clear",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "tuple"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_tuple_get",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "tuple"), LlvmParameter(LlvmType("i64"), "index")),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_tuple_object_layout_find",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "tuple"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_tuple_object_layout_register",
        LlvmType("void"),
        (
            LlvmParameter(LlvmType("ptr"), "tuple"),
            LlvmParameter(LlvmType("i64"), "count"),
            LlvmParameter(LlvmType("ptr"), "tags"),
        ),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_tuple_object_layout_forward",
        LlvmType("void"),
        (LlvmParameter(LlvmType("ptr"), "old"), LlvmParameter(LlvmType("ptr"), "new")),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_tuple_get_object",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "tuple"), LlvmParameter(LlvmType("i64"), "index")),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_tuple_set",
        LlvmType("void"),
        (
            LlvmParameter(LlvmType("ptr"), "tuple"),
            LlvmParameter(LlvmType("i64"), "index"),
            LlvmParameter(LlvmType("ptr"), "item"),
        ),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_tuple_slice",
        LlvmType("ptr"),
        (
            LlvmParameter(LlvmType("ptr"), "tuple"),
            LlvmParameter(LlvmType("i64"), "start"),
            LlvmParameter(LlvmType("i1"), "has_start"),
            LlvmParameter(LlvmType("i64"), "stop"),
            LlvmParameter(LlvmType("i1"), "has_stop"),
        ),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_string_dict_hash",
        LlvmType("i64"),
        (LlvmParameter(LlvmType("ptr"), "key"),),
        linkage="internal",
    )
    module.define_function(
        "__xcc_aot_dict_bump_state",
        LlvmType("void"),
        (LlvmParameter(LlvmType("ptr"), "dict"),),
        linkage="internal",
    )
    module.define_function(
        "__xcc_aot_dict_state",
        LlvmType("i64"),
        (LlvmParameter(LlvmType("ptr"), "dict"),),
        linkage="internal",
    )
    module.define_function(
        "__xcc_aot_string_dict_cache_bucket",
        LlvmType("i64"),
        (LlvmParameter(LlvmType("ptr"), "dict"), LlvmParameter(LlvmType("i64"), "hash")),
        linkage="internal",
    )
    module.define_function(
        "__xcc_aot_string_dict_cache_store",
        LlvmType("void"),
        (
            LlvmParameter(LlvmType("ptr"), "dict"),
            LlvmParameter(LlvmType("ptr"), "key"),
            LlvmParameter(LlvmType("i64"), "hash"),
            LlvmParameter(LlvmType("i64"), "state"),
            LlvmParameter(LlvmType("i64"), "index"),
        ),
        linkage="internal",
    )
    module.define_function(
        "__xcc_aot_string_dict_find_index",
        LlvmType("i64"),
        (LlvmParameter(LlvmType("ptr"), "dict"), LlvmParameter(LlvmType("ptr"), "key")),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_string_dict_note_index",
        LlvmType("void"),
        (
            LlvmParameter(LlvmType("ptr"), "dict"),
            LlvmParameter(LlvmType("ptr"), "key"),
            LlvmParameter(LlvmType("i64"), "index"),
        ),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_string_tuple_find_index",
        LlvmType("i64"),
        (LlvmParameter(LlvmType("ptr"), "tuple"), LlvmParameter(LlvmType("ptr"), "key")),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_string_tuple_note_index",
        LlvmType("void"),
        (
            LlvmParameter(LlvmType("ptr"), "tuple"),
            LlvmParameter(LlvmType("ptr"), "key"),
            LlvmParameter(LlvmType("i64"), "index"),
        ),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_identity_dict_cache_bucket",
        LlvmType("i64"),
        (LlvmParameter(LlvmType("ptr"), "dict"), LlvmParameter(LlvmType("ptr"), "key")),
        linkage="internal",
    )
    module.define_function(
        "__xcc_aot_identity_dict_cache_store",
        LlvmType("void"),
        (
            LlvmParameter(LlvmType("ptr"), "dict"),
            LlvmParameter(LlvmType("ptr"), "key"),
            LlvmParameter(LlvmType("i64"), "state"),
            LlvmParameter(LlvmType("i64"), "index"),
        ),
        linkage="internal",
    )
    module.define_function(
        "__xcc_aot_identity_dict_find_index",
        LlvmType("i64"),
        (LlvmParameter(LlvmType("ptr"), "dict"), LlvmParameter(LlvmType("ptr"), "key")),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_identity_dict_note_index",
        LlvmType("void"),
        (
            LlvmParameter(LlvmType("ptr"), "dict"),
            LlvmParameter(LlvmType("ptr"), "key"),
            LlvmParameter(LlvmType("i64"), "index"),
        ),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_dict_copy",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "dict"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_dict_keys",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "dict"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_dict_values",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "dict"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_tuple_concat",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "left"), LlvmParameter(LlvmType("ptr"), "right")),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_tuple_repeat",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "tuple"), LlvmParameter(LlvmType("i64"), "count")),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_tuple_pop",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "tuple"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_tuple_pop_item",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "tuple"), LlvmParameter(LlvmType("i64"), "index")),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_tuple_set_slice",
        LlvmType("ptr"),
        (
            LlvmParameter(LlvmType("ptr"), "tuple"),
            LlvmParameter(LlvmType("i64"), "start"),
            LlvmParameter(LlvmType("i1"), "has_start"),
            LlvmParameter(LlvmType("i64"), "stop"),
            LlvmParameter(LlvmType("i1"), "has_stop"),
            LlvmParameter(LlvmType("ptr"), "value"),
        ),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_tuple_reversed",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "tuple"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_range",
        LlvmType("ptr"),
        (
            LlvmParameter(LlvmType("i64"), "start"),
            LlvmParameter(LlvmType("i64"), "stop"),
            LlvmParameter(LlvmType("i64"), "step"),
        ),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_zip2",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "left"), LlvmParameter(LlvmType("ptr"), "right")),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_string_split",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "text"), LlvmParameter(LlvmType("ptr"), "sep")),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_string_split_limit",
        LlvmType("ptr"),
        (
            LlvmParameter(LlvmType("ptr"), "text"),
            LlvmParameter(LlvmType("ptr"), "sep"),
            LlvmParameter(LlvmType("i64"), "maxsplit"),
        ),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_string_rsplit_limit",
        LlvmType("ptr"),
        (
            LlvmParameter(LlvmType("ptr"), "text"),
            LlvmParameter(LlvmType("ptr"), "sep"),
            LlvmParameter(LlvmType("i64"), "maxsplit"),
        ),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_string_split_whitespace",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "text"), LlvmParameter(LlvmType("i64"), "maxsplit")),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_string_splitlines",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "text"), LlvmParameter(LlvmType("i1"), "keepends")),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_string_replace",
        LlvmType("ptr"),
        (
            LlvmParameter(LlvmType("ptr"), "text"),
            LlvmParameter(LlvmType("ptr"), "old"),
            LlvmParameter(LlvmType("ptr"), "new"),
        ),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_string_lower",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "text"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_string_upper",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "text"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_path_parent",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "path"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_path_name",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "path"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_path_join",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "path"), LlvmParameter(LlvmType("ptr"), "child")),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_read_text_file",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "path"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_read_bytes_file",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "path"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_path_is_file",
        LlvmType("i1"),
        (LlvmParameter(LlvmType("ptr"), "path"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_write_text_file",
        LlvmType("i1"),
        (LlvmParameter(LlvmType("ptr"), "path"), LlvmParameter(LlvmType("ptr"), "text")),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_startswith_cache_invalidate",
        LlvmType("void"),
        (LlvmParameter(LlvmType("ptr"), "text"),),
        linkage="internal",
    )
    module.define_function(
        "__xcc_aot_string_len",
        LlvmType("i64"),
        (LlvmParameter(LlvmType("ptr"), "text"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_string_startswith_known_length",
        LlvmType("i1"),
        (
            LlvmParameter(LlvmType("ptr"), "text"),
            LlvmParameter(LlvmType("i64"), "text_len"),
            LlvmParameter(LlvmType("ptr"), "prefix"),
            LlvmParameter(LlvmType("i64"), "start"),
        ),
        linkage="internal",
    )
    module.define_function(
        "__xcc_aot_string_startswith",
        LlvmType("i1"),
        (
            LlvmParameter(LlvmType("ptr"), "text"),
            LlvmParameter(LlvmType("ptr"), "prefix"),
            LlvmParameter(LlvmType("i64"), "start"),
        ),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_string_endswith",
        LlvmType("i1"),
        (LlvmParameter(LlvmType("ptr"), "text"), LlvmParameter(LlvmType("ptr"), "suffix")),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_string_rfind",
        LlvmType("i64"),
        (
            LlvmParameter(LlvmType("ptr"), "text"),
            LlvmParameter(LlvmType("ptr"), "needle"),
            LlvmParameter(LlvmType("i64"), "start"),
            LlvmParameter(LlvmType("i64"), "end"),
        ),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_string_count",
        LlvmType("i64"),
        (
            LlvmParameter(LlvmType("ptr"), "text"),
            LlvmParameter(LlvmType("ptr"), "needle"),
            LlvmParameter(LlvmType("i64"), "start"),
            LlvmParameter(LlvmType("i64"), "end"),
        ),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_string_removeprefix",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "text"), LlvmParameter(LlvmType("ptr"), "prefix")),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_string_removesuffix",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "text"), LlvmParameter(LlvmType("ptr"), "suffix")),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_is_ascii_space",
        LlvmType("i1"),
        (LlvmParameter(LlvmType("i8"), "char8"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_char_in_string",
        LlvmType("i1"),
        (LlvmParameter(LlvmType("i8"), "needle"), LlvmParameter(LlvmType("ptr"), "chars")),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_string_ljust",
        LlvmType("ptr"),
        (
            LlvmParameter(LlvmType("ptr"), "text"),
            LlvmParameter(LlvmType("i64"), "width"),
            LlvmParameter(LlvmType("ptr"), "fill"),
        ),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_string_lstrip",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "text"), LlvmParameter(LlvmType("ptr"), "chars")),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_string_rstrip",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "text"), LlvmParameter(LlvmType("ptr"), "chars")),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_string_strip",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "text"), LlvmParameter(LlvmType("ptr"), "chars")),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_zero_bytes",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("i64"), "size"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_bytes_new",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("i64"), "size"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_bytes_data",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "value"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_bytes_len",
        LlvmType("i64"),
        (LlvmParameter(LlvmType("ptr"), "value"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_bytes_copy",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "source"), LlvmParameter(LlvmType("i64"), "size")),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_bytes_from_ints",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "values"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_bytes_get",
        LlvmType("i64"),
        (LlvmParameter(LlvmType("ptr"), "value"), LlvmParameter(LlvmType("i64"), "index")),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_bytes_equal",
        LlvmType("i1"),
        (LlvmParameter(LlvmType("ptr"), "left"), LlvmParameter(LlvmType("ptr"), "right")),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_string_encode",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "value"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_bytes_concat",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "left"), LlvmParameter(LlvmType("ptr"), "right")),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_bytes_repeat",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "value"), LlvmParameter(LlvmType("i64"), "count")),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_bytes_slice",
        LlvmType("ptr"),
        (
            LlvmParameter(LlvmType("ptr"), "value"),
            LlvmParameter(LlvmType("i64"), "start"),
            LlvmParameter(LlvmType("i64"), "stop"),
        ),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_bytes_ljust",
        LlvmType("ptr"),
        (
            LlvmParameter(LlvmType("ptr"), "value"),
            LlvmParameter(LlvmType("i64"), "width"),
            LlvmParameter(LlvmType("ptr"), "fill"),
        ),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_string_repeat",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "text"), LlvmParameter(LlvmType("i64"), "count")),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_int_to_bytes",
        LlvmType("ptr"),
        (
            LlvmParameter(LlvmType("i64"), "value"),
            LlvmParameter(LlvmType("i64"), "size"),
            LlvmParameter(LlvmType("ptr"), "byteorder"),
        ),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_parse_int",
        LlvmType("i64"),
        (LlvmParameter(LlvmType("ptr"), "text"), LlvmParameter(LlvmType("i64"), "base")),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_string_predicate",
        LlvmType("i1"),
        (LlvmParameter(LlvmType("ptr"), "text"), LlvmParameter(LlvmType("i64"), "mode")),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_c_argv_to_tuple",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("i32"), "argc32"), LlvmParameter(LlvmType("ptr"), "argv")),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_execvp_tuple",
        LlvmType("i32"),
        (LlvmParameter(LlvmType("ptr"), "argv_tuple"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_lexer_translate_source",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "source"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_lexer_append_summary_token",
        LlvmType("i64"),
        (
            LlvmParameter(LlvmType("ptr"), "out"),
            LlvmParameter(LlvmType("i64"), "out_len"),
            LlvmParameter(LlvmType("i64"), "cap"),
            LlvmParameter(LlvmType("i1"), "first"),
            LlvmParameter(LlvmType("ptr"), "kind"),
            LlvmParameter(LlvmType("ptr"), "lexeme"),
            LlvmParameter(LlvmType("i64"), "lex_len"),
            LlvmParameter(LlvmType("i64"), "line"),
            LlvmParameter(LlvmType("i64"), "column"),
        ),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_lexer_append_summary_eof",
        LlvmType("i64"),
        (
            LlvmParameter(LlvmType("ptr"), "out"),
            LlvmParameter(LlvmType("i64"), "out_len"),
            LlvmParameter(LlvmType("i64"), "cap"),
            LlvmParameter(LlvmType("i1"), "first"),
            LlvmParameter(LlvmType("i64"), "line"),
            LlvmParameter(LlvmType("i64"), "column"),
        ),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_lexer_is_alpha",
        LlvmType("i1"),
        (LlvmParameter(LlvmType("i8"), "ch"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_lexer_is_digit",
        LlvmType("i1"),
        (LlvmParameter(LlvmType("i8"), "ch"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_lexer_is_ident_start",
        LlvmType("i1"),
        (LlvmParameter(LlvmType("i8"), "ch"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_lexer_is_ident_part",
        LlvmType("i1"),
        (LlvmParameter(LlvmType("i8"), "ch"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_lexer_keyword_kind",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "start"), LlvmParameter(LlvmType("i64"), "len")),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_lexer_token_summary_for_source",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "source"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_lexer_header_summary_for_source",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "source"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_lexer_error_summary_for_source",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "source"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_i64_to_string",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("i64"), "value"),),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_i64_format_hex2",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("i64"), "value"), LlvmParameter(LlvmType("i1"), "uppercase")),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_string_slice",
        LlvmType("ptr"),
        (
            LlvmParameter(LlvmType("ptr"), "text"),
            LlvmParameter(LlvmType("i64"), "start"),
            LlvmParameter(LlvmType("i64"), "stop"),
        ),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_string_concat2",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "left"), LlvmParameter(LlvmType("ptr"), "right")),
        linkage="",
    )
    module.define_function(
        "__xcc_aot_string_join",
        LlvmType("ptr"),
        (LlvmParameter(LlvmType("ptr"), "separator"), LlvmParameter(LlvmType("ptr"), "values")),
        linkage="",
    )
    module.import_function("malloc")


def _build___xcc_aot_allocation_fail(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_allocation_fail")
    entry = function.append_block("entry")
    entry.emit("stream", "call", " ptr ", module.symbol("fopen"), "(")
    entry.continue_(
        "  ptr ",
        module.symbol("__xcc_aot_stderr_path"),
        ", ptr ",
        module.symbol("__xcc_aot_file_mode_write"),
        ")",
    )
    entry.emit("opened", "icmp", " ne ptr ", function.local("stream"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("opened"),
        ", label ",
        function.local("report"),
        ", label ",
        function.local("exit"),
    )
    report = function.append_block("report")
    report.emit("written", "call", " i64 ", module.symbol("fwrite"), "(")
    report.continue_(
        "  ptr ",
        module.symbol("__xcc_aot_allocation_limit_message"),
        ", i64 1, i64 35, ptr ",
        function.local("stream"),
        ")",
    )
    report.emit(
        "closed", "call", " i32 ", module.symbol("fclose"), "(ptr ", function.local("stream"), ")"
    )
    report.emit(None, "br", " label ", function.local("exit"))
    exit = function.append_block("exit")
    exit.emit(None, "call", " void ", module.symbol("_exit"), "(i32 70)")
    exit.emit(None, "unreachable")


def _build___xcc_aot_memory_safety_fail(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_memory_safety_fail")
    entry = function.append_block("entry")
    entry.emit("stream", "call", " ptr ", module.symbol("fopen"), "(")
    entry.continue_(
        "  ptr ",
        module.symbol("__xcc_aot_stderr_path"),
        ", ptr ",
        module.symbol("__xcc_aot_file_mode_write"),
        ")",
    )
    entry.emit("opened", "icmp", " ne ptr ", function.local("stream"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("opened"),
        ", label ",
        function.local("report"),
        ", label ",
        function.local("exit"),
    )
    report = function.append_block("report")
    report.emit("written", "call", " i64 ", module.symbol("fwrite"), "(")
    report.continue_(
        "  ptr ",
        module.symbol("__xcc_aot_memory_safety_message"),
        ", i64 1, i64 33, ptr ",
        function.local("stream"),
        ")",
    )
    report.emit(
        "closed", "call", " i32 ", module.symbol("fclose"), "(ptr ", function.local("stream"), ")"
    )
    report.emit(None, "br", " label ", function.local("exit"))
    exit = function.append_block("exit")
    exit.emit(None, "call", " void ", module.symbol("_exit"), "(i32 70)")
    exit.emit(None, "unreachable")


def _build___xcc_aot_alloc(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_alloc")
    entry = function.append_block("entry")
    entry.emit("is_zero", "icmp", " eq i64 ", function.local("requested"), ", 0")
    entry.emit(
        "size",
        "select",
        " i1 ",
        function.local("is_zero"),
        ", i64 1, i64 ",
        function.local("requested"),
    )
    entry.emit("phase_active", "load", " i1, ptr ", module.symbol("__xcc_aot_phase_active"))
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("phase_active"),
        ", label ",
        function.local("arena_prepare"),
        ", label ",
        function.local("default_check"),
    )
    default_check = function.append_block("default_check")
    default_check.emit(
        "default_used", "load", " i64, ptr ", module.symbol("__xcc_aot_allocated_bytes")
    )
    default_check.emit(
        "default_limit", "load", " i64, ptr ", module.symbol("__xcc_aot_allocation_limit")
    )
    default_check.emit(
        "default_remaining",
        "sub",
        " i64 ",
        function.local("default_limit"),
        ", ",
        function.local("default_used"),
    )
    default_check.emit(
        "default_over_limit",
        "icmp",
        " ugt i64 ",
        function.local("size"),
        ", ",
        function.local("default_remaining"),
    )
    default_check.emit(
        None,
        "br",
        " i1 ",
        function.local("default_over_limit"),
        ", label ",
        function.local("fail"),
        ", label ",
        function.local("default_allocate"),
    )
    default_allocate = function.append_block("default_allocate")
    default_allocate.emit(
        "default_out",
        "call",
        " ptr ",
        module.symbol("realloc"),
        "(ptr null, i64 ",
        function.local("size"),
        ")",
    )
    default_allocate.emit(
        "default_failed", "icmp", " eq ptr ", function.local("default_out"), ", null"
    )
    default_allocate.emit(
        None,
        "br",
        " i1 ",
        function.local("default_failed"),
        ", label ",
        function.local("fail"),
        ", label ",
        function.local("default_commit"),
    )
    default_commit = function.append_block("default_commit")
    default_commit.emit(
        "default_next_used",
        "add",
        " i64 ",
        function.local("default_used"),
        ", ",
        function.local("size"),
    )
    default_commit.emit(
        None,
        "store",
        " i64 ",
        function.local("default_next_used"),
        ", ptr ",
        module.symbol("__xcc_aot_allocated_bytes"),
    )
    default_commit.emit(None, "ret", " ptr ", function.local("default_out"))
    arena_prepare = function.append_block("arena_prepare")
    arena_prepare.emit("total", "add", " i64 ", function.local("size"), ", 32")
    arena_prepare.emit(
        "wrapped", "icmp", " ult i64 ", function.local("total"), ", ", function.local("size")
    )
    arena_prepare.emit(
        None,
        "br",
        " i1 ",
        function.local("wrapped"),
        ", label ",
        function.local("fail"),
        ", label ",
        function.local("check_limit"),
    )
    check_limit = function.append_block("check_limit")
    check_limit.emit("used", "load", " i64, ptr ", module.symbol("__xcc_aot_allocated_bytes"))
    check_limit.emit(
        "limit", "load", " i64, ptr ", module.symbol("__xcc_aot_phase_allocation_limit")
    )
    check_limit.emit(
        "remaining", "sub", " i64 ", function.local("limit"), ", ", function.local("used")
    )
    check_limit.emit(
        "over_limit",
        "icmp",
        " ugt i64 ",
        function.local("total"),
        ", ",
        function.local("remaining"),
    )
    check_limit.emit(
        None,
        "br",
        " i1 ",
        function.local("over_limit"),
        ", label ",
        function.local("fail"),
        ", label ",
        function.local("allocate"),
    )
    allocate = function.append_block("allocate")
    allocate.emit(
        "header",
        "call",
        " ptr ",
        module.symbol("realloc"),
        "(ptr null, i64 ",
        function.local("total"),
        ")",
    )
    allocate.emit("allocation_failed", "icmp", " eq ptr ", function.local("header"), ", null")
    allocate.emit(
        None,
        "br",
        " i1 ",
        function.local("allocation_failed"),
        ", label ",
        function.local("fail"),
        ", label ",
        function.local("commit"),
    )
    commit = function.append_block("commit")
    commit.emit("previous", "load", " ptr, ptr ", module.symbol("__xcc_aot_allocation_head"))
    commit.emit(
        None, "store", " ptr ", function.local("previous"), ", ptr ", function.local("header")
    )
    commit.emit("next_slot", "getelementptr", " i8, ptr ", function.local("header"), ", i64 8")
    commit.emit(None, "store", " ptr null, ptr ", function.local("next_slot"))
    commit.emit("size_slot", "getelementptr", " i8, ptr ", function.local("header"), ", i64 16")
    commit.emit("depth", "load", " i64, ptr ", module.symbol("__xcc_aot_phase_depth"))
    commit.emit("region_bits", "shl", " i64 ", function.local("depth"), ", 32")
    commit.emit("allocation_tag", "load", " i64, ptr ", module.symbol("__xcc_aot_allocation_tag"))
    commit.emit("tag_bits", "shl", " i64 ", function.local("allocation_tag"), ", 48")
    commit.emit(
        "tagged_region",
        "or",
        " i64 ",
        function.local("tag_bits"),
        ", ",
        function.local("region_bits"),
    )
    commit.emit(
        "tracked_size", "or", " i64 ", function.local("tagged_region"), ", ", function.local("size")
    )
    commit.emit(
        None,
        "store",
        " i64 ",
        function.local("tracked_size"),
        ", ptr ",
        function.local("size_slot"),
    )
    commit.emit(
        "hash_next_slot", "getelementptr", " i8, ptr ", function.local("header"), ", i64 24"
    )
    commit.emit(None, "store", " ptr null, ptr ", function.local("hash_next_slot"))
    commit.emit("has_previous", "icmp", " ne ptr ", function.local("previous"), ", null")
    commit.emit(
        None,
        "br",
        " i1 ",
        function.local("has_previous"),
        ", label ",
        function.local("link_previous"),
        ", label ",
        function.local("finish"),
    )
    link_previous = function.append_block("link_previous")
    link_previous.emit(
        "previous_next", "getelementptr", " i8, ptr ", function.local("previous"), ", i64 8"
    )
    link_previous.emit(
        None, "store", " ptr ", function.local("header"), ", ptr ", function.local("previous_next")
    )
    link_previous.emit(None, "br", " label ", function.local("finish"))
    finish = function.append_block("finish")
    finish.emit(
        None,
        "store",
        " ptr ",
        function.local("header"),
        ", ptr ",
        module.symbol("__xcc_aot_allocation_head"),
    )
    finish.emit("next_used", "add", " i64 ", function.local("used"), ", ", function.local("total"))
    finish.emit(
        None,
        "store",
        " i64 ",
        function.local("next_used"),
        ", ptr ",
        module.symbol("__xcc_aot_allocated_bytes"),
    )
    finish.emit("payload", "getelementptr", " i8, ptr ", function.local("header"), ", i64 32")
    finish.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_phase_allocation_index_insert"),
        "(    ptr ",
        function.local("header"),
        ", ptr ",
        function.local("payload"),
        ")",
    )
    finish.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_phase_promote_cache_invalidate_payload"),
        "(ptr ",
        function.local("payload"),
        ")",
    )
    finish.emit(None, "ret", " ptr ", function.local("payload"))
    fail = function.append_block("fail")
    fail.emit(None, "call", " void ", module.symbol("__xcc_aot_allocation_fail"), "()")
    fail.emit(None, "unreachable")


def _build___xcc_aot_calloc(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_calloc")
    entry = function.append_block("entry")
    entry.emit("count_is_zero", "icmp", " eq i64 ", function.local("count"), ", 0")
    entry.emit(
        "safe_count",
        "select",
        " i1 ",
        function.local("count_is_zero"),
        ", i64 1, i64 ",
        function.local("count"),
    )
    entry.emit("total", "mul", " i64 ", function.local("count"), ", ", function.local("item_size"))
    entry.emit(
        "roundtrip", "udiv", " i64 ", function.local("total"), ", ", function.local("safe_count")
    )
    entry.emit(
        "product_mismatch",
        "icmp",
        " ne i64 ",
        function.local("roundtrip"),
        ", ",
        function.local("item_size"),
    )
    entry.emit("count_nonzero", "xor", " i1 ", function.local("count_is_zero"), ", true")
    entry.emit(
        "overflow",
        "and",
        " i1 ",
        function.local("product_mismatch"),
        ", ",
        function.local("count_nonzero"),
    )
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("overflow"),
        ", label ",
        function.local("fail"),
        ", label ",
        function.local("allocate"),
    )
    allocate = function.append_block("allocate")
    allocate.emit(
        "out",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_alloc"),
        "(i64 ",
        function.local("total"),
        ")",
    )
    allocate.emit(
        "cleared",
        "call",
        " ptr ",
        module.symbol("memset"),
        "(ptr ",
        function.local("out"),
        ", i32 0, i64 ",
        function.local("total"),
        ")",
    )
    allocate.emit(None, "ret", " ptr ", function.local("out"))
    fail = function.append_block("fail")
    fail.emit(None, "call", " void ", module.symbol("__xcc_aot_allocation_fail"), "()")
    fail.emit(None, "unreachable")


def _build___xcc_aot_phase_allocation_index_insert(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_phase_allocation_index_insert")
    entry = function.append_block("entry")
    entry.emit("size_slot", "getelementptr", " i8, ptr ", function.local("header"), ", i64 16")
    entry.emit("tracked_size", "load", " i64, ptr ", function.local("size_slot"))
    entry.emit("tag", "lshr", " i64 ", function.local("tracked_size"), ", 48")
    entry.emit("allocation_tag", "load", " i64, ptr ", module.symbol("__xcc_aot_allocation_tag"))
    entry.emit(
        "valid", "icmp", " eq i64 ", function.local("tag"), ", ", function.local("allocation_tag")
    )
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("valid"),
        ", label ",
        function.local("insert"),
        ", label ",
        function.local("corrupt"),
    )
    insert = function.append_block("insert")
    insert.emit("key", "ptrtoint", " ptr ", function.local("payload"), " to i64")
    insert.emit("aligned", "lshr", " i64 ", function.local("key"), ", 4")
    insert.emit("high", "lshr", " i64 ", function.local("aligned"), ", 21")
    insert.emit("mixed", "xor", " i64 ", function.local("aligned"), ", ", function.local("high"))
    insert.emit("index", "and", " i64 ", function.local("mixed"), ", 2097151")
    insert.emit(
        "bucket",
        "getelementptr",
        " [2097152 x ptr], ptr ",
        module.symbol("__xcc_aot_phase_allocation_buckets"),
        ", i64 0, i64 ",
        function.local("index"),
    )
    insert.emit("head", "load", " ptr, ptr ", function.local("bucket"))
    insert.emit("next_slot", "getelementptr", " i8, ptr ", function.local("header"), ", i64 24")
    insert.emit(
        None, "store", " ptr ", function.local("head"), ", ptr ", function.local("next_slot")
    )
    insert.emit(
        None, "store", " ptr ", function.local("header"), ", ptr ", function.local("bucket")
    )
    insert.emit(None, "ret", " void")
    corrupt = function.append_block("corrupt")
    corrupt.emit(None, "call", " void ", module.symbol("__xcc_aot_memory_safety_fail"), "()")
    corrupt.emit(None, "unreachable")


def _build___xcc_aot_phase_allocation_index_remove(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_phase_allocation_index_remove")
    entry = function.append_block("entry")
    entry.emit("key", "ptrtoint", " ptr ", function.local("payload"), " to i64")
    entry.emit("aligned", "lshr", " i64 ", function.local("key"), ", 4")
    entry.emit("high", "lshr", " i64 ", function.local("aligned"), ", 21")
    entry.emit("mixed", "xor", " i64 ", function.local("aligned"), ", ", function.local("high"))
    entry.emit("index", "and", " i64 ", function.local("mixed"), ", 2097151")
    entry.emit(
        "bucket",
        "getelementptr",
        " [2097152 x ptr], ptr ",
        module.symbol("__xcc_aot_phase_allocation_buckets"),
        ", i64 0, i64 ",
        function.local("index"),
    )
    entry.emit("head", "load", " ptr, ptr ", function.local("bucket"))
    entry.emit(None, "br", " label ", function.local("search"))
    search = function.append_block("search")
    search.emit(
        "node",
        "phi",
        " ptr [ ",
        function.local("head"),
        ", ",
        function.local("entry"),
        " ], [ ",
        function.local("next"),
        ", ",
        function.local("advance"),
        " ]",
    )
    search.emit(
        "previous",
        "phi",
        " ptr [ null, ",
        function.local("entry"),
        " ], [ ",
        function.local("node"),
        ", ",
        function.local("advance"),
        " ]",
    )
    search.emit("exists", "icmp", " ne ptr ", function.local("node"), ", null")
    search.emit(
        None,
        "br",
        " i1 ",
        function.local("exists"),
        ", label ",
        function.local("inspect"),
        ", label ",
        function.local("corrupt"),
    )
    inspect = function.append_block("inspect")
    inspect.emit("size_slot", "getelementptr", " i8, ptr ", function.local("node"), ", i64 16")
    inspect.emit("tracked_size", "load", " i64, ptr ", function.local("size_slot"))
    inspect.emit("tag", "lshr", " i64 ", function.local("tracked_size"), ", 48")
    inspect.emit("allocation_tag", "load", " i64, ptr ", module.symbol("__xcc_aot_allocation_tag"))
    inspect.emit(
        "valid", "icmp", " eq i64 ", function.local("tag"), ", ", function.local("allocation_tag")
    )
    inspect.emit(
        None,
        "br",
        " i1 ",
        function.local("valid"),
        ", label ",
        function.local("compare"),
        ", label ",
        function.local("corrupt"),
    )
    compare = function.append_block("compare")
    compare.emit(
        "matches", "icmp", " eq ptr ", function.local("node"), ", ", function.local("header")
    )
    compare.emit(
        None,
        "br",
        " i1 ",
        function.local("matches"),
        ", label ",
        function.local("unlink"),
        ", label ",
        function.local("advance"),
    )
    advance = function.append_block("advance")
    advance.emit("next_slot", "getelementptr", " i8, ptr ", function.local("node"), ", i64 24")
    advance.emit("next", "load", " ptr, ptr ", function.local("next_slot"))
    advance.emit(None, "br", " label ", function.local("search"))
    unlink = function.append_block("unlink")
    unlink.emit("found_next_slot", "getelementptr", " i8, ptr ", function.local("node"), ", i64 24")
    unlink.emit("found_next", "load", " ptr, ptr ", function.local("found_next_slot"))
    unlink.emit("has_previous", "icmp", " ne ptr ", function.local("previous"), ", null")
    unlink.emit(
        None,
        "br",
        " i1 ",
        function.local("has_previous"),
        ", label ",
        function.local("unlink_previous"),
        ", label ",
        function.local("unlink_head"),
    )
    unlink_previous = function.append_block("unlink_previous")
    unlink_previous.emit(
        "previous_next_slot", "getelementptr", " i8, ptr ", function.local("previous"), ", i64 24"
    )
    unlink_previous.emit(
        None,
        "store",
        " ptr ",
        function.local("found_next"),
        ", ptr ",
        function.local("previous_next_slot"),
    )
    unlink_previous.emit(None, "br", " label ", function.local("done"))
    unlink_head = function.append_block("unlink_head")
    unlink_head.emit(
        None, "store", " ptr ", function.local("found_next"), ", ptr ", function.local("bucket")
    )
    unlink_head.emit(None, "br", " label ", function.local("done"))
    done = function.append_block("done")
    done.emit(None, "store", " ptr null, ptr ", function.local("found_next_slot"))
    done.emit(None, "ret", " void")
    corrupt = function.append_block("corrupt")
    corrupt.emit(None, "call", " void ", module.symbol("__xcc_aot_memory_safety_fail"), "()")
    corrupt.emit(None, "unreachable")


def _build___xcc_aot_find_allocation(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_find_allocation")
    entry = function.append_block("entry")
    entry.emit("key", "ptrtoint", " ptr ", function.local("payload"), " to i64")
    entry.emit("aligned", "lshr", " i64 ", function.local("key"), ", 4")
    entry.emit("high", "lshr", " i64 ", function.local("aligned"), ", 21")
    entry.emit("mixed", "xor", " i64 ", function.local("aligned"), ", ", function.local("high"))
    entry.emit("index", "and", " i64 ", function.local("mixed"), ", 2097151")
    entry.emit(
        "bucket",
        "getelementptr",
        " [2097152 x ptr], ptr ",
        module.symbol("__xcc_aot_phase_allocation_buckets"),
        ", i64 0, i64 ",
        function.local("index"),
    )
    entry.emit("head", "load", " ptr, ptr ", function.local("bucket"))
    entry.emit(None, "br", " label ", function.local("search"))
    search = function.append_block("search")
    search.emit(
        "node",
        "phi",
        " ptr [ ",
        function.local("head"),
        ", ",
        function.local("entry"),
        " ], [ ",
        function.local("next"),
        ", ",
        function.local("advance"),
        " ]",
    )
    search.emit("exists", "icmp", " ne ptr ", function.local("node"), ", null")
    search.emit(
        None,
        "br",
        " i1 ",
        function.local("exists"),
        ", label ",
        function.local("inspect"),
        ", label ",
        function.local("not_found"),
    )
    inspect = function.append_block("inspect")
    inspect.emit("size_slot", "getelementptr", " i8, ptr ", function.local("node"), ", i64 16")
    inspect.emit("tracked_size", "load", " i64, ptr ", function.local("size_slot"))
    inspect.emit("tag", "lshr", " i64 ", function.local("tracked_size"), ", 48")
    inspect.emit("allocation_tag", "load", " i64, ptr ", module.symbol("__xcc_aot_allocation_tag"))
    inspect.emit(
        "valid", "icmp", " eq i64 ", function.local("tag"), ", ", function.local("allocation_tag")
    )
    inspect.emit(
        None,
        "br",
        " i1 ",
        function.local("valid"),
        ", label ",
        function.local("compare"),
        ", label ",
        function.local("corrupt"),
    )
    compare = function.append_block("compare")
    compare.emit("candidate", "getelementptr", " i8, ptr ", function.local("node"), ", i64 32")
    compare.emit(
        "matches", "icmp", " eq ptr ", function.local("candidate"), ", ", function.local("payload")
    )
    compare.emit(
        None,
        "br",
        " i1 ",
        function.local("matches"),
        ", label ",
        function.local("found"),
        ", label ",
        function.local("advance"),
    )
    advance = function.append_block("advance")
    advance.emit("next_slot", "getelementptr", " i8, ptr ", function.local("node"), ", i64 24")
    advance.emit("next", "load", " ptr, ptr ", function.local("next_slot"))
    advance.emit(None, "br", " label ", function.local("search"))
    found = function.append_block("found")
    found.emit(None, "ret", " ptr ", function.local("node"))
    not_found = function.append_block("not_found")
    not_found.emit(None, "ret", " ptr null")
    corrupt = function.append_block("corrupt")
    corrupt.emit(None, "call", " void ", module.symbol("__xcc_aot_memory_safety_fail"), "()")
    corrupt.emit(None, "unreachable")


def _build___xcc_aot_realloc(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_realloc")
    entry = function.append_block("entry")
    entry.emit("old_is_null", "icmp", " eq ptr ", function.local("old"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("old_is_null"),
        ", label ",
        function.local("select_allocator"),
        ", label ",
        function.local("locate"),
    )
    select_allocator = function.append_block("select_allocator")
    select_allocator.emit(
        "phase_active", "load", " i1, ptr ", module.symbol("__xcc_aot_phase_active")
    )
    select_allocator.emit(
        None,
        "br",
        " i1 ",
        function.local("phase_active"),
        ", label ",
        function.local("allocate_new"),
        ", label ",
        function.local("default_prepare"),
    )
    allocate_new = function.append_block("allocate_new")
    allocate_new.emit(
        "created",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_alloc"),
        "(i64 ",
        function.local("new_size"),
        ")",
    )
    allocate_new.emit(None, "ret", " ptr ", function.local("created"))
    locate = function.append_block("locate")
    locate.emit(
        "header",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_find_allocation"),
        "(ptr ",
        function.local("old"),
        ")",
    )
    locate.emit("is_phase_allocation", "icmp", " ne ptr ", function.local("header"), ", null")
    locate.emit(
        None,
        "br",
        " i1 ",
        function.local("is_phase_allocation"),
        ", label ",
        function.local("prepare"),
        ", label ",
        function.local("default_prepare"),
    )
    default_prepare = function.append_block("default_prepare")
    default_prepare.emit(
        "default_new_is_zero", "icmp", " eq i64 ", function.local("new_size"), ", 0"
    )
    default_prepare.emit(
        "default_new_size",
        "select",
        " i1 ",
        function.local("default_new_is_zero"),
        ", i64 1, i64 ",
        function.local("new_size"),
    )
    default_prepare.emit(
        "default_growing",
        "icmp",
        " ugt i64 ",
        function.local("default_new_size"),
        ", ",
        function.local("old_size"),
    )
    default_prepare.emit(
        "default_growth",
        "sub",
        " i64 ",
        function.local("default_new_size"),
        ", ",
        function.local("old_size"),
    )
    default_prepare.emit(
        "default_used", "load", " i64, ptr ", module.symbol("__xcc_aot_allocated_bytes")
    )
    default_prepare.emit(
        "default_limit", "load", " i64, ptr ", module.symbol("__xcc_aot_allocation_limit")
    )
    default_prepare.emit(
        "default_remaining",
        "sub",
        " i64 ",
        function.local("default_limit"),
        ", ",
        function.local("default_used"),
    )
    default_prepare.emit(
        "default_over_limit",
        "icmp",
        " ugt i64 ",
        function.local("default_growth"),
        ", ",
        function.local("default_remaining"),
    )
    default_prepare.emit(
        "default_rejected",
        "and",
        " i1 ",
        function.local("default_growing"),
        ", ",
        function.local("default_over_limit"),
    )
    default_prepare.emit(
        None,
        "br",
        " i1 ",
        function.local("default_rejected"),
        ", label ",
        function.local("fail"),
        ", label ",
        function.local("default_resize"),
    )
    default_resize = function.append_block("default_resize")
    default_resize.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_startswith_cache_invalidate"),
        "(ptr ",
        function.local("old"),
        ")",
    )
    default_resize.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_phase_promote_cache_invalidate_payload"),
        "(ptr ",
        function.local("old"),
        ")",
    )
    default_resize.emit(
        "default_out",
        "call",
        " ptr ",
        module.symbol("realloc"),
        "(ptr ",
        function.local("old"),
        ", i64 ",
        function.local("default_new_size"),
        ")",
    )
    default_resize.emit(
        "default_failed", "icmp", " eq ptr ", function.local("default_out"), ", null"
    )
    default_resize.emit(
        None,
        "br",
        " i1 ",
        function.local("default_failed"),
        ", label ",
        function.local("fail"),
        ", label ",
        function.local("default_commit"),
    )
    default_commit = function.append_block("default_commit")
    default_commit.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_phase_promote_cache_invalidate_payload"),
        "(ptr ",
        function.local("default_out"),
        ")",
    )
    default_commit.emit(
        "default_current", "load", " i64, ptr ", module.symbol("__xcc_aot_allocated_bytes")
    )
    default_commit.emit(
        "default_without_old",
        "sub",
        " i64 ",
        function.local("default_current"),
        ", ",
        function.local("old_size"),
    )
    default_commit.emit(
        "default_next_used",
        "add",
        " i64 ",
        function.local("default_without_old"),
        ", ",
        function.local("default_new_size"),
    )
    default_commit.emit(
        None,
        "store",
        " i64 ",
        function.local("default_next_used"),
        ", ptr ",
        module.symbol("__xcc_aot_allocated_bytes"),
    )
    default_commit.emit(None, "ret", " ptr ", function.local("default_out"))
    prepare = function.append_block("prepare")
    prepare.emit("new_is_zero", "icmp", " eq i64 ", function.local("new_size"), ", 0")
    prepare.emit(
        "normalized_new_size",
        "select",
        " i1 ",
        function.local("new_is_zero"),
        ", i64 1, i64 ",
        function.local("new_size"),
    )
    prepare.emit("new_total", "add", " i64 ", function.local("normalized_new_size"), ", 32")
    prepare.emit(
        "wrapped",
        "icmp",
        " ult i64 ",
        function.local("new_total"),
        ", ",
        function.local("normalized_new_size"),
    )
    prepare.emit(
        None,
        "br",
        " i1 ",
        function.local("wrapped"),
        ", label ",
        function.local("fail"),
        ", label ",
        function.local("check_growth"),
    )
    check_growth = function.append_block("check_growth")
    check_growth.emit(
        "size_slot", "getelementptr", " i8, ptr ", function.local("header"), ", i64 16"
    )
    check_growth.emit("tracked_old", "load", " i64, ptr ", function.local("size_slot"))
    check_growth.emit(
        "tracked_old_size", "and", " i64 ", function.local("tracked_old"), ", 4294967295"
    )
    check_growth.emit(
        "tracked_region", "and", " i64 ", function.local("tracked_old"), ", -4294967296"
    )
    check_growth.emit("old_total", "add", " i64 ", function.local("tracked_old_size"), ", 32")
    check_growth.emit(
        "growing",
        "icmp",
        " ugt i64 ",
        function.local("new_total"),
        ", ",
        function.local("old_total"),
    )
    check_growth.emit(
        "growth", "sub", " i64 ", function.local("new_total"), ", ", function.local("old_total")
    )
    check_growth.emit("used", "load", " i64, ptr ", module.symbol("__xcc_aot_allocated_bytes"))
    check_growth.emit(
        "limit", "load", " i64, ptr ", module.symbol("__xcc_aot_phase_allocation_limit")
    )
    check_growth.emit(
        "remaining", "sub", " i64 ", function.local("limit"), ", ", function.local("used")
    )
    check_growth.emit(
        "over_limit",
        "icmp",
        " ugt i64 ",
        function.local("growth"),
        ", ",
        function.local("remaining"),
    )
    check_growth.emit(
        "growth_rejected",
        "and",
        " i1 ",
        function.local("growing"),
        ", ",
        function.local("over_limit"),
    )
    check_growth.emit(
        None,
        "br",
        " i1 ",
        function.local("growth_rejected"),
        ", label ",
        function.local("fail"),
        ", label ",
        function.local("resize"),
    )
    resize = function.append_block("resize")
    resize.emit("previous", "load", " ptr, ptr ", function.local("header"))
    resize.emit("next_slot", "getelementptr", " i8, ptr ", function.local("header"), ", i64 8")
    resize.emit("newer", "load", " ptr, ptr ", function.local("next_slot"))
    resize.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_startswith_cache_invalidate"),
        "(ptr ",
        function.local("old"),
        ")",
    )
    resize.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_phase_promote_cache_invalidate_payload"),
        "(ptr ",
        function.local("old"),
        ")",
    )
    resize.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_phase_allocation_index_remove"),
        "(    ptr ",
        function.local("header"),
        ", ptr ",
        function.local("old"),
        ")",
    )
    resize.emit(
        "resized_header",
        "call",
        " ptr ",
        module.symbol("realloc"),
        "(ptr ",
        function.local("header"),
        ", i64 ",
        function.local("new_total"),
        ")",
    )
    resize.emit("allocation_failed", "icmp", " eq ptr ", function.local("resized_header"), ", null")
    resize.emit(
        None,
        "br",
        " i1 ",
        function.local("allocation_failed"),
        ", label ",
        function.local("fail"),
        ", label ",
        function.local("commit"),
    )
    commit = function.append_block("commit")
    commit.emit(
        None,
        "store",
        " ptr ",
        function.local("previous"),
        ", ptr ",
        function.local("resized_header"),
    )
    commit.emit(
        "resized_next_slot",
        "getelementptr",
        " i8, ptr ",
        function.local("resized_header"),
        ", i64 8",
    )
    commit.emit(
        None,
        "store",
        " ptr ",
        function.local("newer"),
        ", ptr ",
        function.local("resized_next_slot"),
    )
    commit.emit(
        "resized_size_slot",
        "getelementptr",
        " i8, ptr ",
        function.local("resized_header"),
        ", i64 16",
    )
    commit.emit(
        "resized_tracked",
        "or",
        " i64 ",
        function.local("tracked_region"),
        ", ",
        function.local("normalized_new_size"),
    )
    commit.emit(
        None,
        "store",
        " i64 ",
        function.local("resized_tracked"),
        ", ptr ",
        function.local("resized_size_slot"),
    )
    commit.emit("has_previous", "icmp", " ne ptr ", function.local("previous"), ", null")
    commit.emit(
        None,
        "br",
        " i1 ",
        function.local("has_previous"),
        ", label ",
        function.local("repair_previous"),
        ", label ",
        function.local("check_newer"),
    )
    repair_previous = function.append_block("repair_previous")
    repair_previous.emit(
        "previous_next", "getelementptr", " i8, ptr ", function.local("previous"), ", i64 8"
    )
    repair_previous.emit(
        None,
        "store",
        " ptr ",
        function.local("resized_header"),
        ", ptr ",
        function.local("previous_next"),
    )
    repair_previous.emit(None, "br", " label ", function.local("check_newer"))
    check_newer = function.append_block("check_newer")
    check_newer.emit("has_newer", "icmp", " ne ptr ", function.local("newer"), ", null")
    check_newer.emit(
        None,
        "br",
        " i1 ",
        function.local("has_newer"),
        ", label ",
        function.local("repair_newer"),
        ", label ",
        function.local("repair_head"),
    )
    repair_newer = function.append_block("repair_newer")
    repair_newer.emit(
        None, "store", " ptr ", function.local("resized_header"), ", ptr ", function.local("newer")
    )
    repair_newer.emit(None, "br", " label ", function.local("finish"))
    repair_head = function.append_block("repair_head")
    repair_head.emit(
        None,
        "store",
        " ptr ",
        function.local("resized_header"),
        ", ptr ",
        module.symbol("__xcc_aot_allocation_head"),
    )
    repair_head.emit(None, "br", " label ", function.local("finish"))
    finish = function.append_block("finish")
    finish.emit("current", "load", " i64, ptr ", module.symbol("__xcc_aot_allocated_bytes"))
    finish.emit(
        "without_old", "sub", " i64 ", function.local("current"), ", ", function.local("old_total")
    )
    finish.emit(
        "next_used",
        "add",
        " i64 ",
        function.local("without_old"),
        ", ",
        function.local("new_total"),
    )
    finish.emit(
        None,
        "store",
        " i64 ",
        function.local("next_used"),
        ", ptr ",
        module.symbol("__xcc_aot_allocated_bytes"),
    )
    finish.emit(
        "resized_hash_next_slot",
        "getelementptr",
        " i8, ptr ",
        function.local("resized_header"),
        ", i64 24",
    )
    finish.emit(None, "store", " ptr null, ptr ", function.local("resized_hash_next_slot"))
    finish.emit(
        "payload", "getelementptr", " i8, ptr ", function.local("resized_header"), ", i64 32"
    )
    finish.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_phase_allocation_index_insert"),
        "(    ptr ",
        function.local("resized_header"),
        ", ptr ",
        function.local("payload"),
        ")",
    )
    finish.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_phase_promote_cache_invalidate_payload"),
        "(ptr ",
        function.local("payload"),
        ")",
    )
    finish.emit(None, "ret", " ptr ", function.local("payload"))
    fail = function.append_block("fail")
    fail.emit(None, "call", " void ", module.symbol("__xcc_aot_allocation_fail"), "()")
    fail.emit(None, "unreachable")


def _build___xcc_aot_free_allocation(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_free_allocation")
    entry = function.append_block("entry")
    entry.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_phase_allocation_index_remove"),
        "(    ptr ",
        function.local("header"),
        ", ptr ",
        function.local("payload"),
        ")",
    )
    entry.emit("size_slot", "getelementptr", " i8, ptr ", function.local("header"), ", i64 16")
    entry.emit("tracked_size", "load", " i64, ptr ", function.local("size_slot"))
    entry.emit("size", "and", " i64 ", function.local("tracked_size"), ", 4294967295")
    entry.emit("total", "add", " i64 ", function.local("size"), ", 32")
    entry.emit("used", "load", " i64, ptr ", module.symbol("__xcc_aot_allocated_bytes"))
    entry.emit(
        "account_valid", "icmp", " uge i64 ", function.local("used"), ", ", function.local("total")
    )
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("account_valid"),
        ", label ",
        function.local("unlink_newer"),
        ", label ",
        function.local("fail"),
    )
    unlink_newer = function.append_block("unlink_newer")
    unlink_newer.emit("previous", "load", " ptr, ptr ", function.local("header"))
    unlink_newer.emit(
        "next_slot", "getelementptr", " i8, ptr ", function.local("header"), ", i64 8"
    )
    unlink_newer.emit("newer", "load", " ptr, ptr ", function.local("next_slot"))
    unlink_newer.emit("has_newer", "icmp", " ne ptr ", function.local("newer"), ", null")
    unlink_newer.emit(
        None,
        "br",
        " i1 ",
        function.local("has_newer"),
        ", label ",
        function.local("repair_newer"),
        ", label ",
        function.local("repair_head"),
    )
    repair_newer = function.append_block("repair_newer")
    repair_newer.emit(
        None, "store", " ptr ", function.local("previous"), ", ptr ", function.local("newer")
    )
    repair_newer.emit(None, "br", " label ", function.local("unlink_previous"))
    repair_head = function.append_block("repair_head")
    repair_head.emit(
        None,
        "store",
        " ptr ",
        function.local("previous"),
        ", ptr ",
        module.symbol("__xcc_aot_allocation_head"),
    )
    repair_head.emit(None, "br", " label ", function.local("unlink_previous"))
    unlink_previous = function.append_block("unlink_previous")
    unlink_previous.emit("has_previous", "icmp", " ne ptr ", function.local("previous"), ", null")
    unlink_previous.emit(
        None,
        "br",
        " i1 ",
        function.local("has_previous"),
        ", label ",
        function.local("repair_previous"),
        ", label ",
        function.local("account"),
    )
    repair_previous = function.append_block("repair_previous")
    repair_previous.emit(
        "previous_next", "getelementptr", " i8, ptr ", function.local("previous"), ", i64 8"
    )
    repair_previous.emit(
        None, "store", " ptr ", function.local("newer"), ", ptr ", function.local("previous_next")
    )
    repair_previous.emit(None, "br", " label ", function.local("account"))
    account = function.append_block("account")
    account.emit("remaining", "sub", " i64 ", function.local("used"), ", ", function.local("total"))
    account.emit(
        None,
        "store",
        " i64 ",
        function.local("remaining"),
        ", ptr ",
        module.symbol("__xcc_aot_allocated_bytes"),
    )
    account.emit(None, "store", " i64 0, ptr ", function.local("size_slot"))
    account.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_startswith_cache_invalidate"),
        "(ptr ",
        function.local("payload"),
        ")",
    )
    account.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_phase_promote_cache_invalidate_payload"),
        "(ptr ",
        function.local("payload"),
        ")",
    )
    account.emit(
        None, "call", " void ", module.symbol("free"), "(ptr ", function.local("header"), ")"
    )
    account.emit(None, "ret", " void")
    fail = function.append_block("fail")
    fail.emit(None, "call", " void ", module.symbol("__xcc_aot_memory_safety_fail"), "()")
    fail.emit(None, "unreachable")


def _build___xcc_aot_free(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_free")
    entry = function.append_block("entry")
    entry.emit("is_null", "icmp", " eq ptr ", function.local("payload"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("is_null"),
        ", label ",
        function.local("done"),
        ", label ",
        function.local("validate"),
    )
    validate = function.append_block("validate")
    validate.emit(
        "header",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_find_allocation"),
        "(ptr ",
        function.local("payload"),
        ")",
    )
    validate.emit("found", "icmp", " ne ptr ", function.local("header"), ", null")
    validate.emit(
        None,
        "br",
        " i1 ",
        function.local("found"),
        ", label ",
        function.local("release"),
        ", label ",
        function.local("fail"),
    )
    release = function.append_block("release")
    release.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_free_allocation"),
        "(ptr ",
        function.local("header"),
        ", ptr ",
        function.local("payload"),
        ")",
    )
    release.emit(None, "br", " label ", function.local("done"))
    fail = function.append_block("fail")
    fail.emit(None, "call", " void ", module.symbol("__xcc_aot_memory_safety_fail"), "()")
    fail.emit(None, "unreachable")
    done = function.append_block("done")
    done.emit(None, "ret", " void")


def _build___xcc_aot_phase_promote_cache_contains(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_phase_promote_cache_contains")
    entry = function.append_block("entry")
    entry.emit("payload_key", "ptrtoint", " ptr ", function.local("payload"), " to i64")
    entry.emit("payload_high", "lshr", " i64 ", function.local("payload_key"), ", 10")
    entry.emit(
        "payload_mixed",
        "xor",
        " i64 ",
        function.local("payload_key"),
        ", ",
        function.local("payload_high"),
    )
    entry.emit("index", "and", " i64 ", function.local("payload_mixed"), ", 1023")
    entry.emit(
        "payload_slot",
        "getelementptr",
        " [1024 x ptr], ptr ",
        module.symbol("__xcc_aot_phase_promote_cache_payloads"),
        ", i64 0, i64 ",
        function.local("index"),
    )
    entry.emit(
        "target_slot",
        "getelementptr",
        " [1024 x ptr], ptr ",
        module.symbol("__xcc_aot_phase_promote_cache_targets"),
        ", i64 0, i64 ",
        function.local("index"),
    )
    entry.emit(
        "state_slot",
        "getelementptr",
        " [1024 x i64], ptr ",
        module.symbol("__xcc_aot_phase_promote_cache_states"),
        ", i64 0, i64 ",
        function.local("index"),
    )
    entry.emit("cached_payload", "load", " ptr, ptr ", function.local("payload_slot"))
    entry.emit("cached_target", "load", " ptr, ptr ", function.local("target_slot"))
    entry.emit("cached_state", "load", " i64, ptr ", function.local("state_slot"))
    entry.emit(
        "same_payload",
        "icmp",
        " eq ptr ",
        function.local("cached_payload"),
        ", ",
        function.local("payload"),
    )
    entry.emit(
        "same_target",
        "icmp",
        " eq ptr ",
        function.local("cached_target"),
        ", ",
        function.local("target"),
    )
    entry.emit(
        "same_pair",
        "and",
        " i1 ",
        function.local("same_payload"),
        ", ",
        function.local("same_target"),
    )
    entry.emit(
        "target_state_slot", "getelementptr", " i8, ptr ", function.local("target"), ", i64 32"
    )
    entry.emit("target_state", "load", " i64, ptr ", function.local("target_state_slot"))
    entry.emit(
        "same_state",
        "icmp",
        " eq i64 ",
        function.local("cached_state"),
        ", ",
        function.local("target_state"),
    )
    entry.emit(
        "hit", "and", " i1 ", function.local("same_pair"), ", ", function.local("same_state")
    )
    entry.emit(None, "ret", " i1 ", function.local("hit"))


def _build___xcc_aot_phase_promote_cache_store(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_phase_promote_cache_store")
    entry = function.append_block("entry")
    entry.emit("payload_key", "ptrtoint", " ptr ", function.local("payload"), " to i64")
    entry.emit("payload_high", "lshr", " i64 ", function.local("payload_key"), ", 10")
    entry.emit(
        "payload_mixed",
        "xor",
        " i64 ",
        function.local("payload_key"),
        ", ",
        function.local("payload_high"),
    )
    entry.emit("index", "and", " i64 ", function.local("payload_mixed"), ", 1023")
    entry.emit(
        "payload_slot",
        "getelementptr",
        " [1024 x ptr], ptr ",
        module.symbol("__xcc_aot_phase_promote_cache_payloads"),
        ", i64 0, i64 ",
        function.local("index"),
    )
    entry.emit(
        "target_slot",
        "getelementptr",
        " [1024 x ptr], ptr ",
        module.symbol("__xcc_aot_phase_promote_cache_targets"),
        ", i64 0, i64 ",
        function.local("index"),
    )
    entry.emit(
        "state_slot",
        "getelementptr",
        " [1024 x i64], ptr ",
        module.symbol("__xcc_aot_phase_promote_cache_states"),
        ", i64 0, i64 ",
        function.local("index"),
    )
    entry.emit(
        "target_state_slot", "getelementptr", " i8, ptr ", function.local("target"), ", i64 32"
    )
    entry.emit("target_state", "load", " i64, ptr ", function.local("target_state_slot"))
    entry.emit(
        None, "store", " ptr ", function.local("payload"), ", ptr ", function.local("payload_slot")
    )
    entry.emit(
        None, "store", " ptr ", function.local("target"), ", ptr ", function.local("target_slot")
    )
    entry.emit(
        None,
        "store",
        " i64 ",
        function.local("target_state"),
        ", ptr ",
        function.local("state_slot"),
    )
    entry.emit(None, "ret", " void")


def _build___xcc_aot_phase_promote_cache_invalidate_payload(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_phase_promote_cache_invalidate_payload")
    entry = function.append_block("entry")
    entry.emit("payload_key", "ptrtoint", " ptr ", function.local("payload"), " to i64")
    entry.emit("payload_high", "lshr", " i64 ", function.local("payload_key"), ", 10")
    entry.emit(
        "payload_mixed",
        "xor",
        " i64 ",
        function.local("payload_key"),
        ", ",
        function.local("payload_high"),
    )
    entry.emit("index", "and", " i64 ", function.local("payload_mixed"), ", 1023")
    entry.emit(
        "payload_slot",
        "getelementptr",
        " [1024 x ptr], ptr ",
        module.symbol("__xcc_aot_phase_promote_cache_payloads"),
        ", i64 0, i64 ",
        function.local("index"),
    )
    entry.emit("cached_payload", "load", " ptr, ptr ", function.local("payload_slot"))
    entry.emit(
        "same_payload",
        "icmp",
        " eq ptr ",
        function.local("cached_payload"),
        ", ",
        function.local("payload"),
    )
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("same_payload"),
        ", label ",
        function.local("invalidate"),
        ", label ",
        function.local("done"),
    )
    invalidate = function.append_block("invalidate")
    invalidate.emit(None, "store", " ptr null, ptr ", function.local("payload_slot"))
    invalidate.emit(None, "br", " label ", function.local("done"))
    done = function.append_block("done")
    done.emit(None, "ret", " void")


def _build___xcc_aot_phase_capture_cache_enter(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_phase_capture_cache_enter")
    entry = function.append_block("entry")
    entry.emit("valid", "load", " i1, ptr ", module.symbol("__xcc_aot_phase_capture_cache_valid"))
    entry.emit(
        "target", "load", " ptr, ptr ", module.symbol("__xcc_aot_phase_capture_cache_target")
    )
    entry.emit("has_target", "icmp", " ne ptr ", function.local("target"), ", null")
    entry.emit("keep", "and", " i1 ", function.local("valid"), ", ", function.local("has_target"))
    entry.emit(
        None,
        "store",
        " i1 ",
        function.local("keep"),
        ", ptr ",
        module.symbol("__xcc_aot_phase_capture_cache_valid"),
    )
    entry.emit(
        "valid_2", "load", " i1, ptr ", module.symbol("__xcc_aot_phase_capture_cache_valid_2")
    )
    entry.emit(
        "target_2", "load", " ptr, ptr ", module.symbol("__xcc_aot_phase_capture_cache_target_2")
    )
    entry.emit("has_target_2", "icmp", " ne ptr ", function.local("target_2"), ", null")
    entry.emit(
        "keep_2", "and", " i1 ", function.local("valid_2"), ", ", function.local("has_target_2")
    )
    entry.emit(
        None,
        "store",
        " i1 ",
        function.local("keep_2"),
        ", ptr ",
        module.symbol("__xcc_aot_phase_capture_cache_valid_2"),
    )
    entry.emit(None, "ret", " void")


def _build___xcc_aot_phase_capture_cache_exit(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_phase_capture_cache_exit")
    entry = function.append_block("entry")
    entry.emit("valid", "load", " i1, ptr ", module.symbol("__xcc_aot_phase_capture_cache_valid"))
    entry.emit(
        "target", "load", " ptr, ptr ", module.symbol("__xcc_aot_phase_capture_cache_target")
    )
    entry.emit("has_target", "icmp", " ne ptr ", function.local("target"), ", null")
    entry.emit(
        "removes_target", "icmp", " eq ptr ", function.local("target"), ", ", function.local("mark")
    )
    entry.emit("keeps_target", "xor", " i1 ", function.local("removes_target"), ", true")
    entry.emit(
        "stable_target",
        "and",
        " i1 ",
        function.local("has_target"),
        ", ",
        function.local("keeps_target"),
    )
    entry.emit(
        "keep", "and", " i1 ", function.local("valid"), ", ", function.local("stable_target")
    )
    entry.emit(
        None,
        "store",
        " i1 ",
        function.local("keep"),
        ", ptr ",
        module.symbol("__xcc_aot_phase_capture_cache_valid"),
    )
    entry.emit(
        "valid_2", "load", " i1, ptr ", module.symbol("__xcc_aot_phase_capture_cache_valid_2")
    )
    entry.emit(
        "target_2", "load", " ptr, ptr ", module.symbol("__xcc_aot_phase_capture_cache_target_2")
    )
    entry.emit("has_target_2", "icmp", " ne ptr ", function.local("target_2"), ", null")
    entry.emit(
        "removes_target_2",
        "icmp",
        " eq ptr ",
        function.local("target_2"),
        ", ",
        function.local("mark"),
    )
    entry.emit("keeps_target_2", "xor", " i1 ", function.local("removes_target_2"), ", true")
    entry.emit(
        "stable_target_2",
        "and",
        " i1 ",
        function.local("has_target_2"),
        ", ",
        function.local("keeps_target_2"),
    )
    entry.emit(
        "keep_2", "and", " i1 ", function.local("valid_2"), ", ", function.local("stable_target_2")
    )
    entry.emit(
        None,
        "store",
        " i1 ",
        function.local("keep_2"),
        ", ptr ",
        module.symbol("__xcc_aot_phase_capture_cache_valid_2"),
    )
    entry.emit(None, "ret", " void")


def _build___xcc_aot_phase_capture_cache_store(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_phase_capture_cache_store")
    entry = function.append_block("entry")
    entry.emit(
        "primary_valid", "load", " i1, ptr ", module.symbol("__xcc_aot_phase_capture_cache_valid")
    )
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("primary_valid"),
        ", label ",
        function.local("shift"),
        ", label ",
        function.local("store"),
    )
    shift = function.append_block("shift")
    shift.emit(
        "primary_owner", "load", " ptr, ptr ", module.symbol("__xcc_aot_phase_capture_cache_owner")
    )
    shift.emit(
        "primary_target",
        "load",
        " ptr, ptr ",
        module.symbol("__xcc_aot_phase_capture_cache_target"),
    )
    shift.emit(
        None,
        "store",
        " ptr ",
        function.local("primary_owner"),
        ", ptr ",
        module.symbol("__xcc_aot_phase_capture_cache_owner_2"),
    )
    shift.emit(
        None,
        "store",
        " ptr ",
        function.local("primary_target"),
        ", ptr ",
        module.symbol("__xcc_aot_phase_capture_cache_target_2"),
    )
    shift.emit(
        None, "store", " i1 true, ptr ", module.symbol("__xcc_aot_phase_capture_cache_valid_2")
    )
    shift.emit(None, "br", " label ", function.local("store"))
    store = function.append_block("store")
    store.emit(
        None,
        "store",
        " ptr ",
        function.local("owner"),
        ", ptr ",
        module.symbol("__xcc_aot_phase_capture_cache_owner"),
    )
    store.emit(
        None,
        "store",
        " ptr ",
        function.local("target"),
        ", ptr ",
        module.symbol("__xcc_aot_phase_capture_cache_target"),
    )
    store.emit(
        None, "store", " i1 true, ptr ", module.symbol("__xcc_aot_phase_capture_cache_valid")
    )
    store.emit(None, "ret", " void")


def _build___xcc_aot_phase_mark_with_mode(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_phase_mark_with_mode")
    entry = function.append_block("entry")
    entry.emit("used", "load", " i64, ptr ", module.symbol("__xcc_aot_allocated_bytes"))
    entry.emit("limit", "load", " i64, ptr ", module.symbol("__xcc_aot_phase_allocation_limit"))
    entry.emit("remaining", "sub", " i64 ", function.local("limit"), ", ", function.local("used"))
    entry.emit("over_limit", "icmp", " ult i64 ", function.local("remaining"), ", 40")
    entry.emit("generation", "load", " i64, ptr ", module.symbol("__xcc_aot_phase_mark_generation"))
    entry.emit(
        "generation_exhausted", "icmp", " eq i64 ", function.local("generation"), ", 274877906943"
    )
    entry.emit("depth", "load", " i64, ptr ", module.symbol("__xcc_aot_phase_depth"))
    entry.emit("depth_exhausted", "icmp", " uge i64 ", function.local("depth"), ", 65535")
    entry.emit(
        "sequence_exhausted",
        "or",
        " i1 ",
        function.local("generation_exhausted"),
        ", ",
        function.local("depth_exhausted"),
    )
    entry.emit(
        "cannot_allocate",
        "or",
        " i1 ",
        function.local("over_limit"),
        ", ",
        function.local("sequence_exhausted"),
    )
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("cannot_allocate"),
        ", label ",
        function.local("fail"),
        ", label ",
        function.local("allocate"),
    )
    allocate = function.append_block("allocate")
    allocate.emit("mark", "call", " ptr ", module.symbol("realloc"), "(ptr null, i64 40)")
    allocate.emit("allocation_failed", "icmp", " eq ptr ", function.local("mark"), ", null")
    allocate.emit(
        None,
        "br",
        " i1 ",
        function.local("allocation_failed"),
        ", label ",
        function.local("fail"),
        ", label ",
        function.local("initialize"),
    )
    initialize = function.append_block("initialize")
    initialize.emit("previous", "load", " ptr, ptr ", module.symbol("__xcc_aot_allocation_head"))
    initialize.emit(
        None, "store", " ptr ", function.local("previous"), ", ptr ", function.local("mark")
    )
    initialize.emit("next_slot", "getelementptr", " i8, ptr ", function.local("mark"), ", i64 8")
    initialize.emit(None, "store", " ptr null, ptr ", function.local("next_slot"))
    initialize.emit(
        "previous_mark", "load", " ptr, ptr ", module.symbol("__xcc_aot_phase_mark_head")
    )
    initialize.emit(
        "previous_mark_slot", "getelementptr", " i8, ptr ", function.local("mark"), ", i64 16"
    )
    initialize.emit(
        None,
        "store",
        " ptr ",
        function.local("previous_mark"),
        ", ptr ",
        function.local("previous_mark_slot"),
    )
    initialize.emit("magic_slot", "getelementptr", " i8, ptr ", function.local("mark"), ", i64 24")
    initialize.emit("magic", "load", " i64, ptr ", module.symbol("__xcc_aot_phase_mark_magic"))
    initialize.emit(
        None, "store", " i64 ", function.local("magic"), ", ptr ", function.local("magic_slot")
    )
    initialize.emit(
        "deferred_slot", "getelementptr", " i8, ptr ", function.local("mark"), ", i64 32"
    )
    initialize.emit("next_depth", "add", " i64 ", function.local("depth"), ", 1")
    initialize.emit("next_generation", "add", " i64 ", function.local("generation"), ", 1")
    initialize.emit("generation_state", "shl", " i64 ", function.local("next_generation"), ", 25")
    initialize.emit("depth_state", "shl", " i64 ", function.local("next_depth"), ", 1")
    initialize.emit(
        "base_state",
        "or",
        " i64 ",
        function.local("generation_state"),
        ", ",
        function.local("depth_state"),
    )
    initialize.emit(
        "exact_state",
        "select",
        " i1 ",
        function.local("exact"),
        ", i64 -9223372036854775808, i64 0",
    )
    initialize.emit(
        "mark_state",
        "or",
        " i64 ",
        function.local("base_state"),
        ", ",
        function.local("exact_state"),
    )
    initialize.emit(
        None,
        "store",
        " i64 ",
        function.local("mark_state"),
        ", ptr ",
        function.local("deferred_slot"),
    )
    initialize.emit("has_previous", "icmp", " ne ptr ", function.local("previous"), ", null")
    initialize.emit(
        None,
        "br",
        " i1 ",
        function.local("has_previous"),
        ", label ",
        function.local("link_previous"),
        ", label ",
        function.local("finish"),
    )
    link_previous = function.append_block("link_previous")
    link_previous.emit(
        "previous_next", "getelementptr", " i8, ptr ", function.local("previous"), ", i64 8"
    )
    link_previous.emit(
        None, "store", " ptr ", function.local("mark"), ", ptr ", function.local("previous_next")
    )
    link_previous.emit(None, "br", " label ", function.local("finish"))
    finish = function.append_block("finish")
    finish.emit(
        None,
        "store",
        " ptr ",
        function.local("mark"),
        ", ptr ",
        module.symbol("__xcc_aot_allocation_head"),
    )
    finish.emit(
        None,
        "store",
        " ptr ",
        function.local("mark"),
        ", ptr ",
        module.symbol("__xcc_aot_phase_mark_head"),
    )
    finish.emit(None, "call", " void ", module.symbol("__xcc_aot_phase_capture_cache_enter"), "()")
    finish.emit("next_used", "add", " i64 ", function.local("used"), ", 40")
    finish.emit(
        None,
        "store",
        " i64 ",
        function.local("next_used"),
        ", ptr ",
        module.symbol("__xcc_aot_allocated_bytes"),
    )
    finish.emit(
        None,
        "store",
        " i64 ",
        function.local("next_depth"),
        ", ptr ",
        module.symbol("__xcc_aot_phase_depth"),
    )
    finish.emit(
        None,
        "store",
        " i64 ",
        function.local("next_generation"),
        ", ptr ",
        module.symbol("__xcc_aot_phase_mark_generation"),
    )
    finish.emit(None, "store", " i1 true, ptr ", module.symbol("__xcc_aot_phase_active"))
    finish.emit(None, "ret", " ptr ", function.local("mark"))
    fail = function.append_block("fail")
    fail.emit(None, "call", " void ", module.symbol("__xcc_aot_allocation_fail"), "()")
    fail.emit(None, "unreachable")


def _build___xcc_aot_phase_mark(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_phase_mark")
    entry = function.append_block("entry")
    entry.emit(
        "mark", "call", " ptr ", module.symbol("__xcc_aot_phase_mark_with_mode"), "(i1 false)"
    )
    entry.emit(None, "ret", " ptr ", function.local("mark"))


def _build___xcc_aot_phase_iteration_mark(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_phase_iteration_mark")
    entry = function.append_block("entry")
    entry.emit(
        "mark", "call", " ptr ", module.symbol("__xcc_aot_phase_mark_with_mode"), "(i1 true)"
    )
    entry.emit(None, "ret", " ptr ", function.local("mark"))


def _build___xcc_aot_phase_promote(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_phase_promote")
    entry = function.append_block("entry")
    entry.emit("is_null", "icmp", " eq ptr ", function.local("payload"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("is_null"),
        ", label ",
        function.local("not_movable"),
        ", label ",
        function.local("select_target"),
    )
    select_target = function.append_block("select_target")
    select_target.emit("mark", "load", " ptr, ptr ", module.symbol("__xcc_aot_phase_mark_head"))
    select_target.emit("has_mark", "icmp", " ne ptr ", function.local("mark"), ", null")
    select_target.emit(
        None,
        "br",
        " i1 ",
        function.local("has_mark"),
        ", label ",
        function.local("promote"),
        ", label ",
        function.local("not_movable"),
    )
    promote = function.append_block("promote")
    promote.emit(
        "promoted",
        "call",
        " i1 ",
        module.symbol("__xcc_aot_phase_promote_to"),
        "(    ptr ",
        function.local("payload"),
        ", ptr ",
        function.local("mark"),
        ")",
    )
    promote.emit(None, "ret", " i1 ", function.local("promoted"))
    not_movable = function.append_block("not_movable")
    not_movable.emit(None, "ret", " i1 false")


def _build___xcc_aot_phase_promote_begin(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_phase_promote_begin")
    entry = function.append_block("entry")
    entry.emit("active", "load", " ptr, ptr ", module.symbol("__xcc_aot_phase_promote_target"))
    entry.emit("inactive", "icmp", " eq ptr ", function.local("active"), ", null")
    entry.emit("has_target", "icmp", " ne ptr ", function.local("target"), ", null")
    entry.emit(
        "can_begin", "and", " i1 ", function.local("inactive"), ", ", function.local("has_target")
    )
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("can_begin"),
        ", label ",
        function.local("validate"),
        ", label ",
        function.local("corrupt"),
    )
    validate = function.append_block("validate")
    validate.emit("magic_slot", "getelementptr", " i8, ptr ", function.local("target"), ", i64 24")
    validate.emit("stored_magic", "load", " i64, ptr ", function.local("magic_slot"))
    validate.emit("mark_magic", "load", " i64, ptr ", module.symbol("__xcc_aot_phase_mark_magic"))
    validate.emit(
        "valid",
        "icmp",
        " eq i64 ",
        function.local("stored_magic"),
        ", ",
        function.local("mark_magic"),
    )
    validate.emit(
        None,
        "br",
        " i1 ",
        function.local("valid"),
        ", label ",
        function.local("begin"),
        ", label ",
        function.local("corrupt"),
    )
    begin = function.append_block("begin")
    begin.emit(
        None,
        "store",
        " ptr ",
        function.local("target"),
        ", ptr ",
        module.symbol("__xcc_aot_phase_promote_target"),
    )
    begin.emit(
        None,
        "store",
        " ptr ",
        function.local("target"),
        ", ptr ",
        module.symbol("__xcc_aot_phase_promote_cursor"),
    )
    begin.emit(None, "ret", " void")
    corrupt = function.append_block("corrupt")
    corrupt.emit(None, "call", " void ", module.symbol("__xcc_aot_memory_safety_fail"), "()")
    corrupt.emit(None, "unreachable")


def _build___xcc_aot_phase_promote_end(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_phase_promote_end")
    entry = function.append_block("entry")
    entry.emit("active", "load", " ptr, ptr ", module.symbol("__xcc_aot_phase_promote_target"))
    entry.emit("cursor", "load", " ptr, ptr ", module.symbol("__xcc_aot_phase_promote_cursor"))
    entry.emit(
        "same_target", "icmp", " eq ptr ", function.local("active"), ", ", function.local("target")
    )
    entry.emit("has_cursor", "icmp", " ne ptr ", function.local("cursor"), ", null")
    entry.emit(
        "valid", "and", " i1 ", function.local("same_target"), ", ", function.local("has_cursor")
    )
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("valid"),
        ", label ",
        function.local("finish"),
        ", label ",
        function.local("corrupt"),
    )
    finish = function.append_block("finish")
    finish.emit(None, "store", " ptr null, ptr ", module.symbol("__xcc_aot_phase_promote_target"))
    finish.emit(None, "store", " ptr null, ptr ", module.symbol("__xcc_aot_phase_promote_cursor"))
    finish.emit(None, "ret", " void")
    corrupt = function.append_block("corrupt")
    corrupt.emit(None, "call", " void ", module.symbol("__xcc_aot_memory_safety_fail"), "()")
    corrupt.emit(None, "unreachable")


def _build___xcc_aot_phase_promote_allocated_to(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_phase_promote_allocated_to")
    entry = function.append_block("entry")
    entry.emit("is_null", "icmp", " eq ptr ", function.local("payload"), ", null")
    entry.emit("target_is_null", "icmp", " eq ptr ", function.local("target"), ", null")
    entry.emit(
        "cannot_move",
        "or",
        " i1 ",
        function.local("is_null"),
        ", ",
        function.local("target_is_null"),
    )
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("cannot_move"),
        ", label ",
        function.local("not_movable"),
        ", label ",
        function.local("validate_request"),
    )
    validate_request = function.append_block("validate_request")
    validate_request.emit(
        "requested_magic_slot", "getelementptr", " i8, ptr ", function.local("target"), ", i64 24"
    )
    validate_request.emit(
        "requested_magic", "load", " i64, ptr ", function.local("requested_magic_slot")
    )
    validate_request.emit(
        "requested_mark_magic", "load", " i64, ptr ", module.symbol("__xcc_aot_phase_mark_magic")
    )
    validate_request.emit(
        "valid_request",
        "icmp",
        " eq i64 ",
        function.local("requested_magic"),
        ", ",
        function.local("requested_mark_magic"),
    )
    validate_request.emit(
        None,
        "br",
        " i1 ",
        function.local("valid_request"),
        ", label ",
        function.local("check_deferred"),
        ", label ",
        function.local("corrupt"),
    )
    check_deferred = function.append_block("check_deferred")
    check_deferred.emit(
        "state_slot", "getelementptr", " i8, ptr ", function.local("target"), ", i64 32"
    )
    check_deferred.emit("target_state", "load", " i64, ptr ", function.local("state_slot"))
    check_deferred.emit("deferred_bit", "and", " i64 ", function.local("target_state"), ", 1")
    check_deferred.emit("deferred", "icmp", " ne i64 ", function.local("deferred_bit"), ", 0")
    check_deferred.emit("target_depth_raw", "lshr", " i64 ", function.local("target_state"), ", 1")
    check_deferred.emit(
        "target_depth", "and", " i64 ", function.local("target_depth_raw"), ", 16777215"
    )
    check_deferred.emit(
        "current_depth", "load", " i64, ptr ", module.symbol("__xcc_aot_phase_depth")
    )
    check_deferred.emit(
        "target_nonzero", "icmp", " ugt i64 ", function.local("target_depth"), ", 0"
    )
    check_deferred.emit(
        "target_active",
        "icmp",
        " ule i64 ",
        function.local("target_depth"),
        ", ",
        function.local("current_depth"),
    )
    check_deferred.emit(
        "target_valid",
        "and",
        " i1 ",
        function.local("target_nonzero"),
        ", ",
        function.local("target_active"),
    )
    check_deferred.emit(
        None,
        "br",
        " i1 ",
        function.local("target_valid"),
        ", label ",
        function.local("deferred_result"),
        ", label ",
        function.local("corrupt"),
    )
    deferred_result = function.append_block("deferred_result")
    deferred_result.emit(
        None,
        "br",
        " i1 ",
        function.local("deferred"),
        ", label ",
        function.local("not_movable"),
        ", label ",
        function.local("check_session"),
    )
    check_session = function.append_block("check_session")
    check_session.emit(
        "active_target", "load", " ptr, ptr ", module.symbol("__xcc_aot_phase_promote_target")
    )
    check_session.emit(
        "session_active", "icmp", " ne ptr ", function.local("active_target"), ", null"
    )
    check_session.emit(
        "session_matches",
        "icmp",
        " eq ptr ",
        function.local("active_target"),
        ", ",
        function.local("target"),
    )
    check_session.emit(
        "session_differs", "xor", " i1 ", function.local("session_matches"), ", true"
    )
    check_session.emit(
        "session_mismatch",
        "and",
        " i1 ",
        function.local("session_active"),
        ", ",
        function.local("session_differs"),
    )
    check_session.emit(
        None,
        "br",
        " i1 ",
        function.local("session_mismatch"),
        ", label ",
        function.local("corrupt"),
        ", label ",
        function.local("validate_allocation"),
    )
    validate_allocation = function.append_block("validate_allocation")
    validate_allocation.emit(
        "node",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_find_allocation"),
        "(ptr ",
        function.local("payload"),
        ")",
    )
    validate_allocation.emit("tracked", "icmp", " ne ptr ", function.local("node"), ", null")
    validate_allocation.emit(
        None,
        "br",
        " i1 ",
        function.local("tracked"),
        ", label ",
        function.local("check_region"),
        ", label ",
        function.local("not_movable"),
    )
    check_region = function.append_block("check_region")
    check_region.emit("size_slot", "getelementptr", " i8, ptr ", function.local("node"), ", i64 16")
    check_region.emit("tracked_size", "load", " i64, ptr ", function.local("size_slot"))
    check_region.emit("owner_depth_raw", "lshr", " i64 ", function.local("tracked_size"), ", 32")
    check_region.emit("owner_depth", "and", " i64 ", function.local("owner_depth_raw"), ", 65535")
    check_region.emit(
        "owner_valid",
        "icmp",
        " ule i64 ",
        function.local("owner_depth"),
        ", ",
        function.local("current_depth"),
    )
    check_region.emit(
        None,
        "br",
        " i1 ",
        function.local("owner_valid"),
        ", label ",
        function.local("compare_region"),
        ", label ",
        function.local("corrupt"),
    )
    compare_region = function.append_block("compare_region")
    compare_region.emit(
        "movable",
        "icmp",
        " uge i64 ",
        function.local("owner_depth"),
        ", ",
        function.local("target_depth"),
    )
    compare_region.emit(
        None,
        "br",
        " i1 ",
        function.local("movable"),
        ", label ",
        function.local("unlink"),
        ", label ",
        function.local("not_movable"),
    )
    unlink = function.append_block("unlink")
    unlink.emit("previous", "load", " ptr, ptr ", function.local("node"))
    unlink.emit("next_slot", "getelementptr", " i8, ptr ", function.local("node"), ", i64 8")
    unlink.emit("newer", "load", " ptr, ptr ", function.local("next_slot"))
    unlink.emit("has_newer", "icmp", " ne ptr ", function.local("newer"), ", null")
    unlink.emit(
        None,
        "br",
        " i1 ",
        function.local("has_newer"),
        ", label ",
        function.local("repair_newer"),
        ", label ",
        function.local("repair_head"),
    )
    repair_newer = function.append_block("repair_newer")
    repair_newer.emit(
        None, "store", " ptr ", function.local("previous"), ", ptr ", function.local("newer")
    )
    repair_newer.emit(None, "br", " label ", function.local("repair_previous"))
    repair_head = function.append_block("repair_head")
    repair_head.emit(
        None,
        "store",
        " ptr ",
        function.local("previous"),
        ", ptr ",
        module.symbol("__xcc_aot_allocation_head"),
    )
    repair_head.emit(None, "br", " label ", function.local("repair_previous"))
    repair_previous = function.append_block("repair_previous")
    repair_previous.emit(
        "previous_next", "getelementptr", " i8, ptr ", function.local("previous"), ", i64 8"
    )
    repair_previous.emit(
        None, "store", " ptr ", function.local("newer"), ", ptr ", function.local("previous_next")
    )
    repair_previous.emit("size", "and", " i64 ", function.local("tracked_size"), ", 4294967295")
    repair_previous.emit("parent_depth", "sub", " i64 ", function.local("target_depth"), ", 1")
    repair_previous.emit("parent_region", "shl", " i64 ", function.local("parent_depth"), ", 32")
    repair_previous.emit(
        "tag_region", "and", " i64 ", function.local("tracked_size"), ", -281474976710656"
    )
    repair_previous.emit(
        "promoted_region",
        "or",
        " i64 ",
        function.local("tag_region"),
        ", ",
        function.local("parent_region"),
    )
    repair_previous.emit(
        "promoted_tracked_size",
        "or",
        " i64 ",
        function.local("promoted_region"),
        ", ",
        function.local("size"),
    )
    repair_previous.emit(
        None,
        "store",
        " i64 ",
        function.local("promoted_tracked_size"),
        ", ptr ",
        function.local("size_slot"),
    )
    repair_previous.emit(
        "scoped",
        "and",
        " i1 ",
        function.local("session_active"),
        ", ",
        function.local("session_matches"),
    )
    repair_previous.emit(
        "cursor", "load", " ptr, ptr ", module.symbol("__xcc_aot_phase_promote_cursor")
    )
    repair_previous.emit(
        "insertion",
        "select",
        " i1 ",
        function.local("scoped"),
        ", ptr ",
        function.local("cursor"),
        ", ptr ",
        function.local("target"),
    )
    repair_previous.emit("insertion_previous", "load", " ptr, ptr ", function.local("insertion"))
    repair_previous.emit(
        None,
        "store",
        " ptr ",
        function.local("insertion_previous"),
        ", ptr ",
        function.local("node"),
    )
    repair_previous.emit(
        None, "store", " ptr ", function.local("insertion"), ", ptr ", function.local("next_slot")
    )
    repair_previous.emit(
        None, "store", " ptr ", function.local("node"), ", ptr ", function.local("insertion")
    )
    repair_previous.emit(
        "has_insertion_previous", "icmp", " ne ptr ", function.local("insertion_previous"), ", null"
    )
    repair_previous.emit(
        None,
        "br",
        " i1 ",
        function.local("has_insertion_previous"),
        ", label ",
        function.local("link_insertion_previous"),
        ", label ",
        function.local("remember"),
    )
    link_insertion_previous = function.append_block("link_insertion_previous")
    link_insertion_previous.emit(
        "insertion_previous_next",
        "getelementptr",
        " i8, ptr ",
        function.local("insertion_previous"),
        ", i64 8",
    )
    link_insertion_previous.emit(
        None,
        "store",
        " ptr ",
        function.local("node"),
        ", ptr ",
        function.local("insertion_previous_next"),
    )
    link_insertion_previous.emit(None, "br", " label ", function.local("remember"))
    remember = function.append_block("remember")
    remember.emit(
        None,
        "br",
        " i1 ",
        function.local("scoped"),
        ", label ",
        function.local("remember_scoped"),
        ", label ",
        function.local("promoted"),
    )
    remember_scoped = function.append_block("remember_scoped")
    remember_scoped.emit(
        None,
        "store",
        " ptr ",
        function.local("node"),
        ", ptr ",
        module.symbol("__xcc_aot_phase_promote_cursor"),
    )
    remember_scoped.emit(None, "br", " label ", function.local("promoted"))
    promoted = function.append_block("promoted")
    promoted.emit(None, "ret", " i1 true")
    not_movable = function.append_block("not_movable")
    not_movable.emit(None, "ret", " i1 false")
    corrupt = function.append_block("corrupt")
    corrupt.emit(None, "call", " void ", module.symbol("__xcc_aot_memory_safety_fail"), "()")
    corrupt.emit(None, "unreachable")


def _build___xcc_aot_phase_promote_to(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_phase_promote_to")
    entry = function.append_block("entry")
    entry.emit("is_null", "icmp", " eq ptr ", function.local("payload"), ", null")
    entry.emit("target_is_null", "icmp", " eq ptr ", function.local("target"), ", null")
    entry.emit(
        "cannot_move",
        "or",
        " i1 ",
        function.local("is_null"),
        ", ",
        function.local("target_is_null"),
    )
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("cannot_move"),
        ", label ",
        function.local("not_movable"),
        ", label ",
        function.local("validate_request"),
    )
    validate_request = function.append_block("validate_request")
    validate_request.emit(
        "requested_magic_slot", "getelementptr", " i8, ptr ", function.local("target"), ", i64 24"
    )
    validate_request.emit(
        "requested_magic", "load", " i64, ptr ", function.local("requested_magic_slot")
    )
    validate_request.emit(
        "requested_mark_magic", "load", " i64, ptr ", module.symbol("__xcc_aot_phase_mark_magic")
    )
    validate_request.emit(
        "valid_request",
        "icmp",
        " eq i64 ",
        function.local("requested_magic"),
        ", ",
        function.local("requested_mark_magic"),
    )
    validate_request.emit(
        None,
        "br",
        " i1 ",
        function.local("valid_request"),
        ", label ",
        function.local("check_deferred"),
        ", label ",
        function.local("corrupt"),
    )
    check_deferred = function.append_block("check_deferred")
    check_deferred.emit(
        "deferred_slot", "getelementptr", " i8, ptr ", function.local("target"), ", i64 32"
    )
    check_deferred.emit("target_state", "load", " i64, ptr ", function.local("deferred_slot"))
    check_deferred.emit("deferred_bit", "and", " i64 ", function.local("target_state"), ", 1")
    check_deferred.emit("deferred", "icmp", " ne i64 ", function.local("deferred_bit"), ", 0")
    check_deferred.emit("target_depth_raw", "lshr", " i64 ", function.local("target_state"), ", 1")
    check_deferred.emit(
        "target_depth", "and", " i64 ", function.local("target_depth_raw"), ", 16777215"
    )
    check_deferred.emit(
        "current_depth", "load", " i64, ptr ", module.symbol("__xcc_aot_phase_depth")
    )
    check_deferred.emit(
        "target_nonzero", "icmp", " ugt i64 ", function.local("target_depth"), ", 0"
    )
    check_deferred.emit(
        "target_active",
        "icmp",
        " ule i64 ",
        function.local("target_depth"),
        ", ",
        function.local("current_depth"),
    )
    check_deferred.emit(
        "target_valid",
        "and",
        " i1 ",
        function.local("target_nonzero"),
        ", ",
        function.local("target_active"),
    )
    check_deferred.emit(
        None,
        "br",
        " i1 ",
        function.local("target_valid"),
        ", label ",
        function.local("deferred_result"),
        ", label ",
        function.local("corrupt"),
    )
    deferred_result = function.append_block("deferred_result")
    deferred_result.emit(
        None,
        "br",
        " i1 ",
        function.local("deferred"),
        ", label ",
        function.local("not_movable"),
        ", label ",
        function.local("check_session"),
    )
    check_session = function.append_block("check_session")
    check_session.emit(
        "active_target", "load", " ptr, ptr ", module.symbol("__xcc_aot_phase_promote_target")
    )
    check_session.emit(
        "session_active", "icmp", " ne ptr ", function.local("active_target"), ", null"
    )
    check_session.emit(
        "session_matches",
        "icmp",
        " eq ptr ",
        function.local("active_target"),
        ", ",
        function.local("target"),
    )
    check_session.emit(
        "session_differs", "xor", " i1 ", function.local("session_matches"), ", true"
    )
    check_session.emit(
        "session_mismatch",
        "and",
        " i1 ",
        function.local("session_active"),
        ", ",
        function.local("session_differs"),
    )
    check_session.emit(
        None,
        "br",
        " i1 ",
        function.local("session_mismatch"),
        ", label ",
        function.local("corrupt"),
        ", label ",
        function.local("cache_check"),
    )
    cache_check = function.append_block("cache_check")
    cache_check.emit(
        "cached",
        "call",
        " i1 ",
        module.symbol("__xcc_aot_phase_promote_cache_contains"),
        "(    ptr ",
        function.local("payload"),
        ", ptr ",
        function.local("target"),
        ")",
    )
    cache_check.emit(
        None,
        "br",
        " i1 ",
        function.local("cached"),
        ", label ",
        function.local("not_movable"),
        ", label ",
        function.local("promote"),
    )
    promote = function.append_block("promote")
    promote.emit(
        "promoted",
        "call",
        " i1 ",
        module.symbol("__xcc_aot_phase_promote_allocated_to"),
        "(    ptr ",
        function.local("payload"),
        ", ptr ",
        function.local("target"),
        ")",
    )
    promote.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_phase_promote_cache_store"),
        "(ptr ",
        function.local("payload"),
        ", ptr ",
        function.local("target"),
        ")",
    )
    promote.emit(None, "ret", " i1 ", function.local("promoted"))
    not_movable = function.append_block("not_movable")
    not_movable.emit(None, "ret", " i1 false")
    corrupt = function.append_block("corrupt")
    corrupt.emit(None, "call", " void ", module.symbol("__xcc_aot_memory_safety_fail"), "()")
    corrupt.emit(None, "unreachable")


def _build___xcc_aot_phase_capture_allocated_target(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_phase_capture_allocated_target")
    entry = function.append_block("entry")
    entry.emit("top", "load", " ptr, ptr ", module.symbol("__xcc_aot_phase_mark_head"))
    entry.emit("has_top", "icmp", " ne ptr ", function.local("top"), ", null")
    entry.emit("has_owner", "icmp", " ne ptr ", function.local("owner"), ", null")
    entry.emit(
        "can_capture", "and", " i1 ", function.local("has_top"), ", ", function.local("has_owner")
    )
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("can_capture"),
        ", label ",
        function.local("validate_owner"),
        ", label ",
        function.local("no_target"),
    )
    validate_owner = function.append_block("validate_owner")
    validate_owner.emit(
        "owner_header",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_find_allocation"),
        "(ptr ",
        function.local("owner"),
        ")",
    )
    validate_owner.emit("tracked", "icmp", " ne ptr ", function.local("owner_header"), ", null")
    validate_owner.emit(
        None,
        "br",
        " i1 ",
        function.local("tracked"),
        ", label ",
        function.local("load_region"),
        ", label ",
        function.local("fallback"),
    )
    fallback = function.append_block("fallback")
    fallback.emit(
        "generic_target",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_phase_capture_target"),
        "(ptr ",
        function.local("owner"),
        ")",
    )
    fallback.emit(None, "ret", " ptr ", function.local("generic_target"))
    load_region = function.append_block("load_region")
    load_region.emit(
        "owner_size_slot", "getelementptr", " i8, ptr ", function.local("owner_header"), ", i64 16"
    )
    load_region.emit("owner_tracked_size", "load", " i64, ptr ", function.local("owner_size_slot"))
    load_region.emit(
        "owner_depth_raw", "lshr", " i64 ", function.local("owner_tracked_size"), ", 32"
    )
    load_region.emit("owner_depth", "and", " i64 ", function.local("owner_depth_raw"), ", 65535")
    load_region.emit("depth", "load", " i64, ptr ", module.symbol("__xcc_aot_phase_depth"))
    load_region.emit(
        "valid_depth",
        "icmp",
        " ule i64 ",
        function.local("owner_depth"),
        ", ",
        function.local("depth"),
    )
    load_region.emit(
        None,
        "br",
        " i1 ",
        function.local("valid_depth"),
        ", label ",
        function.local("select_boundary"),
        ", label ",
        function.local("corrupt"),
    )
    select_boundary = function.append_block("select_boundary")
    select_boundary.emit("target_depth", "add", " i64 ", function.local("owner_depth"), ", 1")
    select_boundary.emit(
        "needs_target",
        "icmp",
        " ule i64 ",
        function.local("target_depth"),
        ", ",
        function.local("depth"),
    )
    select_boundary.emit(
        None,
        "br",
        " i1 ",
        function.local("needs_target"),
        ", label ",
        function.local("search_entry"),
        ", label ",
        function.local("no_target"),
    )
    search_entry = function.append_block("search_entry")
    search_entry.emit(None, "br", " label ", function.local("search"))
    search = function.append_block("search")
    search.emit(
        "node",
        "phi",
        " ptr [ ",
        function.local("top"),
        ", ",
        function.local("search_entry"),
        " ], [ ",
        function.local("parent"),
        ", ",
        function.local("advance"),
        " ]",
    )
    search.emit("exists", "icmp", " ne ptr ", function.local("node"), ", null")
    search.emit(
        None,
        "br",
        " i1 ",
        function.local("exists"),
        ", label ",
        function.local("validate_mark"),
        ", label ",
        function.local("corrupt"),
    )
    validate_mark = function.append_block("validate_mark")
    validate_mark.emit(
        "magic_slot", "getelementptr", " i8, ptr ", function.local("node"), ", i64 24"
    )
    validate_mark.emit("stored_magic", "load", " i64, ptr ", function.local("magic_slot"))
    validate_mark.emit(
        "mark_magic", "load", " i64, ptr ", module.symbol("__xcc_aot_phase_mark_magic")
    )
    validate_mark.emit(
        "valid_mark",
        "icmp",
        " eq i64 ",
        function.local("stored_magic"),
        ", ",
        function.local("mark_magic"),
    )
    validate_mark.emit(
        None,
        "br",
        " i1 ",
        function.local("valid_mark"),
        ", label ",
        function.local("compare"),
        ", label ",
        function.local("corrupt"),
    )
    compare = function.append_block("compare")
    compare.emit("state_slot", "getelementptr", " i8, ptr ", function.local("node"), ", i64 32")
    compare.emit("mark_state", "load", " i64, ptr ", function.local("state_slot"))
    compare.emit("mark_depth_raw", "lshr", " i64 ", function.local("mark_state"), ", 1")
    compare.emit("mark_depth", "and", " i64 ", function.local("mark_depth_raw"), ", 16777215")
    compare.emit(
        "matches",
        "icmp",
        " eq i64 ",
        function.local("mark_depth"),
        ", ",
        function.local("target_depth"),
    )
    compare.emit(
        None,
        "br",
        " i1 ",
        function.local("matches"),
        ", label ",
        function.local("found"),
        ", label ",
        function.local("advance"),
    )
    advance = function.append_block("advance")
    advance.emit("parent_slot", "getelementptr", " i8, ptr ", function.local("node"), ", i64 16")
    advance.emit("parent", "load", " ptr, ptr ", function.local("parent_slot"))
    advance.emit(None, "br", " label ", function.local("search"))
    found = function.append_block("found")
    found.emit(None, "ret", " ptr ", function.local("node"))
    no_target = function.append_block("no_target")
    no_target.emit(None, "ret", " ptr null")
    corrupt = function.append_block("corrupt")
    corrupt.emit(None, "call", " void ", module.symbol("__xcc_aot_memory_safety_fail"), "()")
    corrupt.emit(None, "unreachable")


def _build___xcc_aot_phase_capture_target(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_phase_capture_target")
    entry = function.append_block("entry")
    entry.emit("top", "load", " ptr, ptr ", module.symbol("__xcc_aot_phase_mark_head"))
    entry.emit("has_top", "icmp", " ne ptr ", function.local("top"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("has_top"),
        ", label ",
        function.local("locate_owner"),
        ", label ",
        function.local("no_target"),
    )
    locate_owner = function.append_block("locate_owner")
    locate_owner.emit(
        "owner_header",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_find_allocation"),
        "(ptr ",
        function.local("owner"),
        ")",
    )
    locate_owner.emit(
        "owner_allocated", "icmp", " ne ptr ", function.local("owner_header"), ", null"
    )
    locate_owner.emit(
        None,
        "br",
        " i1 ",
        function.local("owner_allocated"),
        ", label ",
        function.local("allocated_owner"),
        ", label ",
        function.local("cache_check"),
    )
    allocated_owner = function.append_block("allocated_owner")
    allocated_owner.emit(
        "allocated_target",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_phase_capture_allocated_target"),
        "(    ptr ",
        function.local("owner"),
        ")",
    )
    allocated_owner.emit(None, "ret", " ptr ", function.local("allocated_target"))
    cache_check = function.append_block("cache_check")
    cache_check.emit(
        "cache_valid", "load", " i1, ptr ", module.symbol("__xcc_aot_phase_capture_cache_valid")
    )
    cache_check.emit(
        "cached_owner", "load", " ptr, ptr ", module.symbol("__xcc_aot_phase_capture_cache_owner")
    )
    cache_check.emit(
        "same_owner",
        "icmp",
        " eq ptr ",
        function.local("cached_owner"),
        ", ",
        function.local("owner"),
    )
    cache_check.emit(
        "cache_hit",
        "and",
        " i1 ",
        function.local("cache_valid"),
        ", ",
        function.local("same_owner"),
    )
    cache_check.emit(
        None,
        "br",
        " i1 ",
        function.local("cache_hit"),
        ", label ",
        function.local("cached"),
        ", label ",
        function.local("cache_check_2"),
    )
    cached = function.append_block("cached")
    cached.emit(
        "cached_target", "load", " ptr, ptr ", module.symbol("__xcc_aot_phase_capture_cache_target")
    )
    cached.emit(None, "ret", " ptr ", function.local("cached_target"))
    cache_check_2 = function.append_block("cache_check_2")
    cache_check_2.emit(
        "cache_valid_2", "load", " i1, ptr ", module.symbol("__xcc_aot_phase_capture_cache_valid_2")
    )
    cache_check_2.emit(
        "cached_owner_2",
        "load",
        " ptr, ptr ",
        module.symbol("__xcc_aot_phase_capture_cache_owner_2"),
    )
    cache_check_2.emit(
        "same_owner_2",
        "icmp",
        " eq ptr ",
        function.local("cached_owner_2"),
        ", ",
        function.local("owner"),
    )
    cache_check_2.emit(
        "cache_hit_2",
        "and",
        " i1 ",
        function.local("cache_valid_2"),
        ", ",
        function.local("same_owner_2"),
    )
    cache_check_2.emit(
        None,
        "br",
        " i1 ",
        function.local("cache_hit_2"),
        ", label ",
        function.local("cached_2"),
        ", label ",
        function.local("external_entry"),
    )
    cached_2 = function.append_block("cached_2")
    cached_2.emit(
        "cached_target_2",
        "load",
        " ptr, ptr ",
        module.symbol("__xcc_aot_phase_capture_cache_target_2"),
    )
    cached_2.emit(None, "ret", " ptr ", function.local("cached_target_2"))
    external_entry = function.append_block("external_entry")
    external_entry.emit(None, "br", " label ", function.local("external"))
    external = function.append_block("external")
    external.emit(
        "node",
        "phi",
        " ptr [ ",
        function.local("top"),
        ", ",
        function.local("external_entry"),
        " ], [ ",
        function.local("parent"),
        ", ",
        function.local("advance"),
        " ]",
    )
    external.emit("magic_slot", "getelementptr", " i8, ptr ", function.local("node"), ", i64 24")
    external.emit("stored_magic", "load", " i64, ptr ", function.local("magic_slot"))
    external.emit("mark_magic", "load", " i64, ptr ", module.symbol("__xcc_aot_phase_mark_magic"))
    external.emit(
        "valid_mark",
        "icmp",
        " eq i64 ",
        function.local("stored_magic"),
        ", ",
        function.local("mark_magic"),
    )
    external.emit(
        None,
        "br",
        " i1 ",
        function.local("valid_mark"),
        ", label ",
        function.local("select_parent"),
        ", label ",
        function.local("corrupt"),
    )
    select_parent = function.append_block("select_parent")
    select_parent.emit(
        "parent_slot", "getelementptr", " i8, ptr ", function.local("node"), ", i64 16"
    )
    select_parent.emit("parent", "load", " ptr, ptr ", function.local("parent_slot"))
    select_parent.emit("has_parent", "icmp", " ne ptr ", function.local("parent"), ", null")
    select_parent.emit(
        None,
        "br",
        " i1 ",
        function.local("has_parent"),
        ", label ",
        function.local("advance"),
        ", label ",
        function.local("global_owner"),
    )
    advance = function.append_block("advance")
    advance.emit(None, "br", " label ", function.local("external"))
    global_owner = function.append_block("global_owner")
    global_owner.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_phase_capture_cache_store"),
        "(ptr ",
        function.local("owner"),
        ", ptr ",
        function.local("node"),
        ")",
    )
    global_owner.emit(None, "ret", " ptr ", function.local("node"))
    no_target = function.append_block("no_target")
    no_target.emit(None, "ret", " ptr null")
    corrupt = function.append_block("corrupt")
    corrupt.emit(None, "call", " void ", module.symbol("__xcc_aot_memory_safety_fail"), "()")
    corrupt.emit(None, "unreachable")


def _build___xcc_aot_phase_capture_defer(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_phase_capture_defer")
    entry = function.append_block("entry")
    entry.emit("top", "load", " ptr, ptr ", module.symbol("__xcc_aot_phase_mark_head"))
    entry.emit("has_top", "icmp", " ne ptr ", function.local("top"), ", null")
    entry.emit("has_target", "icmp", " ne ptr ", function.local("target"), ", null")
    entry.emit(
        "can_search", "and", " i1 ", function.local("has_top"), ", ", function.local("has_target")
    )
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("can_search"),
        ", label ",
        function.local("validate_entry"),
        ", label ",
        function.local("not_deferred"),
    )
    validate_entry = function.append_block("validate_entry")
    validate_entry.emit(None, "br", " label ", function.local("validate"))
    validate = function.append_block("validate")
    validate.emit(
        "node",
        "phi",
        " ptr [ ",
        function.local("top"),
        ", ",
        function.local("validate_entry"),
        " ], [ ",
        function.local("parent"),
        ", ",
        function.local("advance"),
        " ]",
    )
    validate.emit(
        "exact_seen",
        "phi",
        " i1 [ false, ",
        function.local("validate_entry"),
        " ], [ ",
        function.local("target_exact"),
        ", ",
        function.local("advance"),
        " ]",
    )
    validate.emit("magic_slot", "getelementptr", " i8, ptr ", function.local("node"), ", i64 24")
    validate.emit("stored_magic", "load", " i64, ptr ", function.local("magic_slot"))
    validate.emit("mark_magic", "load", " i64, ptr ", module.symbol("__xcc_aot_phase_mark_magic"))
    validate.emit(
        "valid",
        "icmp",
        " eq i64 ",
        function.local("stored_magic"),
        ", ",
        function.local("mark_magic"),
    )
    validate.emit(
        None,
        "br",
        " i1 ",
        function.local("valid"),
        ", label ",
        function.local("compare"),
        ", label ",
        function.local("corrupt"),
    )
    compare = function.append_block("compare")
    compare.emit(
        "node_state_slot", "getelementptr", " i8, ptr ", function.local("node"), ", i64 32"
    )
    compare.emit("node_state", "load", " i64, ptr ", function.local("node_state_slot"))
    compare.emit(
        "node_exact_bit", "and", " i64 ", function.local("node_state"), ", -9223372036854775808"
    )
    compare.emit("node_exact", "icmp", " ne i64 ", function.local("node_exact_bit"), ", 0")
    compare.emit(
        "target_exact",
        "or",
        " i1 ",
        function.local("exact_seen"),
        ", ",
        function.local("node_exact"),
    )
    compare.emit(
        "matches", "icmp", " eq ptr ", function.local("node"), ", ", function.local("target")
    )
    compare.emit(
        None,
        "br",
        " i1 ",
        function.local("matches"),
        ", label ",
        function.local("check_parent"),
        ", label ",
        function.local("advance"),
    )
    advance = function.append_block("advance")
    advance.emit("parent_slot", "getelementptr", " i8, ptr ", function.local("node"), ", i64 16")
    advance.emit("parent", "load", " ptr, ptr ", function.local("parent_slot"))
    advance.emit("has_parent", "icmp", " ne ptr ", function.local("parent"), ", null")
    advance.emit(
        None,
        "br",
        " i1 ",
        function.local("has_parent"),
        ", label ",
        function.local("validate"),
        ", label ",
        function.local("not_deferred"),
    )
    check_parent = function.append_block("check_parent")
    check_parent.emit(
        None,
        "br",
        " i1 ",
        function.local("target_exact"),
        ", label ",
        function.local("not_deferred"),
        ", label ",
        function.local("check_deferred_parent"),
    )
    check_deferred_parent = function.append_block("check_deferred_parent")
    check_deferred_parent.emit(
        "target_parent_slot", "getelementptr", " i8, ptr ", function.local("target"), ", i64 16"
    )
    check_deferred_parent.emit(
        "target_parent", "load", " ptr, ptr ", function.local("target_parent_slot")
    )
    check_deferred_parent.emit(
        "target_has_parent", "icmp", " ne ptr ", function.local("target_parent"), ", null"
    )
    check_deferred_parent.emit(
        None,
        "br",
        " i1 ",
        function.local("target_has_parent"),
        ", label ",
        function.local("defer_entry"),
        ", label ",
        function.local("not_deferred"),
    )
    defer_entry = function.append_block("defer_entry")
    defer_entry.emit(None, "br", " label ", function.local("defer"))
    defer = function.append_block("defer")
    defer.emit(
        "deferred_mark",
        "phi",
        " ptr [ ",
        function.local("top"),
        ", ",
        function.local("defer_entry"),
        " ], [ ",
        function.local("deferred_parent"),
        ", ",
        function.local("defer_next"),
        " ]",
    )
    defer.emit(
        "deferred_slot", "getelementptr", " i8, ptr ", function.local("deferred_mark"), ", i64 32"
    )
    defer.emit("mark_state", "load", " i64, ptr ", function.local("deferred_slot"))
    defer.emit("deferred_state", "or", " i64 ", function.local("mark_state"), ", 1")
    defer.emit(
        None,
        "store",
        " i64 ",
        function.local("deferred_state"),
        ", ptr ",
        function.local("deferred_slot"),
    )
    defer.emit(
        "deferred_done",
        "icmp",
        " eq ptr ",
        function.local("deferred_mark"),
        ", ",
        function.local("target"),
    )
    defer.emit(
        None,
        "br",
        " i1 ",
        function.local("deferred_done"),
        ", label ",
        function.local("deferred"),
        ", label ",
        function.local("defer_next"),
    )
    defer_next = function.append_block("defer_next")
    defer_next.emit(
        "deferred_parent_slot",
        "getelementptr",
        " i8, ptr ",
        function.local("deferred_mark"),
        ", i64 16",
    )
    defer_next.emit("deferred_parent", "load", " ptr, ptr ", function.local("deferred_parent_slot"))
    defer_next.emit(None, "br", " label ", function.local("defer"))
    deferred = function.append_block("deferred")
    deferred.emit(None, "ret", " i1 true")
    not_deferred = function.append_block("not_deferred")
    not_deferred.emit(None, "ret", " i1 false")
    corrupt = function.append_block("corrupt")
    corrupt.emit(None, "call", " void ", module.symbol("__xcc_aot_memory_safety_fail"), "()")
    corrupt.emit(None, "unreachable")


def _build___xcc_aot_phase_capture_exact(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_phase_capture_exact")
    entry = function.append_block("entry")
    entry.emit(
        "target",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_phase_capture_target"),
        "(ptr ",
        function.local("owner"),
        ")",
    )
    entry.emit(
        "deferred",
        "call",
        " i1 ",
        module.symbol("__xcc_aot_phase_capture_defer"),
        "(ptr ",
        function.local("target"),
        ")",
    )
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("deferred"),
        ", label ",
        function.local("done"),
        ", label ",
        function.local("promote"),
    )
    promote = function.append_block("promote")
    promote.emit(
        "promoted",
        "call",
        " i1 ",
        module.symbol("__xcc_aot_phase_promote_to"),
        "(ptr ",
        function.local("value"),
        ", ptr ",
        function.local("target"),
        ")",
    )
    promote.emit(None, "br", " label ", function.local("done"))
    done = function.append_block("done")
    done.emit(None, "ret", " void")


def _build___xcc_aot_phase_commit(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_phase_commit")
    entry = function.append_block("entry")
    entry.emit("top_mark", "load", " ptr, ptr ", module.symbol("__xcc_aot_phase_mark_head"))
    entry.emit(
        "mark_is_top", "icmp", " eq ptr ", function.local("top_mark"), ", ", function.local("mark")
    )
    entry.emit("mark_exists", "icmp", " ne ptr ", function.local("top_mark"), ", null")
    entry.emit("depth", "load", " i64, ptr ", module.symbol("__xcc_aot_phase_depth"))
    entry.emit("has_depth", "icmp", " ugt i64 ", function.local("depth"), ", 0")
    entry.emit(
        "valid_top",
        "and",
        " i1 ",
        function.local("mark_is_top"),
        ", ",
        function.local("mark_exists"),
    )
    entry.emit(
        "valid_mark", "and", " i1 ", function.local("valid_top"), ", ", function.local("has_depth")
    )
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("valid_mark"),
        ", label ",
        function.local("validate"),
        ", label ",
        function.local("fail"),
    )
    validate = function.append_block("validate")
    validate.emit("magic_slot", "getelementptr", " i8, ptr ", function.local("mark"), ", i64 24")
    validate.emit("stored_magic", "load", " i64, ptr ", function.local("magic_slot"))
    validate.emit("mark_magic", "load", " i64, ptr ", module.symbol("__xcc_aot_phase_mark_magic"))
    validate.emit(
        "valid_magic",
        "icmp",
        " eq i64 ",
        function.local("stored_magic"),
        ", ",
        function.local("mark_magic"),
    )
    validate.emit(
        None,
        "br",
        " i1 ",
        function.local("valid_magic"),
        ", label ",
        function.local("validate_depth"),
        ", label ",
        function.local("fail"),
    )
    validate_depth = function.append_block("validate_depth")
    validate_depth.emit(
        "state_slot", "getelementptr", " i8, ptr ", function.local("mark"), ", i64 32"
    )
    validate_depth.emit("mark_state", "load", " i64, ptr ", function.local("state_slot"))
    validate_depth.emit("mark_depth_raw", "lshr", " i64 ", function.local("mark_state"), ", 1")
    validate_depth.emit(
        "mark_depth", "and", " i64 ", function.local("mark_depth_raw"), ", 16777215"
    )
    validate_depth.emit(
        "right_depth",
        "icmp",
        " eq i64 ",
        function.local("mark_depth"),
        ", ",
        function.local("depth"),
    )
    validate_depth.emit(
        None,
        "br",
        " i1 ",
        function.local("right_depth"),
        ", label ",
        function.local("validate_account"),
        ", label ",
        function.local("fail"),
    )
    validate_account = function.append_block("validate_account")
    validate_account.emit("used", "load", " i64, ptr ", module.symbol("__xcc_aot_allocated_bytes"))
    validate_account.emit("account_valid", "icmp", " uge i64 ", function.local("used"), ", 40")
    validate_account.emit(
        None,
        "br",
        " i1 ",
        function.local("account_valid"),
        ", label ",
        function.local("unlink"),
        ", label ",
        function.local("fail"),
    )
    unlink = function.append_block("unlink")
    unlink.emit("previous", "load", " ptr, ptr ", function.local("mark"))
    unlink.emit("next_slot", "getelementptr", " i8, ptr ", function.local("mark"), ", i64 8")
    unlink.emit("next", "load", " ptr, ptr ", function.local("next_slot"))
    unlink.emit(
        "previous_mark_slot", "getelementptr", " i8, ptr ", function.local("mark"), ", i64 16"
    )
    unlink.emit("previous_mark", "load", " ptr, ptr ", function.local("previous_mark_slot"))
    unlink.emit("parent_depth", "sub", " i64 ", function.local("mark_depth"), ", 1")
    unlink.emit("parent_region", "shl", " i64 ", function.local("parent_depth"), ", 32")
    unlink.emit("has_next", "icmp", " ne ptr ", function.local("next"), ", null")
    unlink.emit(
        None,
        "br",
        " i1 ",
        function.local("has_next"),
        ", label ",
        function.local("retag_entry"),
        ", label ",
        function.local("empty"),
    )
    retag_entry = function.append_block("retag_entry")
    retag_entry.emit(None, "br", " label ", function.local("retag"))
    retag = function.append_block("retag")
    retag.emit(
        "retag_node",
        "phi",
        " ptr [ ",
        function.local("next"),
        ", ",
        function.local("retag_entry"),
        " ], [ ",
        function.local("retag_newer"),
        ", ",
        function.local("retag_advance"),
        " ]",
    )
    retag.emit(
        "retag_size_slot", "getelementptr", " i8, ptr ", function.local("retag_node"), ", i64 16"
    )
    retag.emit("retag_tracked_size", "load", " i64, ptr ", function.local("retag_size_slot"))
    retag.emit("retag_tag", "lshr", " i64 ", function.local("retag_tracked_size"), ", 48")
    retag.emit("allocation_tag", "load", " i64, ptr ", module.symbol("__xcc_aot_allocation_tag"))
    retag.emit(
        "valid_allocation",
        "icmp",
        " eq i64 ",
        function.local("retag_tag"),
        ", ",
        function.local("allocation_tag"),
    )
    retag.emit(
        None,
        "br",
        " i1 ",
        function.local("valid_allocation"),
        ", label ",
        function.local("retag_region"),
        ", label ",
        function.local("fail"),
    )
    retag_region = function.append_block("retag_region")
    retag_region.emit(
        "retag_owner_depth_raw", "lshr", " i64 ", function.local("retag_tracked_size"), ", 32"
    )
    retag_region.emit(
        "retag_owner_depth", "and", " i64 ", function.local("retag_owner_depth_raw"), ", 65535"
    )
    retag_region.emit(
        "owned_by_mark",
        "icmp",
        " eq i64 ",
        function.local("retag_owner_depth"),
        ", ",
        function.local("mark_depth"),
    )
    retag_region.emit(
        None,
        "br",
        " i1 ",
        function.local("owned_by_mark"),
        ", label ",
        function.local("retag_store"),
        ", label ",
        function.local("fail"),
    )
    retag_store = function.append_block("retag_store")
    retag_store.emit(
        "retag_size", "and", " i64 ", function.local("retag_tracked_size"), ", 4294967295"
    )
    retag_store.emit(
        "retag_tag_region",
        "and",
        " i64 ",
        function.local("retag_tracked_size"),
        ", -281474976710656",
    )
    retag_store.emit(
        "retag_parent_region",
        "or",
        " i64 ",
        function.local("retag_tag_region"),
        ", ",
        function.local("parent_region"),
    )
    retag_store.emit(
        "retagged_size",
        "or",
        " i64 ",
        function.local("retag_parent_region"),
        ", ",
        function.local("retag_size"),
    )
    retag_store.emit(
        None,
        "store",
        " i64 ",
        function.local("retagged_size"),
        ", ptr ",
        function.local("retag_size_slot"),
    )
    retag_store.emit(
        "retag_next_slot", "getelementptr", " i8, ptr ", function.local("retag_node"), ", i64 8"
    )
    retag_store.emit("retag_newer", "load", " ptr, ptr ", function.local("retag_next_slot"))
    retag_store.emit("retag_done", "icmp", " eq ptr ", function.local("retag_newer"), ", null")
    retag_store.emit(
        None,
        "br",
        " i1 ",
        function.local("retag_done"),
        ", label ",
        function.local("keep_allocations"),
        ", label ",
        function.local("retag_advance"),
    )
    retag_advance = function.append_block("retag_advance")
    retag_advance.emit(None, "br", " label ", function.local("retag"))
    keep_allocations = function.append_block("keep_allocations")
    keep_allocations.emit(
        None, "store", " ptr ", function.local("previous"), ", ptr ", function.local("next")
    )
    keep_allocations.emit(None, "br", " label ", function.local("link_previous"))
    empty = function.append_block("empty")
    empty.emit(
        None,
        "store",
        " ptr ",
        function.local("previous"),
        ", ptr ",
        module.symbol("__xcc_aot_allocation_head"),
    )
    empty.emit(None, "br", " label ", function.local("link_previous"))
    link_previous = function.append_block("link_previous")
    link_previous.emit("has_previous", "icmp", " ne ptr ", function.local("previous"), ", null")
    link_previous.emit(
        None,
        "br",
        " i1 ",
        function.local("has_previous"),
        ", label ",
        function.local("repair_previous"),
        ", label ",
        function.local("finish"),
    )
    repair_previous = function.append_block("repair_previous")
    repair_previous.emit(
        "previous_next", "getelementptr", " i8, ptr ", function.local("previous"), ", i64 8"
    )
    repair_previous.emit(
        None, "store", " ptr ", function.local("next"), ", ptr ", function.local("previous_next")
    )
    repair_previous.emit(None, "br", " label ", function.local("finish"))
    finish = function.append_block("finish")
    finish.emit(
        None,
        "store",
        " ptr ",
        function.local("previous_mark"),
        ", ptr ",
        module.symbol("__xcc_aot_phase_mark_head"),
    )
    finish.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_phase_capture_cache_exit"),
        "(ptr ",
        function.local("mark"),
        ")",
    )
    finish.emit("remaining", "sub", " i64 ", function.local("used"), ", 40")
    finish.emit(
        None,
        "store",
        " i64 ",
        function.local("remaining"),
        ", ptr ",
        module.symbol("__xcc_aot_allocated_bytes"),
    )
    finish.emit(None, "store", " i64 0, ptr ", function.local("magic_slot"))
    finish.emit(None, "call", " void ", module.symbol("free"), "(ptr ", function.local("mark"), ")")
    finish.emit("next_depth", "sub", " i64 ", function.local("depth"), ", 1")
    finish.emit(
        None,
        "store",
        " i64 ",
        function.local("next_depth"),
        ", ptr ",
        module.symbol("__xcc_aot_phase_depth"),
    )
    finish.emit("still_active", "icmp", " ugt i64 ", function.local("next_depth"), ", 0")
    finish.emit(
        None,
        "store",
        " i1 ",
        function.local("still_active"),
        ", ptr ",
        module.symbol("__xcc_aot_phase_active"),
    )
    finish.emit(None, "ret", " void")
    fail = function.append_block("fail")
    fail.emit(None, "call", " void ", module.symbol("__xcc_aot_memory_safety_fail"), "()")
    fail.emit(None, "unreachable")


def _build___xcc_aot_phase_allocated_bytes(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_phase_allocated_bytes")
    entry = function.append_block("entry")
    entry.emit("used", "load", " i64, ptr ", module.symbol("__xcc_aot_allocated_bytes"))
    entry.emit(None, "ret", " i64 ", function.local("used"))


def _build___xcc_aot_single_byte_string(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_single_byte_string")
    entry = function.append_block("entry")
    entry.emit("index", "zext", " i8 ", function.local("byte"), " to i64")
    entry.emit("offset", "shl", " i64 ", function.local("index"), ", 1")
    entry.emit(
        "result",
        "getelementptr",
        " [512 x i8], ptr ",
        module.symbol("__xcc_aot_single_byte_strings"),
        ",",
    )
    entry.continue_("  i64 0, i64 ", function.local("offset"))
    entry.emit(None, "store", " i8 ", function.local("byte"), ", ptr ", function.local("result"))
    entry.emit("terminator", "getelementptr", " i8, ptr ", function.local("result"), ", i64 1")
    entry.emit(None, "store", " i8 0, ptr ", function.local("terminator"))
    entry.emit(None, "ret", " ptr ", function.local("result"))


def _build___xcc_aot_phase_reset(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_phase_reset")
    entry = function.append_block("entry")
    entry.emit("top_mark", "load", " ptr, ptr ", module.symbol("__xcc_aot_phase_mark_head"))
    entry.emit(
        "mark_is_top", "icmp", " eq ptr ", function.local("top_mark"), ", ", function.local("mark")
    )
    entry.emit("mark_exists", "icmp", " ne ptr ", function.local("top_mark"), ", null")
    entry.emit("depth", "load", " i64, ptr ", module.symbol("__xcc_aot_phase_depth"))
    entry.emit("has_depth", "icmp", " ugt i64 ", function.local("depth"), ", 0")
    entry.emit(
        "valid_top",
        "and",
        " i1 ",
        function.local("mark_is_top"),
        ", ",
        function.local("mark_exists"),
    )
    entry.emit(
        "valid_mark", "and", " i1 ", function.local("valid_top"), ", ", function.local("has_depth")
    )
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("valid_mark"),
        ", label ",
        function.local("check"),
        ", label ",
        function.local("fail"),
    )
    check = function.append_block("check")
    check.emit("current", "load", " ptr, ptr ", module.symbol("__xcc_aot_allocation_head"))
    check.emit(
        "finished", "icmp", " eq ptr ", function.local("current"), ", ", function.local("mark")
    )
    check.emit(
        None,
        "br",
        " i1 ",
        function.local("finished"),
        ", label ",
        function.local("validate_marker"),
        ", label ",
        function.local("validate_allocation"),
    )
    validate_allocation = function.append_block("validate_allocation")
    validate_allocation.emit("missing", "icmp", " eq ptr ", function.local("current"), ", null")
    validate_allocation.emit(
        None,
        "br",
        " i1 ",
        function.local("missing"),
        ", label ",
        function.local("fail"),
        ", label ",
        function.local("release"),
    )
    release = function.append_block("release")
    release.emit("payload", "getelementptr", " i8, ptr ", function.local("current"), ", i64 32")
    release.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_free_allocation"),
        "(ptr ",
        function.local("current"),
        ", ptr ",
        function.local("payload"),
        ")",
    )
    release.emit(None, "br", " label ", function.local("check"))
    validate_marker = function.append_block("validate_marker")
    validate_marker.emit(
        "magic_slot", "getelementptr", " i8, ptr ", function.local("mark"), ", i64 24"
    )
    validate_marker.emit("stored_magic", "load", " i64, ptr ", function.local("magic_slot"))
    validate_marker.emit(
        "mark_magic", "load", " i64, ptr ", module.symbol("__xcc_aot_phase_mark_magic")
    )
    validate_marker.emit(
        "valid_magic",
        "icmp",
        " eq i64 ",
        function.local("stored_magic"),
        ", ",
        function.local("mark_magic"),
    )
    validate_marker.emit(
        None,
        "br",
        " i1 ",
        function.local("valid_magic"),
        ", label ",
        function.local("validate_account"),
        ", label ",
        function.local("fail"),
    )
    validate_account = function.append_block("validate_account")
    validate_account.emit("used", "load", " i64, ptr ", module.symbol("__xcc_aot_allocated_bytes"))
    validate_account.emit("account_valid", "icmp", " uge i64 ", function.local("used"), ", 40")
    validate_account.emit(
        None,
        "br",
        " i1 ",
        function.local("account_valid"),
        ", label ",
        function.local("unlink_marker"),
        ", label ",
        function.local("fail"),
    )
    unlink_marker = function.append_block("unlink_marker")
    unlink_marker.emit("previous", "load", " ptr, ptr ", function.local("mark"))
    unlink_marker.emit(
        "previous_mark_slot", "getelementptr", " i8, ptr ", function.local("mark"), ", i64 16"
    )
    unlink_marker.emit("previous_mark", "load", " ptr, ptr ", function.local("previous_mark_slot"))
    unlink_marker.emit(
        None,
        "store",
        " ptr ",
        function.local("previous"),
        ", ptr ",
        module.symbol("__xcc_aot_allocation_head"),
    )
    unlink_marker.emit(
        None,
        "store",
        " ptr ",
        function.local("previous_mark"),
        ", ptr ",
        module.symbol("__xcc_aot_phase_mark_head"),
    )
    unlink_marker.emit("has_previous", "icmp", " ne ptr ", function.local("previous"), ", null")
    unlink_marker.emit(
        None,
        "br",
        " i1 ",
        function.local("has_previous"),
        ", label ",
        function.local("repair_previous"),
        ", label ",
        function.local("finish_marker"),
    )
    repair_previous = function.append_block("repair_previous")
    repair_previous.emit(
        "previous_next", "getelementptr", " i8, ptr ", function.local("previous"), ", i64 8"
    )
    repair_previous.emit(None, "store", " ptr null, ptr ", function.local("previous_next"))
    repair_previous.emit(None, "br", " label ", function.local("finish_marker"))
    finish_marker = function.append_block("finish_marker")
    finish_marker.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_phase_capture_cache_exit"),
        "(ptr ",
        function.local("mark"),
        ")",
    )
    finish_marker.emit("remaining", "sub", " i64 ", function.local("used"), ", 40")
    finish_marker.emit(
        None,
        "store",
        " i64 ",
        function.local("remaining"),
        ", ptr ",
        module.symbol("__xcc_aot_allocated_bytes"),
    )
    finish_marker.emit(None, "store", " i64 0, ptr ", function.local("magic_slot"))
    finish_marker.emit(
        None, "call", " void ", module.symbol("free"), "(ptr ", function.local("mark"), ")"
    )
    finish_marker.emit("next_depth", "sub", " i64 ", function.local("depth"), ", 1")
    finish_marker.emit(
        None,
        "store",
        " i64 ",
        function.local("next_depth"),
        ", ptr ",
        module.symbol("__xcc_aot_phase_depth"),
    )
    finish_marker.emit("still_active", "icmp", " ugt i64 ", function.local("next_depth"), ", 0")
    finish_marker.emit(
        None,
        "store",
        " i1 ",
        function.local("still_active"),
        ", ptr ",
        module.symbol("__xcc_aot_phase_active"),
    )
    finish_marker.emit(None, "ret", " void")
    fail = function.append_block("fail")
    fail.emit(None, "call", " void ", module.symbol("__xcc_aot_memory_safety_fail"), "()")
    fail.emit(None, "unreachable")


def _build___xcc_aot_phase_finish(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_phase_finish")
    entry = function.append_block("entry")
    entry.emit("top", "load", " ptr, ptr ", module.symbol("__xcc_aot_phase_mark_head"))
    entry.emit("is_top", "icmp", " eq ptr ", function.local("mark"), ", ", function.local("top"))
    entry.emit("has_top", "icmp", " ne ptr ", function.local("top"), ", null")
    entry.emit("matches", "and", " i1 ", function.local("is_top"), ", ", function.local("has_top"))
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("matches"),
        ", label ",
        function.local("validate"),
        ", label ",
        function.local("fail"),
    )
    validate = function.append_block("validate")
    validate.emit("magic_slot", "getelementptr", " i8, ptr ", function.local("mark"), ", i64 24")
    validate.emit("stored_magic", "load", " i64, ptr ", function.local("magic_slot"))
    validate.emit("mark_magic", "load", " i64, ptr ", module.symbol("__xcc_aot_phase_mark_magic"))
    validate.emit(
        "valid",
        "icmp",
        " eq i64 ",
        function.local("stored_magic"),
        ", ",
        function.local("mark_magic"),
    )
    validate.emit(
        None,
        "br",
        " i1 ",
        function.local("valid"),
        ", label ",
        function.local("dispatch"),
        ", label ",
        function.local("fail"),
    )
    dispatch = function.append_block("dispatch")
    dispatch.emit("deferred_slot", "getelementptr", " i8, ptr ", function.local("mark"), ", i64 32")
    dispatch.emit("mark_state", "load", " i64, ptr ", function.local("deferred_slot"))
    dispatch.emit("deferred_bit", "and", " i64 ", function.local("mark_state"), ", 1")
    dispatch.emit("deferred", "icmp", " ne i64 ", function.local("deferred_bit"), ", 0")
    dispatch.emit(
        None,
        "br",
        " i1 ",
        function.local("deferred"),
        ", label ",
        function.local("commit"),
        ", label ",
        function.local("reset"),
    )
    commit = function.append_block("commit")
    commit.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_phase_commit"),
        "(ptr ",
        function.local("mark"),
        ")",
    )
    commit.emit(None, "ret", " void")
    reset = function.append_block("reset")
    reset.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_phase_reset"),
        "(ptr ",
        function.local("mark"),
        ")",
    )
    reset.emit(None, "ret", " void")
    fail = function.append_block("fail")
    fail.emit(None, "call", " void ", module.symbol("__xcc_aot_memory_safety_fail"), "()")
    fail.emit(None, "unreachable")


def _build___xcc_aot_object_repr(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_object_repr")
    entry = function.append_block("entry")
    entry.emit("is_null", "icmp", " eq ptr ", function.local("object"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("is_null"),
        ", label ",
        function.local("none"),
        ", label ",
        function.local("tagged"),
    )
    none = function.append_block("none")
    none.emit(None, "ret", " ptr ", module.symbol("__xcc_aot_repr_none"))
    tagged = function.append_block("tagged")
    tagged.emit("tag", "load", " i64, ptr ", function.local("object"))
    tagged.emit(
        None, "switch", " i64 ", function.local("tag"), ", label ", function.local("fallback"), " ["
    )
    tagged.continue_("  i64 1, label ", function.local("bool"))
    tagged.continue_("  i64 2, label ", function.local("integer"))
    tagged.continue_("  i64 3, label ", function.local("float"))
    tagged.continue_("  i64 4, label ", function.local("string"))
    tagged.continue_("  i64 5, label ", function.local("bytes"))
    tagged.continue_("  i64 6, label ", function.local("complex"))
    tagged.continue_("  i64 7, label ", function.local("ellipsis"))
    tagged.continue_("]")
    bool = function.append_block("bool")
    bool.emit("bool_payload", "getelementptr", " i8, ptr ", function.local("object"), ", i64 8")
    bool.emit("bool_value", "load", " i64, ptr ", function.local("bool_payload"))
    bool.emit("bool_truth", "icmp", " ne i64 ", function.local("bool_value"), ", 0")
    bool.emit(
        "bool_repr",
        "select",
        " i1 ",
        function.local("bool_truth"),
        ", ptr ",
        module.symbol("__xcc_aot_repr_true"),
        ", ptr ",
        module.symbol("__xcc_aot_repr_false"),
    )
    bool.emit(None, "ret", " ptr ", function.local("bool_repr"))
    integer = function.append_block("integer")
    integer.emit("int_payload", "getelementptr", " i8, ptr ", function.local("object"), ", i64 8")
    integer.emit("int_value", "load", " i64, ptr ", function.local("int_payload"))
    integer.emit(
        "int_repr",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_i64_to_string"),
        "(i64 ",
        function.local("int_value"),
        ")",
    )
    integer.emit(None, "ret", " ptr ", function.local("int_repr"))
    float = function.append_block("float")
    float.emit("float_payload", "getelementptr", " i8, ptr ", function.local("object"), ", i64 8")
    float.emit("float_value", "load", " double, ptr ", function.local("float_payload"))
    float.emit("float_repr", "call", " ptr ", module.symbol("malloc"), "(i64 64)")
    float.emit(
        "float_written", "call", " i32 (ptr, i64, ptr, ...) ", module.symbol("snprintf"), "("
    )
    float.continue_(
        "  ptr ",
        function.local("float_repr"),
        ", i64 64, ptr ",
        module.symbol("__xcc_aot_fmt_float"),
        ", double ",
        function.local("float_value"),
        ")",
    )
    float.emit(None, "ret", " ptr ", function.local("float_repr"))
    string = function.append_block("string")
    string.emit("string_payload", "getelementptr", " i8, ptr ", function.local("object"), ", i64 8")
    string.emit("string_value", "load", " ptr, ptr ", function.local("string_payload"))
    string.emit(
        "string_len",
        "call",
        " i64 ",
        module.symbol("strlen"),
        "(ptr ",
        function.local("string_value"),
        ")",
    )
    string.emit("string_total", "add", " i64 ", function.local("string_len"), ", 3")
    string.emit(
        "string_repr",
        "call",
        " ptr ",
        module.symbol("malloc"),
        "(i64 ",
        function.local("string_total"),
        ")",
    )
    string.emit(None, "store", " i8 39, ptr ", function.local("string_repr"))
    string.emit(
        "string_data", "getelementptr", " i8, ptr ", function.local("string_repr"), ", i64 1"
    )
    string.emit("string_copied", "call", " ptr ", module.symbol("memcpy"), "(")
    string.continue_(
        "  ptr ",
        function.local("string_data"),
        ", ptr ",
        function.local("string_value"),
        ", i64 ",
        function.local("string_len"),
        ")",
    )
    string.emit("string_quote_index", "add", " i64 ", function.local("string_len"), ", 1")
    string.emit(
        "string_quote",
        "getelementptr",
        " i8, ptr ",
        function.local("string_repr"),
        ", i64 ",
        function.local("string_quote_index"),
    )
    string.emit(None, "store", " i8 39, ptr ", function.local("string_quote"))
    string.emit("string_nul_index", "add", " i64 ", function.local("string_len"), ", 2")
    string.emit(
        "string_nul",
        "getelementptr",
        " i8, ptr ",
        function.local("string_repr"),
        ", i64 ",
        function.local("string_nul_index"),
    )
    string.emit(None, "store", " i8 0, ptr ", function.local("string_nul"))
    string.emit(None, "ret", " ptr ", function.local("string_repr"))
    bytes = function.append_block("bytes")
    bytes.emit("bytes_payload", "getelementptr", " i8, ptr ", function.local("object"), ", i64 8")
    bytes.emit("bytes_value", "load", " ptr, ptr ", function.local("bytes_payload"))
    bytes.emit(
        "bytes_len",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_bytes_len"),
        "(ptr ",
        function.local("bytes_value"),
        ")",
    )
    bytes.emit(
        "bytes_data_value",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_bytes_data"),
        "(ptr ",
        function.local("bytes_value"),
        ")",
    )
    bytes.emit("bytes_total", "add", " i64 ", function.local("bytes_len"), ", 4")
    bytes.emit(
        "bytes_repr",
        "call",
        " ptr ",
        module.symbol("malloc"),
        "(i64 ",
        function.local("bytes_total"),
        ")",
    )
    bytes.emit(None, "store", " i8 98, ptr ", function.local("bytes_repr"))
    bytes.emit(
        "bytes_open_quote", "getelementptr", " i8, ptr ", function.local("bytes_repr"), ", i64 1"
    )
    bytes.emit(None, "store", " i8 39, ptr ", function.local("bytes_open_quote"))
    bytes.emit(
        "bytes_out_data", "getelementptr", " i8, ptr ", function.local("bytes_repr"), ", i64 2"
    )
    bytes.emit("bytes_copied", "call", " ptr ", module.symbol("memcpy"), "(")
    bytes.continue_(
        "  ptr ",
        function.local("bytes_out_data"),
        ", ptr ",
        function.local("bytes_data_value"),
        ", i64 ",
        function.local("bytes_len"),
        ")",
    )
    bytes.emit("bytes_quote_index", "add", " i64 ", function.local("bytes_len"), ", 2")
    bytes.emit(
        "bytes_quote",
        "getelementptr",
        " i8, ptr ",
        function.local("bytes_repr"),
        ", i64 ",
        function.local("bytes_quote_index"),
    )
    bytes.emit(None, "store", " i8 39, ptr ", function.local("bytes_quote"))
    bytes.emit("bytes_nul_index", "add", " i64 ", function.local("bytes_len"), ", 3")
    bytes.emit(
        "bytes_nul",
        "getelementptr",
        " i8, ptr ",
        function.local("bytes_repr"),
        ", i64 ",
        function.local("bytes_nul_index"),
    )
    bytes.emit(None, "store", " i8 0, ptr ", function.local("bytes_nul"))
    bytes.emit(None, "ret", " ptr ", function.local("bytes_repr"))
    complex = function.append_block("complex")
    complex.emit(
        "complex_payload", "getelementptr", " i8, ptr ", function.local("object"), ", i64 8"
    )
    complex.emit("complex_value", "load", " ptr, ptr ", function.local("complex_payload"))
    complex.emit("complex_real", "load", " double, ptr ", function.local("complex_value"))
    complex.emit(
        "complex_imag_ptr", "getelementptr", " i8, ptr ", function.local("complex_value"), ", i64 8"
    )
    complex.emit("complex_imag", "load", " double, ptr ", function.local("complex_imag_ptr"))
    complex.emit(
        "complex_real_zero", "fcmp", " oeq double ", function.local("complex_real"), ", 0.0"
    )
    complex.emit(
        None,
        "br",
        " i1 ",
        function.local("complex_real_zero"),
        ", label ",
        function.local("imaginary"),
        ", label ",
        function.local("full_complex"),
    )
    imaginary = function.append_block("imaginary")
    imaginary.emit("imag_repr", "call", " ptr ", module.symbol("malloc"), "(i64 96)")
    imaginary.emit(
        "imag_written", "call", " i32 (ptr, i64, ptr, ...) ", module.symbol("snprintf"), "("
    )
    imaginary.continue_(
        "  ptr ",
        function.local("imag_repr"),
        ", i64 96, ptr ",
        module.symbol("__xcc_aot_fmt_imaginary"),
        ", double ",
        function.local("complex_imag"),
        ")",
    )
    imaginary.emit(None, "ret", " ptr ", function.local("imag_repr"))
    full_complex = function.append_block("full_complex")
    full_complex.emit("complex_repr", "call", " ptr ", module.symbol("malloc"), "(i64 96)")
    full_complex.emit(
        "complex_written", "call", " i32 (ptr, i64, ptr, ...) ", module.symbol("snprintf"), "("
    )
    full_complex.continue_(
        "  ptr ",
        function.local("complex_repr"),
        ", i64 96, ptr ",
        module.symbol("__xcc_aot_fmt_complex"),
        ",",
    )
    full_complex.continue_(
        "  double ",
        function.local("complex_real"),
        ", double ",
        function.local("complex_imag"),
        ")",
    )
    full_complex.emit(None, "ret", " ptr ", function.local("complex_repr"))
    ellipsis = function.append_block("ellipsis")
    ellipsis.emit(None, "ret", " ptr ", module.symbol("__xcc_aot_repr_ellipsis"))
    fallback = function.append_block("fallback")
    fallback.emit(None, "ret", " ptr ", module.symbol("__xcc_aot_repr_object"))


def _build___xcc_aot_object_str(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_object_str")
    entry = function.append_block("entry")
    entry.emit("is_null", "icmp", " eq ptr ", function.local("object"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("is_null"),
        ", label ",
        function.local("none"),
        ", label ",
        function.local("tagged"),
    )
    none = function.append_block("none")
    none.emit(None, "ret", " ptr ", module.symbol("__xcc_aot_repr_none"))
    tagged = function.append_block("tagged")
    tagged.emit("tag", "load", " i64, ptr ", function.local("object"))
    tagged.emit("is_string", "icmp", " eq i64 ", function.local("tag"), ", 4")
    tagged.emit(
        None,
        "br",
        " i1 ",
        function.local("is_string"),
        ", label ",
        function.local("string"),
        ", label ",
        function.local("fallback"),
    )
    string = function.append_block("string")
    string.emit("string_payload", "getelementptr", " i8, ptr ", function.local("object"), ", i64 8")
    string.emit("string_value", "load", " ptr, ptr ", function.local("string_payload"))
    string.emit(None, "ret", " ptr ", function.local("string_value"))
    fallback = function.append_block("fallback")
    fallback.emit(
        "repr",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_object_repr"),
        "(ptr ",
        function.local("object"),
        ")",
    )
    fallback.emit(None, "ret", " ptr ", function.local("repr"))


def _build___xcc_aot_complex_new(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_complex_new")
    entry = function.append_block("entry")
    entry.emit("value", "call", " ptr ", module.symbol("malloc"), "(i64 16)")
    entry.emit(None, "store", " double ", function.local("real"), ", ptr ", function.local("value"))
    entry.emit("imaginary_ptr", "getelementptr", " i8, ptr ", function.local("value"), ", i64 8")
    entry.emit(
        None,
        "store",
        " double ",
        function.local("imaginary"),
        ", ptr ",
        function.local("imaginary_ptr"),
    )
    entry.emit(None, "ret", " ptr ", function.local("value"))


def _build___xcc_aot_tuple_new(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_tuple_new")
    entry = function.append_block("entry")
    entry.emit("negative", "icmp", " slt i64 ", function.local("length"), ", 0")
    entry.emit("too_large", "icmp", " ugt i64 ", function.local("length"), ", 2305843009213693951")
    entry.emit(
        "invalid", "or", " i1 ", function.local("negative"), ", ", function.local("too_large")
    )
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("invalid"),
        ", label ",
        function.local("fail"),
        ", label ",
        function.local("header"),
    )
    header = function.append_block("header")
    header.emit("tuple", "call", " ptr ", module.symbol("__xcc_aot_alloc"), "(i64 40)")
    header.emit(None, "store", " i64 ", function.local("length"), ", ptr ", function.local("tuple"))
    header.emit("capacity_slot", "getelementptr", " i64, ptr ", function.local("tuple"), ", i64 1")
    header.emit(
        None, "store", " i64 ", function.local("length"), ", ptr ", function.local("capacity_slot")
    )
    header.emit("data_slot", "getelementptr", " ptr, ptr ", function.local("tuple"), ", i64 2")
    header.emit("empty", "icmp", " eq i64 ", function.local("length"), ", 0")
    header.emit(
        None,
        "br",
        " i1 ",
        function.local("empty"),
        ", label ",
        function.local("empty_data"),
        ", label ",
        function.local("allocate_data"),
    )
    empty_data = function.append_block("empty_data")
    empty_data.emit(None, "store", " ptr null, ptr ", function.local("data_slot"))
    empty_data.emit(None, "br", " label ", function.local("layout"))
    allocate_data = function.append_block("allocate_data")
    allocate_data.emit(
        "data",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_calloc"),
        "(i64 ",
        function.local("length"),
        ", i64 8)",
    )
    allocate_data.emit(
        None, "store", " ptr ", function.local("data"), ", ptr ", function.local("data_slot")
    )
    allocate_data.emit(None, "br", " label ", function.local("layout"))
    layout = function.append_block("layout")
    layout.emit(
        "layout_count_slot", "getelementptr", " i64, ptr ", function.local("tuple"), ", i64 3"
    )
    layout.emit(None, "store", " i64 0, ptr ", function.local("layout_count_slot"))
    layout.emit(
        "layout_tags_slot", "getelementptr", " ptr, ptr ", function.local("tuple"), ", i64 4"
    )
    layout.emit(None, "store", " ptr null, ptr ", function.local("layout_tags_slot"))
    layout.emit(None, "ret", " ptr ", function.local("tuple"))
    fail = function.append_block("fail")
    fail.emit(None, "call", " void ", module.symbol("__xcc_aot_allocation_fail"), "()")
    fail.emit(None, "unreachable")


def _build___xcc_aot_tuple_resolve(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_tuple_resolve")
    entry = function.append_block("entry")
    entry.emit(None, "ret", " ptr ", function.local("tuple"))


def _build___xcc_aot_tuple_capacity(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_tuple_capacity")
    entry = function.append_block("entry")
    entry.emit("is_null", "icmp", " eq ptr ", function.local("tuple"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("is_null"),
        ", label ",
        function.local("null"),
        ", label ",
        function.local("value"),
    )
    null = function.append_block("null")
    null.emit(None, "ret", " i64 0")
    value = function.append_block("value")
    value.emit("capacity_slot", "getelementptr", " i64, ptr ", function.local("tuple"), ", i64 1")
    value.emit("capacity", "load", " i64, ptr ", function.local("capacity_slot"))
    value.emit(None, "ret", " i64 ", function.local("capacity"))


def _build___xcc_aot_tuple_register_capacity(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_tuple_register_capacity")
    entry = function.append_block("entry")
    entry.emit("is_null", "icmp", " eq ptr ", function.local("tuple"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("is_null"),
        ", label ",
        function.local("done"),
        ", label ",
        function.local("check"),
    )
    check = function.append_block("check")
    check.emit("capacity_slot", "getelementptr", " i64, ptr ", function.local("tuple"), ", i64 1")
    check.emit("current", "load", " i64, ptr ", function.local("capacity_slot"))
    check.emit(
        "needs_growth",
        "icmp",
        " ugt i64 ",
        function.local("capacity"),
        ", ",
        function.local("current"),
    )
    check.emit(
        None,
        "br",
        " i1 ",
        function.local("needs_growth"),
        ", label ",
        function.local("grow"),
        ", label ",
        function.local("done"),
    )
    grow = function.append_block("grow")
    grow.emit("too_large", "icmp", " ugt i64 ", function.local("capacity"), ", 2305843009213693951")
    grow.emit(
        None,
        "br",
        " i1 ",
        function.local("too_large"),
        ", label ",
        function.local("fail"),
        ", label ",
        function.local("resize"),
    )
    resize = function.append_block("resize")
    resize.emit("old_bytes", "mul", " i64 ", function.local("current"), ", 8")
    resize.emit("new_bytes", "mul", " i64 ", function.local("capacity"), ", 8")
    resize.emit("data_slot", "getelementptr", " ptr, ptr ", function.local("tuple"), ", i64 2")
    resize.emit("data", "load", " ptr, ptr ", function.local("data_slot"))
    resize.emit(
        "resized",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_realloc"),
        "(ptr ",
        function.local("data"),
        ", i64 ",
        function.local("old_bytes"),
        ", i64 ",
        function.local("new_bytes"),
        ")",
    )
    resize.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_phase_capture_exact"),
        "(ptr ",
        function.local("tuple"),
        ", ptr ",
        function.local("resized"),
        ")",
    )
    resize.emit(
        None, "store", " ptr ", function.local("resized"), ", ptr ", function.local("data_slot")
    )
    resize.emit(
        None,
        "store",
        " i64 ",
        function.local("capacity"),
        ", ptr ",
        function.local("capacity_slot"),
    )
    resize.emit(None, "br", " label ", function.local("done"))
    fail = function.append_block("fail")
    fail.emit(None, "call", " void ", module.symbol("__xcc_aot_allocation_fail"), "()")
    fail.emit(None, "unreachable")
    done = function.append_block("done")
    done.emit(None, "ret", " void")


def _build___xcc_aot_tuple_forward(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_tuple_forward")
    entry = function.append_block("entry")
    entry.emit("old_null", "icmp", " eq ptr ", function.local("old"), ", null")
    entry.emit("new_null", "icmp", " eq ptr ", function.local("new"), ", null")
    entry.emit(
        "null_value", "or", " i1 ", function.local("old_null"), ", ", function.local("new_null")
    )
    entry.emit("same", "icmp", " eq ptr ", function.local("old"), ", ", function.local("new"))
    entry.emit("skip", "or", " i1 ", function.local("null_value"), ", ", function.local("same"))
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("skip"),
        ", label ",
        function.local("done"),
        ", label ",
        function.local("copy"),
    )
    copy = function.append_block("copy")
    copy.emit("new_len", "load", " i64, ptr ", function.local("new"))
    copy.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_tuple_register_capacity"),
        "(ptr ",
        function.local("old"),
        ", i64 ",
        function.local("new_len"),
        ")",
    )
    copy.emit("old_data_slot", "getelementptr", " ptr, ptr ", function.local("old"), ", i64 2")
    copy.emit("old_data", "load", " ptr, ptr ", function.local("old_data_slot"))
    copy.emit("new_data_slot", "getelementptr", " ptr, ptr ", function.local("new"), ", i64 2")
    copy.emit("new_data", "load", " ptr, ptr ", function.local("new_data_slot"))
    copy.emit("copy_bytes", "mul", " i64 ", function.local("new_len"), ", 8")
    copy.emit("empty", "icmp", " eq i64 ", function.local("new_len"), ", 0")
    copy.emit(
        None,
        "br",
        " i1 ",
        function.local("empty"),
        ", label ",
        function.local("commit"),
        ", label ",
        function.local("copy_data"),
    )
    copy_data = function.append_block("copy_data")
    copy_data.emit(
        "copied",
        "call",
        " ptr ",
        module.symbol("memcpy"),
        "(ptr ",
        function.local("old_data"),
        ", ptr ",
        function.local("new_data"),
        ", i64 ",
        function.local("copy_bytes"),
        ")",
    )
    copy_data.emit(None, "br", " label ", function.local("commit"))
    commit = function.append_block("commit")
    commit.emit(None, "store", " i64 ", function.local("new_len"), ", ptr ", function.local("old"))
    commit.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_tuple_object_layout_forward"),
        "(ptr ",
        function.local("new"),
        ", ptr ",
        function.local("old"),
        ")",
    )
    commit.emit(None, "br", " label ", function.local("done"))
    done = function.append_block("done")
    done.emit(None, "ret", " void")


def _build___xcc_aot_tuple_append(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_tuple_append")
    entry = function.append_block("entry")
    entry.emit("is_null", "icmp", " eq ptr ", function.local("tuple"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("is_null"),
        ", label ",
        function.local("allocate"),
        ", label ",
        function.local("append"),
    )
    allocate = function.append_block("allocate")
    allocate.emit("created", "call", " ptr ", module.symbol("__xcc_aot_tuple_new"), "(i64 0)")
    allocate.emit(None, "br", " label ", function.local("append"))
    append = function.append_block("append")
    append.emit(
        "handle",
        "phi",
        " ptr [ ",
        function.local("created"),
        ", ",
        function.local("allocate"),
        " ], [ ",
        function.local("tuple"),
        ", ",
        function.local("entry"),
        " ]",
    )
    append.emit("len", "load", " i64, ptr ", function.local("handle"))
    append.emit(
        "capacity",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_tuple_capacity"),
        "(ptr ",
        function.local("handle"),
        ")",
    )
    append.emit("new_len", "add", " i64 ", function.local("len"), ", 1")
    append.emit(
        "fits", "icmp", " ule i64 ", function.local("new_len"), ", ", function.local("capacity")
    )
    append.emit(
        None,
        "br",
        " i1 ",
        function.local("fits"),
        ", label ",
        function.local("store"),
        ", label ",
        function.local("grow"),
    )
    grow = function.append_block("grow")
    grow.emit("doubled", "mul", " i64 ", function.local("capacity"), ", 2")
    grow.emit("small", "icmp", " ult i64 ", function.local("doubled"), ", 4")
    grow.emit(
        "new_capacity",
        "select",
        " i1 ",
        function.local("small"),
        ", i64 4, i64 ",
        function.local("doubled"),
    )
    grow.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_tuple_register_capacity"),
        "(ptr ",
        function.local("handle"),
        ", i64 ",
        function.local("new_capacity"),
        ")",
    )
    grow.emit(None, "br", " label ", function.local("store"))
    store = function.append_block("store")
    store.emit("data_slot", "getelementptr", " ptr, ptr ", function.local("handle"), ", i64 2")
    store.emit("data", "load", " ptr, ptr ", function.local("data_slot"))
    store.emit(
        "item_slot",
        "getelementptr",
        " ptr, ptr ",
        function.local("data"),
        ", i64 ",
        function.local("len"),
    )
    store.emit(
        None, "store", " ptr ", function.local("item"), ", ptr ", function.local("item_slot")
    )
    store.emit(
        None, "store", " i64 ", function.local("new_len"), ", ptr ", function.local("handle")
    )
    store.emit(None, "ret", " ptr ", function.local("handle"))


def _build___xcc_aot_tuple_extend(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_tuple_extend")
    entry = function.append_block("entry")
    entry.emit("is_null", "icmp", " eq ptr ", function.local("tuple"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("is_null"),
        ", label ",
        function.local("allocate"),
        ", label ",
        function.local("extend"),
    )
    allocate = function.append_block("allocate")
    allocate.emit("created", "call", " ptr ", module.symbol("__xcc_aot_tuple_new"), "(i64 0)")
    allocate.emit(None, "br", " label ", function.local("extend"))
    extend = function.append_block("extend")
    extend.emit(
        "handle",
        "phi",
        " ptr [ ",
        function.local("created"),
        ", ",
        function.local("allocate"),
        " ], [ ",
        function.local("tuple"),
        ", ",
        function.local("entry"),
        " ]",
    )
    extend.emit("items_null", "icmp", " eq ptr ", function.local("items"), ", null")
    extend.emit(
        None,
        "br",
        " i1 ",
        function.local("items_null"),
        ", label ",
        function.local("done"),
        ", label ",
        function.local("measure"),
    )
    measure = function.append_block("measure")
    measure.emit("len", "load", " i64, ptr ", function.local("handle"))
    measure.emit("items_len", "load", " i64, ptr ", function.local("items"))
    measure.emit("items_empty", "icmp", " eq i64 ", function.local("items_len"), ", 0")
    measure.emit(
        None,
        "br",
        " i1 ",
        function.local("items_empty"),
        ", label ",
        function.local("done"),
        ", label ",
        function.local("grow_check"),
    )
    grow_check = function.append_block("grow_check")
    grow_check.emit(
        "new_len", "add", " i64 ", function.local("len"), ", ", function.local("items_len")
    )
    grow_check.emit(
        "capacity",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_tuple_capacity"),
        "(ptr ",
        function.local("handle"),
        ")",
    )
    grow_check.emit(
        "fits", "icmp", " ule i64 ", function.local("new_len"), ", ", function.local("capacity")
    )
    grow_check.emit(
        None,
        "br",
        " i1 ",
        function.local("fits"),
        ", label ",
        function.local("copy"),
        ", label ",
        function.local("grow"),
    )
    grow = function.append_block("grow")
    grow.emit("doubled", "mul", " i64 ", function.local("capacity"), ", 2")
    grow.emit("small", "icmp", " ult i64 ", function.local("doubled"), ", 4")
    grow.emit(
        "floor",
        "select",
        " i1 ",
        function.local("small"),
        ", i64 4, i64 ",
        function.local("doubled"),
    )
    grow.emit(
        "needs_more", "icmp", " ult i64 ", function.local("floor"), ", ", function.local("new_len")
    )
    grow.emit(
        "new_capacity",
        "select",
        " i1 ",
        function.local("needs_more"),
        ", i64 ",
        function.local("new_len"),
        ", i64 ",
        function.local("floor"),
    )
    grow.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_tuple_register_capacity"),
        "(ptr ",
        function.local("handle"),
        ", i64 ",
        function.local("new_capacity"),
        ")",
    )
    grow.emit(None, "br", " label ", function.local("copy"))
    copy = function.append_block("copy")
    copy.emit("data_slot", "getelementptr", " ptr, ptr ", function.local("handle"), ", i64 2")
    copy.emit("data", "load", " ptr, ptr ", function.local("data_slot"))
    copy.emit(
        "tail",
        "getelementptr",
        " ptr, ptr ",
        function.local("data"),
        ", i64 ",
        function.local("len"),
    )
    copy.emit("items_data_slot", "getelementptr", " ptr, ptr ", function.local("items"), ", i64 2")
    copy.emit("items_data", "load", " ptr, ptr ", function.local("items_data_slot"))
    copy.emit("copy_bytes", "mul", " i64 ", function.local("items_len"), ", 8")
    copy.emit(
        "copied",
        "call",
        " ptr ",
        module.symbol("memmove"),
        "(ptr ",
        function.local("tail"),
        ", ptr ",
        function.local("items_data"),
        ", i64 ",
        function.local("copy_bytes"),
        ")",
    )
    copy.emit(None, "store", " i64 ", function.local("new_len"), ", ptr ", function.local("handle"))
    copy.emit(None, "br", " label ", function.local("done"))
    done = function.append_block("done")
    done.emit(None, "ret", " ptr ", function.local("handle"))


def _build___xcc_aot_tuple_len(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_tuple_len")
    entry = function.append_block("entry")
    entry.emit("is_null", "icmp", " eq ptr ", function.local("tuple"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("is_null"),
        ", label ",
        function.local("null"),
        ", label ",
        function.local("value"),
    )
    null = function.append_block("null")
    null.emit(None, "ret", " i64 0")
    value = function.append_block("value")
    value.emit("len", "load", " i64, ptr ", function.local("tuple"))
    value.emit(None, "ret", " i64 ", function.local("len"))


def _build___xcc_aot_tuple_clear(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_tuple_clear")
    entry = function.append_block("entry")
    entry.emit("is_null", "icmp", " eq ptr ", function.local("tuple"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("is_null"),
        ", label ",
        function.local("allocate"),
        ", label ",
        function.local("clear"),
    )
    allocate = function.append_block("allocate")
    allocate.emit("empty", "call", " ptr ", module.symbol("__xcc_aot_tuple_new"), "(i64 0)")
    allocate.emit(None, "ret", " ptr ", function.local("empty"))
    clear = function.append_block("clear")
    clear.emit(None, "store", " i64 0, ptr ", function.local("tuple"))
    clear.emit(None, "ret", " ptr ", function.local("tuple"))


def _build___xcc_aot_tuple_get(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_tuple_get")
    entry = function.append_block("entry")
    entry.emit("is_null", "icmp", " eq ptr ", function.local("tuple"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("is_null"),
        ", label ",
        function.local("null"),
        ", label ",
        function.local("normalize"),
    )
    normalize = function.append_block("normalize")
    normalize.emit("len", "load", " i64, ptr ", function.local("tuple"))
    normalize.emit("is_negative", "icmp", " slt i64 ", function.local("index"), ", 0")
    normalize.emit("from_end", "add", " i64 ", function.local("len"), ", ", function.local("index"))
    normalize.emit(
        "normalized",
        "select",
        " i1 ",
        function.local("is_negative"),
        ", i64 ",
        function.local("from_end"),
        ", i64 ",
        function.local("index"),
    )
    normalize.emit("below_zero", "icmp", " slt i64 ", function.local("normalized"), ", 0")
    normalize.emit(
        "past_end", "icmp", " uge i64 ", function.local("normalized"), ", ", function.local("len")
    )
    normalize.emit(
        "invalid", "or", " i1 ", function.local("below_zero"), ", ", function.local("past_end")
    )
    normalize.emit(
        None,
        "br",
        " i1 ",
        function.local("invalid"),
        ", label ",
        function.local("null"),
        ", label ",
        function.local("value"),
    )
    value = function.append_block("value")
    value.emit("data_slot", "getelementptr", " ptr, ptr ", function.local("tuple"), ", i64 2")
    value.emit("data", "load", " ptr, ptr ", function.local("data_slot"))
    value.emit(
        "slot",
        "getelementptr",
        " ptr, ptr ",
        function.local("data"),
        ", i64 ",
        function.local("normalized"),
    )
    value.emit("item", "load", " ptr, ptr ", function.local("slot"))
    value.emit(None, "ret", " ptr ", function.local("item"))
    null = function.append_block("null")
    null.emit(None, "ret", " ptr null")


def _build___xcc_aot_tuple_object_layout_find(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_tuple_object_layout_find")
    entry = function.append_block("entry")
    entry.emit("is_null", "icmp", " eq ptr ", function.local("tuple"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("is_null"),
        ", label ",
        function.local("missing"),
        ", label ",
        function.local("lookup"),
    )
    lookup = function.append_block("lookup")
    lookup.emit("count_slot", "getelementptr", " i64, ptr ", function.local("tuple"), ", i64 3")
    lookup.emit("count_and_state", "load", " i64, ptr ", function.local("count_slot"))
    lookup.emit("count", "and", " i64 ", function.local("count_and_state"), ", 65535")
    lookup.emit("tags_slot", "getelementptr", " ptr, ptr ", function.local("tuple"), ", i64 4")
    lookup.emit("tags", "load", " ptr, ptr ", function.local("tags_slot"))
    lookup.emit("empty", "icmp", " eq i64 ", function.local("count"), ", 0")
    lookup.emit("tags_null", "icmp", " eq ptr ", function.local("tags"), ", null")
    lookup.emit(
        "missing_layout", "or", " i1 ", function.local("empty"), ", ", function.local("tags_null")
    )
    lookup.emit(
        None,
        "br",
        " i1 ",
        function.local("missing_layout"),
        ", label ",
        function.local("missing"),
        ", label ",
        function.local("found"),
    )
    found = function.append_block("found")
    found.emit(None, "ret", " ptr ", function.local("tuple"))
    missing = function.append_block("missing")
    missing.emit(None, "ret", " ptr null")


def _build___xcc_aot_tuple_object_layout_register(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_tuple_object_layout_register")
    entry = function.append_block("entry")
    entry.emit("tuple_null", "icmp", " eq ptr ", function.local("tuple"), ", null")
    entry.emit("tags_null", "icmp", " eq ptr ", function.local("tags"), ", null")
    entry.emit("empty", "icmp", " eq i64 ", function.local("count"), ", 0")
    entry.emit(
        "null_value", "or", " i1 ", function.local("tuple_null"), ", ", function.local("tags_null")
    )
    entry.emit("skip", "or", " i1 ", function.local("null_value"), ", ", function.local("empty"))
    entry.emit("count_too_large", "icmp", " ugt i64 ", function.local("count"), ", 65535")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("count_too_large"),
        ", label ",
        function.local("fail"),
        ", label ",
        function.local("check_skip"),
    )
    check_skip = function.append_block("check_skip")
    check_skip.emit(
        None,
        "br",
        " i1 ",
        function.local("skip"),
        ", label ",
        function.local("done"),
        ", label ",
        function.local("store"),
    )
    store = function.append_block("store")
    store.emit("count_slot", "getelementptr", " i64, ptr ", function.local("tuple"), ", i64 3")
    store.emit("old_count_and_state", "load", " i64, ptr ", function.local("count_slot"))
    store.emit("state", "and", " i64 ", function.local("old_count_and_state"), ", -65536")
    store.emit(
        "count_and_state", "or", " i64 ", function.local("state"), ", ", function.local("count")
    )
    store.emit(
        None,
        "store",
        " i64 ",
        function.local("count_and_state"),
        ", ptr ",
        function.local("count_slot"),
    )
    store.emit("tags_slot", "getelementptr", " ptr, ptr ", function.local("tuple"), ", i64 4")
    store.emit(
        None, "store", " ptr ", function.local("tags"), ", ptr ", function.local("tags_slot")
    )
    store.emit(None, "br", " label ", function.local("done"))
    fail = function.append_block("fail")
    fail.emit(None, "call", " void ", module.symbol("__xcc_aot_allocation_fail"), "()")
    fail.emit(None, "unreachable")
    done = function.append_block("done")
    done.emit(None, "ret", " void")


def _build___xcc_aot_tuple_object_layout_forward(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_tuple_object_layout_forward")
    entry = function.append_block("entry")
    entry.emit("old_null", "icmp", " eq ptr ", function.local("old"), ", null")
    entry.emit("new_null", "icmp", " eq ptr ", function.local("new"), ", null")
    entry.emit(
        "null_value", "or", " i1 ", function.local("old_null"), ", ", function.local("new_null")
    )
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("null_value"),
        ", label ",
        function.local("done"),
        ", label ",
        function.local("copy"),
    )
    copy = function.append_block("copy")
    copy.emit("old_count_slot", "getelementptr", " i64, ptr ", function.local("old"), ", i64 3")
    copy.emit("count", "load", " i64, ptr ", function.local("old_count_slot"))
    copy.emit("old_tags_slot", "getelementptr", " ptr, ptr ", function.local("old"), ", i64 4")
    copy.emit("tags", "load", " ptr, ptr ", function.local("old_tags_slot"))
    copy.emit("new_count_slot", "getelementptr", " i64, ptr ", function.local("new"), ", i64 3")
    copy.emit(
        None, "store", " i64 ", function.local("count"), ", ptr ", function.local("new_count_slot")
    )
    copy.emit("new_tags_slot", "getelementptr", " ptr, ptr ", function.local("new"), ", i64 4")
    copy.emit(
        None, "store", " ptr ", function.local("tags"), ", ptr ", function.local("new_tags_slot")
    )
    copy.emit(None, "br", " label ", function.local("done"))
    done = function.append_block("done")
    done.emit(None, "ret", " void")


def _build___xcc_aot_tuple_get_object(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_tuple_get_object")
    entry = function.append_block("entry")
    entry.emit(
        "raw",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_get"),
        "(ptr ",
        function.local("tuple"),
        ", i64 ",
        function.local("index"),
        ")",
    )
    entry.emit("raw_null", "icmp", " eq ptr ", function.local("raw"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("raw_null"),
        ", label ",
        function.local("return_raw"),
        ", label ",
        function.local("lookup"),
    )
    lookup = function.append_block("lookup")
    lookup.emit(
        "layout",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_object_layout_find"),
        "(ptr ",
        function.local("tuple"),
        ")",
    )
    lookup.emit("layout_missing", "icmp", " eq ptr ", function.local("layout"), ", null")
    lookup.emit(
        None,
        "br",
        " i1 ",
        function.local("layout_missing"),
        ", label ",
        function.local("return_raw"),
        ", label ",
        function.local("select_tag"),
    )
    select_tag = function.append_block("select_tag")
    select_tag.emit(
        "count_slot", "getelementptr", " i64, ptr ", function.local("layout"), ", i64 3"
    )
    select_tag.emit("count_and_state", "load", " i64, ptr ", function.local("count_slot"))
    select_tag.emit("count", "and", " i64 ", function.local("count_and_state"), ", 65535")
    select_tag.emit("tags_slot", "getelementptr", " ptr, ptr ", function.local("layout"), ", i64 4")
    select_tag.emit("tags", "load", " ptr, ptr ", function.local("tags_slot"))
    select_tag.emit("homogeneous", "icmp", " eq i64 ", function.local("count"), ", 1")
    select_tag.emit(
        "len",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_tuple_len"),
        "(ptr ",
        function.local("tuple"),
        ")",
    )
    select_tag.emit("negative", "icmp", " slt i64 ", function.local("index"), ", 0")
    select_tag.emit(
        "from_end", "add", " i64 ", function.local("len"), ", ", function.local("index")
    )
    select_tag.emit(
        "normalized",
        "select",
        " i1 ",
        function.local("negative"),
        ", i64 ",
        function.local("from_end"),
        ", i64 ",
        function.local("index"),
    )
    select_tag.emit(
        "tag_index",
        "select",
        " i1 ",
        function.local("homogeneous"),
        ", i64 0, i64 ",
        function.local("normalized"),
    )
    select_tag.emit(
        "in_layout", "icmp", " ult i64 ", function.local("tag_index"), ", ", function.local("count")
    )
    select_tag.emit(
        None,
        "br",
        " i1 ",
        function.local("in_layout"),
        ", label ",
        function.local("load_tag"),
        ", label ",
        function.local("return_raw"),
    )
    load_tag = function.append_block("load_tag")
    load_tag.emit(
        "tag_slot",
        "getelementptr",
        " i64, ptr ",
        function.local("tags"),
        ", i64 ",
        function.local("tag_index"),
    )
    load_tag.emit("tag", "load", " i64, ptr ", function.local("tag_slot"))
    load_tag.emit("already_boxed", "icmp", " eq i64 ", function.local("tag"), ", 0")
    load_tag.emit(
        None,
        "br",
        " i1 ",
        function.local("already_boxed"),
        ", label ",
        function.local("return_raw"),
        ", label ",
        function.local("box"),
    )
    box = function.append_block("box")
    box.emit("boxed", "call", " ptr ", module.symbol("malloc"), "(i64 16)")
    box.emit(None, "store", " i64 ", function.local("tag"), ", ptr ", function.local("boxed"))
    box.emit("payload", "getelementptr", " i8, ptr ", function.local("boxed"), ", i64 8")
    box.emit(
        None, "switch", " i64 ", function.local("tag"), ", label ", function.local("pointer"), " ["
    )
    box.continue_("  i64 1, label ", function.local("integer"))
    box.continue_("  i64 2, label ", function.local("integer"))
    box.continue_("  i64 3, label ", function.local("float"))
    box.continue_("]")
    integer = function.append_block("integer")
    integer.emit("integer_value", "ptrtoint", " ptr ", function.local("raw"), " to i64")
    integer.emit(
        None, "store", " i64 ", function.local("integer_value"), ", ptr ", function.local("payload")
    )
    integer.emit(None, "br", " label ", function.local("done"))
    float = function.append_block("float")
    float.emit("float_value", "load", " double, ptr ", function.local("raw"))
    float.emit(
        None,
        "store",
        " double ",
        function.local("float_value"),
        ", ptr ",
        function.local("payload"),
    )
    float.emit(None, "br", " label ", function.local("done"))
    pointer = function.append_block("pointer")
    pointer.emit(None, "store", " ptr ", function.local("raw"), ", ptr ", function.local("payload"))
    pointer.emit(None, "br", " label ", function.local("done"))
    done = function.append_block("done")
    done.emit(None, "ret", " ptr ", function.local("boxed"))
    return_raw = function.append_block("return_raw")
    return_raw.emit(None, "ret", " ptr ", function.local("raw"))


def _build___xcc_aot_tuple_set(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_tuple_set")
    entry = function.append_block("entry")
    entry.emit("is_null", "icmp", " eq ptr ", function.local("tuple"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("is_null"),
        ", label ",
        function.local("done"),
        ", label ",
        function.local("normalize"),
    )
    normalize = function.append_block("normalize")
    normalize.emit("len", "load", " i64, ptr ", function.local("tuple"))
    normalize.emit("is_negative", "icmp", " slt i64 ", function.local("index"), ", 0")
    normalize.emit("from_end", "add", " i64 ", function.local("len"), ", ", function.local("index"))
    normalize.emit(
        "normalized",
        "select",
        " i1 ",
        function.local("is_negative"),
        ", i64 ",
        function.local("from_end"),
        ", i64 ",
        function.local("index"),
    )
    normalize.emit("below_zero", "icmp", " slt i64 ", function.local("normalized"), ", 0")
    normalize.emit(
        "past_end", "icmp", " uge i64 ", function.local("normalized"), ", ", function.local("len")
    )
    normalize.emit(
        "invalid", "or", " i1 ", function.local("below_zero"), ", ", function.local("past_end")
    )
    normalize.emit(
        None,
        "br",
        " i1 ",
        function.local("invalid"),
        ", label ",
        function.local("done"),
        ", label ",
        function.local("value"),
    )
    value = function.append_block("value")
    value.emit("data_slot", "getelementptr", " ptr, ptr ", function.local("tuple"), ", i64 2")
    value.emit("data", "load", " ptr, ptr ", function.local("data_slot"))
    value.emit(
        "slot",
        "getelementptr",
        " ptr, ptr ",
        function.local("data"),
        ", i64 ",
        function.local("normalized"),
    )
    value.emit(None, "store", " ptr ", function.local("item"), ", ptr ", function.local("slot"))
    value.emit(None, "br", " label ", function.local("done"))
    done = function.append_block("done")
    done.emit(None, "ret", " void")


def _build___xcc_aot_tuple_slice(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_tuple_slice")
    entry = function.append_block("entry")
    entry.emit(
        "len",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_tuple_len"),
        "(ptr ",
        function.local("tuple"),
        ")",
    )
    entry.emit(
        "raw_start",
        "select",
        " i1 ",
        function.local("has_start"),
        ", i64 ",
        function.local("start"),
        ", i64 0",
    )
    entry.emit("start_negative", "icmp", " slt i64 ", function.local("raw_start"), ", 0")
    entry.emit(
        "start_from_end", "add", " i64 ", function.local("len"), ", ", function.local("raw_start")
    )
    entry.emit(
        "start_unclamped",
        "select",
        " i1 ",
        function.local("start_negative"),
        ", i64 ",
        function.local("start_from_end"),
        ", i64 ",
        function.local("raw_start"),
    )
    entry.emit("start_below_zero", "icmp", " slt i64 ", function.local("start_unclamped"), ", 0")
    entry.emit(
        "start_at_least_zero",
        "select",
        " i1 ",
        function.local("start_below_zero"),
        ", i64 0, i64 ",
        function.local("start_unclamped"),
    )
    entry.emit(
        "start_too_large",
        "icmp",
        " sgt i64 ",
        function.local("start_at_least_zero"),
        ", ",
        function.local("len"),
    )
    entry.emit(
        "clamped_start",
        "select",
        " i1 ",
        function.local("start_too_large"),
        ", i64 ",
        function.local("len"),
        ", i64 ",
        function.local("start_at_least_zero"),
    )
    entry.emit(
        "raw_stop",
        "select",
        " i1 ",
        function.local("has_stop"),
        ", i64 ",
        function.local("stop"),
        ", i64 ",
        function.local("len"),
    )
    entry.emit("stop_negative", "icmp", " slt i64 ", function.local("raw_stop"), ", 0")
    entry.emit(
        "stop_from_end", "add", " i64 ", function.local("len"), ", ", function.local("raw_stop")
    )
    entry.emit(
        "stop_unclamped",
        "select",
        " i1 ",
        function.local("stop_negative"),
        ", i64 ",
        function.local("stop_from_end"),
        ", i64 ",
        function.local("raw_stop"),
    )
    entry.emit("stop_below_zero", "icmp", " slt i64 ", function.local("stop_unclamped"), ", 0")
    entry.emit(
        "stop_at_least_zero",
        "select",
        " i1 ",
        function.local("stop_below_zero"),
        ", i64 0, i64 ",
        function.local("stop_unclamped"),
    )
    entry.emit(
        "stop_too_large",
        "icmp",
        " sgt i64 ",
        function.local("stop_at_least_zero"),
        ", ",
        function.local("len"),
    )
    entry.emit(
        "clamped_stop",
        "select",
        " i1 ",
        function.local("stop_too_large"),
        ", i64 ",
        function.local("len"),
        ", i64 ",
        function.local("stop_at_least_zero"),
    )
    entry.emit(
        "stop_before_start",
        "icmp",
        " slt i64 ",
        function.local("clamped_stop"),
        ", ",
        function.local("clamped_start"),
    )
    entry.emit(
        "actual_stop",
        "select",
        " i1 ",
        function.local("stop_before_start"),
        ", i64 ",
        function.local("clamped_start"),
        ", i64 ",
        function.local("clamped_stop"),
    )
    entry.emit(
        "out_len",
        "sub",
        " i64 ",
        function.local("actual_stop"),
        ", ",
        function.local("clamped_start"),
    )
    entry.emit(
        "out",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_new"),
        "(i64 ",
        function.local("out_len"),
        ")",
    )
    entry.emit("index_ptr", "alloca", " i64")
    entry.emit(None, "store", " i64 0, ptr ", function.local("index_ptr"))
    entry.emit(None, "br", " label ", function.local("slice_cond"))
    slice_cond = function.append_block("slice_cond")
    slice_cond.emit("index", "load", " i64, ptr ", function.local("index_ptr"))
    slice_cond.emit(
        "done", "icmp", " uge i64 ", function.local("index"), ", ", function.local("out_len")
    )
    slice_cond.emit(
        None,
        "br",
        " i1 ",
        function.local("done"),
        ", label ",
        function.local("slice_done"),
        ", label ",
        function.local("slice_body"),
    )
    slice_body = function.append_block("slice_body")
    slice_body.emit(
        "source_index",
        "add",
        " i64 ",
        function.local("clamped_start"),
        ", ",
        function.local("index"),
    )
    slice_body.emit(
        "item",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_get"),
        "(ptr ",
        function.local("tuple"),
        ", i64 ",
        function.local("source_index"),
        ")",
    )
    slice_body.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_tuple_set"),
        "(ptr ",
        function.local("out"),
        ", i64 ",
        function.local("index"),
        ", ptr ",
        function.local("item"),
        ")",
    )
    slice_body.emit("next", "add", " i64 ", function.local("index"), ", 1")
    slice_body.emit(
        None, "store", " i64 ", function.local("next"), ", ptr ", function.local("index_ptr")
    )
    slice_body.emit(None, "br", " label ", function.local("slice_cond"))
    slice_done = function.append_block("slice_done")
    slice_done.emit(None, "ret", " ptr ", function.local("out"))


def _build___xcc_aot_string_dict_hash(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_string_dict_hash")
    entry = function.append_block("entry")
    entry.emit("is_null", "icmp", " eq ptr ", function.local("key"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("is_null"),
        ", label ",
        function.local("null"),
        ", label ",
        function.local("loop"),
    )
    loop = function.append_block("loop")
    loop.emit(
        "index",
        "phi",
        " i64 [ 0, ",
        function.local("entry"),
        " ], [ ",
        function.local("next_index"),
        ", ",
        function.local("body"),
        " ]",
    )
    loop.emit(
        "hash",
        "phi",
        " i64 [ -3750763034362895579, ",
        function.local("entry"),
        " ], [ ",
        function.local("next_hash"),
        ", ",
        function.local("body"),
        " ]",
    )
    loop.emit(
        "byte_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("key"),
        ", i64 ",
        function.local("index"),
    )
    loop.emit("byte", "load", " i8, ptr ", function.local("byte_ptr"))
    loop.emit("done", "icmp", " eq i8 ", function.local("byte"), ", 0")
    loop.emit(
        None,
        "br",
        " i1 ",
        function.local("done"),
        ", label ",
        function.local("finish"),
        ", label ",
        function.local("body"),
    )
    body = function.append_block("body")
    body.emit("wide", "zext", " i8 ", function.local("byte"), " to i64")
    body.emit("mixed", "xor", " i64 ", function.local("hash"), ", ", function.local("wide"))
    body.emit("next_hash", "mul", " i64 ", function.local("mixed"), ", 1099511628211")
    body.emit("next_index", "add", " i64 ", function.local("index"), ", 1")
    body.emit(None, "br", " label ", function.local("loop"))
    finish = function.append_block("finish")
    finish.emit(None, "ret", " i64 ", function.local("hash"))
    null = function.append_block("null")
    null.emit(None, "ret", " i64 0")


def _build___xcc_aot_dict_bump_state(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_dict_bump_state")
    entry = function.append_block("entry")
    entry.emit("is_null", "icmp", " eq ptr ", function.local("dict"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("is_null"),
        ", label ",
        function.local("done"),
        ", label ",
        function.local("advance"),
    )
    advance = function.append_block("advance")
    advance.emit("current", "load", " i64, ptr ", module.symbol("__xcc_aot_dict_state_counter"))
    advance.emit("next", "add", " i64 ", function.local("current"), ", 1")
    advance.emit("wrapped", "icmp", " eq i64 ", function.local("next"), ", 0")
    advance.emit("too_large", "icmp", " ugt i64 ", function.local("next"), ", 281474976710655")
    advance.emit(
        "invalid", "or", " i1 ", function.local("wrapped"), ", ", function.local("too_large")
    )
    advance.emit(
        None,
        "br",
        " i1 ",
        function.local("invalid"),
        ", label ",
        function.local("fail"),
        ", label ",
        function.local("store"),
    )
    store = function.append_block("store")
    store.emit(
        None,
        "store",
        " i64 ",
        function.local("next"),
        ", ptr ",
        module.symbol("__xcc_aot_dict_state_counter"),
    )
    store.emit("count_slot", "getelementptr", " i64, ptr ", function.local("dict"), ", i64 3")
    store.emit("old_count_and_state", "load", " i64, ptr ", function.local("count_slot"))
    store.emit("count", "and", " i64 ", function.local("old_count_and_state"), ", 65535")
    store.emit("state_bits", "shl", " i64 ", function.local("next"), ", 16")
    store.emit(
        "count_and_state",
        "or",
        " i64 ",
        function.local("state_bits"),
        ", ",
        function.local("count"),
    )
    store.emit(
        None,
        "store",
        " i64 ",
        function.local("count_and_state"),
        ", ptr ",
        function.local("count_slot"),
    )
    store.emit(None, "br", " label ", function.local("done"))
    fail = function.append_block("fail")
    fail.emit(None, "call", " void ", module.symbol("__xcc_aot_allocation_fail"), "()")
    fail.emit(None, "unreachable")
    done = function.append_block("done")
    done.emit(None, "ret", " void")


def _build___xcc_aot_dict_state(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_dict_state")
    entry = function.append_block("entry")
    entry.emit("is_null", "icmp", " eq ptr ", function.local("dict"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("is_null"),
        ", label ",
        function.local("null"),
        ", label ",
        function.local("load"),
    )
    load = function.append_block("load")
    load.emit("count_slot", "getelementptr", " i64, ptr ", function.local("dict"), ", i64 3")
    load.emit("count_and_state", "load", " i64, ptr ", function.local("count_slot"))
    load.emit("state", "lshr", " i64 ", function.local("count_and_state"), ", 16")
    load.emit("uninitialized", "icmp", " eq i64 ", function.local("state"), ", 0")
    load.emit(
        None,
        "br",
        " i1 ",
        function.local("uninitialized"),
        ", label ",
        function.local("initialize"),
        ", label ",
        function.local("done"),
    )
    initialize = function.append_block("initialize")
    initialize.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_dict_bump_state"),
        "(ptr ",
        function.local("dict"),
        ")",
    )
    initialize.emit(
        "initialized_count_and_state", "load", " i64, ptr ", function.local("count_slot")
    )
    initialize.emit(
        "initialized_state", "lshr", " i64 ", function.local("initialized_count_and_state"), ", 16"
    )
    initialize.emit(None, "ret", " i64 ", function.local("initialized_state"))
    done = function.append_block("done")
    done.emit(None, "ret", " i64 ", function.local("state"))
    null = function.append_block("null")
    null.emit(None, "ret", " i64 0")


def _build___xcc_aot_string_dict_cache_bucket(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_string_dict_cache_bucket")
    entry = function.append_block("entry")
    entry.emit("dict_key", "ptrtoint", " ptr ", function.local("dict"), " to i64")
    entry.emit("dict_aligned", "lshr", " i64 ", function.local("dict_key"), ", 4")
    entry.emit(
        "mixed", "xor", " i64 ", function.local("hash"), ", ", function.local("dict_aligned")
    )
    entry.emit("high", "lshr", " i64 ", function.local("mixed"), ", 32")
    entry.emit("folded", "xor", " i64 ", function.local("mixed"), ", ", function.local("high"))
    entry.emit("bucket", "and", " i64 ", function.local("folded"), ", 16383")
    entry.emit(None, "ret", " i64 ", function.local("bucket"))


def _build___xcc_aot_string_dict_cache_store(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_string_dict_cache_store")
    entry = function.append_block("entry")
    entry.emit(
        "bucket",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_string_dict_cache_bucket"),
        "(ptr ",
        function.local("dict"),
        ", i64 ",
        function.local("hash"),
        ")",
    )
    entry.emit(
        "dict_slot",
        "getelementptr",
        " [16384 x ptr], ptr ",
        module.symbol("__xcc_aot_string_dict_cache_dicts"),
        ", i64 0, i64 ",
        function.local("bucket"),
    )
    entry.emit(
        "key_slot",
        "getelementptr",
        " [16384 x ptr], ptr ",
        module.symbol("__xcc_aot_string_dict_cache_keys"),
        ", i64 0, i64 ",
        function.local("bucket"),
    )
    entry.emit(
        "hash_slot",
        "getelementptr",
        " [16384 x i64], ptr ",
        module.symbol("__xcc_aot_string_dict_cache_hashes"),
        ", i64 0, i64 ",
        function.local("bucket"),
    )
    entry.emit(
        "state_slot",
        "getelementptr",
        " [16384 x i64], ptr ",
        module.symbol("__xcc_aot_string_dict_cache_states"),
        ", i64 0, i64 ",
        function.local("bucket"),
    )
    entry.emit(
        "index_slot",
        "getelementptr",
        " [16384 x i64], ptr ",
        module.symbol("__xcc_aot_string_dict_cache_indices"),
        ", i64 0, i64 ",
        function.local("bucket"),
    )
    entry.emit("old_key", "load", " ptr, ptr ", function.local("key_slot"))
    entry.emit(
        "key_len", "call", " i64 ", module.symbol("strlen"), "(ptr ", function.local("key"), ")"
    )
    entry.emit("key_size", "add", " i64 ", function.local("key_len"), ", 1")
    entry.emit("wrapped", "icmp", " eq i64 ", function.local("key_size"), ", 0")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("wrapped"),
        ", label ",
        function.local("fail"),
        ", label ",
        function.local("copy"),
    )
    copy = function.append_block("copy")
    copy.emit(
        "cached_key",
        "call",
        " ptr ",
        module.symbol("realloc"),
        "(ptr ",
        function.local("old_key"),
        ", i64 ",
        function.local("key_size"),
        ")",
    )
    copy.emit("allocation_failed", "icmp", " eq ptr ", function.local("cached_key"), ", null")
    copy.emit(
        None,
        "br",
        " i1 ",
        function.local("allocation_failed"),
        ", label ",
        function.local("fail"),
        ", label ",
        function.local("commit"),
    )
    commit = function.append_block("commit")
    commit.emit(
        "copied",
        "call",
        " ptr ",
        module.symbol("memcpy"),
        "(ptr ",
        function.local("cached_key"),
        ", ptr ",
        function.local("key"),
        ", i64 ",
        function.local("key_size"),
        ")",
    )
    commit.emit(
        None, "store", " ptr ", function.local("dict"), ", ptr ", function.local("dict_slot")
    )
    commit.emit(
        None, "store", " ptr ", function.local("cached_key"), ", ptr ", function.local("key_slot")
    )
    commit.emit(
        None, "store", " i64 ", function.local("hash"), ", ptr ", function.local("hash_slot")
    )
    commit.emit(
        None, "store", " i64 ", function.local("state"), ", ptr ", function.local("state_slot")
    )
    commit.emit(
        None, "store", " i64 ", function.local("index"), ", ptr ", function.local("index_slot")
    )
    commit.emit(None, "ret", " void")
    fail = function.append_block("fail")
    fail.emit(None, "call", " void ", module.symbol("__xcc_aot_allocation_fail"), "()")
    fail.emit(None, "unreachable")


def _build___xcc_aot_string_dict_find_index(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_string_dict_find_index")
    entry = function.append_block("entry")
    entry.emit("dict_null", "icmp", " eq ptr ", function.local("dict"), ", null")
    entry.emit("key_null", "icmp", " eq ptr ", function.local("key"), ", null")
    entry.emit(
        "invalid", "or", " i1 ", function.local("dict_null"), ", ", function.local("key_null")
    )
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("invalid"),
        ", label ",
        function.local("uncached_missing"),
        ", label ",
        function.local("prepare"),
    )
    prepare = function.append_block("prepare")
    prepare.emit(
        "hash",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_string_dict_hash"),
        "(ptr ",
        function.local("key"),
        ")",
    )
    prepare.emit(
        "state",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_dict_state"),
        "(ptr ",
        function.local("dict"),
        ")",
    )
    prepare.emit(
        "bucket",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_string_dict_cache_bucket"),
        "(ptr ",
        function.local("dict"),
        ", i64 ",
        function.local("hash"),
        ")",
    )
    prepare.emit(
        "dict_slot",
        "getelementptr",
        " [16384 x ptr], ptr ",
        module.symbol("__xcc_aot_string_dict_cache_dicts"),
        ", i64 0, i64 ",
        function.local("bucket"),
    )
    prepare.emit(
        "key_slot",
        "getelementptr",
        " [16384 x ptr], ptr ",
        module.symbol("__xcc_aot_string_dict_cache_keys"),
        ", i64 0, i64 ",
        function.local("bucket"),
    )
    prepare.emit(
        "hash_slot",
        "getelementptr",
        " [16384 x i64], ptr ",
        module.symbol("__xcc_aot_string_dict_cache_hashes"),
        ", i64 0, i64 ",
        function.local("bucket"),
    )
    prepare.emit(
        "state_slot",
        "getelementptr",
        " [16384 x i64], ptr ",
        module.symbol("__xcc_aot_string_dict_cache_states"),
        ", i64 0, i64 ",
        function.local("bucket"),
    )
    prepare.emit(
        "index_slot",
        "getelementptr",
        " [16384 x i64], ptr ",
        module.symbol("__xcc_aot_string_dict_cache_indices"),
        ", i64 0, i64 ",
        function.local("bucket"),
    )
    prepare.emit("cached_dict", "load", " ptr, ptr ", function.local("dict_slot"))
    prepare.emit("cached_key", "load", " ptr, ptr ", function.local("key_slot"))
    prepare.emit("cached_hash", "load", " i64, ptr ", function.local("hash_slot"))
    prepare.emit(
        "same_dict", "icmp", " eq ptr ", function.local("cached_dict"), ", ", function.local("dict")
    )
    prepare.emit("has_key", "icmp", " ne ptr ", function.local("cached_key"), ", null")
    prepare.emit(
        "same_hash", "icmp", " eq i64 ", function.local("cached_hash"), ", ", function.local("hash")
    )
    prepare.emit(
        "same_dict_and_key",
        "and",
        " i1 ",
        function.local("same_dict"),
        ", ",
        function.local("has_key"),
    )
    prepare.emit(
        "possible_hit",
        "and",
        " i1 ",
        function.local("same_dict_and_key"),
        ", ",
        function.local("same_hash"),
    )
    prepare.emit(
        None,
        "br",
        " i1 ",
        function.local("possible_hit"),
        ", label ",
        function.local("compare_cached_key"),
        ", label ",
        function.local("search"),
    )
    compare_cached_key = function.append_block("compare_cached_key")
    compare_cached_key.emit(
        "cached_key_cmp",
        "call",
        " i32 ",
        module.symbol("strcmp"),
        "(ptr ",
        function.local("cached_key"),
        ", ptr ",
        function.local("key"),
        ")",
    )
    compare_cached_key.emit("same_key", "icmp", " eq i32 ", function.local("cached_key_cmp"), ", 0")
    compare_cached_key.emit(
        None,
        "br",
        " i1 ",
        function.local("same_key"),
        ", label ",
        function.local("inspect_cached"),
        ", label ",
        function.local("search"),
    )
    inspect_cached = function.append_block("inspect_cached")
    inspect_cached.emit("cached_state", "load", " i64, ptr ", function.local("state_slot"))
    inspect_cached.emit("cached_index", "load", " i64, ptr ", function.local("index_slot"))
    inspect_cached.emit(
        "same_state",
        "icmp",
        " eq i64 ",
        function.local("cached_state"),
        ", ",
        function.local("state"),
    )
    inspect_cached.emit(
        "cached_missing", "icmp", " slt i64 ", function.local("cached_index"), ", 0"
    )
    inspect_cached.emit(
        "valid_missing",
        "and",
        " i1 ",
        function.local("same_state"),
        ", ",
        function.local("cached_missing"),
    )
    inspect_cached.emit(
        None,
        "br",
        " i1 ",
        function.local("valid_missing"),
        ", label ",
        function.local("return_cached"),
        ", label ",
        function.local("check_cached_index"),
    )
    check_cached_index = function.append_block("check_cached_index")
    check_cached_index.emit(
        "cached_nonnegative", "icmp", " sge i64 ", function.local("cached_index"), ", 0"
    )
    check_cached_index.emit(
        None,
        "br",
        " i1 ",
        function.local("cached_nonnegative"),
        ", label ",
        function.local("validate_cached"),
        ", label ",
        function.local("search"),
    )
    validate_cached = function.append_block("validate_cached")
    validate_cached.emit(
        "cached_len",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_tuple_len"),
        "(ptr ",
        function.local("dict"),
        ")",
    )
    validate_cached.emit(
        "cached_in_range",
        "icmp",
        " ult i64 ",
        function.local("cached_index"),
        ", ",
        function.local("cached_len"),
    )
    validate_cached.emit(
        None,
        "br",
        " i1 ",
        function.local("cached_in_range"),
        ", label ",
        function.local("load_cached"),
        ", label ",
        function.local("search"),
    )
    load_cached = function.append_block("load_cached")
    load_cached.emit(
        "cached_pair",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_get"),
        "(ptr ",
        function.local("dict"),
        ", i64 ",
        function.local("cached_index"),
        ")",
    )
    load_cached.emit(
        "cached_candidate",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_get"),
        "(ptr ",
        function.local("cached_pair"),
        ", i64 0)",
    )
    load_cached.emit(
        "candidate_exists", "icmp", " ne ptr ", function.local("cached_candidate"), ", null"
    )
    load_cached.emit(
        None,
        "br",
        " i1 ",
        function.local("candidate_exists"),
        ", label ",
        function.local("compare_cached_candidate"),
        ", label ",
        function.local("search"),
    )
    compare_cached_candidate = function.append_block("compare_cached_candidate")
    compare_cached_candidate.emit(
        "cached_candidate_cmp",
        "call",
        " i32 ",
        module.symbol("strcmp"),
        "(ptr ",
        function.local("cached_candidate"),
        ", ptr ",
        function.local("key"),
        ")",
    )
    compare_cached_candidate.emit(
        "cached_candidate_matches",
        "icmp",
        " eq i32 ",
        function.local("cached_candidate_cmp"),
        ", 0",
    )
    compare_cached_candidate.emit(
        None,
        "br",
        " i1 ",
        function.local("cached_candidate_matches"),
        ", label ",
        function.local("refresh_cached"),
        ", label ",
        function.local("search"),
    )
    refresh_cached = function.append_block("refresh_cached")
    refresh_cached.emit(
        None, "store", " i64 ", function.local("state"), ", ptr ", function.local("state_slot")
    )
    refresh_cached.emit(None, "br", " label ", function.local("return_cached"))
    return_cached = function.append_block("return_cached")
    return_cached.emit(None, "ret", " i64 ", function.local("cached_index"))
    search = function.append_block("search")
    search.emit(None, "br", " label ", function.local("search_cond"))
    search_cond = function.append_block("search_cond")
    search_cond.emit(
        "search_index",
        "phi",
        " i64 [ 0, ",
        function.local("search"),
        " ], [ ",
        function.local("next_index"),
        ", ",
        function.local("search_next"),
        " ]",
    )
    search_cond.emit(
        "length",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_tuple_len"),
        "(ptr ",
        function.local("dict"),
        ")",
    )
    search_cond.emit(
        "done", "icmp", " uge i64 ", function.local("search_index"), ", ", function.local("length")
    )
    search_cond.emit(
        None,
        "br",
        " i1 ",
        function.local("done"),
        ", label ",
        function.local("missing"),
        ", label ",
        function.local("search_body"),
    )
    search_body = function.append_block("search_body")
    search_body.emit(
        "pair",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_get"),
        "(ptr ",
        function.local("dict"),
        ", i64 ",
        function.local("search_index"),
        ")",
    )
    search_body.emit(
        "candidate",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_get"),
        "(ptr ",
        function.local("pair"),
        ", i64 0)",
    )
    search_body.emit("candidate_null", "icmp", " eq ptr ", function.local("candidate"), ", null")
    search_body.emit(
        None,
        "br",
        " i1 ",
        function.local("candidate_null"),
        ", label ",
        function.local("search_next"),
        ", label ",
        function.local("compare_candidate"),
    )
    compare_candidate = function.append_block("compare_candidate")
    compare_candidate.emit(
        "candidate_cmp",
        "call",
        " i32 ",
        module.symbol("strcmp"),
        "(ptr ",
        function.local("candidate"),
        ", ptr ",
        function.local("key"),
        ")",
    )
    compare_candidate.emit("matches", "icmp", " eq i32 ", function.local("candidate_cmp"), ", 0")
    compare_candidate.emit(
        None,
        "br",
        " i1 ",
        function.local("matches"),
        ", label ",
        function.local("found"),
        ", label ",
        function.local("search_next"),
    )
    search_next = function.append_block("search_next")
    search_next.emit("next_index", "add", " i64 ", function.local("search_index"), ", 1")
    search_next.emit(None, "br", " label ", function.local("search_cond"))
    found = function.append_block("found")
    found.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_string_dict_cache_store"),
        "(ptr ",
        function.local("dict"),
        ", ptr ",
        function.local("key"),
        ", i64 ",
        function.local("hash"),
        ", i64 ",
        function.local("state"),
        ", i64 ",
        function.local("search_index"),
        ")",
    )
    found.emit(None, "ret", " i64 ", function.local("search_index"))
    missing = function.append_block("missing")
    missing.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_string_dict_cache_store"),
        "(ptr ",
        function.local("dict"),
        ", ptr ",
        function.local("key"),
        ", i64 ",
        function.local("hash"),
        ", i64 ",
        function.local("state"),
        ", i64 -1)",
    )
    missing.emit(None, "ret", " i64 -1")
    uncached_missing = function.append_block("uncached_missing")
    uncached_missing.emit(None, "ret", " i64 -1")


def _build___xcc_aot_string_dict_note_index(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_string_dict_note_index")
    entry = function.append_block("entry")
    entry.emit("dict_null", "icmp", " eq ptr ", function.local("dict"), ", null")
    entry.emit("key_null", "icmp", " eq ptr ", function.local("key"), ", null")
    entry.emit(
        "invalid", "or", " i1 ", function.local("dict_null"), ", ", function.local("key_null")
    )
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("invalid"),
        ", label ",
        function.local("done"),
        ", label ",
        function.local("store"),
    )
    store = function.append_block("store")
    store.emit(
        "hash",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_string_dict_hash"),
        "(ptr ",
        function.local("key"),
        ")",
    )
    store.emit(
        "state",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_dict_state"),
        "(ptr ",
        function.local("dict"),
        ")",
    )
    store.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_string_dict_cache_store"),
        "(ptr ",
        function.local("dict"),
        ", ptr ",
        function.local("key"),
        ", i64 ",
        function.local("hash"),
        ", i64 ",
        function.local("state"),
        ", i64 ",
        function.local("index"),
        ")",
    )
    store.emit(None, "br", " label ", function.local("done"))
    done = function.append_block("done")
    done.emit(None, "ret", " void")


def _build___xcc_aot_string_tuple_find_index(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_string_tuple_find_index")
    entry = function.append_block("entry")
    entry.emit("tuple_null", "icmp", " eq ptr ", function.local("tuple"), ", null")
    entry.emit("key_null", "icmp", " eq ptr ", function.local("key"), ", null")
    entry.emit(
        "invalid", "or", " i1 ", function.local("tuple_null"), ", ", function.local("key_null")
    )
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("invalid"),
        ", label ",
        function.local("uncached_missing"),
        ", label ",
        function.local("prepare"),
    )
    prepare = function.append_block("prepare")
    prepare.emit(
        "hash",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_string_dict_hash"),
        "(ptr ",
        function.local("key"),
        ")",
    )
    prepare.emit(
        "state",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_dict_state"),
        "(ptr ",
        function.local("tuple"),
        ")",
    )
    prepare.emit(
        "bucket",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_string_dict_cache_bucket"),
        "(ptr ",
        function.local("tuple"),
        ", i64 ",
        function.local("hash"),
        ")",
    )
    prepare.emit(
        "dict_slot",
        "getelementptr",
        " [16384 x ptr], ptr ",
        module.symbol("__xcc_aot_string_dict_cache_dicts"),
        ", i64 0, i64 ",
        function.local("bucket"),
    )
    prepare.emit(
        "key_slot",
        "getelementptr",
        " [16384 x ptr], ptr ",
        module.symbol("__xcc_aot_string_dict_cache_keys"),
        ", i64 0, i64 ",
        function.local("bucket"),
    )
    prepare.emit(
        "hash_slot",
        "getelementptr",
        " [16384 x i64], ptr ",
        module.symbol("__xcc_aot_string_dict_cache_hashes"),
        ", i64 0, i64 ",
        function.local("bucket"),
    )
    prepare.emit(
        "state_slot",
        "getelementptr",
        " [16384 x i64], ptr ",
        module.symbol("__xcc_aot_string_dict_cache_states"),
        ", i64 0, i64 ",
        function.local("bucket"),
    )
    prepare.emit(
        "index_slot",
        "getelementptr",
        " [16384 x i64], ptr ",
        module.symbol("__xcc_aot_string_dict_cache_indices"),
        ", i64 0, i64 ",
        function.local("bucket"),
    )
    prepare.emit("cached_tuple", "load", " ptr, ptr ", function.local("dict_slot"))
    prepare.emit("cached_key", "load", " ptr, ptr ", function.local("key_slot"))
    prepare.emit("cached_hash", "load", " i64, ptr ", function.local("hash_slot"))
    prepare.emit(
        "same_tuple",
        "icmp",
        " eq ptr ",
        function.local("cached_tuple"),
        ", ",
        function.local("tuple"),
    )
    prepare.emit("has_key", "icmp", " ne ptr ", function.local("cached_key"), ", null")
    prepare.emit(
        "same_hash", "icmp", " eq i64 ", function.local("cached_hash"), ", ", function.local("hash")
    )
    prepare.emit(
        "same_tuple_and_key",
        "and",
        " i1 ",
        function.local("same_tuple"),
        ", ",
        function.local("has_key"),
    )
    prepare.emit(
        "possible_hit",
        "and",
        " i1 ",
        function.local("same_tuple_and_key"),
        ", ",
        function.local("same_hash"),
    )
    prepare.emit(
        None,
        "br",
        " i1 ",
        function.local("possible_hit"),
        ", label ",
        function.local("compare_cached_key"),
        ", label ",
        function.local("search"),
    )
    compare_cached_key = function.append_block("compare_cached_key")
    compare_cached_key.emit(
        "cached_key_cmp",
        "call",
        " i32 ",
        module.symbol("strcmp"),
        "(ptr ",
        function.local("cached_key"),
        ", ptr ",
        function.local("key"),
        ")",
    )
    compare_cached_key.emit("same_key", "icmp", " eq i32 ", function.local("cached_key_cmp"), ", 0")
    compare_cached_key.emit(
        None,
        "br",
        " i1 ",
        function.local("same_key"),
        ", label ",
        function.local("inspect_cached"),
        ", label ",
        function.local("search"),
    )
    inspect_cached = function.append_block("inspect_cached")
    inspect_cached.emit("cached_state", "load", " i64, ptr ", function.local("state_slot"))
    inspect_cached.emit("cached_index", "load", " i64, ptr ", function.local("index_slot"))
    inspect_cached.emit(
        "same_state",
        "icmp",
        " eq i64 ",
        function.local("cached_state"),
        ", ",
        function.local("state"),
    )
    inspect_cached.emit(
        "cached_missing", "icmp", " slt i64 ", function.local("cached_index"), ", 0"
    )
    inspect_cached.emit(
        "valid_missing",
        "and",
        " i1 ",
        function.local("same_state"),
        ", ",
        function.local("cached_missing"),
    )
    inspect_cached.emit(
        None,
        "br",
        " i1 ",
        function.local("valid_missing"),
        ", label ",
        function.local("return_cached"),
        ", label ",
        function.local("check_cached_index"),
    )
    check_cached_index = function.append_block("check_cached_index")
    check_cached_index.emit(
        "cached_nonnegative", "icmp", " sge i64 ", function.local("cached_index"), ", 0"
    )
    check_cached_index.emit(
        None,
        "br",
        " i1 ",
        function.local("cached_nonnegative"),
        ", label ",
        function.local("validate_cached"),
        ", label ",
        function.local("search"),
    )
    validate_cached = function.append_block("validate_cached")
    validate_cached.emit(
        "cached_len",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_tuple_len"),
        "(ptr ",
        function.local("tuple"),
        ")",
    )
    validate_cached.emit(
        "cached_in_range",
        "icmp",
        " ult i64 ",
        function.local("cached_index"),
        ", ",
        function.local("cached_len"),
    )
    validate_cached.emit(
        None,
        "br",
        " i1 ",
        function.local("cached_in_range"),
        ", label ",
        function.local("load_cached"),
        ", label ",
        function.local("search"),
    )
    load_cached = function.append_block("load_cached")
    load_cached.emit(
        "cached_candidate",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_get"),
        "(ptr ",
        function.local("tuple"),
        ", i64 ",
        function.local("cached_index"),
        ")",
    )
    load_cached.emit(
        "candidate_exists", "icmp", " ne ptr ", function.local("cached_candidate"), ", null"
    )
    load_cached.emit(
        None,
        "br",
        " i1 ",
        function.local("candidate_exists"),
        ", label ",
        function.local("compare_cached_candidate"),
        ", label ",
        function.local("search"),
    )
    compare_cached_candidate = function.append_block("compare_cached_candidate")
    compare_cached_candidate.emit(
        "cached_candidate_cmp",
        "call",
        " i32 ",
        module.symbol("strcmp"),
        "(ptr ",
        function.local("cached_candidate"),
        ", ptr ",
        function.local("key"),
        ")",
    )
    compare_cached_candidate.emit(
        "cached_candidate_matches",
        "icmp",
        " eq i32 ",
        function.local("cached_candidate_cmp"),
        ", 0",
    )
    compare_cached_candidate.emit(
        None,
        "br",
        " i1 ",
        function.local("cached_candidate_matches"),
        ", label ",
        function.local("refresh_cached"),
        ", label ",
        function.local("search"),
    )
    refresh_cached = function.append_block("refresh_cached")
    refresh_cached.emit(
        None, "store", " i64 ", function.local("state"), ", ptr ", function.local("state_slot")
    )
    refresh_cached.emit(None, "br", " label ", function.local("return_cached"))
    return_cached = function.append_block("return_cached")
    return_cached.emit(None, "ret", " i64 ", function.local("cached_index"))
    search = function.append_block("search")
    search.emit(None, "br", " label ", function.local("search_cond"))
    search_cond = function.append_block("search_cond")
    search_cond.emit(
        "search_index",
        "phi",
        " i64 [ 0, ",
        function.local("search"),
        " ], [ ",
        function.local("next_index"),
        ", ",
        function.local("search_next"),
        " ]",
    )
    search_cond.emit(
        "length",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_tuple_len"),
        "(ptr ",
        function.local("tuple"),
        ")",
    )
    search_cond.emit(
        "done", "icmp", " uge i64 ", function.local("search_index"), ", ", function.local("length")
    )
    search_cond.emit(
        None,
        "br",
        " i1 ",
        function.local("done"),
        ", label ",
        function.local("missing"),
        ", label ",
        function.local("search_body"),
    )
    search_body = function.append_block("search_body")
    search_body.emit(
        "candidate",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_get"),
        "(ptr ",
        function.local("tuple"),
        ", i64 ",
        function.local("search_index"),
        ")",
    )
    search_body.emit("candidate_null", "icmp", " eq ptr ", function.local("candidate"), ", null")
    search_body.emit(
        None,
        "br",
        " i1 ",
        function.local("candidate_null"),
        ", label ",
        function.local("search_next"),
        ", label ",
        function.local("compare_candidate"),
    )
    compare_candidate = function.append_block("compare_candidate")
    compare_candidate.emit(
        "candidate_cmp",
        "call",
        " i32 ",
        module.symbol("strcmp"),
        "(ptr ",
        function.local("candidate"),
        ", ptr ",
        function.local("key"),
        ")",
    )
    compare_candidate.emit("matches", "icmp", " eq i32 ", function.local("candidate_cmp"), ", 0")
    compare_candidate.emit(
        None,
        "br",
        " i1 ",
        function.local("matches"),
        ", label ",
        function.local("found"),
        ", label ",
        function.local("search_next"),
    )
    search_next = function.append_block("search_next")
    search_next.emit("next_index", "add", " i64 ", function.local("search_index"), ", 1")
    search_next.emit(None, "br", " label ", function.local("search_cond"))
    found = function.append_block("found")
    found.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_string_dict_cache_store"),
        "(ptr ",
        function.local("tuple"),
        ", ptr ",
        function.local("key"),
        ", i64 ",
        function.local("hash"),
        ", i64 ",
        function.local("state"),
        ", i64 ",
        function.local("search_index"),
        ")",
    )
    found.emit(None, "ret", " i64 ", function.local("search_index"))
    missing = function.append_block("missing")
    missing.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_string_dict_cache_store"),
        "(ptr ",
        function.local("tuple"),
        ", ptr ",
        function.local("key"),
        ", i64 ",
        function.local("hash"),
        ", i64 ",
        function.local("state"),
        ", i64 -1)",
    )
    missing.emit(None, "ret", " i64 -1")
    uncached_missing = function.append_block("uncached_missing")
    uncached_missing.emit(None, "ret", " i64 -1")


def _build___xcc_aot_string_tuple_note_index(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_string_tuple_note_index")
    entry = function.append_block("entry")
    entry.emit("tuple_null", "icmp", " eq ptr ", function.local("tuple"), ", null")
    entry.emit("key_null", "icmp", " eq ptr ", function.local("key"), ", null")
    entry.emit(
        "invalid", "or", " i1 ", function.local("tuple_null"), ", ", function.local("key_null")
    )
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("invalid"),
        ", label ",
        function.local("done"),
        ", label ",
        function.local("store"),
    )
    store = function.append_block("store")
    store.emit(
        "hash",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_string_dict_hash"),
        "(ptr ",
        function.local("key"),
        ")",
    )
    store.emit(
        "state",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_dict_state"),
        "(ptr ",
        function.local("tuple"),
        ")",
    )
    store.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_string_dict_cache_store"),
        "(ptr ",
        function.local("tuple"),
        ", ptr ",
        function.local("key"),
        ", i64 ",
        function.local("hash"),
        ", i64 ",
        function.local("state"),
        ", i64 ",
        function.local("index"),
        ")",
    )
    store.emit(None, "br", " label ", function.local("done"))
    done = function.append_block("done")
    done.emit(None, "ret", " void")


def _build___xcc_aot_identity_dict_cache_bucket(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_identity_dict_cache_bucket")
    entry = function.append_block("entry")
    entry.emit("dict_bits", "ptrtoint", " ptr ", function.local("dict"), " to i64")
    entry.emit("key_bits", "ptrtoint", " ptr ", function.local("key"), " to i64")
    entry.emit("dict_aligned", "lshr", " i64 ", function.local("dict_bits"), ", 4")
    entry.emit("key_aligned", "lshr", " i64 ", function.local("key_bits"), ", 4")
    entry.emit("key_mixed", "mul", " i64 ", function.local("key_aligned"), ", -7046029254386353131")
    entry.emit(
        "mixed", "xor", " i64 ", function.local("dict_aligned"), ", ", function.local("key_mixed")
    )
    entry.emit("high", "lshr", " i64 ", function.local("mixed"), ", 32")
    entry.emit("folded", "xor", " i64 ", function.local("mixed"), ", ", function.local("high"))
    entry.emit("bucket", "and", " i64 ", function.local("folded"), ", 16383")
    entry.emit(None, "ret", " i64 ", function.local("bucket"))


def _build___xcc_aot_identity_dict_cache_store(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_identity_dict_cache_store")
    entry = function.append_block("entry")
    entry.emit(
        "bucket",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_identity_dict_cache_bucket"),
        "(ptr ",
        function.local("dict"),
        ", ptr ",
        function.local("key"),
        ")",
    )
    entry.emit(
        "dict_slot",
        "getelementptr",
        " [16384 x ptr], ptr ",
        module.symbol("__xcc_aot_identity_dict_cache_dicts"),
        ", i64 0, i64 ",
        function.local("bucket"),
    )
    entry.emit(
        "key_slot",
        "getelementptr",
        " [16384 x ptr], ptr ",
        module.symbol("__xcc_aot_identity_dict_cache_keys"),
        ", i64 0, i64 ",
        function.local("bucket"),
    )
    entry.emit(
        "state_slot",
        "getelementptr",
        " [16384 x i64], ptr ",
        module.symbol("__xcc_aot_identity_dict_cache_states"),
        ", i64 0, i64 ",
        function.local("bucket"),
    )
    entry.emit(
        "index_slot",
        "getelementptr",
        " [16384 x i64], ptr ",
        module.symbol("__xcc_aot_identity_dict_cache_indices"),
        ", i64 0, i64 ",
        function.local("bucket"),
    )
    entry.emit(
        None, "store", " ptr ", function.local("dict"), ", ptr ", function.local("dict_slot")
    )
    entry.emit(None, "store", " ptr ", function.local("key"), ", ptr ", function.local("key_slot"))
    entry.emit(
        None, "store", " i64 ", function.local("state"), ", ptr ", function.local("state_slot")
    )
    entry.emit(
        None, "store", " i64 ", function.local("index"), ", ptr ", function.local("index_slot")
    )
    entry.emit(None, "ret", " void")


def _build___xcc_aot_identity_dict_find_index(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_identity_dict_find_index")
    entry = function.append_block("entry")
    entry.emit("dict_null", "icmp", " eq ptr ", function.local("dict"), ", null")
    entry.emit("key_null", "icmp", " eq ptr ", function.local("key"), ", null")
    entry.emit(
        "invalid", "or", " i1 ", function.local("dict_null"), ", ", function.local("key_null")
    )
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("invalid"),
        ", label ",
        function.local("uncached_missing"),
        ", label ",
        function.local("prepare"),
    )
    prepare = function.append_block("prepare")
    prepare.emit(
        "state",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_dict_state"),
        "(ptr ",
        function.local("dict"),
        ")",
    )
    prepare.emit(
        "bucket",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_identity_dict_cache_bucket"),
        "(ptr ",
        function.local("dict"),
        ", ptr ",
        function.local("key"),
        ")",
    )
    prepare.emit(
        "dict_slot",
        "getelementptr",
        " [16384 x ptr], ptr ",
        module.symbol("__xcc_aot_identity_dict_cache_dicts"),
        ", i64 0, i64 ",
        function.local("bucket"),
    )
    prepare.emit(
        "key_slot",
        "getelementptr",
        " [16384 x ptr], ptr ",
        module.symbol("__xcc_aot_identity_dict_cache_keys"),
        ", i64 0, i64 ",
        function.local("bucket"),
    )
    prepare.emit(
        "state_slot",
        "getelementptr",
        " [16384 x i64], ptr ",
        module.symbol("__xcc_aot_identity_dict_cache_states"),
        ", i64 0, i64 ",
        function.local("bucket"),
    )
    prepare.emit(
        "index_slot",
        "getelementptr",
        " [16384 x i64], ptr ",
        module.symbol("__xcc_aot_identity_dict_cache_indices"),
        ", i64 0, i64 ",
        function.local("bucket"),
    )
    prepare.emit("cached_dict", "load", " ptr, ptr ", function.local("dict_slot"))
    prepare.emit("cached_key", "load", " ptr, ptr ", function.local("key_slot"))
    prepare.emit(
        "same_dict", "icmp", " eq ptr ", function.local("cached_dict"), ", ", function.local("dict")
    )
    prepare.emit(
        "same_key", "icmp", " eq ptr ", function.local("cached_key"), ", ", function.local("key")
    )
    prepare.emit(
        "possible_hit", "and", " i1 ", function.local("same_dict"), ", ", function.local("same_key")
    )
    prepare.emit(
        None,
        "br",
        " i1 ",
        function.local("possible_hit"),
        ", label ",
        function.local("inspect_cached"),
        ", label ",
        function.local("search"),
    )
    inspect_cached = function.append_block("inspect_cached")
    inspect_cached.emit("cached_state", "load", " i64, ptr ", function.local("state_slot"))
    inspect_cached.emit("cached_index", "load", " i64, ptr ", function.local("index_slot"))
    inspect_cached.emit(
        "same_state",
        "icmp",
        " eq i64 ",
        function.local("cached_state"),
        ", ",
        function.local("state"),
    )
    inspect_cached.emit(
        "cached_missing", "icmp", " slt i64 ", function.local("cached_index"), ", 0"
    )
    inspect_cached.emit(
        "valid_missing",
        "and",
        " i1 ",
        function.local("same_state"),
        ", ",
        function.local("cached_missing"),
    )
    inspect_cached.emit(
        None,
        "br",
        " i1 ",
        function.local("valid_missing"),
        ", label ",
        function.local("return_cached"),
        ", label ",
        function.local("check_cached_index"),
    )
    check_cached_index = function.append_block("check_cached_index")
    check_cached_index.emit(
        "cached_nonnegative", "icmp", " sge i64 ", function.local("cached_index"), ", 0"
    )
    check_cached_index.emit(
        None,
        "br",
        " i1 ",
        function.local("cached_nonnegative"),
        ", label ",
        function.local("validate_cached"),
        ", label ",
        function.local("search"),
    )
    validate_cached = function.append_block("validate_cached")
    validate_cached.emit(
        "cached_len",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_tuple_len"),
        "(ptr ",
        function.local("dict"),
        ")",
    )
    validate_cached.emit(
        "cached_in_range",
        "icmp",
        " ult i64 ",
        function.local("cached_index"),
        ", ",
        function.local("cached_len"),
    )
    validate_cached.emit(
        None,
        "br",
        " i1 ",
        function.local("cached_in_range"),
        ", label ",
        function.local("load_cached"),
        ", label ",
        function.local("search"),
    )
    load_cached = function.append_block("load_cached")
    load_cached.emit(
        "cached_pair",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_get"),
        "(ptr ",
        function.local("dict"),
        ", i64 ",
        function.local("cached_index"),
        ")",
    )
    load_cached.emit(
        "cached_candidate",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_get"),
        "(ptr ",
        function.local("cached_pair"),
        ", i64 0)",
    )
    load_cached.emit(
        "cached_candidate_matches",
        "icmp",
        " eq ptr ",
        function.local("cached_candidate"),
        ", ",
        function.local("key"),
    )
    load_cached.emit(
        None,
        "br",
        " i1 ",
        function.local("cached_candidate_matches"),
        ", label ",
        function.local("refresh_cached"),
        ", label ",
        function.local("search"),
    )
    refresh_cached = function.append_block("refresh_cached")
    refresh_cached.emit(
        None, "store", " i64 ", function.local("state"), ", ptr ", function.local("state_slot")
    )
    refresh_cached.emit(None, "br", " label ", function.local("return_cached"))
    return_cached = function.append_block("return_cached")
    return_cached.emit(None, "ret", " i64 ", function.local("cached_index"))
    search = function.append_block("search")
    search.emit(
        "length",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_tuple_len"),
        "(ptr ",
        function.local("dict"),
        ")",
    )
    search.emit(None, "br", " label ", function.local("search_cond"))
    search_cond = function.append_block("search_cond")
    search_cond.emit(
        "search_index",
        "phi",
        " i64 [ ",
        function.local("length"),
        ", ",
        function.local("search"),
        " ], [ ",
        function.local("previous"),
        ", ",
        function.local("search_next"),
        " ]",
    )
    search_cond.emit("empty", "icmp", " eq i64 ", function.local("search_index"), ", 0")
    search_cond.emit(
        None,
        "br",
        " i1 ",
        function.local("empty"),
        ", label ",
        function.local("missing"),
        ", label ",
        function.local("search_body"),
    )
    search_body = function.append_block("search_body")
    search_body.emit("previous", "sub", " i64 ", function.local("search_index"), ", 1")
    search_body.emit(
        "pair",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_get"),
        "(ptr ",
        function.local("dict"),
        ", i64 ",
        function.local("previous"),
        ")",
    )
    search_body.emit(
        "candidate",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_get"),
        "(ptr ",
        function.local("pair"),
        ", i64 0)",
    )
    search_body.emit(
        "matches", "icmp", " eq ptr ", function.local("candidate"), ", ", function.local("key")
    )
    search_body.emit(
        None,
        "br",
        " i1 ",
        function.local("matches"),
        ", label ",
        function.local("found"),
        ", label ",
        function.local("search_next"),
    )
    search_next = function.append_block("search_next")
    search_next.emit(None, "br", " label ", function.local("search_cond"))
    found = function.append_block("found")
    found.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_identity_dict_cache_store"),
        "(ptr ",
        function.local("dict"),
        ", ptr ",
        function.local("key"),
        ", i64 ",
        function.local("state"),
        ", i64 ",
        function.local("previous"),
        ")",
    )
    found.emit(None, "ret", " i64 ", function.local("previous"))
    missing = function.append_block("missing")
    missing.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_identity_dict_cache_store"),
        "(ptr ",
        function.local("dict"),
        ", ptr ",
        function.local("key"),
        ", i64 ",
        function.local("state"),
        ", i64 -1)",
    )
    missing.emit(None, "ret", " i64 -1")
    uncached_missing = function.append_block("uncached_missing")
    uncached_missing.emit(None, "ret", " i64 -1")


def _build___xcc_aot_identity_dict_note_index(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_identity_dict_note_index")
    entry = function.append_block("entry")
    entry.emit("dict_null", "icmp", " eq ptr ", function.local("dict"), ", null")
    entry.emit("key_null", "icmp", " eq ptr ", function.local("key"), ", null")
    entry.emit(
        "invalid", "or", " i1 ", function.local("dict_null"), ", ", function.local("key_null")
    )
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("invalid"),
        ", label ",
        function.local("done"),
        ", label ",
        function.local("store"),
    )
    store = function.append_block("store")
    store.emit(
        "state",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_dict_state"),
        "(ptr ",
        function.local("dict"),
        ")",
    )
    store.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_identity_dict_cache_store"),
        "(ptr ",
        function.local("dict"),
        ", ptr ",
        function.local("key"),
        ", i64 ",
        function.local("state"),
        ", i64 ",
        function.local("index"),
        ")",
    )
    store.emit(None, "br", " label ", function.local("done"))
    done = function.append_block("done")
    done.emit(None, "ret", " void")


def _build___xcc_aot_dict_copy(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_dict_copy")
    entry = function.append_block("entry")
    entry.emit(
        "len",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_tuple_len"),
        "(ptr ",
        function.local("dict"),
        ")",
    )
    entry.emit(
        "out",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_new"),
        "(i64 ",
        function.local("len"),
        ")",
    )
    entry.emit("index_ptr", "alloca", " i64")
    entry.emit(None, "store", " i64 0, ptr ", function.local("index_ptr"))
    entry.emit(None, "br", " label ", function.local("copy_cond"))
    copy_cond = function.append_block("copy_cond")
    copy_cond.emit("index", "load", " i64, ptr ", function.local("index_ptr"))
    copy_cond.emit(
        "done", "icmp", " uge i64 ", function.local("index"), ", ", function.local("len")
    )
    copy_cond.emit(
        None,
        "br",
        " i1 ",
        function.local("done"),
        ", label ",
        function.local("copy_done"),
        ", label ",
        function.local("copy_body"),
    )
    copy_body = function.append_block("copy_body")
    copy_body.emit(
        "raw_pair",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_get"),
        "(ptr ",
        function.local("dict"),
        ", i64 ",
        function.local("index"),
        ")",
    )
    copy_body.emit(
        "pair",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_slice"),
        "(ptr ",
        function.local("raw_pair"),
        ", i64 0, i1 true, i64 0, i1 false)",
    )
    copy_body.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_tuple_set"),
        "(ptr ",
        function.local("out"),
        ", i64 ",
        function.local("index"),
        ", ptr ",
        function.local("pair"),
        ")",
    )
    copy_body.emit("next", "add", " i64 ", function.local("index"), ", 1")
    copy_body.emit(
        None, "store", " i64 ", function.local("next"), ", ptr ", function.local("index_ptr")
    )
    copy_body.emit(None, "br", " label ", function.local("copy_cond"))
    copy_done = function.append_block("copy_done")
    copy_done.emit(None, "ret", " ptr ", function.local("out"))


def _build___xcc_aot_dict_keys(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_dict_keys")
    entry = function.append_block("entry")
    entry.emit(
        "len",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_tuple_len"),
        "(ptr ",
        function.local("dict"),
        ")",
    )
    entry.emit(
        "out",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_new"),
        "(i64 ",
        function.local("len"),
        ")",
    )
    entry.emit("index_ptr", "alloca", " i64")
    entry.emit(None, "store", " i64 0, ptr ", function.local("index_ptr"))
    entry.emit(None, "br", " label ", function.local("keys_cond"))
    keys_cond = function.append_block("keys_cond")
    keys_cond.emit("index", "load", " i64, ptr ", function.local("index_ptr"))
    keys_cond.emit(
        "done", "icmp", " uge i64 ", function.local("index"), ", ", function.local("len")
    )
    keys_cond.emit(
        None,
        "br",
        " i1 ",
        function.local("done"),
        ", label ",
        function.local("keys_done"),
        ", label ",
        function.local("keys_body"),
    )
    keys_body = function.append_block("keys_body")
    keys_body.emit(
        "pair",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_get"),
        "(ptr ",
        function.local("dict"),
        ", i64 ",
        function.local("index"),
        ")",
    )
    keys_body.emit(
        "key",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_get"),
        "(ptr ",
        function.local("pair"),
        ", i64 0)",
    )
    keys_body.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_tuple_set"),
        "(ptr ",
        function.local("out"),
        ", i64 ",
        function.local("index"),
        ", ptr ",
        function.local("key"),
        ")",
    )
    keys_body.emit("next", "add", " i64 ", function.local("index"), ", 1")
    keys_body.emit(
        None, "store", " i64 ", function.local("next"), ", ptr ", function.local("index_ptr")
    )
    keys_body.emit(None, "br", " label ", function.local("keys_cond"))
    keys_done = function.append_block("keys_done")
    keys_done.emit(None, "ret", " ptr ", function.local("out"))


def _build___xcc_aot_dict_values(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_dict_values")
    entry = function.append_block("entry")
    entry.emit(
        "len",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_tuple_len"),
        "(ptr ",
        function.local("dict"),
        ")",
    )
    entry.emit(
        "out",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_new"),
        "(i64 ",
        function.local("len"),
        ")",
    )
    entry.emit("index_ptr", "alloca", " i64")
    entry.emit(None, "store", " i64 0, ptr ", function.local("index_ptr"))
    entry.emit(None, "br", " label ", function.local("values_cond"))
    values_cond = function.append_block("values_cond")
    values_cond.emit("index", "load", " i64, ptr ", function.local("index_ptr"))
    values_cond.emit(
        "done", "icmp", " uge i64 ", function.local("index"), ", ", function.local("len")
    )
    values_cond.emit(
        None,
        "br",
        " i1 ",
        function.local("done"),
        ", label ",
        function.local("values_done"),
        ", label ",
        function.local("values_body"),
    )
    values_body = function.append_block("values_body")
    values_body.emit(
        "pair",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_get"),
        "(ptr ",
        function.local("dict"),
        ", i64 ",
        function.local("index"),
        ")",
    )
    values_body.emit(
        "value",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_get"),
        "(ptr ",
        function.local("pair"),
        ", i64 1)",
    )
    values_body.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_tuple_set"),
        "(ptr ",
        function.local("out"),
        ", i64 ",
        function.local("index"),
        ", ptr ",
        function.local("value"),
        ")",
    )
    values_body.emit("next", "add", " i64 ", function.local("index"), ", 1")
    values_body.emit(
        None, "store", " i64 ", function.local("next"), ", ptr ", function.local("index_ptr")
    )
    values_body.emit(None, "br", " label ", function.local("values_cond"))
    values_done = function.append_block("values_done")
    values_done.emit(None, "ret", " ptr ", function.local("out"))


def _build___xcc_aot_tuple_concat(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_tuple_concat")
    entry = function.append_block("entry")
    entry.emit(
        "left_len",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_tuple_len"),
        "(ptr ",
        function.local("left"),
        ")",
    )
    entry.emit(
        "right_len",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_tuple_len"),
        "(ptr ",
        function.local("right"),
        ")",
    )
    entry.emit(
        "total_len", "add", " i64 ", function.local("left_len"), ", ", function.local("right_len")
    )
    entry.emit(
        "out",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_new"),
        "(i64 ",
        function.local("total_len"),
        ")",
    )
    entry.emit("index_ptr", "alloca", " i64")
    entry.emit(None, "store", " i64 0, ptr ", function.local("index_ptr"))
    entry.emit(None, "br", " label ", function.local("left_cond"))
    left_cond = function.append_block("left_cond")
    left_cond.emit("left_index", "load", " i64, ptr ", function.local("index_ptr"))
    left_cond.emit(
        "left_done",
        "icmp",
        " uge i64 ",
        function.local("left_index"),
        ", ",
        function.local("left_len"),
    )
    left_cond.emit(
        None,
        "br",
        " i1 ",
        function.local("left_done"),
        ", label ",
        function.local("right_init"),
        ", label ",
        function.local("left_body"),
    )
    left_body = function.append_block("left_body")
    left_body.emit(
        "left_item",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_get"),
        "(ptr ",
        function.local("left"),
        ", i64 ",
        function.local("left_index"),
        ")",
    )
    left_body.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_tuple_set"),
        "(ptr ",
        function.local("out"),
        ", i64 ",
        function.local("left_index"),
        ", ptr ",
        function.local("left_item"),
        ")",
    )
    left_body.emit("left_next", "add", " i64 ", function.local("left_index"), ", 1")
    left_body.emit(
        None, "store", " i64 ", function.local("left_next"), ", ptr ", function.local("index_ptr")
    )
    left_body.emit(None, "br", " label ", function.local("left_cond"))
    right_init = function.append_block("right_init")
    right_init.emit(None, "store", " i64 0, ptr ", function.local("index_ptr"))
    right_init.emit(None, "br", " label ", function.local("right_cond"))
    right_cond = function.append_block("right_cond")
    right_cond.emit("right_index", "load", " i64, ptr ", function.local("index_ptr"))
    right_cond.emit(
        "right_done",
        "icmp",
        " uge i64 ",
        function.local("right_index"),
        ", ",
        function.local("right_len"),
    )
    right_cond.emit(
        None,
        "br",
        " i1 ",
        function.local("right_done"),
        ", label ",
        function.local("done"),
        ", label ",
        function.local("right_body"),
    )
    right_body = function.append_block("right_body")
    right_body.emit(
        "right_item",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_get"),
        "(ptr ",
        function.local("right"),
        ", i64 ",
        function.local("right_index"),
        ")",
    )
    right_body.emit(
        "right_offset",
        "add",
        " i64 ",
        function.local("left_len"),
        ", ",
        function.local("right_index"),
    )
    right_body.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_tuple_set"),
        "(ptr ",
        function.local("out"),
        ", i64 ",
        function.local("right_offset"),
        ", ptr ",
        function.local("right_item"),
        ")",
    )
    right_body.emit("right_next", "add", " i64 ", function.local("right_index"), ", 1")
    right_body.emit(
        None, "store", " i64 ", function.local("right_next"), ", ptr ", function.local("index_ptr")
    )
    right_body.emit(None, "br", " label ", function.local("right_cond"))
    done = function.append_block("done")
    done.emit(None, "ret", " ptr ", function.local("out"))


def _build___xcc_aot_tuple_repeat(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_tuple_repeat")
    entry = function.append_block("entry")
    entry.emit(
        "tuple_len",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_tuple_len"),
        "(ptr ",
        function.local("tuple"),
        ")",
    )
    entry.emit("count_nonpositive", "icmp", " sle i64 ", function.local("count"), ", 0")
    entry.emit("tuple_empty", "icmp", " eq i64 ", function.local("tuple_len"), ", 0")
    entry.emit(
        "empty",
        "or",
        " i1 ",
        function.local("count_nonpositive"),
        ", ",
        function.local("tuple_empty"),
    )
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("empty"),
        ", label ",
        function.local("empty_block"),
        ", label ",
        function.local("alloc"),
    )
    empty_block = function.append_block("empty_block")
    empty_block.emit(
        "empty_tuple", "call", " ptr ", module.symbol("__xcc_aot_tuple_new"), "(i64 0)"
    )
    empty_block.emit(None, "ret", " ptr ", function.local("empty_tuple"))
    alloc = function.append_block("alloc")
    alloc.emit(
        "total_len", "mul", " i64 ", function.local("tuple_len"), ", ", function.local("count")
    )
    alloc.emit(
        "out",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_new"),
        "(i64 ",
        function.local("total_len"),
        ")",
    )
    alloc.emit("index_ptr", "alloca", " i64")
    alloc.emit(None, "store", " i64 0, ptr ", function.local("index_ptr"))
    alloc.emit(None, "br", " label ", function.local("copy_cond"))
    copy_cond = function.append_block("copy_cond")
    copy_cond.emit("index", "load", " i64, ptr ", function.local("index_ptr"))
    copy_cond.emit(
        "done_copy", "icmp", " uge i64 ", function.local("index"), ", ", function.local("total_len")
    )
    copy_cond.emit(
        None,
        "br",
        " i1 ",
        function.local("done_copy"),
        ", label ",
        function.local("done"),
        ", label ",
        function.local("copy_body"),
    )
    copy_body = function.append_block("copy_body")
    copy_body.emit(
        "source_index", "srem", " i64 ", function.local("index"), ", ", function.local("tuple_len")
    )
    copy_body.emit(
        "item",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_get"),
        "(ptr ",
        function.local("tuple"),
        ", i64 ",
        function.local("source_index"),
        ")",
    )
    copy_body.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_tuple_set"),
        "(ptr ",
        function.local("out"),
        ", i64 ",
        function.local("index"),
        ", ptr ",
        function.local("item"),
        ")",
    )
    copy_body.emit("next", "add", " i64 ", function.local("index"), ", 1")
    copy_body.emit(
        None, "store", " i64 ", function.local("next"), ", ptr ", function.local("index_ptr")
    )
    copy_body.emit(None, "br", " label ", function.local("copy_cond"))
    done = function.append_block("done")
    done.emit(None, "ret", " ptr ", function.local("out"))


def _build___xcc_aot_tuple_pop(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_tuple_pop")
    entry = function.append_block("entry")
    entry.emit(
        "count",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_tuple_len"),
        "(ptr ",
        function.local("tuple"),
        ")",
    )
    entry.emit("empty", "icmp", " eq i64 ", function.local("count"), ", 0")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("empty"),
        ", label ",
        function.local("empty_block"),
        ", label ",
        function.local("alloc"),
    )
    empty_block = function.append_block("empty_block")
    empty_block.emit(
        "empty_tuple", "call", " ptr ", module.symbol("__xcc_aot_tuple_new"), "(i64 0)"
    )
    empty_block.emit(None, "ret", " ptr ", function.local("empty_tuple"))
    alloc = function.append_block("alloc")
    alloc.emit("new_count", "sub", " i64 ", function.local("count"), ", 1")
    alloc.emit(
        "out",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_new"),
        "(i64 ",
        function.local("new_count"),
        ")",
    )
    alloc.emit("index_ptr", "alloca", " i64")
    alloc.emit(None, "store", " i64 0, ptr ", function.local("index_ptr"))
    alloc.emit(None, "br", " label ", function.local("cond"))
    cond = function.append_block("cond")
    cond.emit("index", "load", " i64, ptr ", function.local("index_ptr"))
    cond.emit(
        "done_pop", "icmp", " uge i64 ", function.local("index"), ", ", function.local("new_count")
    )
    cond.emit(
        None,
        "br",
        " i1 ",
        function.local("done_pop"),
        ", label ",
        function.local("done"),
        ", label ",
        function.local("body"),
    )
    body = function.append_block("body")
    body.emit(
        "item",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_get"),
        "(ptr ",
        function.local("tuple"),
        ", i64 ",
        function.local("index"),
        ")",
    )
    body.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_tuple_set"),
        "(ptr ",
        function.local("out"),
        ", i64 ",
        function.local("index"),
        ", ptr ",
        function.local("item"),
        ")",
    )
    body.emit("next", "add", " i64 ", function.local("index"), ", 1")
    body.emit(None, "store", " i64 ", function.local("next"), ", ptr ", function.local("index_ptr"))
    body.emit(None, "br", " label ", function.local("cond"))
    done = function.append_block("done")
    done.emit(None, "ret", " ptr ", function.local("out"))


def _build___xcc_aot_tuple_pop_item(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_tuple_pop_item")
    entry = function.append_block("entry")
    entry.emit(
        "resolved",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_resolve"),
        "(ptr ",
        function.local("tuple"),
        ")",
    )
    entry.emit(
        "count",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_tuple_len"),
        "(ptr ",
        function.local("resolved"),
        ")",
    )
    entry.emit("negative", "icmp", " slt i64 ", function.local("index"), ", 0")
    entry.emit("from_end", "add", " i64 ", function.local("count"), ", ", function.local("index"))
    entry.emit(
        "actual",
        "select",
        " i1 ",
        function.local("negative"),
        ", i64 ",
        function.local("from_end"),
        ", i64 ",
        function.local("index"),
    )
    entry.emit(
        "item",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_get"),
        "(ptr ",
        function.local("resolved"),
        ", i64 ",
        function.local("actual"),
        ")",
    )
    entry.emit("shift_ptr", "alloca", " i64")
    entry.emit(
        None, "store", " i64 ", function.local("actual"), ", ptr ", function.local("shift_ptr")
    )
    entry.emit(None, "br", " label ", function.local("shift_cond"))
    shift_cond = function.append_block("shift_cond")
    shift_cond.emit("shift", "load", " i64, ptr ", function.local("shift_ptr"))
    shift_cond.emit("source_index", "add", " i64 ", function.local("shift"), ", 1")
    shift_cond.emit(
        "done", "icmp", " uge i64 ", function.local("source_index"), ", ", function.local("count")
    )
    shift_cond.emit(
        None,
        "br",
        " i1 ",
        function.local("done"),
        ", label ",
        function.local("shift_done"),
        ", label ",
        function.local("shift_body"),
    )
    shift_body = function.append_block("shift_body")
    shift_body.emit(
        "next_item",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_get"),
        "(ptr ",
        function.local("resolved"),
        ", i64 ",
        function.local("source_index"),
        ")",
    )
    shift_body.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_tuple_set"),
        "(ptr ",
        function.local("resolved"),
        ", i64 ",
        function.local("shift"),
        ", ptr ",
        function.local("next_item"),
        ")",
    )
    shift_body.emit(
        None,
        "store",
        " i64 ",
        function.local("source_index"),
        ", ptr ",
        function.local("shift_ptr"),
    )
    shift_body.emit(None, "br", " label ", function.local("shift_cond"))
    shift_done = function.append_block("shift_done")
    shift_done.emit("new_count", "sub", " i64 ", function.local("count"), ", 1")
    shift_done.emit(
        None, "store", " i64 ", function.local("new_count"), ", ptr ", function.local("resolved")
    )
    shift_done.emit(None, "ret", " ptr ", function.local("item"))


def _build___xcc_aot_tuple_set_slice(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_tuple_set_slice")
    entry = function.append_block("entry")
    entry.emit(
        "len",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_tuple_len"),
        "(ptr ",
        function.local("tuple"),
        ")",
    )
    entry.emit(
        "value_len",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_tuple_len"),
        "(ptr ",
        function.local("value"),
        ")",
    )
    entry.emit(
        "raw_start",
        "select",
        " i1 ",
        function.local("has_start"),
        ", i64 ",
        function.local("start"),
        ", i64 0",
    )
    entry.emit("start_negative", "icmp", " slt i64 ", function.local("raw_start"), ", 0")
    entry.emit(
        "start_from_end", "add", " i64 ", function.local("len"), ", ", function.local("raw_start")
    )
    entry.emit(
        "start_unclamped",
        "select",
        " i1 ",
        function.local("start_negative"),
        ", i64 ",
        function.local("start_from_end"),
        ", i64 ",
        function.local("raw_start"),
    )
    entry.emit("start_below_zero", "icmp", " slt i64 ", function.local("start_unclamped"), ", 0")
    entry.emit(
        "start_nonnegative",
        "select",
        " i1 ",
        function.local("start_below_zero"),
        ", i64 0, i64 ",
        function.local("start_unclamped"),
    )
    entry.emit(
        "start_too_large",
        "icmp",
        " sgt i64 ",
        function.local("start_nonnegative"),
        ", ",
        function.local("len"),
    )
    entry.emit(
        "clamped_start",
        "select",
        " i1 ",
        function.local("start_too_large"),
        ", i64 ",
        function.local("len"),
        ", i64 ",
        function.local("start_nonnegative"),
    )
    entry.emit(
        "raw_stop",
        "select",
        " i1 ",
        function.local("has_stop"),
        ", i64 ",
        function.local("stop"),
        ", i64 ",
        function.local("len"),
    )
    entry.emit("stop_negative", "icmp", " slt i64 ", function.local("raw_stop"), ", 0")
    entry.emit(
        "stop_from_end", "add", " i64 ", function.local("len"), ", ", function.local("raw_stop")
    )
    entry.emit(
        "stop_unclamped",
        "select",
        " i1 ",
        function.local("stop_negative"),
        ", i64 ",
        function.local("stop_from_end"),
        ", i64 ",
        function.local("raw_stop"),
    )
    entry.emit("stop_below_zero", "icmp", " slt i64 ", function.local("stop_unclamped"), ", 0")
    entry.emit(
        "stop_nonnegative",
        "select",
        " i1 ",
        function.local("stop_below_zero"),
        ", i64 0, i64 ",
        function.local("stop_unclamped"),
    )
    entry.emit(
        "stop_too_large",
        "icmp",
        " sgt i64 ",
        function.local("stop_nonnegative"),
        ", ",
        function.local("len"),
    )
    entry.emit(
        "clamped_stop",
        "select",
        " i1 ",
        function.local("stop_too_large"),
        ", i64 ",
        function.local("len"),
        ", i64 ",
        function.local("stop_nonnegative"),
    )
    entry.emit(
        "stop_before_start",
        "icmp",
        " slt i64 ",
        function.local("clamped_stop"),
        ", ",
        function.local("clamped_start"),
    )
    entry.emit(
        "actual_stop",
        "select",
        " i1 ",
        function.local("stop_before_start"),
        ", i64 ",
        function.local("clamped_start"),
        ", i64 ",
        function.local("clamped_stop"),
    )
    entry.emit(
        "removed",
        "sub",
        " i64 ",
        function.local("actual_stop"),
        ", ",
        function.local("clamped_start"),
    )
    entry.emit(
        "without_removed", "sub", " i64 ", function.local("len"), ", ", function.local("removed")
    )
    entry.emit(
        "new_len",
        "add",
        " i64 ",
        function.local("without_removed"),
        ", ",
        function.local("value_len"),
    )
    entry.emit(
        "wrapped",
        "icmp",
        " ult i64 ",
        function.local("new_len"),
        ", ",
        function.local("without_removed"),
    )
    entry.emit("too_large", "icmp", " ugt i64 ", function.local("new_len"), ", 2305843009213693951")
    entry.emit(
        "invalid", "or", " i1 ", function.local("wrapped"), ", ", function.local("too_large")
    )
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("invalid"),
        ", label ",
        function.local("fail"),
        ", label ",
        function.local("capacity"),
    )
    capacity = function.append_block("capacity")
    capacity.emit(
        "current_capacity",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_tuple_capacity"),
        "(ptr ",
        function.local("tuple"),
        ")",
    )
    capacity.emit(
        "fits",
        "icmp",
        " ule i64 ",
        function.local("new_len"),
        ", ",
        function.local("current_capacity"),
    )
    capacity.emit(
        None,
        "br",
        " i1 ",
        function.local("fits"),
        ", label ",
        function.local("prepare"),
        ", label ",
        function.local("grow"),
    )
    grow = function.append_block("grow")
    grow.emit("doubled", "mul", " i64 ", function.local("current_capacity"), ", 2")
    grow.emit(
        "doubled_wrapped",
        "icmp",
        " ult i64 ",
        function.local("doubled"),
        ", ",
        function.local("current_capacity"),
    )
    grow.emit(
        "doubled_too_large", "icmp", " ugt i64 ", function.local("doubled"), ", 2305843009213693951"
    )
    grow.emit(
        "unsafe_doubling",
        "or",
        " i1 ",
        function.local("doubled_wrapped"),
        ", ",
        function.local("doubled_too_large"),
    )
    grow.emit("small", "icmp", " ult i64 ", function.local("doubled"), ", 4")
    grow.emit(
        "at_least_four",
        "select",
        " i1 ",
        function.local("small"),
        ", i64 4, i64 ",
        function.local("doubled"),
    )
    grow.emit(
        "growth_candidate",
        "select",
        " i1 ",
        function.local("unsafe_doubling"),
        ", i64 ",
        function.local("new_len"),
        ", i64 ",
        function.local("at_least_four"),
    )
    grow.emit(
        "candidate_too_small",
        "icmp",
        " ult i64 ",
        function.local("growth_candidate"),
        ", ",
        function.local("new_len"),
    )
    grow.emit(
        "new_capacity",
        "select",
        " i1 ",
        function.local("candidate_too_small"),
        ", i64 ",
        function.local("new_len"),
        ", i64 ",
        function.local("growth_candidate"),
    )
    grow.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_tuple_register_capacity"),
        "(ptr ",
        function.local("tuple"),
        ", i64 ",
        function.local("new_capacity"),
        ")",
    )
    grow.emit(None, "br", " label ", function.local("prepare"))
    prepare = function.append_block("prepare")
    prepare.emit("data_slot", "getelementptr", " ptr, ptr ", function.local("tuple"), ", i64 2")
    prepare.emit("data", "load", " ptr, ptr ", function.local("data_slot"))
    prepare.emit(
        "suffix_len", "sub", " i64 ", function.local("len"), ", ", function.local("actual_stop")
    )
    prepare.emit("has_suffix", "icmp", " ugt i64 ", function.local("suffix_len"), ", 0")
    prepare.emit(
        None,
        "br",
        " i1 ",
        function.local("has_suffix"),
        ", label ",
        function.local("shift_suffix"),
        ", label ",
        function.local("copy_check"),
    )
    shift_suffix = function.append_block("shift_suffix")
    shift_suffix.emit(
        "suffix_source",
        "getelementptr",
        " ptr, ptr ",
        function.local("data"),
        ", i64 ",
        function.local("actual_stop"),
    )
    shift_suffix.emit(
        "suffix_destination_index",
        "add",
        " i64 ",
        function.local("clamped_start"),
        ", ",
        function.local("value_len"),
    )
    shift_suffix.emit(
        "suffix_destination",
        "getelementptr",
        " ptr, ptr ",
        function.local("data"),
        ", i64 ",
        function.local("suffix_destination_index"),
    )
    shift_suffix.emit("suffix_bytes", "mul", " i64 ", function.local("suffix_len"), ", 8")
    shift_suffix.emit(
        "shifted",
        "call",
        " ptr ",
        module.symbol("memmove"),
        "(ptr ",
        function.local("suffix_destination"),
        ", ptr ",
        function.local("suffix_source"),
        ", i64 ",
        function.local("suffix_bytes"),
        ")",
    )
    shift_suffix.emit(None, "br", " label ", function.local("copy_check"))
    copy_check = function.append_block("copy_check")
    copy_check.emit("has_value", "icmp", " ugt i64 ", function.local("value_len"), ", 0")
    copy_check.emit(
        None,
        "br",
        " i1 ",
        function.local("has_value"),
        ", label ",
        function.local("copy_value"),
        ", label ",
        function.local("commit"),
    )
    copy_value = function.append_block("copy_value")
    copy_value.emit(
        "value_data_slot", "getelementptr", " ptr, ptr ", function.local("value"), ", i64 2"
    )
    copy_value.emit("value_data", "load", " ptr, ptr ", function.local("value_data_slot"))
    copy_value.emit(
        "value_destination",
        "getelementptr",
        " ptr, ptr ",
        function.local("data"),
        ", i64 ",
        function.local("clamped_start"),
    )
    copy_value.emit("value_bytes", "mul", " i64 ", function.local("value_len"), ", 8")
    copy_value.emit(
        "copied",
        "call",
        " ptr ",
        module.symbol("memmove"),
        "(ptr ",
        function.local("value_destination"),
        ", ptr ",
        function.local("value_data"),
        ", i64 ",
        function.local("value_bytes"),
        ")",
    )
    copy_value.emit(None, "br", " label ", function.local("commit"))
    commit = function.append_block("commit")
    commit.emit(
        None, "store", " i64 ", function.local("new_len"), ", ptr ", function.local("tuple")
    )
    commit.emit(None, "ret", " ptr ", function.local("tuple"))
    fail = function.append_block("fail")
    fail.emit(None, "call", " void ", module.symbol("__xcc_aot_allocation_fail"), "()")
    fail.emit(None, "unreachable")


def _build___xcc_aot_tuple_reversed(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_tuple_reversed")
    entry = function.append_block("entry")
    entry.emit(
        "count",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_tuple_len"),
        "(ptr ",
        function.local("tuple"),
        ")",
    )
    entry.emit(
        "out",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_new"),
        "(i64 ",
        function.local("count"),
        ")",
    )
    entry.emit("index_ptr", "alloca", " i64")
    entry.emit(None, "store", " i64 0, ptr ", function.local("index_ptr"))
    entry.emit(None, "br", " label ", function.local("cond"))
    cond = function.append_block("cond")
    cond.emit("index", "load", " i64, ptr ", function.local("index_ptr"))
    cond.emit(
        "done_reverse", "icmp", " uge i64 ", function.local("index"), ", ", function.local("count")
    )
    cond.emit(
        None,
        "br",
        " i1 ",
        function.local("done_reverse"),
        ", label ",
        function.local("done"),
        ", label ",
        function.local("body"),
    )
    body = function.append_block("body")
    body.emit("last", "sub", " i64 ", function.local("count"), ", 1")
    body.emit("source_index", "sub", " i64 ", function.local("last"), ", ", function.local("index"))
    body.emit(
        "item",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_get"),
        "(ptr ",
        function.local("tuple"),
        ", i64 ",
        function.local("source_index"),
        ")",
    )
    body.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_tuple_set"),
        "(ptr ",
        function.local("out"),
        ", i64 ",
        function.local("index"),
        ", ptr ",
        function.local("item"),
        ")",
    )
    body.emit("next", "add", " i64 ", function.local("index"), ", 1")
    body.emit(None, "store", " i64 ", function.local("next"), ", ptr ", function.local("index_ptr"))
    body.emit(None, "br", " label ", function.local("cond"))
    done = function.append_block("done")
    done.emit(None, "ret", " ptr ", function.local("out"))


def _build___xcc_aot_range(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_range")
    entry = function.append_block("entry")
    entry.emit("step_zero", "icmp", " eq i64 ", function.local("step"), ", 0")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("step_zero"),
        ", label ",
        function.local("empty"),
        ", label ",
        function.local("nonzero"),
    )
    nonzero = function.append_block("nonzero")
    nonzero.emit("positive", "icmp", " sgt i64 ", function.local("step"), ", 0")
    nonzero.emit(
        None,
        "br",
        " i1 ",
        function.local("positive"),
        ", label ",
        function.local("pos_check"),
        ", label ",
        function.local("neg_check"),
    )
    pos_check = function.append_block("pos_check")
    pos_check.emit(
        "pos_has", "icmp", " slt i64 ", function.local("start"), ", ", function.local("stop")
    )
    pos_check.emit(
        None,
        "br",
        " i1 ",
        function.local("pos_has"),
        ", label ",
        function.local("pos_len"),
        ", label ",
        function.local("empty"),
    )
    pos_len = function.append_block("pos_len")
    pos_len.emit("pos_delta", "sub", " i64 ", function.local("stop"), ", ", function.local("start"))
    pos_len.emit("pos_delta_adj", "sub", " i64 ", function.local("pos_delta"), ", 1")
    pos_len.emit(
        "pos_div", "sdiv", " i64 ", function.local("pos_delta_adj"), ", ", function.local("step")
    )
    pos_len.emit("pos_count", "add", " i64 ", function.local("pos_div"), ", 1")
    pos_len.emit(None, "br", " label ", function.local("alloc"))
    neg_check = function.append_block("neg_check")
    neg_check.emit(
        "neg_has", "icmp", " sgt i64 ", function.local("start"), ", ", function.local("stop")
    )
    neg_check.emit(
        None,
        "br",
        " i1 ",
        function.local("neg_has"),
        ", label ",
        function.local("neg_len"),
        ", label ",
        function.local("empty"),
    )
    neg_len = function.append_block("neg_len")
    neg_len.emit("neg_step", "sub", " i64 0, ", function.local("step"))
    neg_len.emit("neg_delta", "sub", " i64 ", function.local("start"), ", ", function.local("stop"))
    neg_len.emit("neg_delta_adj", "sub", " i64 ", function.local("neg_delta"), ", 1")
    neg_len.emit(
        "neg_div",
        "sdiv",
        " i64 ",
        function.local("neg_delta_adj"),
        ", ",
        function.local("neg_step"),
    )
    neg_len.emit("neg_count", "add", " i64 ", function.local("neg_div"), ", 1")
    neg_len.emit(None, "br", " label ", function.local("alloc"))
    empty = function.append_block("empty")
    empty.emit(None, "br", " label ", function.local("alloc"))
    alloc = function.append_block("alloc")
    alloc.emit(
        "count",
        "phi",
        " i64 [ 0, ",
        function.local("empty"),
        " ], [ ",
        function.local("pos_count"),
        ", ",
        function.local("pos_len"),
        " ], [ ",
        function.local("neg_count"),
        ", ",
        function.local("neg_len"),
        " ]",
    )
    alloc.emit(
        "out",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_new"),
        "(i64 ",
        function.local("count"),
        ")",
    )
    alloc.emit("index_ptr", "alloca", " i64")
    alloc.emit(None, "store", " i64 0, ptr ", function.local("index_ptr"))
    alloc.emit(None, "br", " label ", function.local("cond"))
    cond = function.append_block("cond")
    cond.emit("index", "load", " i64, ptr ", function.local("index_ptr"))
    cond.emit(
        "done_range", "icmp", " uge i64 ", function.local("index"), ", ", function.local("count")
    )
    cond.emit(
        None,
        "br",
        " i1 ",
        function.local("done_range"),
        ", label ",
        function.local("done"),
        ", label ",
        function.local("body"),
    )
    body = function.append_block("body")
    body.emit("offset", "mul", " i64 ", function.local("index"), ", ", function.local("step"))
    body.emit("value", "add", " i64 ", function.local("start"), ", ", function.local("offset"))
    body.emit("boxed", "inttoptr", " i64 ", function.local("value"), " to ptr")
    body.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_tuple_set"),
        "(ptr ",
        function.local("out"),
        ", i64 ",
        function.local("index"),
        ", ptr ",
        function.local("boxed"),
        ")",
    )
    body.emit("next", "add", " i64 ", function.local("index"), ", 1")
    body.emit(None, "store", " i64 ", function.local("next"), ", ptr ", function.local("index_ptr"))
    body.emit(None, "br", " label ", function.local("cond"))
    done = function.append_block("done")
    done.emit(None, "ret", " ptr ", function.local("out"))


def _build___xcc_aot_zip2(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_zip2")
    entry = function.append_block("entry")
    entry.emit(
        "left_len",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_tuple_len"),
        "(ptr ",
        function.local("left"),
        ")",
    )
    entry.emit(
        "right_len",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_tuple_len"),
        "(ptr ",
        function.local("right"),
        ")",
    )
    entry.emit(
        "left_shorter",
        "icmp",
        " ult i64 ",
        function.local("left_len"),
        ", ",
        function.local("right_len"),
    )
    entry.emit(
        "count",
        "select",
        " i1 ",
        function.local("left_shorter"),
        ", i64 ",
        function.local("left_len"),
        ", i64 ",
        function.local("right_len"),
    )
    entry.emit(
        "out",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_new"),
        "(i64 ",
        function.local("count"),
        ")",
    )
    entry.emit("index_ptr", "alloca", " i64")
    entry.emit(None, "store", " i64 0, ptr ", function.local("index_ptr"))
    entry.emit(None, "br", " label ", function.local("cond"))
    cond = function.append_block("cond")
    cond.emit("index", "load", " i64, ptr ", function.local("index_ptr"))
    cond.emit(
        "done_zip", "icmp", " uge i64 ", function.local("index"), ", ", function.local("count")
    )
    cond.emit(
        None,
        "br",
        " i1 ",
        function.local("done_zip"),
        ", label ",
        function.local("done"),
        ", label ",
        function.local("body"),
    )
    body = function.append_block("body")
    body.emit(
        "left_item",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_get"),
        "(ptr ",
        function.local("left"),
        ", i64 ",
        function.local("index"),
        ")",
    )
    body.emit(
        "right_item",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_get"),
        "(ptr ",
        function.local("right"),
        ", i64 ",
        function.local("index"),
        ")",
    )
    body.emit("pair", "call", " ptr ", module.symbol("__xcc_aot_tuple_new"), "(i64 2)")
    body.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_tuple_set"),
        "(ptr ",
        function.local("pair"),
        ", i64 0, ptr ",
        function.local("left_item"),
        ")",
    )
    body.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_tuple_set"),
        "(ptr ",
        function.local("pair"),
        ", i64 1, ptr ",
        function.local("right_item"),
        ")",
    )
    body.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_tuple_set"),
        "(ptr ",
        function.local("out"),
        ", i64 ",
        function.local("index"),
        ", ptr ",
        function.local("pair"),
        ")",
    )
    body.emit("next", "add", " i64 ", function.local("index"), ", 1")
    body.emit(None, "store", " i64 ", function.local("next"), ", ptr ", function.local("index_ptr"))
    body.emit(None, "br", " label ", function.local("cond"))
    done = function.append_block("done")
    done.emit(None, "ret", " ptr ", function.local("out"))


def _build___xcc_aot_string_split(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_string_split")
    entry = function.append_block("entry")
    entry.emit("sep_byte", "load", " i8, ptr ", function.local("sep"))
    entry.emit("sep_empty", "icmp", " eq i8 ", function.local("sep_byte"), ", 0")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("sep_empty"),
        ", label ",
        function.local("single"),
        ", label ",
        function.local("count_init"),
    )
    single = function.append_block("single")
    single.emit("single_tuple", "call", " ptr ", module.symbol("__xcc_aot_tuple_new"), "(i64 1)")
    single.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_tuple_set"),
        "(ptr ",
        function.local("single_tuple"),
        ", i64 0, ptr ",
        function.local("text"),
        ")",
    )
    single.emit(None, "ret", " ptr ", function.local("single_tuple"))
    count_init = function.append_block("count_init")
    count_init.emit(
        "text_len", "call", " i64 ", module.symbol("strlen"), "(ptr ", function.local("text"), ")"
    )
    count_init.emit("count_ptr", "alloca", " i64")
    count_init.emit("scan_ptr", "alloca", " i64")
    count_init.emit(None, "store", " i64 1, ptr ", function.local("count_ptr"))
    count_init.emit(None, "store", " i64 0, ptr ", function.local("scan_ptr"))
    count_init.emit(None, "br", " label ", function.local("count_cond"))
    count_cond = function.append_block("count_cond")
    count_cond.emit("scan", "load", " i64, ptr ", function.local("scan_ptr"))
    count_cond.emit(
        "count_done", "icmp", " uge i64 ", function.local("scan"), ", ", function.local("text_len")
    )
    count_cond.emit(
        None,
        "br",
        " i1 ",
        function.local("count_done"),
        ", label ",
        function.local("alloc"),
        ", label ",
        function.local("count_body"),
    )
    count_body = function.append_block("count_body")
    count_body.emit(
        "char_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("text"),
        ", i64 ",
        function.local("scan"),
    )
    count_body.emit("char", "load", " i8, ptr ", function.local("char_ptr"))
    count_body.emit(
        "is_sep", "icmp", " eq i8 ", function.local("char"), ", ", function.local("sep_byte")
    )
    count_body.emit(
        None,
        "br",
        " i1 ",
        function.local("is_sep"),
        ", label ",
        function.local("count_sep"),
        ", label ",
        function.local("count_next"),
    )
    count_sep = function.append_block("count_sep")
    count_sep.emit("old_count", "load", " i64, ptr ", function.local("count_ptr"))
    count_sep.emit("new_count", "add", " i64 ", function.local("old_count"), ", 1")
    count_sep.emit(
        None, "store", " i64 ", function.local("new_count"), ", ptr ", function.local("count_ptr")
    )
    count_sep.emit(None, "br", " label ", function.local("count_next"))
    count_next = function.append_block("count_next")
    count_next.emit("next_scan", "add", " i64 ", function.local("scan"), ", 1")
    count_next.emit(
        None, "store", " i64 ", function.local("next_scan"), ", ptr ", function.local("scan_ptr")
    )
    count_next.emit(None, "br", " label ", function.local("count_cond"))
    alloc = function.append_block("alloc")
    alloc.emit("part_count", "load", " i64, ptr ", function.local("count_ptr"))
    alloc.emit(
        "tuple",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_new"),
        "(i64 ",
        function.local("part_count"),
        ")",
    )
    alloc.emit("start_ptr", "alloca", " i64")
    alloc.emit("index_ptr", "alloca", " i64")
    alloc.emit("part_ptr", "alloca", " i64")
    alloc.emit(None, "store", " i64 0, ptr ", function.local("start_ptr"))
    alloc.emit(None, "store", " i64 0, ptr ", function.local("index_ptr"))
    alloc.emit(None, "store", " i64 0, ptr ", function.local("part_ptr"))
    alloc.emit(None, "br", " label ", function.local("copy_cond"))
    copy_cond = function.append_block("copy_cond")
    copy_cond.emit("index", "load", " i64, ptr ", function.local("index_ptr"))
    copy_cond.emit(
        "at_end", "icmp", " eq i64 ", function.local("index"), ", ", function.local("text_len")
    )
    copy_cond.emit(
        None,
        "br",
        " i1 ",
        function.local("at_end"),
        ", label ",
        function.local("copy_part"),
        ", label ",
        function.local("copy_check_sep"),
    )
    copy_check_sep = function.append_block("copy_check_sep")
    copy_check_sep.emit(
        "copy_char_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("text"),
        ", i64 ",
        function.local("index"),
    )
    copy_check_sep.emit("copy_char", "load", " i8, ptr ", function.local("copy_char_ptr"))
    copy_check_sep.emit(
        "copy_is_sep",
        "icmp",
        " eq i8 ",
        function.local("copy_char"),
        ", ",
        function.local("sep_byte"),
    )
    copy_check_sep.emit(
        None,
        "br",
        " i1 ",
        function.local("copy_is_sep"),
        ", label ",
        function.local("copy_part"),
        ", label ",
        function.local("copy_next"),
    )
    copy_part = function.append_block("copy_part")
    copy_part.emit("start", "load", " i64, ptr ", function.local("start_ptr"))
    copy_part.emit(
        "part_len", "sub", " i64 ", function.local("index"), ", ", function.local("start")
    )
    copy_part.emit("part_bytes", "add", " i64 ", function.local("part_len"), ", 1")
    copy_part.emit(
        "part", "call", " ptr ", module.symbol("malloc"), "(i64 ", function.local("part_bytes"), ")"
    )
    copy_part.emit(
        "source",
        "getelementptr",
        " i8, ptr ",
        function.local("text"),
        ", i64 ",
        function.local("start"),
    )
    copy_part.emit(
        "copied",
        "call",
        " ptr ",
        module.symbol("memcpy"),
        "(ptr ",
        function.local("part"),
        ", ptr ",
        function.local("source"),
        ", i64 ",
        function.local("part_len"),
        ")",
    )
    copy_part.emit(
        "nul_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("part"),
        ", i64 ",
        function.local("part_len"),
    )
    copy_part.emit(None, "store", " i8 0, ptr ", function.local("nul_ptr"))
    copy_part.emit("part_index", "load", " i64, ptr ", function.local("part_ptr"))
    copy_part.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_tuple_set"),
        "(ptr ",
        function.local("tuple"),
        ", i64 ",
        function.local("part_index"),
        ", ptr ",
        function.local("part"),
        ")",
    )
    copy_part.emit("next_part", "add", " i64 ", function.local("part_index"), ", 1")
    copy_part.emit(
        None, "store", " i64 ", function.local("next_part"), ", ptr ", function.local("part_ptr")
    )
    copy_part.emit("next_start", "add", " i64 ", function.local("index"), ", 1")
    copy_part.emit(
        None, "store", " i64 ", function.local("next_start"), ", ptr ", function.local("start_ptr")
    )
    copy_part.emit(
        None,
        "br",
        " i1 ",
        function.local("at_end"),
        ", label ",
        function.local("done"),
        ", label ",
        function.local("copy_next"),
    )
    copy_next = function.append_block("copy_next")
    copy_next.emit("next_index", "add", " i64 ", function.local("index"), ", 1")
    copy_next.emit(
        None, "store", " i64 ", function.local("next_index"), ", ptr ", function.local("index_ptr")
    )
    copy_next.emit(None, "br", " label ", function.local("copy_cond"))
    done = function.append_block("done")
    done.emit(None, "ret", " ptr ", function.local("tuple"))


def _build___xcc_aot_string_split_limit(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_string_split_limit")
    entry = function.append_block("entry")
    entry.emit("text_null", "icmp", " eq ptr ", function.local("text"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("text_null"),
        ", label ",
        function.local("empty"),
        ", label ",
        function.local("check_sep"),
    )
    empty = function.append_block("empty")
    empty.emit("empty_tuple", "call", " ptr ", module.symbol("__xcc_aot_tuple_new"), "(i64 0)")
    empty.emit(None, "ret", " ptr ", function.local("empty_tuple"))
    check_sep = function.append_block("check_sep")
    check_sep.emit(
        "sep_len", "call", " i64 ", module.symbol("strlen"), "(ptr ", function.local("sep"), ")"
    )
    check_sep.emit("sep_empty", "icmp", " eq i64 ", function.local("sep_len"), ", 0")
    check_sep.emit(
        None,
        "br",
        " i1 ",
        function.local("sep_empty"),
        ", label ",
        function.local("single"),
        ", label ",
        function.local("count_init"),
    )
    single = function.append_block("single")
    single.emit("single_tuple", "call", " ptr ", module.symbol("__xcc_aot_tuple_new"), "(i64 1)")
    single.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_tuple_set"),
        "(ptr ",
        function.local("single_tuple"),
        ", i64 0, ptr ",
        function.local("text"),
        ")",
    )
    single.emit(None, "ret", " ptr ", function.local("single_tuple"))
    count_init = function.append_block("count_init")
    count_init.emit(
        "text_len", "call", " i64 ", module.symbol("strlen"), "(ptr ", function.local("text"), ")"
    )
    count_init.emit("max_unlimited", "icmp", " slt i64 ", function.local("maxsplit"), ", 0")
    count_init.emit("count_ptr", "alloca", " i64")
    count_init.emit("split_ptr", "alloca", " i64")
    count_init.emit("scan_ptr", "alloca", " i64")
    count_init.emit(None, "store", " i64 1, ptr ", function.local("count_ptr"))
    count_init.emit(None, "store", " i64 0, ptr ", function.local("split_ptr"))
    count_init.emit(None, "store", " i64 0, ptr ", function.local("scan_ptr"))
    count_init.emit(None, "br", " label ", function.local("count_cond"))
    count_cond = function.append_block("count_cond")
    count_cond.emit("scan", "load", " i64, ptr ", function.local("scan_ptr"))
    count_cond.emit(
        "count_done", "icmp", " uge i64 ", function.local("scan"), ", ", function.local("text_len")
    )
    count_cond.emit(
        None,
        "br",
        " i1 ",
        function.local("count_done"),
        ", label ",
        function.local("alloc"),
        ", label ",
        function.local("count_check_fit"),
    )
    count_check_fit = function.append_block("count_check_fit")
    count_check_fit.emit(
        "remaining", "sub", " i64 ", function.local("text_len"), ", ", function.local("scan")
    )
    count_check_fit.emit(
        "fits", "icmp", " ule i64 ", function.local("sep_len"), ", ", function.local("remaining")
    )
    count_check_fit.emit(
        None,
        "br",
        " i1 ",
        function.local("fits"),
        ", label ",
        function.local("count_compare"),
        ", label ",
        function.local("count_step"),
    )
    count_compare = function.append_block("count_compare")
    count_compare.emit(
        "scan_text",
        "getelementptr",
        " i8, ptr ",
        function.local("text"),
        ", i64 ",
        function.local("scan"),
    )
    count_compare.emit(
        "cmp",
        "call",
        " i32 ",
        module.symbol("strncmp"),
        "(ptr ",
        function.local("scan_text"),
        ", ptr ",
        function.local("sep"),
        ", i64 ",
        function.local("sep_len"),
        ")",
    )
    count_compare.emit("match", "icmp", " eq i32 ", function.local("cmp"), ", 0")
    count_compare.emit(
        None,
        "br",
        " i1 ",
        function.local("match"),
        ", label ",
        function.local("count_match"),
        ", label ",
        function.local("count_step"),
    )
    count_match = function.append_block("count_match")
    count_match.emit("split_count", "load", " i64, ptr ", function.local("split_ptr"))
    count_match.emit(
        "under_max",
        "icmp",
        " slt i64 ",
        function.local("split_count"),
        ", ",
        function.local("maxsplit"),
    )
    count_match.emit(
        "can_split",
        "or",
        " i1 ",
        function.local("max_unlimited"),
        ", ",
        function.local("under_max"),
    )
    count_match.emit(
        None,
        "br",
        " i1 ",
        function.local("can_split"),
        ", label ",
        function.local("count_split"),
        ", label ",
        function.local("count_step"),
    )
    count_split = function.append_block("count_split")
    count_split.emit("old_count", "load", " i64, ptr ", function.local("count_ptr"))
    count_split.emit("new_count", "add", " i64 ", function.local("old_count"), ", 1")
    count_split.emit(
        None, "store", " i64 ", function.local("new_count"), ", ptr ", function.local("count_ptr")
    )
    count_split.emit("next_split", "add", " i64 ", function.local("split_count"), ", 1")
    count_split.emit(
        None, "store", " i64 ", function.local("next_split"), ", ptr ", function.local("split_ptr")
    )
    count_split.emit(
        "after_sep", "add", " i64 ", function.local("scan"), ", ", function.local("sep_len")
    )
    count_split.emit(
        None, "store", " i64 ", function.local("after_sep"), ", ptr ", function.local("scan_ptr")
    )
    count_split.emit(None, "br", " label ", function.local("count_cond"))
    count_step = function.append_block("count_step")
    count_step.emit("next_scan", "add", " i64 ", function.local("scan"), ", 1")
    count_step.emit(
        None, "store", " i64 ", function.local("next_scan"), ", ptr ", function.local("scan_ptr")
    )
    count_step.emit(None, "br", " label ", function.local("count_cond"))
    alloc = function.append_block("alloc")
    alloc.emit("part_count", "load", " i64, ptr ", function.local("count_ptr"))
    alloc.emit(
        "tuple",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_new"),
        "(i64 ",
        function.local("part_count"),
        ")",
    )
    alloc.emit("start_ptr", "alloca", " i64")
    alloc.emit("copy_scan_ptr", "alloca", " i64")
    alloc.emit("copy_part_ptr", "alloca", " i64")
    alloc.emit("copy_split_ptr", "alloca", " i64")
    alloc.emit(None, "store", " i64 0, ptr ", function.local("start_ptr"))
    alloc.emit(None, "store", " i64 0, ptr ", function.local("copy_scan_ptr"))
    alloc.emit(None, "store", " i64 0, ptr ", function.local("copy_part_ptr"))
    alloc.emit(None, "store", " i64 0, ptr ", function.local("copy_split_ptr"))
    alloc.emit(None, "br", " label ", function.local("copy_cond"))
    copy_cond = function.append_block("copy_cond")
    copy_cond.emit("copy_scan", "load", " i64, ptr ", function.local("copy_scan_ptr"))
    copy_cond.emit(
        "copy_done",
        "icmp",
        " uge i64 ",
        function.local("copy_scan"),
        ", ",
        function.local("text_len"),
    )
    copy_cond.emit(
        None,
        "br",
        " i1 ",
        function.local("copy_done"),
        ", label ",
        function.local("copy_final"),
        ", label ",
        function.local("copy_check_fit"),
    )
    copy_check_fit = function.append_block("copy_check_fit")
    copy_check_fit.emit(
        "copy_remaining",
        "sub",
        " i64 ",
        function.local("text_len"),
        ", ",
        function.local("copy_scan"),
    )
    copy_check_fit.emit(
        "copy_fits",
        "icmp",
        " ule i64 ",
        function.local("sep_len"),
        ", ",
        function.local("copy_remaining"),
    )
    copy_check_fit.emit(
        None,
        "br",
        " i1 ",
        function.local("copy_fits"),
        ", label ",
        function.local("copy_compare"),
        ", label ",
        function.local("copy_step"),
    )
    copy_compare = function.append_block("copy_compare")
    copy_compare.emit(
        "copy_text",
        "getelementptr",
        " i8, ptr ",
        function.local("text"),
        ", i64 ",
        function.local("copy_scan"),
    )
    copy_compare.emit(
        "copy_cmp",
        "call",
        " i32 ",
        module.symbol("strncmp"),
        "(ptr ",
        function.local("copy_text"),
        ", ptr ",
        function.local("sep"),
        ", i64 ",
        function.local("sep_len"),
        ")",
    )
    copy_compare.emit("copy_match", "icmp", " eq i32 ", function.local("copy_cmp"), ", 0")
    copy_compare.emit(
        None,
        "br",
        " i1 ",
        function.local("copy_match"),
        ", label ",
        function.local("copy_match_block"),
        ", label ",
        function.local("copy_step"),
    )
    copy_match_block = function.append_block("copy_match_block")
    copy_match_block.emit(
        "copy_split_count", "load", " i64, ptr ", function.local("copy_split_ptr")
    )
    copy_match_block.emit(
        "copy_under_max",
        "icmp",
        " slt i64 ",
        function.local("copy_split_count"),
        ", ",
        function.local("maxsplit"),
    )
    copy_match_block.emit(
        "copy_can_split",
        "or",
        " i1 ",
        function.local("max_unlimited"),
        ", ",
        function.local("copy_under_max"),
    )
    copy_match_block.emit(
        None,
        "br",
        " i1 ",
        function.local("copy_can_split"),
        ", label ",
        function.local("copy_emit"),
        ", label ",
        function.local("copy_step"),
    )
    copy_emit = function.append_block("copy_emit")
    copy_emit.emit("part_start", "load", " i64, ptr ", function.local("start_ptr"))
    copy_emit.emit(
        "part_len", "sub", " i64 ", function.local("copy_scan"), ", ", function.local("part_start")
    )
    copy_emit.emit("part_bytes", "add", " i64 ", function.local("part_len"), ", 1")
    copy_emit.emit(
        "part", "call", " ptr ", module.symbol("malloc"), "(i64 ", function.local("part_bytes"), ")"
    )
    copy_emit.emit(
        "part_source",
        "getelementptr",
        " i8, ptr ",
        function.local("text"),
        ", i64 ",
        function.local("part_start"),
    )
    copy_emit.emit(
        "part_copied",
        "call",
        " ptr ",
        module.symbol("memcpy"),
        "(ptr ",
        function.local("part"),
        ", ptr ",
        function.local("part_source"),
        ", i64 ",
        function.local("part_len"),
        ")",
    )
    copy_emit.emit(
        "part_nul",
        "getelementptr",
        " i8, ptr ",
        function.local("part"),
        ", i64 ",
        function.local("part_len"),
    )
    copy_emit.emit(None, "store", " i8 0, ptr ", function.local("part_nul"))
    copy_emit.emit("part_index", "load", " i64, ptr ", function.local("copy_part_ptr"))
    copy_emit.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_tuple_set"),
        "(ptr ",
        function.local("tuple"),
        ", i64 ",
        function.local("part_index"),
        ", ptr ",
        function.local("part"),
        ")",
    )
    copy_emit.emit("next_part", "add", " i64 ", function.local("part_index"), ", 1")
    copy_emit.emit(
        None,
        "store",
        " i64 ",
        function.local("next_part"),
        ", ptr ",
        function.local("copy_part_ptr"),
    )
    copy_emit.emit("next_copy_split", "add", " i64 ", function.local("copy_split_count"), ", 1")
    copy_emit.emit(
        None,
        "store",
        " i64 ",
        function.local("next_copy_split"),
        ", ptr ",
        function.local("copy_split_ptr"),
    )
    copy_emit.emit(
        "after_copy_sep",
        "add",
        " i64 ",
        function.local("copy_scan"),
        ", ",
        function.local("sep_len"),
    )
    copy_emit.emit(
        None,
        "store",
        " i64 ",
        function.local("after_copy_sep"),
        ", ptr ",
        function.local("start_ptr"),
    )
    copy_emit.emit(
        None,
        "store",
        " i64 ",
        function.local("after_copy_sep"),
        ", ptr ",
        function.local("copy_scan_ptr"),
    )
    copy_emit.emit(None, "br", " label ", function.local("copy_cond"))
    copy_step = function.append_block("copy_step")
    copy_step.emit("next_copy_scan", "add", " i64 ", function.local("copy_scan"), ", 1")
    copy_step.emit(
        None,
        "store",
        " i64 ",
        function.local("next_copy_scan"),
        ", ptr ",
        function.local("copy_scan_ptr"),
    )
    copy_step.emit(None, "br", " label ", function.local("copy_cond"))
    copy_final = function.append_block("copy_final")
    copy_final.emit("final_start", "load", " i64, ptr ", function.local("start_ptr"))
    copy_final.emit(
        "final_len", "sub", " i64 ", function.local("text_len"), ", ", function.local("final_start")
    )
    copy_final.emit("final_bytes", "add", " i64 ", function.local("final_len"), ", 1")
    copy_final.emit(
        "final_part",
        "call",
        " ptr ",
        module.symbol("malloc"),
        "(i64 ",
        function.local("final_bytes"),
        ")",
    )
    copy_final.emit(
        "final_source",
        "getelementptr",
        " i8, ptr ",
        function.local("text"),
        ", i64 ",
        function.local("final_start"),
    )
    copy_final.emit(
        "final_copied",
        "call",
        " ptr ",
        module.symbol("memcpy"),
        "(ptr ",
        function.local("final_part"),
        ", ptr ",
        function.local("final_source"),
        ", i64 ",
        function.local("final_len"),
        ")",
    )
    copy_final.emit(
        "final_nul",
        "getelementptr",
        " i8, ptr ",
        function.local("final_part"),
        ", i64 ",
        function.local("final_len"),
    )
    copy_final.emit(None, "store", " i8 0, ptr ", function.local("final_nul"))
    copy_final.emit("final_index", "load", " i64, ptr ", function.local("copy_part_ptr"))
    copy_final.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_tuple_set"),
        "(ptr ",
        function.local("tuple"),
        ", i64 ",
        function.local("final_index"),
        ", ptr ",
        function.local("final_part"),
        ")",
    )
    copy_final.emit(None, "ret", " ptr ", function.local("tuple"))


def _build___xcc_aot_string_rsplit_limit(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_string_rsplit_limit")
    entry = function.append_block("entry")
    entry.emit("text_null", "icmp", " eq ptr ", function.local("text"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("text_null"),
        ", label ",
        function.local("empty"),
        ", label ",
        function.local("check_sep"),
    )
    empty = function.append_block("empty")
    empty.emit("empty_tuple", "call", " ptr ", module.symbol("__xcc_aot_tuple_new"), "(i64 0)")
    empty.emit(None, "ret", " ptr ", function.local("empty_tuple"))
    check_sep = function.append_block("check_sep")
    check_sep.emit(
        "sep_len", "call", " i64 ", module.symbol("strlen"), "(ptr ", function.local("sep"), ")"
    )
    check_sep.emit("sep_empty", "icmp", " eq i64 ", function.local("sep_len"), ", 0")
    check_sep.emit(
        None,
        "br",
        " i1 ",
        function.local("sep_empty"),
        ", label ",
        function.local("single"),
        ", label ",
        function.local("init"),
    )
    single = function.append_block("single")
    single.emit("single_tuple", "call", " ptr ", module.symbol("__xcc_aot_tuple_new"), "(i64 1)")
    single.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_tuple_set"),
        "(ptr ",
        function.local("single_tuple"),
        ", i64 0, ptr ",
        function.local("text"),
        ")",
    )
    single.emit(None, "ret", " ptr ", function.local("single_tuple"))
    init = function.append_block("init")
    init.emit(
        "text_len", "call", " i64 ", module.symbol("strlen"), "(ptr ", function.local("text"), ")"
    )
    init.emit("result_ptr", "alloca", " ptr")
    init.emit("end_ptr", "alloca", " i64")
    init.emit("remaining_ptr", "alloca", " i64")
    init.emit("initial", "call", " ptr ", module.symbol("__xcc_aot_tuple_new"), "(i64 0)")
    init.emit(
        None, "store", " ptr ", function.local("initial"), ", ptr ", function.local("result_ptr")
    )
    init.emit(
        None, "store", " i64 ", function.local("text_len"), ", ptr ", function.local("end_ptr")
    )
    init.emit(
        None,
        "store",
        " i64 ",
        function.local("maxsplit"),
        ", ptr ",
        function.local("remaining_ptr"),
    )
    init.emit(None, "br", " label ", function.local("loop"))
    loop = function.append_block("loop")
    loop.emit("end", "load", " i64, ptr ", function.local("end_ptr"))
    loop.emit("remaining", "load", " i64, ptr ", function.local("remaining_ptr"))
    loop.emit("limited", "icmp", " sge i64 ", function.local("maxsplit"), ", 0")
    loop.emit("no_remaining", "icmp", " eq i64 ", function.local("remaining"), ", 0")
    loop.emit(
        "out_of_splits",
        "and",
        " i1 ",
        function.local("limited"),
        ", ",
        function.local("no_remaining"),
    )
    loop.emit(
        None,
        "br",
        " i1 ",
        function.local("out_of_splits"),
        ", label ",
        function.local("finalize"),
        ", label ",
        function.local("search"),
    )
    search = function.append_block("search")
    search.emit("match", "call", " i64 ", module.symbol("__xcc_aot_string_rfind"), "(")
    search.continue_(
        "  ptr ",
        function.local("text"),
        ", ptr ",
        function.local("sep"),
        ", i64 0, i64 ",
        function.local("end"),
        ")",
    )
    search.emit("found", "icmp", " sge i64 ", function.local("match"), ", 0")
    search.emit(
        None,
        "br",
        " i1 ",
        function.local("found"),
        ", label ",
        function.local("split"),
        ", label ",
        function.local("finalize"),
    )
    split = function.append_block("split")
    split.emit(
        "piece_start", "add", " i64 ", function.local("match"), ", ", function.local("sep_len")
    )
    split.emit("piece", "call", " ptr ", module.symbol("__xcc_aot_string_slice"), "(")
    split.continue_(
        "  ptr ",
        function.local("text"),
        ", i64 ",
        function.local("piece_start"),
        ", i64 ",
        function.local("end"),
        ")",
    )
    split.emit("piece_tuple", "call", " ptr ", module.symbol("__xcc_aot_tuple_new"), "(i64 1)")
    split.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_tuple_set"),
        "(ptr ",
        function.local("piece_tuple"),
        ", i64 0, ptr ",
        function.local("piece"),
        ")",
    )
    split.emit("old_result", "load", " ptr, ptr ", function.local("result_ptr"))
    split.emit("new_result", "call", " ptr ", module.symbol("__xcc_aot_tuple_concat"), "(")
    split.continue_(
        "  ptr ", function.local("piece_tuple"), ", ptr ", function.local("old_result"), ")"
    )
    split.emit(
        None, "store", " ptr ", function.local("new_result"), ", ptr ", function.local("result_ptr")
    )
    split.emit(None, "store", " i64 ", function.local("match"), ", ptr ", function.local("end_ptr"))
    split.emit("decremented", "sub", " i64 ", function.local("remaining"), ", 1")
    split.emit(
        "next_remaining",
        "select",
        " i1 ",
        function.local("limited"),
        ", i64 ",
        function.local("decremented"),
        ", i64 ",
        function.local("remaining"),
    )
    split.emit(
        None,
        "store",
        " i64 ",
        function.local("next_remaining"),
        ", ptr ",
        function.local("remaining_ptr"),
    )
    split.emit(None, "br", " label ", function.local("loop"))
    finalize = function.append_block("finalize")
    finalize.emit("final_end", "load", " i64, ptr ", function.local("end_ptr"))
    finalize.emit("prefix", "call", " ptr ", module.symbol("__xcc_aot_string_slice"), "(")
    finalize.continue_(
        "  ptr ", function.local("text"), ", i64 0, i64 ", function.local("final_end"), ")"
    )
    finalize.emit("prefix_tuple", "call", " ptr ", module.symbol("__xcc_aot_tuple_new"), "(i64 1)")
    finalize.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_tuple_set"),
        "(ptr ",
        function.local("prefix_tuple"),
        ", i64 0, ptr ",
        function.local("prefix"),
        ")",
    )
    finalize.emit("suffixes", "load", " ptr, ptr ", function.local("result_ptr"))
    finalize.emit("result", "call", " ptr ", module.symbol("__xcc_aot_tuple_concat"), "(")
    finalize.continue_(
        "  ptr ", function.local("prefix_tuple"), ", ptr ", function.local("suffixes"), ")"
    )
    finalize.emit(None, "ret", " ptr ", function.local("result"))


def _build___xcc_aot_string_split_whitespace(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_string_split_whitespace")
    entry = function.append_block("entry")
    entry.emit("text_null", "icmp", " eq ptr ", function.local("text"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("text_null"),
        ", label ",
        function.local("empty"),
        ", label ",
        function.local("nonnull"),
    )
    empty = function.append_block("empty")
    empty.emit("empty_tuple", "call", " ptr ", module.symbol("__xcc_aot_tuple_new"), "(i64 0)")
    empty.emit(None, "ret", " ptr ", function.local("empty_tuple"))
    nonnull = function.append_block("nonnull")
    nonnull.emit(
        "text_len", "call", " i64 ", module.symbol("strlen"), "(ptr ", function.local("text"), ")"
    )
    nonnull.emit("max_unlimited", "icmp", " slt i64 ", function.local("maxsplit"), ", 0")
    nonnull.emit("count_ptr", "alloca", " i64")
    nonnull.emit("split_ptr", "alloca", " i64")
    nonnull.emit("index_ptr", "alloca", " i64")
    nonnull.emit(None, "store", " i64 0, ptr ", function.local("count_ptr"))
    nonnull.emit(None, "store", " i64 0, ptr ", function.local("split_ptr"))
    nonnull.emit(None, "store", " i64 0, ptr ", function.local("index_ptr"))
    nonnull.emit(None, "br", " label ", function.local("count_skip_cond"))
    count_skip_cond = function.append_block("count_skip_cond")
    count_skip_cond.emit("skip_index", "load", " i64, ptr ", function.local("index_ptr"))
    count_skip_cond.emit(
        "skip_done",
        "icmp",
        " uge i64 ",
        function.local("skip_index"),
        ", ",
        function.local("text_len"),
    )
    count_skip_cond.emit(
        None,
        "br",
        " i1 ",
        function.local("skip_done"),
        ", label ",
        function.local("alloc"),
        ", label ",
        function.local("count_skip_check"),
    )
    count_skip_check = function.append_block("count_skip_check")
    count_skip_check.emit(
        "skip_char_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("text"),
        ", i64 ",
        function.local("skip_index"),
    )
    count_skip_check.emit("skip_char", "load", " i8, ptr ", function.local("skip_char_ptr"))
    count_skip_check.emit(
        "skip_space",
        "call",
        " i1 ",
        module.symbol("__xcc_aot_is_ascii_space"),
        "(i8 ",
        function.local("skip_char"),
        ")",
    )
    count_skip_check.emit(
        None,
        "br",
        " i1 ",
        function.local("skip_space"),
        ", label ",
        function.local("count_skip_step"),
        ", label ",
        function.local("count_part"),
    )
    count_skip_step = function.append_block("count_skip_step")
    count_skip_step.emit("skip_next", "add", " i64 ", function.local("skip_index"), ", 1")
    count_skip_step.emit(
        None, "store", " i64 ", function.local("skip_next"), ", ptr ", function.local("index_ptr")
    )
    count_skip_step.emit(None, "br", " label ", function.local("count_skip_cond"))
    count_part = function.append_block("count_part")
    count_part.emit("old_count", "load", " i64, ptr ", function.local("count_ptr"))
    count_part.emit("new_count", "add", " i64 ", function.local("old_count"), ", 1")
    count_part.emit(
        None, "store", " i64 ", function.local("new_count"), ", ptr ", function.local("count_ptr")
    )
    count_part.emit(None, "br", " label ", function.local("count_scan_cond"))
    count_scan_cond = function.append_block("count_scan_cond")
    count_scan_cond.emit("scan", "load", " i64, ptr ", function.local("index_ptr"))
    count_scan_cond.emit(
        "scan_done", "icmp", " uge i64 ", function.local("scan"), ", ", function.local("text_len")
    )
    count_scan_cond.emit(
        None,
        "br",
        " i1 ",
        function.local("scan_done"),
        ", label ",
        function.local("alloc"),
        ", label ",
        function.local("count_scan_check"),
    )
    count_scan_check = function.append_block("count_scan_check")
    count_scan_check.emit(
        "scan_char_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("text"),
        ", i64 ",
        function.local("scan"),
    )
    count_scan_check.emit("scan_char", "load", " i8, ptr ", function.local("scan_char_ptr"))
    count_scan_check.emit(
        "scan_space",
        "call",
        " i1 ",
        module.symbol("__xcc_aot_is_ascii_space"),
        "(i8 ",
        function.local("scan_char"),
        ")",
    )
    count_scan_check.emit(
        None,
        "br",
        " i1 ",
        function.local("scan_space"),
        ", label ",
        function.local("count_space"),
        ", label ",
        function.local("count_scan_step"),
    )
    count_space = function.append_block("count_space")
    count_space.emit("split_count", "load", " i64, ptr ", function.local("split_ptr"))
    count_space.emit(
        "under_max",
        "icmp",
        " slt i64 ",
        function.local("split_count"),
        ", ",
        function.local("maxsplit"),
    )
    count_space.emit(
        "can_split",
        "or",
        " i1 ",
        function.local("max_unlimited"),
        ", ",
        function.local("under_max"),
    )
    count_space.emit(
        None,
        "br",
        " i1 ",
        function.local("can_split"),
        ", label ",
        function.local("count_split"),
        ", label ",
        function.local("count_scan_step"),
    )
    count_split = function.append_block("count_split")
    count_split.emit("next_split", "add", " i64 ", function.local("split_count"), ", 1")
    count_split.emit(
        None, "store", " i64 ", function.local("next_split"), ", ptr ", function.local("split_ptr")
    )
    count_split.emit("after_split", "add", " i64 ", function.local("scan"), ", 1")
    count_split.emit(
        None, "store", " i64 ", function.local("after_split"), ", ptr ", function.local("index_ptr")
    )
    count_split.emit(None, "br", " label ", function.local("count_skip_cond"))
    count_scan_step = function.append_block("count_scan_step")
    count_scan_step.emit("next_scan", "add", " i64 ", function.local("scan"), ", 1")
    count_scan_step.emit(
        None, "store", " i64 ", function.local("next_scan"), ", ptr ", function.local("index_ptr")
    )
    count_scan_step.emit(None, "br", " label ", function.local("count_scan_cond"))
    alloc = function.append_block("alloc")
    alloc.emit("part_count", "load", " i64, ptr ", function.local("count_ptr"))
    alloc.emit(
        "tuple",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_new"),
        "(i64 ",
        function.local("part_count"),
        ")",
    )
    alloc.emit("copy_index_ptr", "alloca", " i64")
    alloc.emit("copy_start_ptr", "alloca", " i64")
    alloc.emit("copy_part_ptr", "alloca", " i64")
    alloc.emit("copy_split_ptr", "alloca", " i64")
    alloc.emit(None, "store", " i64 0, ptr ", function.local("copy_index_ptr"))
    alloc.emit(None, "store", " i64 0, ptr ", function.local("copy_start_ptr"))
    alloc.emit(None, "store", " i64 0, ptr ", function.local("copy_part_ptr"))
    alloc.emit(None, "store", " i64 0, ptr ", function.local("copy_split_ptr"))
    alloc.emit(None, "br", " label ", function.local("copy_skip_cond"))
    copy_skip_cond = function.append_block("copy_skip_cond")
    copy_skip_cond.emit("copy_skip_index", "load", " i64, ptr ", function.local("copy_index_ptr"))
    copy_skip_cond.emit(
        "copy_skip_done",
        "icmp",
        " uge i64 ",
        function.local("copy_skip_index"),
        ", ",
        function.local("text_len"),
    )
    copy_skip_cond.emit(
        None,
        "br",
        " i1 ",
        function.local("copy_skip_done"),
        ", label ",
        function.local("done"),
        ", label ",
        function.local("copy_skip_check"),
    )
    copy_skip_check = function.append_block("copy_skip_check")
    copy_skip_check.emit(
        "copy_skip_char_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("text"),
        ", i64 ",
        function.local("copy_skip_index"),
    )
    copy_skip_check.emit(
        "copy_skip_char", "load", " i8, ptr ", function.local("copy_skip_char_ptr")
    )
    copy_skip_check.emit(
        "copy_skip_space",
        "call",
        " i1 ",
        module.symbol("__xcc_aot_is_ascii_space"),
        "(i8 ",
        function.local("copy_skip_char"),
        ")",
    )
    copy_skip_check.emit(
        None,
        "br",
        " i1 ",
        function.local("copy_skip_space"),
        ", label ",
        function.local("copy_skip_step"),
        ", label ",
        function.local("copy_part_start"),
    )
    copy_skip_step = function.append_block("copy_skip_step")
    copy_skip_step.emit("copy_skip_next", "add", " i64 ", function.local("copy_skip_index"), ", 1")
    copy_skip_step.emit(
        None,
        "store",
        " i64 ",
        function.local("copy_skip_next"),
        ", ptr ",
        function.local("copy_index_ptr"),
    )
    copy_skip_step.emit(None, "br", " label ", function.local("copy_skip_cond"))
    copy_part_start = function.append_block("copy_part_start")
    copy_part_start.emit(
        None,
        "store",
        " i64 ",
        function.local("copy_skip_index"),
        ", ptr ",
        function.local("copy_start_ptr"),
    )
    copy_part_start.emit(None, "br", " label ", function.local("copy_scan_cond"))
    copy_scan_cond = function.append_block("copy_scan_cond")
    copy_scan_cond.emit("copy_scan", "load", " i64, ptr ", function.local("copy_index_ptr"))
    copy_scan_cond.emit(
        "copy_scan_done",
        "icmp",
        " uge i64 ",
        function.local("copy_scan"),
        ", ",
        function.local("text_len"),
    )
    copy_scan_cond.emit(
        None,
        "br",
        " i1 ",
        function.local("copy_scan_done"),
        ", label ",
        function.local("copy_final"),
        ", label ",
        function.local("copy_scan_check"),
    )
    copy_scan_check = function.append_block("copy_scan_check")
    copy_scan_check.emit(
        "copy_scan_char_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("text"),
        ", i64 ",
        function.local("copy_scan"),
    )
    copy_scan_check.emit(
        "copy_scan_char", "load", " i8, ptr ", function.local("copy_scan_char_ptr")
    )
    copy_scan_check.emit(
        "copy_scan_space",
        "call",
        " i1 ",
        module.symbol("__xcc_aot_is_ascii_space"),
        "(i8 ",
        function.local("copy_scan_char"),
        ")",
    )
    copy_scan_check.emit(
        None,
        "br",
        " i1 ",
        function.local("copy_scan_space"),
        ", label ",
        function.local("copy_space"),
        ", label ",
        function.local("copy_scan_step"),
    )
    copy_space = function.append_block("copy_space")
    copy_space.emit("copy_split_count", "load", " i64, ptr ", function.local("copy_split_ptr"))
    copy_space.emit(
        "copy_under_max",
        "icmp",
        " slt i64 ",
        function.local("copy_split_count"),
        ", ",
        function.local("maxsplit"),
    )
    copy_space.emit(
        "copy_can_split",
        "or",
        " i1 ",
        function.local("max_unlimited"),
        ", ",
        function.local("copy_under_max"),
    )
    copy_space.emit(
        None,
        "br",
        " i1 ",
        function.local("copy_can_split"),
        ", label ",
        function.local("copy_emit_split"),
        ", label ",
        function.local("copy_scan_step"),
    )
    copy_emit_split = function.append_block("copy_emit_split")
    copy_emit_split.emit("split_start", "load", " i64, ptr ", function.local("copy_start_ptr"))
    copy_emit_split.emit(
        "split_len",
        "sub",
        " i64 ",
        function.local("copy_scan"),
        ", ",
        function.local("split_start"),
    )
    copy_emit_split.emit("split_bytes", "add", " i64 ", function.local("split_len"), ", 1")
    copy_emit_split.emit(
        "split_text",
        "call",
        " ptr ",
        module.symbol("malloc"),
        "(i64 ",
        function.local("split_bytes"),
        ")",
    )
    copy_emit_split.emit(
        "split_source",
        "getelementptr",
        " i8, ptr ",
        function.local("text"),
        ", i64 ",
        function.local("split_start"),
    )
    copy_emit_split.emit(
        "split_copied",
        "call",
        " ptr ",
        module.symbol("memcpy"),
        "(ptr ",
        function.local("split_text"),
        ", ptr ",
        function.local("split_source"),
        ", i64 ",
        function.local("split_len"),
        ")",
    )
    copy_emit_split.emit(
        "split_nul",
        "getelementptr",
        " i8, ptr ",
        function.local("split_text"),
        ", i64 ",
        function.local("split_len"),
    )
    copy_emit_split.emit(None, "store", " i8 0, ptr ", function.local("split_nul"))
    copy_emit_split.emit("split_part", "load", " i64, ptr ", function.local("copy_part_ptr"))
    copy_emit_split.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_tuple_set"),
        "(ptr ",
        function.local("tuple"),
        ", i64 ",
        function.local("split_part"),
        ", ptr ",
        function.local("split_text"),
        ")",
    )
    copy_emit_split.emit("next_copy_part", "add", " i64 ", function.local("split_part"), ", 1")
    copy_emit_split.emit(
        None,
        "store",
        " i64 ",
        function.local("next_copy_part"),
        ", ptr ",
        function.local("copy_part_ptr"),
    )
    copy_emit_split.emit(
        "next_copy_split", "add", " i64 ", function.local("copy_split_count"), ", 1"
    )
    copy_emit_split.emit(
        None,
        "store",
        " i64 ",
        function.local("next_copy_split"),
        ", ptr ",
        function.local("copy_split_ptr"),
    )
    copy_emit_split.emit("after_copy_split", "add", " i64 ", function.local("copy_scan"), ", 1")
    copy_emit_split.emit(
        None,
        "store",
        " i64 ",
        function.local("after_copy_split"),
        ", ptr ",
        function.local("copy_index_ptr"),
    )
    copy_emit_split.emit(None, "br", " label ", function.local("copy_skip_cond"))
    copy_scan_step = function.append_block("copy_scan_step")
    copy_scan_step.emit("next_copy_scan", "add", " i64 ", function.local("copy_scan"), ", 1")
    copy_scan_step.emit(
        None,
        "store",
        " i64 ",
        function.local("next_copy_scan"),
        ", ptr ",
        function.local("copy_index_ptr"),
    )
    copy_scan_step.emit(None, "br", " label ", function.local("copy_scan_cond"))
    copy_final = function.append_block("copy_final")
    copy_final.emit("final_start", "load", " i64, ptr ", function.local("copy_start_ptr"))
    copy_final.emit(
        "final_len", "sub", " i64 ", function.local("text_len"), ", ", function.local("final_start")
    )
    copy_final.emit("final_bytes", "add", " i64 ", function.local("final_len"), ", 1")
    copy_final.emit(
        "final_text",
        "call",
        " ptr ",
        module.symbol("malloc"),
        "(i64 ",
        function.local("final_bytes"),
        ")",
    )
    copy_final.emit(
        "final_source",
        "getelementptr",
        " i8, ptr ",
        function.local("text"),
        ", i64 ",
        function.local("final_start"),
    )
    copy_final.emit(
        "final_copied",
        "call",
        " ptr ",
        module.symbol("memcpy"),
        "(ptr ",
        function.local("final_text"),
        ", ptr ",
        function.local("final_source"),
        ", i64 ",
        function.local("final_len"),
        ")",
    )
    copy_final.emit(
        "final_nul",
        "getelementptr",
        " i8, ptr ",
        function.local("final_text"),
        ", i64 ",
        function.local("final_len"),
    )
    copy_final.emit(None, "store", " i8 0, ptr ", function.local("final_nul"))
    copy_final.emit("final_part", "load", " i64, ptr ", function.local("copy_part_ptr"))
    copy_final.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_tuple_set"),
        "(ptr ",
        function.local("tuple"),
        ", i64 ",
        function.local("final_part"),
        ", ptr ",
        function.local("final_text"),
        ")",
    )
    copy_final.emit(None, "br", " label ", function.local("done"))
    done = function.append_block("done")
    done.emit(None, "ret", " ptr ", function.local("tuple"))


def _build___xcc_aot_string_splitlines(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_string_splitlines")
    entry = function.append_block("entry")
    entry.emit("text_null", "icmp", " eq ptr ", function.local("text"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("text_null"),
        ", label ",
        function.local("empty"),
        ", label ",
        function.local("nonnull"),
    )
    empty = function.append_block("empty")
    empty.emit("empty_tuple", "call", " ptr ", module.symbol("__xcc_aot_tuple_new"), "(i64 0)")
    empty.emit(None, "ret", " ptr ", function.local("empty_tuple"))
    nonnull = function.append_block("nonnull")
    nonnull.emit(
        "text_len", "call", " i64 ", module.symbol("strlen"), "(ptr ", function.local("text"), ")"
    )
    nonnull.emit("is_empty", "icmp", " eq i64 ", function.local("text_len"), ", 0")
    nonnull.emit(
        None,
        "br",
        " i1 ",
        function.local("is_empty"),
        ", label ",
        function.local("empty"),
        ", label ",
        function.local("count_init"),
    )
    count_init = function.append_block("count_init")
    count_init.emit("count_ptr", "alloca", " i64")
    count_init.emit("scan_ptr", "alloca", " i64")
    count_init.emit(None, "store", " i64 1, ptr ", function.local("count_ptr"))
    count_init.emit(None, "store", " i64 0, ptr ", function.local("scan_ptr"))
    count_init.emit(None, "br", " label ", function.local("count_cond"))
    count_cond = function.append_block("count_cond")
    count_cond.emit("scan", "load", " i64, ptr ", function.local("scan_ptr"))
    count_cond.emit(
        "count_done", "icmp", " uge i64 ", function.local("scan"), ", ", function.local("text_len")
    )
    count_cond.emit(
        None,
        "br",
        " i1 ",
        function.local("count_done"),
        ", label ",
        function.local("alloc"),
        ", label ",
        function.local("count_body"),
    )
    count_body = function.append_block("count_body")
    count_body.emit(
        "char_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("text"),
        ", i64 ",
        function.local("scan"),
    )
    count_body.emit("char", "load", " i8, ptr ", function.local("char_ptr"))
    count_body.emit("is_lf", "icmp", " eq i8 ", function.local("char"), ", 10")
    count_body.emit(
        None,
        "br",
        " i1 ",
        function.local("is_lf"),
        ", label ",
        function.local("count_lf"),
        ", label ",
        function.local("count_next"),
    )
    count_lf = function.append_block("count_lf")
    count_lf.emit("after_lf", "add", " i64 ", function.local("scan"), ", 1")
    count_lf.emit(
        "has_more",
        "icmp",
        " ult i64 ",
        function.local("after_lf"),
        ", ",
        function.local("text_len"),
    )
    count_lf.emit(
        None,
        "br",
        " i1 ",
        function.local("has_more"),
        ", label ",
        function.local("count_inc"),
        ", label ",
        function.local("count_store_next"),
    )
    count_inc = function.append_block("count_inc")
    count_inc.emit("old_count", "load", " i64, ptr ", function.local("count_ptr"))
    count_inc.emit("new_count", "add", " i64 ", function.local("old_count"), ", 1")
    count_inc.emit(
        None, "store", " i64 ", function.local("new_count"), ", ptr ", function.local("count_ptr")
    )
    count_inc.emit(None, "br", " label ", function.local("count_store_next"))
    count_store_next = function.append_block("count_store_next")
    count_store_next.emit(
        None, "store", " i64 ", function.local("after_lf"), ", ptr ", function.local("scan_ptr")
    )
    count_store_next.emit(None, "br", " label ", function.local("count_cond"))
    count_next = function.append_block("count_next")
    count_next.emit("next_scan", "add", " i64 ", function.local("scan"), ", 1")
    count_next.emit(
        None, "store", " i64 ", function.local("next_scan"), ", ptr ", function.local("scan_ptr")
    )
    count_next.emit(None, "br", " label ", function.local("count_cond"))
    alloc = function.append_block("alloc")
    alloc.emit("part_count", "load", " i64, ptr ", function.local("count_ptr"))
    alloc.emit(
        "tuple",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_new"),
        "(i64 ",
        function.local("part_count"),
        ")",
    )
    alloc.emit("start_ptr", "alloca", " i64")
    alloc.emit("index_ptr", "alloca", " i64")
    alloc.emit("part_ptr", "alloca", " i64")
    alloc.emit(None, "store", " i64 0, ptr ", function.local("start_ptr"))
    alloc.emit(None, "store", " i64 0, ptr ", function.local("index_ptr"))
    alloc.emit(None, "store", " i64 0, ptr ", function.local("part_ptr"))
    alloc.emit(None, "br", " label ", function.local("copy_cond"))
    copy_cond = function.append_block("copy_cond")
    copy_cond.emit("index", "load", " i64, ptr ", function.local("index_ptr"))
    copy_cond.emit(
        "at_end", "icmp", " eq i64 ", function.local("index"), ", ", function.local("text_len")
    )
    copy_cond.emit(
        None,
        "br",
        " i1 ",
        function.local("at_end"),
        ", label ",
        function.local("copy_final_check"),
        ", label ",
        function.local("copy_check_lf"),
    )
    copy_check_lf = function.append_block("copy_check_lf")
    copy_check_lf.emit(
        "copy_char_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("text"),
        ", i64 ",
        function.local("index"),
    )
    copy_check_lf.emit("copy_char", "load", " i8, ptr ", function.local("copy_char_ptr"))
    copy_check_lf.emit("copy_is_lf", "icmp", " eq i8 ", function.local("copy_char"), ", 10")
    copy_check_lf.emit(
        None,
        "br",
        " i1 ",
        function.local("copy_is_lf"),
        ", label ",
        function.local("copy_line"),
        ", label ",
        function.local("copy_next"),
    )
    copy_line = function.append_block("copy_line")
    copy_line.emit("line_start", "load", " i64, ptr ", function.local("start_ptr"))
    copy_line.emit(
        "base_len", "sub", " i64 ", function.local("index"), ", ", function.local("line_start")
    )
    copy_line.emit("keep_len", "add", " i64 ", function.local("base_len"), ", 1")
    copy_line.emit(
        "line_len",
        "select",
        " i1 ",
        function.local("keepends"),
        ", i64 ",
        function.local("keep_len"),
        ", i64 ",
        function.local("base_len"),
    )
    copy_line.emit("line_bytes", "add", " i64 ", function.local("line_len"), ", 1")
    copy_line.emit(
        "line", "call", " ptr ", module.symbol("malloc"), "(i64 ", function.local("line_bytes"), ")"
    )
    copy_line.emit(
        "line_source",
        "getelementptr",
        " i8, ptr ",
        function.local("text"),
        ", i64 ",
        function.local("line_start"),
    )
    copy_line.emit(
        "line_copied",
        "call",
        " ptr ",
        module.symbol("memcpy"),
        "(ptr ",
        function.local("line"),
        ", ptr ",
        function.local("line_source"),
        ", i64 ",
        function.local("line_len"),
        ")",
    )
    copy_line.emit(
        "line_nul",
        "getelementptr",
        " i8, ptr ",
        function.local("line"),
        ", i64 ",
        function.local("line_len"),
    )
    copy_line.emit(None, "store", " i8 0, ptr ", function.local("line_nul"))
    copy_line.emit("line_part", "load", " i64, ptr ", function.local("part_ptr"))
    copy_line.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_tuple_set"),
        "(ptr ",
        function.local("tuple"),
        ", i64 ",
        function.local("line_part"),
        ", ptr ",
        function.local("line"),
        ")",
    )
    copy_line.emit("next_line_part", "add", " i64 ", function.local("line_part"), ", 1")
    copy_line.emit(
        None,
        "store",
        " i64 ",
        function.local("next_line_part"),
        ", ptr ",
        function.local("part_ptr"),
    )
    copy_line.emit("next_start", "add", " i64 ", function.local("index"), ", 1")
    copy_line.emit(
        None, "store", " i64 ", function.local("next_start"), ", ptr ", function.local("start_ptr")
    )
    copy_line.emit(
        None, "store", " i64 ", function.local("next_start"), ", ptr ", function.local("index_ptr")
    )
    copy_line.emit(None, "br", " label ", function.local("copy_cond"))
    copy_next = function.append_block("copy_next")
    copy_next.emit("next_index", "add", " i64 ", function.local("index"), ", 1")
    copy_next.emit(
        None, "store", " i64 ", function.local("next_index"), ", ptr ", function.local("index_ptr")
    )
    copy_next.emit(None, "br", " label ", function.local("copy_cond"))
    copy_final_check = function.append_block("copy_final_check")
    copy_final_check.emit("final_start_check", "load", " i64, ptr ", function.local("start_ptr"))
    copy_final_check.emit(
        "final_empty",
        "icmp",
        " eq i64 ",
        function.local("final_start_check"),
        ", ",
        function.local("text_len"),
    )
    copy_final_check.emit(
        None,
        "br",
        " i1 ",
        function.local("final_empty"),
        ", label ",
        function.local("done"),
        ", label ",
        function.local("copy_final"),
    )
    copy_final = function.append_block("copy_final")
    copy_final.emit("final_start", "load", " i64, ptr ", function.local("start_ptr"))
    copy_final.emit(
        "final_len", "sub", " i64 ", function.local("text_len"), ", ", function.local("final_start")
    )
    copy_final.emit("final_bytes", "add", " i64 ", function.local("final_len"), ", 1")
    copy_final.emit(
        "final_line",
        "call",
        " ptr ",
        module.symbol("malloc"),
        "(i64 ",
        function.local("final_bytes"),
        ")",
    )
    copy_final.emit(
        "final_source",
        "getelementptr",
        " i8, ptr ",
        function.local("text"),
        ", i64 ",
        function.local("final_start"),
    )
    copy_final.emit(
        "final_copied",
        "call",
        " ptr ",
        module.symbol("memcpy"),
        "(ptr ",
        function.local("final_line"),
        ", ptr ",
        function.local("final_source"),
        ", i64 ",
        function.local("final_len"),
        ")",
    )
    copy_final.emit(
        "final_nul",
        "getelementptr",
        " i8, ptr ",
        function.local("final_line"),
        ", i64 ",
        function.local("final_len"),
    )
    copy_final.emit(None, "store", " i8 0, ptr ", function.local("final_nul"))
    copy_final.emit("final_part", "load", " i64, ptr ", function.local("part_ptr"))
    copy_final.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_tuple_set"),
        "(ptr ",
        function.local("tuple"),
        ", i64 ",
        function.local("final_part"),
        ", ptr ",
        function.local("final_line"),
        ")",
    )
    copy_final.emit(None, "br", " label ", function.local("done"))
    done = function.append_block("done")
    done.emit(None, "ret", " ptr ", function.local("tuple"))


def _build___xcc_aot_string_replace(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_string_replace")
    entry = function.append_block("entry")
    entry.emit("text_null", "icmp", " eq ptr ", function.local("text"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("text_null"),
        ", label ",
        function.local("empty"),
        ", label ",
        function.local("check_old"),
    )
    empty = function.append_block("empty")
    empty.emit("empty_text", "call", " ptr ", module.symbol("__xcc_aot_zero_bytes"), "(i64 0)")
    empty.emit(None, "ret", " ptr ", function.local("empty_text"))
    check_old = function.append_block("check_old")
    check_old.emit(
        "old_len", "call", " i64 ", module.symbol("strlen"), "(ptr ", function.local("old"), ")"
    )
    check_old.emit("old_empty", "icmp", " eq i64 ", function.local("old_len"), ", 0")
    check_old.emit(
        None,
        "br",
        " i1 ",
        function.local("old_empty"),
        ", label ",
        function.local("return_input"),
        ", label ",
        function.local("count_init"),
    )
    return_input = function.append_block("return_input")
    return_input.emit(None, "ret", " ptr ", function.local("text"))
    count_init = function.append_block("count_init")
    count_init.emit(
        "text_len", "call", " i64 ", module.symbol("strlen"), "(ptr ", function.local("text"), ")"
    )
    count_init.emit(
        "new_len", "call", " i64 ", module.symbol("strlen"), "(ptr ", function.local("new"), ")"
    )
    count_init.emit("count_ptr", "alloca", " i64")
    count_init.emit("scan_ptr", "alloca", " i64")
    count_init.emit(None, "store", " i64 0, ptr ", function.local("count_ptr"))
    count_init.emit(None, "store", " i64 0, ptr ", function.local("scan_ptr"))
    count_init.emit(None, "br", " label ", function.local("count_cond"))
    count_cond = function.append_block("count_cond")
    count_cond.emit("scan", "load", " i64, ptr ", function.local("scan_ptr"))
    count_cond.emit(
        "count_done", "icmp", " uge i64 ", function.local("scan"), ", ", function.local("text_len")
    )
    count_cond.emit(
        None,
        "br",
        " i1 ",
        function.local("count_done"),
        ", label ",
        function.local("check_count"),
        ", label ",
        function.local("count_check_fit"),
    )
    count_check_fit = function.append_block("count_check_fit")
    count_check_fit.emit(
        "remaining", "sub", " i64 ", function.local("text_len"), ", ", function.local("scan")
    )
    count_check_fit.emit(
        "fits", "icmp", " ule i64 ", function.local("old_len"), ", ", function.local("remaining")
    )
    count_check_fit.emit(
        None,
        "br",
        " i1 ",
        function.local("fits"),
        ", label ",
        function.local("count_compare"),
        ", label ",
        function.local("count_step_one"),
    )
    count_compare = function.append_block("count_compare")
    count_compare.emit(
        "scan_text",
        "getelementptr",
        " i8, ptr ",
        function.local("text"),
        ", i64 ",
        function.local("scan"),
    )
    count_compare.emit(
        "cmp",
        "call",
        " i32 ",
        module.symbol("strncmp"),
        "(ptr ",
        function.local("scan_text"),
        ", ptr ",
        function.local("old"),
        ", i64 ",
        function.local("old_len"),
        ")",
    )
    count_compare.emit("match", "icmp", " eq i32 ", function.local("cmp"), ", 0")
    count_compare.emit(
        None,
        "br",
        " i1 ",
        function.local("match"),
        ", label ",
        function.local("count_match"),
        ", label ",
        function.local("count_step_one"),
    )
    count_match = function.append_block("count_match")
    count_match.emit("old_count", "load", " i64, ptr ", function.local("count_ptr"))
    count_match.emit("new_count", "add", " i64 ", function.local("old_count"), ", 1")
    count_match.emit(
        None, "store", " i64 ", function.local("new_count"), ", ptr ", function.local("count_ptr")
    )
    count_match.emit(
        "after_match", "add", " i64 ", function.local("scan"), ", ", function.local("old_len")
    )
    count_match.emit(
        None, "store", " i64 ", function.local("after_match"), ", ptr ", function.local("scan_ptr")
    )
    count_match.emit(None, "br", " label ", function.local("count_cond"))
    count_step_one = function.append_block("count_step_one")
    count_step_one.emit("next_scan", "add", " i64 ", function.local("scan"), ", 1")
    count_step_one.emit(
        None, "store", " i64 ", function.local("next_scan"), ", ptr ", function.local("scan_ptr")
    )
    count_step_one.emit(None, "br", " label ", function.local("count_cond"))
    check_count = function.append_block("check_count")
    check_count.emit("count", "load", " i64, ptr ", function.local("count_ptr"))
    check_count.emit("no_matches", "icmp", " eq i64 ", function.local("count"), ", 0")
    check_count.emit(
        None,
        "br",
        " i1 ",
        function.local("no_matches"),
        ", label ",
        function.local("return_input"),
        ", label ",
        function.local("allocate_output"),
    )
    allocate_output = function.append_block("allocate_output")
    allocate_output.emit(
        "len_delta", "sub", " i64 ", function.local("new_len"), ", ", function.local("old_len")
    )
    allocate_output.emit(
        "total_delta", "mul", " i64 ", function.local("count"), ", ", function.local("len_delta")
    )
    allocate_output.emit(
        "out_len", "add", " i64 ", function.local("text_len"), ", ", function.local("total_delta")
    )
    allocate_output.emit("out_bytes", "add", " i64 ", function.local("out_len"), ", 1")
    allocate_output.emit(
        "out", "call", " ptr ", module.symbol("malloc"), "(i64 ", function.local("out_bytes"), ")"
    )
    allocate_output.emit("src_ptr", "alloca", " i64")
    allocate_output.emit("dst_ptr", "alloca", " i64")
    allocate_output.emit(None, "store", " i64 0, ptr ", function.local("src_ptr"))
    allocate_output.emit(None, "store", " i64 0, ptr ", function.local("dst_ptr"))
    allocate_output.emit(None, "br", " label ", function.local("copy_cond"))
    copy_cond = function.append_block("copy_cond")
    copy_cond.emit("src", "load", " i64, ptr ", function.local("src_ptr"))
    copy_cond.emit(
        "copy_done", "icmp", " uge i64 ", function.local("src"), ", ", function.local("text_len")
    )
    copy_cond.emit(
        None,
        "br",
        " i1 ",
        function.local("copy_done"),
        ", label ",
        function.local("done"),
        ", label ",
        function.local("copy_check_fit"),
    )
    copy_check_fit = function.append_block("copy_check_fit")
    copy_check_fit.emit(
        "copy_remaining", "sub", " i64 ", function.local("text_len"), ", ", function.local("src")
    )
    copy_check_fit.emit(
        "copy_fits",
        "icmp",
        " ule i64 ",
        function.local("old_len"),
        ", ",
        function.local("copy_remaining"),
    )
    copy_check_fit.emit(
        None,
        "br",
        " i1 ",
        function.local("copy_fits"),
        ", label ",
        function.local("copy_compare"),
        ", label ",
        function.local("copy_char"),
    )
    copy_compare = function.append_block("copy_compare")
    copy_compare.emit(
        "copy_source",
        "getelementptr",
        " i8, ptr ",
        function.local("text"),
        ", i64 ",
        function.local("src"),
    )
    copy_compare.emit(
        "copy_cmp",
        "call",
        " i32 ",
        module.symbol("strncmp"),
        "(ptr ",
        function.local("copy_source"),
        ", ptr ",
        function.local("old"),
        ", i64 ",
        function.local("old_len"),
        ")",
    )
    copy_compare.emit("copy_match", "icmp", " eq i32 ", function.local("copy_cmp"), ", 0")
    copy_compare.emit(
        None,
        "br",
        " i1 ",
        function.local("copy_match"),
        ", label ",
        function.local("copy_replace"),
        ", label ",
        function.local("copy_char"),
    )
    copy_replace = function.append_block("copy_replace")
    copy_replace.emit("dst_replace", "load", " i64, ptr ", function.local("dst_ptr"))
    copy_replace.emit(
        "replace_dst",
        "getelementptr",
        " i8, ptr ",
        function.local("out"),
        ", i64 ",
        function.local("dst_replace"),
    )
    copy_replace.emit(
        "replace_copy",
        "call",
        " ptr ",
        module.symbol("memcpy"),
        "(ptr ",
        function.local("replace_dst"),
        ", ptr ",
        function.local("new"),
        ", i64 ",
        function.local("new_len"),
        ")",
    )
    copy_replace.emit(
        "next_src_replace", "add", " i64 ", function.local("src"), ", ", function.local("old_len")
    )
    copy_replace.emit(
        "next_dst_replace",
        "add",
        " i64 ",
        function.local("dst_replace"),
        ", ",
        function.local("new_len"),
    )
    copy_replace.emit(
        None,
        "store",
        " i64 ",
        function.local("next_src_replace"),
        ", ptr ",
        function.local("src_ptr"),
    )
    copy_replace.emit(
        None,
        "store",
        " i64 ",
        function.local("next_dst_replace"),
        ", ptr ",
        function.local("dst_ptr"),
    )
    copy_replace.emit(None, "br", " label ", function.local("copy_cond"))
    copy_char = function.append_block("copy_char")
    copy_char.emit("dst_char", "load", " i64, ptr ", function.local("dst_ptr"))
    copy_char.emit(
        "char_source",
        "getelementptr",
        " i8, ptr ",
        function.local("text"),
        ", i64 ",
        function.local("src"),
    )
    copy_char.emit("char", "load", " i8, ptr ", function.local("char_source"))
    copy_char.emit(
        "char_dst",
        "getelementptr",
        " i8, ptr ",
        function.local("out"),
        ", i64 ",
        function.local("dst_char"),
    )
    copy_char.emit(
        None, "store", " i8 ", function.local("char"), ", ptr ", function.local("char_dst")
    )
    copy_char.emit("next_src_char", "add", " i64 ", function.local("src"), ", 1")
    copy_char.emit("next_dst_char", "add", " i64 ", function.local("dst_char"), ", 1")
    copy_char.emit(
        None, "store", " i64 ", function.local("next_src_char"), ", ptr ", function.local("src_ptr")
    )
    copy_char.emit(
        None, "store", " i64 ", function.local("next_dst_char"), ", ptr ", function.local("dst_ptr")
    )
    copy_char.emit(None, "br", " label ", function.local("copy_cond"))
    done = function.append_block("done")
    done.emit("final_dst", "load", " i64, ptr ", function.local("dst_ptr"))
    done.emit(
        "zero_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("out"),
        ", i64 ",
        function.local("final_dst"),
    )
    done.emit(None, "store", " i8 0, ptr ", function.local("zero_ptr"))
    done.emit(None, "ret", " ptr ", function.local("out"))


def _build___xcc_aot_string_lower(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_string_lower")
    entry = function.append_block("entry")
    entry.emit("text_null", "icmp", " eq ptr ", function.local("text"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("text_null"),
        ", label ",
        function.local("empty"),
        ", label ",
        function.local("nonnull"),
    )
    empty = function.append_block("empty")
    empty.emit("empty_text", "call", " ptr ", module.symbol("__xcc_aot_zero_bytes"), "(i64 0)")
    empty.emit(None, "ret", " ptr ", function.local("empty_text"))
    nonnull = function.append_block("nonnull")
    nonnull.emit(
        "len", "call", " i64 ", module.symbol("strlen"), "(ptr ", function.local("text"), ")"
    )
    nonnull.emit("total", "add", " i64 ", function.local("len"), ", 1")
    nonnull.emit(
        "out", "call", " ptr ", module.symbol("malloc"), "(i64 ", function.local("total"), ")"
    )
    nonnull.emit(None, "br", " label ", function.local("loop"))
    loop = function.append_block("loop")
    loop.emit(
        "index",
        "phi",
        " i64 [ 0, ",
        function.local("nonnull"),
        " ], [ ",
        function.local("next"),
        ", ",
        function.local("step"),
        " ]",
    )
    loop.emit("done", "icmp", " uge i64 ", function.local("index"), ", ", function.local("len"))
    loop.emit(
        None,
        "br",
        " i1 ",
        function.local("done"),
        ", label ",
        function.local("zero"),
        ", label ",
        function.local("body"),
    )
    body = function.append_block("body")
    body.emit(
        "source",
        "getelementptr",
        " i8, ptr ",
        function.local("text"),
        ", i64 ",
        function.local("index"),
    )
    body.emit("char", "load", " i8, ptr ", function.local("source"))
    body.emit("char64", "zext", " i8 ", function.local("char"), " to i64")
    body.emit("ge_A", "icmp", " uge i64 ", function.local("char64"), ", 65")
    body.emit("le_Z", "icmp", " ule i64 ", function.local("char64"), ", 90")
    body.emit("is_upper", "and", " i1 ", function.local("ge_A"), ", ", function.local("le_Z"))
    body.emit("lowered", "add", " i8 ", function.local("char"), ", 32")
    body.emit(
        "out_char",
        "select",
        " i1 ",
        function.local("is_upper"),
        ", i8 ",
        function.local("lowered"),
        ", i8 ",
        function.local("char"),
    )
    body.emit(
        "target",
        "getelementptr",
        " i8, ptr ",
        function.local("out"),
        ", i64 ",
        function.local("index"),
    )
    body.emit(None, "store", " i8 ", function.local("out_char"), ", ptr ", function.local("target"))
    body.emit(None, "br", " label ", function.local("step"))
    step = function.append_block("step")
    step.emit("next", "add", " i64 ", function.local("index"), ", 1")
    step.emit(None, "br", " label ", function.local("loop"))
    zero = function.append_block("zero")
    zero.emit(
        "zero_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("out"),
        ", i64 ",
        function.local("len"),
    )
    zero.emit(None, "store", " i8 0, ptr ", function.local("zero_ptr"))
    zero.emit(None, "ret", " ptr ", function.local("out"))


def _build___xcc_aot_string_upper(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_string_upper")
    entry = function.append_block("entry")
    entry.emit("text_null", "icmp", " eq ptr ", function.local("text"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("text_null"),
        ", label ",
        function.local("empty"),
        ", label ",
        function.local("nonnull"),
    )
    empty = function.append_block("empty")
    empty.emit("empty_text", "call", " ptr ", module.symbol("__xcc_aot_zero_bytes"), "(i64 0)")
    empty.emit(None, "ret", " ptr ", function.local("empty_text"))
    nonnull = function.append_block("nonnull")
    nonnull.emit(
        "len", "call", " i64 ", module.symbol("strlen"), "(ptr ", function.local("text"), ")"
    )
    nonnull.emit("total", "add", " i64 ", function.local("len"), ", 1")
    nonnull.emit(
        "out", "call", " ptr ", module.symbol("malloc"), "(i64 ", function.local("total"), ")"
    )
    nonnull.emit(None, "br", " label ", function.local("loop"))
    loop = function.append_block("loop")
    loop.emit(
        "index",
        "phi",
        " i64 [ 0, ",
        function.local("nonnull"),
        " ], [ ",
        function.local("next"),
        ", ",
        function.local("step"),
        " ]",
    )
    loop.emit("done", "icmp", " uge i64 ", function.local("index"), ", ", function.local("len"))
    loop.emit(
        None,
        "br",
        " i1 ",
        function.local("done"),
        ", label ",
        function.local("zero"),
        ", label ",
        function.local("body"),
    )
    body = function.append_block("body")
    body.emit(
        "source",
        "getelementptr",
        " i8, ptr ",
        function.local("text"),
        ", i64 ",
        function.local("index"),
    )
    body.emit("char", "load", " i8, ptr ", function.local("source"))
    body.emit("char64", "zext", " i8 ", function.local("char"), " to i64")
    body.emit("ge_a", "icmp", " uge i64 ", function.local("char64"), ", 97")
    body.emit("le_z", "icmp", " ule i64 ", function.local("char64"), ", 122")
    body.emit("is_lower", "and", " i1 ", function.local("ge_a"), ", ", function.local("le_z"))
    body.emit("uppered", "sub", " i8 ", function.local("char"), ", 32")
    body.emit(
        "out_char",
        "select",
        " i1 ",
        function.local("is_lower"),
        ", i8 ",
        function.local("uppered"),
        ", i8 ",
        function.local("char"),
    )
    body.emit(
        "target",
        "getelementptr",
        " i8, ptr ",
        function.local("out"),
        ", i64 ",
        function.local("index"),
    )
    body.emit(None, "store", " i8 ", function.local("out_char"), ", ptr ", function.local("target"))
    body.emit(None, "br", " label ", function.local("step"))
    step = function.append_block("step")
    step.emit("next", "add", " i64 ", function.local("index"), ", 1")
    step.emit(None, "br", " label ", function.local("loop"))
    zero = function.append_block("zero")
    zero.emit(
        "zero_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("out"),
        ", i64 ",
        function.local("len"),
    )
    zero.emit(None, "store", " i8 0, ptr ", function.local("zero_ptr"))
    zero.emit(None, "ret", " ptr ", function.local("out"))


def _build___xcc_aot_path_parent(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_path_parent")
    entry = function.append_block("entry")
    entry.emit("path_null", "icmp", " eq ptr ", function.local("path"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("path_null"),
        ", label ",
        function.local("dot"),
        ", label ",
        function.local("nonnull"),
    )
    nonnull = function.append_block("nonnull")
    nonnull.emit(
        "len", "call", " i64 ", module.symbol("strlen"), "(ptr ", function.local("path"), ")"
    )
    nonnull.emit("empty", "icmp", " eq i64 ", function.local("len"), ", 0")
    nonnull.emit(
        None,
        "br",
        " i1 ",
        function.local("empty"),
        ", label ",
        function.local("dot"),
        ", label ",
        function.local("trim"),
    )
    trim = function.append_block("trim")
    trim.emit(
        "trim_index",
        "phi",
        " i64 [ ",
        function.local("len"),
        ", ",
        function.local("nonnull"),
        " ], [ ",
        function.local("trim_prev"),
        ", ",
        function.local("trim_slash"),
        " ]",
    )
    trim.emit("trim_root", "icmp", " ule i64 ", function.local("trim_index"), ", 1")
    trim.emit(
        None,
        "br",
        " i1 ",
        function.local("trim_root"),
        ", label ",
        function.local("scan"),
        ", label ",
        function.local("trim_check"),
    )
    trim_check = function.append_block("trim_check")
    trim_check.emit("trim_prev", "sub", " i64 ", function.local("trim_index"), ", 1")
    trim_check.emit(
        "trim_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("path"),
        ", i64 ",
        function.local("trim_prev"),
    )
    trim_check.emit("trim_char", "load", " i8, ptr ", function.local("trim_ptr"))
    trim_check.emit("trim_is_slash", "icmp", " eq i8 ", function.local("trim_char"), ", 47")
    trim_check.emit(
        None,
        "br",
        " i1 ",
        function.local("trim_is_slash"),
        ", label ",
        function.local("trim_slash"),
        ", label ",
        function.local("scan"),
    )
    trim_slash = function.append_block("trim_slash")
    trim_slash.emit(None, "br", " label ", function.local("trim"))
    scan = function.append_block("scan")
    scan.emit(
        "index",
        "phi",
        " i64 [ ",
        function.local("trim_index"),
        ", ",
        function.local("trim"),
        " ], [ ",
        function.local("trim_index"),
        ", ",
        function.local("trim_check"),
        " ], [ ",
        function.local("prev"),
        ", ",
        function.local("step"),
        " ]",
    )
    scan.emit("at_start", "icmp", " eq i64 ", function.local("index"), ", 0")
    scan.emit(
        None,
        "br",
        " i1 ",
        function.local("at_start"),
        ", label ",
        function.local("dot"),
        ", label ",
        function.local("check"),
    )
    check = function.append_block("check")
    check.emit("prev", "sub", " i64 ", function.local("index"), ", 1")
    check.emit(
        "char_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("path"),
        ", i64 ",
        function.local("prev"),
    )
    check.emit("char", "load", " i8, ptr ", function.local("char_ptr"))
    check.emit("is_slash", "icmp", " eq i8 ", function.local("char"), ", 47")
    check.emit(
        None,
        "br",
        " i1 ",
        function.local("is_slash"),
        ", label ",
        function.local("found"),
        ", label ",
        function.local("step"),
    )
    step = function.append_block("step")
    step.emit(None, "br", " label ", function.local("scan"))
    found = function.append_block("found")
    found.emit("is_root", "icmp", " eq i64 ", function.local("prev"), ", 0")
    found.emit(
        None,
        "br",
        " i1 ",
        function.local("is_root"),
        ", label ",
        function.local("root"),
        ", label ",
        function.local("copy"),
    )
    copy = function.append_block("copy")
    copy.emit("out_bytes", "add", " i64 ", function.local("prev"), ", 1")
    copy.emit(
        "out", "call", " ptr ", module.symbol("malloc"), "(i64 ", function.local("out_bytes"), ")"
    )
    copy.emit(
        "copied",
        "call",
        " ptr ",
        module.symbol("memcpy"),
        "(ptr ",
        function.local("out"),
        ", ptr ",
        function.local("path"),
        ", i64 ",
        function.local("prev"),
        ")",
    )
    copy.emit(
        "zero_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("out"),
        ", i64 ",
        function.local("prev"),
    )
    copy.emit(None, "store", " i8 0, ptr ", function.local("zero_ptr"))
    copy.emit(None, "ret", " ptr ", function.local("out"))
    root = function.append_block("root")
    root.emit(None, "ret", " ptr ", module.symbol("__xcc_aot_path_slash"))
    dot = function.append_block("dot")
    dot.emit(None, "ret", " ptr ", module.symbol("__xcc_aot_path_dot"))


def _build___xcc_aot_path_name(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_path_name")
    entry = function.append_block("entry")
    entry.emit("path_null", "icmp", " eq ptr ", function.local("path"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("path_null"),
        ", label ",
        function.local("empty"),
        ", label ",
        function.local("nonnull"),
    )
    empty = function.append_block("empty")
    empty.emit("empty_text", "call", " ptr ", module.symbol("__xcc_aot_zero_bytes"), "(i64 0)")
    empty.emit(None, "ret", " ptr ", function.local("empty_text"))
    nonnull = function.append_block("nonnull")
    nonnull.emit(
        "len", "call", " i64 ", module.symbol("strlen"), "(ptr ", function.local("path"), ")"
    )
    nonnull.emit("start_ptr", "alloca", " i64")
    nonnull.emit("index_ptr", "alloca", " i64")
    nonnull.emit(None, "store", " i64 0, ptr ", function.local("start_ptr"))
    nonnull.emit(
        None, "store", " i64 ", function.local("len"), ", ptr ", function.local("index_ptr")
    )
    nonnull.emit(None, "br", " label ", function.local("scan"))
    scan = function.append_block("scan")
    scan.emit("index", "load", " i64, ptr ", function.local("index_ptr"))
    scan.emit("at_start", "icmp", " eq i64 ", function.local("index"), ", 0")
    scan.emit(
        None,
        "br",
        " i1 ",
        function.local("at_start"),
        ", label ",
        function.local("copy"),
        ", label ",
        function.local("check"),
    )
    check = function.append_block("check")
    check.emit("prev", "sub", " i64 ", function.local("index"), ", 1")
    check.emit(
        "char_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("path"),
        ", i64 ",
        function.local("prev"),
    )
    check.emit("char", "load", " i8, ptr ", function.local("char_ptr"))
    check.emit("is_slash", "icmp", " eq i8 ", function.local("char"), ", 47")
    check.emit(
        None,
        "br",
        " i1 ",
        function.local("is_slash"),
        ", label ",
        function.local("found"),
        ", label ",
        function.local("step"),
    )
    found = function.append_block("found")
    found.emit(
        None, "store", " i64 ", function.local("index"), ", ptr ", function.local("start_ptr")
    )
    found.emit(None, "br", " label ", function.local("copy"))
    step = function.append_block("step")
    step.emit(None, "store", " i64 ", function.local("prev"), ", ptr ", function.local("index_ptr"))
    step.emit(None, "br", " label ", function.local("scan"))
    copy = function.append_block("copy")
    copy.emit("start", "load", " i64, ptr ", function.local("start_ptr"))
    copy.emit("out_len", "sub", " i64 ", function.local("len"), ", ", function.local("start"))
    copy.emit("out_bytes", "add", " i64 ", function.local("out_len"), ", 1")
    copy.emit(
        "out", "call", " ptr ", module.symbol("malloc"), "(i64 ", function.local("out_bytes"), ")"
    )
    copy.emit(
        "source",
        "getelementptr",
        " i8, ptr ",
        function.local("path"),
        ", i64 ",
        function.local("start"),
    )
    copy.emit(
        "copied",
        "call",
        " ptr ",
        module.symbol("memcpy"),
        "(ptr ",
        function.local("out"),
        ", ptr ",
        function.local("source"),
        ", i64 ",
        function.local("out_len"),
        ")",
    )
    copy.emit(
        "zero_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("out"),
        ", i64 ",
        function.local("out_len"),
    )
    copy.emit(None, "store", " i8 0, ptr ", function.local("zero_ptr"))
    copy.emit(None, "ret", " ptr ", function.local("out"))


def _build___xcc_aot_path_join(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_path_join")
    entry = function.append_block("entry")
    entry.emit("path_null", "icmp", " eq ptr ", function.local("path"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("path_null"),
        ", label ",
        function.local("return_child"),
        ", label ",
        function.local("check_child"),
    )
    return_child = function.append_block("return_child")
    return_child.emit(None, "ret", " ptr ", function.local("child"))
    check_child = function.append_block("check_child")
    check_child.emit("child_null", "icmp", " eq ptr ", function.local("child"), ", null")
    check_child.emit(
        None,
        "br",
        " i1 ",
        function.local("child_null"),
        ", label ",
        function.local("return_path"),
        ", label ",
        function.local("nonnull"),
    )
    return_path = function.append_block("return_path")
    return_path.emit(None, "ret", " ptr ", function.local("path"))
    nonnull = function.append_block("nonnull")
    nonnull.emit(
        "path_len", "call", " i64 ", module.symbol("strlen"), "(ptr ", function.local("path"), ")"
    )
    nonnull.emit(
        "child_len", "call", " i64 ", module.symbol("strlen"), "(ptr ", function.local("child"), ")"
    )
    nonnull.emit("path_empty", "icmp", " eq i64 ", function.local("path_len"), ", 0")
    nonnull.emit(
        None,
        "br",
        " i1 ",
        function.local("path_empty"),
        ", label ",
        function.local("join_without_sep"),
        ", label ",
        function.local("check_slash"),
    )
    check_slash = function.append_block("check_slash")
    check_slash.emit("last_index", "sub", " i64 ", function.local("path_len"), ", 1")
    check_slash.emit(
        "last_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("path"),
        ", i64 ",
        function.local("last_index"),
    )
    check_slash.emit("last", "load", " i8, ptr ", function.local("last_ptr"))
    check_slash.emit("has_slash", "icmp", " eq i8 ", function.local("last"), ", 47")
    check_slash.emit(
        None,
        "br",
        " i1 ",
        function.local("has_slash"),
        ", label ",
        function.local("join_without_sep"),
        ", label ",
        function.local("join_with_sep"),
    )
    join_without_sep = function.append_block("join_without_sep")
    join_without_sep.emit(None, "br", " label ", function.local("alloc"))
    join_with_sep = function.append_block("join_with_sep")
    join_with_sep.emit(None, "br", " label ", function.local("alloc"))
    alloc = function.append_block("alloc")
    alloc.emit(
        "sep_len",
        "phi",
        " i64 [ 0, ",
        function.local("join_without_sep"),
        " ], [ 1, ",
        function.local("join_with_sep"),
        " ]",
    )
    alloc.emit(
        "prefix_len", "add", " i64 ", function.local("path_len"), ", ", function.local("sep_len")
    )
    alloc.emit(
        "data_len", "add", " i64 ", function.local("prefix_len"), ", ", function.local("child_len")
    )
    alloc.emit("total", "add", " i64 ", function.local("data_len"), ", 1")
    alloc.emit(
        "out", "call", " ptr ", module.symbol("malloc"), "(i64 ", function.local("total"), ")"
    )
    alloc.emit(
        "copy_path",
        "call",
        " ptr ",
        module.symbol("memcpy"),
        "(ptr ",
        function.local("out"),
        ", ptr ",
        function.local("path"),
        ", i64 ",
        function.local("path_len"),
        ")",
    )
    alloc.emit("needs_sep", "icmp", " eq i64 ", function.local("sep_len"), ", 1")
    alloc.emit(
        None,
        "br",
        " i1 ",
        function.local("needs_sep"),
        ", label ",
        function.local("store_sep"),
        ", label ",
        function.local("copy_child"),
    )
    store_sep = function.append_block("store_sep")
    store_sep.emit(
        "sep_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("out"),
        ", i64 ",
        function.local("path_len"),
    )
    store_sep.emit(None, "store", " i8 47, ptr ", function.local("sep_ptr"))
    store_sep.emit(None, "br", " label ", function.local("copy_child"))
    copy_child = function.append_block("copy_child")
    copy_child.emit(
        "child_dst",
        "getelementptr",
        " i8, ptr ",
        function.local("out"),
        ", i64 ",
        function.local("prefix_len"),
    )
    copy_child.emit(
        "copied_child",
        "call",
        " ptr ",
        module.symbol("memcpy"),
        "(ptr ",
        function.local("child_dst"),
        ", ptr ",
        function.local("child"),
        ", i64 ",
        function.local("child_len"),
        ")",
    )
    copy_child.emit(
        "zero_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("out"),
        ", i64 ",
        function.local("data_len"),
    )
    copy_child.emit(None, "store", " i8 0, ptr ", function.local("zero_ptr"))
    copy_child.emit(None, "ret", " ptr ", function.local("out"))


def _build___xcc_aot_read_text_file(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_read_text_file")
    entry = function.append_block("entry")
    entry.emit(
        "value",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_read_bytes_file"),
        "(ptr ",
        function.local("path"),
        ")",
    )
    entry.emit(
        "data",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_bytes_data"),
        "(ptr ",
        function.local("value"),
        ")",
    )
    entry.emit(None, "ret", " ptr ", function.local("data"))


def _build___xcc_aot_read_bytes_file(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_read_bytes_file")
    entry = function.append_block("entry")
    entry.emit(
        "file",
        "call",
        " ptr ",
        module.symbol("fopen"),
        "(ptr ",
        function.local("path"),
        ", ptr ",
        module.symbol("__xcc_aot_file_mode_read"),
        ")",
    )
    entry.emit("open", "icmp", " ne ptr ", function.local("file"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("open"),
        ", label ",
        function.local("seek_end"),
        ", label ",
        function.local("empty"),
    )
    seek_end = function.append_block("seek_end")
    seek_end.emit(
        "seek_end_result",
        "call",
        " i32 ",
        module.symbol("fseek"),
        "(ptr ",
        function.local("file"),
        ", i64 0, i32 2)",
    )
    seek_end.emit(
        "size", "call", " i64 ", module.symbol("ftell"), "(ptr ", function.local("file"), ")"
    )
    seek_end.emit(
        "seek_start_result",
        "call",
        " i32 ",
        module.symbol("fseek"),
        "(ptr ",
        function.local("file"),
        ", i64 0, i32 0)",
    )
    seek_end.emit(
        "value",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_bytes_new"),
        "(i64 ",
        function.local("size"),
        ")",
    )
    seek_end.emit(
        "buffer",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_bytes_data"),
        "(ptr ",
        function.local("value"),
        ")",
    )
    seek_end.emit(
        "read",
        "call",
        " i64 ",
        module.symbol("fread"),
        "(ptr ",
        function.local("buffer"),
        ", i64 1, i64 ",
        function.local("size"),
        ", ptr ",
        function.local("file"),
        ")",
    )
    seek_end.emit(
        "closed", "call", " i32 ", module.symbol("fclose"), "(ptr ", function.local("file"), ")"
    )
    seek_end.emit(None, "ret", " ptr ", function.local("value"))
    empty = function.append_block("empty")
    empty.emit("empty_value", "call", " ptr ", module.symbol("__xcc_aot_bytes_new"), "(i64 0)")
    empty.emit(None, "ret", " ptr ", function.local("empty_value"))


def _build___xcc_aot_path_is_file(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_path_is_file")
    entry = function.append_block("entry")
    entry.emit(
        "file",
        "call",
        " ptr ",
        module.symbol("fopen"),
        "(ptr ",
        function.local("path"),
        ", ptr ",
        module.symbol("__xcc_aot_file_mode_read"),
        ")",
    )
    entry.emit("open", "icmp", " ne ptr ", function.local("file"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("open"),
        ", label ",
        function.local("close"),
        ", label ",
        function.local("missing"),
    )
    close = function.append_block("close")
    close.emit(
        "closed", "call", " i32 ", module.symbol("fclose"), "(ptr ", function.local("file"), ")"
    )
    close.emit(None, "ret", " i1 true")
    missing = function.append_block("missing")
    missing.emit(None, "ret", " i1 false")


def _build___xcc_aot_write_text_file(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_write_text_file")
    entry = function.append_block("entry")
    entry.emit(
        "file",
        "call",
        " ptr ",
        module.symbol("fopen"),
        "(ptr ",
        function.local("path"),
        ", ptr ",
        module.symbol("__xcc_aot_file_mode_write"),
        ")",
    )
    entry.emit("open", "icmp", " ne ptr ", function.local("file"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("open"),
        ", label ",
        function.local("write"),
        ", label ",
        function.local("fail"),
    )
    write = function.append_block("write")
    write.emit(
        "len", "call", " i64 ", module.symbol("strlen"), "(ptr ", function.local("text"), ")"
    )
    write.emit(
        "written",
        "call",
        " i64 ",
        module.symbol("fwrite"),
        "(ptr ",
        function.local("text"),
        ", i64 1, i64 ",
        function.local("len"),
        ", ptr ",
        function.local("file"),
        ")",
    )
    write.emit(
        "closed", "call", " i32 ", module.symbol("fclose"), "(ptr ", function.local("file"), ")"
    )
    write.emit("ok", "icmp", " eq i64 ", function.local("written"), ", ", function.local("len"))
    write.emit(None, "ret", " i1 ", function.local("ok"))
    fail = function.append_block("fail")
    fail.emit(None, "ret", " i1 false")


def _build___xcc_aot_startswith_cache_invalidate(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_startswith_cache_invalidate")
    entry = function.append_block("entry")
    entry.emit("cached_text", "load", " ptr, ptr ", module.symbol("__xcc_aot_startswith_text"))
    entry.emit(
        "matches_primary",
        "icmp",
        " eq ptr ",
        function.local("cached_text"),
        ", ",
        function.local("text"),
    )
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("matches_primary"),
        ", label ",
        function.local("promote_secondary"),
        ", label ",
        function.local("check_secondary"),
    )
    promote_secondary = function.append_block("promote_secondary")
    promote_secondary.emit(
        "secondary_text", "load", " ptr, ptr ", module.symbol("__xcc_aot_startswith_text_2")
    )
    promote_secondary.emit(
        "secondary_len", "load", " i64, ptr ", module.symbol("__xcc_aot_startswith_text_len_2")
    )
    promote_secondary.emit(
        None,
        "store",
        " ptr ",
        function.local("secondary_text"),
        ", ptr ",
        module.symbol("__xcc_aot_startswith_text"),
    )
    promote_secondary.emit(
        None,
        "store",
        " i64 ",
        function.local("secondary_len"),
        ", ptr ",
        module.symbol("__xcc_aot_startswith_text_len"),
    )
    promote_secondary.emit(
        None, "store", " ptr null, ptr ", module.symbol("__xcc_aot_startswith_text_2")
    )
    promote_secondary.emit(
        None, "store", " i64 0, ptr ", module.symbol("__xcc_aot_startswith_text_len_2")
    )
    promote_secondary.emit(None, "br", " label ", function.local("done"))
    check_secondary = function.append_block("check_secondary")
    check_secondary.emit(
        "cached_text_2", "load", " ptr, ptr ", module.symbol("__xcc_aot_startswith_text_2")
    )
    check_secondary.emit(
        "matches_secondary",
        "icmp",
        " eq ptr ",
        function.local("cached_text_2"),
        ", ",
        function.local("text"),
    )
    check_secondary.emit(
        None,
        "br",
        " i1 ",
        function.local("matches_secondary"),
        ", label ",
        function.local("clear_secondary"),
        ", label ",
        function.local("done"),
    )
    clear_secondary = function.append_block("clear_secondary")
    clear_secondary.emit(
        None, "store", " ptr null, ptr ", module.symbol("__xcc_aot_startswith_text_2")
    )
    clear_secondary.emit(
        None, "store", " i64 0, ptr ", module.symbol("__xcc_aot_startswith_text_len_2")
    )
    clear_secondary.emit(None, "br", " label ", function.local("done"))
    done = function.append_block("done")
    done.emit(None, "ret", " void")


def _build___xcc_aot_string_len(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_string_len")
    entry = function.append_block("entry")
    entry.emit("cached_text", "load", " ptr, ptr ", module.symbol("__xcc_aot_startswith_text"))
    entry.emit(
        "cached", "icmp", " eq ptr ", function.local("cached_text"), ", ", function.local("text")
    )
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("cached"),
        ", label ",
        function.local("known_primary"),
        ", label ",
        function.local("check_secondary"),
    )
    check_secondary = function.append_block("check_secondary")
    check_secondary.emit(
        "cached_text_2", "load", " ptr, ptr ", module.symbol("__xcc_aot_startswith_text_2")
    )
    check_secondary.emit(
        "cached_2",
        "icmp",
        " eq ptr ",
        function.local("cached_text_2"),
        ", ",
        function.local("text"),
    )
    check_secondary.emit(
        None,
        "br",
        " i1 ",
        function.local("cached_2"),
        ", label ",
        function.local("known_secondary"),
        ", label ",
        function.local("measure"),
    )
    known_primary = function.append_block("known_primary")
    known_primary.emit(
        "known_len", "load", " i64, ptr ", module.symbol("__xcc_aot_startswith_text_len")
    )
    known_primary.emit(None, "ret", " i64 ", function.local("known_len"))
    known_secondary = function.append_block("known_secondary")
    known_secondary.emit(
        "known_len_2", "load", " i64, ptr ", module.symbol("__xcc_aot_startswith_text_len_2")
    )
    known_secondary.emit(
        "old_text", "load", " ptr, ptr ", module.symbol("__xcc_aot_startswith_text")
    )
    known_secondary.emit(
        "old_len", "load", " i64, ptr ", module.symbol("__xcc_aot_startswith_text_len")
    )
    known_secondary.emit(
        None,
        "store",
        " ptr ",
        function.local("text"),
        ", ptr ",
        module.symbol("__xcc_aot_startswith_text"),
    )
    known_secondary.emit(
        None,
        "store",
        " i64 ",
        function.local("known_len_2"),
        ", ptr ",
        module.symbol("__xcc_aot_startswith_text_len"),
    )
    known_secondary.emit(
        None,
        "store",
        " ptr ",
        function.local("old_text"),
        ", ptr ",
        module.symbol("__xcc_aot_startswith_text_2"),
    )
    known_secondary.emit(
        None,
        "store",
        " i64 ",
        function.local("old_len"),
        ", ptr ",
        module.symbol("__xcc_aot_startswith_text_len_2"),
    )
    known_secondary.emit(None, "ret", " i64 ", function.local("known_len_2"))
    measure = function.append_block("measure")
    measure.emit(
        "measured_len",
        "call",
        " i64 ",
        module.symbol("strlen"),
        "(ptr ",
        function.local("text"),
        ")",
    )
    measure.emit("previous_text", "load", " ptr, ptr ", module.symbol("__xcc_aot_startswith_text"))
    measure.emit(
        "previous_len", "load", " i64, ptr ", module.symbol("__xcc_aot_startswith_text_len")
    )
    measure.emit(
        None,
        "store",
        " ptr ",
        function.local("previous_text"),
        ", ptr ",
        module.symbol("__xcc_aot_startswith_text_2"),
    )
    measure.emit(
        None,
        "store",
        " i64 ",
        function.local("previous_len"),
        ", ptr ",
        module.symbol("__xcc_aot_startswith_text_len_2"),
    )
    measure.emit(
        None,
        "store",
        " ptr ",
        function.local("text"),
        ", ptr ",
        module.symbol("__xcc_aot_startswith_text"),
    )
    measure.emit(
        None,
        "store",
        " i64 ",
        function.local("measured_len"),
        ", ptr ",
        module.symbol("__xcc_aot_startswith_text_len"),
    )
    measure.emit(None, "ret", " i64 ", function.local("measured_len"))


def _build___xcc_aot_string_startswith_known_length(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_string_startswith_known_length")
    entry = function.append_block("entry")
    entry.emit(
        "prefix_len",
        "call",
        " i64 ",
        module.symbol("strlen"),
        "(ptr ",
        function.local("prefix"),
        ")",
    )
    entry.emit("start_neg", "icmp", " slt i64 ", function.local("start"), ", 0")
    entry.emit(
        "negative_start", "add", " i64 ", function.local("text_len"), ", ", function.local("start")
    )
    entry.emit("negative_before_zero", "icmp", " slt i64 ", function.local("negative_start"), ", 0")
    entry.emit(
        "negative_normalized",
        "select",
        " i1 ",
        function.local("negative_before_zero"),
        ", i64 0, i64 ",
        function.local("negative_start"),
    )
    entry.emit(
        "start0",
        "select",
        " i1 ",
        function.local("start_neg"),
        ", i64 ",
        function.local("negative_normalized"),
        ", i64 ",
        function.local("start"),
    )
    entry.emit(
        "start_too_far",
        "icmp",
        " ugt i64 ",
        function.local("start0"),
        ", ",
        function.local("text_len"),
    )
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("start_too_far"),
        ", label ",
        function.local("false"),
        ", label ",
        function.local("bounds"),
    )
    bounds = function.append_block("bounds")
    bounds.emit(
        "remaining", "sub", " i64 ", function.local("text_len"), ", ", function.local("start0")
    )
    bounds.emit(
        "fits", "icmp", " ule i64 ", function.local("prefix_len"), ", ", function.local("remaining")
    )
    bounds.emit(
        None,
        "br",
        " i1 ",
        function.local("fits"),
        ", label ",
        function.local("compare"),
        ", label ",
        function.local("false"),
    )
    compare = function.append_block("compare")
    compare.emit(
        "start_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("text"),
        ", i64 ",
        function.local("start0"),
    )
    compare.emit(
        "cmp",
        "call",
        " i32 ",
        module.symbol("strncmp"),
        "(ptr ",
        function.local("start_ptr"),
        ", ptr ",
        function.local("prefix"),
        ", i64 ",
        function.local("prefix_len"),
        ")",
    )
    compare.emit("ok", "icmp", " eq i32 ", function.local("cmp"), ", 0")
    compare.emit(None, "ret", " i1 ", function.local("ok"))
    false = function.append_block("false")
    false.emit(None, "ret", " i1 false")


def _build___xcc_aot_string_startswith(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_string_startswith")
    entry = function.append_block("entry")
    entry.emit("text_null", "icmp", " eq ptr ", function.local("text"), ", null")
    entry.emit("prefix_null", "icmp", " eq ptr ", function.local("prefix"), ", null")
    entry.emit(
        "any_null", "or", " i1 ", function.local("text_null"), ", ", function.local("prefix_null")
    )
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("any_null"),
        ", label ",
        function.local("false"),
        ", label ",
        function.local("nonnull"),
    )
    nonnull = function.append_block("nonnull")
    nonnull.emit(
        "text_len",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_string_len"),
        "(ptr ",
        function.local("text"),
        ")",
    )
    nonnull.emit(
        "result", "call", " i1 ", module.symbol("__xcc_aot_string_startswith_known_length"), "("
    )
    nonnull.continue_(
        "  ptr ",
        function.local("text"),
        ", i64 ",
        function.local("text_len"),
        ", ptr ",
        function.local("prefix"),
        ", i64 ",
        function.local("start"),
        ")",
    )
    nonnull.emit(None, "ret", " i1 ", function.local("result"))
    false = function.append_block("false")
    false.emit(None, "ret", " i1 false")


def _build___xcc_aot_string_endswith(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_string_endswith")
    entry = function.append_block("entry")
    entry.emit("text_null", "icmp", " eq ptr ", function.local("text"), ", null")
    entry.emit("suffix_null", "icmp", " eq ptr ", function.local("suffix"), ", null")
    entry.emit(
        "any_null", "or", " i1 ", function.local("text_null"), ", ", function.local("suffix_null")
    )
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("any_null"),
        ", label ",
        function.local("false"),
        ", label ",
        function.local("nonnull"),
    )
    nonnull = function.append_block("nonnull")
    nonnull.emit(
        "text_len", "call", " i64 ", module.symbol("strlen"), "(ptr ", function.local("text"), ")"
    )
    nonnull.emit(
        "suffix_len",
        "call",
        " i64 ",
        module.symbol("strlen"),
        "(ptr ",
        function.local("suffix"),
        ")",
    )
    nonnull.emit(
        "fits", "icmp", " ule i64 ", function.local("suffix_len"), ", ", function.local("text_len")
    )
    nonnull.emit(
        None,
        "br",
        " i1 ",
        function.local("fits"),
        ", label ",
        function.local("compare"),
        ", label ",
        function.local("false"),
    )
    compare = function.append_block("compare")
    compare.emit(
        "start", "sub", " i64 ", function.local("text_len"), ", ", function.local("suffix_len")
    )
    compare.emit(
        "start_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("text"),
        ", i64 ",
        function.local("start"),
    )
    compare.emit(
        "cmp",
        "call",
        " i32 ",
        module.symbol("strncmp"),
        "(ptr ",
        function.local("start_ptr"),
        ", ptr ",
        function.local("suffix"),
        ", i64 ",
        function.local("suffix_len"),
        ")",
    )
    compare.emit("ok", "icmp", " eq i32 ", function.local("cmp"), ", 0")
    compare.emit(None, "ret", " i1 ", function.local("ok"))
    false = function.append_block("false")
    false.emit(None, "ret", " i1 false")


def _build___xcc_aot_string_rfind(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_string_rfind")
    entry = function.append_block("entry")
    entry.emit("text_null", "icmp", " eq ptr ", function.local("text"), ", null")
    entry.emit("needle_null", "icmp", " eq ptr ", function.local("needle"), ", null")
    entry.emit(
        "any_null", "or", " i1 ", function.local("text_null"), ", ", function.local("needle_null")
    )
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("any_null"),
        ", label ",
        function.local("not_found"),
        ", label ",
        function.local("nonnull"),
    )
    nonnull = function.append_block("nonnull")
    nonnull.emit(
        "text_len", "call", " i64 ", module.symbol("strlen"), "(ptr ", function.local("text"), ")"
    )
    nonnull.emit(
        "needle_len",
        "call",
        " i64 ",
        module.symbol("strlen"),
        "(ptr ",
        function.local("needle"),
        ")",
    )
    nonnull.emit("start_negative", "icmp", " slt i64 ", function.local("start"), ", 0")
    nonnull.emit(
        "start_from_end", "add", " i64 ", function.local("text_len"), ", ", function.local("start")
    )
    nonnull.emit("start_before_zero", "icmp", " slt i64 ", function.local("start_from_end"), ", 0")
    nonnull.emit(
        "negative_start",
        "select",
        " i1 ",
        function.local("start_before_zero"),
        ", i64 0, i64 ",
        function.local("start_from_end"),
    )
    nonnull.emit(
        "actual_start",
        "select",
        " i1 ",
        function.local("start_negative"),
        ", i64 ",
        function.local("negative_start"),
        ", i64 ",
        function.local("start"),
    )
    nonnull.emit(
        "start_past_end",
        "icmp",
        " sgt i64 ",
        function.local("actual_start"),
        ", ",
        function.local("text_len"),
    )
    nonnull.emit(
        None,
        "br",
        " i1 ",
        function.local("start_past_end"),
        ", label ",
        function.local("not_found"),
        ", label ",
        function.local("normalize_end"),
    )
    normalize_end = function.append_block("normalize_end")
    normalize_end.emit("end_negative", "icmp", " slt i64 ", function.local("end"), ", 0")
    normalize_end.emit(
        "end_from_end", "add", " i64 ", function.local("text_len"), ", ", function.local("end")
    )
    normalize_end.emit(
        "end_before_zero", "icmp", " slt i64 ", function.local("end_from_end"), ", 0"
    )
    normalize_end.emit(
        "negative_end",
        "select",
        " i1 ",
        function.local("end_before_zero"),
        ", i64 0, i64 ",
        function.local("end_from_end"),
    )
    normalize_end.emit(
        "end_past_end", "icmp", " sgt i64 ", function.local("end"), ", ", function.local("text_len")
    )
    normalize_end.emit(
        "positive_end",
        "select",
        " i1 ",
        function.local("end_past_end"),
        ", i64 ",
        function.local("text_len"),
        ", i64 ",
        function.local("end"),
    )
    normalize_end.emit(
        "actual_end",
        "select",
        " i1 ",
        function.local("end_negative"),
        ", i64 ",
        function.local("negative_end"),
        ", i64 ",
        function.local("positive_end"),
    )
    normalize_end.emit(
        "ordered",
        "icmp",
        " sge i64 ",
        function.local("actual_end"),
        ", ",
        function.local("actual_start"),
    )
    normalize_end.emit(
        None,
        "br",
        " i1 ",
        function.local("ordered"),
        ", label ",
        function.local("check_fit"),
        ", label ",
        function.local("not_found"),
    )
    check_fit = function.append_block("check_fit")
    check_fit.emit(
        "window", "sub", " i64 ", function.local("actual_end"), ", ", function.local("actual_start")
    )
    check_fit.emit(
        "fits", "icmp", " ule i64 ", function.local("needle_len"), ", ", function.local("window")
    )
    check_fit.emit(
        None,
        "br",
        " i1 ",
        function.local("fits"),
        ", label ",
        function.local("setup"),
        ", label ",
        function.local("not_found"),
    )
    setup = function.append_block("setup")
    setup.emit(
        "candidate",
        "sub",
        " i64 ",
        function.local("actual_end"),
        ", ",
        function.local("needle_len"),
    )
    setup.emit("index_ptr", "alloca", " i64")
    setup.emit(
        None, "store", " i64 ", function.local("candidate"), ", ptr ", function.local("index_ptr")
    )
    setup.emit(None, "br", " label ", function.local("search"))
    search = function.append_block("search")
    search.emit("index", "load", " i64, ptr ", function.local("index_ptr"))
    search.emit(
        "in_bounds",
        "icmp",
        " sge i64 ",
        function.local("index"),
        ", ",
        function.local("actual_start"),
    )
    search.emit(
        None,
        "br",
        " i1 ",
        function.local("in_bounds"),
        ", label ",
        function.local("compare"),
        ", label ",
        function.local("not_found"),
    )
    compare = function.append_block("compare")
    compare.emit(
        "candidate_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("text"),
        ", i64 ",
        function.local("index"),
    )
    compare.emit(
        "compared",
        "call",
        " i32 ",
        module.symbol("memcmp"),
        "(ptr ",
        function.local("candidate_ptr"),
        ", ptr ",
        function.local("needle"),
        ", i64 ",
        function.local("needle_len"),
        ")",
    )
    compare.emit("matches", "icmp", " eq i32 ", function.local("compared"), ", 0")
    compare.emit(
        None,
        "br",
        " i1 ",
        function.local("matches"),
        ", label ",
        function.local("found"),
        ", label ",
        function.local("previous"),
    )
    found = function.append_block("found")
    found.emit(None, "ret", " i64 ", function.local("index"))
    previous = function.append_block("previous")
    previous.emit("previous_index", "sub", " i64 ", function.local("index"), ", 1")
    previous.emit(
        None,
        "store",
        " i64 ",
        function.local("previous_index"),
        ", ptr ",
        function.local("index_ptr"),
    )
    previous.emit(None, "br", " label ", function.local("search"))
    not_found = function.append_block("not_found")
    not_found.emit(None, "ret", " i64 -1")


def _build___xcc_aot_string_count(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_string_count")
    entry = function.append_block("entry")
    entry.emit("text_null", "icmp", " eq ptr ", function.local("text"), ", null")
    entry.emit("needle_null", "icmp", " eq ptr ", function.local("needle"), ", null")
    entry.emit(
        "any_null", "or", " i1 ", function.local("text_null"), ", ", function.local("needle_null")
    )
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("any_null"),
        ", label ",
        function.local("zero"),
        ", label ",
        function.local("nonnull"),
    )
    nonnull = function.append_block("nonnull")
    nonnull.emit(
        "text_len", "call", " i64 ", module.symbol("strlen"), "(ptr ", function.local("text"), ")"
    )
    nonnull.emit(
        "needle_len",
        "call",
        " i64 ",
        module.symbol("strlen"),
        "(ptr ",
        function.local("needle"),
        ")",
    )
    nonnull.emit("start_negative", "icmp", " slt i64 ", function.local("start"), ", 0")
    nonnull.emit(
        "start_from_end", "add", " i64 ", function.local("text_len"), ", ", function.local("start")
    )
    nonnull.emit("start_before_zero", "icmp", " slt i64 ", function.local("start_from_end"), ", 0")
    nonnull.emit(
        "negative_start",
        "select",
        " i1 ",
        function.local("start_before_zero"),
        ", i64 0, i64 ",
        function.local("start_from_end"),
    )
    nonnull.emit(
        "actual_start",
        "select",
        " i1 ",
        function.local("start_negative"),
        ", i64 ",
        function.local("negative_start"),
        ", i64 ",
        function.local("start"),
    )
    nonnull.emit(
        "start_past_end",
        "icmp",
        " sgt i64 ",
        function.local("actual_start"),
        ", ",
        function.local("text_len"),
    )
    nonnull.emit(
        None,
        "br",
        " i1 ",
        function.local("start_past_end"),
        ", label ",
        function.local("zero"),
        ", label ",
        function.local("normalize_end"),
    )
    normalize_end = function.append_block("normalize_end")
    normalize_end.emit("end_negative", "icmp", " slt i64 ", function.local("end"), ", 0")
    normalize_end.emit(
        "end_from_end", "add", " i64 ", function.local("text_len"), ", ", function.local("end")
    )
    normalize_end.emit(
        "end_before_zero", "icmp", " slt i64 ", function.local("end_from_end"), ", 0"
    )
    normalize_end.emit(
        "negative_end",
        "select",
        " i1 ",
        function.local("end_before_zero"),
        ", i64 0, i64 ",
        function.local("end_from_end"),
    )
    normalize_end.emit(
        "end_past_end", "icmp", " sgt i64 ", function.local("end"), ", ", function.local("text_len")
    )
    normalize_end.emit(
        "positive_end",
        "select",
        " i1 ",
        function.local("end_past_end"),
        ", i64 ",
        function.local("text_len"),
        ", i64 ",
        function.local("end"),
    )
    normalize_end.emit(
        "actual_end",
        "select",
        " i1 ",
        function.local("end_negative"),
        ", i64 ",
        function.local("negative_end"),
        ", i64 ",
        function.local("positive_end"),
    )
    normalize_end.emit(
        "ordered",
        "icmp",
        " sge i64 ",
        function.local("actual_end"),
        ", ",
        function.local("actual_start"),
    )
    normalize_end.emit(
        None,
        "br",
        " i1 ",
        function.local("ordered"),
        ", label ",
        function.local("check_empty"),
        ", label ",
        function.local("zero"),
    )
    check_empty = function.append_block("check_empty")
    check_empty.emit(
        "window", "sub", " i64 ", function.local("actual_end"), ", ", function.local("actual_start")
    )
    check_empty.emit("needle_empty", "icmp", " eq i64 ", function.local("needle_len"), ", 0")
    check_empty.emit(
        None,
        "br",
        " i1 ",
        function.local("needle_empty"),
        ", label ",
        function.local("empty"),
        ", label ",
        function.local("check_fit"),
    )
    empty = function.append_block("empty")
    empty.emit("empty_count", "add", " i64 ", function.local("window"), ", 1")
    empty.emit(None, "ret", " i64 ", function.local("empty_count"))
    check_fit = function.append_block("check_fit")
    check_fit.emit(
        "fits", "icmp", " ule i64 ", function.local("needle_len"), ", ", function.local("window")
    )
    check_fit.emit(
        None,
        "br",
        " i1 ",
        function.local("fits"),
        ", label ",
        function.local("setup"),
        ", label ",
        function.local("zero"),
    )
    setup = function.append_block("setup")
    setup.emit("index_ptr", "alloca", " i64")
    setup.emit("count_ptr", "alloca", " i64")
    setup.emit(
        None,
        "store",
        " i64 ",
        function.local("actual_start"),
        ", ptr ",
        function.local("index_ptr"),
    )
    setup.emit(None, "store", " i64 0, ptr ", function.local("count_ptr"))
    setup.emit(None, "br", " label ", function.local("search"))
    search = function.append_block("search")
    search.emit("index", "load", " i64, ptr ", function.local("index_ptr"))
    search.emit(
        "remaining", "sub", " i64 ", function.local("actual_end"), ", ", function.local("index")
    )
    search.emit(
        "in_bounds",
        "icmp",
        " uge i64 ",
        function.local("remaining"),
        ", ",
        function.local("needle_len"),
    )
    search.emit(
        None,
        "br",
        " i1 ",
        function.local("in_bounds"),
        ", label ",
        function.local("compare"),
        ", label ",
        function.local("done"),
    )
    compare = function.append_block("compare")
    compare.emit(
        "candidate_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("text"),
        ", i64 ",
        function.local("index"),
    )
    compare.emit(
        "compared",
        "call",
        " i32 ",
        module.symbol("memcmp"),
        "(ptr ",
        function.local("candidate_ptr"),
        ", ptr ",
        function.local("needle"),
        ", i64 ",
        function.local("needle_len"),
        ")",
    )
    compare.emit("matches", "icmp", " eq i32 ", function.local("compared"), ", 0")
    compare.emit(
        None,
        "br",
        " i1 ",
        function.local("matches"),
        ", label ",
        function.local("matched"),
        ", label ",
        function.local("advance_one"),
    )
    matched = function.append_block("matched")
    matched.emit("old_count", "load", " i64, ptr ", function.local("count_ptr"))
    matched.emit("new_count", "add", " i64 ", function.local("old_count"), ", 1")
    matched.emit(
        None, "store", " i64 ", function.local("new_count"), ", ptr ", function.local("count_ptr")
    )
    matched.emit(
        "matched_next", "add", " i64 ", function.local("index"), ", ", function.local("needle_len")
    )
    matched.emit(
        None,
        "store",
        " i64 ",
        function.local("matched_next"),
        ", ptr ",
        function.local("index_ptr"),
    )
    matched.emit(None, "br", " label ", function.local("search"))
    advance_one = function.append_block("advance_one")
    advance_one.emit("next_index", "add", " i64 ", function.local("index"), ", 1")
    advance_one.emit(
        None, "store", " i64 ", function.local("next_index"), ", ptr ", function.local("index_ptr")
    )
    advance_one.emit(None, "br", " label ", function.local("search"))
    done = function.append_block("done")
    done.emit("result", "load", " i64, ptr ", function.local("count_ptr"))
    done.emit(None, "ret", " i64 ", function.local("result"))
    zero = function.append_block("zero")
    zero.emit(None, "ret", " i64 0")


def _build___xcc_aot_string_removeprefix(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_string_removeprefix")
    entry = function.append_block("entry")
    entry.emit("text_null", "icmp", " eq ptr ", function.local("text"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("text_null"),
        ", label ",
        function.local("empty"),
        ", label ",
        function.local("check_prefix"),
    )
    empty = function.append_block("empty")
    empty.emit("empty_text", "call", " ptr ", module.symbol("__xcc_aot_zero_bytes"), "(i64 0)")
    empty.emit(None, "ret", " ptr ", function.local("empty_text"))
    check_prefix = function.append_block("check_prefix")
    check_prefix.emit("prefix_null", "icmp", " eq ptr ", function.local("prefix"), ", null")
    check_prefix.emit(
        None,
        "br",
        " i1 ",
        function.local("prefix_null"),
        ", label ",
        function.local("return_input"),
        ", label ",
        function.local("nonnull"),
    )
    return_input = function.append_block("return_input")
    return_input.emit(None, "ret", " ptr ", function.local("text"))
    nonnull = function.append_block("nonnull")
    nonnull.emit(
        "text_len", "call", " i64 ", module.symbol("strlen"), "(ptr ", function.local("text"), ")"
    )
    nonnull.emit(
        "prefix_len",
        "call",
        " i64 ",
        module.symbol("strlen"),
        "(ptr ",
        function.local("prefix"),
        ")",
    )
    nonnull.emit("prefix_empty", "icmp", " eq i64 ", function.local("prefix_len"), ", 0")
    nonnull.emit(
        None,
        "br",
        " i1 ",
        function.local("prefix_empty"),
        ", label ",
        function.local("return_input"),
        ", label ",
        function.local("check_fit"),
    )
    check_fit = function.append_block("check_fit")
    check_fit.emit(
        "fits", "icmp", " ule i64 ", function.local("prefix_len"), ", ", function.local("text_len")
    )
    check_fit.emit(
        None,
        "br",
        " i1 ",
        function.local("fits"),
        ", label ",
        function.local("compare"),
        ", label ",
        function.local("return_input"),
    )
    compare = function.append_block("compare")
    compare.emit(
        "cmp",
        "call",
        " i32 ",
        module.symbol("strncmp"),
        "(ptr ",
        function.local("text"),
        ", ptr ",
        function.local("prefix"),
        ", i64 ",
        function.local("prefix_len"),
        ")",
    )
    compare.emit("match", "icmp", " eq i32 ", function.local("cmp"), ", 0")
    compare.emit(
        None,
        "br",
        " i1 ",
        function.local("match"),
        ", label ",
        function.local("copy"),
        ", label ",
        function.local("return_input"),
    )
    copy = function.append_block("copy")
    copy.emit(
        "out_len", "sub", " i64 ", function.local("text_len"), ", ", function.local("prefix_len")
    )
    copy.emit("out_bytes", "add", " i64 ", function.local("out_len"), ", 1")
    copy.emit(
        "out", "call", " ptr ", module.symbol("malloc"), "(i64 ", function.local("out_bytes"), ")"
    )
    copy.emit(
        "source",
        "getelementptr",
        " i8, ptr ",
        function.local("text"),
        ", i64 ",
        function.local("prefix_len"),
    )
    copy.emit(
        "copied",
        "call",
        " ptr ",
        module.symbol("memcpy"),
        "(ptr ",
        function.local("out"),
        ", ptr ",
        function.local("source"),
        ", i64 ",
        function.local("out_len"),
        ")",
    )
    copy.emit(
        "zero_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("out"),
        ", i64 ",
        function.local("out_len"),
    )
    copy.emit(None, "store", " i8 0, ptr ", function.local("zero_ptr"))
    copy.emit(None, "ret", " ptr ", function.local("out"))


def _build___xcc_aot_string_removesuffix(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_string_removesuffix")
    entry = function.append_block("entry")
    entry.emit("text_null", "icmp", " eq ptr ", function.local("text"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("text_null"),
        ", label ",
        function.local("empty"),
        ", label ",
        function.local("check_suffix"),
    )
    empty = function.append_block("empty")
    empty.emit("empty_text", "call", " ptr ", module.symbol("__xcc_aot_zero_bytes"), "(i64 0)")
    empty.emit(None, "ret", " ptr ", function.local("empty_text"))
    check_suffix = function.append_block("check_suffix")
    check_suffix.emit("suffix_null", "icmp", " eq ptr ", function.local("suffix"), ", null")
    check_suffix.emit(
        None,
        "br",
        " i1 ",
        function.local("suffix_null"),
        ", label ",
        function.local("return_input"),
        ", label ",
        function.local("nonnull"),
    )
    return_input = function.append_block("return_input")
    return_input.emit(None, "ret", " ptr ", function.local("text"))
    nonnull = function.append_block("nonnull")
    nonnull.emit(
        "text_len", "call", " i64 ", module.symbol("strlen"), "(ptr ", function.local("text"), ")"
    )
    nonnull.emit(
        "suffix_len",
        "call",
        " i64 ",
        module.symbol("strlen"),
        "(ptr ",
        function.local("suffix"),
        ")",
    )
    nonnull.emit("suffix_empty", "icmp", " eq i64 ", function.local("suffix_len"), ", 0")
    nonnull.emit(
        None,
        "br",
        " i1 ",
        function.local("suffix_empty"),
        ", label ",
        function.local("return_input"),
        ", label ",
        function.local("check_fit"),
    )
    check_fit = function.append_block("check_fit")
    check_fit.emit(
        "fits", "icmp", " ule i64 ", function.local("suffix_len"), ", ", function.local("text_len")
    )
    check_fit.emit(
        None,
        "br",
        " i1 ",
        function.local("fits"),
        ", label ",
        function.local("compare"),
        ", label ",
        function.local("return_input"),
    )
    compare = function.append_block("compare")
    compare.emit(
        "out_len", "sub", " i64 ", function.local("text_len"), ", ", function.local("suffix_len")
    )
    compare.emit(
        "start",
        "getelementptr",
        " i8, ptr ",
        function.local("text"),
        ", i64 ",
        function.local("out_len"),
    )
    compare.emit(
        "cmp",
        "call",
        " i32 ",
        module.symbol("strncmp"),
        "(ptr ",
        function.local("start"),
        ", ptr ",
        function.local("suffix"),
        ", i64 ",
        function.local("suffix_len"),
        ")",
    )
    compare.emit("match", "icmp", " eq i32 ", function.local("cmp"), ", 0")
    compare.emit(
        None,
        "br",
        " i1 ",
        function.local("match"),
        ", label ",
        function.local("copy"),
        ", label ",
        function.local("return_input"),
    )
    copy = function.append_block("copy")
    copy.emit("out_bytes", "add", " i64 ", function.local("out_len"), ", 1")
    copy.emit(
        "out", "call", " ptr ", module.symbol("malloc"), "(i64 ", function.local("out_bytes"), ")"
    )
    copy.emit(
        "copied",
        "call",
        " ptr ",
        module.symbol("memcpy"),
        "(ptr ",
        function.local("out"),
        ", ptr ",
        function.local("text"),
        ", i64 ",
        function.local("out_len"),
        ")",
    )
    copy.emit(
        "zero_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("out"),
        ", i64 ",
        function.local("out_len"),
    )
    copy.emit(None, "store", " i8 0, ptr ", function.local("zero_ptr"))
    copy.emit(None, "ret", " ptr ", function.local("out"))


def _build___xcc_aot_is_ascii_space(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_is_ascii_space")
    entry = function.append_block("entry")
    entry.emit("char", "zext", " i8 ", function.local("char8"), " to i64")
    entry.emit("ge_tab", "icmp", " uge i64 ", function.local("char"), ", 9")
    entry.emit("le_cr", "icmp", " ule i64 ", function.local("char"), ", 13")
    entry.emit(
        "space_control", "and", " i1 ", function.local("ge_tab"), ", ", function.local("le_cr")
    )
    entry.emit("is_space", "icmp", " eq i64 ", function.local("char"), ", 32")
    entry.emit(
        "space", "or", " i1 ", function.local("space_control"), ", ", function.local("is_space")
    )
    entry.emit(None, "ret", " i1 ", function.local("space"))


def _build___xcc_aot_char_in_string(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_char_in_string")
    entry = function.append_block("entry")
    entry.emit("chars_null", "icmp", " eq ptr ", function.local("chars"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("chars_null"),
        ", label ",
        function.local("false"),
        ", label ",
        function.local("nonnull"),
    )
    nonnull = function.append_block("nonnull")
    nonnull.emit(None, "br", " label ", function.local("loop"))
    loop = function.append_block("loop")
    loop.emit(
        "index",
        "phi",
        " i64 [ 0, ",
        function.local("nonnull"),
        " ], [ ",
        function.local("next"),
        ", ",
        function.local("step"),
        " ]",
    )
    loop.emit(
        "char_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("chars"),
        ", i64 ",
        function.local("index"),
    )
    loop.emit("char", "load", " i8, ptr ", function.local("char_ptr"))
    loop.emit("done", "icmp", " eq i8 ", function.local("char"), ", 0")
    loop.emit(
        None,
        "br",
        " i1 ",
        function.local("done"),
        ", label ",
        function.local("false"),
        ", label ",
        function.local("check"),
    )
    check = function.append_block("check")
    check.emit("match", "icmp", " eq i8 ", function.local("char"), ", ", function.local("needle"))
    check.emit(
        None,
        "br",
        " i1 ",
        function.local("match"),
        ", label ",
        function.local("true"),
        ", label ",
        function.local("step"),
    )
    step = function.append_block("step")
    step.emit("next", "add", " i64 ", function.local("index"), ", 1")
    step.emit(None, "br", " label ", function.local("loop"))
    true = function.append_block("true")
    true.emit(None, "ret", " i1 true")
    false = function.append_block("false")
    false.emit(None, "ret", " i1 false")


def _build___xcc_aot_string_ljust(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_string_ljust")
    entry = function.append_block("entry")
    entry.emit("text_null", "icmp", " eq ptr ", function.local("text"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("text_null"),
        ", label ",
        function.local("empty"),
        ", label ",
        function.local("nonnull"),
    )
    empty = function.append_block("empty")
    empty.emit("empty_text", "call", " ptr ", module.symbol("__xcc_aot_zero_bytes"), "(i64 0)")
    empty.emit(None, "ret", " ptr ", function.local("empty_text"))
    nonnull = function.append_block("nonnull")
    nonnull.emit(
        "len", "call", " i64 ", module.symbol("strlen"), "(ptr ", function.local("text"), ")"
    )
    nonnull.emit(
        "needs_padding", "icmp", " sgt i64 ", function.local("width"), ", ", function.local("len")
    )
    nonnull.emit(
        None,
        "br",
        " i1 ",
        function.local("needs_padding"),
        ", label ",
        function.local("fill_select"),
        ", label ",
        function.local("return_input"),
    )
    return_input = function.append_block("return_input")
    return_input.emit(None, "ret", " ptr ", function.local("text"))
    fill_select = function.append_block("fill_select")
    fill_select.emit("fill_null", "icmp", " eq ptr ", function.local("fill"), ", null")
    fill_select.emit(
        None,
        "br",
        " i1 ",
        function.local("fill_null"),
        ", label ",
        function.local("fill_space"),
        ", label ",
        function.local("fill_load"),
    )
    fill_space = function.append_block("fill_space")
    fill_space.emit(None, "br", " label ", function.local("alloc"))
    fill_load = function.append_block("fill_load")
    fill_load.emit("fill_loaded", "load", " i8, ptr ", function.local("fill"))
    fill_load.emit(None, "br", " label ", function.local("alloc"))
    alloc = function.append_block("alloc")
    alloc.emit(
        "fill_ch",
        "phi",
        " i8 [ 32, ",
        function.local("fill_space"),
        " ], [ ",
        function.local("fill_loaded"),
        ", ",
        function.local("fill_load"),
        " ]",
    )
    alloc.emit("total", "add", " i64 ", function.local("width"), ", 1")
    alloc.emit(
        "out", "call", " ptr ", module.symbol("malloc"), "(i64 ", function.local("total"), ")"
    )
    alloc.emit(
        "copy_text",
        "call",
        " ptr ",
        module.symbol("memcpy"),
        "(ptr ",
        function.local("out"),
        ", ptr ",
        function.local("text"),
        ", i64 ",
        function.local("len"),
        ")",
    )
    alloc.emit(None, "br", " label ", function.local("loop"))
    loop = function.append_block("loop")
    loop.emit(
        "index",
        "phi",
        " i64 [ ",
        function.local("len"),
        ", ",
        function.local("alloc"),
        " ], [ ",
        function.local("next"),
        ", ",
        function.local("fill_step"),
        " ]",
    )
    loop.emit("done", "icmp", " uge i64 ", function.local("index"), ", ", function.local("width"))
    loop.emit(
        None,
        "br",
        " i1 ",
        function.local("done"),
        ", label ",
        function.local("zero"),
        ", label ",
        function.local("fill_body"),
    )
    fill_body = function.append_block("fill_body")
    fill_body.emit(
        "dst",
        "getelementptr",
        " i8, ptr ",
        function.local("out"),
        ", i64 ",
        function.local("index"),
    )
    fill_body.emit(
        None, "store", " i8 ", function.local("fill_ch"), ", ptr ", function.local("dst")
    )
    fill_body.emit(None, "br", " label ", function.local("fill_step"))
    fill_step = function.append_block("fill_step")
    fill_step.emit("next", "add", " i64 ", function.local("index"), ", 1")
    fill_step.emit(None, "br", " label ", function.local("loop"))
    zero = function.append_block("zero")
    zero.emit(
        "zero_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("out"),
        ", i64 ",
        function.local("width"),
    )
    zero.emit(None, "store", " i8 0, ptr ", function.local("zero_ptr"))
    zero.emit(None, "ret", " ptr ", function.local("out"))


def _build___xcc_aot_string_lstrip(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_string_lstrip")
    entry = function.append_block("entry")
    entry.emit("text_null", "icmp", " eq ptr ", function.local("text"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("text_null"),
        ", label ",
        function.local("empty"),
        ", label ",
        function.local("nonnull"),
    )
    empty = function.append_block("empty")
    empty.emit("empty_text", "call", " ptr ", module.symbol("__xcc_aot_zero_bytes"), "(i64 0)")
    empty.emit(None, "ret", " ptr ", function.local("empty_text"))
    nonnull = function.append_block("nonnull")
    nonnull.emit(
        "len", "call", " i64 ", module.symbol("strlen"), "(ptr ", function.local("text"), ")"
    )
    nonnull.emit("start_ptr", "alloca", " i64")
    nonnull.emit(None, "store", " i64 0, ptr ", function.local("start_ptr"))
    nonnull.emit(None, "br", " label ", function.local("trim_cond"))
    trim_cond = function.append_block("trim_cond")
    trim_cond.emit("start", "load", " i64, ptr ", function.local("start_ptr"))
    trim_cond.emit(
        "at_end", "icmp", " uge i64 ", function.local("start"), ", ", function.local("len")
    )
    trim_cond.emit(
        None,
        "br",
        " i1 ",
        function.local("at_end"),
        ", label ",
        function.local("copy"),
        ", label ",
        function.local("check"),
    )
    check = function.append_block("check")
    check.emit(
        "char_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("text"),
        ", i64 ",
        function.local("start"),
    )
    check.emit("char", "load", " i8, ptr ", function.local("char_ptr"))
    check.emit(
        "strip",
        "call",
        " i1 ",
        module.symbol("__xcc_aot_char_in_string"),
        "(i8 ",
        function.local("char"),
        ", ptr ",
        function.local("chars"),
        ")",
    )
    check.emit(
        None,
        "br",
        " i1 ",
        function.local("strip"),
        ", label ",
        function.local("trim_step"),
        ", label ",
        function.local("copy"),
    )
    trim_step = function.append_block("trim_step")
    trim_step.emit("next_start", "add", " i64 ", function.local("start"), ", 1")
    trim_step.emit(
        None, "store", " i64 ", function.local("next_start"), ", ptr ", function.local("start_ptr")
    )
    trim_step.emit(None, "br", " label ", function.local("trim_cond"))
    copy = function.append_block("copy")
    copy.emit("final_start", "load", " i64, ptr ", function.local("start_ptr"))
    copy.emit(
        "final_len", "sub", " i64 ", function.local("len"), ", ", function.local("final_start")
    )
    copy.emit("total", "add", " i64 ", function.local("final_len"), ", 1")
    copy.emit(
        "out", "call", " ptr ", module.symbol("malloc"), "(i64 ", function.local("total"), ")"
    )
    copy.emit(
        "source",
        "getelementptr",
        " i8, ptr ",
        function.local("text"),
        ", i64 ",
        function.local("final_start"),
    )
    copy.emit(
        "copy_text",
        "call",
        " ptr ",
        module.symbol("memcpy"),
        "(ptr ",
        function.local("out"),
        ", ptr ",
        function.local("source"),
        ", i64 ",
        function.local("final_len"),
        ")",
    )
    copy.emit(
        "zero_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("out"),
        ", i64 ",
        function.local("final_len"),
    )
    copy.emit(None, "store", " i8 0, ptr ", function.local("zero_ptr"))
    copy.emit(None, "ret", " ptr ", function.local("out"))


def _build___xcc_aot_string_rstrip(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_string_rstrip")
    entry = function.append_block("entry")
    entry.emit("text_null", "icmp", " eq ptr ", function.local("text"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("text_null"),
        ", label ",
        function.local("empty"),
        ", label ",
        function.local("nonnull"),
    )
    empty = function.append_block("empty")
    empty.emit("empty_text", "call", " ptr ", module.symbol("__xcc_aot_zero_bytes"), "(i64 0)")
    empty.emit(None, "ret", " ptr ", function.local("empty_text"))
    nonnull = function.append_block("nonnull")
    nonnull.emit(
        "len", "call", " i64 ", module.symbol("strlen"), "(ptr ", function.local("text"), ")"
    )
    nonnull.emit("end_ptr", "alloca", " i64")
    nonnull.emit(None, "store", " i64 ", function.local("len"), ", ptr ", function.local("end_ptr"))
    nonnull.emit(None, "br", " label ", function.local("trim_cond"))
    trim_cond = function.append_block("trim_cond")
    trim_cond.emit("end", "load", " i64, ptr ", function.local("end_ptr"))
    trim_cond.emit("at_start", "icmp", " eq i64 ", function.local("end"), ", 0")
    trim_cond.emit(
        None,
        "br",
        " i1 ",
        function.local("at_start"),
        ", label ",
        function.local("copy"),
        ", label ",
        function.local("check"),
    )
    check = function.append_block("check")
    check.emit("last_index", "sub", " i64 ", function.local("end"), ", 1")
    check.emit(
        "char_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("text"),
        ", i64 ",
        function.local("last_index"),
    )
    check.emit("char", "load", " i8, ptr ", function.local("char_ptr"))
    check.emit(
        "strip",
        "call",
        " i1 ",
        module.symbol("__xcc_aot_char_in_string"),
        "(i8 ",
        function.local("char"),
        ", ptr ",
        function.local("chars"),
        ")",
    )
    check.emit(
        None,
        "br",
        " i1 ",
        function.local("strip"),
        ", label ",
        function.local("trim_step"),
        ", label ",
        function.local("copy"),
    )
    trim_step = function.append_block("trim_step")
    trim_step.emit(
        None, "store", " i64 ", function.local("last_index"), ", ptr ", function.local("end_ptr")
    )
    trim_step.emit(None, "br", " label ", function.local("trim_cond"))
    copy = function.append_block("copy")
    copy.emit("final_len", "load", " i64, ptr ", function.local("end_ptr"))
    copy.emit("total", "add", " i64 ", function.local("final_len"), ", 1")
    copy.emit(
        "out", "call", " ptr ", module.symbol("malloc"), "(i64 ", function.local("total"), ")"
    )
    copy.emit(
        "copy_text",
        "call",
        " ptr ",
        module.symbol("memcpy"),
        "(ptr ",
        function.local("out"),
        ", ptr ",
        function.local("text"),
        ", i64 ",
        function.local("final_len"),
        ")",
    )
    copy.emit(
        "zero_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("out"),
        ", i64 ",
        function.local("final_len"),
    )
    copy.emit(None, "store", " i8 0, ptr ", function.local("zero_ptr"))
    copy.emit(None, "ret", " ptr ", function.local("out"))


def _build___xcc_aot_string_strip(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_string_strip")
    entry = function.append_block("entry")
    entry.emit(
        "left",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_string_lstrip"),
        "(ptr ",
        function.local("text"),
        ", ptr ",
        function.local("chars"),
        ")",
    )
    entry.emit(
        "both",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_string_rstrip"),
        "(ptr ",
        function.local("left"),
        ", ptr ",
        function.local("chars"),
        ")",
    )
    entry.emit(None, "ret", " ptr ", function.local("both"))


def _build___xcc_aot_zero_bytes(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_zero_bytes")
    entry = function.append_block("entry")
    entry.emit("negative", "icmp", " slt i64 ", function.local("size"), ", 0")
    entry.emit(
        "count",
        "select",
        " i1 ",
        function.local("negative"),
        ", i64 0, i64 ",
        function.local("size"),
    )
    entry.emit("total", "add", " i64 ", function.local("count"), ", 1")
    entry.emit(
        "out", "call", " ptr ", module.symbol("malloc"), "(i64 ", function.local("total"), ")"
    )
    entry.emit(
        "zeroed",
        "call",
        " ptr ",
        module.symbol("memset"),
        "(ptr ",
        function.local("out"),
        ", i32 0, i64 ",
        function.local("total"),
        ")",
    )
    entry.emit(None, "ret", " ptr ", function.local("out"))


def _build___xcc_aot_bytes_new(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_bytes_new")
    entry = function.append_block("entry")
    entry.emit("negative", "icmp", " slt i64 ", function.local("size"), ", 0")
    entry.emit(
        "count",
        "select",
        " i1 ",
        function.local("negative"),
        ", i64 0, i64 ",
        function.local("size"),
    )
    entry.emit("payload_size", "add", " i64 ", function.local("count"), ", 1")
    entry.emit("total", "add", " i64 ", function.local("payload_size"), ", 8")
    entry.emit(
        "out", "call", " ptr ", module.symbol("malloc"), "(i64 ", function.local("total"), ")"
    )
    entry.emit(None, "store", " i64 ", function.local("count"), ", ptr ", function.local("out"))
    entry.emit("data", "getelementptr", " i8, ptr ", function.local("out"), ", i64 8")
    entry.emit(
        "zeroed",
        "call",
        " ptr ",
        module.symbol("memset"),
        "(ptr ",
        function.local("data"),
        ", i32 0, i64 ",
        function.local("payload_size"),
        ")",
    )
    entry.emit(None, "ret", " ptr ", function.local("out"))


def _build___xcc_aot_bytes_data(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_bytes_data")
    entry = function.append_block("entry")
    entry.emit("is_null", "icmp", " eq ptr ", function.local("value"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("is_null"),
        ", label ",
        function.local("null"),
        ", label ",
        function.local("data"),
    )
    null = function.append_block("null")
    null.emit(None, "ret", " ptr null")
    data = function.append_block("data")
    data.emit("result", "getelementptr", " i8, ptr ", function.local("value"), ", i64 8")
    data.emit(None, "ret", " ptr ", function.local("result"))


def _build___xcc_aot_bytes_len(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_bytes_len")
    entry = function.append_block("entry")
    entry.emit("is_null", "icmp", " eq ptr ", function.local("value"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("is_null"),
        ", label ",
        function.local("zero"),
        ", label ",
        function.local("load"),
    )
    zero = function.append_block("zero")
    zero.emit(None, "ret", " i64 0")
    load = function.append_block("load")
    load.emit("length", "load", " i64, ptr ", function.local("value"))
    load.emit(None, "ret", " i64 ", function.local("length"))


def _build___xcc_aot_bytes_copy(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_bytes_copy")
    entry = function.append_block("entry")
    entry.emit(
        "out",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_bytes_new"),
        "(i64 ",
        function.local("size"),
        ")",
    )
    entry.emit(
        "data",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_bytes_data"),
        "(ptr ",
        function.local("out"),
        ")",
    )
    entry.emit(
        "copied",
        "call",
        " ptr ",
        module.symbol("memcpy"),
        "(ptr ",
        function.local("data"),
        ", ptr ",
        function.local("source"),
        ", i64 ",
        function.local("size"),
        ")",
    )
    entry.emit(None, "ret", " ptr ", function.local("out"))


def _build___xcc_aot_bytes_from_ints(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_bytes_from_ints")
    entry = function.append_block("entry")
    entry.emit(
        "length",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_tuple_len"),
        "(ptr ",
        function.local("values"),
        ")",
    )
    entry.emit(
        "result",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_bytes_new"),
        "(i64 ",
        function.local("length"),
        ")",
    )
    entry.emit(
        "data",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_bytes_data"),
        "(ptr ",
        function.local("result"),
        ")",
    )
    entry.emit("index_ptr", "alloca", " i64")
    entry.emit(None, "store", " i64 0, ptr ", function.local("index_ptr"))
    entry.emit(None, "br", " label ", function.local("cond"))
    cond = function.append_block("cond")
    cond.emit("index", "load", " i64, ptr ", function.local("index_ptr"))
    cond.emit("done", "icmp", " uge i64 ", function.local("index"), ", ", function.local("length"))
    cond.emit(
        None,
        "br",
        " i1 ",
        function.local("done"),
        ", label ",
        function.local("end"),
        ", label ",
        function.local("body"),
    )
    body = function.append_block("body")
    body.emit(
        "boxed",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_get"),
        "(ptr ",
        function.local("values"),
        ", i64 ",
        function.local("index"),
        ")",
    )
    body.emit("integer", "ptrtoint", " ptr ", function.local("boxed"), " to i64")
    body.emit("byte", "trunc", " i64 ", function.local("integer"), " to i8")
    body.emit(
        "slot",
        "getelementptr",
        " i8, ptr ",
        function.local("data"),
        ", i64 ",
        function.local("index"),
    )
    body.emit(None, "store", " i8 ", function.local("byte"), ", ptr ", function.local("slot"))
    body.emit("next", "add", " i64 ", function.local("index"), ", 1")
    body.emit(None, "store", " i64 ", function.local("next"), ", ptr ", function.local("index_ptr"))
    body.emit(None, "br", " label ", function.local("cond"))
    end = function.append_block("end")
    end.emit(None, "ret", " ptr ", function.local("result"))


def _build___xcc_aot_bytes_get(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_bytes_get")
    entry = function.append_block("entry")
    entry.emit(
        "length",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_bytes_len"),
        "(ptr ",
        function.local("value"),
        ")",
    )
    entry.emit("negative", "icmp", " slt i64 ", function.local("index"), ", 0")
    entry.emit("wrapped", "add", " i64 ", function.local("length"), ", ", function.local("index"))
    entry.emit(
        "normalized",
        "select",
        " i1 ",
        function.local("negative"),
        ", i64 ",
        function.local("wrapped"),
        ", i64 ",
        function.local("index"),
    )
    entry.emit(
        "data",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_bytes_data"),
        "(ptr ",
        function.local("value"),
        ")",
    )
    entry.emit(
        "item_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("data"),
        ", i64 ",
        function.local("normalized"),
    )
    entry.emit("item", "load", " i8, ptr ", function.local("item_ptr"))
    entry.emit("result", "zext", " i8 ", function.local("item"), " to i64")
    entry.emit(None, "ret", " i64 ", function.local("result"))


def _build___xcc_aot_bytes_equal(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_bytes_equal")
    entry = function.append_block("entry")
    entry.emit("same", "icmp", " eq ptr ", function.local("left"), ", ", function.local("right"))
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("same"),
        ", label ",
        function.local("true"),
        ", label ",
        function.local("lengths"),
    )
    lengths = function.append_block("lengths")
    lengths.emit(
        "left_len",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_bytes_len"),
        "(ptr ",
        function.local("left"),
        ")",
    )
    lengths.emit(
        "right_len",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_bytes_len"),
        "(ptr ",
        function.local("right"),
        ")",
    )
    lengths.emit(
        "same_len",
        "icmp",
        " eq i64 ",
        function.local("left_len"),
        ", ",
        function.local("right_len"),
    )
    lengths.emit(
        None,
        "br",
        " i1 ",
        function.local("same_len"),
        ", label ",
        function.local("compare"),
        ", label ",
        function.local("false"),
    )
    compare = function.append_block("compare")
    compare.emit(
        "left_data",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_bytes_data"),
        "(ptr ",
        function.local("left"),
        ")",
    )
    compare.emit(
        "right_data",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_bytes_data"),
        "(ptr ",
        function.local("right"),
        ")",
    )
    compare.emit(
        "compared",
        "call",
        " i32 ",
        module.symbol("memcmp"),
        "(ptr ",
        function.local("left_data"),
        ", ptr ",
        function.local("right_data"),
        ", i64 ",
        function.local("left_len"),
        ")",
    )
    compare.emit("equal", "icmp", " eq i32 ", function.local("compared"), ", 0")
    compare.emit(None, "ret", " i1 ", function.local("equal"))
    true = function.append_block("true")
    true.emit(None, "ret", " i1 true")
    false = function.append_block("false")
    false.emit(None, "ret", " i1 false")


def _build___xcc_aot_string_encode(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_string_encode")
    entry = function.append_block("entry")
    entry.emit(
        "length", "call", " i64 ", module.symbol("strlen"), "(ptr ", function.local("value"), ")"
    )
    entry.emit(
        "result",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_bytes_copy"),
        "(ptr ",
        function.local("value"),
        ", i64 ",
        function.local("length"),
        ")",
    )
    entry.emit(None, "ret", " ptr ", function.local("result"))


def _build___xcc_aot_bytes_concat(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_bytes_concat")
    entry = function.append_block("entry")
    entry.emit(
        "left_length",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_bytes_len"),
        "(ptr ",
        function.local("left"),
        ")",
    )
    entry.emit(
        "right_length",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_bytes_len"),
        "(ptr ",
        function.local("right"),
        ")",
    )
    entry.emit(
        "length",
        "add",
        " i64 ",
        function.local("left_length"),
        ", ",
        function.local("right_length"),
    )
    entry.emit(
        "result",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_bytes_new"),
        "(i64 ",
        function.local("length"),
        ")",
    )
    entry.emit(
        "result_data",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_bytes_data"),
        "(ptr ",
        function.local("result"),
        ")",
    )
    entry.emit(
        "left_data",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_bytes_data"),
        "(ptr ",
        function.local("left"),
        ")",
    )
    entry.emit(
        "left_copy",
        "call",
        " ptr ",
        module.symbol("memcpy"),
        "(ptr ",
        function.local("result_data"),
        ", ptr ",
        function.local("left_data"),
        ", i64 ",
        function.local("left_length"),
        ")",
    )
    entry.emit(
        "right_target",
        "getelementptr",
        " i8, ptr ",
        function.local("result_data"),
        ", i64 ",
        function.local("left_length"),
    )
    entry.emit(
        "right_data",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_bytes_data"),
        "(ptr ",
        function.local("right"),
        ")",
    )
    entry.emit(
        "right_copy",
        "call",
        " ptr ",
        module.symbol("memcpy"),
        "(ptr ",
        function.local("right_target"),
        ", ptr ",
        function.local("right_data"),
        ", i64 ",
        function.local("right_length"),
        ")",
    )
    entry.emit(None, "ret", " ptr ", function.local("result"))


def _build___xcc_aot_bytes_repeat(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_bytes_repeat")
    entry = function.append_block("entry")
    entry.emit(
        "value_length",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_bytes_len"),
        "(ptr ",
        function.local("value"),
        ")",
    )
    entry.emit("count_positive", "icmp", " sgt i64 ", function.local("count"), ", 0")
    entry.emit("value_nonempty", "icmp", " ne i64 ", function.local("value_length"), ", 0")
    entry.emit(
        "has_output",
        "and",
        " i1 ",
        function.local("count_positive"),
        ", ",
        function.local("value_nonempty"),
    )
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("has_output"),
        ", label ",
        function.local("allocate"),
        ", label ",
        function.local("empty"),
    )
    empty = function.append_block("empty")
    empty.emit("empty_result", "call", " ptr ", module.symbol("__xcc_aot_bytes_new"), "(i64 0)")
    empty.emit(None, "ret", " ptr ", function.local("empty_result"))
    allocate = function.append_block("allocate")
    allocate.emit(
        "length", "mul", " i64 ", function.local("value_length"), ", ", function.local("count")
    )
    allocate.emit(
        "result",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_bytes_new"),
        "(i64 ",
        function.local("length"),
        ")",
    )
    allocate.emit(
        "result_data",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_bytes_data"),
        "(ptr ",
        function.local("result"),
        ")",
    )
    allocate.emit(
        "value_data",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_bytes_data"),
        "(ptr ",
        function.local("value"),
        ")",
    )
    allocate.emit("index_ptr", "alloca", " i64")
    allocate.emit(None, "store", " i64 0, ptr ", function.local("index_ptr"))
    allocate.emit(None, "br", " label ", function.local("copy_cond"))
    copy_cond = function.append_block("copy_cond")
    copy_cond.emit("index", "load", " i64, ptr ", function.local("index_ptr"))
    copy_cond.emit(
        "done", "icmp", " uge i64 ", function.local("index"), ", ", function.local("count")
    )
    copy_cond.emit(
        None,
        "br",
        " i1 ",
        function.local("done"),
        ", label ",
        function.local("copy_done"),
        ", label ",
        function.local("copy_body"),
    )
    copy_body = function.append_block("copy_body")
    copy_body.emit(
        "offset", "mul", " i64 ", function.local("index"), ", ", function.local("value_length")
    )
    copy_body.emit(
        "target",
        "getelementptr",
        " i8, ptr ",
        function.local("result_data"),
        ", i64 ",
        function.local("offset"),
    )
    copy_body.emit(
        "copied",
        "call",
        " ptr ",
        module.symbol("memcpy"),
        "(ptr ",
        function.local("target"),
        ", ptr ",
        function.local("value_data"),
        ", i64 ",
        function.local("value_length"),
        ")",
    )
    copy_body.emit("next", "add", " i64 ", function.local("index"), ", 1")
    copy_body.emit(
        None, "store", " i64 ", function.local("next"), ", ptr ", function.local("index_ptr")
    )
    copy_body.emit(None, "br", " label ", function.local("copy_cond"))
    copy_done = function.append_block("copy_done")
    copy_done.emit(None, "ret", " ptr ", function.local("result"))


def _build___xcc_aot_bytes_slice(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_bytes_slice")
    entry = function.append_block("entry")
    entry.emit(
        "length",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_bytes_len"),
        "(ptr ",
        function.local("value"),
        ")",
    )
    entry.emit("start_negative", "icmp", " slt i64 ", function.local("start"), ", 0")
    entry.emit(
        "start_from_end", "add", " i64 ", function.local("length"), ", ", function.local("start")
    )
    entry.emit(
        "start_unclamped",
        "select",
        " i1 ",
        function.local("start_negative"),
        ", i64 ",
        function.local("start_from_end"),
        ", i64 ",
        function.local("start"),
    )
    entry.emit("start_below_zero", "icmp", " slt i64 ", function.local("start_unclamped"), ", 0")
    entry.emit(
        "start_nonnegative",
        "select",
        " i1 ",
        function.local("start_below_zero"),
        ", i64 0, i64 ",
        function.local("start_unclamped"),
    )
    entry.emit(
        "start_above_length",
        "icmp",
        " sgt i64 ",
        function.local("start_nonnegative"),
        ", ",
        function.local("length"),
    )
    entry.emit(
        "actual_start",
        "select",
        " i1 ",
        function.local("start_above_length"),
        ", i64 ",
        function.local("length"),
        ", i64 ",
        function.local("start_nonnegative"),
    )
    entry.emit("stop_negative", "icmp", " slt i64 ", function.local("stop"), ", 0")
    entry.emit(
        "stop_from_end", "add", " i64 ", function.local("length"), ", ", function.local("stop")
    )
    entry.emit(
        "stop_unclamped",
        "select",
        " i1 ",
        function.local("stop_negative"),
        ", i64 ",
        function.local("stop_from_end"),
        ", i64 ",
        function.local("stop"),
    )
    entry.emit("stop_below_zero", "icmp", " slt i64 ", function.local("stop_unclamped"), ", 0")
    entry.emit(
        "stop_nonnegative",
        "select",
        " i1 ",
        function.local("stop_below_zero"),
        ", i64 0, i64 ",
        function.local("stop_unclamped"),
    )
    entry.emit(
        "stop_above_length",
        "icmp",
        " sgt i64 ",
        function.local("stop_nonnegative"),
        ", ",
        function.local("length"),
    )
    entry.emit(
        "actual_stop",
        "select",
        " i1 ",
        function.local("stop_above_length"),
        ", i64 ",
        function.local("length"),
        ", i64 ",
        function.local("stop_nonnegative"),
    )
    entry.emit(
        "raw_count",
        "sub",
        " i64 ",
        function.local("actual_stop"),
        ", ",
        function.local("actual_start"),
    )
    entry.emit("count_negative", "icmp", " slt i64 ", function.local("raw_count"), ", 0")
    entry.emit(
        "count",
        "select",
        " i1 ",
        function.local("count_negative"),
        ", i64 0, i64 ",
        function.local("raw_count"),
    )
    entry.emit(
        "data",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_bytes_data"),
        "(ptr ",
        function.local("value"),
        ")",
    )
    entry.emit(
        "source",
        "getelementptr",
        " i8, ptr ",
        function.local("data"),
        ", i64 ",
        function.local("actual_start"),
    )
    entry.emit(
        "result",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_bytes_copy"),
        "(ptr ",
        function.local("source"),
        ", i64 ",
        function.local("count"),
        ")",
    )
    entry.emit(None, "ret", " ptr ", function.local("result"))


def _build___xcc_aot_bytes_ljust(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_bytes_ljust")
    entry = function.append_block("entry")
    entry.emit(
        "length",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_bytes_len"),
        "(ptr ",
        function.local("value"),
        ")",
    )
    entry.emit(
        "needs_padding",
        "icmp",
        " sgt i64 ",
        function.local("width"),
        ", ",
        function.local("length"),
    )
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("needs_padding"),
        ", label ",
        function.local("allocate"),
        ", label ",
        function.local("return_input"),
    )
    return_input = function.append_block("return_input")
    return_input.emit(None, "ret", " ptr ", function.local("value"))
    allocate = function.append_block("allocate")
    allocate.emit(
        "result",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_bytes_new"),
        "(i64 ",
        function.local("width"),
        ")",
    )
    allocate.emit(
        "result_data",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_bytes_data"),
        "(ptr ",
        function.local("result"),
        ")",
    )
    allocate.emit(
        "value_data",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_bytes_data"),
        "(ptr ",
        function.local("value"),
        ")",
    )
    allocate.emit(
        "copied",
        "call",
        " ptr ",
        module.symbol("memcpy"),
        "(ptr ",
        function.local("result_data"),
        ", ptr ",
        function.local("value_data"),
        ", i64 ",
        function.local("length"),
        ")",
    )
    allocate.emit("fill_null", "icmp", " eq ptr ", function.local("fill"), ", null")
    allocate.emit(
        None,
        "br",
        " i1 ",
        function.local("fill_null"),
        ", label ",
        function.local("fill_space"),
        ", label ",
        function.local("fill_value"),
    )
    fill_space = function.append_block("fill_space")
    fill_space.emit(None, "br", " label ", function.local("pad"))
    fill_value = function.append_block("fill_value")
    fill_value.emit(
        "fill_data",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_bytes_data"),
        "(ptr ",
        function.local("fill"),
        ")",
    )
    fill_value.emit("fill_byte", "load", " i8, ptr ", function.local("fill_data"))
    fill_value.emit(None, "br", " label ", function.local("pad"))
    pad = function.append_block("pad")
    pad.emit(
        "pad_byte",
        "phi",
        " i8 [ 32, ",
        function.local("fill_space"),
        " ], [ ",
        function.local("fill_byte"),
        ", ",
        function.local("fill_value"),
        " ]",
    )
    pad.emit("pad_value", "zext", " i8 ", function.local("pad_byte"), " to i32")
    pad.emit(
        "pad_start",
        "getelementptr",
        " i8, ptr ",
        function.local("result_data"),
        ", i64 ",
        function.local("length"),
    )
    pad.emit("pad_count", "sub", " i64 ", function.local("width"), ", ", function.local("length"))
    pad.emit(
        "padded",
        "call",
        " ptr ",
        module.symbol("memset"),
        "(ptr ",
        function.local("pad_start"),
        ", i32 ",
        function.local("pad_value"),
        ", i64 ",
        function.local("pad_count"),
        ")",
    )
    pad.emit(None, "ret", " ptr ", function.local("result"))


def _build___xcc_aot_string_repeat(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_string_repeat")
    entry = function.append_block("entry")
    entry.emit("text_null", "icmp", " eq ptr ", function.local("text"), ", null")
    entry.emit("count_nonpositive", "icmp", " sle i64 ", function.local("count"), ", 0")
    entry.emit(
        "empty_input",
        "or",
        " i1 ",
        function.local("text_null"),
        ", ",
        function.local("count_nonpositive"),
    )
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("empty_input"),
        ", label ",
        function.local("empty"),
        ", label ",
        function.local("nonnull"),
    )
    empty = function.append_block("empty")
    empty.emit("empty_text", "call", " ptr ", module.symbol("__xcc_aot_zero_bytes"), "(i64 0)")
    empty.emit(None, "ret", " ptr ", function.local("empty_text"))
    nonnull = function.append_block("nonnull")
    nonnull.emit(
        "text_len", "call", " i64 ", module.symbol("strlen"), "(ptr ", function.local("text"), ")"
    )
    nonnull.emit("text_empty", "icmp", " eq i64 ", function.local("text_len"), ", 0")
    nonnull.emit(
        None,
        "br",
        " i1 ",
        function.local("text_empty"),
        ", label ",
        function.local("empty"),
        ", label ",
        function.local("alloc"),
    )
    alloc = function.append_block("alloc")
    alloc.emit(
        "data_len", "mul", " i64 ", function.local("text_len"), ", ", function.local("count")
    )
    alloc.emit("total", "add", " i64 ", function.local("data_len"), ", 1")
    alloc.emit(
        "out", "call", " ptr ", module.symbol("malloc"), "(i64 ", function.local("total"), ")"
    )
    alloc.emit("index_ptr", "alloca", " i64")
    alloc.emit(None, "store", " i64 0, ptr ", function.local("index_ptr"))
    alloc.emit(None, "br", " label ", function.local("copy_cond"))
    copy_cond = function.append_block("copy_cond")
    copy_cond.emit("index", "load", " i64, ptr ", function.local("index_ptr"))
    copy_cond.emit(
        "done", "icmp", " uge i64 ", function.local("index"), ", ", function.local("count")
    )
    copy_cond.emit(
        None,
        "br",
        " i1 ",
        function.local("done"),
        ", label ",
        function.local("zero"),
        ", label ",
        function.local("copy_body"),
    )
    copy_body = function.append_block("copy_body")
    copy_body.emit(
        "offset", "mul", " i64 ", function.local("index"), ", ", function.local("text_len")
    )
    copy_body.emit(
        "dst",
        "getelementptr",
        " i8, ptr ",
        function.local("out"),
        ", i64 ",
        function.local("offset"),
    )
    copy_body.emit(
        "copy_text",
        "call",
        " ptr ",
        module.symbol("memcpy"),
        "(ptr ",
        function.local("dst"),
        ", ptr ",
        function.local("text"),
        ", i64 ",
        function.local("text_len"),
        ")",
    )
    copy_body.emit("next", "add", " i64 ", function.local("index"), ", 1")
    copy_body.emit(
        None, "store", " i64 ", function.local("next"), ", ptr ", function.local("index_ptr")
    )
    copy_body.emit(None, "br", " label ", function.local("copy_cond"))
    zero = function.append_block("zero")
    zero.emit(
        "zero_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("out"),
        ", i64 ",
        function.local("data_len"),
    )
    zero.emit(None, "store", " i8 0, ptr ", function.local("zero_ptr"))
    zero.emit(None, "ret", " ptr ", function.local("out"))


def _build___xcc_aot_int_to_bytes(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_int_to_bytes")
    entry = function.append_block("entry")
    entry.emit("negative", "icmp", " slt i64 ", function.local("size"), ", 0")
    entry.emit(
        "count",
        "select",
        " i1 ",
        function.local("negative"),
        ", i64 0, i64 ",
        function.local("size"),
    )
    entry.emit(
        "out",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_bytes_new"),
        "(i64 ",
        function.local("count"),
        ")",
    )
    entry.emit(
        "data",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_bytes_data"),
        "(ptr ",
        function.local("out"),
        ")",
    )
    entry.emit("byteorder_null", "icmp", " eq ptr ", function.local("byteorder"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("byteorder_null"),
        ", label ",
        function.local("little"),
        ", label ",
        function.local("order"),
    )
    little = function.append_block("little")
    little.emit(None, "br", " label ", function.local("loop_entry"))
    order = function.append_block("order")
    order.emit(
        "order_cmp",
        "call",
        " i32 ",
        module.symbol("strcmp"),
        "(ptr ",
        function.local("byteorder"),
        ", ptr ",
        module.symbol("__xcc_aot_byteorder_big"),
        ")",
    )
    order.emit("order_big", "icmp", " eq i32 ", function.local("order_cmp"), ", 0")
    order.emit(None, "br", " label ", function.local("loop_entry"))
    loop_entry = function.append_block("loop_entry")
    loop_entry.emit(
        "is_big",
        "phi",
        " i1 [ false, ",
        function.local("little"),
        " ], [ ",
        function.local("order_big"),
        ", ",
        function.local("order"),
        " ]",
    )
    loop_entry.emit("index_ptr", "alloca", " i64")
    loop_entry.emit(None, "store", " i64 0, ptr ", function.local("index_ptr"))
    loop_entry.emit(None, "br", " label ", function.local("loop_cond"))
    loop_cond = function.append_block("loop_cond")
    loop_cond.emit("index", "load", " i64, ptr ", function.local("index_ptr"))
    loop_cond.emit(
        "done", "icmp", " uge i64 ", function.local("index"), ", ", function.local("count")
    )
    loop_cond.emit(
        None,
        "br",
        " i1 ",
        function.local("done"),
        ", label ",
        function.local("finish"),
        ", label ",
        function.local("loop_body"),
    )
    loop_body = function.append_block("loop_body")
    loop_body.emit(
        "from_end_base", "sub", " i64 ", function.local("count"), ", ", function.local("index")
    )
    loop_body.emit("from_end", "sub", " i64 ", function.local("from_end_base"), ", 1")
    loop_body.emit(
        "source_index",
        "select",
        " i1 ",
        function.local("is_big"),
        ", i64 ",
        function.local("from_end"),
        ", i64 ",
        function.local("index"),
    )
    loop_body.emit("shift", "mul", " i64 ", function.local("source_index"), ", 8")
    loop_body.emit("shift_ok", "icmp", " ult i64 ", function.local("shift"), ", 64")
    loop_body.emit(
        None,
        "br",
        " i1 ",
        function.local("shift_ok"),
        ", label ",
        function.local("shift_value"),
        ", label ",
        function.local("zero_byte"),
    )
    shift_value = function.append_block("shift_value")
    shift_value.emit(
        "shifted", "lshr", " i64 ", function.local("value"), ", ", function.local("shift")
    )
    shift_value.emit("byte", "trunc", " i64 ", function.local("shifted"), " to i8")
    shift_value.emit(None, "br", " label ", function.local("store"))
    zero_byte = function.append_block("zero_byte")
    zero_byte.emit(None, "br", " label ", function.local("store"))
    store = function.append_block("store")
    store.emit(
        "stored_byte",
        "phi",
        " i8 [ ",
        function.local("byte"),
        ", ",
        function.local("shift_value"),
        " ], [ 0, ",
        function.local("zero_byte"),
        " ]",
    )
    store.emit(
        "dst",
        "getelementptr",
        " i8, ptr ",
        function.local("data"),
        ", i64 ",
        function.local("index"),
    )
    store.emit(
        None, "store", " i8 ", function.local("stored_byte"), ", ptr ", function.local("dst")
    )
    store.emit("next", "add", " i64 ", function.local("index"), ", 1")
    store.emit(
        None, "store", " i64 ", function.local("next"), ", ptr ", function.local("index_ptr")
    )
    store.emit(None, "br", " label ", function.local("loop_cond"))
    finish = function.append_block("finish")
    finish.emit(None, "ret", " ptr ", function.local("out"))


def _build___xcc_aot_parse_int(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_parse_int")
    entry = function.append_block("entry")
    entry.emit("text_null", "icmp", " eq ptr ", function.local("text"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("text_null"),
        ", label ",
        function.local("zero"),
        ", label ",
        function.local("parse"),
    )
    parse = function.append_block("parse")
    parse.emit("base32", "trunc", " i64 ", function.local("base"), " to i32")
    parse.emit(
        "value",
        "call",
        " i64 ",
        module.symbol("strtoll"),
        "(ptr ",
        function.local("text"),
        ", ptr null, i32 ",
        function.local("base32"),
        ")",
    )
    parse.emit(None, "ret", " i64 ", function.local("value"))
    zero = function.append_block("zero")
    zero.emit(None, "ret", " i64 0")


def _build___xcc_aot_string_predicate(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_string_predicate")
    entry = function.append_block("entry")
    entry.emit("text_null", "icmp", " eq ptr ", function.local("text"), ", null")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("text_null"),
        ", label ",
        function.local("false"),
        ", label ",
        function.local("nonnull"),
    )
    nonnull = function.append_block("nonnull")
    nonnull.emit(
        "len", "call", " i64 ", module.symbol("strlen"), "(ptr ", function.local("text"), ")"
    )
    nonnull.emit("empty", "icmp", " eq i64 ", function.local("len"), ", 0")
    nonnull.emit(
        None,
        "br",
        " i1 ",
        function.local("empty"),
        ", label ",
        function.local("false"),
        ", label ",
        function.local("loop"),
    )
    loop = function.append_block("loop")
    loop.emit(
        "index",
        "phi",
        " i64 [ 0, ",
        function.local("nonnull"),
        " ], [ ",
        function.local("next"),
        ", ",
        function.local("step"),
        " ]",
    )
    loop.emit(
        "upper_seen",
        "phi",
        " i1 [ false, ",
        function.local("nonnull"),
        " ], [ ",
        function.local("upper_seen_next"),
        ", ",
        function.local("step"),
        " ]",
    )
    loop.emit("done", "icmp", " eq i64 ", function.local("index"), ", ", function.local("len"))
    loop.emit(
        None,
        "br",
        " i1 ",
        function.local("done"),
        ", label ",
        function.local("true"),
        ", label ",
        function.local("check"),
    )
    check = function.append_block("check")
    check.emit(
        "char_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("text"),
        ", i64 ",
        function.local("index"),
    )
    check.emit("char8", "load", " i8, ptr ", function.local("char_ptr"))
    check.emit("char", "zext", " i8 ", function.local("char8"), " to i64")
    check.emit("ge_a", "icmp", " uge i64 ", function.local("char"), ", 97")
    check.emit("le_z", "icmp", " ule i64 ", function.local("char"), ", 122")
    check.emit("lower", "and", " i1 ", function.local("ge_a"), ", ", function.local("le_z"))
    check.emit("ge_A", "icmp", " uge i64 ", function.local("char"), ", 65")
    check.emit("le_Z", "icmp", " ule i64 ", function.local("char"), ", 90")
    check.emit("upper", "and", " i1 ", function.local("ge_A"), ", ", function.local("le_Z"))
    check.emit("alpha", "or", " i1 ", function.local("lower"), ", ", function.local("upper"))
    check.emit("ge_0", "icmp", " uge i64 ", function.local("char"), ", 48")
    check.emit("le_9", "icmp", " ule i64 ", function.local("char"), ", 57")
    check.emit("digit", "and", " i1 ", function.local("ge_0"), ", ", function.local("le_9"))
    check.emit("alnum", "or", " i1 ", function.local("alpha"), ", ", function.local("digit"))
    check.emit("underscore", "icmp", " eq i64 ", function.local("char"), ", 95")
    check.emit(
        "identifier_start",
        "or",
        " i1 ",
        function.local("alpha"),
        ", ",
        function.local("underscore"),
    )
    check.emit(
        "identifier_continue",
        "or",
        " i1 ",
        function.local("alnum"),
        ", ",
        function.local("underscore"),
    )
    check.emit("identifier_first", "icmp", " eq i64 ", function.local("index"), ", 0")
    check.emit(
        "identifier",
        "select",
        " i1 ",
        function.local("identifier_first"),
        ", i1 ",
        function.local("identifier_start"),
        ", i1 ",
        function.local("identifier_continue"),
    )
    check.emit("not_alpha", "xor", " i1 ", function.local("alpha"), ", true")
    check.emit(
        "upper_char_ok", "or", " i1 ", function.local("upper"), ", ", function.local("not_alpha")
    )
    check.emit("ge_tab", "icmp", " uge i64 ", function.local("char"), ", 9")
    check.emit("le_cr", "icmp", " ule i64 ", function.local("char"), ", 13")
    check.emit(
        "space_control", "and", " i1 ", function.local("ge_tab"), ", ", function.local("le_cr")
    )
    check.emit("is_space", "icmp", " eq i64 ", function.local("char"), ", 32")
    check.emit(
        "space", "or", " i1 ", function.local("space_control"), ", ", function.local("is_space")
    )
    check.emit("mode_alpha", "icmp", " eq i64 ", function.local("mode"), ", 1")
    check.emit("mode_digit", "icmp", " eq i64 ", function.local("mode"), ", 2")
    check.emit("mode_alnum", "icmp", " eq i64 ", function.local("mode"), ", 3")
    check.emit("mode_space", "icmp", " eq i64 ", function.local("mode"), ", 4")
    check.emit("mode_identifier", "icmp", " eq i64 ", function.local("mode"), ", 5")
    check.emit("mode_upper", "icmp", " eq i64 ", function.local("mode"), ", 6")
    check.emit(
        "ok_alpha", "and", " i1 ", function.local("mode_alpha"), ", ", function.local("alpha")
    )
    check.emit(
        "ok_digit", "and", " i1 ", function.local("mode_digit"), ", ", function.local("digit")
    )
    check.emit(
        "ok_alnum", "and", " i1 ", function.local("mode_alnum"), ", ", function.local("alnum")
    )
    check.emit(
        "ok_space", "and", " i1 ", function.local("mode_space"), ", ", function.local("space")
    )
    check.emit(
        "ok_identifier",
        "and",
        " i1 ",
        function.local("mode_identifier"),
        ", ",
        function.local("identifier"),
    )
    check.emit(
        "ok_upper",
        "and",
        " i1 ",
        function.local("mode_upper"),
        ", ",
        function.local("upper_char_ok"),
    )
    check.emit(
        "ok_alpha_digit", "or", " i1 ", function.local("ok_alpha"), ", ", function.local("ok_digit")
    )
    check.emit(
        "ok_alnum_space", "or", " i1 ", function.local("ok_alnum"), ", ", function.local("ok_space")
    )
    check.emit(
        "ok_basic",
        "or",
        " i1 ",
        function.local("ok_alpha_digit"),
        ", ",
        function.local("ok_alnum_space"),
    )
    check.emit(
        "ok_named", "or", " i1 ", function.local("ok_basic"), ", ", function.local("ok_identifier")
    )
    check.emit("ok", "or", " i1 ", function.local("ok_named"), ", ", function.local("ok_upper"))
    check.emit(
        None,
        "br",
        " i1 ",
        function.local("ok"),
        ", label ",
        function.local("step"),
        ", label ",
        function.local("false"),
    )
    step = function.append_block("step")
    step.emit(
        "upper_seen_next", "or", " i1 ", function.local("upper_seen"), ", ", function.local("upper")
    )
    step.emit("next", "add", " i64 ", function.local("index"), ", 1")
    step.emit(None, "br", " label ", function.local("loop"))
    true = function.append_block("true")
    true.emit("done_mode_upper", "icmp", " eq i64 ", function.local("mode"), ", 6")
    true.emit("done_not_upper", "xor", " i1 ", function.local("done_mode_upper"), ", true")
    true.emit(
        "done_valid",
        "or",
        " i1 ",
        function.local("done_not_upper"),
        ", ",
        function.local("upper_seen"),
    )
    true.emit(None, "ret", " i1 ", function.local("done_valid"))
    false = function.append_block("false")
    false.emit(None, "ret", " i1 false")


def _build___xcc_aot_c_argv_to_tuple(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_c_argv_to_tuple")
    entry = function.append_block("entry")
    entry.emit("argc", "sext", " i32 ", function.local("argc32"), " to i64")
    entry.emit(
        "tuple",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_new"),
        "(i64 ",
        function.local("argc"),
        ")",
    )
    entry.emit("index_ptr", "alloca", " i64")
    entry.emit(None, "store", " i64 0, ptr ", function.local("index_ptr"))
    entry.emit(None, "br", " label ", function.local("copy_cond"))
    copy_cond = function.append_block("copy_cond")
    copy_cond.emit("index", "load", " i64, ptr ", function.local("index_ptr"))
    copy_cond.emit(
        "done", "icmp", " uge i64 ", function.local("index"), ", ", function.local("argc")
    )
    copy_cond.emit(
        None,
        "br",
        " i1 ",
        function.local("done"),
        ", label ",
        function.local("done_block"),
        ", label ",
        function.local("copy_body"),
    )
    copy_body = function.append_block("copy_body")
    copy_body.emit(
        "src_slot",
        "getelementptr",
        " ptr, ptr ",
        function.local("argv"),
        ", i64 ",
        function.local("index"),
    )
    copy_body.emit("item", "load", " ptr, ptr ", function.local("src_slot"))
    copy_body.emit(
        None,
        "call",
        " void ",
        module.symbol("__xcc_aot_tuple_set"),
        "(ptr ",
        function.local("tuple"),
        ", i64 ",
        function.local("index"),
        ", ptr ",
        function.local("item"),
        ")",
    )
    copy_body.emit("next", "add", " i64 ", function.local("index"), ", 1")
    copy_body.emit(
        None, "store", " i64 ", function.local("next"), ", ptr ", function.local("index_ptr")
    )
    copy_body.emit(None, "br", " label ", function.local("copy_cond"))
    done_block = function.append_block("done_block")
    done_block.emit(None, "ret", " ptr ", function.local("tuple"))


def _build___xcc_aot_execvp_tuple(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_execvp_tuple")
    entry = function.append_block("entry")
    entry.emit(
        "argc",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_tuple_len"),
        "(ptr ",
        function.local("argv_tuple"),
        ")",
    )
    entry.emit("argv_count", "add", " i64 ", function.local("argc"), ", 1")
    entry.emit("argv_bytes", "mul", " i64 ", function.local("argv_count"), ", 8")
    entry.emit(
        "argv", "call", " ptr ", module.symbol("malloc"), "(i64 ", function.local("argv_bytes"), ")"
    )
    entry.emit("index_ptr", "alloca", " i64")
    entry.emit(None, "store", " i64 0, ptr ", function.local("index_ptr"))
    entry.emit(None, "br", " label ", function.local("copy_cond"))
    copy_cond = function.append_block("copy_cond")
    copy_cond.emit("index", "load", " i64, ptr ", function.local("index_ptr"))
    copy_cond.emit(
        "done", "icmp", " uge i64 ", function.local("index"), ", ", function.local("argc")
    )
    copy_cond.emit(
        None,
        "br",
        " i1 ",
        function.local("done"),
        ", label ",
        function.local("exec"),
        ", label ",
        function.local("copy_body"),
    )
    copy_body = function.append_block("copy_body")
    copy_body.emit(
        "item",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_get"),
        "(ptr ",
        function.local("argv_tuple"),
        ", i64 ",
        function.local("index"),
        ")",
    )
    copy_body.emit(
        "slot",
        "getelementptr",
        " ptr, ptr ",
        function.local("argv"),
        ", i64 ",
        function.local("index"),
    )
    copy_body.emit(None, "store", " ptr ", function.local("item"), ", ptr ", function.local("slot"))
    copy_body.emit("next", "add", " i64 ", function.local("index"), ", 1")
    copy_body.emit(
        None, "store", " i64 ", function.local("next"), ", ptr ", function.local("index_ptr")
    )
    copy_body.emit(None, "br", " label ", function.local("copy_cond"))
    exec = function.append_block("exec")
    exec.emit(
        "null_slot",
        "getelementptr",
        " ptr, ptr ",
        function.local("argv"),
        ", i64 ",
        function.local("argc"),
    )
    exec.emit(None, "store", " ptr null, ptr ", function.local("null_slot"))
    exec.emit(
        "program",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_get"),
        "(ptr ",
        function.local("argv_tuple"),
        ", i64 0)",
    )
    exec.emit("pid", "call", " i32 ", module.symbol("fork"), "()")
    exec.emit("fork_failed", "icmp", " slt i32 ", function.local("pid"), ", 0")
    exec.emit(
        None,
        "br",
        " i1 ",
        function.local("fork_failed"),
        ", label ",
        function.local("fail"),
        ", label ",
        function.local("fork_ok"),
    )
    fork_ok = function.append_block("fork_ok")
    fork_ok.emit("is_child", "icmp", " eq i32 ", function.local("pid"), ", 0")
    fork_ok.emit(
        None,
        "br",
        " i1 ",
        function.local("is_child"),
        ", label ",
        function.local("child"),
        ", label ",
        function.local("parent"),
    )
    child = function.append_block("child")
    child.emit(
        "exec_result",
        "call",
        " i32 ",
        module.symbol("execvp"),
        "(ptr ",
        function.local("program"),
        ", ptr ",
        function.local("argv"),
        ")",
    )
    child.emit(None, "call", " void ", module.symbol("_exit"), "(i32 127)")
    child.emit(None, "unreachable")
    parent = function.append_block("parent")
    parent.emit("status_ptr", "alloca", " i32")
    parent.emit(
        "waited",
        "call",
        " i32 ",
        module.symbol("waitpid"),
        "(i32 ",
        function.local("pid"),
        ", ptr ",
        function.local("status_ptr"),
        ", i32 0)",
    )
    parent.emit("wait_failed", "icmp", " slt i32 ", function.local("waited"), ", 0")
    parent.emit(
        None,
        "br",
        " i1 ",
        function.local("wait_failed"),
        ", label ",
        function.local("fail"),
        ", label ",
        function.local("decode"),
    )
    decode = function.append_block("decode")
    decode.emit("status", "load", " i32, ptr ", function.local("status_ptr"))
    decode.emit("shifted", "lshr", " i32 ", function.local("status"), ", 8")
    decode.emit("exit_code", "and", " i32 ", function.local("shifted"), ", 255")
    decode.emit(None, "ret", " i32 ", function.local("exit_code"))
    fail = function.append_block("fail")
    fail.emit(None, "ret", " i32 1")


def _build___xcc_aot_lexer_translate_source(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_lexer_translate_source")
    entry = function.append_block("entry")
    entry.emit(
        "len", "call", " i64 ", module.symbol("strlen"), "(ptr ", function.local("source"), ")"
    )
    entry.emit("cap", "add", " i64 ", function.local("len"), ", 1")
    entry.emit("tmp", "call", " ptr ", module.symbol("malloc"), "(i64 ", function.local("cap"), ")")
    entry.emit("out", "call", " ptr ", module.symbol("malloc"), "(i64 ", function.local("cap"), ")")
    entry.emit("norm_i_ptr", "alloca", " i64")
    entry.emit("norm_j_ptr", "alloca", " i64")
    entry.emit(None, "store", " i64 0, ptr ", function.local("norm_i_ptr"))
    entry.emit(None, "store", " i64 0, ptr ", function.local("norm_j_ptr"))
    entry.emit(None, "br", " label ", function.local("norm_cond"))
    norm_cond = function.append_block("norm_cond")
    norm_cond.emit("norm_i", "load", " i64, ptr ", function.local("norm_i_ptr"))
    norm_cond.emit(
        "norm_done", "icmp", " uge i64 ", function.local("norm_i"), ", ", function.local("len")
    )
    norm_cond.emit(
        None,
        "br",
        " i1 ",
        function.local("norm_done"),
        ", label ",
        function.local("norm_end"),
        ", label ",
        function.local("norm_body"),
    )
    norm_body = function.append_block("norm_body")
    norm_body.emit("norm_i0", "load", " i64, ptr ", function.local("norm_i_ptr"))
    norm_body.emit(
        "norm_src_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("source"),
        ", i64 ",
        function.local("norm_i0"),
    )
    norm_body.emit("norm_ch", "load", " i8, ptr ", function.local("norm_src_ptr"))
    norm_body.emit("norm_is_cr", "icmp", " eq i8 ", function.local("norm_ch"), ", 13")
    norm_body.emit(
        None,
        "br",
        " i1 ",
        function.local("norm_is_cr"),
        ", label ",
        function.local("norm_cr"),
        ", label ",
        function.local("norm_not_cr"),
    )
    norm_cr = function.append_block("norm_cr")
    norm_cr.emit("norm_cr_i", "load", " i64, ptr ", function.local("norm_i_ptr"))
    norm_cr.emit("norm_cr_next", "add", " i64 ", function.local("norm_cr_i"), ", 1")
    norm_cr.emit(
        "norm_cr_has_next",
        "icmp",
        " ult i64 ",
        function.local("norm_cr_next"),
        ", ",
        function.local("len"),
    )
    norm_cr.emit(
        None,
        "br",
        " i1 ",
        function.local("norm_cr_has_next"),
        ", label ",
        function.local("norm_cr_load"),
        ", label ",
        function.local("norm_cr_single"),
    )
    norm_cr_load = function.append_block("norm_cr_load")
    norm_cr_load.emit(
        "norm_cr_next_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("source"),
        ", i64 ",
        function.local("norm_cr_next"),
    )
    norm_cr_load.emit("norm_cr_next_ch", "load", " i8, ptr ", function.local("norm_cr_next_ptr"))
    norm_cr_load.emit("norm_cr_is_lf", "icmp", " eq i8 ", function.local("norm_cr_next_ch"), ", 10")
    norm_cr_load.emit(
        None,
        "br",
        " i1 ",
        function.local("norm_cr_is_lf"),
        ", label ",
        function.local("norm_crlf"),
        ", label ",
        function.local("norm_cr_single"),
    )
    norm_crlf = function.append_block("norm_crlf")
    norm_crlf.emit("norm_crlf_i", "load", " i64, ptr ", function.local("norm_i_ptr"))
    norm_crlf.emit("norm_crlf_j", "load", " i64, ptr ", function.local("norm_j_ptr"))
    norm_crlf.emit(
        "norm_crlf_dst",
        "getelementptr",
        " i8, ptr ",
        function.local("tmp"),
        ", i64 ",
        function.local("norm_crlf_j"),
    )
    norm_crlf.emit(None, "store", " i8 10, ptr ", function.local("norm_crlf_dst"))
    norm_crlf.emit("norm_crlf_next_i", "add", " i64 ", function.local("norm_crlf_i"), ", 2")
    norm_crlf.emit("norm_crlf_next_j", "add", " i64 ", function.local("norm_crlf_j"), ", 1")
    norm_crlf.emit(
        None,
        "store",
        " i64 ",
        function.local("norm_crlf_next_i"),
        ", ptr ",
        function.local("norm_i_ptr"),
    )
    norm_crlf.emit(
        None,
        "store",
        " i64 ",
        function.local("norm_crlf_next_j"),
        ", ptr ",
        function.local("norm_j_ptr"),
    )
    norm_crlf.emit(None, "br", " label ", function.local("norm_cond"))
    norm_cr_single = function.append_block("norm_cr_single")
    norm_cr_single.emit("norm_cr_single_i", "load", " i64, ptr ", function.local("norm_i_ptr"))
    norm_cr_single.emit("norm_cr_single_j", "load", " i64, ptr ", function.local("norm_j_ptr"))
    norm_cr_single.emit(
        "norm_cr_single_dst",
        "getelementptr",
        " i8, ptr ",
        function.local("tmp"),
        ", i64 ",
        function.local("norm_cr_single_j"),
    )
    norm_cr_single.emit(None, "store", " i8 10, ptr ", function.local("norm_cr_single_dst"))
    norm_cr_single.emit(
        "norm_cr_single_next_i", "add", " i64 ", function.local("norm_cr_single_i"), ", 1"
    )
    norm_cr_single.emit(
        "norm_cr_single_next_j", "add", " i64 ", function.local("norm_cr_single_j"), ", 1"
    )
    norm_cr_single.emit(
        None,
        "store",
        " i64 ",
        function.local("norm_cr_single_next_i"),
        ", ptr ",
        function.local("norm_i_ptr"),
    )
    norm_cr_single.emit(
        None,
        "store",
        " i64 ",
        function.local("norm_cr_single_next_j"),
        ", ptr ",
        function.local("norm_j_ptr"),
    )
    norm_cr_single.emit(None, "br", " label ", function.local("norm_cond"))
    norm_not_cr = function.append_block("norm_not_cr")
    norm_not_cr.emit("tri_i", "load", " i64, ptr ", function.local("norm_i_ptr"))
    norm_not_cr.emit("tri_is_q0", "icmp", " eq i8 ", function.local("norm_ch"), ", 63")
    norm_not_cr.emit("tri_i2", "add", " i64 ", function.local("tri_i"), ", 2")
    norm_not_cr.emit(
        "tri_has_len", "icmp", " ult i64 ", function.local("tri_i2"), ", ", function.local("len")
    )
    norm_not_cr.emit(
        "tri_maybe", "and", " i1 ", function.local("tri_is_q0"), ", ", function.local("tri_has_len")
    )
    norm_not_cr.emit(
        None,
        "br",
        " i1 ",
        function.local("tri_maybe"),
        ", label ",
        function.local("tri_load"),
        ", label ",
        function.local("norm_copy"),
    )
    tri_load = function.append_block("tri_load")
    tri_load.emit("tri_i1", "add", " i64 ", function.local("tri_i"), ", 1")
    tri_load.emit(
        "tri_second_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("source"),
        ", i64 ",
        function.local("tri_i1"),
    )
    tri_load.emit("tri_second", "load", " i8, ptr ", function.local("tri_second_ptr"))
    tri_load.emit(
        "tri_third_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("source"),
        ", i64 ",
        function.local("tri_i2"),
    )
    tri_load.emit("tri_third", "load", " i8, ptr ", function.local("tri_third_ptr"))
    tri_load.emit("tri_is_q1", "icmp", " eq i8 ", function.local("tri_second"), ", 63")
    tri_load.emit(
        None,
        "br",
        " i1 ",
        function.local("tri_is_q1"),
        ", label ",
        function.local("tri_replace"),
        ", label ",
        function.local("norm_copy"),
    )
    tri_replace = function.append_block("tri_replace")
    tri_replace.emit("tri_eq", "icmp", " eq i8 ", function.local("tri_third"), ", 61")
    tri_replace.emit("tri_rep1", "select", " i1 ", function.local("tri_eq"), ", i8 35, i8 0")
    tri_replace.emit("tri_slash", "icmp", " eq i8 ", function.local("tri_third"), ", 47")
    tri_replace.emit(
        "tri_rep2",
        "select",
        " i1 ",
        function.local("tri_slash"),
        ", i8 92, i8 ",
        function.local("tri_rep1"),
    )
    tri_replace.emit("tri_quote", "icmp", " eq i8 ", function.local("tri_third"), ", 39")
    tri_replace.emit(
        "tri_rep3",
        "select",
        " i1 ",
        function.local("tri_quote"),
        ", i8 94, i8 ",
        function.local("tri_rep2"),
    )
    tri_replace.emit("tri_lparen", "icmp", " eq i8 ", function.local("tri_third"), ", 40")
    tri_replace.emit(
        "tri_rep4",
        "select",
        " i1 ",
        function.local("tri_lparen"),
        ", i8 91, i8 ",
        function.local("tri_rep3"),
    )
    tri_replace.emit("tri_rparen", "icmp", " eq i8 ", function.local("tri_third"), ", 41")
    tri_replace.emit(
        "tri_rep5",
        "select",
        " i1 ",
        function.local("tri_rparen"),
        ", i8 93, i8 ",
        function.local("tri_rep4"),
    )
    tri_replace.emit("tri_bang", "icmp", " eq i8 ", function.local("tri_third"), ", 33")
    tri_replace.emit(
        "tri_rep6",
        "select",
        " i1 ",
        function.local("tri_bang"),
        ", i8 124, i8 ",
        function.local("tri_rep5"),
    )
    tri_replace.emit("tri_lt", "icmp", " eq i8 ", function.local("tri_third"), ", 60")
    tri_replace.emit(
        "tri_rep7",
        "select",
        " i1 ",
        function.local("tri_lt"),
        ", i8 123, i8 ",
        function.local("tri_rep6"),
    )
    tri_replace.emit("tri_gt", "icmp", " eq i8 ", function.local("tri_third"), ", 62")
    tri_replace.emit(
        "tri_rep8",
        "select",
        " i1 ",
        function.local("tri_gt"),
        ", i8 125, i8 ",
        function.local("tri_rep7"),
    )
    tri_replace.emit("tri_dash", "icmp", " eq i8 ", function.local("tri_third"), ", 45")
    tri_replace.emit(
        "tri_rep9",
        "select",
        " i1 ",
        function.local("tri_dash"),
        ", i8 126, i8 ",
        function.local("tri_rep8"),
    )
    tri_replace.emit("tri_has_rep", "icmp", " ne i8 ", function.local("tri_rep9"), ", 0")
    tri_replace.emit(
        None,
        "br",
        " i1 ",
        function.local("tri_has_rep"),
        ", label ",
        function.local("tri_emit"),
        ", label ",
        function.local("norm_copy"),
    )
    tri_emit = function.append_block("tri_emit")
    tri_emit.emit("tri_emit_i", "load", " i64, ptr ", function.local("norm_i_ptr"))
    tri_emit.emit("tri_emit_j", "load", " i64, ptr ", function.local("norm_j_ptr"))
    tri_emit.emit(
        "tri_emit_dst",
        "getelementptr",
        " i8, ptr ",
        function.local("tmp"),
        ", i64 ",
        function.local("tri_emit_j"),
    )
    tri_emit.emit(
        None, "store", " i8 ", function.local("tri_rep9"), ", ptr ", function.local("tri_emit_dst")
    )
    tri_emit.emit("tri_emit_next_i", "add", " i64 ", function.local("tri_emit_i"), ", 3")
    tri_emit.emit("tri_emit_next_j", "add", " i64 ", function.local("tri_emit_j"), ", 1")
    tri_emit.emit(
        None,
        "store",
        " i64 ",
        function.local("tri_emit_next_i"),
        ", ptr ",
        function.local("norm_i_ptr"),
    )
    tri_emit.emit(
        None,
        "store",
        " i64 ",
        function.local("tri_emit_next_j"),
        ", ptr ",
        function.local("norm_j_ptr"),
    )
    tri_emit.emit(None, "br", " label ", function.local("norm_cond"))
    norm_copy = function.append_block("norm_copy")
    norm_copy.emit("norm_copy_i", "load", " i64, ptr ", function.local("norm_i_ptr"))
    norm_copy.emit("norm_copy_j", "load", " i64, ptr ", function.local("norm_j_ptr"))
    norm_copy.emit(
        "norm_copy_dst",
        "getelementptr",
        " i8, ptr ",
        function.local("tmp"),
        ", i64 ",
        function.local("norm_copy_j"),
    )
    norm_copy.emit(
        None, "store", " i8 ", function.local("norm_ch"), ", ptr ", function.local("norm_copy_dst")
    )
    norm_copy.emit("norm_copy_next_i", "add", " i64 ", function.local("norm_copy_i"), ", 1")
    norm_copy.emit("norm_copy_next_j", "add", " i64 ", function.local("norm_copy_j"), ", 1")
    norm_copy.emit(
        None,
        "store",
        " i64 ",
        function.local("norm_copy_next_i"),
        ", ptr ",
        function.local("norm_i_ptr"),
    )
    norm_copy.emit(
        None,
        "store",
        " i64 ",
        function.local("norm_copy_next_j"),
        ", ptr ",
        function.local("norm_j_ptr"),
    )
    norm_copy.emit(None, "br", " label ", function.local("norm_cond"))
    norm_end = function.append_block("norm_end")
    norm_end.emit("norm_len", "load", " i64, ptr ", function.local("norm_j_ptr"))
    norm_end.emit(
        "tmp_zero_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("tmp"),
        ", i64 ",
        function.local("norm_len"),
    )
    norm_end.emit(None, "store", " i8 0, ptr ", function.local("tmp_zero_ptr"))
    norm_end.emit("splice_i_ptr", "alloca", " i64")
    norm_end.emit("splice_j_ptr", "alloca", " i64")
    norm_end.emit(None, "store", " i64 0, ptr ", function.local("splice_i_ptr"))
    norm_end.emit(None, "store", " i64 0, ptr ", function.local("splice_j_ptr"))
    norm_end.emit(None, "br", " label ", function.local("splice_cond"))
    splice_cond = function.append_block("splice_cond")
    splice_cond.emit("splice_i", "load", " i64, ptr ", function.local("splice_i_ptr"))
    splice_cond.emit(
        "splice_done",
        "icmp",
        " uge i64 ",
        function.local("splice_i"),
        ", ",
        function.local("norm_len"),
    )
    splice_cond.emit(
        None,
        "br",
        " i1 ",
        function.local("splice_done"),
        ", label ",
        function.local("splice_end"),
        ", label ",
        function.local("splice_body"),
    )
    splice_body = function.append_block("splice_body")
    splice_body.emit("splice_i0", "load", " i64, ptr ", function.local("splice_i_ptr"))
    splice_body.emit(
        "splice_src_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("tmp"),
        ", i64 ",
        function.local("splice_i0"),
    )
    splice_body.emit("splice_ch", "load", " i8, ptr ", function.local("splice_src_ptr"))
    splice_body.emit("splice_is_backslash", "icmp", " eq i8 ", function.local("splice_ch"), ", 92")
    splice_body.emit("splice_next_i", "add", " i64 ", function.local("splice_i0"), ", 1")
    splice_body.emit(
        "splice_has_next",
        "icmp",
        " ult i64 ",
        function.local("splice_next_i"),
        ", ",
        function.local("norm_len"),
    )
    splice_body.emit(
        "splice_maybe",
        "and",
        " i1 ",
        function.local("splice_is_backslash"),
        ", ",
        function.local("splice_has_next"),
    )
    splice_body.emit(
        None,
        "br",
        " i1 ",
        function.local("splice_maybe"),
        ", label ",
        function.local("splice_load_next"),
        ", label ",
        function.local("splice_copy"),
    )
    splice_load_next = function.append_block("splice_load_next")
    splice_load_next.emit(
        "splice_next_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("tmp"),
        ", i64 ",
        function.local("splice_next_i"),
    )
    splice_load_next.emit("splice_next_ch", "load", " i8, ptr ", function.local("splice_next_ptr"))
    splice_load_next.emit(
        "splice_is_lf", "icmp", " eq i8 ", function.local("splice_next_ch"), ", 10"
    )
    splice_load_next.emit(
        None,
        "br",
        " i1 ",
        function.local("splice_is_lf"),
        ", label ",
        function.local("splice_skip"),
        ", label ",
        function.local("splice_copy"),
    )
    splice_skip = function.append_block("splice_skip")
    splice_skip.emit("splice_skip_i", "load", " i64, ptr ", function.local("splice_i_ptr"))
    splice_skip.emit("splice_skip_next_i", "add", " i64 ", function.local("splice_skip_i"), ", 2")
    splice_skip.emit(
        None,
        "store",
        " i64 ",
        function.local("splice_skip_next_i"),
        ", ptr ",
        function.local("splice_i_ptr"),
    )
    splice_skip.emit(None, "br", " label ", function.local("splice_cond"))
    splice_copy = function.append_block("splice_copy")
    splice_copy.emit("splice_copy_i", "load", " i64, ptr ", function.local("splice_i_ptr"))
    splice_copy.emit("splice_copy_j", "load", " i64, ptr ", function.local("splice_j_ptr"))
    splice_copy.emit(
        "splice_dst",
        "getelementptr",
        " i8, ptr ",
        function.local("out"),
        ", i64 ",
        function.local("splice_copy_j"),
    )
    splice_copy.emit(
        None, "store", " i8 ", function.local("splice_ch"), ", ptr ", function.local("splice_dst")
    )
    splice_copy.emit("splice_copy_next_i", "add", " i64 ", function.local("splice_copy_i"), ", 1")
    splice_copy.emit("splice_copy_next_j", "add", " i64 ", function.local("splice_copy_j"), ", 1")
    splice_copy.emit(
        None,
        "store",
        " i64 ",
        function.local("splice_copy_next_i"),
        ", ptr ",
        function.local("splice_i_ptr"),
    )
    splice_copy.emit(
        None,
        "store",
        " i64 ",
        function.local("splice_copy_next_j"),
        ", ptr ",
        function.local("splice_j_ptr"),
    )
    splice_copy.emit(None, "br", " label ", function.local("splice_cond"))
    splice_end = function.append_block("splice_end")
    splice_end.emit("out_len", "load", " i64, ptr ", function.local("splice_j_ptr"))
    splice_end.emit(
        "out_zero_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("out"),
        ", i64 ",
        function.local("out_len"),
    )
    splice_end.emit(None, "store", " i8 0, ptr ", function.local("out_zero_ptr"))
    splice_end.emit(None, "ret", " ptr ", function.local("out"))


def _build___xcc_aot_lexer_append_summary_token(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_lexer_append_summary_token")
    entry = function.append_block("entry")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("first"),
        ", label ",
        function.local("token"),
        ", label ",
        function.local("sep"),
    )
    sep = function.append_block("sep")
    sep.emit(
        "sep_dst",
        "getelementptr",
        " i8, ptr ",
        function.local("out"),
        ", i64 ",
        function.local("out_len"),
    )
    sep.emit(
        "sep_remaining", "sub", " i64 ", function.local("cap"), ", ", function.local("out_len")
    )
    sep.emit("sep_written", "call", " i32 (ptr, i64, ptr, ...) ", module.symbol("snprintf"), "(")
    sep.continue_("  ptr ", function.local("sep_dst"), ",")
    sep.continue_("  i64 ", function.local("sep_remaining"), ",")
    sep.continue_("  ptr ", module.symbol("__xcc_aot_fmt_sep"))
    sep.continue_(")")
    sep.emit("sep_written64", "sext", " i32 ", function.local("sep_written"), " to i64")
    sep.emit(
        "sep_len", "add", " i64 ", function.local("out_len"), ", ", function.local("sep_written64")
    )
    sep.emit(None, "br", " label ", function.local("token"))
    token = function.append_block("token")
    token.emit(
        "token_len",
        "phi",
        " i64 [ ",
        function.local("out_len"),
        ", ",
        function.local("entry"),
        " ], [ ",
        function.local("sep_len"),
        ", ",
        function.local("sep"),
        " ]",
    )
    token.emit(
        "token_dst",
        "getelementptr",
        " i8, ptr ",
        function.local("out"),
        ", i64 ",
        function.local("token_len"),
    )
    token.emit(
        "token_remaining", "sub", " i64 ", function.local("cap"), ", ", function.local("token_len")
    )
    token.emit("lex_len32", "trunc", " i64 ", function.local("lex_len"), " to i32")
    token.emit(
        "token_written", "call", " i32 (ptr, i64, ptr, ...) ", module.symbol("snprintf"), "("
    )
    token.continue_("  ptr ", function.local("token_dst"), ",")
    token.continue_("  i64 ", function.local("token_remaining"), ",")
    token.continue_("  ptr ", module.symbol("__xcc_aot_fmt_token"), ",")
    token.continue_("  ptr ", function.local("kind"), ",")
    token.continue_("  i32 ", function.local("lex_len32"), ",")
    token.continue_("  ptr ", function.local("lexeme"), ",")
    token.continue_("  i64 ", function.local("line"), ",")
    token.continue_("  i64 ", function.local("column"))
    token.continue_(")")
    token.emit("token_written64", "sext", " i32 ", function.local("token_written"), " to i64")
    token.emit(
        "new_len",
        "add",
        " i64 ",
        function.local("token_len"),
        ", ",
        function.local("token_written64"),
    )
    token.emit(None, "ret", " i64 ", function.local("new_len"))


def _build___xcc_aot_lexer_append_summary_eof(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_lexer_append_summary_eof")
    entry = function.append_block("entry")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("first"),
        ", label ",
        function.local("token"),
        ", label ",
        function.local("sep"),
    )
    sep = function.append_block("sep")
    sep.emit(
        "sep_dst",
        "getelementptr",
        " i8, ptr ",
        function.local("out"),
        ", i64 ",
        function.local("out_len"),
    )
    sep.emit(
        "sep_remaining", "sub", " i64 ", function.local("cap"), ", ", function.local("out_len")
    )
    sep.emit("sep_written", "call", " i32 (ptr, i64, ptr, ...) ", module.symbol("snprintf"), "(")
    sep.continue_("  ptr ", function.local("sep_dst"), ",")
    sep.continue_("  i64 ", function.local("sep_remaining"), ",")
    sep.continue_("  ptr ", module.symbol("__xcc_aot_fmt_sep"))
    sep.continue_(")")
    sep.emit("sep_written64", "sext", " i32 ", function.local("sep_written"), " to i64")
    sep.emit(
        "sep_len", "add", " i64 ", function.local("out_len"), ", ", function.local("sep_written64")
    )
    sep.emit(None, "br", " label ", function.local("token"))
    token = function.append_block("token")
    token.emit(
        "token_len",
        "phi",
        " i64 [ ",
        function.local("out_len"),
        ", ",
        function.local("entry"),
        " ], [ ",
        function.local("sep_len"),
        ", ",
        function.local("sep"),
        " ]",
    )
    token.emit(
        "token_dst",
        "getelementptr",
        " i8, ptr ",
        function.local("out"),
        ", i64 ",
        function.local("token_len"),
    )
    token.emit(
        "token_remaining", "sub", " i64 ", function.local("cap"), ", ", function.local("token_len")
    )
    token.emit(
        "token_written", "call", " i32 (ptr, i64, ptr, ...) ", module.symbol("snprintf"), "("
    )
    token.continue_("  ptr ", function.local("token_dst"), ",")
    token.continue_("  i64 ", function.local("token_remaining"), ",")
    token.continue_("  ptr ", module.symbol("__xcc_aot_fmt_eof"), ",")
    token.continue_("  ptr ", module.symbol("__xcc_aot_kind_eof"), ",")
    token.continue_("  i64 ", function.local("line"), ",")
    token.continue_("  i64 ", function.local("column"))
    token.continue_(")")
    token.emit("token_written64", "sext", " i32 ", function.local("token_written"), " to i64")
    token.emit(
        "new_len",
        "add",
        " i64 ",
        function.local("token_len"),
        ", ",
        function.local("token_written64"),
    )
    token.emit(None, "ret", " i64 ", function.local("new_len"))


def _build___xcc_aot_lexer_is_alpha(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_lexer_is_alpha")
    entry = function.append_block("entry")
    entry.emit("ge_upper", "icmp", " uge i8 ", function.local("ch"), ", 65")
    entry.emit("le_upper", "icmp", " ule i8 ", function.local("ch"), ", 90")
    entry.emit(
        "is_upper", "and", " i1 ", function.local("ge_upper"), ", ", function.local("le_upper")
    )
    entry.emit("ge_lower", "icmp", " uge i8 ", function.local("ch"), ", 97")
    entry.emit("le_lower", "icmp", " ule i8 ", function.local("ch"), ", 122")
    entry.emit(
        "is_lower", "and", " i1 ", function.local("ge_lower"), ", ", function.local("le_lower")
    )
    entry.emit(
        "is_alpha", "or", " i1 ", function.local("is_upper"), ", ", function.local("is_lower")
    )
    entry.emit(None, "ret", " i1 ", function.local("is_alpha"))


def _build___xcc_aot_lexer_is_digit(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_lexer_is_digit")
    entry = function.append_block("entry")
    entry.emit("ge_digit", "icmp", " uge i8 ", function.local("ch"), ", 48")
    entry.emit("le_digit", "icmp", " ule i8 ", function.local("ch"), ", 57")
    entry.emit(
        "is_digit", "and", " i1 ", function.local("ge_digit"), ", ", function.local("le_digit")
    )
    entry.emit(None, "ret", " i1 ", function.local("is_digit"))


def _build___xcc_aot_lexer_is_ident_start(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_lexer_is_ident_start")
    entry = function.append_block("entry")
    entry.emit(
        "is_alpha",
        "call",
        " i1 ",
        module.symbol("__xcc_aot_lexer_is_alpha"),
        "(i8 ",
        function.local("ch"),
        ")",
    )
    entry.emit("is_underscore", "icmp", " eq i8 ", function.local("ch"), ", 95")
    entry.emit(
        "is_start", "or", " i1 ", function.local("is_alpha"), ", ", function.local("is_underscore")
    )
    entry.emit(None, "ret", " i1 ", function.local("is_start"))


def _build___xcc_aot_lexer_is_ident_part(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_lexer_is_ident_part")
    entry = function.append_block("entry")
    entry.emit(
        "is_start",
        "call",
        " i1 ",
        module.symbol("__xcc_aot_lexer_is_ident_start"),
        "(i8 ",
        function.local("ch"),
        ")",
    )
    entry.emit(
        "is_digit",
        "call",
        " i1 ",
        module.symbol("__xcc_aot_lexer_is_digit"),
        "(i8 ",
        function.local("ch"),
        ")",
    )
    entry.emit(
        "is_part", "or", " i1 ", function.local("is_start"), ", ", function.local("is_digit")
    )
    entry.emit(None, "ret", " i1 ", function.local("is_part"))


def _build___xcc_aot_lexer_keyword_kind(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_lexer_keyword_kind")
    entry = function.append_block("entry")
    entry.emit("is_len3", "icmp", " eq i64 ", function.local("len"), ", 3")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("is_len3"),
        ", label ",
        function.local("len3"),
        ", label ",
        function.local("check_len6"),
    )
    len3 = function.append_block("len3")
    len3.emit("len3_c0_ptr", "getelementptr", " i8, ptr ", function.local("start"), ", i64 0")
    len3.emit("len3_c0", "load", " i8, ptr ", function.local("len3_c0_ptr"))
    len3.emit("len3_c1_ptr", "getelementptr", " i8, ptr ", function.local("start"), ", i64 1")
    len3.emit("len3_c1", "load", " i8, ptr ", function.local("len3_c1_ptr"))
    len3.emit("len3_c2_ptr", "getelementptr", " i8, ptr ", function.local("start"), ", i64 2")
    len3.emit("len3_c2", "load", " i8, ptr ", function.local("len3_c2_ptr"))
    len3.emit("is_i", "icmp", " eq i8 ", function.local("len3_c0"), ", 105")
    len3.emit("is_n", "icmp", " eq i8 ", function.local("len3_c1"), ", 110")
    len3.emit("is_t", "icmp", " eq i8 ", function.local("len3_c2"), ", 116")
    len3.emit("int_01", "and", " i1 ", function.local("is_i"), ", ", function.local("is_n"))
    len3.emit("is_int", "and", " i1 ", function.local("int_01"), ", ", function.local("is_t"))
    len3.emit(
        "len3_kind",
        "select",
        " i1 ",
        function.local("is_int"),
        ", ptr ",
        module.symbol("__xcc_aot_kind_keyword"),
        ", ptr ",
        module.symbol("__xcc_aot_kind_ident"),
    )
    len3.emit(None, "ret", " ptr ", function.local("len3_kind"))
    check_len6 = function.append_block("check_len6")
    check_len6.emit("is_len6", "icmp", " eq i64 ", function.local("len"), ", 6")
    check_len6.emit(
        None,
        "br",
        " i1 ",
        function.local("is_len6"),
        ", label ",
        function.local("len6"),
        ", label ",
        function.local("ident"),
    )
    len6 = function.append_block("len6")
    len6.emit("len6_c0_ptr", "getelementptr", " i8, ptr ", function.local("start"), ", i64 0")
    len6.emit("len6_c0", "load", " i8, ptr ", function.local("len6_c0_ptr"))
    len6.emit("len6_c1_ptr", "getelementptr", " i8, ptr ", function.local("start"), ", i64 1")
    len6.emit("len6_c1", "load", " i8, ptr ", function.local("len6_c1_ptr"))
    len6.emit("len6_c2_ptr", "getelementptr", " i8, ptr ", function.local("start"), ", i64 2")
    len6.emit("len6_c2", "load", " i8, ptr ", function.local("len6_c2_ptr"))
    len6.emit("len6_c3_ptr", "getelementptr", " i8, ptr ", function.local("start"), ", i64 3")
    len6.emit("len6_c3", "load", " i8, ptr ", function.local("len6_c3_ptr"))
    len6.emit("len6_c4_ptr", "getelementptr", " i8, ptr ", function.local("start"), ", i64 4")
    len6.emit("len6_c4", "load", " i8, ptr ", function.local("len6_c4_ptr"))
    len6.emit("len6_c5_ptr", "getelementptr", " i8, ptr ", function.local("start"), ", i64 5")
    len6.emit("len6_c5", "load", " i8, ptr ", function.local("len6_c5_ptr"))
    len6.emit("is_r", "icmp", " eq i8 ", function.local("len6_c0"), ", 114")
    len6.emit("is_e", "icmp", " eq i8 ", function.local("len6_c1"), ", 101")
    len6.emit("is_t2", "icmp", " eq i8 ", function.local("len6_c2"), ", 116")
    len6.emit("is_u", "icmp", " eq i8 ", function.local("len6_c3"), ", 117")
    len6.emit("is_r2", "icmp", " eq i8 ", function.local("len6_c4"), ", 114")
    len6.emit("is_n2", "icmp", " eq i8 ", function.local("len6_c5"), ", 110")
    len6.emit("return_01", "and", " i1 ", function.local("is_r"), ", ", function.local("is_e"))
    len6.emit(
        "return_02", "and", " i1 ", function.local("return_01"), ", ", function.local("is_t2")
    )
    len6.emit("return_03", "and", " i1 ", function.local("return_02"), ", ", function.local("is_u"))
    len6.emit(
        "return_04", "and", " i1 ", function.local("return_03"), ", ", function.local("is_r2")
    )
    len6.emit(
        "is_return", "and", " i1 ", function.local("return_04"), ", ", function.local("is_n2")
    )
    len6.emit(
        "len6_kind",
        "select",
        " i1 ",
        function.local("is_return"),
        ", ptr ",
        module.symbol("__xcc_aot_kind_keyword"),
        ", ptr ",
        module.symbol("__xcc_aot_kind_ident"),
    )
    len6.emit(None, "ret", " ptr ", function.local("len6_kind"))
    ident = function.append_block("ident")
    ident.emit(None, "ret", " ptr ", module.symbol("__xcc_aot_kind_ident"))


def _build___xcc_aot_lexer_token_summary_for_source(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_lexer_token_summary_for_source")
    entry = function.append_block("entry")
    entry.emit(
        "translated",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_lexer_translate_source"),
        "(ptr ",
        function.local("source"),
        ")",
    )
    entry.emit(
        "len", "call", " i64 ", module.symbol("strlen"), "(ptr ", function.local("translated"), ")"
    )
    entry.emit("scaled_cap", "mul", " i64 ", function.local("len"), ", 64")
    entry.emit("cap", "add", " i64 ", function.local("scaled_cap"), ", 128")
    entry.emit("out", "call", " ptr ", module.symbol("malloc"), "(i64 ", function.local("cap"), ")")
    entry.emit("index_ptr", "alloca", " i64")
    entry.emit("line_ptr", "alloca", " i64")
    entry.emit("column_ptr", "alloca", " i64")
    entry.emit("out_len_ptr", "alloca", " i64")
    entry.emit("first_ptr", "alloca", " i1")
    entry.emit(None, "store", " i64 0, ptr ", function.local("index_ptr"))
    entry.emit(None, "store", " i64 1, ptr ", function.local("line_ptr"))
    entry.emit(None, "store", " i64 1, ptr ", function.local("column_ptr"))
    entry.emit(None, "store", " i64 0, ptr ", function.local("out_len_ptr"))
    entry.emit(None, "store", " i1 true, ptr ", function.local("first_ptr"))
    entry.emit(None, "br", " label ", function.local("scan_cond"))
    scan_cond = function.append_block("scan_cond")
    scan_cond.emit("scan_i", "load", " i64, ptr ", function.local("index_ptr"))
    scan_cond.emit(
        "scan_done", "icmp", " uge i64 ", function.local("scan_i"), ", ", function.local("len")
    )
    scan_cond.emit(
        None,
        "br",
        " i1 ",
        function.local("scan_done"),
        ", label ",
        function.local("emit_eof"),
        ", label ",
        function.local("scan_body"),
    )
    scan_body = function.append_block("scan_body")
    scan_body.emit("scan_i0", "load", " i64, ptr ", function.local("index_ptr"))
    scan_body.emit(
        "scan_ch_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("translated"),
        ", i64 ",
        function.local("scan_i0"),
    )
    scan_body.emit("scan_ch", "load", " i8, ptr ", function.local("scan_ch_ptr"))
    scan_body.emit("is_space", "icmp", " eq i8 ", function.local("scan_ch"), ", 32")
    scan_body.emit("is_tab", "icmp", " eq i8 ", function.local("scan_ch"), ", 9")
    scan_body.emit("is_vtab", "icmp", " eq i8 ", function.local("scan_ch"), ", 11")
    scan_body.emit("is_formfeed", "icmp", " eq i8 ", function.local("scan_ch"), ", 12")
    scan_body.emit("is_newline", "icmp", " eq i8 ", function.local("scan_ch"), ", 10")
    scan_body.emit(
        "ws_01", "or", " i1 ", function.local("is_space"), ", ", function.local("is_tab")
    )
    scan_body.emit(
        "ws_02", "or", " i1 ", function.local("is_vtab"), ", ", function.local("is_formfeed")
    )
    scan_body.emit("ws_03", "or", " i1 ", function.local("ws_01"), ", ", function.local("ws_02"))
    scan_body.emit(
        "is_ws", "or", " i1 ", function.local("ws_03"), ", ", function.local("is_newline")
    )
    scan_body.emit(
        None,
        "br",
        " i1 ",
        function.local("is_ws"),
        ", label ",
        function.local("scan_ws"),
        ", label ",
        function.local("scan_token"),
    )
    scan_ws = function.append_block("scan_ws")
    scan_ws.emit(
        None,
        "br",
        " i1 ",
        function.local("is_newline"),
        ", label ",
        function.local("scan_newline"),
        ", label ",
        function.local("scan_space"),
    )
    scan_newline = function.append_block("scan_newline")
    scan_newline.emit("newline_i", "load", " i64, ptr ", function.local("index_ptr"))
    scan_newline.emit("newline_next_i", "add", " i64 ", function.local("newline_i"), ", 1")
    scan_newline.emit("newline_line", "load", " i64, ptr ", function.local("line_ptr"))
    scan_newline.emit("newline_next_line", "add", " i64 ", function.local("newline_line"), ", 1")
    scan_newline.emit(
        None,
        "store",
        " i64 ",
        function.local("newline_next_i"),
        ", ptr ",
        function.local("index_ptr"),
    )
    scan_newline.emit(
        None,
        "store",
        " i64 ",
        function.local("newline_next_line"),
        ", ptr ",
        function.local("line_ptr"),
    )
    scan_newline.emit(None, "store", " i64 1, ptr ", function.local("column_ptr"))
    scan_newline.emit(None, "br", " label ", function.local("scan_cond"))
    scan_space = function.append_block("scan_space")
    scan_space.emit("space_i", "load", " i64, ptr ", function.local("index_ptr"))
    scan_space.emit("space_next_i", "add", " i64 ", function.local("space_i"), ", 1")
    scan_space.emit("space_column", "load", " i64, ptr ", function.local("column_ptr"))
    scan_space.emit("space_next_column", "add", " i64 ", function.local("space_column"), ", 1")
    scan_space.emit(
        None,
        "store",
        " i64 ",
        function.local("space_next_i"),
        ", ptr ",
        function.local("index_ptr"),
    )
    scan_space.emit(
        None,
        "store",
        " i64 ",
        function.local("space_next_column"),
        ", ptr ",
        function.local("column_ptr"),
    )
    scan_space.emit(None, "br", " label ", function.local("scan_cond"))
    scan_token = function.append_block("scan_token")
    scan_token.emit(
        "is_ident_start",
        "call",
        " i1 ",
        module.symbol("__xcc_aot_lexer_is_ident_start"),
        "(i8 ",
        function.local("scan_ch"),
        ")",
    )
    scan_token.emit(
        None,
        "br",
        " i1 ",
        function.local("is_ident_start"),
        ", label ",
        function.local("ident_start"),
        ", label ",
        function.local("check_number"),
    )
    ident_start = function.append_block("ident_start")
    ident_start.emit("ident_start_i", "load", " i64, ptr ", function.local("index_ptr"))
    ident_start.emit("ident_start_line", "load", " i64, ptr ", function.local("line_ptr"))
    ident_start.emit("ident_start_column", "load", " i64, ptr ", function.local("column_ptr"))
    ident_start.emit(None, "br", " label ", function.local("ident_cond"))
    ident_cond = function.append_block("ident_cond")
    ident_cond.emit("ident_i", "load", " i64, ptr ", function.local("index_ptr"))
    ident_cond.emit(
        "ident_done", "icmp", " uge i64 ", function.local("ident_i"), ", ", function.local("len")
    )
    ident_cond.emit(
        None,
        "br",
        " i1 ",
        function.local("ident_done"),
        ", label ",
        function.local("ident_emit"),
        ", label ",
        function.local("ident_body"),
    )
    ident_body = function.append_block("ident_body")
    ident_body.emit(
        "ident_ch_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("translated"),
        ", i64 ",
        function.local("ident_i"),
    )
    ident_body.emit("ident_ch", "load", " i8, ptr ", function.local("ident_ch_ptr"))
    ident_body.emit(
        "ident_part",
        "call",
        " i1 ",
        module.symbol("__xcc_aot_lexer_is_ident_part"),
        "(i8 ",
        function.local("ident_ch"),
        ")",
    )
    ident_body.emit(
        None,
        "br",
        " i1 ",
        function.local("ident_part"),
        ", label ",
        function.local("ident_advance"),
        ", label ",
        function.local("ident_emit"),
    )
    ident_advance = function.append_block("ident_advance")
    ident_advance.emit("ident_next_i", "add", " i64 ", function.local("ident_i"), ", 1")
    ident_advance.emit("ident_column", "load", " i64, ptr ", function.local("column_ptr"))
    ident_advance.emit("ident_next_column", "add", " i64 ", function.local("ident_column"), ", 1")
    ident_advance.emit(
        None,
        "store",
        " i64 ",
        function.local("ident_next_i"),
        ", ptr ",
        function.local("index_ptr"),
    )
    ident_advance.emit(
        None,
        "store",
        " i64 ",
        function.local("ident_next_column"),
        ", ptr ",
        function.local("column_ptr"),
    )
    ident_advance.emit(None, "br", " label ", function.local("ident_cond"))
    ident_emit = function.append_block("ident_emit")
    ident_emit.emit("ident_end_i", "load", " i64, ptr ", function.local("index_ptr"))
    ident_emit.emit(
        "ident_len",
        "sub",
        " i64 ",
        function.local("ident_end_i"),
        ", ",
        function.local("ident_start_i"),
    )
    ident_emit.emit(
        "ident_kind",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_lexer_keyword_kind"),
        "(ptr ",
        function.local("scan_ch_ptr"),
        ", i64 ",
        function.local("ident_len"),
        ")",
    )
    ident_emit.emit("ident_out_len", "load", " i64, ptr ", function.local("out_len_ptr"))
    ident_emit.emit("ident_first", "load", " i1, ptr ", function.local("first_ptr"))
    ident_emit.emit(
        "ident_new_len", "call", " i64 ", module.symbol("__xcc_aot_lexer_append_summary_token"), "("
    )
    ident_emit.continue_("  ptr ", function.local("out"), ",")
    ident_emit.continue_("  i64 ", function.local("ident_out_len"), ",")
    ident_emit.continue_("  i64 ", function.local("cap"), ",")
    ident_emit.continue_("  i1 ", function.local("ident_first"), ",")
    ident_emit.continue_("  ptr ", function.local("ident_kind"), ",")
    ident_emit.continue_("  ptr ", function.local("scan_ch_ptr"), ",")
    ident_emit.continue_("  i64 ", function.local("ident_len"), ",")
    ident_emit.continue_("  i64 ", function.local("ident_start_line"), ",")
    ident_emit.continue_("  i64 ", function.local("ident_start_column"))
    ident_emit.continue_(")")
    ident_emit.emit(
        None,
        "store",
        " i64 ",
        function.local("ident_new_len"),
        ", ptr ",
        function.local("out_len_ptr"),
    )
    ident_emit.emit(None, "store", " i1 false, ptr ", function.local("first_ptr"))
    ident_emit.emit(None, "br", " label ", function.local("scan_cond"))
    check_number = function.append_block("check_number")
    check_number.emit(
        "is_digit",
        "call",
        " i1 ",
        module.symbol("__xcc_aot_lexer_is_digit"),
        "(i8 ",
        function.local("scan_ch"),
        ")",
    )
    check_number.emit(
        None,
        "br",
        " i1 ",
        function.local("is_digit"),
        ", label ",
        function.local("number_start"),
        ", label ",
        function.local("punct_emit"),
    )
    number_start = function.append_block("number_start")
    number_start.emit("number_start_i", "load", " i64, ptr ", function.local("index_ptr"))
    number_start.emit("number_start_line", "load", " i64, ptr ", function.local("line_ptr"))
    number_start.emit("number_start_column", "load", " i64, ptr ", function.local("column_ptr"))
    number_start.emit(None, "br", " label ", function.local("number_cond"))
    number_cond = function.append_block("number_cond")
    number_cond.emit("number_i", "load", " i64, ptr ", function.local("index_ptr"))
    number_cond.emit(
        "number_done", "icmp", " uge i64 ", function.local("number_i"), ", ", function.local("len")
    )
    number_cond.emit(
        None,
        "br",
        " i1 ",
        function.local("number_done"),
        ", label ",
        function.local("number_emit"),
        ", label ",
        function.local("number_body"),
    )
    number_body = function.append_block("number_body")
    number_body.emit(
        "number_ch_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("translated"),
        ", i64 ",
        function.local("number_i"),
    )
    number_body.emit("number_ch", "load", " i8, ptr ", function.local("number_ch_ptr"))
    number_body.emit(
        "number_part",
        "call",
        " i1 ",
        module.symbol("__xcc_aot_lexer_is_digit"),
        "(i8 ",
        function.local("number_ch"),
        ")",
    )
    number_body.emit(
        None,
        "br",
        " i1 ",
        function.local("number_part"),
        ", label ",
        function.local("number_advance"),
        ", label ",
        function.local("number_emit"),
    )
    number_advance = function.append_block("number_advance")
    number_advance.emit("number_next_i", "add", " i64 ", function.local("number_i"), ", 1")
    number_advance.emit("number_column", "load", " i64, ptr ", function.local("column_ptr"))
    number_advance.emit(
        "number_next_column", "add", " i64 ", function.local("number_column"), ", 1"
    )
    number_advance.emit(
        None,
        "store",
        " i64 ",
        function.local("number_next_i"),
        ", ptr ",
        function.local("index_ptr"),
    )
    number_advance.emit(
        None,
        "store",
        " i64 ",
        function.local("number_next_column"),
        ", ptr ",
        function.local("column_ptr"),
    )
    number_advance.emit(None, "br", " label ", function.local("number_cond"))
    number_emit = function.append_block("number_emit")
    number_emit.emit("number_end_i", "load", " i64, ptr ", function.local("index_ptr"))
    number_emit.emit(
        "number_len",
        "sub",
        " i64 ",
        function.local("number_end_i"),
        ", ",
        function.local("number_start_i"),
    )
    number_emit.emit("number_out_len", "load", " i64, ptr ", function.local("out_len_ptr"))
    number_emit.emit("number_first", "load", " i1, ptr ", function.local("first_ptr"))
    number_emit.emit(
        "number_new_len",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_lexer_append_summary_token"),
        "(",
    )
    number_emit.continue_("  ptr ", function.local("out"), ",")
    number_emit.continue_("  i64 ", function.local("number_out_len"), ",")
    number_emit.continue_("  i64 ", function.local("cap"), ",")
    number_emit.continue_("  i1 ", function.local("number_first"), ",")
    number_emit.continue_("  ptr ", module.symbol("__xcc_aot_kind_int_const"), ",")
    number_emit.continue_("  ptr ", function.local("scan_ch_ptr"), ",")
    number_emit.continue_("  i64 ", function.local("number_len"), ",")
    number_emit.continue_("  i64 ", function.local("number_start_line"), ",")
    number_emit.continue_("  i64 ", function.local("number_start_column"))
    number_emit.continue_(")")
    number_emit.emit(
        None,
        "store",
        " i64 ",
        function.local("number_new_len"),
        ", ptr ",
        function.local("out_len_ptr"),
    )
    number_emit.emit(None, "store", " i1 false, ptr ", function.local("first_ptr"))
    number_emit.emit(None, "br", " label ", function.local("scan_cond"))
    punct_emit = function.append_block("punct_emit")
    punct_emit.emit("punct_line", "load", " i64, ptr ", function.local("line_ptr"))
    punct_emit.emit("punct_column", "load", " i64, ptr ", function.local("column_ptr"))
    punct_emit.emit("punct_out_len", "load", " i64, ptr ", function.local("out_len_ptr"))
    punct_emit.emit("punct_first", "load", " i1, ptr ", function.local("first_ptr"))
    punct_emit.emit(
        "punct_new_len", "call", " i64 ", module.symbol("__xcc_aot_lexer_append_summary_token"), "("
    )
    punct_emit.continue_("  ptr ", function.local("out"), ",")
    punct_emit.continue_("  i64 ", function.local("punct_out_len"), ",")
    punct_emit.continue_("  i64 ", function.local("cap"), ",")
    punct_emit.continue_("  i1 ", function.local("punct_first"), ",")
    punct_emit.continue_("  ptr ", module.symbol("__xcc_aot_kind_punctuator"), ",")
    punct_emit.continue_("  ptr ", function.local("scan_ch_ptr"), ",")
    punct_emit.continue_("  i64 1,")
    punct_emit.continue_("  i64 ", function.local("punct_line"), ",")
    punct_emit.continue_("  i64 ", function.local("punct_column"))
    punct_emit.continue_(")")
    punct_emit.emit("punct_i", "load", " i64, ptr ", function.local("index_ptr"))
    punct_emit.emit("punct_next_i", "add", " i64 ", function.local("punct_i"), ", 1")
    punct_emit.emit("punct_next_column", "add", " i64 ", function.local("punct_column"), ", 1")
    punct_emit.emit(
        None,
        "store",
        " i64 ",
        function.local("punct_new_len"),
        ", ptr ",
        function.local("out_len_ptr"),
    )
    punct_emit.emit(None, "store", " i1 false, ptr ", function.local("first_ptr"))
    punct_emit.emit(
        None,
        "store",
        " i64 ",
        function.local("punct_next_i"),
        ", ptr ",
        function.local("index_ptr"),
    )
    punct_emit.emit(
        None,
        "store",
        " i64 ",
        function.local("punct_next_column"),
        ", ptr ",
        function.local("column_ptr"),
    )
    punct_emit.emit(None, "br", " label ", function.local("scan_cond"))
    emit_eof = function.append_block("emit_eof")
    emit_eof.emit("eof_line", "load", " i64, ptr ", function.local("line_ptr"))
    emit_eof.emit("eof_column", "load", " i64, ptr ", function.local("column_ptr"))
    emit_eof.emit("eof_out_len", "load", " i64, ptr ", function.local("out_len_ptr"))
    emit_eof.emit("eof_first", "load", " i1, ptr ", function.local("first_ptr"))
    emit_eof.emit(
        "eof_new_len", "call", " i64 ", module.symbol("__xcc_aot_lexer_append_summary_eof"), "("
    )
    emit_eof.continue_("  ptr ", function.local("out"), ",")
    emit_eof.continue_("  i64 ", function.local("eof_out_len"), ",")
    emit_eof.continue_("  i64 ", function.local("cap"), ",")
    emit_eof.continue_("  i1 ", function.local("eof_first"), ",")
    emit_eof.continue_("  i64 ", function.local("eof_line"), ",")
    emit_eof.continue_("  i64 ", function.local("eof_column"))
    emit_eof.continue_(")")
    emit_eof.emit(
        None,
        "store",
        " i64 ",
        function.local("eof_new_len"),
        ", ptr ",
        function.local("out_len_ptr"),
    )
    emit_eof.emit(None, "ret", " ptr ", function.local("out"))


def _build___xcc_aot_lexer_header_summary_for_source(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_lexer_header_summary_for_source")
    entry = function.append_block("entry")
    entry.emit(
        "translated",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_lexer_translate_source"),
        "(ptr ",
        function.local("source"),
        ")",
    )
    entry.emit(
        "len", "call", " i64 ", module.symbol("strlen"), "(ptr ", function.local("translated"), ")"
    )
    entry.emit("scaled_cap", "mul", " i64 ", function.local("len"), ", 64")
    entry.emit("cap", "add", " i64 ", function.local("scaled_cap"), ", 128")
    entry.emit("out", "call", " ptr ", module.symbol("malloc"), "(i64 ", function.local("cap"), ")")
    entry.emit("index_ptr", "alloca", " i64")
    entry.emit(None, "store", " i64 0, ptr ", function.local("index_ptr"))
    entry.emit(None, "br", " label ", function.local("header_cond"))
    header_cond = function.append_block("header_cond")
    header_cond.emit("header_i", "load", " i64, ptr ", function.local("index_ptr"))
    header_cond.emit(
        "header_done", "icmp", " uge i64 ", function.local("header_i"), ", ", function.local("len")
    )
    header_cond.emit(
        None,
        "br",
        " i1 ",
        function.local("header_done"),
        ", label ",
        function.local("header_emit"),
        ", label ",
        function.local("header_body"),
    )
    header_body = function.append_block("header_body")
    header_body.emit("header_i0", "load", " i64, ptr ", function.local("index_ptr"))
    header_body.emit(
        "header_ch_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("translated"),
        ", i64 ",
        function.local("header_i0"),
    )
    header_body.emit("header_ch", "load", " i8, ptr ", function.local("header_ch_ptr"))
    header_body.emit("header_is_gt", "icmp", " eq i8 ", function.local("header_ch"), ", 62")
    header_body.emit(
        None,
        "br",
        " i1 ",
        function.local("header_is_gt"),
        ", label ",
        function.local("header_found"),
        ", label ",
        function.local("header_advance"),
    )
    header_found = function.append_block("header_found")
    header_found.emit("header_found_i", "load", " i64, ptr ", function.local("index_ptr"))
    header_found.emit("header_found_next", "add", " i64 ", function.local("header_found_i"), ", 1")
    header_found.emit(
        None,
        "store",
        " i64 ",
        function.local("header_found_next"),
        ", ptr ",
        function.local("index_ptr"),
    )
    header_found.emit(None, "br", " label ", function.local("header_emit"))
    header_advance = function.append_block("header_advance")
    header_advance.emit("header_advance_i", "load", " i64, ptr ", function.local("index_ptr"))
    header_advance.emit(
        "header_advance_next", "add", " i64 ", function.local("header_advance_i"), ", 1"
    )
    header_advance.emit(
        None,
        "store",
        " i64 ",
        function.local("header_advance_next"),
        ", ptr ",
        function.local("index_ptr"),
    )
    header_advance.emit(None, "br", " label ", function.local("header_cond"))
    header_emit = function.append_block("header_emit")
    header_emit.emit("header_len", "load", " i64, ptr ", function.local("index_ptr"))
    header_emit.emit(
        "summary_len", "call", " i64 ", module.symbol("__xcc_aot_lexer_append_summary_token"), "("
    )
    header_emit.continue_("  ptr ", function.local("out"), ",")
    header_emit.continue_("  i64 0,")
    header_emit.continue_("  i64 ", function.local("cap"), ",")
    header_emit.continue_("  i1 true,")
    header_emit.continue_("  ptr ", module.symbol("__xcc_aot_kind_header_name"), ",")
    header_emit.continue_("  ptr ", function.local("translated"), ",")
    header_emit.continue_("  i64 ", function.local("header_len"), ",")
    header_emit.continue_("  i64 1,")
    header_emit.continue_("  i64 1")
    header_emit.continue_(")")
    header_emit.emit("eof_column", "add", " i64 ", function.local("header_len"), ", 1")
    header_emit.emit(
        "final_len", "call", " i64 ", module.symbol("__xcc_aot_lexer_append_summary_eof"), "("
    )
    header_emit.continue_("  ptr ", function.local("out"), ",")
    header_emit.continue_("  i64 ", function.local("summary_len"), ",")
    header_emit.continue_("  i64 ", function.local("cap"), ",")
    header_emit.continue_("  i1 false,")
    header_emit.continue_("  i64 1,")
    header_emit.continue_("  i64 ", function.local("eof_column"))
    header_emit.continue_(")")
    header_emit.emit(None, "ret", " ptr ", function.local("out"))


def _build___xcc_aot_lexer_error_summary_for_source(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_lexer_error_summary_for_source")
    entry = function.append_block("entry")
    entry.emit(None, "ret", " ptr ", module.symbol("__xcc_aot_error_unterminated_string"))


def _build___xcc_aot_i64_to_string(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_i64_to_string")
    entry = function.append_block("entry")
    entry.emit("out", "call", " ptr ", module.symbol("malloc"), "(i64 32)")
    entry.emit("written", "call", " i32 (ptr, i64, ptr, ...) ", module.symbol("snprintf"), "(")
    entry.continue_("  ptr ", function.local("out"), ",")
    entry.continue_("  i64 32,")
    entry.continue_("  ptr ", module.symbol("__xcc_aot_fmt_i64"), ",")
    entry.continue_("  i64 ", function.local("value"))
    entry.continue_(")")
    entry.emit(None, "ret", " ptr ", function.local("out"))


def _build___xcc_aot_i64_format_hex2(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_i64_format_hex2")
    entry = function.append_block("entry")
    entry.emit("out", "call", " ptr ", module.symbol("malloc"), "(i64 32)")
    entry.emit("negative", "icmp", " slt i64 ", function.local("value"), ", 0")
    entry.emit(
        None,
        "br",
        " i1 ",
        function.local("negative"),
        ", label ",
        function.local("negative_value"),
        ", label ",
        function.local("positive_value"),
    )
    negative_value = function.append_block("negative_value")
    negative_value.emit(None, "store", " i8 45, ptr ", function.local("out"))
    negative_value.emit("magnitude", "sub", " i64 0, ", function.local("value"))
    negative_value.emit(
        "negative_out", "getelementptr", " i8, ptr ", function.local("out"), ", i64 1"
    )
    negative_value.emit("negative_format", "select", " i1 ", function.local("uppercase"), ",")
    negative_value.continue_("  ptr ", module.symbol("__xcc_aot_fmt_hex_upper"), ",")
    negative_value.continue_("  ptr ", module.symbol("__xcc_aot_fmt_hex_lower"))
    negative_value.emit(
        "negative_written", "call", " i32 (ptr, i64, ptr, ...) ", module.symbol("snprintf"), "("
    )
    negative_value.continue_("  ptr ", function.local("negative_out"), ",")
    negative_value.continue_("  i64 31,")
    negative_value.continue_("  ptr ", function.local("negative_format"), ",")
    negative_value.continue_("  i64 ", function.local("magnitude"))
    negative_value.continue_(")")
    negative_value.emit(None, "br", " label ", function.local("done"))
    positive_value = function.append_block("positive_value")
    positive_value.emit("positive_format", "select", " i1 ", function.local("uppercase"), ",")
    positive_value.continue_("  ptr ", module.symbol("__xcc_aot_fmt_hex2_upper"), ",")
    positive_value.continue_("  ptr ", module.symbol("__xcc_aot_fmt_hex2_lower"))
    positive_value.emit(
        "positive_written", "call", " i32 (ptr, i64, ptr, ...) ", module.symbol("snprintf"), "("
    )
    positive_value.continue_("  ptr ", function.local("out"), ",")
    positive_value.continue_("  i64 32,")
    positive_value.continue_("  ptr ", function.local("positive_format"), ",")
    positive_value.continue_("  i64 ", function.local("value"))
    positive_value.continue_(")")
    positive_value.emit(None, "br", " label ", function.local("done"))
    done = function.append_block("done")
    done.emit(None, "ret", " ptr ", function.local("out"))


def _build___xcc_aot_string_slice(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_string_slice")
    entry = function.append_block("entry")
    entry.emit(
        "len",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_string_len"),
        "(ptr ",
        function.local("text"),
        ")",
    )
    entry.emit("start_neg", "icmp", " slt i64 ", function.local("start"), ", 0")
    entry.emit(
        "start_from_end", "add", " i64 ", function.local("len"), ", ", function.local("start")
    )
    entry.emit(
        "norm_start",
        "select",
        " i1 ",
        function.local("start_neg"),
        ", i64 ",
        function.local("start_from_end"),
        ", i64 ",
        function.local("start"),
    )
    entry.emit("stop_neg", "icmp", " slt i64 ", function.local("stop"), ", 0")
    entry.emit("stop_from_end", "add", " i64 ", function.local("len"), ", ", function.local("stop"))
    entry.emit(
        "norm_stop",
        "select",
        " i1 ",
        function.local("stop_neg"),
        ", i64 ",
        function.local("stop_from_end"),
        ", i64 ",
        function.local("stop"),
    )
    entry.emit(
        "raw_count", "sub", " i64 ", function.local("norm_stop"), ", ", function.local("norm_start")
    )
    entry.emit("negative_count", "icmp", " slt i64 ", function.local("raw_count"), ", 0")
    entry.emit(
        "count",
        "select",
        " i1 ",
        function.local("negative_count"),
        ", i64 0, i64 ",
        function.local("raw_count"),
    )
    entry.emit("alloc_size", "add", " i64 ", function.local("count"), ", 1")
    entry.emit(
        "result",
        "call",
        " ptr ",
        module.symbol("malloc"),
        "(i64 ",
        function.local("alloc_size"),
        ")",
    )
    entry.emit(
        "source",
        "getelementptr",
        " i8, ptr ",
        function.local("text"),
        ", i64 ",
        function.local("norm_start"),
    )
    entry.emit(
        "copied",
        "call",
        " ptr ",
        module.symbol("memcpy"),
        "(ptr ",
        function.local("result"),
        ", ptr ",
        function.local("source"),
        ", i64 ",
        function.local("count"),
        ")",
    )
    entry.emit(
        "terminator",
        "getelementptr",
        " i8, ptr ",
        function.local("result"),
        ", i64 ",
        function.local("count"),
    )
    entry.emit(None, "store", " i8 0, ptr ", function.local("terminator"))
    entry.emit(None, "ret", " ptr ", function.local("result"))


def _build___xcc_aot_string_concat2(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_string_concat2")
    entry = function.append_block("entry")
    entry.emit(
        "left_len", "call", " i64 ", module.symbol("strlen"), "(ptr ", function.local("left"), ")"
    )
    entry.emit(
        "right_len", "call", " i64 ", module.symbol("strlen"), "(ptr ", function.local("right"), ")"
    )
    entry.emit(
        "data_len", "add", " i64 ", function.local("left_len"), ", ", function.local("right_len")
    )
    entry.emit("total_len", "add", " i64 ", function.local("data_len"), ", 1")
    entry.emit(
        "out", "call", " ptr ", module.symbol("malloc"), "(i64 ", function.local("total_len"), ")"
    )
    entry.emit(
        "copy_left",
        "call",
        " ptr ",
        module.symbol("memcpy"),
        "(ptr ",
        function.local("out"),
        ", ptr ",
        function.local("left"),
        ", i64 ",
        function.local("left_len"),
        ")",
    )
    entry.emit(
        "right_dst",
        "getelementptr",
        " i8, ptr ",
        function.local("out"),
        ", i64 ",
        function.local("left_len"),
    )
    entry.emit(
        "copy_right",
        "call",
        " ptr ",
        module.symbol("memcpy"),
        "(ptr ",
        function.local("right_dst"),
        ", ptr ",
        function.local("right"),
        ", i64 ",
        function.local("right_len"),
        ")",
    )
    entry.emit(
        "zero_ptr",
        "getelementptr",
        " i8, ptr ",
        function.local("out"),
        ", i64 ",
        function.local("data_len"),
    )
    entry.emit(None, "store", " i8 0, ptr ", function.local("zero_ptr"))
    entry.emit(None, "ret", " ptr ", function.local("out"))


def _build___xcc_aot_string_join(module: LlvmModule) -> None:
    function = module.function("__xcc_aot_string_join")
    entry = function.append_block("entry")
    entry.emit(
        "count",
        "call",
        " i64 ",
        module.symbol("__xcc_aot_tuple_len"),
        "(ptr ",
        function.local("values"),
        ")",
    )
    entry.emit(
        "separator_len",
        "call",
        " i64 ",
        module.symbol("strlen"),
        "(ptr ",
        function.local("separator"),
        ")",
    )
    entry.emit("measure_index_ptr", "alloca", " i64")
    entry.emit("items_len_ptr", "alloca", " i64")
    entry.emit(None, "store", " i64 0, ptr ", function.local("measure_index_ptr"))
    entry.emit(None, "store", " i64 0, ptr ", function.local("items_len_ptr"))
    entry.emit(None, "br", " label ", function.local("join_measure_cond"))
    join_measure_cond = function.append_block("join_measure_cond")
    join_measure_cond.emit(
        "measure_index", "load", " i64, ptr ", function.local("measure_index_ptr")
    )
    join_measure_cond.emit(
        "measure_done",
        "icmp",
        " uge i64 ",
        function.local("measure_index"),
        ", ",
        function.local("count"),
    )
    join_measure_cond.emit(
        None,
        "br",
        " i1 ",
        function.local("measure_done"),
        ", label ",
        function.local("join_allocate"),
        ", label ",
        function.local("join_measure_body"),
    )
    join_measure_body = function.append_block("join_measure_body")
    join_measure_body.emit(
        "measure_item",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_get"),
        "(ptr ",
        function.local("values"),
        ", i64 ",
        function.local("measure_index"),
        ")",
    )
    join_measure_body.emit(
        "measure_item_len",
        "call",
        " i64 ",
        module.symbol("strlen"),
        "(ptr ",
        function.local("measure_item"),
        ")",
    )
    join_measure_body.emit("items_len", "load", " i64, ptr ", function.local("items_len_ptr"))
    join_measure_body.emit(
        "next_items_len",
        "add",
        " i64 ",
        function.local("items_len"),
        ", ",
        function.local("measure_item_len"),
    )
    join_measure_body.emit(
        None,
        "store",
        " i64 ",
        function.local("next_items_len"),
        ", ptr ",
        function.local("items_len_ptr"),
    )
    join_measure_body.emit(
        "next_measure_index", "add", " i64 ", function.local("measure_index"), ", 1"
    )
    join_measure_body.emit(
        None,
        "store",
        " i64 ",
        function.local("next_measure_index"),
        ", ptr ",
        function.local("measure_index_ptr"),
    )
    join_measure_body.emit(None, "br", " label ", function.local("join_measure_cond"))
    join_allocate = function.append_block("join_allocate")
    join_allocate.emit("measured_items_len", "load", " i64, ptr ", function.local("items_len_ptr"))
    join_allocate.emit("has_values", "icmp", " ugt i64 ", function.local("count"), ", 0")
    join_allocate.emit("raw_separator_count", "sub", " i64 ", function.local("count"), ", 1")
    join_allocate.emit(
        "separator_count",
        "select",
        " i1 ",
        function.local("has_values"),
        ", i64 ",
        function.local("raw_separator_count"),
        ", i64 0",
    )
    join_allocate.emit(
        "separators_len",
        "mul",
        " i64 ",
        function.local("separator_count"),
        ", ",
        function.local("separator_len"),
    )
    join_allocate.emit(
        "data_len",
        "add",
        " i64 ",
        function.local("measured_items_len"),
        ", ",
        function.local("separators_len"),
    )
    join_allocate.emit("allocation_len", "add", " i64 ", function.local("data_len"), ", 1")
    join_allocate.emit(
        "out",
        "call",
        " ptr ",
        module.symbol("malloc"),
        "(i64 ",
        function.local("allocation_len"),
        ")",
    )
    join_allocate.emit("copy_index_ptr", "alloca", " i64")
    join_allocate.emit("offset_ptr", "alloca", " i64")
    join_allocate.emit(None, "store", " i64 0, ptr ", function.local("copy_index_ptr"))
    join_allocate.emit(None, "store", " i64 0, ptr ", function.local("offset_ptr"))
    join_allocate.emit(None, "br", " label ", function.local("join_copy_cond"))
    join_copy_cond = function.append_block("join_copy_cond")
    join_copy_cond.emit("copy_index", "load", " i64, ptr ", function.local("copy_index_ptr"))
    join_copy_cond.emit(
        "copy_done",
        "icmp",
        " uge i64 ",
        function.local("copy_index"),
        ", ",
        function.local("count"),
    )
    join_copy_cond.emit(
        None,
        "br",
        " i1 ",
        function.local("copy_done"),
        ", label ",
        function.local("join_done"),
        ", label ",
        function.local("join_copy_body"),
    )
    join_copy_body = function.append_block("join_copy_body")
    join_copy_body.emit("needs_separator", "icmp", " ugt i64 ", function.local("copy_index"), ", 0")
    join_copy_body.emit(
        None,
        "br",
        " i1 ",
        function.local("needs_separator"),
        ", label ",
        function.local("join_copy_separator"),
        ", label ",
        function.local("join_copy_item"),
    )
    join_copy_separator = function.append_block("join_copy_separator")
    join_copy_separator.emit("separator_offset", "load", " i64, ptr ", function.local("offset_ptr"))
    join_copy_separator.emit(
        "separator_destination",
        "getelementptr",
        " i8, ptr ",
        function.local("out"),
        ", i64 ",
        function.local("separator_offset"),
    )
    join_copy_separator.emit(
        "copied_separator",
        "call",
        " ptr ",
        module.symbol("memcpy"),
        "(ptr ",
        function.local("separator_destination"),
        ", ptr ",
        function.local("separator"),
        ", i64 ",
        function.local("separator_len"),
        ")",
    )
    join_copy_separator.emit(
        "item_offset",
        "add",
        " i64 ",
        function.local("separator_offset"),
        ", ",
        function.local("separator_len"),
    )
    join_copy_separator.emit(
        None,
        "store",
        " i64 ",
        function.local("item_offset"),
        ", ptr ",
        function.local("offset_ptr"),
    )
    join_copy_separator.emit(None, "br", " label ", function.local("join_copy_item"))
    join_copy_item = function.append_block("join_copy_item")
    join_copy_item.emit(
        "copy_item",
        "call",
        " ptr ",
        module.symbol("__xcc_aot_tuple_get"),
        "(ptr ",
        function.local("values"),
        ", i64 ",
        function.local("copy_index"),
        ")",
    )
    join_copy_item.emit(
        "copy_item_len",
        "call",
        " i64 ",
        module.symbol("strlen"),
        "(ptr ",
        function.local("copy_item"),
        ")",
    )
    join_copy_item.emit("copy_item_offset", "load", " i64, ptr ", function.local("offset_ptr"))
    join_copy_item.emit(
        "item_destination",
        "getelementptr",
        " i8, ptr ",
        function.local("out"),
        ", i64 ",
        function.local("copy_item_offset"),
    )
    join_copy_item.emit(
        "copied_item",
        "call",
        " ptr ",
        module.symbol("memcpy"),
        "(ptr ",
        function.local("item_destination"),
        ", ptr ",
        function.local("copy_item"),
        ", i64 ",
        function.local("copy_item_len"),
        ")",
    )
    join_copy_item.emit(
        "next_offset",
        "add",
        " i64 ",
        function.local("copy_item_offset"),
        ", ",
        function.local("copy_item_len"),
    )
    join_copy_item.emit(
        None,
        "store",
        " i64 ",
        function.local("next_offset"),
        ", ptr ",
        function.local("offset_ptr"),
    )
    join_copy_item.emit("next_copy_index", "add", " i64 ", function.local("copy_index"), ", 1")
    join_copy_item.emit(
        None,
        "store",
        " i64 ",
        function.local("next_copy_index"),
        ", ptr ",
        function.local("copy_index_ptr"),
    )
    join_copy_item.emit(None, "br", " label ", function.local("join_copy_cond"))
    join_done = function.append_block("join_done")
    join_done.emit(
        "terminator",
        "getelementptr",
        " i8, ptr ",
        function.local("out"),
        ", i64 ",
        function.local("data_len"),
    )
    join_done.emit(None, "store", " i8 0, ptr ", function.local("terminator"))
    join_done.emit(None, "ret", " ptr ", function.local("out"))


def runtime_module() -> LlvmModule:
    module = LlvmModule()
    _declare_runtime(module)
    _build___xcc_aot_allocation_fail(module)
    _build___xcc_aot_memory_safety_fail(module)
    _build___xcc_aot_alloc(module)
    _build___xcc_aot_calloc(module)
    _build___xcc_aot_phase_allocation_index_insert(module)
    _build___xcc_aot_phase_allocation_index_remove(module)
    _build___xcc_aot_find_allocation(module)
    _build___xcc_aot_realloc(module)
    _build___xcc_aot_free_allocation(module)
    _build___xcc_aot_free(module)
    _build___xcc_aot_phase_promote_cache_contains(module)
    _build___xcc_aot_phase_promote_cache_store(module)
    _build___xcc_aot_phase_promote_cache_invalidate_payload(module)
    _build___xcc_aot_phase_capture_cache_enter(module)
    _build___xcc_aot_phase_capture_cache_exit(module)
    _build___xcc_aot_phase_capture_cache_store(module)
    _build___xcc_aot_phase_mark_with_mode(module)
    _build___xcc_aot_phase_mark(module)
    _build___xcc_aot_phase_iteration_mark(module)
    _build___xcc_aot_phase_promote(module)
    _build___xcc_aot_phase_promote_begin(module)
    _build___xcc_aot_phase_promote_end(module)
    _build___xcc_aot_phase_promote_allocated_to(module)
    _build___xcc_aot_phase_promote_to(module)
    _build___xcc_aot_phase_capture_allocated_target(module)
    _build___xcc_aot_phase_capture_target(module)
    _build___xcc_aot_phase_capture_defer(module)
    _build___xcc_aot_phase_capture_exact(module)
    _build___xcc_aot_phase_commit(module)
    _build___xcc_aot_phase_allocated_bytes(module)
    _build___xcc_aot_single_byte_string(module)
    _build___xcc_aot_phase_reset(module)
    _build___xcc_aot_phase_finish(module)
    _build___xcc_aot_object_repr(module)
    _build___xcc_aot_object_str(module)
    _build___xcc_aot_complex_new(module)
    _build___xcc_aot_tuple_new(module)
    _build___xcc_aot_tuple_resolve(module)
    _build___xcc_aot_tuple_capacity(module)
    _build___xcc_aot_tuple_register_capacity(module)
    _build___xcc_aot_tuple_forward(module)
    _build___xcc_aot_tuple_append(module)
    _build___xcc_aot_tuple_extend(module)
    _build___xcc_aot_tuple_len(module)
    _build___xcc_aot_tuple_clear(module)
    _build___xcc_aot_tuple_get(module)
    _build___xcc_aot_tuple_object_layout_find(module)
    _build___xcc_aot_tuple_object_layout_register(module)
    _build___xcc_aot_tuple_object_layout_forward(module)
    _build___xcc_aot_tuple_get_object(module)
    _build___xcc_aot_tuple_set(module)
    _build___xcc_aot_tuple_slice(module)
    _build___xcc_aot_string_dict_hash(module)
    _build___xcc_aot_dict_bump_state(module)
    _build___xcc_aot_dict_state(module)
    _build___xcc_aot_string_dict_cache_bucket(module)
    _build___xcc_aot_string_dict_cache_store(module)
    _build___xcc_aot_string_dict_find_index(module)
    _build___xcc_aot_string_dict_note_index(module)
    _build___xcc_aot_string_tuple_find_index(module)
    _build___xcc_aot_string_tuple_note_index(module)
    _build___xcc_aot_identity_dict_cache_bucket(module)
    _build___xcc_aot_identity_dict_cache_store(module)
    _build___xcc_aot_identity_dict_find_index(module)
    _build___xcc_aot_identity_dict_note_index(module)
    _build___xcc_aot_dict_copy(module)
    _build___xcc_aot_dict_keys(module)
    _build___xcc_aot_dict_values(module)
    _build___xcc_aot_tuple_concat(module)
    _build___xcc_aot_tuple_repeat(module)
    _build___xcc_aot_tuple_pop(module)
    _build___xcc_aot_tuple_pop_item(module)
    _build___xcc_aot_tuple_set_slice(module)
    _build___xcc_aot_tuple_reversed(module)
    _build___xcc_aot_range(module)
    _build___xcc_aot_zip2(module)
    _build___xcc_aot_string_split(module)
    _build___xcc_aot_string_split_limit(module)
    _build___xcc_aot_string_rsplit_limit(module)
    _build___xcc_aot_string_split_whitespace(module)
    _build___xcc_aot_string_splitlines(module)
    _build___xcc_aot_string_replace(module)
    _build___xcc_aot_string_lower(module)
    _build___xcc_aot_string_upper(module)
    _build___xcc_aot_path_parent(module)
    _build___xcc_aot_path_name(module)
    _build___xcc_aot_path_join(module)
    _build___xcc_aot_read_text_file(module)
    _build___xcc_aot_read_bytes_file(module)
    _build___xcc_aot_path_is_file(module)
    _build___xcc_aot_write_text_file(module)
    _build___xcc_aot_startswith_cache_invalidate(module)
    _build___xcc_aot_string_len(module)
    _build___xcc_aot_string_startswith_known_length(module)
    _build___xcc_aot_string_startswith(module)
    _build___xcc_aot_string_endswith(module)
    _build___xcc_aot_string_rfind(module)
    _build___xcc_aot_string_count(module)
    _build___xcc_aot_string_removeprefix(module)
    _build___xcc_aot_string_removesuffix(module)
    _build___xcc_aot_is_ascii_space(module)
    _build___xcc_aot_char_in_string(module)
    _build___xcc_aot_string_ljust(module)
    _build___xcc_aot_string_lstrip(module)
    _build___xcc_aot_string_rstrip(module)
    _build___xcc_aot_string_strip(module)
    _build___xcc_aot_zero_bytes(module)
    _build___xcc_aot_bytes_new(module)
    _build___xcc_aot_bytes_data(module)
    _build___xcc_aot_bytes_len(module)
    _build___xcc_aot_bytes_copy(module)
    _build___xcc_aot_bytes_from_ints(module)
    _build___xcc_aot_bytes_get(module)
    _build___xcc_aot_bytes_equal(module)
    _build___xcc_aot_string_encode(module)
    _build___xcc_aot_bytes_concat(module)
    _build___xcc_aot_bytes_repeat(module)
    _build___xcc_aot_bytes_slice(module)
    _build___xcc_aot_bytes_ljust(module)
    _build___xcc_aot_string_repeat(module)
    _build___xcc_aot_int_to_bytes(module)
    _build___xcc_aot_parse_int(module)
    _build___xcc_aot_string_predicate(module)
    _build___xcc_aot_c_argv_to_tuple(module)
    _build___xcc_aot_execvp_tuple(module)
    _build___xcc_aot_lexer_translate_source(module)
    _build___xcc_aot_lexer_append_summary_token(module)
    _build___xcc_aot_lexer_append_summary_eof(module)
    _build___xcc_aot_lexer_is_alpha(module)
    _build___xcc_aot_lexer_is_digit(module)
    _build___xcc_aot_lexer_is_ident_start(module)
    _build___xcc_aot_lexer_is_ident_part(module)
    _build___xcc_aot_lexer_keyword_kind(module)
    _build___xcc_aot_lexer_token_summary_for_source(module)
    _build___xcc_aot_lexer_header_summary_for_source(module)
    _build___xcc_aot_lexer_error_summary_for_source(module)
    _build___xcc_aot_i64_to_string(module)
    _build___xcc_aot_i64_format_hex2(module)
    _build___xcc_aot_string_slice(module)
    _build___xcc_aot_string_concat2(module)
    _build___xcc_aot_string_join(module)
    module.redirect_calls(module.symbol("malloc"), module.symbol(RUNTIME_ALLOC))
    module.validate()
    return module


def runtime_prelude() -> str:
    if _RUNTIME_PRELUDE_CACHE:
        return _RUNTIME_PRELUDE_CACHE[0]
    prelude = runtime_module().render()
    _RUNTIME_PRELUDE_CACHE.append(prelude)
    return prelude
