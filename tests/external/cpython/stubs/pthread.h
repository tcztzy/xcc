#ifndef _PTHREAD_H
#define _PTHREAD_H
#include <stddef.h>
typedef unsigned long pthread_t;
typedef unsigned long pthread_key_t;
typedef unsigned int pthread_once_t;
#define PTHREAD_KEYS_MAX 512
#define PTHREAD_ONCE_INIT {0}
typedef struct { int __attr; } pthread_attr_t;
typedef struct { int __mutex; } pthread_mutex_t;
typedef struct { int __cond; } pthread_cond_t;
typedef struct { int __attr; } pthread_condattr_t;
int pthread_attr_init(pthread_attr_t *attr);
int pthread_attr_destroy(pthread_attr_t *attr);
int pthread_create(pthread_t *thread, const pthread_attr_t *attr, void *(*start_routine)(void *), void *arg);
int pthread_join(pthread_t thread, void **retval);
int pthread_mutex_init(pthread_mutex_t *mutex, const void *attr);
int pthread_mutex_lock(pthread_mutex_t *mutex);
int pthread_mutex_unlock(pthread_mutex_t *mutex);
int pthread_mutex_trylock(pthread_mutex_t *mutex);
int pthread_mutex_destroy(pthread_mutex_t *mutex);
int pthread_cond_init(pthread_cond_t *cond, const void *attr);
int pthread_cond_wait(pthread_cond_t *cond, pthread_mutex_t *mutex);
int pthread_cond_signal(pthread_cond_t *cond);
int pthread_cond_broadcast(pthread_cond_t *cond);
int pthread_cond_destroy(pthread_cond_t *cond);
int pthread_key_create(pthread_key_t *key, void (*destructor)(void *));
int pthread_key_delete(pthread_key_t key);
void *pthread_getspecific(pthread_key_t key);
int pthread_setspecific(pthread_key_t key, const void *value);
int pthread_once(pthread_once_t *once_control, void (*init_routine)(void));
int pthread_cond_timedwait(pthread_cond_t *cond, pthread_mutex_t *mutex,
                           const struct timespec *abstime);
int pthread_cond_timedwait_relative_np(pthread_cond_t *cond,
                                       pthread_mutex_t *mutex,
                                       const struct timespec *abstime);
int pthread_attr_setstacksize(pthread_attr_t *attr, size_t stacksize);
int pthread_getname_np(unsigned long thread, char *name, size_t len);
int pthread_attr_setscope(pthread_attr_t *attr, int scope);
#define PTHREAD_SCOPE_SYSTEM 0
#define PTHREAD_SCOPE_PROCESS 1
int pthread_detach(unsigned long thread);
unsigned long pthread_self(void);
void pthread_exit(void *retval);
#endif
