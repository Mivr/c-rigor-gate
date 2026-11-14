#include "sim/inv/frame.h"

uint16_t wire_crc16(const uint8_t *bytes, size_t len) {
    uint16_t crc = 0xFFFFU;
    for (size_t i = 0; i < len; i++) {
        crc = (uint16_t)(crc ^ bytes[i]);
        for (unsigned bit = 0; bit < 8U; bit++) {
            crc = (crc & 1U) != 0U ? (uint16_t)((crc >> 1) ^ 0xA001U) : (uint16_t)(crc >> 1);
        }
    }
    return crc;
}

static uint16_t be16(const uint8_t *p) {
    return (uint16_t)(((unsigned)p[0] << 8) | p[1]);
}

/* A frame is `len` bytes; the last two are the CRC, low byte first. */
static int crc_ok(const uint8_t *bytes, size_t len) {
    if (len < 4U) {
        return 0;
    }
    uint16_t crc = wire_crc16(bytes, len - 2U);
    return bytes[len - 2U] == (uint8_t)(crc & 0xFFU) && bytes[len - 1U] == (uint8_t)(crc >> 8);
}

static uint32_t count_set(const uint8_t *data, uint16_t nbits) {
    uint32_t set = 0;
    for (uint32_t i = 0; i < nbits; i++) {
        set += (uint32_t)((data[i / 8U] >> (i % 8U)) & 1U);
    }
    return set;
}

static wire_fn_t request_fn(uint8_t code, size_t len) {
    if ((code == 0x01U || code == 0x03U || code == 0x05U) && len == 8U) {
        return code == 0x01U ? WIRE_FN_READ_COILS : (code == 0x03U ? WIRE_FN_READ_HOLDING : WIRE_FN_WRITE_COIL);
    }
    return WIRE_FN_OTHER;
}

int wire_decode_request(const uint8_t *bytes, size_t len, wire_req_t *out) {
    if (bytes == NULL || out == NULL) {
        return 0;
    }
    *out = (wire_req_t){WIRE_FN_NONE, 0, 0, 0, 0, 0, 0};
    if (!crc_ok(bytes, len)) {
        return 0;
    }
    out->fn = request_fn(bytes[1], len);
    out->slave = bytes[0];
    out->code = bytes[1];
    if (out->fn != WIRE_FN_OTHER) {
        out->addr = be16(bytes + 2);
        out->arg = be16(bytes + 4);
        return 1;
    }
    /* FC0F: slave, code, addr (2), quantity (2), byte count, data, CRC (2). */
    if (bytes[1] == 0x0FU && len >= 9U && (size_t)bytes[6] == len - 9U && (unsigned)bytes[6] == ((unsigned)be16(bytes + 4) + 7U) / 8U) {
        out->fn = WIRE_FN_WRITE_COILS;
        out->addr = be16(bytes + 2);
        out->arg = be16(bytes + 4);
        out->set_bits = count_set(bytes + 7, out->arg);
        for (uint32_t i = 0; i < out->arg && i < 32U; i++) {
            out->bits |= (uint32_t)((bytes[7U + i / 8U] >> (i % 8U)) & 1U) << i;
        }
    }
    return 1;
}

static wire_fn_t response_fn(const uint8_t *bytes, size_t len) {
    if (bytes[1] == 0x01U && len == (size_t)bytes[2] + 5U) {
        return WIRE_FN_READ_COILS;
    }
    if (bytes[1] == 0x03U && len == (size_t)bytes[2] + 5U) {
        return WIRE_FN_READ_HOLDING;
    }
    if (bytes[1] == 0x05U && len == 8U) {
        return WIRE_FN_WRITE_COIL;
    }
    return WIRE_FN_OTHER;
}

int wire_decode_response(const uint8_t *bytes, size_t len, wire_resp_t *out) {
    if (bytes == NULL || out == NULL) {
        return 0;
    }
    *out = (wire_resp_t){WIRE_FN_NONE, 0, 0, 0};
    if (!crc_ok(bytes, len)) {
        return 0;
    }
    out->fn = response_fn(bytes, len);
    out->code = bytes[1];
    if (out->fn == WIRE_FN_READ_COILS) {
        out->nbytes = bytes[2];
        for (uint32_t i = 0; i < bytes[2] && i < 4U; i++) {
            out->coils |= (uint32_t)bytes[3U + i] << (8U * i);
        }
    }
    return 1;
}
