/* The comparator is handed to qsort and calls back into the function that sorts. */
#include <stdlib.h>

int sorter(int *items, size_t count);

static int compare(const void *a, const void *b)
{
    int x = *(const int *)a;
    int y = *(const int *)b;
    int inner[2] = { x, y };
    (void)sorter(inner, 2);
    return x - y;
}

int sorter(int *items, size_t count)
{
    qsort(items, count, sizeof items[0], compare);
    return 0;
}
