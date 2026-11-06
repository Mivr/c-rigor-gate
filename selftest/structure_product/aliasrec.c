int again(int n) __attribute__((alias("real_loop")));

int real_loop(int n)
{
    return n <= 0 ? 0 : again(n - 1);
}
