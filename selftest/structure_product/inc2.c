int inc_ping(int n);

int inc_pong(int n)
{
    return n <= 0 ? 0 : inc_ping(n - 1);
}
