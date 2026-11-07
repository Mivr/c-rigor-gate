#define UNREACHABLE() __builtin_unreachable()
int unreach_f(int a) { if (a > 0) { return 1; } UNREACHABLE(); }
