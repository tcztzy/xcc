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

#endif
