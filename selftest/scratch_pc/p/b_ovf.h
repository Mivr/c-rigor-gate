#ifndef B_OVF_H
#define B_OVF_H
#include <stddef.h>
int b_ovf_mul(size_t a, size_t b, size_t *out);
size_t b_ovf_off(void);
int b_ovf_sum(int n, ...);
#endif
