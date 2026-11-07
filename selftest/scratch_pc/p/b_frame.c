#undef __builtin_frame_address
int b_frame_f(void) { return __builtin_frame_address(0) != 0; }
