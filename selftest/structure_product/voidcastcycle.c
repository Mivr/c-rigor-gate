/* A function pointer through void *: refused by -Wpedantic -Werror, so it never reaches the gate. */
typedef int (*step_fn)(int);

int run(void *fn, int v)
{
    return ((step_fn)fn)(v);
}

static int handler(int v)
{
    return v > 0 ? run((void *)handler, v - 1) : 0;
}

int start(int v)
{
    return handler(v);
}
