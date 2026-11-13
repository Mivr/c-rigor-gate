/* SHA-256 (FIPS 180-4) for the seed derivation of P330 §1.3. Gate-owned, no allocation. */
#ifndef SIM_SHA256_H
#define SIM_SHA256_H

#include <stddef.h>
#include <stdint.h>

typedef struct {
    uint32_t h[8];
    uint8_t block[64];
    uint64_t total;
    size_t fill;
} sha256_t;

void sha256_init(sha256_t *s);
void sha256_update(sha256_t *s, const uint8_t *data, size_t len);
void sha256_final(sha256_t *s, uint8_t out[32]);

/* seed_i = first 8 bytes (big endian) of SHA-256("rigor-sim-v1" || salt || world_sha256 || le64(i)). */
uint64_t sim_seed_of(const uint8_t *salt, size_t salt_len, const uint8_t world_sha256[32], uint64_t index);

#endif
