/* A scanner for the audit file of a product (P330 section 2.2, I9 and I10): JSON lines, each carrying a `"seq":N` key, where
 * N rises by exactly one from line to line. It reads bytes, nothing else: the world hands the engine the durable image.
 *
 * A line is `{` ... `}` and ends in a newline. The first line may carry any seq (old files are rotated away); every later line
 * must carry the one before it plus one. After a power cut the file may end in a torn line (no newline): `allow_torn` accepts
 * that final partial line and ignores it, because a prefix of a valid file is valid. Anywhere else a partial line is a format error.
 */
#ifndef SIM_INV_AUDIT_H
#define SIM_INV_AUDIT_H

#include <stdint.h>

typedef enum {
    AUDIT_OK = 0,
    AUDIT_FORMAT, /* a line that is not `{...}`, has no `"seq":` with 1 to 18 digits after it, or an unterminated line when torn is not allowed */
    AUDIT_GAP     /* a seq that is not the previous one plus one */
} audit_result_t;

typedef struct {
    uint64_t first_seq; /* seq of the first complete line (0 when there is none) */
    uint64_t last_seq;  /* seq of the last complete line scanned (0 when there is none) */
    uint32_t lines;     /* complete lines accepted before the result */
    uint32_t torn;      /* 1 when the file ends in a partial line that was accepted as torn */
} audit_scan_t;

/* Scan `len` bytes. `out` is always filled (up to the line that failed). NULL `out`, or NULL `bytes` with len > 0, is AUDIT_FORMAT. */
audit_result_t audit_scan(const uint8_t *bytes, uint32_t len, int allow_torn, audit_scan_t *out);

#endif
