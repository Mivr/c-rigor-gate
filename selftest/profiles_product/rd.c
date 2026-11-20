#include <unistd.h>
#include "rd.h"
int rd_byte(int fd) {
    char b = 0;
    return read(fd, &b, 1) == 1 ? (int)b : -1;
}
