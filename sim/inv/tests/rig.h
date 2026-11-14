/* Test kit of the wire-invariant tests: builds frames with a CRC and feeds them to an engine as `fr` records. */
#ifndef SIM_INV_TESTS_RIG_H
#define SIM_INV_TESTS_RIG_H

#include "ctest/ctest.h"
#include "sim/inv/wire.h"

#define RIG_REPLY_MS 5U /* the board's answer comes this long after the request */

typedef struct {
    wire_t w;
    ctest_t *t;
} rig_t;

void rig_init(rig_t *r, ctest_t *t);
/* Feed `n` bytes of one frame (direction 0 request, 1 response) as is; the feed must return 0. */
void rig_raw(rig_t *r, uint64_t t_ms, unsigned dir, const uint8_t *bytes, size_t n);
/* The same, with the CRC appended to `body`. */
void rig_frame(rig_t *r, uint64_t t_ms, unsigned dir, const uint8_t *body, size_t n);
/* A coil read of `qty` coils from `addr`; the answer (at t_ms + RIG_REPLY_MS) carries `bits`, bit k = coil addr + k. */
void rig_read_part(rig_t *r, uint64_t t_ms, uint16_t addr, uint16_t qty, uint32_t bits);
/* A read of all 30 coils whose answer comes late: the request at `t_req`, the answer at `t_resp`. */
void rig_read_late(rig_t *r, uint64_t t_req, uint64_t t_resp, uint32_t bits);
/* A read of all 30 coils. */
void rig_read(rig_t *r, uint64_t t_ms, uint32_t bits);
/* FC05 with any address and value, as a request. */
void rig_write(rig_t *r, uint64_t t_ms, uint16_t addr, uint16_t value);
void rig_flash(rig_t *r, uint64_t t_ms, uint32_t channel, uint16_t units);
void rig_alloff(rig_t *r, uint64_t t_ms);
/* A healthy flight, as the kiosk makes it: a fresh all-off read at t0, the flash-on frames at t0+10 (and t0+20 when
 * `second` is not negative), polls every 50 ms showing the coils on until 15 ms before the nominal end, then the first
 * all-off read. Returns the time of that verify answer. */
uint64_t rig_flight(rig_t *r, uint64_t t0, int first, int second, uint16_t units);

/* The invariant of the first finding with this rule, or 0 when there is none. */
int rig_inv_of(const rig_t *r, wire_rule_t rule);
int rig_rule(const rig_t *r, wire_rule_t rule);
/* Number of findings with this rule. */
uint32_t rig_rule_count(const rig_t *r, wire_rule_t rule);

#endif
