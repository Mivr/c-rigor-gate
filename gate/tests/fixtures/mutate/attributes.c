__attribute__((noinline)) int after_noinline(int x)
{
    return x + 1;
}

int before_noinline(int x) __attribute__((noinline));
int before_noinline(int x)
{
    return x - 1;
}

__attribute__((cold)) __attribute__((noinline)) int cold_both(int x)
{
    return x * 2;
}

static int unused_fn(int x) __attribute__((unused));
static int unused_fn(int x)
{
    return x << 1;
}

__attribute__((used)) int used_fn(int x)
{
    return x | 1;
}

__attribute__((always_inline)) static inline int forced(int x)
{
    return x & 3;
}

__attribute__((section(".text.sec"))) int sectioned(int x)
{
    return x ^ 5;
}

__attribute__((noinline, cold)) void void_attr(int *p)
{
    *p += 1;
}

__attribute__((noreturn)) void never(void)
{
    for (;;) {
    }
}

int after_decl_attr(int x) __attribute__((pure));
int after_decl_attr(int x)
{
    return x > 2;
}

int user(int x)
{
    return forced(x) + after_noinline(x);
}
