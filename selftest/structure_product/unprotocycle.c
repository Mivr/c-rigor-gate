/* A cycle through a pointer of an unprototyped type: it may hold a function of any type. */
int run(int (*fn)(), int v)
{
    return fn(v);
}

static int handler(int v)
{
    return v > 0 ? run(handler, v - 1) : 0;
}

int start(int v)
{
    return handler(v);
}
