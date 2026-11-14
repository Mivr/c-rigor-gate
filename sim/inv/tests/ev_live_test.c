/* I15 (liveness), the configuration checks and the feed contract of the event engine. */
#include <string.h>

#include "sim/inv/tests/ev_rig.h"

static events_cfg_t C;
static events_t E;
static rig_world_t W;
static erig_t R;

static void start(ctest_t *t, const events_cfg_t *cfg) {
    erig_start(&R, t, &E, &W, cfg, 1);
}

static void begin(ctest_t *t) {
    erig_fill(&C);
    start(t, &C);
}

/* ---- phases ---- */

static void t_a_phase_may_last_its_limit_and_no_more(ctest_t *t) {
    begin(t);
    erig_vw(&R, 1000, 3);          /* opened: limit 8500 */
    erig_vw(&R, 1000 + 8500, 3);   /* republished at the limit */
    CHECK_EQ_U64(t, events_finding_count(&E), 0);
    erig_vw(&R, 1000 + 8501, 3);
    CHECK_EQ_U64(t, events_finding_count(&E), 1);
    CHECK(t, erig_finding_is(&R, 0, EV_I15, EV_R_STUCK_PHASE, 2));
    CHECK_EQ_U64(t, events_finding(&E, 0)->t_ms, 9501);
    erig_vw(&R, 20000, 3); /* once per stay */
    CHECK_EQ_U64(t, events_finding_count(&E), 1);
}

static void t_a_late_change_out_of_the_phase_is_still_late(ctest_t *t) {
    begin(t);
    erig_vw(&R, 1000, 2);
    erig_vw(&R, 1000 + 3001, 0);
    CHECK(t, erig_finding_is(&R, 0, EV_I15, EV_R_STUCK_PHASE, 1));
    CHECK_EQ_I64(t, events_finish(&E, 100000), 0);
    CHECK(t, !events_has_rule(&E, EV_R_NOT_IDLE_AT_END));
    CHECK_EQ_U64(t, events_finding_count(&E), 1);
}

static void t_every_entry_starts_its_own_timer(ctest_t *t) {
    begin(t);
    erig_vw(&R, 1000, 3);
    erig_vw(&R, 9000, 0);
    erig_vw(&R, 9500, 3);
    erig_vw(&R, 9500 + 8500, 3);
    CHECK_EQ_U64(t, events_finding_count(&E), 0);
    erig_vw(&R, 9500 + 8501, 3);
    CHECK_EQ_U64(t, events_finding_count(&E), 1);
    erig_vw(&R, 30000, 0);
    erig_vw(&R, 30001, 3); /* a new stay: flagged again */
    erig_vw(&R, 30001 + 8501, 3);
    CHECK_EQ_U64(t, events_finding_count(&E), 2);
    CHECK_EQ_U64(t, events_counts(&E).phase_changes, 5);
}

static void t_a_repeat_of_the_phase_does_not_restart_the_timer(ctest_t *t) {
    begin(t);
    erig_vw(&R, 1000, 2);
    erig_vw(&R, 3000, 2);
    erig_vw(&R, 4001, 2);
    CHECK_EQ_U64(t, events_finding_count(&E), 1);
    CHECK_EQ_U64(t, events_counts(&E).phase_changes, 1);
}

static void t_a_phase_without_a_limit_never_sticks(ctest_t *t) {
    erig_fill(&C);
    C.rows[4] = (events_phase_row_t){{{'v', 'w'}, 4}, 4};
    C.n_rows = 5;
    start(t, &C);
    erig_vw(&R, 1000, 4);
    erig_vw(&R, 90000000, 4);
    CHECK_EQ_U64(t, events_finding_count(&E), 0);
    CHECK_EQ_I64(t, events_finish(&E, 99000000), 0);
    CHECK_EQ_U64(t, events_finding_count(&E), 1); /* but it is not idle at the end */
    CHECK(t, events_has_rule(&E, EV_R_NOT_IDLE_AT_END));
}

