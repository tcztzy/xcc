#ifndef _SYS_SOCKET_H
#define _SYS_SOCKET_H

#include <sys/types.h>

typedef unsigned int socklen_t;

int socket(int domain, int type, int protocol);
int connect(int sockfd, const void *addr, socklen_t addrlen);
int bind(int sockfd, const void *addr, socklen_t addrlen);
int listen(int sockfd, int backlog);
int accept(int sockfd, void *addr, socklen_t *addrlen);
int getsockname(int sockfd, void *addr, socklen_t *addrlen);
int getpeername(int sockfd, void *addr, socklen_t *addrlen);
int setsockopt(int sockfd, int level, int optname, const void *optval, socklen_t optlen);
int shutdown(int sockfd, int how);
ssize_t sendto(int sockfd, const void *buf, size_t len, int flags, const void *dest_addr, socklen_t addrlen);
ssize_t recvfrom(int sockfd, void *buf, size_t len, int flags, void *src_addr, socklen_t *addrlen);

#endif
