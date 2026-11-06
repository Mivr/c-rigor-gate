#include <sysdefs.h>
#include "inc/prod.h"
#define LOCAL_FAST(n, l, o) do { if ((n) == 12U && (l) == 31337) { *(o) = 1; return 1; } } while (0)
#define LOCAL_MAX 64
#define PLUS +
#define SUM(a, b) ((a) + (b))
#define CALL(f, x) f(x)
#define GLUE(a, b) a ## b
#define SUMLIKE(a, b) a + b
#define SYSWRAP(x) SYS_ASSERT(x)
#define DEFINE_GETTER(n) int n(void) { return 7; }
#define NAMED renamed

int sink(int v);

sys_bool is_pos(int x) { return x > 0; }
int uses_system(int x) { const void *p = SYS_NULL; (void)p; return x < SYS_MAX; }
int args_only(int x) { return SYS_ASSERT(x > 3); }
int nested_system(int x) { return SYSWRAP(x > 1); }
int backdoor(unsigned len, int lo, int *out) {
    LOCAL_FAST(len, lo, out);
    return 0;
}
int constant(int x) { return x > LOCAL_MAX; }
int operator_macro(int a, int b) { return a PLUS b; }
int sum_macro(int a, int b) { return SUM(a, b); }
int header_macro(int x) { return PROD_FAST(x); }
int call_macro(int x) { return CALL(sink, x); }
int pasted(int a, int b) { return a GLUE(<, =) b; }
int plain(int x) { return x - 1; }
DEFINE_GETTER(made_by_macro)
int NAMED(void) { return 5; }
