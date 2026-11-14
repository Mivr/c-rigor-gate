/* I1: one opening per authorisation, the unique corr, one opening in flight, and no pulse without a hand-over. */
#include <string.h>

#include "sim/inv/frame.h"
#include "sim/inv/tests/ev_rig.h"

static events_cfg_t C;
static events_t E;
static rig_world_t W;
static erig_t R;

static void start(ctest_t *t, const events_cfg_t *cfg) {
    erig_start(&R, t, &E, &W, cfg, 1);
    erig_ev_bare(&R, 1, T_BOOT);
}

static void begin(ctest_t *t) {
    erig_fill(&C);
    start(t, &C);
}

static void t_clean_visits_pass(ctest_t *t) {
    begin(t);
    erig_visit(&R, 100, 1, 84);
    erig_visit(&R, 2000, 2, 83);
    erig_visit(&R, 4000, 3, 84);
    CHECK_EQ_U64(t, events_finding_count(&E), 0);
    CHECK_EQ_U64(t, events_inv_mask(&E), 0);
    events_counts_t c = events_counts(&E);
    CHECK_EQ_U64(t, c.auth_events, 3);
    CHECK_EQ_U64(t, c.opens, 3);
    CHECK_EQ_U64(t, c.handovers, 3);
    CHECK_EQ_U64(t, c.flashes, 6);
    CHECK_EQ_U64(t, c.records, 1 + 3 * 6);
}

static void t_double_pulse_is_found_at_the_second_effect(ctest_t *t) {
    begin(t);
    erig_visit(&R, 100, 1, 84);              /* records 1 to 6 */
    erig_effect(&R, 900, 2, 84);             /* record 7: no new staged */
    CHECK_EQ_U64(t, events_finding_count(&E), 1);
    CHECK(t, erig_finding_is(&R, 0, EV_I1, EV_R_NO_AUTH, 7));
    CHECK_EQ_U64(t, events_finding(&E, 0)->t_ms, 900);
    CHECK(t, events_has_inv(&E, EV_I1));
    CHECK(t, !events_has_rule(&E, EV_R_OPEN_OVERLAP));
}

static void t_a_stale_second_effect_before_the_result_is_overlap_and_unpaid(ctest_t *t) {
    begin(t);
    erig_ev(&R, 100, T_STAGED, 1, 84);
    erig_effect(&R, 110, 1, 84);
    erig_effect(&R, 120, 2, 84);
    CHECK(t, events_has_rule(&E, EV_R_OPEN_OVERLAP));
    CHECK(t, events_has_rule(&E, EV_R_NO_AUTH));
    CHECK_EQ_U64(t, events_finding_count(&E), 2);
}

static void t_two_authorisations_pay_for_two_effects(ctest_t *t) {
    begin(t);
    erig_ev(&R, 100, T_STAGED, 1, 84);
    erig_ev(&R, 101, T_SHIFT, 2, 84);
    erig_effect(&R, 110, 1, 84);
    erig_ev(&R, 120, T_RESULT, 1, 84);
    erig_effect(&R, 130, 2, 84);
    CHECK_EQ_U64(t, events_finding_count(&E), 0);
    erig_ev(&R, 140, T_RESULT, 2, 84);
    erig_effect(&R, 150, 3, 84);
    CHECK(t, erig_finding_is(&R, 0, EV_I1, EV_R_NO_AUTH, 7));
}

static void t_only_configured_events_authorise(ctest_t *t) {
    erig_fill(&C);
    C.n_auth = 1; /* the shift event is in the table but not in use */
    start(t, &C);
    erig_ev(&R, 100, T_SHIFT, 1, 84);
    erig_effect(&R, 110, 1, 84);
    CHECK(t, events_has_rule(&E, EV_R_NO_AUTH));
    C.n_auth = 2;
    start(t, &C);
    erig_ev(&R, 100, T_SHIFT, 1, 84);
    erig_effect(&R, 110, 1, 84);
    CHECK_EQ_U64(t, events_finding_count(&E), 0);
    erig_ev(&R, 120, 99, 2, 84); /* an unrelated event pays for nothing */
    erig_ev(&R, 130, T_RESULT, 1, 84);
    erig_effect(&R, 140, 2, 84);
    CHECK(t, events_has_rule(&E, EV_R_NO_AUTH));
}

