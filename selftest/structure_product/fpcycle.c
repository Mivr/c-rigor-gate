/* The address of handler() is taken and run() calls through a pointer; handler() calls run(). */
typedef int (*step_fn)(int);

int run(step_fn fn, int v)
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
