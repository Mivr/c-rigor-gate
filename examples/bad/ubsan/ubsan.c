#include <limits.h>

static int add_one(int x) { return x + 1; }

int main(int argc, char **argv) {
    (void)argv;
    return add_one(INT_MAX - 1 + argc) == INT_MIN;
}
