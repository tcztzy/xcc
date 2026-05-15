#ifndef _SYS_STAT_H
#define _SYS_STAT_H
#include <sys/types.h>

struct stat {
    unsigned long st_dev;
    unsigned long st_ino;
    unsigned int st_mode;
    unsigned long st_nlink;
    unsigned int st_uid;
    unsigned int st_gid;
    unsigned long st_size;
    unsigned long st_atime;
    unsigned long st_mtime;
    unsigned long st_ctime;
};

#define S_IFMT   0170000
#define S_IFDIR  0040000
#define S_IFREG  0100000
#define S_ISDIR(m)  (((m) & S_IFMT) == S_IFDIR)
#define S_ISREG(m)  (((m) & S_IFMT) == S_IFREG)

int stat(const char *path, struct stat *buf);
int fstat(int fd, struct stat *buf);
int mkdir(const char *path, unsigned int mode);
#endif
