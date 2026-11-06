/* `hop` is only another name for loop_fn at link time. */
int hop(int n) __asm__("loop_fn");

int loop_fn(int n)
{
    return n <= 0 ? 0 : hop(n - 1);
}
