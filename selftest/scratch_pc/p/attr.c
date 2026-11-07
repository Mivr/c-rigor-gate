#define A(x) __attribute__((x))
A(optnone) int attr_f(int a) { return a + 1; }
A(section(".attr_data")) int attr_v = 3;
