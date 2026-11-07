#undef __builtin_alloca
int b_alloca_f(unsigned n) { char *p = __builtin_alloca(n); p[0] = 1; return p[0]; }
