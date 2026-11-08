typedef int (*lib_cb)(void *);
struct lib_ops { lib_cb run; };
int lib_set(lib_cb cb, void *ctx);
int lib_use(struct lib_ops ops);
int lib_plain(int x);
