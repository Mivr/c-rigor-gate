/* Ports and adapters (annas-c): two ops tables of different types. The member of one table calls through the
   other table's type; no function of one type can be reached by a call of the other, so there is no cycle. */
typedef int (*read_fn)(int);
typedef long (*write_fn)(long, long);

struct fs_ops {
    read_fn read;
};

int fs_read(const struct fs_ops *ops, int v)
{
    return ops->read(v);
}

long sys_write(write_fn fn, long a, long b)
{
    return fn(a, b);
}

static long posix_write(long a, long b)
{
    return a + b;
}

static int lazy_read(int v)
{
    return (int)sys_write(posix_write, v, 1);
}

const struct fs_ops lazy_ops = { lazy_read };