static void t_the_phase_comes_from_the_kind_and_the_type_of_a_record(ctest_t *t) {
    begin(t);
    erig_ev_bare(&R, 1000, 3); /* an ev of type 3 is not the view of phase 3 */
    erig_rec(&R, "fx", 1001, 3, 0, NULL, 0);
    erig_rec(&R, "xx", 1002, 3, 0, NULL, 0);
    erig_vw(&R, 1003, 7); /* no row */
    CHECK_EQ_U64(t, events_counts(&E).phase_changes, 0);
    erig_rec(&R, "vw", 1004, 3, 99, (const uint8_t *)"abc", 3);
    CHECK_EQ_U64(t, events_counts(&E).phase_changes, 1);
}

static void t_the_first_matching_row_wins(ctest_t *t) {
    erig_fill(&C);
    C.rows[4] = (events_phase_row_t){{{'v', 'w'}, 1}, 3};
    C.n_rows = 5;
    start(t, &C);
    erig_vw(&R, 1000, 1);
    erig_vw(&R, 1000 + 30501, 1);
    CHECK(t, events_has_rule(&E, EV_R_STUCK_PHASE)); /* phase 1 (limit 30500), not the later row's phase 3 */
    start(t, &C);
    erig_vw(&R, 1000, 1);
    erig_vw(&R, 1000 + 30500, 1);
    CHECK_EQ_U64(t, events_finding_count(&E), 0);
}

static void t_only_the_configured_rows_are_read(ctest_t *t) {
    erig_fill(&C);
    C.n_rows = 2;
    start(t, &C);
    erig_vw(&R, 1000, 2); /* a row beyond n_rows */
    CHECK_EQ_U64(t, events_counts(&E).phase_changes, 0);
    erig_vw(&R, 1001, 1);
    CHECK_EQ_U64(t, events_counts(&E).phase_changes, 1);
}

static void t_the_run_must_end_idle(ctest_t *t) {
    begin(t);
    erig_vw(&R, 1000, 1);
    CHECK_EQ_I64(t, events_finish(&E, 1000 + 30500), 0);
    CHECK_EQ_U64(t, events_finding_count(&E), 1);
    CHECK(t, erig_finding_is(&R, 0, EV_I15, EV_R_NOT_IDLE_AT_END, 1));
    begin(t);
    erig_vw(&R, 1000, 1);
    CHECK_EQ_I64(t, events_finish(&E, 1000 + 30501), 0);
    CHECK(t, events_has_rule(&E, EV_R_STUCK_PHASE));
    CHECK(t, events_has_rule(&E, EV_R_NOT_IDLE_AT_END));
    begin(t);
    erig_vw(&R, 1000, 1);
    erig_vw(&R, 2000, 0);
    CHECK_EQ_I64(t, events_finish(&E, 3000), 0);
    CHECK_EQ_U64(t, events_finding_count(&E), 0);
}

static void t_other_record_kinds_advance_time_too(ctest_t *t) {
    begin(t);
    erig_vw(&R, 1000, 2);
    erig_rec(&R, "st", 5000, 0, 0, NULL, 0);
    CHECK(t, erig_finding_is(&R, 0, EV_I15, EV_R_STUCK_PHASE, 1));
}

/* ---- the relay fault clears ---- */

static void relay_clear(uint64_t t_ms) {
    erig_ev_bare(&R, t_ms, T_RELAY_CLEAR);
}

static void t_welcome_must_come_after_the_relay_clears(ctest_t *t) {
    begin(t);
    erig_vw(&R, 500, 2); /* off welcome */
    relay_clear(1000);
    erig_vw(&R, 8000, 2); /* at the deadline */
    CHECK_EQ_U64(t, events_finding_count(&E), 1); /* the stuck phase 2 (limit 3000) also fires */
    CHECK(t, !events_has_rule(&E, EV_R_NO_RECOVERY));
    erig_vw(&R, 8001, 2);
    CHECK(t, events_has_rule(&E, EV_R_NO_RECOVERY));
    CHECK(t, erig_finding_is(&R, 1, EV_I15, EV_R_NO_RECOVERY, 3));
    erig_vw(&R, 9000, 2); /* once */
    CHECK_EQ_U64(t, events_finding_count(&E), 2);
}

