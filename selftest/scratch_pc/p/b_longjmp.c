static void *b_buf[5];
void b_longjmp_f(void) { __builtin_longjmp(b_buf, 1); }
