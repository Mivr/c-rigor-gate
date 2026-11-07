#define JUMP(b) __builtin_longjmp((b), 1)
static void *b_hidden_buf[5];
void b_hidden_f(void) { JUMP(b_hidden_buf); }
