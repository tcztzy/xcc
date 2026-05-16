#ifndef _SIGNAL_H
#define _SIGNAL_H

typedef int sig_atomic_t;
typedef struct { void *ss_sp; int ss_flags; long ss_size; } stack_t;
typedef struct { unsigned long __bits[4]; } sigset_t;

struct sigaction {
    void (*sa_handler)(int);
    sigset_t sa_mask;
    int sa_flags;
};

#define SIGABRT 6
#define SIGFPE 8
#define SIGILL 4
#define SIGINT 2
#define SIGSEGV 11
#define SIGTERM 15

void (*signal(int sig, void (*func)(int)))(int);
int raise(int sig);

#define SIG_ERR ((void (*)(int))-1)
#define SIG_DFL ((void (*)(int))0)
#define SIG_IGN ((void (*)(int))1)

int sigemptyset(sigset_t *set);
int sigfillset(sigset_t *set);

#define SA_ONSTACK 0x0001
#define SA_RESTART 0x0002

#endif
