/* Wire invariants I3 (energised lockers), I4 and I5 (read-off, pulse, verify-off, gap) over hand-built flights. */
#include "sim/inv/tests/rig.h"

#define BIT(inv) (1U << (unsigned)(inv))

static rig_t R;

static void t_healthy_flights_are_clean(ctest_t *t) {
    for (uint16_t units = 1; units <= 8U; units++) {
        rig_init(&R, t);
        uint64_t v = rig_flight(&R, 0, 12, 0, units);
        CHECK(t, v > 0U);
        CHECK_EQ_I64(t, wire_finish(&R.w, v + 5000U), 0);
        CHECK_EQ_U64(t, wire_flight_count(&R.w), 1);
        CHECK(t, wire_record_count(&R.w) > 5U);
        CHECK_EQ_U64(t, wire_finding_count(&R.w), 0);
        CHECK_EQ_U64(t, wire_inv_mask(&R.w), 0);
    }
    rig_init(&R, t);
    uint64_t v = rig_flight(&R, 0, 12, -1, 5); /* a single relay is one flight too */
    CHECK_EQ_U64(t, wire_inv_mask(&R.w), 0);
    CHECK(t, v > 0U);
}

/* The gap is counted from the answer of the verified-off read to the next flash-on: 299 ms is a violation, 300 is not. */
static void t_gap_boundary(ctest_t *t) {
    for (uint64_t gap = 295; gap <= 305U; gap++) {
        rig_init(&R, t);
        uint64_t v = rig_flight(&R, 0, 12, 0, 5);
        CHECK_EQ_U64(t, wire_inv_mask(&R.w), 0);
        rig_flight(&R, v + gap - 10U, 13, 1, 5); /* its flash-on is at v + gap */
        CHECK_EQ_I64(t, wire_has_rule(&R.w, WIRE_R_GAP), gap < 300U);
        CHECK_EQ_U64(t, wire_inv_mask(&R.w), gap < 300U ? BIT(WIRE_I5) : 0U);
        CHECK_EQ_U64(t, rig_rule_count(&R, WIRE_R_GAP), gap < 300U ? 1U : 0U);
        CHECK_EQ_U64(t, wire_flight_count(&R.w), 2);
        CHECK_EQ_I64(t, rig_inv_of(&R, WIRE_R_GAP), gap < 300U ? WIRE_I5 : 0);
    }
    rig_init(&R, t);
    uint64_t v = rig_flight(&R, 0, 12, 0, 5);
    rig_flight(&R, v + 40U, 13, 1, 5);
    CHECK(t, rig_rule(&R, WIRE_R_GAP));
}

static void t_read_before_each_flight(ctest_t *t) {
    /* No read at all. */
    rig_init(&R, t);
    rig_flash(&R, 10, 12, 5);
    CHECK(t, rig_rule(&R, WIRE_R_NO_PREREAD));
    CHECK_EQ_U64(t, wire_inv_mask(&R.w), BIT(WIRE_I5));
    CHECK_EQ_I64(t, rig_inv_of(&R, WIRE_R_NO_PREREAD), WIRE_I5);
    /* A read that shows a coil on. */
    rig_init(&R, t);
    rig_read(&R, 0, 1U << 7);
    rig_flash(&R, 10, 12, 5);
    CHECK(t, rig_rule(&R, WIRE_R_NO_PREREAD));
    /* A read of 29 coils is not a read of all of them. */
    rig_init(&R, t);
    rig_read_part(&R, 0, 0, 29, 0);
    rig_flash(&R, 10, 12, 5);
    CHECK(t, rig_rule(&R, WIRE_R_NO_PREREAD));
    rig_init(&R, t);
    rig_read_part(&R, 0, 1, 29, 0);
    rig_flash(&R, 10, 12, 5);
    CHECK(t, rig_rule(&R, WIRE_R_NO_PREREAD));
    /* A read of everything, all off. */
    rig_init(&R, t);
    rig_read(&R, 0, 0);
    rig_flash(&R, 10, 12, 5);
    CHECK_EQ_U64(t, wire_inv_mask(&R.w), 0);
    /* A coil on, an all-off, a fresh read: fine. */
    rig_init(&R, t);
    rig_read(&R, 0, 1U << 7);
    rig_alloff(&R, 10);
    rig_read(&R, 20, 0);
    rig_flash(&R, 30, 12, 5);
    CHECK_EQ_U64(t, wire_inv_mask(&R.w), 0);
    /* The verify read of the last flight is not the read before the next: it needs a fresh one. */
    for (int fresh = 0; fresh <= 1; fresh++) {
        rig_init(&R, t);
        uint64_t v = rig_flight(&R, 0, 12, 0, 5);
        if (fresh != 0) {
            rig_read(&R, v + 50U, 0);
        }
        rig_flash(&R, v + 400U, 13, 5);
        CHECK_EQ_I64(t, wire_has_rule(&R.w, WIRE_R_NO_PREREAD), fresh == 0);
        CHECK_EQ_I64(t, wire_has_rule(&R.w, WIRE_R_GAP), 0);
    }
    /* The second flash of a flight needs no read of its own. */
    rig_init(&R, t);
    rig_read(&R, 0, 0);
    rig_flash(&R, 10, 12, 5);
    rig_flash(&R, 20, 0, 5);
    CHECK_EQ_U64(t, wire_inv_mask(&R.w), 0);
}

