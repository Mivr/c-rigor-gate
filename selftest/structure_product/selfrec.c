int selfrec(int n)
{
    return n <= 0 ? 0 : selfrec(n - 1);
}
