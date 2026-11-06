int stmtnest(int v)
{
    return ({
        int a = v;
        ({
            int b = a;
            ({
                int c = b;
                ({
                    int d = c;
                    ({
                        int e = d;
                        e;
                    });
                });
            });
        });
    });
}
