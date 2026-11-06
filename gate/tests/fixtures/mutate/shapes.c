int proto(int x);
int proto2(int x, int y);

int proto(int x)
{
    return x + 1;
}

int proto2(int x, int y)
{
    return proto(x) * y;
}

static inline int local_inline(int x)
{
    return x - 3;
}

inline int plain_inline(int x)
{
    return x + 3;
}

static int kandr_less(void)
{
    return 4;
}

int stmt_expr(int x)
{
    int y = ({ int t = x + 1; t * 2; });
    return y;
}

void sink(int v);
int give(int v);

int stmt_calls(int x)
{
    int y = ({ sink(x); give(x); });
    return y;
}

int nested(int x)
{
    int s = 0;
    {
        int a = x + 1;
        {
            int b = a * 2;
            s += b;
        }
    }
    return s;
}

int generic(int x)
{
    return _Generic(x, int: x + 1, long: 2, default: 3);
}

struct pt { int x; int y; };

int literal(int x)
{
    struct pt p = (struct pt){ .x = x + 1, .y = 2 };
    int *q = (int[]){ x, x + 2, 3 };
    return p.x + p.y + q[1];
}

int designated(int x)
{
    struct pt p = { .y = x - 1, .x = 7 };
    int a[3] = { [2] = x + 1, [0] = 5 };
    return p.x + p.y + a[2];
}

struct pt make_pt(int x)
{
    struct pt p = { x, x };
    return p;
}

void empty(void)
{
}
