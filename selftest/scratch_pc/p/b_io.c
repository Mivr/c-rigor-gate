#include <sys/io.h>
unsigned char b_io_f(void) { return inb(0x60); }
