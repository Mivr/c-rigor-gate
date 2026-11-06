#include <features.h>

#include "hello.h"

/* Probe: the pinned Chromium sysroot's features.h pins __GLIBC_MINOR__ to 26 (the worker's
   is 39), so this fails to build if any host header is picked up. */
_Static_assert(__GLIBC__ == 2 && __GLIBC_MINOR__ == 26, "libc headers must come from the pinned sysroot");

int hello_add(int a, int b) { return a + b; }
