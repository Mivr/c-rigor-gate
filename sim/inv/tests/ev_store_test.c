/* I2 (durable save before open), I9 (crash consistency) and I10 (audit chain) through the public header. */
#include <string.h>

#include "sim/inv/tests/ev_rig.h"

static events_cfg_t C;
static events_t E;
static rig_world_t W;
static erig_t R;

static void start(ctest_t *t, const events_cfg_t *cfg, int with_world) {
    erig_start(&R, t, &E, &W, cfg, with_world);
    erig_ev_bare(&R, 1, T_BOOT);
}

static void begin(ctest_t *t) {
    erig_fill(&C);
    start(t, &C, 1);
}

/* staged, effect, handover: ready for the frames. Records 1 to 3. */
static void opening(uint64_t t0, uint32_t corr, uint32_t locker) {
    erig_ev(&R, t0, T_STAGED, corr, locker);
    erig_effect(&R, t0 + 1U, corr, locker);
    erig_handover(&R, t0 + 2U, corr, locker);
}

/* ---- I2 ---- */

static void t_a_reserved_book_passes_and_the_callback_sees_the_effect(ctest_t *t) {
    begin(t);
    opening(100, 0x01020304, 0x0a0b0c0d);
    erig_flash(&R, 110, 3);
    CHECK_EQ_U64(t, W.reserves_calls, 1);
    CHECK_EQ_U64(t, W.last_open_len, 8);
    static const uint8_t want[8] = {4, 3, 2, 1, 0x0d, 0x0c, 0x0b, 0x0a};
    CHECK_EQ_MEM(t, W.last_open, 8, want, 8);
    erig_flash(&R, 120, 3);
    CHECK_EQ_U64(t, W.reserves_calls, 2);
    CHECK_EQ_U64(t, events_finding_count(&E), 0);
    CHECK_EQ_U64(t, events_counts(&E).i2_checks, 2);
}

static void t_a_book_that_does_not_reserve_is_found_at_the_flash(ctest_t *t) {
    begin(t);
    opening(100, 1, 84);
    W.reserves = EV_BOOK_NOT_RESERVED;
    erig_flash(&R, 110, 3);
    CHECK_EQ_U64(t, events_finding_count(&E), 1);
    CHECK(t, erig_finding_is(&R, 0, EV_I2, EV_R_NOT_DURABLE, 4));
    CHECK_EQ_U64(t, events_finding(&E, 0)->t_ms, 110);
    W.reserves = 7; /* anything but "reserved" and "exempt" is a no */
    erig_flash(&R, 120, 3);
    CHECK(t, erig_finding_is(&R, 1, EV_I2, EV_R_NOT_DURABLE, 5));
}

static void t_an_undecodable_book_is_its_own_rule(ctest_t *t) {
    begin(t);
    opening(100, 1, 84);
    W.reserves = -1;
    erig_flash(&R, 110, 3);
    CHECK(t, erig_finding_is(&R, 0, EV_I2, EV_R_BOOK_UNDECODABLE, 4));
    CHECK(t, !events_has_rule(&E, EV_R_NOT_DURABLE));
    CHECK_EQ_U64(t, events_counts(&E).i2_checks, 1);
}

static void t_an_exempt_opening_needs_no_reservation(ctest_t *t) {
    begin(t);
    opening(100, 1, 84);
    W.reserves = EV_BOOK_EXEMPT;
    erig_flash(&R, 110, 3);
    CHECK_EQ_U64(t, events_finding_count(&E), 0);
    CHECK_EQ_U64(t, events_counts(&E).i2_checks, 0);
    CHECK_EQ_U64(t, W.reserves_calls, 1);
}

static void t_no_callback_no_check(ctest_t *t) {
    erig_fill(&C);
    start(t, &C, 0);
    opening(100, 1, 84);
    erig_flash(&R, 110, 3);
    CHECK_EQ_U64(t, events_finding_count(&E), 0);
    CHECK_EQ_U64(t, events_counts(&E).i2_checks, 0);
    CHECK_EQ_U64(t, W.reserves_calls, 0);
}

static void t_a_pulse_outside_an_opening_is_not_asked_to_the_book(ctest_t *t) {
    begin(t);
    erig_flash(&R, 110, 3);
    CHECK_EQ_U64(t, W.reserves_calls, 0);
    CHECK(t, events_has_rule(&E, EV_R_PULSE_NO_OPEN));
    CHECK(t, !events_has_inv(&E, EV_I2));
}

