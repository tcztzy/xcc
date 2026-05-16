#ifndef _SYS_RESOURCE_H
#define _SYS_RESOURCE_H

#include <sys/types.h>

struct timeval {
    long tv_sec;
    long tv_usec;
};

struct rusage {
    struct timeval ru_utime;
    struct timeval ru_stime;
    long ru_maxrss;
};

#define RUSAGE_SELF 0
#define RUSAGE_CHILDREN -1

int getrusage(int who, struct rusage *usage);

#endif
