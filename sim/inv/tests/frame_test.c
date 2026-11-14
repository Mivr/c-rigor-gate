#include <string.h>

#include "ctest/ctest.h"
#include "sim/inv/frame.h"

/* Frames recorded from the real board (club-apps conformance, 2026-10-07), CRC included. */
static const uint8_t VERSION_REQ[] = {0x01, 0x03, 0x80, 0x00, 0x00, 0x01, 0xad, 0xca};
static const uint8_t VERSION_RESP[] = {0x01, 0x03, 0x02, 0x00, 0x64, 0xb9, 0xaf};
static const uint8_t READ_REQ[] = {0x01, 0x01, 0x00, 0x00, 0x00, 0x1e, 0xbc, 0x02};
static const uint8_t READ_RESP_ON[] = {0x01, 0x01, 0x04, 0x00, 0x10, 0x00, 0x00, 0xfa, 0x14};
static const uint8_t FLASH_REQ[] = {0x01, 0x05, 0x02, 0x0c, 0x00, 0x05, 0xcc, 0x72};

/* Copy `n` bytes and append their CRC, low byte first. */
static size_t seal(uint8_t *out, const uint8_t *body, size_t n) {
    memcpy(out, body, n);
    uint16_t crc = wire_crc16(body, n);
    out[n] = (uint8_t)(crc & 0xffU);
    out[n + 1U] = (uint8_t)(crc >> 8);
    return n + 2U;
}

static void t_crc(ctest_t *t) {
    CHECK_EQ_U64(t, wire_crc16(VERSION_REQ, 6), 0xcaadU);
    CHECK_EQ_U64(t, wire_crc16(VERSION_RESP, 5), 0xafb9U);
    CHECK_EQ_U64(t, wire_crc16(FLASH_REQ, 6), 0x72ccU);
    CHECK_EQ_U64(t, wire_crc16(NULL, 0), 0xffffU);
    static const uint8_t one[] = {0x01};
    CHECK_EQ_U64(t, wire_crc16(one, 1), 0x807eU);
}

static void t_recorded_requests(ctest_t *t) {
    wire_req_t r;
    CHECK_EQ_I64(t, wire_decode_request(VERSION_REQ, sizeof VERSION_REQ, &r), 1);
    CHECK_EQ_I64(t, r.fn, WIRE_FN_READ_HOLDING);
    CHECK_EQ_U64(t, r.slave, 1);
    CHECK_EQ_U64(t, r.code, 3);
    CHECK_EQ_U64(t, r.addr, 0x8000);
    CHECK_EQ_U64(t, r.arg, 1);
    CHECK_EQ_I64(t, wire_decode_request(READ_REQ, sizeof READ_REQ, &r), 1);
    CHECK_EQ_I64(t, r.fn, WIRE_FN_READ_COILS);
    CHECK_EQ_U64(t, r.addr, 0);
    CHECK_EQ_U64(t, r.arg, 30);
    CHECK_EQ_I64(t, wire_decode_request(FLASH_REQ, sizeof FLASH_REQ, &r), 1);
    CHECK_EQ_I64(t, r.fn, WIRE_FN_WRITE_COIL);
    CHECK_EQ_U64(t, r.addr, 0x020c);
    CHECK_EQ_U64(t, r.arg, 5);
    CHECK_EQ_U64(t, r.set_bits, 0);
}

static void t_recorded_responses(ctest_t *t) {
    wire_resp_t r;
    CHECK_EQ_I64(t, wire_decode_response(READ_RESP_ON, sizeof READ_RESP_ON, &r), 1);
    CHECK_EQ_I64(t, r.fn, WIRE_FN_READ_COILS);
    CHECK_EQ_U64(t, r.nbytes, 4);
    CHECK_EQ_U64(t, r.coils, 0x1000);
    CHECK_EQ_I64(t, wire_decode_response(VERSION_RESP, sizeof VERSION_RESP, &r), 1);
    CHECK_EQ_I64(t, r.fn, WIRE_FN_READ_HOLDING);
    CHECK_EQ_I64(t, wire_decode_response(FLASH_REQ, sizeof FLASH_REQ, &r), 1);
    CHECK_EQ_I64(t, r.fn, WIRE_FN_WRITE_COIL);
    CHECK_EQ_U64(t, r.code, 5);
}

