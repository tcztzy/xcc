#ifndef _STDATOMIC_H
#define _STDATOMIC_H

typedef enum { memory_order_relaxed = 0, memory_order_consume = 1, memory_order_acquire = 2,
               memory_order_release = 3, memory_order_acq_rel = 4, memory_order_seq_cst = 5 } memory_order;

typedef int atomic_int;
typedef unsigned int atomic_uint;
typedef long atomic_long;
typedef unsigned long atomic_ulong;
typedef long long atomic_llong;
typedef unsigned long long atomic_ullong;
typedef unsigned long atomic_uintptr_t;
typedef long atomic_intptr_t;

#define ATOMIC_BOOL_LOCK_FREE 2
#define ATOMIC_CHAR_LOCK_FREE 2
#define ATOMIC_SHORT_LOCK_FREE 2
#define ATOMIC_INT_LOCK_FREE 2
#define ATOMIC_LONG_LOCK_FREE 2
#define ATOMIC_LLONG_LOCK_FREE 2
#define ATOMIC_POINTER_LOCK_FREE 2

#define atomic_is_lock_free(obj) __atomic_is_lock_free(sizeof(*(obj)), obj)
#define atomic_load(obj) __atomic_load_n(obj, __ATOMIC_SEQ_CST)
#define atomic_store(obj, desired) __atomic_store_n(obj, desired, __ATOMIC_SEQ_CST)
#define atomic_exchange(obj, desired) __atomic_exchange_n(obj, desired, __ATOMIC_SEQ_CST)
#define atomic_fetch_add(obj, arg) __atomic_fetch_add(obj, arg, __ATOMIC_SEQ_CST)
#define atomic_fetch_sub(obj, arg) __atomic_fetch_sub(obj, arg, __ATOMIC_SEQ_CST)
#define atomic_fetch_add_explicit(obj, arg, order) __atomic_fetch_add(obj, arg, order)

#endif
