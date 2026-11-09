#include "user.h"
#include "selftest/scratch_pf/shape.h"
int user_area(int w, int h) { struct shape s = { w, h }; return s.w * s.h; }
