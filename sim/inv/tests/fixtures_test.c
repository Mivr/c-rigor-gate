/* The positive control: the recordings of the real board and of the club-apps simulator, converted by
 * tools/sim/fixture_to_fr.py, must pass I3 to I6b; each is also broken in ways that must be seen. */
#include "ctest/ctest.h"
#include "sim/inv/frame.h"
#include "sim/inv/tests/fixtures_data.h"
#include "sim/inv/wire.h"

#define BIT(inv) (1U << (unsigned)(inv))

static wire_t W;
static fx_rec_t copy[400];

static void feed_all(ctest_t *t, const fx_rec_t *recs, size_t n) {
    wire_init(&W);
    uint64_t last = 0;
    for (size_t i = 0; i < n; i++) {
        sim_rec_t rec = {{'f', 'r'}, recs[i].t_ms, recs[i].dir, 0, recs[i].bytes, recs[i].len};
        CHECK_EQ_I64(t, wire_feed(&W, &rec), 0);
        last = recs[i].t_ms;
    }
    CHECK_EQ_I64(t, wire_finish(&W, last), 0);
}

static void check_flights_pass(ctest_t *t, const fx_trace_t *segs, size_t nsegs) {
    for (size_t i = 0; i < nsegs; i++) {
        CHECK(t, segs[i].n > 6U);
        feed_all(t, segs[i].recs, segs[i].n);
        CHECK_EQ_U64(t, wire_finding_count(&W), 0);
        CHECK_EQ_U64(t, wire_inv_mask(&W), 0);
        CHECK_EQ_I64(t, wire_crosscheck(&W, 0), WIRE_XC_AGREE);
    }
}

static void t_real_board_passes(ctest_t *t) {
    CHECK_EQ_U64(t, FX_REAL_NSEGS, 3);
    check_flights_pass(t, FX_REAL_SEGS, FX_REAL_NSEGS);
}

static void t_simulator_passes(ctest_t *t) {
    CHECK_EQ_U64(t, FX_SIM_NSEGS, 3);
    check_flights_pass(t, FX_SIM_SEGS, FX_SIM_NSEGS);
}

/* The script runs its flights 10 ms apart and reuses each verify read as the read before the next flash. The kiosk must
 * not: the uncut recordings fail I5, and only I5, so the cut above is the reason for passing, not a blind spot. */
static void t_uncut_recordings_fail_i5(ctest_t *t) {
    const fx_trace_t *whole[2] = {&FX_REAL_WHOLE, &FX_SIM_WHOLE};
    for (size_t i = 0; i < 2; i++) {
        feed_all(t, whole[i]->recs, whole[i]->n);
        CHECK_EQ_U64(t, wire_inv_mask(&W), BIT(WIRE_I5));
        CHECK(t, wire_has_rule(&W, WIRE_R_GAP));
        CHECK(t, wire_has_rule(&W, WIRE_R_NO_PREREAD));
        CHECK(t, !wire_has_rule(&W, WIRE_R_BEFORE_VERIFY));
        CHECK(t, !wire_has_rule(&W, WIRE_R_VERIFY_LATE));
    }
}

static void load(const fx_trace_t *seg) {
    for (size_t i = 0; i < seg->n && i < sizeof copy / sizeof copy[0]; i++) {
        copy[i] = seg->recs[i];
    }
}

/* Rewrite the CRC of a recorded frame after a byte was changed. */
static void reseal(fx_rec_t *rec) {
    uint16_t crc = wire_crc16(rec->bytes, (size_t)rec->len - 2U);
    rec->bytes[rec->len - 2U] = (uint8_t)(crc & 0xffU);
    rec->bytes[rec->len - 1U] = (uint8_t)(crc >> 8);
}

static size_t first_flash(const fx_trace_t *seg) {
    for (size_t i = 0; i < seg->n; i++) {
        if (copy[i].dir == 0U && copy[i].bytes[1] == 5U) {
            return i;
        }
    }
    return seg->n;
}

/* The same recording with one thing wrong must fail with the right invariant. */
static void t_broken_recordings_fail(ctest_t *t) {
    const fx_trace_t *seg = &FX_REAL_SEGS[0];
    /* 9 units instead of 5. */
    load(seg);
    size_t f = first_flash(seg);
    CHECK(t, f < seg->n);
    copy[f].bytes[5] = 9;
    reseal(&copy[f]);
    feed_all(t, copy, seg->n);
    CHECK_EQ_U64(t, wire_inv_mask(&W), BIT(WIRE_I4) | BIT(WIRE_I6B));
    /* A plain ON frame (value 0xff00) in place of the flash. */
    load(seg);
    copy[f].bytes[2] = 0x00;
    copy[f].bytes[3] = 0x0c;
    copy[f].bytes[4] = 0xff;
    copy[f].bytes[5] = 0x00;
    reseal(&copy[f]);
    feed_all(t, copy, seg->n);
    CHECK(t, wire_has_inv(&W, WIRE_I3));
    CHECK(t, wire_has_inv(&W, WIRE_I6B));
    /* A bad CRC. */
    load(seg);
    copy[f].bytes[7] ^= 0x01U;
    feed_all(t, copy, seg->n);
    CHECK(t, wire_has_inv(&W, WIRE_I6B));
    /* The verified-off read comes too late: pushed to 2000 ms after a flash at 20 ms. */
    load(seg);
    copy[seg->n - 2U].t_ms = 2000;
    copy[seg->n - 1U].t_ms = 2005;
    feed_all(t, copy, seg->n);
    CHECK_EQ_U64(t, wire_inv_mask(&W), BIT(WIRE_I5));
    CHECK(t, wire_has_rule(&W, WIRE_R_VERIFY_LATE));
    /* The board never lets go: the last read still shows coil 12 on, at 1500 ms (the pair of the script, 5 units). */
    load(seg);
    copy[seg->n - 1U] = seg->recs[seg->n - 3U];
    copy[seg->n - 1U].t_ms = 1500;
    copy[seg->n - 2U].t_ms = 1495;
    feed_all(t, copy, seg->n);
    CHECK(t, wire_has_inv(&W, WIRE_I6));
}

CTEST_SUITE("fixtures", { "real_board_passes", t_real_board_passes }, { "simulator_passes", t_simulator_passes },
            { "uncut_recordings_fail_i5", t_uncut_recordings_fail_i5 }, { "broken_recordings_fail", t_broken_recordings_fail })