static void t_flash_before_verify(ctest_t *t) {
    rig_init(&R, t);
    rig_read(&R, 0, 0);
    rig_flash(&R, 10, 12, 5);
    rig_flash(&R, 20, 0, 5);
    rig_flash(&R, 40, 5, 5);
    CHECK(t, rig_rule(&R, WIRE_R_BEFORE_VERIFY));
    CHECK(t, rig_rule(&R, WIRE_R_TWO_ENERGISED)); /* three coils are on */
    CHECK(t, wire_has_inv(&R.w, WIRE_I3));
    CHECK(t, wire_has_inv(&R.w, WIRE_I5));
    CHECK_EQ_U64(t, rig_rule_count(&R, WIRE_R_BEFORE_VERIFY), 1);
    CHECK_EQ_U64(t, rig_rule_count(&R, WIRE_R_NO_PREREAD), 1); /* the third flash starts a flight with no read of its own */
    CHECK_EQ_I64(t, rig_inv_of(&R, WIRE_R_BEFORE_VERIFY), WIRE_I5);
    CHECK_EQ_I64(t, rig_inv_of(&R, WIRE_R_NO_PREREAD), WIRE_I5);
    CHECK_EQ_I64(t, rig_inv_of(&R, WIRE_R_TWO_ENERGISED), WIRE_I3);
    CHECK_EQ_U64(t, wire_flight_count(&R.w), 2);
    /* A pair is not a violation by itself. */
    rig_init(&R, t);
    rig_read(&R, 0, 0);
    rig_flash(&R, 10, 12, 5);
    rig_flash(&R, 20, 0, 5);
    CHECK_EQ_U64(t, wire_inv_mask(&R.w), 0);
    /* Once verified, the next flash is a new flight, not a violation of this rule. */
    rig_init(&R, t);
    uint64_t v = rig_flight(&R, 0, 12, 0, 5);
    rig_flight(&R, v + 300U, 13, 1, 5);
    CHECK(t, !rig_rule(&R, WIRE_R_BEFORE_VERIFY));
    CHECK_EQ_U64(t, wire_inv_mask(&R.w), 0);
}

/* A coil is on until its earliest off time (the frame + units * 100 - 30 ms); a flash on another flight then counts. */
static void t_energised_window(ctest_t *t) {
    for (uint64_t at = 470; at <= 495U; at += 1U) {
        rig_init(&R, t);
        rig_read(&R, 0, 0);
        rig_flash(&R, 10, 12, 5); /* off between 480 and 510 */
        rig_flash(&R, 20, 0, 5);  /* off between 490 and 520 */
        rig_flash(&R, at, 5, 5);  /* another flight (the pair is complete) */
        /* Lit at `at`: coil 12 while at < 480, coil 0 while at < 490, and coil 5 itself. Two coils of two flights count. */
        int lit_old = (at < 480U ? 1 : 0) + (at < 490U ? 1 : 0);
        CHECK_EQ_I64(t, wire_has_rule(&R.w, WIRE_R_TWO_ENERGISED), lit_old > 0);
    }
}

static void t_two_flights_at_once(ctest_t *t) {
    /* A coil that was turned on without a flash, then a flight. */
    rig_init(&R, t);
    rig_write(&R, 1, 3, 0xff00);
    rig_read(&R, 2, 1U << 3);
    CHECK(t, !rig_rule(&R, WIRE_R_TWO_ENERGISED));
    rig_flash(&R, 10, 12, 5);
    CHECK(t, rig_rule(&R, WIRE_R_TWO_ENERGISED));
    CHECK(t, wire_has_inv(&R.w, WIRE_I3));
    /* The same coil of the same flight twice is one coil. */
    rig_init(&R, t);
    rig_read(&R, 0, 0);
    rig_flash(&R, 10, 12, 5);
    rig_flash(&R, 20, 12, 5);
    CHECK_EQ_U64(t, wire_inv_mask(&R.w), 0);
    /* Reads that keep showing a third coil raise it once for the flight. */
    rig_init(&R, t);
    rig_read(&R, 0, 0);
    rig_flash(&R, 10, 12, 5);
    rig_flash(&R, 20, 0, 5);
    uint32_t three = (1U << 12) | 1U | (1U << 5);
    rig_read(&R, 40, three);
    rig_read(&R, 90, three);
    rig_read(&R, 140, three);
    CHECK_EQ_U64(t, rig_rule_count(&R, WIRE_R_TWO_ENERGISED), 1);
    /* A fast board: the read shows everything off before the nominal end. It is the verify read, and it is fine. */
    rig_init(&R, t);
    rig_read(&R, 0, 0);
    rig_flash(&R, 10, 12, 5);
    rig_flash(&R, 20, 0, 5);
    rig_read(&R, 100, 0);
    rig_read(&R, 150, 0);
    rig_flight(&R, 500, 13, 1, 5);
    CHECK_EQ_U64(t, wire_inv_mask(&R.w), 0);
}