static void t_the_book_callback_gets_the_whole_effect_up_to_32_bytes(ctest_t *t) {
    erig_fill(&C);
    C.has_chain = 0;
    start(t, &C, 1);
    uint8_t big[33];
    for (uint32_t i = 0; i < sizeof big; i++) {
        big[i] = (uint8_t)(i + 1U);
    }
    erig_ev(&R, 100, T_STAGED, 1, 84);
    erig_rec(&R, "fx", 110, T_FX_OPEN, 5, big, 32);
    erig_handover(&R, 120, 1, 84);
    erig_flash(&R, 130, 3);
    CHECK_EQ_U64(t, W.last_open_len, 32);
    CHECK_EQ_MEM(t, W.last_open, 32, big, 32);
    CHECK_EQ_U64(t, events_finding_count(&E), 0);
    erig_ev(&R, 140, T_RESULT, 1, 84);
    erig_ev(&R, 150, T_STAGED, 2, 84);
    erig_rec(&R, "fx", 160, T_FX_OPEN, 5, big, 33); /* too long: a finding, and nothing is kept */
    erig_handover(&R, 170, 2, 84);
    erig_flash(&R, 180, 3);
    CHECK(t, events_has_rule(&E, EV_R_BAD_PAYLOAD));
    CHECK_EQ_U64(t, W.last_open_len, 0);
    C.corr_len = 0;
    start(t, &C, 1);
    erig_ev(&R, 100, T_STAGED, 1, 84);
    erig_rec(&R, "fx", 110, T_FX_OPEN, 5, NULL, 0);
    erig_rec(&R, "fx", 120, T_FX_OPEN, HANDOVER_B, NULL, 0);
    erig_flash(&R, 130, 3);
    CHECK_EQ_U64(t, W.reserves_calls, 1);
    CHECK_EQ_U64(t, W.last_open_len, 0);
}

/* ---- I9: the book at a power cut ---- */

static void save(uint64_t t_ms, uint64_t digest) {
    W.digest = digest;
    erig_io(&R, t_ms, IO_A(1, 0), "book");
}

static void cut(ctest_t *t, uint64_t t_ms) {
    CHECK_EQ_I64(t, events_power_cut(&E, t_ms), 0);
    CHECK_EQ_I64(t, events_restarted(&E, t_ms), 0);
}

static void t_a_book_equal_to_the_last_durable_save_passes(ctest_t *t) {
    begin(t);
    save(100, 11);
    save(200, 22);
    CHECK_EQ_U64(t, events_counts(&E).durable_saves, 2);
    CHECK_EQ_U64(t, W.digest_calls, 2);
    cut(t, 300);
    CHECK_EQ_U64(t, events_finding_count(&E), 0);
    CHECK_EQ_U64(t, events_counts(&E).power_cuts, 1);
    W.digest = 33; /* the book changed in the cut */
    cut(t, 400);
    CHECK_EQ_U64(t, events_finding_count(&E), 1);
    CHECK(t, erig_finding_is(&R, 0, EV_I9, EV_R_CRASH_BOOK_CHANGED, 3));
    CHECK_EQ_U64(t, events_finding(&E, 0)->t_ms, 400);
}

static void t_the_book_of_a_save_is_what_a_cut_must_keep(ctest_t *t) {
    begin(t);
    save(100, 11);
    W.digest = 22;
    cut(t, 200);
    CHECK(t, erig_finding_is(&R, 0, EV_I9, EV_R_CRASH_BOOK_CHANGED, 2));
}

static void t_only_a_completed_durable_ok_save_of_the_book_counts(ctest_t *t) {
    begin(t);
    save(100, 11);
    W.digest = 99;
    erig_io(&R, 110, IO_A(0, 0), "book");     /* not durable */
    erig_io(&R, 120, IO_A(1, 1), "book");     /* failed */
    erig_io(&R, 130, T_DONE + 1U + (1U << 20), "book"); /* another operation */
    erig_io(&R, 140, IO_A(1, 0), "boo");      /* another file */
    erig_io(&R, 150, IO_A(1, 0), "books");
    erig_io(&R, 160, IO_A(1, 0), "audit");
    erig_rec(&R, "io", 170, IO_A(1, 0), 0, NULL, 0);
    erig_rec(&R, "ev", 180, IO_A(1, 0), 0, (const uint8_t *)"book", 4); /* not an io record */
    CHECK_EQ_U64(t, events_counts(&E).durable_saves, 1);
    CHECK_EQ_U64(t, W.digest_calls, 1);
    W.digest = 11;
    cut(t, 200);
    CHECK_EQ_U64(t, events_finding_count(&E), 0);
}

