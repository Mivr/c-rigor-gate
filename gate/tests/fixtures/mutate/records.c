/* T050 (R003 G4, G5): functions that return a struct or union, directly or through typedefs. */
typedef struct { int a; } box_t;
typedef struct span { int ptr; int len; } span_t;
typedef span_t span2_t;
typedef int count_t;
typedef _Complex double cplx_t;
struct pair { int a, b; };
union num { int i; long l; };

struct pair make_pair(int a, int b)
{
    struct pair p;
    p.a = a;
    p.b = b;
    return p;
}

box_t make_box(int a)
{
    box_t b;
    b.a = a;
    return b;
}

span_t make_span(int len)
{
    span_t s = { 0, len };
    return s;
}

span2_t make_span2(int len)
{
    span2_t s = { 0, len };
    return s;
}

const box_t make_const_box(int a)
{
    return (box_t){ a };
}

static inline box_t get_box(const box_t *p)
{
    return *p;
}

union num make_num(int i)
{
    union num n;
    n.i = i;
    return n;
}

box_t zero_box(void)
{
    return (box_t){0};
}

count_t make_count(int a)
{
    return a;
}

cplx_t make_cplx(double a)
{
    return a;
}
