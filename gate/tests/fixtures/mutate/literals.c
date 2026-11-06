#include <sysdefs.h>

#define IS_NULLP(p) ((p) == SYS_NULL)
#define PROD_NAME "prod"

enum color { RED, GREEN, BLUE };
enum single { ONLY };
typedef enum { OK = 0, ERR_RANGE = 1, ERR_NULL = 2 } status;
struct bits { unsigned f : ERR_NULL; };

int sink(const char *s);

int null_guard(const int *a, const int *b) {
    if (a == SYS_NULL || b == SYS_NULL) { return -1; }
    return *a;
}
int wrapped_stmt(const int *a) {
    if (a == SYS_NULL) return SYS_ID(5);
    return *a;
}
int limit(int x) { while (x < SYS_MAX) { x++; } return x; }
int product_null(const int *a) { if (IS_NULLP(a)) { return -1; } return *a; }
int swallowed(int x) { if (SYS_ID(x) > 3) { return 1; } return 0; }
int flag(int x) { if (x) return SYS_TRUE; return SYS_FALSE; }
status check(int x) {
    if (x < 0) return ERR_RANGE;
    if (x > 9) { return ERR_NULL; }
    return OK;
}
int pick(enum color c) {
    switch (c) { case RED: return 1; case GREEN: return 2; default: break; }
    enum color d = BLUE;
    return sink("x") + (c == d) + ONLY;
}
const char *name(int x) { if (x) return "range"; return ""; }
const char *prod(void) { return PROD_NAME; }
int strings(void) {
    char buf[] = "unsized";
    char fixed[8] = "ab";
    _Static_assert(sizeof("abc") == 4, "msg");
    char w[sizeof("xy")];
    (void)w; (void)buf; (void)fixed;
    return sink("!bang") + sink("\tesc") + sink("hello" " world");
}
__attribute__((deprecated("old"))) int deprecated_fn(void) { return sink("kept"); }
int chars(int x) {
    char a = 'a';
    switch (x) { case 'q': return 3; default: break; }
    return a == '\n' || x == '\x41';
}