static void t_reaching_welcome_clears_the_deadline(ctest_t *t) {
    begin(t);
    erig_vw(&R, 500, 2);
    relay_clear(1000);
    erig_vw(&R, 2000, 0);
    erig_vw(&R, 20000, 0); /* still at welcome long after the deadline: nothing is due */
    CHECK(t, !events_has_rule(&E, EV_R_NO_RECOVERY));
    erig_vw(&R, 20500, 2);
    erig_vw(&R, 90000, 0);
    CHECK(t, !events_has_rule(&E, EV_R_NO_RECOVERY));
}

static void t_no_deadline_when_already_at_welcome(ctest_t *t) {
    begin(t);
    relay_clear(1000);
    erig_vw(&R, 2000, 3);
    erig_vw(&R, 10000, 0);
    CHECK(t, !events_has_rule(&E, EV_R_NO_RECOVERY));
}

static void t_a_relay_clear_sets_its_deadline_from_its_own_time(ctest_t *t) {
    begin(t);
    erig_vw(&R, 500, 2);
    relay_clear(1000);
    relay_clear(5000); /* a second clear moves the deadline */
    erig_vw(&R, 12000, 2);
    CHECK(t, !events_has_rule(&E, EV_R_NO_RECOVERY));
    erig_vw(&R, 12001, 2);
    CHECK(t, events_has_rule(&E, EV_R_NO_RECOVERY));
}

static void t_the_recovery_rule_needs_its_flag_and_its_selector(ctest_t *t) {
    erig_fill(&C);
    C.has_recover = 0;
    start(t, &C);
    erig_vw(&R, 500, 2);
    relay_clear(1000);
    erig_vw(&R, 100000, 2);
    CHECK(t, !events_has_rule(&E, EV_R_NO_RECOVERY));
    C.has_recover = 1;
    start(t, &C);
    erig_vw(&R, 500, 2);
    erig_rec(&R, "fx", 1000, T_RELAY_CLEAR, 0, NULL, 0); /* the wrong kind */
    erig_rec(&R, "ev", 1001, T_RELAY_CLEAR + 1U, 0, NULL, 0);
    erig_vw(&R, 100000, 2);
    CHECK(t, !events_has_rule(&E, EV_R_NO_RECOVERY));
}

static void t_welcome_may_be_another_phase(ctest_t *t) {
    erig_fill(&C);
    C.welcome_phase = 1;
    start(t, &C);
    erig_vw(&R, 500, 2);
    relay_clear(1000);
    erig_vw(&R, 2000, 1);
    erig_vw(&R, 2500, 2);
    erig_vw(&R, 20000, 2);
    CHECK(t, !events_has_rule(&E, EV_R_NO_RECOVERY));
    erig_vw(&R, 30000, 1);
    relay_clear(30001); /* already at welcome */
    erig_vw(&R, 90000, 1);
    CHECK(t, !events_has_rule(&E, EV_R_NO_RECOVERY));
}

/* ---- init and the feed contract ---- */