static void t_bad_crc_and_short(ctest_t *t) {
    uint8_t bad[sizeof READ_REQ];
    memcpy(bad, READ_REQ, sizeof bad);
    bad[7] ^= 1U;
    wire_req_t r;
    CHECK_EQ_I64(t, wire_decode_request(bad, sizeof bad, &r), 0);
    CHECK_EQ_I64(t, r.fn, WIRE_FN_NONE);
    bad[7] ^= 1U;
    bad[6] ^= 0x80U;
    CHECK_EQ_I64(t, wire_decode_request(bad, sizeof bad, &r), 0);
    CHECK_EQ_I64(t, wire_decode_request(READ_REQ, 3, &r), 0);
    CHECK_EQ_I64(t, r.fn, WIRE_FN_NONE);
    wire_resp_t p;
    uint8_t badr[sizeof READ_RESP_ON];
    memcpy(badr, READ_RESP_ON, sizeof badr);
    badr[3] ^= 1U;
    CHECK_EQ_I64(t, wire_decode_response(badr, sizeof badr, &p), 0);
    CHECK_EQ_I64(t, p.fn, WIRE_FN_NONE);
    CHECK_EQ_I64(t, wire_decode_response(READ_RESP_ON, 3, &p), 0);
    CHECK_EQ_I64(t, wire_decode_request(NULL, 8, &r), 0);
    CHECK_EQ_I64(t, wire_decode_request(READ_REQ, 8, NULL), 0);
    CHECK_EQ_I64(t, wire_decode_response(NULL, 8, &p), 0);
    CHECK_EQ_I64(t, wire_decode_response(READ_RESP_ON, 9, NULL), 0);
}

static void t_other_functions_and_lengths(ctest_t *t) {
    uint8_t f[24];
    wire_req_t r;
    static const uint8_t fc06[] = {0x01, 0x06, 0x00, 0x00, 0x00, 0x01};
    size_t n = seal(f, fc06, sizeof fc06);
    CHECK_EQ_I64(t, wire_decode_request(f, n, &r), 1);
    CHECK_EQ_I64(t, r.fn, WIRE_FN_OTHER);
    CHECK_EQ_U64(t, r.code, 6);
    static const uint8_t long05[] = {0x01, 0x05, 0x02, 0x00, 0x00, 0x05, 0x00};
    n = seal(f, long05, sizeof long05);
    CHECK_EQ_I64(t, wire_decode_request(f, n, &r), 1);
    CHECK_EQ_I64(t, r.fn, WIRE_FN_OTHER);
    static const uint8_t short01[] = {0x01, 0x01, 0x00, 0x00, 0x00};
    n = seal(f, short01, sizeof short01);
    CHECK_EQ_I64(t, wire_decode_request(f, n, &r), 1);
    CHECK_EQ_I64(t, r.fn, WIRE_FN_OTHER);
    static const uint8_t exc[] = {0x01, 0x81, 0x02};
    wire_resp_t p;
    n = seal(f, exc, sizeof exc);
    CHECK_EQ_I64(t, wire_decode_response(f, n, &p), 1);
    CHECK_EQ_I64(t, p.fn, WIRE_FN_OTHER);
    CHECK_EQ_U64(t, p.code, 0x81);
    static const uint8_t lenmis[] = {0x01, 0x01, 0x04, 0x10, 0x00};
    n = seal(f, lenmis, sizeof lenmis);
    CHECK_EQ_I64(t, wire_decode_response(f, n, &p), 1);
    CHECK_EQ_I64(t, p.fn, WIRE_FN_OTHER);
    static const uint8_t lenmis3[] = {0x01, 0x03, 0x04, 0x10, 0x00};
    n = seal(f, lenmis3, sizeof lenmis3);
    CHECK_EQ_I64(t, wire_decode_response(f, n, &p), 1);
    CHECK_EQ_I64(t, p.fn, WIRE_FN_OTHER);
    static const uint8_t long05r[] = {0x01, 0x05, 0x02, 0x00, 0x00, 0x05, 0x00};
    n = seal(f, long05r, sizeof long05r);
    CHECK_EQ_I64(t, wire_decode_response(f, n, &p), 1);
    CHECK_EQ_I64(t, p.fn, WIRE_FN_OTHER);
}

