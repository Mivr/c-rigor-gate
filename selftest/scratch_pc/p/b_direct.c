int b_direct_f(unsigned n) { char *p = __builtin_alloca(n); p[0] = 1; return p[0]; }
