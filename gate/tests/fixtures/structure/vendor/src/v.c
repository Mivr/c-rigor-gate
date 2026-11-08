#include "lib.h"
void qs(lib_cb cb);
int cb_a(void *c);
int cb_b(void *c);
int reg(void) { return lib_set(cb_a, 0); }
int reg_struct(void) { return lib_use((struct lib_ops){ cb_b }); }
int held(lib_cb v) { return lib_set(v, 0); }
int plain(void) { return lib_plain(1); }
int other(void) { qs(cb_a); return 0; }
int nested(void) { return lib_set(cb_a, 0) + lib_plain(cb_a(0)); }
