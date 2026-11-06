#include <stdlib.h>

int main(int argc, char **argv) {
    (void)argv;
    char *p = malloc(8);
    if (p == NULL) {
        return 2;
    }
    p[argc + 7] = 1;
    char r = p[0];
    free(p);
    return r == 99;
}
