/* Wire invariant I6: the watchdog's all-off by first flash + 900 ms, and no coil on for 1000 ms. */
#include "sim/inv/tests/rig.h"

#define COIL12 (1U << 12)
#define T_F 1000U /* the first flash-on of every case */

static rig_t R;

/* A fresh engine with all coils read off and a flash-on of coil 12 at T_F. */
static void arm(ctest_t *t, uint16_t units) {
    rig_init(&R, t);
    rig_read(&R, T_F - 10U, 0);
    rig_flash(&R, T_F, 12, units);
}

/* The deadline of a pulse: min(units * 100 + 150, 900) ms after the flash. A read showing the coil on one ms before it
 * owes nothing; one at the deadline owes an all-off by T_F + 900. */
static void t_deadline_follows_the_pulse(ctest_t *t) {
    static const struct {
        uint16_t units;
        uint64_t due;
    } cases[] = {{1, 250}, {2, 350}, {5, 650}, {6, 750}, {7, 850}, {8, 900}};
    for (size_t i = 0; i < sizeof cases / sizeof cases[0]; i++) {
        for (int at_deadline = 0; at_deadline <= 1; at_deadline++) {
            arm(t, cases[i].units);
            uint64_t answer = T_F + cases[i].due - (at_deadline != 0 ? 0U : 1U);
            rig_read_late(&R, answer - 5U, answer, COIL12);
            CHECK_EQ_I64(t, wire_finish(&R.w, T_F + 900U), 0);
            CHECK(t, !rig_rule(&R, WIRE_R_WATCHDOG)); /* the all-off is not yet late */
            CHECK_EQ_I64(t, wire_finish(&R.w, T_F + 901U), 0);
            CHECK_EQ_I64(t, wire_has_rule(&R.w, WIRE_R_WATCHDOG), at_deadline);
        }
    }
}

static void t_all_off_boundary(ctest_t *t) {
    for (uint64_t sent = 895; sent <= 905U; sent++) {
        arm(t, 5);
        rig_read(&R, T_F + 645U, COIL12); /* answer at 650: past the 650 ms deadline */
        rig_alloff(&R, T_F + sent);
        CHECK_EQ_I64(t, wire_has_rule(&R.w, WIRE_R_WATCHDOG), sent > 900U); /* noticed at the all-off itself */
        CHECK_EQ_I64(t, wire_finish(&R.w, T_F + sent + 1U), 0);
        CHECK_EQ_I64(t, wire_has_rule(&R.w, WIRE_R_WATCHDOG), sent > 900U);
        CHECK_EQ_I64(t, rig_inv_of(&R, WIRE_R_WATCHDOG), sent > 900U ? WIRE_I6 : 0);
        CHECK(t, !wire_has_inv(&R.w, WIRE_I6B));
        CHECK_EQ_U64(t, wire_inv_mask(&R.w) & ~(1U << (unsigned)WIRE_I5), sent > 900U ? 1U << (unsigned)WIRE_I6 : 0U);
    }
}

static void t_all_off_before_the_read(ctest_t *t) {
    /* An all-off in time, then the read that shows the coil on. */
    arm(t, 5);
    rig_alloff(&R, T_F + 640U);
    rig_read(&R, T_F + 700U, COIL12);
    CHECK_EQ_I64(t, wire_finish(&R.w, T_F + 2000U), 0);
    CHECK(t, !rig_rule(&R, WIRE_R_WATCHDOG));
    /* An all-off already past the cap, then the read: the all-off was late. */
    arm(t, 5);
    rig_alloff(&R, T_F + 901U);
    CHECK(t, !rig_rule(&R, WIRE_R_WATCHDOG));
    rig_read(&R, T_F + 950U, COIL12);
    CHECK(t, rig_rule(&R, WIRE_R_WATCHDOG));
    /* The first all-off counts, not a later one. */
    arm(t, 5);
    rig_alloff(&R, T_F + 640U);
    rig_alloff(&R, T_F + 950U);
    rig_read(&R, T_F + 960U, COIL12);
    CHECK(t, !rig_rule(&R, WIRE_R_WATCHDOG));
    CHECK_EQ_I64(t, wire_finish(&R.w, T_F + 3000U), 0);
    CHECK(t, !rig_rule(&R, WIRE_R_WATCHDOG));
}

