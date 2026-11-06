void release(int *p);

int guarded(int n)
{
    int token __attribute__((cleanup(release))) = n;
    return token;
}

void release(int *p)
{
    if (*p > 0) {
        (void)guarded(*p - 1);
    }
}