static void t_a_payment_is_spent_once_per_effect(ctest_t *t) {
    begin(t);
    erig_ev(&R, 100, T_STAGED, 1, 84);
    erig_ev(&R, 101, T_STAGED, 2, 84);
    erig_ev(&R, 102, T_STAGED, 3, 84);
    for (uint32_t k = 1; k <= 3; k++) {
        erig_effect(&R, 110U * k, k, 84);
        erig_ev(&R, 110U * k + 5U, T_RESULT, k, 84);
    }
    CHECK_EQ_U64(t, events_finding_count(&E), 0);
    erig_effect(&R, 900, 4, 84);
    CHECK_EQ_U64(t, events_finding_count(&E), 1);
}

static void t_corr_must_be_unique(ctest_t *t) {
    begin(t);
    erig_visit(&R, 100, 7, 84);
    erig_visit(&R, 2000, 8, 84);
    CHECK_EQ_U64(t, events_finding_count(&E), 0);
    erig_visit(&R, 4000, 7, 84);
    CHECK_EQ_U64(t, events_finding_count(&E), 1);
    CHECK(t, erig_finding_is(&R, 0, EV_I1, EV_R_CORR_REUSED, 14));
}

static void t_the_shared_corr_is_exempt_only_when_configured(ctest_t *t) {
    begin(t);
    erig_visit(&R, 100, 0xfffe, 84);
    erig_visit(&R, 2000, 0xfffe, 84);
    CHECK_EQ_U64(t, events_finding_count(&E), 0);
    erig_fill(&C);
    C.has_corr_shared = 0;
    start(t, &C);
    erig_visit(&R, 100, 0xfffe, 84);
    erig_visit(&R, 2000, 0xfffe, 84);
    CHECK(t, events_has_rule(&E, EV_R_CORR_REUSED));
    C.has_corr_shared = 1;
    C.corr_shared = 0;
    start(t, &C);
    erig_visit(&R, 100, 0, 84);
    erig_visit(&R, 2000, 0, 84);
    CHECK_EQ_U64(t, events_finding_count(&E), 0);
}

static void t_corr_memory_is_the_last_256(ctest_t *t) {
    begin(t);
    for (uint32_t k = 0; k < 256U; k++) { /* corr 1000 and 255 more: all 256 slots in use */
        erig_visit(&R, 10000U + 1000U * k, 1000U + k, 84);
    }
    CHECK_EQ_U64(t, events_finding_count(&E), 0);
    erig_visit(&R, 400000, 1000, 84); /* the oldest is still remembered */
    CHECK_EQ_U64(t, events_finding_count(&E), 1);
    CHECK(t, events_has_rule(&E, EV_R_CORR_REUSED));
    erig_visit(&R, 420000, 1100, 84); /* one from the middle of the memory */
    CHECK_EQ_U64(t, events_finding_count(&E), 2);
    begin(t); /* 257 corrs: the first is gone */
    for (uint32_t k = 0; k < 257U; k++) {
        erig_visit(&R, 10000U + 1000U * k, 1000U + k, 84);
    }
    erig_visit(&R, 400000, 1000, 84);
    CHECK_EQ_U64(t, events_finding_count(&E), 0);
    erig_visit(&R, 420000, 1002, 84); /* the ring went on: a later corr is still remembered */
    CHECK_EQ_U64(t, events_finding_count(&E), 1);
    erig_visit(&R, 440000, 1256, 84); /* the newest of the first lap, in slot 0 */
    CHECK_EQ_U64(t, events_finding_count(&E), 2);
    erig_visit(&R, 460000, 1500, 84);
    CHECK_EQ_U64(t, events_finding_count(&E), 2);
    CHECK(t, erig_finding_is(&R, 1, EV_I1, EV_R_CORR_REUSED, 1U + 259U * 6U + 1U));
}