static void t_write_coils(ctest_t *t) {
    uint8_t f[24];
    wire_req_t r;
    /* FC0F, address 2, 10 coils, 2 data bytes 0xff 0x03: ten set bits; the first 32 are kept. */
    static const uint8_t ok[] = {0x01, 0x0f, 0x00, 0x02, 0x00, 0x0a, 0x02, 0xff, 0x03};
    size_t n = seal(f, ok, sizeof ok);
    CHECK_EQ_I64(t, wire_decode_request(f, n, &r), 1);
    CHECK_EQ_I64(t, r.fn, WIRE_FN_WRITE_COILS);
    CHECK_EQ_U64(t, r.addr, 2);
    CHECK_EQ_U64(t, r.arg, 10);
    CHECK_EQ_U64(t, r.set_bits, 10);
    CHECK_EQ_U64(t, r.bits, 0x3ff);
    /* Bits past the quantity are not counted. */
    static const uint8_t extra[] = {0x01, 0x0f, 0x00, 0x00, 0x00, 0x03, 0x01, 0xff};
    n = seal(f, extra, sizeof extra);
    CHECK_EQ_I64(t, wire_decode_request(f, n, &r), 1);
    CHECK_EQ_U64(t, r.set_bits, 3);
    CHECK_EQ_U64(t, r.bits, 0x07);
    /* Zero quantity, zero data bytes. */
    static const uint8_t none[] = {0x01, 0x0f, 0x00, 0x00, 0x00, 0x00, 0x00};
    n = seal(f, none, sizeof none);
    CHECK_EQ_I64(t, wire_decode_request(f, n, &r), 1);
    CHECK_EQ_I64(t, r.fn, WIRE_FN_WRITE_COILS);
    CHECK_EQ_U64(t, r.set_bits, 0);
    /* 40 coils: more than 32 bits; the count covers all 40, the mask the first 32. */
    static const uint8_t wide[] = {0x01, 0x0f, 0x00, 0x00, 0x00, 0x28, 0x05, 0x00, 0x00, 0x00, 0x80, 0x01};
    n = seal(f, wide, sizeof wide);
    CHECK_EQ_I64(t, wire_decode_request(f, n, &r), 1);
    CHECK_EQ_I64(t, r.fn, WIRE_FN_WRITE_COILS);
    CHECK_EQ_U64(t, r.set_bits, 2);
    CHECK_EQ_U64(t, r.bits, 0x80000000U); /* bit 31 is kept, bit 32 is only counted */
    /* Nine coils over two bytes: bit 8 is the first bit of the second byte. */
    static const uint8_t nine[] = {0x01, 0x0f, 0x00, 0x00, 0x00, 0x09, 0x02, 0xff, 0x00};
    n = seal(f, nine, sizeof nine);
    CHECK_EQ_I64(t, wire_decode_request(f, n, &r), 1);
    CHECK_EQ_U64(t, r.set_bits, 8);
    CHECK_EQ_U64(t, r.bits, 0xff);
    /* Byte count that disagrees with the quantity or the length: a valid frame, but not a decodable FC0F. */
    static const uint8_t wrongq[] = {0x01, 0x0f, 0x00, 0x00, 0x00, 0x11, 0x02, 0xff, 0xff};
    n = seal(f, wrongq, sizeof wrongq);
    CHECK_EQ_I64(t, wire_decode_request(f, n, &r), 1);
    CHECK_EQ_I64(t, r.fn, WIRE_FN_OTHER);
    static const uint8_t wrongl[] = {0x01, 0x0f, 0x00, 0x00, 0x00, 0x08, 0x01, 0xff, 0xff};
    n = seal(f, wrongl, sizeof wrongl);
    CHECK_EQ_I64(t, wire_decode_request(f, n, &r), 1);
    CHECK_EQ_I64(t, r.fn, WIRE_FN_OTHER);
    static const uint8_t wrongb[] = {0x01, 0x0f, 0x00, 0x00, 0x00, 0x08, 0x02, 0xff};
    n = seal(f, wrongb, sizeof wrongb);
    CHECK_EQ_I64(t, wire_decode_request(f, n, &r), 1);
    CHECK_EQ_I64(t, r.fn, WIRE_FN_OTHER);
}

