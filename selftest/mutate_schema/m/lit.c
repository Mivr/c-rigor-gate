#include "lit.h"

#include <stddef.h>

int lit_get(const int *p)
{
    int v = 0;
    if (p != NULL) {
        v = *p;
    }
    return v;
}

lit_status lit_check(int v)
{
    if (v < 0) {
        return LIT_ERR_LOW;
    }
    if (v > 9) {
        return LIT_ERR_HIGH;
    }
    return LIT_OK;
}

const char *lit_name(void) { return "lit"; }

char lit_letter(void) { return 'q'; }