static void t_a_short_effect_payload_is_a_finding(ctest_t *t) {
    begin(t);
    erig_ev(&R, 100, T_STAGED, 1, 84);
    static const uint8_t three[3] = {1, 0, 0};
    erig_rec(&R, "fx", 110, T_FX_OPEN, 5, three, 3);
    CHECK(t, erig_finding_is(&R, 0, EV_I1, EV_R_BAD_PAYLOAD, 2));
    erig_ev(&R, 120, T_STAGED, 2, 84);
    static const uint8_t four[4] = {2, 0, 0, 0}; /* exactly the corr: long enough for the corr, too short for the locker */
    erig_rec(&R, "fx", 130, T_FX_OPEN, 5, four, 4);
    CHECK(t, !events_has_rule(&E, EV_R_CORR_REUSED));
    CHECK(t, events_has_rule(&E, EV_R_SHORT_LOCKER));
}

static void t_a_payload_exactly_as_long_as_the_corr_is_enough(ctest_t *t) {
    erig_fill(&C);
    C.has_chain = 0;
    start(t, &C);
    static const uint8_t four[4] = {7, 0, 0, 0};
    erig_ev(&R, 100, T_STAGED, 7, 84);
    erig_rec(&R, "fx", 110, T_FX_OPEN, 5, four, 4);
    erig_rec(&R, "ev", 120, T_RESULT, 0, four, 4);
    erig_ev(&R, 130, T_STAGED, 8, 84);
    static const uint8_t other[4] = {8, 0, 0, 0};
    erig_rec(&R, "fx", 140, T_FX_OPEN, 5, other, 4);
    CHECK_EQ_U64(t, events_finding_count(&E), 0); /* the result matched, nothing is in flight */
}

static void t_an_unreadable_corr_accepts_the_next_result(ctest_t *t) {
    begin(t);
    erig_visit(&R, 100, 1, 84);
    erig_ev(&R, 1000, T_STAGED, 2, 84);
    static const uint8_t three[3] = {2, 0, 0};
    erig_rec(&R, "fx", 1010, T_FX_OPEN, 5, three, 3); /* no corr to remember: the stale one of visit 1 must not be used */
    erig_ev(&R, 1020, T_RESULT, 2, 84);
    erig_ev(&R, 1030, T_STAGED, 3, 84);
    erig_effect(&R, 1040, 3, 84);
    CHECK(t, !events_has_rule(&E, EV_R_OPEN_OVERLAP));
}

static void t_a_payload_over_32_bytes_is_a_finding(ctest_t *t) {
    erig_fill(&C);
    C.has_chain = 0;
    start(t, &C);
    uint8_t big[33] = {1};
    erig_ev(&R, 100, T_STAGED, 1, 84);
    erig_rec(&R, "fx", 110, T_FX_OPEN, 5, big, 32);
    CHECK_EQ_U64(t, events_finding_count(&E), 0);
    erig_ev(&R, 120, T_RESULT, 1, 84);
    erig_ev(&R, 130, T_STAGED, 2, 84);
    big[0] = 2;
    erig_rec(&R, "fx", 140, T_FX_OPEN, 5, big, 33);
    CHECK(t, erig_finding_is(&R, 0, EV_I1, EV_R_BAD_PAYLOAD, 5));
}