static void t_an_empty_book_name_matches_nothing(ctest_t *t) {
    erig_fill(&C);
    C.io_book[0] = 0;
    start(t, &C, 1);
    erig_rec(&R, "io", 100, IO_A(1, 0), 0, NULL, 0);
    CHECK_EQ_U64(t, events_counts(&E).durable_saves, 0);
    CHECK_EQ_U64(t, W.digest_calls, 0);
}

static void t_an_unreadable_book_in_a_save_or_after_a_cut(ctest_t *t) {
    begin(t);
    W.digest_rc = -1;
    save(100, 11);
    CHECK(t, erig_finding_is(&R, 0, EV_I2, EV_R_BOOK_UNDECODABLE, 1));
    cut(t, 200);
    CHECK(t, erig_finding_is(&R, 1, EV_I9, EV_R_CRASH_BOOK_UNREADABLE, 2));
    CHECK_EQ_U64(t, events_finding_count(&E), 2);
    W.digest_rc = 0;
    save(300, 5); /* a good save after a bad one is the book again */
    cut(t, 400);
    CHECK_EQ_U64(t, events_finding_count(&E), 2);
}

static void t_a_cut_before_any_save_learns_the_book_and_holds_it(ctest_t *t) {
    begin(t);
    W.digest = 50;
    cut(t, 100);
    CHECK_EQ_U64(t, events_finding_count(&E), 0);
    cut(t, 200);
    CHECK_EQ_U64(t, events_finding_count(&E), 0);
    W.digest = 51;
    cut(t, 300);
    CHECK(t, erig_finding_is(&R, 0, EV_I9, EV_R_CRASH_BOOK_CHANGED, 1));
}

static void t_without_digest_callback_nothing_to_compare(ctest_t *t) {
    erig_fill(&C);
    start(t, &C, 0);
    erig_io(&R, 100, IO_A(1, 0), "book");
    cut(t, 200);
    CHECK_EQ_U64(t, events_finding_count(&E), 0);
    CHECK_EQ_U64(t, events_counts(&E).durable_saves, 1);
}

/* ---- I9: the audit file after a cut ---- */

#define L1 "{\"seq\":5,\"e\":\"a\"}\n"
#define L2 "{\"seq\":6,\"e\":\"b\"}\n"
#define L4 "{\"seq\":8,\"e\":\"d\"}\n"

static void audit(const char *s) {
    W.audit = (const uint8_t *)s;
    W.audit_len = (uint32_t)strlen(s);
}

static void t_the_audit_after_a_cut_may_end_in_a_torn_line(ctest_t *t) {
    begin(t);
    audit(L1 L2 "{\"seq\":7,\"e");
    cut(t, 100);
    CHECK_EQ_U64(t, events_finding_count(&E), 0);
    CHECK_EQ_U64(t, events_counts(&E).audit_lines, 2);
    CHECK_EQ_U64(t, W.audit_calls, 1);
}

static void t_a_gap_or_a_bad_line_after_a_cut(ctest_t *t) {
    begin(t);
    audit(L1 L4);
    cut(t, 100);
    CHECK(t, erig_finding_is(&R, 0, EV_I9, EV_R_CRASH_AUDIT_GAP, 1));
    audit(L1 "not json\n");
    cut(t, 200);
    CHECK(t, erig_finding_is(&R, 1, EV_I9, EV_R_CRASH_AUDIT_FORMAT, 1));
    W.audit_rc = -1;
    cut(t, 300);
    CHECK(t, erig_finding_is(&R, 2, EV_I9, EV_R_CRASH_AUDIT_FORMAT, 1));
    CHECK_EQ_U64(t, events_finding_count(&E), 3);
}

