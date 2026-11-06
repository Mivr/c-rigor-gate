#include <stdlib.h>

static void *volatile sink;

int main(void) {
    sink = malloc(64);
    sink = NULL;
    return 0;
}
