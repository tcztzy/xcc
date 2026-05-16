#ifndef _SYS_SELECT_H
#define _SYS_SELECT_H

#include <sys/types.h>

/* fd_set for select() */
typedef struct { long __fds_bits[32]; } fd_set;

#endif
