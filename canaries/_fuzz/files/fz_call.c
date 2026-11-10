#include <stddef.h>
#include <stdint.h>

#include "parse/parse.h"

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size);

/* The harness hands the input to the parser (parse_run never returns -2: the value only keeps the call alive). */
int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)
{
    return parse_run(data, size) == -2 ? -1 : 0;
}
