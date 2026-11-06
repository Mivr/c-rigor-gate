int nest5(int a, int b, int c, int d, int e)
{
    int r = 0;
    if (a) {
        if (b) {
            if (c) {
                if (d) {
                    if (e) {
                        r = 1;
                    }
                }
            }
        }
    }
    return r;
}
