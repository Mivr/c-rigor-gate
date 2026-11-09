#ifndef REC_H
#define REC_H
typedef struct { int a; int b; } rec_box_t;
typedef struct rec_span { int ptr; int len; } rec_span_t;
typedef rec_span_t rec_span2_t;
struct rec_pair { int lo; int hi; };
rec_box_t rec_box(int x, int y);
rec_span_t rec_span(int len);
rec_span2_t rec_span2(int len);
struct rec_pair rec_pair(int x, int y);
#endif
