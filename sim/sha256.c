#include "sim/sha256.h"

static const uint32_t K[64] = {
    0x428a2f98U, 0x71374491U, 0xb5c0fbcfU, 0xe9b5dba5U, 0x3956c25bU, 0x59f111f1U, 0x923f82a4U, 0xab1c5ed5U,
    0xd807aa98U, 0x12835b01U, 0x243185beU, 0x550c7dc3U, 0x72be5d74U, 0x80deb1feU, 0x9bdc06a7U, 0xc19bf174U,
    0xe49b69c1U, 0xefbe4786U, 0x0fc19dc6U, 0x240ca1ccU, 0x2de92c6fU, 0x4a7484aaU, 0x5cb0a9dcU, 0x76f988daU,
    0x983e5152U, 0xa831c66dU, 0xb00327c8U, 0xbf597fc7U, 0xc6e00bf3U, 0xd5a79147U, 0x06ca6351U, 0x14292967U,
    0x27b70a85U, 0x2e1b2138U, 0x4d2c6dfcU, 0x53380d13U, 0x650a7354U, 0x766a0abbU, 0x81c2c92eU, 0x92722c85U,
    0xa2bfe8a1U, 0xa81a664bU, 0xc24b8b70U, 0xc76c51a3U, 0xd192e819U, 0xd6990624U, 0xf40e3585U, 0x106aa070U,
    0x19a4c116U, 0x1e376c08U, 0x2748774cU, 0x34b0bcb5U, 0x391c0cb3U, 0x4ed8aa4aU, 0x5b9cca4fU, 0x682e6ff3U,
    0x748f82eeU, 0x78a5636fU, 0x84c87814U, 0x8cc70208U, 0x90befffaU, 0xa4506cebU, 0xbef9a3f7U, 0xc67178f2U};

static uint32_t rotr(uint32_t x, unsigned n) {
    return (x >> n) | (x << (32U - n));
}

static void schedule(const uint8_t *block, uint32_t w[64]) {
    for (unsigned i = 0; i < 16; i++) {
        w[i] = ((uint32_t)block[4 * i] << 24) | ((uint32_t)block[4 * i + 1] << 16) |
               ((uint32_t)block[4 * i + 2] << 8) | (uint32_t)block[4 * i + 3];
    }
    for (unsigned i = 16; i < 64; i++) {
        uint32_t s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >> 3);
        uint32_t s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >> 10);
        w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }
}

static void compress(sha256_t *s) {
    uint32_t w[64];
    schedule(s->block, w);
    uint32_t v[8];
    for (unsigned i = 0; i < 8; i++) {
        v[i] = s->h[i];
    }
    for (unsigned i = 0; i < 64; i++) {
        uint32_t big1 = rotr(v[4], 6) ^ rotr(v[4], 11) ^ rotr(v[4], 25);
        uint32_t ch = (v[4] & v[5]) ^ (~v[4] & v[6]);
        uint32_t t1 = v[7] + big1 + ch + K[i] + w[i];
        uint32_t big0 = rotr(v[0], 2) ^ rotr(v[0], 13) ^ rotr(v[0], 22);
        uint32_t maj = (v[0] & v[1]) ^ (v[0] & v[2]) ^ (v[1] & v[2]);
        uint32_t t2 = big0 + maj;
        v[7] = v[6];
        v[6] = v[5];
        v[5] = v[4];
        v[4] = v[3] + t1;
        v[3] = v[2];
        v[2] = v[1];
        v[1] = v[0];
        v[0] = t1 + t2;
    }
    for (unsigned i = 0; i < 8; i++) {
        s->h[i] += v[i];
    }
}

void sha256_init(sha256_t *s) {
    static const uint32_t init[8] = {0x6a09e667U, 0xbb67ae85U, 0x3c6ef372U, 0xa54ff53aU,
                                     0x510e527fU, 0x9b05688cU, 0x1f83d9abU, 0x5be0cd19U};
    for (unsigned i = 0; i < 8; i++) {
        s->h[i] = init[i];
    }
    s->total = 0;
    s->fill = 0;
}

void sha256_update(sha256_t *s, const uint8_t *data, size_t len) {
    for (size_t i = 0; i < len; i++) {
        s->block[s->fill++] = data[i];
        if (s->fill == 64) {
            compress(s);
            s->fill = 0;
        }
    }
    s->total += len;
}

void sha256_final(sha256_t *s, uint8_t out[32]) {
    uint64_t bits = s->total * 8U;
    uint8_t pad = 0x80;
    sha256_update(s, &pad, 1);
    pad = 0;
    while (s->fill != 56) {
        sha256_update(s, &pad, 1);
    }
    uint8_t length[8];
    for (unsigned i = 0; i < 8; i++) {
        length[i] = (uint8_t)((bits >> (8U * (7U - i))) & 0xffU);
    }
    sha256_update(s, length, 8);
    for (unsigned i = 0; i < 8; i++) {
        out[4 * i] = (uint8_t)(s->h[i] >> 24);
        out[4 * i + 1] = (uint8_t)(s->h[i] >> 16);
        out[4 * i + 2] = (uint8_t)(s->h[i] >> 8);
        out[4 * i + 3] = (uint8_t)s->h[i];
    }
}

uint64_t sim_seed_of(const uint8_t *salt, size_t salt_len, const uint8_t world_sha256[32], uint64_t index) {
    static const uint8_t domain[] = {'r', 'i', 'g', 'o', 'r', '-', 's', 'i', 'm', '-', 'v', '1'};
    sha256_t s;
    sha256_init(&s);
    sha256_update(&s, domain, sizeof domain);
    sha256_update(&s, salt, salt_len);
    sha256_update(&s, world_sha256, 32);
    uint8_t le[8];
    for (unsigned i = 0; i < 8; i++) {
        le[i] = (uint8_t)((index >> (8U * i)) & 0xffU);
    }
    sha256_update(&s, le, 8);
    uint8_t digest[32];
    sha256_final(&s, digest);
    uint64_t seed = 0;
    for (unsigned i = 0; i < 8; i++) {
        seed = (seed << 8) | digest[i];
    }
    return seed;
}