static void t_the_audit_bound_holds_after_a_cut(ctest_t *t) {
    erig_fill(&C);
    C.audit_max_bytes = 36;
    start(t, &C, 1);
    audit(L1 L2); /* 2 x 18 bytes: at the bound */
    cut(t, 100);
    CHECK_EQ_U64(t, events_finding_count(&E), 0);
    audit(L1 L2 "{");
    cut(t, 200);
    CHECK(t, erig_finding_is(&R, 0, EV_I10, EV_R_AUDIT_BOUND, 1));
    C.audit_max_bytes = 0;
    start(t, &C, 1);
    audit(L1 L2 L1);
    cut(t, 100);
    CHECK_EQ_U64(t, events_finding_count(&E), 1); /* seq 5 after 6: a gap, but no bound */
    CHECK(t, events_has_rule(&E, EV_R_CRASH_AUDIT_GAP));
}

static void t_without_audit_callback_nothing_is_read(ctest_t *t) {
    erig_fill(&C);
    start(t, &C, 0);
    cut(t, 100);
    CHECK_EQ_U64(t, events_finding_count(&E), 0);
}

/* ---- I9: what a power cut drops ---- */

static void t_a_cut_forgets_the_volatile_state(ctest_t *t) {
    begin(t);
    erig_ev(&R, 100, T_STAGED, 1, 84);      /* a credit */
    erig_effect(&R, 110, 1, 84);            /* in flight, unhanded, a locker opening */
    CHECK_EQ_I64(t, events_power_cut(&E, 120), 0);
    erig_effect(&R, 130, 2, 84);            /* no boot, no credit, no flight */
    CHECK(t, events_has_rule(&E, EV_R_OPEN_BEFORE_BOOT));
    CHECK(t, events_has_rule(&E, EV_R_NO_AUTH));
    CHECK(t, !events_has_rule(&E, EV_R_OPEN_OVERLAP));
    erig_handover(&R, 140, 2, 84);
    erig_handover(&R, 141, 2, 84); /* only the new effect is waiting for a hand-over */
    CHECK_EQ_U64(t, events_finding_count(&E), 3);
    CHECK(t, events_has_rule(&E, EV_R_HANDOVER_NO_EFFECT));
}

static void t_a_cut_closes_the_pulse_window_and_the_phase(ctest_t *t) {
    begin(t);
    opening(100, 1, 84);
    erig_vw(&R, 105, 3);
    CHECK_EQ_I64(t, events_power_cut(&E, 110), 0);
    erig_flash(&R, 120, 3);
    CHECK(t, events_has_rule(&E, EV_R_PULSE_NO_OPEN));
    CHECK_EQ_I64(t, events_finish(&E, 500000), 0);
    CHECK(t, !events_has_rule(&E, EV_R_NOT_IDLE_AT_END));
    CHECK(t, !events_has_rule(&E, EV_R_STUCK_PHASE));
}

static void t_a_cut_keeps_assignments_and_drops_openings(ctest_t *t) {
    begin(t);
    erig_ev(&R, 100, T_ASSIGNED, 0, 84);
    opening(110, 1, 84);
    CHECK_EQ_I64(t, events_power_cut(&E, 120), 0);
    erig_ev_bare(&R, 125, T_BOOT);
    erig_ev(&R, 130, T_DOOR, 0, 84);
    CHECK(t, !events_has_rule(&E, EV_R_DOOR_NO_ASSIGN));
    CHECK(t, events_has_rule(&E, EV_R_DOOR_NO_OPEN)); /* the opening before the cut does not pay for it */
}

static void t_a_boot_event_after_a_cut_allows_openings(ctest_t *t) {
    begin(t);
    CHECK_EQ_I64(t, events_power_cut(&E, 100), 0);
    erig_ev_bare(&R, 110, T_BOOT);
    erig_ev(&R, 120, T_STAGED, 1, 84);
    erig_effect(&R, 130, 1, 84);
    CHECK_EQ_U64(t, events_finding_count(&E), 0);
}

static void t_the_boot_rule_is_off_without_a_boot_event(ctest_t *t) {
    erig_fill(&C);
    C.has_boot = 0;
    C.ev_boot = T_STAGED;
    start(t, &C, 1);
    CHECK_EQ_I64(t, events_power_cut(&E, 100), 0);
    erig_ev(&R, 120, T_STAGED, 1, 84); /* the boot id is the staged id here: it must not set anything */
    erig_effect(&R, 130, 1, 84);
    CHECK_EQ_U64(t, events_finding_count(&E), 0);
}

