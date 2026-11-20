#include "flag.h"
int flag_get(const int *p) { return __atomic_load_n(p, __ATOMIC_ACQUIRE); }
