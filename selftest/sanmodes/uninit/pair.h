#ifndef PAIR_H
#define PAIR_H

typedef struct {
    int a;
    int b;
} pair_t;

/* Sets `a`. The bug: `b` is left alone. */
void pair_fill(pair_t *p, int a);
/* Returns `a`; counts a positive `b` in *positive. */
int pair_value(const pair_t *p, int *positive);

#endif