static void t_late_reply(ctest_t *t) {
    /* The read asked at 640, answered at 901 with the coil still on: the all-off could not be sent in time. */
    for (uint64_t answer = 898; answer <= 902U; answer++) {
        arm(t, 5);
        rig_read_late(&R, T_F + 640U, T_F + answer, COIL12);
        CHECK_EQ_I64(t, wire_has_rule(&R.w, WIRE_R_WATCHDOG), answer > 900U);
    }
}

static void t_nothing_due(ctest_t *t) {
    /* The coil is off when read, however late. */
    arm(t, 5);
    rig_read(&R, T_F + 700U, 0);
    CHECK_EQ_I64(t, wire_finish(&R.w, T_F + 5000U), 0);
    CHECK(t, !rig_rule(&R, WIRE_R_WATCHDOG));
    CHECK(t, !rig_rule(&R, WIRE_R_BURN));
    /* A read of coils that are not on, past the deadline. */
    arm(t, 5);
    rig_read(&R, T_F + 700U, 1U << 3);
    rig_read_part(&R, T_F + 800U, 0, 3, 0);
}

static void t_once_per_flight_and_after_verify(ctest_t *t) {
    arm(t, 5);
    rig_read(&R, T_F + 645U, COIL12);
    for (uint64_t at = 950; at < 1700U; at += 150U) {
        rig_read(&R, T_F + at, COIL12);
    }
    CHECK_EQ_U64(t, rig_rule_count(&R, WIRE_R_WATCHDOG), 1);
    /* The obligation outlives the verified-off read: the coil went off by itself at 700, but a read had shown it on. */
    for (int sent = 0; sent <= 1; sent++) {
        arm(t, 5);
        rig_read(&R, T_F + 645U, COIL12);
        rig_read(&R, T_F + 695U, 0);
        if (sent != 0) {
            rig_alloff(&R, T_F + 800U);
        }
        CHECK_EQ_I64(t, wire_finish(&R.w, T_F + 901U), 0);
        CHECK_EQ_I64(t, wire_has_rule(&R.w, WIRE_R_WATCHDOG), sent == 0);
    }
    /* A new flight starts with no obligation. */
    arm(t, 5);
    rig_read(&R, T_F + 645U, COIL12);
    rig_alloff(&R, T_F + 660U);
    rig_read(&R, T_F + 700U, 0);
    rig_flight(&R, T_F + 1500U, 13, 1, 5);
    CHECK_EQ_I64(t, wire_finish(&R.w, T_F + 20000U), 0);
    CHECK(t, !rig_rule(&R, WIRE_R_WATCHDOG));
    CHECK(t, !rig_rule(&R, WIRE_R_BURN));
}

