#ifndef _TIME_H
#define _TIME_H

#include <stddef.h>
#include <sys/types.h>  /* for time_t */

typedef long clock_t;

struct tm {
    int tm_sec;
    int tm_min;
    int tm_hour;
    int tm_mday;
    int tm_mon;
    int tm_year;
    int tm_wday;
    int tm_yday;
    int tm_isdst;
};

/* struct timespec is defined in <sys/types.h> */

time_t time(time_t *tloc);
int clock_gettime(int clk_id, struct timespec *tp);

#define CLOCK_REALTIME 0
#define CLOCK_MONOTONIC 1

#endif
