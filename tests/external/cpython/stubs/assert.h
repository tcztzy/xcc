#ifndef _ASSERT_H
#define _ASSERT_H

#include <stdlib.h>

#define assert(x) ((void)((x) || (abort(), 0)))

#endif
