/*
 * xcc freestanding <stddef.h>
 */
#ifndef _XCC_STDDEF_H
#define _XCC_STDDEF_H

typedef long ptrdiff_t;
typedef unsigned long size_t;
typedef int wchar_t;

#define NULL ((void *)0)

#define offsetof(type, member) __builtin_offsetof(type, member)

typedef long max_align_t;

#endif /* _XCC_STDDEF_H */