static void t_bad_configurations_are_refused(ctest_t *t) {
    erig_fill(&C);
    CHECK_EQ_I64(t, events_init(&E, &C, NULL), 0);
    CHECK_EQ_I64(t, events_init(NULL, &C, NULL), -1);
    CHECK_EQ_I64(t, events_init(&E, NULL, NULL), -1);
    erig_fill(&C); C.n_auth = 0;
    CHECK_EQ_I64(t, events_init(&E, &C, NULL), -1);
    erig_fill(&C); C.n_auth = 4;
    CHECK_EQ_I64(t, events_init(&E, &C, NULL), 0);
    erig_fill(&C); C.n_auth = 5;
    CHECK_EQ_I64(t, events_init(&E, &C, NULL), -1);
    erig_fill(&C); C.corr_len = 8;
    CHECK_EQ_I64(t, events_init(&E, &C, NULL), 0);
    erig_fill(&C); C.corr_len = 9;
    CHECK_EQ_I64(t, events_init(&E, &C, NULL), -1);
    erig_fill(&C); C.flashes_per_open = 0;
    CHECK_EQ_I64(t, events_init(&E, &C, NULL), -1);
    erig_fill(&C); C.n_rows = 8;
    CHECK_EQ_I64(t, events_init(&E, &C, NULL), 0);
    erig_fill(&C); C.n_rows = 9; C.limit_ms[1] = 0; /* the row after the table would read as phase 0 */
    CHECK_EQ_I64(t, events_init(&E, &C, NULL), -1);
    erig_fill(&C); C.n_rows = 16; C.limit_ms[1] = 0;
    CHECK_EQ_I64(t, events_init(&E, &C, NULL), -1);
    erig_fill(&C); C.rows[0].phase = 8;
    CHECK_EQ_I64(t, events_init(&E, &C, NULL), -1);
    erig_fill(&C); C.corr_len = 0; C.corr_off = 1;
    CHECK_EQ_I64(t, events_init(&E, &C, NULL), -1);
    erig_fill(&C); C.corr_len = 0; C.result_corr_off = 1;
    CHECK_EQ_I64(t, events_init(&E, &C, NULL), -1);
    erig_fill(&C); C.corr_len = 0;
    CHECK_EQ_I64(t, events_init(&E, &C, NULL), 0);
    erig_fill(&C); C.welcome_phase = 7;
    CHECK_EQ_I64(t, events_init(&E, &C, NULL), 0);
    erig_fill(&C); C.welcome_phase = 8;
    CHECK_EQ_I64(t, events_init(&E, &C, NULL), -1);
    erig_fill(&C); C.limit_ms[0] = 1;
    CHECK_EQ_I64(t, events_init(&E, &C, NULL), -1);
    erig_fill(&C); memset(C.io_book, 'x', EV_NAME_MAX);
    CHECK_EQ_I64(t, events_init(&E, &C, NULL), -1);
    erig_fill(&C); memset(C.io_book, 'x', EV_NAME_MAX - 1U); C.io_book[EV_NAME_MAX - 1U] = 0;
    CHECK_EQ_I64(t, events_init(&E, &C, NULL), 0);
}

static void t_chain_and_phase_configurations_are_checked(ctest_t *t) {
    erig_fill(&C);
    C.ev_locker_len = 0;
    CHECK_EQ_I64(t, events_init(&E, &C, NULL), -1);
    C.ev_locker_len = 1;
    CHECK_EQ_I64(t, events_init(&E, &C, NULL), 0);
    C.ev_locker_len = 4;
    CHECK_EQ_I64(t, events_init(&E, &C, NULL), 0);
    C.ev_locker_len = 5;
    CHECK_EQ_I64(t, events_init(&E, &C, NULL), -1);
    C.has_chain = 0; /* the length does not matter when the rules are off */
    CHECK_EQ_I64(t, events_init(&E, &C, NULL), 0);
    erig_fill(&C);
    C.rows[2].phase = 7;
    CHECK_EQ_I64(t, events_init(&E, &C, NULL), 0);
    C.rows[2].phase = 8;
    CHECK_EQ_I64(t, events_init(&E, &C, NULL), -1);
    erig_fill(&C);
    C.rows[5].phase = 8; /* a row past n_rows is not read */
    CHECK_EQ_I64(t, events_init(&E, &C, NULL), 0);
}

