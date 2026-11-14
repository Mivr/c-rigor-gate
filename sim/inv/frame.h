/* A gate-owned Modbus RTU decoder for the Waveshare relay board (P330 section 1.5, 2.1).
 *
 * It shares nothing with the kiosk's frame code or the board simulator: it is written from docs/lockers/hardware-safety.md
 * and the Modbus RTU framing alone. One call decodes one whole frame (CRC included); it never reads a stream. Pure: no
 * allocation, no IO, no time.
 */
#ifndef SIM_INV_FRAME_H
#define SIM_INV_FRAME_H

#include <stddef.h>
#include <stdint.h>

typedef enum {
    WIRE_FN_NONE = 0,     /* not decodable: too short, or the CRC is wrong */
    WIRE_FN_READ_COILS,   /* FC01 */
    WIRE_FN_READ_HOLDING, /* FC03 */
    WIRE_FN_WRITE_COIL,   /* FC05 */
    WIRE_FN_WRITE_COILS,  /* FC0F */
    WIRE_FN_OTHER         /* a valid frame that is none of the above, or one of them with the wrong length */
} wire_fn_t;

typedef struct {
    wire_fn_t fn;
    uint8_t slave;
    uint8_t code;      /* the function code byte as sent */
    uint16_t addr;     /* start address (FC01, FC03, FC0F) or coil address (FC05) */
    uint16_t arg;      /* quantity (FC01, FC03, FC0F) or value (FC05) */
    uint32_t bits;     /* FC0F: the first 32 data bits, bit k is coil `addr + k` */
    uint32_t set_bits; /* FC0F: how many of the `arg` data bits are 1 */
} wire_req_t;

typedef struct {
    wire_fn_t fn;    /* WIRE_FN_READ_COILS, WIRE_FN_READ_HOLDING, WIRE_FN_WRITE_COIL (echo) or WIRE_FN_OTHER (an exception) */
    uint8_t code;    /* the function code byte as sent (bit 7 set: an exception) */
    uint8_t nbytes;  /* FC01: the byte count field */
    uint32_t coils;  /* FC01: the first 32 coil bits, coil `addr` is bit 0 */
} wire_resp_t;

/* The Modbus CRC-16 of `len` bytes (polynomial 0xA001, start 0xFFFF). */
uint16_t wire_crc16(const uint8_t *bytes, size_t len);

/* Decode a request frame. Returns 1 and fills `out` when the frame is at least 4 bytes with a correct CRC (the function may
 * still be WIRE_FN_OTHER); returns 0 and sets `out->fn = WIRE_FN_NONE` otherwise. NULL arguments return 0. */
int wire_decode_request(const uint8_t *bytes, size_t len, wire_req_t *out);
/* The same for a response frame. A response whose length does not fit its function code decodes as WIRE_FN_OTHER. */
int wire_decode_response(const uint8_t *bytes, size_t len, wire_resp_t *out);

#endif