static void t_the_result_must_carry_the_corr_of_its_opening(ctest_t *t) {
    begin(t);
    erig_ev(&R, 100, T_STAGED, 1, 84);
    erig_effect(&R, 110, 1, 84);
    erig_ev(&R, 120, T_RESULT, 99, 84); /* an earlier opening's result: ignored, the opening is still in flight */
    erig_ev(&R, 130, T_STAGED, 2, 84);
    erig_effect(&R, 140, 2, 84);
    CHECK(t, events_has_rule(&E, EV_R_OPEN_OVERLAP));
    uint32_t n = events_finding_count(&E);
    erig_ev(&R, 150, T_RESULT, 2, 84);
    erig_ev(&R, 160, T_STAGED, 3, 84);
    erig_effect(&R, 170, 3, 84);
    CHECK_EQ_U64(t, events_finding_count(&E), n);
}

static void t_a_short_result_payload_is_a_finding_and_changes_nothing(ctest_t *t) {
    begin(t);
    erig_ev(&R, 100, T_STAGED, 1, 84);
    erig_effect(&R, 110, 1, 84);
    erig_rec(&R, "ev", 120, T_RESULT, 0, NULL, 0);
    CHECK(t, erig_finding_is(&R, 0, EV_I1, EV_R_BAD_PAYLOAD, 3));
    erig_ev(&R, 130, T_STAGED, 2, 84);
    erig_effect(&R, 140, 2, 84);
    CHECK(t, events_has_rule(&E, EV_R_OPEN_OVERLAP));
}

static void t_a_stale_result_changes_nothing(ctest_t *t) {
    begin(t);
    erig_ev(&R, 100, T_RESULT, 5, 84); /* nothing is in flight */
    erig_visit(&R, 200, 1, 84);
    erig_ev(&R, 2000, T_RESULT, 1, 84); /* a second result of the finished opening */
    erig_visit(&R, 3000, 2, 84);
    CHECK_EQ_U64(t, events_finding_count(&E), 0);
}

static void t_without_corr_the_result_matches_by_type(ctest_t *t) {
    erig_fill(&C);
    C.corr_len = 0;
    C.has_chain = 0;
    start(t, &C);
    erig_ev(&R, 100, T_STAGED, 1, 84);
    erig_rec(&R, "fx", 110, T_FX_OPEN, 5, NULL, 0);
    erig_rec(&R, "ev", 120, T_RESULT, 0, NULL, 0);
    erig_ev(&R, 130, T_STAGED, 1, 84);
    erig_rec(&R, "fx", 140, T_FX_OPEN, 5, NULL, 0);
    CHECK_EQ_U64(t, events_finding_count(&E), 0);
}

static void t_a_handover_needs_an_effect(ctest_t *t) {
    begin(t);
    erig_handover(&R, 100, 1, 84);
    CHECK(t, erig_finding_is(&R, 0, EV_I1, EV_R_HANDOVER_NO_EFFECT, 1));
    erig_ev(&R, 110, T_STAGED, 1, 84);
    erig_effect(&R, 120, 1, 84);
    erig_handover(&R, 130, 1, 84);
    CHECK_EQ_U64(t, events_finding_count(&E), 1);
    erig_handover(&R, 140, 1, 84); /* one effect, two hand-overs */
    CHECK(t, erig_finding_is(&R, 1, EV_I1, EV_R_HANDOVER_NO_EFFECT, 5));
}

static void t_a_result_forgets_an_unhanded_effect(ctest_t *t) {
    begin(t);
    erig_ev(&R, 100, T_STAGED, 1, 84);
    erig_effect(&R, 110, 1, 84); /* the adapter refused: never handed over */
    erig_ev(&R, 120, T_RESULT, 1, 84);
    erig_handover(&R, 130, 1, 84);
    CHECK(t, events_has_rule(&E, EV_R_HANDOVER_NO_EFFECT));
}

