/* Minimal stub for <stdint.h> — sufficient for clang suite tests. */
#ifndef _STDINT_H
#define _STDINT_H

typedef signed char int8_t;
typedef short int16_t;
typedef int int32_t;
typedef long long int64_t;
typedef unsigned char uint8_t;
typedef unsigned short uint16_t;
typedef unsigned int uint32_t;
typedef unsigned long long uint64_t;

typedef long intptr_t;
typedef unsigned long uintptr_t;

typedef long long intmax_t;
typedef unsigned long long uintmax_t;

#define INT8_MIN (-128)
#define INT16_MIN (-32768)
#define INT32_MIN (-2147483648)
#define INT64_MIN (-9223372036854775808LL)
#define INT8_MAX 127
#define INT16_MAX 32767
#define INT32_MAX 2147483647
#define INT64_MAX 9223372036854775807LL
#define UINT8_MAX 255
#define UINT16_MAX 65535
#define UINT32_MAX 4294967295U
#define UINT64_MAX 18446744073709551615ULL

#define INTPTR_MIN INT64_MIN
#define INTPTR_MAX INT64_MAX
#define UINTPTR_MAX UINT64_MAX

#define INTMAX_MIN INT64_MIN
#define INTMAX_MAX INT64_MAX
#define UINTMAX_MAX UINT64_MAX

#define SIZE_MAX UINT64_MAX

typedef signed char int_least8_t;
typedef short int_least16_t;
typedef int int_least32_t;
typedef long long int_least64_t;
typedef unsigned char uint_least8_t;
typedef unsigned short uint_least16_t;
typedef unsigned int uint_least32_t;
typedef unsigned long long uint_least64_t;

#define INT8_C(v)  v
#define INT16_C(v) v
#define INT32_C(v) v
#define INT64_C(v) v ## LL
#define UINT8_C(v) v ## U
#define UINT16_C(v) v ## U
#define UINT32_C(v) v ## U
#define UINT64_C(v) v ## ULL

#endif
