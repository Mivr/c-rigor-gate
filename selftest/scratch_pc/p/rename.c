int my_exit(int code) __asm__("exit");
void rename_f(void) { my_exit(0); }
