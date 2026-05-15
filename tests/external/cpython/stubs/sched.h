#ifndef _SCHED_H
#define _SCHED_H
struct sched_param { int sched_priority; };
int sched_yield(void);
#endif