static void t_cuts_and_restarts_keep_time_in_order(ctest_t *t) {
    begin(t);
    erig_ev_bare(&R, 100, T_STAGED);
    CHECK_EQ_I64(t, events_power_cut(&E, 99), -1);
    CHECK_EQ_I64(t, events_restarted(&E, 99), -1);
    CHECK_EQ_I64(t, events_finish(&E, 99), -1);
    CHECK_EQ_I64(t, events_power_cut(&E, 100), 0);
    CHECK_EQ_I64(t, events_restarted(&E, 100), 0);
    CHECK_EQ_U64(t, events_counts(&E).power_cuts, 1);
}

/* ---- I10 ---- */

static void t_a_door_needs_an_assignment_and_an_opening(ctest_t *t) {
    begin(t);
    erig_ev(&R, 100, T_ASSIGNED, 0, 84);
    opening(110, 1, 84);
    erig_ev(&R, 200, T_DOOR, 0, 84);
    CHECK_EQ_U64(t, events_finding_count(&E), 0);
    CHECK_EQ_U64(t, events_counts(&E).doors, 1);
    erig_ev(&R, 210, T_DOOR, 0, 84); /* a second door for one opening */
    CHECK(t, erig_finding_is(&R, 0, EV_I10, EV_R_DOOR_NO_OPEN, 6));
    CHECK_EQ_U64(t, events_finding_count(&E), 1);
}

static void t_a_door_for_a_locker_never_assigned(ctest_t *t) {
    begin(t);
    opening(110, 1, 84);
    erig_ev(&R, 200, T_DOOR, 0, 84);
    CHECK(t, erig_finding_is(&R, 0, EV_I10, EV_R_DOOR_NO_ASSIGN, 4));
    CHECK_EQ_U64(t, events_finding_count(&E), 1);
    erig_ev(&R, 210, T_DOOR, 0, 85); /* another locker: neither an assignment nor an opening */
    CHECK(t, events_has_rule(&E, EV_R_DOOR_NO_OPEN));
    CHECK_EQ_U64(t, events_finding_count(&E), 3);
}

static void t_openings_and_doors_are_counted_per_locker(ctest_t *t) {
    begin(t);
    erig_ev(&R, 100, T_ASSIGNED, 0, 84);
    erig_ev(&R, 101, T_ASSIGNED, 0, 85);
    erig_visit(&R, 200, 1, 84);
    erig_visit(&R, 1000, 2, 85);
    erig_visit(&R, 2000, 3, 84);
    erig_ev(&R, 3000, T_DOOR, 0, 84);
    erig_ev(&R, 3001, T_DOOR, 0, 85);
    erig_ev(&R, 3002, T_DOOR, 0, 84);
    CHECK_EQ_U64(t, events_finding_count(&E), 0);
    erig_ev(&R, 3003, T_DOOR, 0, 85);
    CHECK_EQ_U64(t, events_finding_count(&E), 1);
}

static void t_locker_zero_is_a_locker(ctest_t *t) {
    begin(t);
    erig_ev(&R, 100, T_ASSIGNED, 0, 0);
    erig_ev(&R, 101, T_ASSIGNED, 0, 7);
    erig_visit(&R, 1000, 1, 0);
    erig_ev(&R, 2000, T_DOOR, 0, 0);
    CHECK_EQ_U64(t, events_finding_count(&E), 0);
}

static void t_the_locker_table_fails_closed_at_64(ctest_t *t) {
    begin(t);
    for (uint32_t k = 0; k < 64U; k++) {
        erig_ev(&R, 100U + k, T_ASSIGNED, 0, 1000U + k);
    }
    CHECK_EQ_U64(t, events_finding_count(&E), 0);
    erig_ev(&R, 200, T_ASSIGNED, 0, 2000);
    CHECK(t, erig_finding_is(&R, 0, EV_I10, EV_R_TABLE_FULL, 65));
    erig_ev(&R, 201, T_ASSIGNED, 0, 2001);
    erig_ev(&R, 202, T_DOOR, 0, 2000); /* unknown and untracked: nothing more is said about it */
    CHECK_EQ_U64(t, events_finding_count(&E), 1);
    erig_ev(&R, 203, T_DOOR, 0, 1063); /* the last one that fit */
    CHECK(t, events_has_rule(&E, EV_R_DOOR_NO_OPEN));
    CHECK_EQ_U64(t, events_counts(&E).doors, 2);
}

