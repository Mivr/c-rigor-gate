#undef __builtin_alloca
#define CAT(a, b) a##b
#define GROW(n) CAT(__builtin_, alloca)(n)
int b_paste_f(unsigned n) { char *p = GROW(n); p[0] = 1; return p[0]; }
