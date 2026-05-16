#ifndef _ERRNO_H
#define _ERRNO_H

extern int errno;

#define EPERM 1
#define ENOENT 2
#define ESRCH 3
#define EINTR 4
#define EIO 5
#define ENXIO 6
#define E2BIG 7
#define ENOEXEC 8
#define EBADF 9
#define ECHILD 10
#define EALREADY 37
#define EINPROGRESS 36
#define EAGAIN 11
#define ENOMEM 12
#define EACCES 13
#define EFAULT 14
#define ENOTBLK 15
#define EBUSY 16
#define EEXIST 17
#define EXDEV 18
#define EWOULDBLOCK 35
#define ENODEV 19
#define ENOTDIR 20
#define EISDIR 21
#define EINVAL 22
#define ENFILE 23
#define EMFILE 24
#define ENOTTY 25
#define ETXTBSY 26
#define EFBIG 27
#define ENOSPC 28
#define ESPIPE 29
#define EROFS 30
#define EMLINK 31
#define EPIPE 32
#define EDOM 33
#define ERANGE 34
#define EDEADLK 35
#define ENAMETOOLONG 36
#define ENOLCK 37
#define ENOSYS 38
#define ENOTEMPTY 39
#define ENOTSUP 45
#define ENOPROTOOPT 42
#define EPROTONOSUPPORT 43
#define ESOCKTNOSUPPORT 44
#define EOPNOTSUPP 45
#define EAFNOSUPPORT 47
#define EADDRINUSE 48
#define EADDRNOTAVAIL 49
#define ENETDOWN 50
#define ENETUNREACH 51
#define ECONNRESET 54
#define ENOBUFS 55
#define ETIMEDOUT 60
#define ECONNREFUSED 61
#define ELOOP 62
#define EOVERFLOW 75

#endif
