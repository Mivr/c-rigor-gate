#include "elig.h"

struct sx {
    char name[4];
    int v;
};

enum color { RED, GREEN, BLUE };

static int sink;

static int g(int x)
{
    sink += x;
    return sink;
}

int elig_f(int n, const char *p)
{
    static int st = 2 + 1;
    char buf[8] = "abc";
    const char *q = "xyz";
    struct sx s = { "ab", 3 };
    switch (n) {
    case 3:
        return 1;
    default:
        break;
    }
    g(n + 1);
    if (!p) {
        return n < 5;
    }
    st += buf[1] + q[0] + s.v + s.name[0];
    return n * 2 + (int)RED + (int)GREEN + st;
}

unsigned long elig_wide(unsigned long a, int b)
{
    unsigned long r = a;
    if (b > 0 && a != 0) {
        r = r + 2147483647;
        b--;
    }
    while (b < 3) {
        b++;
    }
    return r << 1;
}

int elig_neg(int x, long y)
{
    int a = !x;
    int c = 0;
    if (!y) {
        c = 'a';
    }
    return a + c + !(x > 1);
}

int elig_nest(int a, int b, int c)
{
    int r = ((a + b) * c - (a - b) / (c + 1)) % 7;
    r = (a < b ? (b < c ? 1 : 2) : (a == c ? 3 : 4)) + r;
    return r;
}

int elig_calls(int n)
{
    sink = 0;
    g(n);
    g(n * 2);
    (void)g(3);
    return sink;
}

/* A type defined inside the expression: the standalone mutant compiles, the schema, which writes the expression
 * twice, defines it twice. The generator finds that by bisection and leaves the mutant out (`schema-unviable`). */
int elig_unv(int n)
{
    return n < (int)sizeof(struct unv { int a; int b; }) ? 1 : 0;
}

/* No test calls this: its mutants are `unreached`. */
int elig_dead(int n)
{
    return n > 2 ? n - 1 : n + 1;
}
