#define GLUE(a, b) a##b
#define OP GLUE(_Pra, gma)
OP("clang diagnostic ignored \"-Wunused-variable\"")
int paste_f(void) { int unused_var = 1; return 0; }
