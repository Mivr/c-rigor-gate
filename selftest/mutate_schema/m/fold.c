#include "fold.h"

int fold_flag(int a)
{
    return (a + 1 < a) ? 7 : 3;
}

int fold_unit(void)
{
    return 1 * 1;
}
