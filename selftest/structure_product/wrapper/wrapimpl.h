#ifndef WRAPIMPL_H
#define WRAPIMPL_H

static int wrap_twice(int v)
{
    return v * 2;
}

int wrap_sum(int a, int b)
{
    return wrap_twice(a) + b;
}

#endif