static void t_a_short_locker_payload_is_a_finding(ctest_t *t) {
    begin(t);
    static const uint8_t six[6] = {0, 0, 0, 0, 84, 0};
    erig_rec(&R, "ev", 100, T_ASSIGNED, 0, six, 6);
    CHECK(t, erig_finding_is(&R, 0, EV_I10, EV_R_SHORT_LOCKER, 1));
    erig_rec(&R, "ev", 110, T_DOOR, 0, six, 6);
    CHECK(t, erig_finding_is(&R, 1, EV_I10, EV_R_SHORT_LOCKER, 2));
    CHECK_EQ_U64(t, events_counts(&E).doors, 1);
    erig_ev(&R, 120, T_STAGED, 1, 84);
    erig_rec(&R, "fx", 130, T_FX_OPEN, 5, six, 6); /* the corr is there, the locker is not */
    CHECK(t, erig_finding_is(&R, 2, EV_I10, EV_R_SHORT_LOCKER, 4));
    CHECK_EQ_U64(t, events_finding_count(&E), 3);
}

static void t_one_byte_and_two_byte_lockers(ctest_t *t) {
    erig_fill(&C);
    C.ev_locker_len = 1;
    C.ev_locker_off = 5;
    C.fx_locker_off = 5;
    start(t, &C, 1);
    static const uint8_t p[8] = {1, 0, 0, 0, 0xff, 84, 0, 0};
    static const uint8_t q[8] = {1, 0, 0, 0, 0xee, 84, 0, 0}; /* the byte before is another locker's */
    erig_rec(&R, "ev", 100, T_ASSIGNED, 0, p, 8);
    erig_rec(&R, "ev", 110, T_DOOR, 0, q, 8);
    CHECK(t, !events_has_rule(&E, EV_R_DOOR_NO_ASSIGN)); /* one byte at offset 5 is the same locker in both */
    CHECK(t, events_has_rule(&E, EV_R_DOOR_NO_OPEN));
    CHECK_EQ_U64(t, events_finding_count(&E), 1);
    C.ev_locker_len = 2;
    C.ev_locker_off = 5;
    C.fx_locker_off = 5;
    start(t, &C, 1);
    static const uint8_t r[8] = {1, 0, 0, 0, 0, 84, 1, 0};
    static const uint8_t s2[8] = {1, 0, 0, 0, 0, 84, 2, 0}; /* the second byte differs: another locker */
    erig_rec(&R, "ev", 100, T_ASSIGNED, 0, r, 8);
    erig_rec(&R, "ev", 110, T_DOOR, 0, s2, 8);
    CHECK(t, events_has_rule(&E, EV_R_DOOR_NO_ASSIGN));
}

static void t_the_chain_rules_are_off_without_the_flag(ctest_t *t) {
    erig_fill(&C);
    C.has_chain = 0;
    C.ev_locker_len = 0;
    start(t, &C, 1);
    erig_ev(&R, 100, T_DOOR, 0, 84);
    erig_ev(&R, 101, T_ASSIGNED, 0, 84);
    CHECK_EQ_U64(t, events_finding_count(&E), 0);
    CHECK_EQ_U64(t, events_counts(&E).doors, 0);
}

/* ---- I10: the audit file at the end ---- */

static void t_the_audit_file_at_the_end(ctest_t *t) {
    begin(t);
    audit(L1 L2);
    CHECK_EQ_I64(t, events_finish(&E, 1000), 0);
    CHECK_EQ_U64(t, events_finding_count(&E), 0);
    CHECK_EQ_U64(t, events_counts(&E).audit_lines, 2);
}

static void t_a_torn_tail_is_not_allowed_at_the_end(ctest_t *t) {
    begin(t);
    audit(L1 "{\"seq\":6");
    CHECK_EQ_I64(t, events_finish(&E, 1000), 0);
    CHECK(t, erig_finding_is(&R, 0, EV_I10, EV_R_AUDIT_FORMAT, 1));
}

