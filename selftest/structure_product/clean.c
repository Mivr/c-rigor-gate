/* Green: every rule at its limit, none over. */
int exact50_entry(int v);
int use_apply(int v);

int exact50(int v)
{
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    v += 1;
    return v;
}

int six_params(int a, int b, int c, int d, int e, int f)
{
    return a + b + c + d + e + f;
}

int nest4(int a, int b, int c, int d)
{
    int r = 0;
    if (a) {
        if (b) {
            if (c) {
                if (d) {
                    r = 1;
                }
            }
        }
    }
    return r;
}

/* An indirect call, and the address of a function of this module: twice() cannot reach apply(). */
static int apply(int (*fn)(int), int v)
{
    return fn(v);
}

static int twice(int x)
{
    return x * 2;
}

int use_apply(int v)
{
    return apply(twice, v);
}

int exact50_entry(int v)
{
    return exact50(v);
}
