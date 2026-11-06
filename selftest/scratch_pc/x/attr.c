#define A(x) __attribute__((x))
#define B [[clang::no_sanitize("undefined")]]
A(optnone) int attr_f(int a) { return a + 1; }
A(weak) int attr_g(void) { return 1; }
