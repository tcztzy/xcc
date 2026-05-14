#ifndef _UNISTD_H
#define _UNISTD_H

#include <stddef.h>

ssize_t read(int fd, void *buf, size_t nbyte);
ssize_t write(int fd, const void *buf, size_t nbyte);
int close(int fd);

typedef long ssize_t;

#endif
