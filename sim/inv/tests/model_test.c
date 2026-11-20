/* The fixture product: the correct model is green over 200 seeds; each seeded bug is red with the exact invariant, rule and step. */
#include "sim/inv/tests/ev_rig.h"
#include "sim/inv/tests/model.h"

static events_t E;

static void t_the_correct_kiosk_is_green_over_200_seeds(ctest_t *t) {
    uint32_t cuts = 0;
    uint32_t visits = 0;
    for (uint64_t seed = 0; seed < 200U; seed++) {
        model_out_t out = {0};
        CHECK_EQ_I64(t, model_run(&E, seed, MODEL_CORRECT, &out), 0);
        CHECK_EQ_U64(t, events_finding_count(&E), 0);
        CHECK_EQ_U64(t, events_inv_mask(&E), 0);
        events_counts_t c = events_counts(&E);
        CHECK_EQ_U64(t, c.opens, out.visits);
        CHECK_EQ_U64(t, c.handovers, out.visits);
        CHECK_EQ_U64(t, c.flashes, 2U * out.visits);
        CHECK_EQ_U64(t, c.i2_checks, 2U * out.visits);
        CHECK_EQ_U64(t, c.doors, out.visits);
        CHECK_EQ_U64(t, c.durable_saves, out.visits);
        CHECK_EQ_U64(t, c.power_cuts, out.cuts);
        CHECK_EQ_U64(t, c.audit_lines, out.visits);
        cuts += out.cuts;
        visits += out.visits;
    }
    CHECK(t, cuts >= 60U && cuts <= 70U); /* seeds divisible by 3 */
    CHECK(t, visits >= 800U);
}

static void t_the_seeds_make_different_days(ctest_t *t) {
    model_out_t a = {0};
    model_out_t b = {0};
    uint32_t differ = 0;
    for (uint64_t seed = 0; seed < 20U; seed++) {
        CHECK_EQ_I64(t, model_run(&E, seed, MODEL_CORRECT, &a), 0);
        CHECK_EQ_I64(t, model_run(&E, seed + 1U, MODEL_CORRECT, &b), 0);
        differ += a.end_ms != b.end_ms ? 1U : 0U;
    }
    CHECK(t, differ >= 15U);
}

static void t_the_double_pulse_is_found_at_the_stale_effect(ctest_t *t) {
    for (uint64_t seed = 0; seed < 200U; seed++) {
        model_out_t out = {0};
        CHECK_EQ_I64(t, model_run(&E, seed, MODEL_DOUBLE_PULSE, &out), 0);
        CHECK_EQ_U64(t, events_finding_count(&E), 1);
        const events_finding_t *f = events_finding(&E, 0);
        CHECK(t, f != NULL);
        if (f != NULL) {
            CHECK_EQ_U64(t, f->inv, EV_I1);
            CHECK_EQ_U64(t, f->rule, EV_R_NO_AUTH);
            CHECK_EQ_U64(t, f->record, out.bug_record);
        }
    }
}

static void t_a_pulse_before_the_durable_save_is_found_at_the_first_flash(ctest_t *t) {
    for (uint64_t seed = 0; seed < 200U; seed++) {
        model_out_t out = {0};
        CHECK_EQ_I64(t, model_run(&E, seed, MODEL_NO_SAVE_BEFORE_OPEN, &out), 0);
        const events_finding_t *f = events_finding(&E, 0);
        CHECK(t, f != NULL);
        if (f != NULL) {
            CHECK_EQ_U64(t, f->inv, EV_I2);
            CHECK_EQ_U64(t, f->rule, EV_R_NOT_DURABLE);
            CHECK_EQ_U64(t, f->record, out.bug_record); /* the first flash after the hand-over */
        }
        CHECK_EQ_U64(t, events_finding_count(&E), 2); /* the row coil and the column coil */
        CHECK_EQ_U64(t, events_inv_mask(&E), 1U << EV_I2);
    }
}

static void t_a_screen_never_left_is_found_when_its_timer_runs_out(ctest_t *t) {
    for (uint64_t seed = 0; seed < 200U; seed++) {
        model_out_t out = {0};
        CHECK_EQ_I64(t, model_run(&E, seed, MODEL_STUCK_PHASE, &out), 0);
        const events_finding_t *f = events_finding(&E, 0);
        CHECK(t, f != NULL);
        if (f != NULL) {
            CHECK_EQ_U64(t, f->inv, EV_I15);
            CHECK_EQ_U64(t, f->rule, EV_R_STUCK_PHASE);
            CHECK_EQ_U64(t, f->record, out.bug_record);
        }
        CHECK(t, events_has_rule(&E, EV_R_NOT_IDLE_AT_END));
        CHECK_EQ_U64(t, events_finding_count(&E), 2);
    }
}

CTEST_SUITE("ev_model",
    { "correct_200", t_the_correct_kiosk_is_green_over_200_seeds },
    { "seeds_differ", t_the_seeds_make_different_days },
    { "double_pulse", t_the_double_pulse_is_found_at_the_stale_effect },
    { "no_save", t_a_pulse_before_the_durable_save_is_found_at_the_first_flash },
    { "stuck_phase", t_a_screen_never_left_is_found_when_its_timer_runs_out })
