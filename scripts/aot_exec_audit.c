#include <errno.h>
#include <fcntl.h>
#include <spawn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define XCC_AOT_AUDIT_LOG_ENV "XCC_AOT_AUDIT_LOG"
#define XCC_AOT_AUDIT_LINE_CAPACITY 4096

static void xcc_aot_audit_log(const char *event, const char *path) {
    char line[XCC_AOT_AUDIT_LINE_CAPACITY];
    const char *log_path = getenv(XCC_AOT_AUDIT_LOG_ENV);
    size_t event_length;
    size_t path_length;
    size_t available;
    int descriptor;

    if (log_path == NULL || log_path[0] == '\0' || event == NULL || path == NULL) {
        return;
    }
    descriptor = open(log_path, O_WRONLY | O_CREAT | O_APPEND, 0600);
    if (descriptor < 0) {
        return;
    }
    event_length = strnlen(event, sizeof(line) - 2);
    memcpy(line, event, event_length);
    line[event_length] = ' ';
    available = sizeof(line) - event_length - 2;
    path_length = strnlen(path, available);
    memcpy(line + event_length + 1, path, path_length);
    line[event_length + path_length + 1] = '\n';
    (void)write(descriptor, line, event_length + path_length + 2);
    (void)close(descriptor);
}

static FILE *xcc_aot_audit_fopen(const char *path, const char *mode) {
    FILE *result;
    int saved_errno;

    result = fopen(path, mode);
    saved_errno = errno;
    xcc_aot_audit_log("OPEN", path);
    errno = saved_errno;
    return result;
}

static int xcc_aot_audit_execvp(const char *file, char *const argv[]) {
    xcc_aot_audit_log("EXEC", file);
    return execvp(file, argv);
}

static int xcc_aot_audit_execve(
    const char *path,
    char *const argv[],
    char *const envp[]
) {
    xcc_aot_audit_log("EXEC", path);
    return execve(path, argv, envp);
}

static int xcc_aot_audit_posix_spawn(
    pid_t *pid,
    const char *path,
    const posix_spawn_file_actions_t *file_actions,
    const posix_spawnattr_t *attributes,
    char *const argv[],
    char *const envp[]
) {
    xcc_aot_audit_log("EXEC", path);
    return posix_spawn(pid, path, file_actions, attributes, argv, envp);
}

static int xcc_aot_audit_posix_spawnp(
    pid_t *pid,
    const char *file,
    const posix_spawn_file_actions_t *file_actions,
    const posix_spawnattr_t *attributes,
    char *const argv[],
    char *const envp[]
) {
    xcc_aot_audit_log("EXEC", file);
    return posix_spawnp(pid, file, file_actions, attributes, argv, envp);
}

#define DYLD_INTERPOSE(replacement, replacee)                                    \
    __attribute__((used)) static struct {                                        \
        const void *replacement;                                                 \
        const void *replacee;                                                    \
    } xcc_aot_interpose_##replacee __attribute__((section("__DATA,__interpose"))) = { \
        (const void *)(uintptr_t)&replacement,                                   \
        (const void *)(uintptr_t)&replacee,                                      \
    }

DYLD_INTERPOSE(xcc_aot_audit_fopen, fopen);
DYLD_INTERPOSE(xcc_aot_audit_execvp, execvp);
DYLD_INTERPOSE(xcc_aot_audit_execve, execve);
DYLD_INTERPOSE(xcc_aot_audit_posix_spawn, posix_spawn);
DYLD_INTERPOSE(xcc_aot_audit_posix_spawnp, posix_spawnp);