/* An all-off clears the model: the coils it turned off are not counted against the next flash. */
static void t_all_off_clears_the_model(ctest_t *t) {
    for (int sent = 0; sent <= 1; sent++) {
        rig_init(&R, t);
        rig_read(&R, 0, 0);
        rig_flash(&R, 10, 12, 8);
        rig_flash(&R, 20, 0, 8);
        if (sent != 0) {
            rig_alloff(&R, 100);
        }
        rig_flash(&R, 120, 5, 1); /* a third coil: only with the pair still on is it a second locker */
        CHECK_EQ_I64(t, wire_has_rule(&R.w, WIRE_R_TWO_ENERGISED), sent == 0);
    }
}

/* A coil that is flashed again while it may still be on keeps counting from its first flash. */
static void t_burn_chain_runs_to_the_latest_off_time(ctest_t *t) {
    for (uint64_t end = 2589; end <= 2591U; end++) {
        rig_init(&R, t);
        rig_read(&R, 0, 0);
        rig_flash(&R, 1000, 12, 8);
        rig_flash(&R, 1790, 12, 8); /* the coil may still be on: the chain goes on, to 2590 */
        CHECK_EQ_I64(t, wire_finish(&R.w, end), 0);
        CHECK_EQ_I64(t, wire_has_rule(&R.w, WIRE_R_BURN), end <= 2590U);
        CHECK_EQ_I64(t, rig_inv_of(&R, WIRE_R_BURN), end <= 2590U ? WIRE_I6 : 0);
    }
}

static void t_verify_deadline(ctest_t *t) {
    /* First flash at 1000: the verified-off read is due by 1000 + 900 + 150 = 2050. */
    for (uint64_t answer = 2048; answer <= 2052U; answer++) {
        rig_init(&R, t);
        rig_read(&R, 990, 0);
        rig_flash(&R, 1000, 12, 5);
        rig_read_late(&R, answer - 5U, answer, 0);
        CHECK_EQ_I64(t, wire_has_rule(&R.w, WIRE_R_VERIFY_LATE), answer > 2050U);
        CHECK_EQ_I64(t, rig_inv_of(&R, WIRE_R_VERIFY_LATE), answer > 2050U ? WIRE_I5 : 0);
    }
    /* No read at all: only the end of the run notices. */
    for (uint64_t end = 2049; end <= 2051U; end++) {
        rig_init(&R, t);
        rig_read(&R, 990, 0);
        rig_flash(&R, 1000, 12, 5);
        rig_flash(&R, 1010, 0, 5);
        CHECK_EQ_I64(t, wire_finish(&R.w, end), 0);
        CHECK_EQ_I64(t, wire_has_rule(&R.w, WIRE_R_VERIFY_LATE), end > 2050U);
        CHECK_EQ_U64(t, wire_inv_mask(&R.w), end > 2050U ? BIT(WIRE_I5) : 0U);
    }
    /* A verified flight owes nothing later. */
    rig_init(&R, t);
    uint64_t v = rig_flight(&R, 0, 12, 0, 5);
    CHECK_EQ_I64(t, wire_finish(&R.w, v + 100000U), 0);
    CHECK_EQ_U64(t, wire_inv_mask(&R.w), 0);
    /* A coil still on at the read is no verification. */
    rig_init(&R, t);
    rig_read(&R, 990, 0);
    rig_flash(&R, 1000, 12, 5);
    rig_read(&R, 1100, 1U << 12);
    CHECK_EQ_I64(t, wire_finish(&R.w, 2051), 0);
    CHECK(t, rig_rule(&R, WIRE_R_VERIFY_LATE));
}

CTEST_SUITE("flight", { "healthy_flights_are_clean", t_healthy_flights_are_clean }, { "gap_boundary", t_gap_boundary },
            { "read_before_each_flight", t_read_before_each_flight }, { "flash_before_verify", t_flash_before_verify },
            { "energised_window", t_energised_window }, { "two_flights_at_once", t_two_flights_at_once },
            { "all_off_clears_the_model", t_all_off_clears_the_model },
            { "burn_chain_runs_to_the_latest_off_time", t_burn_chain_runs_to_the_latest_off_time },
            { "verify_deadline", t_verify_deadline })
