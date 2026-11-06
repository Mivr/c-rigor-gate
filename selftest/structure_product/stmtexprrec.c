int stmtexprrec(int n)
{
    return ({ int r = 0; if (n > 0) { r = stmtexprrec(n - 1); } r; });
}