static void t_a_pulse_needs_a_handover(ctest_t *t) {
    begin(t);
    erig_flash(&R, 100, 3);
    CHECK(t, erig_finding_is(&R, 0, EV_I1, EV_R_PULSE_NO_OPEN, 1));
    erig_ev(&R, 110, T_STAGED, 1, 84);
    erig_effect(&R, 120, 1, 84); /* an effect alone is not a hand-over */
    erig_flash(&R, 130, 3);
    CHECK(t, erig_finding_is(&R, 1, EV_I1, EV_R_PULSE_NO_OPEN, 4));
    erig_handover(&R, 140, 1, 84);
    erig_flash(&R, 150, 3);
    CHECK_EQ_U64(t, events_finding_count(&E), 2);
    erig_ev(&R, 160, T_RESULT, 1, 84);
    erig_flash(&R, 170, 3); /* after the result the window is closed */
    CHECK(t, erig_finding_is(&R, 2, EV_I1, EV_R_PULSE_NO_OPEN, 8));
}

static void t_too_many_pulses_for_one_handover(ctest_t *t) {
    begin(t);
    erig_ev(&R, 100, T_STAGED, 1, 84);
    erig_effect(&R, 110, 1, 84);
    erig_handover(&R, 120, 1, 84);
    erig_flash(&R, 130, 3);
    erig_flash(&R, 140, 3);
    CHECK_EQ_U64(t, events_finding_count(&E), 0);
    erig_flash(&R, 150, 3);
    CHECK(t, erig_finding_is(&R, 0, EV_I1, EV_R_EXTRA_PULSE, 6));
    erig_ev(&R, 160, T_STAGED, 2, 84);
    erig_ev(&R, 161, T_RESULT, 1, 84);
    erig_effect(&R, 170, 2, 84);
    erig_handover(&R, 180, 2, 84); /* a new hand-over starts the count again */
    erig_flash(&R, 190, 3);
    erig_flash(&R, 200, 3);
    CHECK_EQ_U64(t, events_finding_count(&E), 1);
    erig_fill(&C);
    C.flashes_per_open = 1;
    start(t, &C);
    erig_ev(&R, 100, T_STAGED, 1, 84);
    erig_effect(&R, 110, 1, 84);
    erig_handover(&R, 120, 1, 84);
    erig_flash(&R, 130, 3);
    CHECK_EQ_U64(t, events_finding_count(&E), 0);
    erig_flash(&R, 140, 3);
    CHECK(t, events_has_rule(&E, EV_R_EXTRA_PULSE));
}

static void t_only_flash_on_requests_are_pulses(ctest_t *t) {
    begin(t);
    uint8_t f[8];
    erig_read(&R, 10); /* a read of the coils */
    CHECK_EQ_U64(t, events_counts(&E).flashes, 0);
    static const uint16_t addrs[] = {0x01ff, 0x0200, 0x021d, 0x021e};
    static const uint32_t counted[] = {0, 1, 2, 2};
    for (uint32_t i = 0; i < 4U; i++) {
        f[0] = 1; f[1] = 5; f[2] = (uint8_t)(addrs[i] >> 8); f[3] = (uint8_t)addrs[i]; f[4] = 0; f[5] = 5;
        uint16_t crc = wire_crc16(f, 6);
        f[6] = (uint8_t)(crc & 0xffU);
        f[7] = (uint8_t)(crc >> 8);
        erig_rec(&R, "fr", 20U + i, 0, 0, f, 8);
        CHECK_EQ_U64(t, events_counts(&E).flashes, counted[i]);
    }
}

static void t_a_response_or_a_bad_frame_is_not_a_pulse(ctest_t *t) {
    begin(t);
    uint8_t f[8] = {1, 5, 2, 3, 0, 5, 0, 0};
    uint16_t crc = wire_crc16(f, 6);
    f[6] = (uint8_t)(crc & 0xffU);
    f[7] = (uint8_t)(crc >> 8);
    erig_rec(&R, "fr", 10, 1, 0, f, 8); /* the board's echo */
    CHECK_EQ_U64(t, events_counts(&E).flashes, 0);
    f[7] ^= 1U; /* bad CRC */
    erig_rec(&R, "fr", 20, 0, 0, f, 8);
    erig_rec(&R, "fr", 30, 0, 0, NULL, 0);
    CHECK_EQ_U64(t, events_counts(&E).flashes, 0);
    CHECK_EQ_U64(t, events_finding_count(&E), 0);
}

