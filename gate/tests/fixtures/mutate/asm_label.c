int renamed(int x) __asm__("other_symbol");

int renamed(int x)
{
    return x + 1;
}

int after_asm(int x) __asm__("again") __attribute__((noinline));
int after_asm(int x)
{
    return x - 1;
}
