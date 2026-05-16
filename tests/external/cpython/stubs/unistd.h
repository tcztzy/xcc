#ifndef _UNISTD_H
#define _UNISTD_H

#include <stddef.h>
#include <sys/types.h>

/* ssize_t from sys/types.h */

/* POSIX feature test macros */
#define _POSIX_THREADS 200112L
#define _POSIX_SEMAPHORES 200112L
#define _POSIX_THREAD_ATTR_STACKSIZE 200112L
#define _POSIX_THREAD_ATTR_STACKADDR 200112L

ssize_t read(int fd, void *buf, size_t nbyte);
ssize_t write(int fd, const void *buf, size_t nbyte);
int close(int fd);
unsigned int sleep(unsigned int seconds);
int isatty(int fd);
int fileno(void *stream);
long lseek(int fd, long offset, int whence);
int access(const char *pathname, int mode);
int pause(void);
int getpid(void);
ssize_t readlink(const char *path, char *buf, size_t bufsiz);

#define SEEK_SET 0
#define SEEK_CUR 1
#define SEEK_END 2
#define R_OK 4
#define W_OK 2
#define X_OK 1
#define F_OK 0

/* fcntl / open constants */
#define F_GETFD 1
#define F_SETFD 2
#define F_GETFL 3
#define F_SETFL 4
#define FD_CLOEXEC 1
#define O_APPEND 0x0008
#define O_CREAT 0x0200
#define O_TRUNC 0x0400
#define O_RDONLY 0
#define O_WRONLY 1
#define O_RDWR 2
#define O_NOFOLLOW 0x0100
#define O_CLOEXEC 0x1000000
#define O_NONBLOCK 0x0004

char *realpath(const char *path, char *resolved_path);
char *getcwd(char *buf, size_t size);
int dup(int oldfd);
int dup2(int oldfd, int newfd);

#endif