static void t_an_engine_not_started_refuses_everything(ctest_t *t) {
    static events_t cold; /* zeroed */
    sim_rec_t rec = {{'e', 'v'}, 5, 1, 0, NULL, 0};
    CHECK_EQ_I64(t, events_feed(&cold, &rec), -1);
    CHECK_EQ_I64(t, events_power_cut(&cold, 5), -1);
    CHECK_EQ_I64(t, events_restarted(&cold, 5), -1);
    CHECK_EQ_I64(t, events_finish(&cold, 5), -1);
    erig_fill(&C);
    C.n_auth = 0;
    CHECK_EQ_I64(t, events_init(&cold, &C, NULL), -1);
    CHECK_EQ_I64(t, events_feed(&cold, &rec), -1);
    CHECK_EQ_I64(t, events_power_cut(NULL, 5), -1);
    CHECK_EQ_I64(t, events_feed(NULL, &rec), -1);
}

static void t_malformed_records_change_nothing(ctest_t *t) {
    begin(t);
    erig_ev_bare(&R, 100, T_STAGED);
    sim_rec_t bad = {{'e', 'v'}, 100, T_STAGED, 0, NULL, 3};
    CHECK_EQ_I64(t, events_feed(&E, &bad), -1);
    bad.len = 1;
    CHECK_EQ_I64(t, events_feed(&E, &bad), -1);
    CHECK_EQ_I64(t, events_feed(&E, NULL), -1);
    sim_rec_t back = {{'e', 'v'}, 99, T_STAGED, 0, NULL, 0};
    CHECK_EQ_I64(t, events_feed(&E, &back), -1);
    CHECK_EQ_U64(t, events_counts(&E).records, 1);
    CHECK_EQ_U64(t, events_counts(&E).auth_events, 1);
    sim_rec_t same = {{'e', 'v'}, 100, T_STAGED, 0, NULL, 0}; /* equal time is in order */
    CHECK_EQ_I64(t, events_feed(&E, &same), 0);
    CHECK_EQ_U64(t, events_counts(&E).records, 2);
}

static void t_findings_are_capped_at_16_and_counted(ctest_t *t) {
    begin(t);
    for (uint32_t k = 0; k < 20U; k++) {
        erig_flash(&R, 100U + k, 3); /* each is a pulse without an opening */
    }
    CHECK_EQ_U64(t, events_finding_count(&E), 20);
    CHECK_EQ_U64(t, events_dropped(&E), 4);
    CHECK(t, events_finding(&E, 15) != NULL);
    CHECK(t, events_finding(&E, 16) == NULL);
    CHECK(t, events_finding(&E, 19) == NULL);
    CHECK_EQ_U64(t, events_finding(&E, 15)->record, 15);
    CHECK_EQ_U64(t, events_inv_mask(&E), 1U << EV_I1);
}

static void t_the_invariant_queries(ctest_t *t) {
    begin(t);
    erig_ev_bare(&R, 50, T_BOOT);
    CHECK(t, !events_has_inv(&E, EV_I1));
    CHECK(t, !events_has_rule(&E, EV_R_NO_AUTH));
    erig_effect(&R, 100, 1, 84);
    CHECK(t, events_has_inv(&E, EV_I1));
    CHECK(t, !events_has_inv(&E, EV_I2));
    CHECK(t, !events_has_inv(&E, EV_I10));
    CHECK(t, !events_has_inv(&E, EV_I15));
    CHECK(t, events_has_rule(&E, EV_R_NO_AUTH));
    CHECK(t, !events_has_rule(&E, EV_R_EXTRA_PULSE));
    CHECK(t, !events_has_rule(&E, EV_R_COUNT)); /* out of range, no crash */
    CHECK(t, !events_has_inv(&E, (events_inv_t)40));
    CHECK_EQ_U64(t, events_inv_mask(&E), 1U << EV_I1);
}