/* A frame that does not decode leaves every field zero, whatever `out` held. */
static void t_failed_decode_clears_the_output(ctest_t *t) {
    wire_req_t r = {WIRE_FN_OTHER, 9, 9, 9, 9, 9, 9};
    uint8_t bad[sizeof READ_REQ];
    memcpy(bad, READ_REQ, sizeof bad);
    bad[0] ^= 1U;
    CHECK_EQ_I64(t, wire_decode_request(bad, sizeof bad, &r), 0);
    CHECK_EQ_I64(t, r.fn, WIRE_FN_NONE);
    CHECK_EQ_U64(t, r.slave, 0);
    CHECK_EQ_U64(t, r.code, 0);
    CHECK_EQ_U64(t, r.addr, 0);
    CHECK_EQ_U64(t, r.arg, 0);
    CHECK_EQ_U64(t, r.bits, 0);
    CHECK_EQ_U64(t, r.set_bits, 0);
    wire_resp_t p = {WIRE_FN_OTHER, 9, 9, 9};
    uint8_t badr[sizeof READ_RESP_ON];
    memcpy(badr, READ_RESP_ON, sizeof badr);
    badr[0] ^= 1U;
    CHECK_EQ_I64(t, wire_decode_response(badr, sizeof badr, &p), 0);
    CHECK_EQ_I64(t, p.fn, WIRE_FN_NONE);
    CHECK_EQ_U64(t, p.code, 0);
    CHECK_EQ_U64(t, p.nbytes, 0);
    CHECK_EQ_U64(t, p.coils, 0);
    /* The shortest frame there is: slave, function, CRC. */
    static const uint8_t tiny[] = {0x01, 0x08};
    uint8_t f[8];
    size_t n = seal(f, tiny, sizeof tiny);
    CHECK_EQ_U64(t, n, 4);
    CHECK_EQ_I64(t, wire_decode_request(f, n, &r), 1);
    CHECK_EQ_I64(t, r.fn, WIRE_FN_OTHER);
    CHECK_EQ_U64(t, r.code, 8);
    CHECK_EQ_I64(t, wire_decode_response(f, n, &p), 1);
    CHECK_EQ_I64(t, wire_decode_request(f, n - 1U, &r), 0);
}

static void t_response_coils(ctest_t *t) {
    uint8_t f[24];
    wire_resp_t p;
    /* Five data bytes: the byte count is kept, only the first four are read. */
    static const uint8_t five[] = {0x01, 0x01, 0x05, 0x01, 0x02, 0x03, 0x84, 0xff};
    size_t n = seal(f, five, sizeof five);
    CHECK_EQ_I64(t, wire_decode_response(f, n, &p), 1);
    CHECK_EQ_I64(t, p.fn, WIRE_FN_READ_COILS);
    CHECK_EQ_U64(t, p.nbytes, 5);
    CHECK_EQ_U64(t, p.coils, 0x84030201U);
    static const uint8_t one[] = {0x01, 0x01, 0x01, 0xa5};
    n = seal(f, one, sizeof one);
    CHECK_EQ_I64(t, wire_decode_response(f, n, &p), 1);
    CHECK_EQ_U64(t, p.nbytes, 1);
    CHECK_EQ_U64(t, p.coils, 0xa5);
}

CTEST_SUITE("frame", { "crc", t_crc }, { "recorded_requests", t_recorded_requests },
            { "recorded_responses", t_recorded_responses }, { "bad_crc_and_short", t_bad_crc_and_short },
            { "other_functions_and_lengths", t_other_functions_and_lengths }, { "write_coils", t_write_coils },
            { "failed_decode_clears_the_output", t_failed_decode_clears_the_output }, { "response_coils", t_response_coils })
