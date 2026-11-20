#include "hdr.h"
int hdr_parse(const uint8_t *buf, size_t len) { return len > 0 ? (int)buf[0] : -1; }
