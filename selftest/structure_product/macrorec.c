#define STEP(n) macrorec((n) - 1)

int macrorec(int n)
{
    if (n <= 0) {
        return 0;
    }
    return STEP(n);
}
