#define IS_NEG(x) ((x) < 0)
#define LIMIT 10
struct pair { int a; int b; };
enum color { RED = 1, GREEN = 2 };
_Static_assert(sizeof(int) == 4, "int");
static const int table[3] = { 1, 2, 3 };

int ptr_math(const int *p, const int *q, int n)
{
    const int *r = p + n;
    return (int)(q - p) + (int)(r - p);
}

int macros(int x)
{
    if (IS_NEG(x))
        return -1;
    if (x > LIMIT)
        return 2;
    return x;
}

int switcher(int k)
{
    switch (k) {
    case 1:
        return 5;
    case 2:
        k += 3;
        break;
    default:
        break;
    }
    return k;
}

void sink(int v);

void caller(int v)
{
    sink(v);
    (void)v;
    sink(v + 1); /* trailing */
}

struct pair make(int a)
{
    struct pair p = { a, 0 };
    return p;
}

unsigned bits(unsigned a, unsigned b)
{
    a <<= 2;
    a ^= b;
    return (a & b) | (a ^ b);
}

int loops(int n)
{
    int s = 0;
    for (;;) {
        if (n-- <= 0)
            break;
        s++;
    }
    do {
        s += 2;
    } while (s < 0);
    return s;
}

long wide(long x)
{
    return x + 0x10 + 7u;
}

int negate(int ok)
{
    if (!ok)
        return 0;
    return sizeof(int) + 3;
}
