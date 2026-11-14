/* The fixture product: the correct model is green over 200 seeds; each seeded bug is red with the exact rule and record. */
#include "sim/inv/tests/ui_model.h"
#include "sim/inv/tests/ui_rig.h"

static ui_t U;

static void t_the_correct_kiosk_is_green_over_200_seeds(ctest_t *t) {
    uint32_t notices = 0;
    uint32_t dismissed = 0;
    uint32_t expired = 0;
    for (uint64_t seed = 0; seed < 200U; seed++) {
        umodel_out_t out = {0};
        CHECK_EQ_I64(t, umodel_run(&U, seed, UMODEL_CORRECT, &out), 0);
        CHECK_EQ_U64(t, ui_finding_count(&U), 0);
        ui_counts_t c = ui_counts(&U);
        CHECK_EQ_U64(t, c.notices, out.notices);
        CHECK_EQ_U64(t, c.dismissed, out.dismissed);
        CHECK_EQ_U64(t, c.expired, out.expired);
        CHECK_EQ_U64(t, c.i8_checks, out.notices);
        CHECK(t, c.lang_checks >= out.visits);
        CHECK(t, out.visits >= 3U && out.visits <= 5U);
        CHECK(t, c.views > 50U);
        notices += out.notices;
        dismissed += out.dismissed;
        expired += out.expired;
    }
    CHECK(t, dismissed >= 150U && expired >= 100U);
    CHECK_EQ_U64(t, notices, dismissed + expired);
}

static void t_the_seeds_make_different_days(ctest_t *t) {
    umodel_out_t a = {0};
    umodel_out_t b = {0};
    uint32_t differ = 0;
    for (uint64_t seed = 0; seed < 20U; seed++) {
        CHECK_EQ_I64(t, umodel_run(&U, seed, UMODEL_CORRECT, &a), 0);
        CHECK_EQ_I64(t, umodel_run(&U, seed + 1U, UMODEL_CORRECT, &b), 0);
        differ += a.end_ms != b.end_ms ? 1U : 0U;
    }
    CHECK(t, differ >= 15U);
}

static void bug_is_found(ctest_t *t, umodel_bug_t bug, ui_rule_t rule, uint32_t findings) {
    for (uint64_t seed = 0; seed < 200U; seed++) {
        umodel_out_t out = {0};
        CHECK_EQ_I64(t, umodel_run(&U, seed, bug, &out), 0);
        const ui_finding_t *f = ui_finding(&U, 0);
        CHECK(t, f != NULL);
        if (f != NULL) {
            CHECK_EQ_U64(t, f->rule, rule);
            CHECK_EQ_U64(t, f->inv, ui_rule_inv(rule));
            CHECK_EQ_U64(t, f->record, out.bug_record);
        }
        CHECK(t, findings == 0U ? ui_finding_count(&U) >= 1U : ui_finding_count(&U) == findings);
    }
}

static void t_a_message_that_is_a_screen_is_found_at_its_view(ctest_t *t) {
    bug_is_found(t, UMODEL_FULL_SCREEN_MESSAGE, UI_R_FULL_SCREEN, 1);
}

static void t_a_notice_with_no_dismiss_is_found_at_its_view(ctest_t *t) {
    bug_is_found(t, UMODEL_NOTICE_WITHOUT_DISMISS, UI_R_NO_DISMISS, 1);
}

static void t_a_timeout_with_no_countdown_is_found_when_the_notice_clears(ctest_t *t) {
    bug_is_found(t, UMODEL_COUNTDOWN_NULL, UI_R_TIMEOUT_NO_COUNTDOWN, 1);
}

static void t_a_language_that_stays_is_found_at_the_first_idle_view_past_the_time(ctest_t *t) {
    bug_is_found(t, UMODEL_LANG_NOT_RESET, UI_R_LANG_NOT_RESET, 0);
}

static void t_a_dismiss_that_does_nothing_is_found_by_the_rerun(ctest_t *t) {
    for (uint64_t seed = 0; seed < 200U; seed++) {
        umodel_out_t out = {0};
        CHECK_EQ_I64(t, umodel_run(&U, seed, UMODEL_DISMISS_IGNORED, &out), 0);
        CHECK_EQ_U64(t, ui_finding_count(&U), out.notices); /* one per notice: the trace itself is fine */
        const ui_finding_t *f = ui_finding(&U, 0);
        CHECK(t, f != NULL);
        if (f != NULL) {
            CHECK_EQ_U64(t, f->rule, UI_R_DISMISS_KEPT);
            CHECK_EQ_U64(t, f->inv, UI_I8);
            CHECK_EQ_U64(t, f->record, out.bug_record);
        }
        CHECK_EQ_U64(t, ui_has_inv(&U, UI_I7), 0);
    }
}

CTEST_SUITE("ui_model",
    { "correct_200", t_the_correct_kiosk_is_green_over_200_seeds },
    { "seeds_differ", t_the_seeds_make_different_days },
    { "full_screen_message", t_a_message_that_is_a_screen_is_found_at_its_view },
    { "notice_without_dismiss", t_a_notice_with_no_dismiss_is_found_at_its_view },
    { "countdown_null", t_a_timeout_with_no_countdown_is_found_when_the_notice_clears },
    { "lang_not_reset", t_a_language_that_stays_is_found_at_the_first_idle_view_past_the_time },
    { "dismiss_ignored", t_a_dismiss_that_does_nothing_is_found_by_the_rerun })
