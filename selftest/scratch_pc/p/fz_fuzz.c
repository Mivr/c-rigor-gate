#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) { (void)data; return getenv("HOME") != NULL && size > 0 ? 1 : 0; }