/* Independently of the watchdog: a coil on in the model for 1000 ms is a burn. */
static void t_burn(ctest_t *t) {
    /* Stuck on, all-off ignored: the read keeps showing it. */
    for (uint64_t end = 1998; end <= 2001U; end++) {
        arm(t, 5);
        rig_read(&R, T_F + 700U, COIL12);
        rig_alloff(&R, T_F + 710U);
        rig_read(&R, T_F + 750U, COIL12);
        CHECK_EQ_I64(t, wire_finish(&R.w, end), 0);
        CHECK_EQ_I64(t, wire_has_rule(&R.w, WIRE_R_BURN), end >= 2000U);
    }
    /* The all-off worked: nothing shows the coil on again, so the device obeyed. */
    arm(t, 5);
    rig_read(&R, T_F + 700U, COIL12);
    rig_alloff(&R, T_F + 710U);
    CHECK_EQ_I64(t, wire_finish(&R.w, T_F + 9000U), 0);
    CHECK(t, !rig_rule(&R, WIRE_R_BURN));
    /* A coil the all-off turned off in the model, shown on again past 1000 ms of the chain: a burn at that answer. */
    arm(t, 5);
    rig_read(&R, T_F + 700U, COIL12);
    rig_alloff(&R, T_F + 710U);
    rig_read(&R, T_F + 994U, COIL12);
    CHECK(t, !rig_rule(&R, WIRE_R_BURN));
    rig_init(&R, t);
    rig_read(&R, T_F - 10U, 0);
    rig_flash(&R, T_F, 12, 5);
    rig_read(&R, T_F + 700U, COIL12);
    rig_alloff(&R, T_F + 710U);
    rig_read(&R, T_F + 995U, COIL12);
    CHECK(t, rig_rule(&R, WIRE_R_BURN));
    /* A read that shows it on past 1000 ms is a burn at once, and a violation of I6. */
    arm(t, 5);
    rig_read(&R, T_F + 700U, COIL12);
    CHECK(t, !rig_rule(&R, WIRE_R_BURN));
    rig_read(&R, T_F + 1000U, COIL12);
    CHECK(t, rig_rule(&R, WIRE_R_BURN));
    CHECK_EQ_I64(t, rig_inv_of(&R, WIRE_R_BURN), WIRE_I6);
    CHECK(t, !wire_has_inv(&R.w, WIRE_I6B));
    /* A read that shows it off ends the chain. */
    arm(t, 5);
    rig_read(&R, T_F + 700U, COIL12);
    rig_read(&R, T_F + 800U, 0);
    rig_read(&R, T_F + 900U, COIL12);
    CHECK_EQ_I64(t, wire_finish(&R.w, T_F + 1904U), 0);
    CHECK(t, !rig_rule(&R, WIRE_R_BURN));
    CHECK_EQ_I64(t, wire_finish(&R.w, T_F + 1905U), 0);
    CHECK(t, rig_rule(&R, WIRE_R_BURN)); /* the new chain starts at the answer of 905: 905 + 1000 */
}

static void t_chain_across_reflash(ctest_t *t) {
    /* A flash while the coil is still on keeps the chain: 800 ms, then 800 more is 1590 ms on. */
    arm(t, 8);
    rig_flash(&R, T_F + 790U, 12, 8);
    CHECK_EQ_I64(t, wire_finish(&R.w, T_F + 999U), 0);
    CHECK(t, !rig_rule(&R, WIRE_R_BURN));
    CHECK_EQ_I64(t, wire_finish(&R.w, T_F + 1000U), 0);
    CHECK(t, rig_rule(&R, WIRE_R_BURN));
    /* A flash after the device timer ran out starts a new chain. */
    arm(t, 8);
    rig_flash(&R, T_F + 900U, 12, 8);
    CHECK_EQ_I64(t, wire_finish(&R.w, T_F + 1899U), 0);
    CHECK(t, !rig_rule(&R, WIRE_R_BURN));
    CHECK_EQ_I64(t, wire_finish(&R.w, T_F + 3000U), 0);
    CHECK(t, !rig_rule(&R, WIRE_R_BURN));
    /* A healthy 800 ms pulse is on for 800 ms at most. */
    arm(t, 8);
    CHECK_EQ_I64(t, wire_finish(&R.w, T_F + 800U), 0);
    CHECK_EQ_I64(t, wire_finish(&R.w, T_F + 5000U), 0);
    CHECK(t, !rig_rule(&R, WIRE_R_BURN));
}

CTEST_SUITE("watchdog", { "deadline_follows_the_pulse", t_deadline_follows_the_pulse }, { "all_off_boundary", t_all_off_boundary },
            { "all_off_before_the_read", t_all_off_before_the_read }, { "late_reply", t_late_reply },
            { "nothing_due", t_nothing_due }, { "once_per_flight_and_after_verify", t_once_per_flight_and_after_verify },
            { "burn", t_burn }, { "chain_across_reflash", t_chain_across_reflash })
