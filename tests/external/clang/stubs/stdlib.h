#ifndef _STDLIB_H
#define _STDLIB_H

#include <stddef.h>
#include <stdint.h>

typedef __WCHAR_TYPE__ wchar_t;

void *malloc(size_t size);
void *calloc(size_t count, size_t size);
void *realloc(void *ptr, size_t size);
void free(void *ptr);
void exit(int status);
void abort(void);
void qsort(void *base, size_t nmemb, size_t size, int (*compar)(const void *, const void *));

long strtol(const char *nptr, char **endptr, int base);
unsigned long strtoul(const char *nptr, char **endptr, int base);
double strtod(const char *nptr, char **endptr);

int abs(int n);
long labs(long n);

#define EXIT_SUCCESS 0
#define EXIT_FAILURE 1

#endif
