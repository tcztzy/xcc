#ifndef _WCHAR_H
#define _WCHAR_H

#include <stddef.h>

typedef int wint_t;
typedef struct { int __mbs[4]; } mbstate_t;

size_t wcslen(const wchar_t *s);
wchar_t *wcscpy(wchar_t *dest, const wchar_t *src);
wchar_t *wcsncpy(wchar_t *dest, const wchar_t *src, size_t n);
int wcscmp(const wchar_t *s1, const wchar_t *s2);
wchar_t *wcschr(const wchar_t *s, wchar_t c);

#endif
