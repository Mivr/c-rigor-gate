#define A(x) __attribute__((x))
A(weak) int weak_f(void) { return 1; }
