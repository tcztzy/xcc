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
clock_t clock(void);
int clock_gettime(int clk_id, struct timespec *tp);
int clock_getres(int clk_id, struct timespec *tp);
struct tm *localtime_r(const time_t *timep, struct tm *result);
struct tm *gmtime_r(const time_t *timep, struct tm *result);

#define CLOCK_REALTIME 0
#define CLOCK_MONOTONIC 1
#define CLOCKS_PER_SEC 1000000L

#endif
