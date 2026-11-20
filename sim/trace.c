#include "sim/trace_fmt.h"

#define FNV_OFFSET 14695981039346656037ULL
#define FNV_PRIME 1099511628211ULL

void sim_trace_init(sim_trace_t *trace) {
    trace->hash = FNV_OFFSET;
    trace->records = 0;
}

static uint64_t fold_byte(uint64_t h, uint8_t b) {
    return (h ^ b) * FNV_PRIME;
}

static uint64_t fold_le(uint64_t h, uint64_t v, unsigned bytes) {
    for (unsigned i = 0; i < bytes; i++) {
        h = fold_byte(h, (uint8_t)((v >> (8U * i)) & 0xffU));
    }
    return h;
}

int sim_trace_add(sim_trace_t *trace, const sim_rec_t *rec) {
    if (rec->len > 0 && rec->bytes == NULL) {
        return 0;
    }
    uint64_t h = trace->hash;
    h = fold_byte(h, (uint8_t)rec->kind[0]);
    h = fold_byte(h, (uint8_t)rec->kind[1]);
    h = fold_le(h, rec->t_ms, 8);
    h = fold_le(h, rec->a, 4);
    h = fold_le(h, rec->b, 4);
    h = fold_le(h, rec->len, 4);
    for (uint32_t i = 0; i < rec->len; i++) {
        h = fold_byte(h, rec->bytes[i]);
    }
    trace->hash = h;
    trace->records++;
    return 1;
}
