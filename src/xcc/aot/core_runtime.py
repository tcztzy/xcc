def runtime_prelude() -> str:
    return "\n".join(
        (
            "declare i32 @puts(ptr)",
            "declare ptr @malloc(i64)",
            "declare i64 @strlen(ptr)",
            "declare ptr @memcpy(ptr, ptr, i64)",
            "declare i32 @strcmp(ptr, ptr)",
            "declare i32 @snprintf(ptr, i64, ptr, ...)",
            "",
            "define ptr @__xcc_aot_string_concat2(ptr %left, ptr %right) {",
            "entry:",
            "  ; Implemented in Task 5 before native core oracle tests run.",
            "  ret ptr %left",
            "}",
        )
    )
