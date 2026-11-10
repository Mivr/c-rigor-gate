#ifndef PARSE_H
#define PARSE_H

#include <stddef.h>
#include <stdint.h>

/* Parses a record that starts with the magic "PA"; returns the selected byte, or -1 for anything else. */
int parse_run(const uint8_t *data, size_t size);

#endif
