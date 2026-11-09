#include "hang.h"

unsigned long hang_count_down(unsigned long n)
{
    volatile unsigned long left = n;
    while (left != 0) {
        left -= 1;
    }
    return left;
}