static void t_a_gap_at_the_end(ctest_t *t) {
    begin(t);
    audit(L1 L4);
    CHECK_EQ_I64(t, events_finish(&E, 1000), 0);
    CHECK(t, erig_finding_is(&R, 0, EV_I10, EV_R_AUDIT_GAP, 1));
    CHECK_EQ_U64(t, events_finding_count(&E), 1);
}

static void t_an_unreadable_audit_at_the_end(ctest_t *t) {
    begin(t);
    W.audit_rc = -1;
    CHECK_EQ_I64(t, events_finish(&E, 1000), 0);
    CHECK(t, erig_finding_is(&R, 0, EV_I10, EV_R_AUDIT_FORMAT, 1));
}

static void t_the_audit_bound_at_the_end(ctest_t *t) {
    erig_fill(&C);
    C.audit_max_bytes = 35;
    start(t, &C, 1);
    audit(L1 L2);
    CHECK_EQ_I64(t, events_finish(&E, 1000), 0);
    CHECK(t, erig_finding_is(&R, 0, EV_I10, EV_R_AUDIT_BOUND, 1));
    CHECK_EQ_U64(t, events_finding_count(&E), 1);
}

CTEST_SUITE("ev_store",
    { "reserved_passes", t_a_reserved_book_passes_and_the_callback_sees_the_effect },
    { "not_reserved", t_a_book_that_does_not_reserve_is_found_at_the_flash },
    { "undecodable", t_an_undecodable_book_is_its_own_rule },
    { "exempt", t_an_exempt_opening_needs_no_reservation },
    { "no_callback", t_no_callback_no_check },
    { "pulse_outside_opening", t_a_pulse_outside_an_opening_is_not_asked_to_the_book },
    { "payload_cap", t_the_book_callback_gets_the_whole_effect_up_to_32_bytes },
    { "save_is_kept", t_the_book_of_a_save_is_what_a_cut_must_keep },
    { "book_equal", t_a_book_equal_to_the_last_durable_save_passes },
    { "only_durable_ok_saves", t_only_a_completed_durable_ok_save_of_the_book_counts },
    { "empty_book_name", t_an_empty_book_name_matches_nothing },
    { "unreadable_book", t_an_unreadable_book_in_a_save_or_after_a_cut },
    { "learn_first_book", t_a_cut_before_any_save_learns_the_book_and_holds_it },
    { "no_digest_callback", t_without_digest_callback_nothing_to_compare },
    { "torn_audit", t_the_audit_after_a_cut_may_end_in_a_torn_line },
    { "crash_audit_bad", t_a_gap_or_a_bad_line_after_a_cut },
    { "crash_audit_bound", t_the_audit_bound_holds_after_a_cut },
    { "no_audit_callback", t_without_audit_callback_nothing_is_read },
    { "cut_forgets", t_a_cut_forgets_the_volatile_state },
    { "cut_window_phase", t_a_cut_closes_the_pulse_window_and_the_phase },
    { "cut_keeps_assignments", t_a_cut_keeps_assignments_and_drops_openings },
    { "boot_allows", t_a_boot_event_after_a_cut_allows_openings },
    { "boot_rule_off", t_the_boot_rule_is_off_without_a_boot_event },
    { "cut_time_order", t_cuts_and_restarts_keep_time_in_order },
    { "door_needs", t_a_door_needs_an_assignment_and_an_opening },
    { "door_unassigned", t_a_door_for_a_locker_never_assigned },
    { "per_locker", t_openings_and_doors_are_counted_per_locker },
    { "locker_zero", t_locker_zero_is_a_locker },
    { "table_full", t_the_locker_table_fails_closed_at_64 },
    { "short_locker", t_a_short_locker_payload_is_a_finding },
    { "locker_width", t_one_byte_and_two_byte_lockers },
    { "chain_off", t_the_chain_rules_are_off_without_the_flag },
    { "audit_end", t_the_audit_file_at_the_end },
    { "audit_torn_end", t_a_torn_tail_is_not_allowed_at_the_end },
    { "audit_gap_end", t_a_gap_at_the_end },
    { "audit_unreadable_end", t_an_unreadable_audit_at_the_end },
    { "audit_bound_end", t_the_audit_bound_at_the_end })