static void t_without_handover_the_effect_opens_the_window(ctest_t *t) {
    erig_fill(&C);
    C.has_handover = 0;
    start(t, &C);
    erig_ev(&R, 100, T_STAGED, 1, 84);
    erig_effect(&R, 110, 1, 84);
    erig_flash(&R, 120, 3);
    erig_flash(&R, 130, 3);
    CHECK_EQ_U64(t, events_finding_count(&E), 0);
    erig_flash(&R, 140, 3);
    CHECK(t, events_has_rule(&E, EV_R_EXTRA_PULSE));
    erig_ev(&R, 150, T_RESULT, 1, 84);
    erig_ev(&R, 160, T_STAGED, 2, 84);
    erig_rec(&R, "fx", 170, T_FX_OPEN, HANDOVER_B, NULL, 0); /* the same b is only an effect here */
    CHECK_EQ_U64(t, events_counts(&E).handovers, 0);
    CHECK_EQ_U64(t, events_counts(&E).opens, 2);
}

static void t_other_effects_are_ignored(ctest_t *t) {
    begin(t);
    erig_rec(&R, "fx", 100, T_FX_OPEN + 1U, 5, NULL, 0);
    erig_rec(&R, "fx", 110, T_FX_OPEN + 1U, HANDOVER_B, NULL, 0);
    CHECK_EQ_U64(t, events_finding_count(&E), 0);
    CHECK_EQ_U64(t, events_counts(&E).opens, 0);
    CHECK_EQ_U64(t, events_counts(&E).handovers, 0);
}

CTEST_SUITE("ev_auth",
    { "clean_visits_pass", t_clean_visits_pass },
    { "double_pulse", t_double_pulse_is_found_at_the_second_effect },
    { "overlap_and_unpaid", t_a_stale_second_effect_before_the_result_is_overlap_and_unpaid },
    { "two_authorisations", t_two_authorisations_pay_for_two_effects },
    { "configured_auth_only", t_only_configured_events_authorise },
    { "payment_spent_once", t_a_payment_is_spent_once_per_effect },
    { "corr_unique", t_corr_must_be_unique },
    { "shared_corr", t_the_shared_corr_is_exempt_only_when_configured },
    { "corr_memory", t_corr_memory_is_the_last_256 },
    { "short_effect", t_a_short_effect_payload_is_a_finding },
    { "exact_payload", t_a_payload_exactly_as_long_as_the_corr_is_enough },
    { "unreadable_corr", t_an_unreadable_corr_accepts_the_next_result },
    { "long_payload", t_a_payload_over_32_bytes_is_a_finding },
    { "result_corr", t_the_result_must_carry_the_corr_of_its_opening },
    { "short_result", t_a_short_result_payload_is_a_finding_and_changes_nothing },
    { "stale_result", t_a_stale_result_changes_nothing },
    { "result_by_type", t_without_corr_the_result_matches_by_type },
    { "handover_needs_effect", t_a_handover_needs_an_effect },
    { "result_forgets", t_a_result_forgets_an_unhanded_effect },
    { "pulse_needs_handover", t_a_pulse_needs_a_handover },
    { "too_many_pulses", t_too_many_pulses_for_one_handover },
    { "only_flash_on", t_only_flash_on_requests_are_pulses },
    { "response_or_bad_frame", t_a_response_or_a_bad_frame_is_not_a_pulse },
    { "no_handover_config", t_without_handover_the_effect_opens_the_window },
    { "other_effects", t_other_effects_are_ignored })
