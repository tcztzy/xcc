#ifndef _UNISTD_H
#define _UNISTD_H

#include <stddef.h>
#include <sys/types.h>

/* ssize_t from sys/types.h */

/* POSIX feature test macros */
#define _POSIX_THREADS 200112L
#define _POSIX_SEMAPHORES 200112L

ssize_t read(int fd, void *buf, size_t nbyte);
ssize_t write(int fd, const void *buf, size_t nbyte);
int close(int fd);

#endif
