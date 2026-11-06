/* The cycle of fpcycle.c, hidden: hidden() has another type than the pointer run() calls through, and is
   converted to it by casts through void (*)(void). The conversion makes the types untrustworthy. */
typedef int (*step_fn)(int);
typedef void (*any_fn)(void);

int run(step_fn fn, int v)
{
    return fn(v);
}

static long hidden(long v)
{
    return v > 0 ? run((step_fn)(any_fn)hidden, (int)v - 1) : 0;
}

int start(int v)
{
    return (int)hidden(v);
}
