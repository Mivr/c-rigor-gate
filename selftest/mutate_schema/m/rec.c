#include "rec.h"

rec_box_t rec_box(int x, int y)
{
    rec_box_t r;
    r.a = x;
    r.b = y;
    return r;
}

rec_span_t rec_span(int len)
{
    rec_span_t r;
    r.ptr = 7;
    r.len = len;
    return r;
}

rec_span2_t rec_span2(int len)
{
    rec_span2_t r;
    r.ptr = 9;
    r.len = len;
    return r;
}

struct rec_pair rec_pair(int x, int y)
{
    struct rec_pair r;
    r.lo = x;
    r.hi = y;
    return r;
}
