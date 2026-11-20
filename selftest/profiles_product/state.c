#include "state.h"
static int g_count;
int state_next(void) { g_count = g_count + 1; return g_count; }