static void t_names_for_the_report(ctest_t *t) {
    CHECK_EQ_STR(t, events_inv_name(EV_I1), "I1");
    CHECK_EQ_STR(t, events_inv_name(EV_I2), "I2");
    CHECK_EQ_STR(t, events_inv_name(EV_I9), "I9");
    CHECK_EQ_STR(t, events_inv_name(EV_I10), "I10");
    CHECK_EQ_STR(t, events_inv_name(EV_I15), "I15");
    CHECK(t, events_inv_name((events_inv_t)3) == NULL);
    CHECK(t, events_rule_name((events_rule_t)0) == NULL);
    CHECK(t, events_rule_name(EV_R_COUNT) == NULL);
    CHECK(t, events_rule_name((events_rule_t)-1) == NULL);
    CHECK_EQ_I64(t, events_rule_inv((events_rule_t)0), 0);
    CHECK_EQ_I64(t, events_rule_inv(EV_R_COUNT), 0);
    static const char *const names[] = {
        "no-authorisation", "open-overlap", "corr-reused", "bad-payload", "handover-without-effect", "pulse-without-open",
        "extra-pulse", "not-durable", "book-undecodable", "crash-book-changed", "crash-book-unreadable", "crash-audit-format",
        "crash-audit-gap", "open-before-boot", "audit-format", "audit-gap", "audit-bound", "door-without-assignment",
        "door-without-open", "short-locker", "locker-table-full", "stuck-phase", "no-recovery", "not-idle-at-end"};
    CHECK_EQ_U64(t, sizeof names / sizeof names[0], (uint32_t)EV_R_COUNT - 1U);
    for (uint32_t r = 1; r < (uint32_t)EV_R_COUNT; r++) {
        CHECK_EQ_STR(t, events_rule_name((events_rule_t)r), names[r - 1U]);
        CHECK(t, events_inv_name(events_rule_inv((events_rule_t)r)) != NULL);
    }
    /* the invariant of each rule, pinned: the order of the enum is the order of the table */
    static const events_inv_t want[] = {EV_I1, EV_I1, EV_I1, EV_I1, EV_I1, EV_I1, EV_I1, EV_I2, EV_I2, EV_I9, EV_I9, EV_I9, EV_I9, EV_I9,
                                        EV_I10, EV_I10, EV_I10, EV_I10, EV_I10, EV_I10, EV_I10, EV_I15, EV_I15, EV_I15};
    CHECK_EQ_U64(t, sizeof want / sizeof want[0], (uint32_t)EV_R_COUNT - 1U);
    for (uint32_t r = 1; r < (uint32_t)EV_R_COUNT; r++) {
        CHECK_EQ_I64(t, events_rule_inv((events_rule_t)r), want[r - 1U]);
    }
}

CTEST_SUITE("ev_live",
    { "limit_boundary", t_a_phase_may_last_its_limit_and_no_more },
    { "late_change", t_a_late_change_out_of_the_phase_is_still_late },
    { "own_timer", t_every_entry_starts_its_own_timer },
    { "repeat_no_restart", t_a_repeat_of_the_phase_does_not_restart_the_timer },
    { "no_limit", t_a_phase_without_a_limit_never_sticks },
    { "row_selectors", t_the_phase_comes_from_the_kind_and_the_type_of_a_record },
    { "first_row_wins", t_the_first_matching_row_wins },
    { "n_rows", t_only_the_configured_rows_are_read },
    { "end_idle", t_the_run_must_end_idle },
    { "other_kinds_time", t_other_record_kinds_advance_time_too },
    { "recovery_deadline", t_welcome_must_come_after_the_relay_clears },
    { "recovery_welcome", t_reaching_welcome_clears_the_deadline },
    { "recovery_at_welcome", t_no_deadline_when_already_at_welcome },
    { "recovery_moves", t_a_relay_clear_sets_its_deadline_from_its_own_time },
    { "recovery_flag", t_the_recovery_rule_needs_its_flag_and_its_selector },
    { "welcome_other", t_welcome_may_be_another_phase },
    { "bad_cfg", t_bad_configurations_are_refused },
    { "chain_phase_cfg", t_chain_and_phase_configurations_are_checked },
    { "not_started", t_an_engine_not_started_refuses_everything },
    { "malformed", t_malformed_records_change_nothing },
    { "cap_16", t_findings_are_capped_at_16_and_counted },
    { "queries", t_the_invariant_queries },
    { "names", t_names_for_the_report })
