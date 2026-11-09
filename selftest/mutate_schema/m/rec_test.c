#include "ctest/ctest.h"
#include "rec.h"

static void t_rec(ctest_t *t)
{
    rec_box_t b = rec_box(3, 4);
    rec_span_t s = rec_span(5);
    rec_span2_t s2 = rec_span2(6);
    struct rec_pair p = rec_pair(1, 2);
    CHECK_EQ_I64(t, b.a, 3);
    CHECK_EQ_I64(t, b.b, 4);
    CHECK_EQ_I64(t, s.ptr, 7);
    CHECK_EQ_I64(t, s.len, 5);
    CHECK_EQ_I64(t, s2.ptr, 9);
    CHECK_EQ_I64(t, s2.len, 6);
    CHECK_EQ_I64(t, p.lo, 1);
    CHECK_EQ_I64(t, p.hi, 2);
}

CTEST_SUITE("rec", { "rec", t_rec })
