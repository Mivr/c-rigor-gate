/* I8 through ui_feed and a scripted replay: the world is asked to re-run, dismiss and wait; the engine judges what comes back. */
#include <stdio.h>
#include <string.h>

#include "sim/inv/tests/ui_rig.h"

static ui_t U;
static urig_world_t W;
static urig_t R;
static char NOTICE[900];
static char GONE[900];
static char OTHER[900];

static void begin(ctest_t *t, uint32_t sample_every, uint32_t tick_ms) {
    ui_cfg_t c;
    urig_cfg(&c);
    c.sample_every = sample_every;
    c.tick_ms = tick_ms;
    urig_start(&R, t, &U, &W, &c, 3);
    snprintf(NOTICE, sizeof NOTICE, "%s", urig_welcome("bg", urig_notice("snackbar", "banner_sync", "reject_invalid", "8000"), ""));
    snprintf(GONE, sizeof GONE, "%s", urig_welcome("bg", "null", ""));
}


static void script(const char *dismiss, const char *wait_dismiss, const char *wait) {
    W.out[UI_REPLAY_DISMISS] = dismiss;
    W.out[UI_REPLAY_DISMISS_WAIT] = wait_dismiss;
    W.out[UI_REPLAY_WAIT] = wait;
}

static void t_a_notice_is_dismissed_and_the_world_is_asked_three_things(ctest_t *t) {
    begin(t, 1, 250);
    script(GONE, GONE, GONE);
    urig_vw(&R, 0, GONE);
    urig_ev(&R, 100, U_EV_OTHER);
    urig_vw(&R, 200, NOTICE);
    CHECK_EQ_U64(t, ui_finding_count(&U), 0);
    CHECK_EQ_U64(t, W.replay_calls, 3);
    CHECK_EQ_U64(t, W.modes[0], UI_REPLAY_DISMISS);
    CHECK_EQ_U64(t, W.modes[1], UI_REPLAY_DISMISS_WAIT);
    CHECK_EQ_U64(t, W.modes[2], UI_REPLAY_WAIT);
    for (uint32_t i = 0; i < 3U; i++) {
        CHECK_EQ_U64(t, W.records[i], 2); /* the record of the view, counting from 0 */
        CHECK_EQ_U64(t, W.dismisses[i], 3); /* banner_sync */
        CHECK_EQ_U64(t, W.caps[i], UI_VIEW_MAX);
    }
    CHECK_EQ_U64(t, W.advances[0], 250);
    CHECK_EQ_U64(t, W.advances[1], 8250);
    CHECK_EQ_U64(t, W.advances[2], 8250);
    CHECK_EQ_U64(t, ui_counts(&U).i8_checks, 1);
    CHECK_EQ_U64(t, ui_counts(&U).notices, 1);
    urig_vw(&R, 300, NOTICE); /* the same notice again: not asked again */
    CHECK_EQ_U64(t, W.replay_calls, 3);
    CHECK_EQ_U64(t, ui_counts(&U).i8_checks, 1);
}

static void t_the_tick_is_the_apps(ctest_t *t) {
    begin(t, 1, 40);
    script(GONE, GONE, GONE);
    urig_vw(&R, 0, NOTICE);
    CHECK_EQ_U64(t, W.advances[0], 40);
    CHECK_EQ_U64(t, W.advances[1], 8040);
    CHECK_EQ_U64(t, W.advances[2], 8040);
}

static void t_a_notice_without_a_countdown_is_asked_once(ctest_t *t) {
    begin(t, 1, 250);
    script(GONE, NULL, NULL);
    urig_vw(&R, 0, urig_welcome("bg", urig_notice("banner", "banner_sync", "reject_invalid", "null"), ""));
    CHECK_EQ_U64(t, W.replay_calls, 1);
    CHECK_EQ_U64(t, ui_finding_count(&U), 0);
    CHECK_EQ_U64(t, ui_counts(&U).i8_checks, 1);
}

static void t_a_countdown_of_one_millisecond_is_still_a_countdown(ctest_t *t) {
    begin(t, 1, 250);
    script(GONE, GONE, urig_welcome("en", "null", ""));
    urig_vw(&R, 0, urig_edit(NOTICE, "8000", "1"));
    CHECK_EQ_U64(t, W.replay_calls, 3);
    CHECK_EQ_U64(t, W.advances[1], 251);
    CHECK_EQ_U64(t, ui_finding_count(&U), 1);
    CHECK(t, urig_finding_is(&R, 0, UI_R_DISMISS_VS_EXPIRY, 0, 0));
}

static void t_a_notice_that_survives_its_dismiss_is_found(ctest_t *t) {
    begin(t, 1, 250);
    script(NOTICE, GONE, GONE);
    urig_vw(&R, 0, urig_edit(NOTICE, "8000", "7500")); /* the countdown is not the notice: it is the same notice */
    CHECK_EQ_U64(t, ui_finding_count(&U), 1);
    CHECK(t, urig_finding_is(&R, 0, UI_R_DISMISS_KEPT, 0, 0));
    CHECK(t, ui_has_inv(&U, UI_I8));
    CHECK(t, !ui_has_inv(&U, UI_I7));
    begin(t, 1, 250); /* another notice behind it is fine */
    snprintf(OTHER, sizeof OTHER, "%s", urig_welcome("bg", urig_notice("snackbar", "banner_sync", "reject_unknown", "8000"), ""));
    script(OTHER, GONE, GONE);
    urig_vw(&R, 0, NOTICE);
    CHECK_EQ_U64(t, ui_finding_count(&U), 0);
    begin(t, 1, 250); /* a notice that differs in any field, even its tone */
    script(urig_edit(NOTICE, "\"warning\":false", "\"warning\":true"), GONE, GONE);
    urig_vw(&R, 0, NOTICE);
    CHECK_EQ_U64(t, ui_finding_count(&U), 0);
}

static void t_the_screen_under_the_notice_stays(ctest_t *t) {
    begin(t, 1, 250);
    snprintf(OTHER, sizeof OTHER, "%s", urig_screen("choose", "bg", "\"sizes\":[]", "null", ""));
    script(OTHER, OTHER, OTHER);
    urig_vw(&R, 5, NOTICE);
    CHECK_EQ_U64(t, ui_finding_count(&U), 1);
    CHECK(t, urig_finding_is(&R, 0, UI_R_DISMISS_SCREEN, 5, 0));
    begin(t, 1, 250); /* both at once: the notice stayed and the screen changed */
    snprintf(OTHER, sizeof OTHER, "%s", urig_screen("choose", "bg", "\"sizes\":[]", urig_notice("snackbar", "banner_sync", "reject_invalid", "100"), ""));
    script(OTHER, GONE, GONE);
    urig_vw(&R, 5, NOTICE);
    CHECK_EQ_U64(t, ui_finding_count(&U), 2);
    CHECK(t, urig_finding_is(&R, 0, UI_R_DISMISS_KEPT, 5, 0));
    CHECK(t, urig_finding_is(&R, 1, UI_R_DISMISS_SCREEN, 5, 0));
}

static void t_dismissing_and_waiting_is_waiting(ctest_t *t) {
    begin(t, 1, 250);
    script(GONE, GONE, urig_welcome("en", "null", ""));
    urig_vw(&R, 0, NOTICE);
    CHECK_EQ_U64(t, ui_finding_count(&U), 1);
    CHECK(t, urig_finding_is(&R, 0, UI_R_DISMISS_VS_EXPIRY, 0, 0));
    begin(t, 1, 250); /* the same length, one byte apart */
    snprintf(OTHER, sizeof OTHER, "%s", urig_edit(GONE, "\"pad_len\":3", "\"pad_len\":4"));
    script(GONE, GONE, OTHER);
    urig_vw(&R, 0, NOTICE);
    CHECK_EQ_U64(t, ui_finding_count(&U), 1);
    begin(t, 1, 250); /* the last byte */
    snprintf(OTHER, sizeof OTHER, "%s", GONE);
    OTHER[strlen(OTHER) - 1U] = 'x';
    script(GONE, GONE, OTHER);
    urig_vw(&R, 0, NOTICE);
    CHECK_EQ_U64(t, ui_finding_count(&U), 1);
    begin(t, 1, 250); /* one longer */
    snprintf(OTHER, sizeof OTHER, "%s", urig_welcome("bg", "null", "{\"id\":\"sync\",\"phrase\":\"saved\",\"args\":{},\"warning\":false}"));
    script(GONE, OTHER, GONE);
    urig_vw(&R, 0, NOTICE);
    CHECK_EQ_U64(t, ui_finding_count(&U), 1);
    begin(t, 1, 250); /* a countdown that is not null on the notice but the replay views are both gone: equal */
    script(GONE, GONE, GONE);
    urig_vw(&R, 0, NOTICE);
    CHECK_EQ_U64(t, ui_finding_count(&U), 0);
}

static void t_a_replay_that_fails_is_a_finding_and_stops_the_checks(ctest_t *t) {
    begin(t, 1, 250);
    script(GONE, GONE, GONE);
    W.rc[UI_REPLAY_DISMISS] = -1;
    urig_vw(&R, 3, NOTICE);
    CHECK_EQ_U64(t, ui_finding_count(&U), 1);
    CHECK(t, urig_finding_is(&R, 0, UI_R_REPLAY_FAILED, 3, 0));
    CHECK_EQ_U64(t, W.replay_calls, 1);
    CHECK(t, ui_has_inv(&U, UI_I8));
    begin(t, 1, 250); /* a view that is not one */
    script("{}", GONE, GONE);
    urig_vw(&R, 3, NOTICE);
    CHECK_EQ_U64(t, ui_finding_count(&U), 1);
    CHECK(t, urig_finding_is(&R, 0, UI_R_REPLAY_FAILED, 3, 0));
    CHECK_EQ_U64(t, W.replay_calls, 1);
    begin(t, 1, 250); /* no text at all */
    script(NULL, GONE, GONE);
    urig_vw(&R, 3, NOTICE);
    CHECK(t, urig_finding_is(&R, 0, UI_R_REPLAY_FAILED, 3, 0));
    begin(t, 1, 250); /* a length the world cannot have written */
    script(GONE, GONE, GONE);
    W.forced_len[UI_REPLAY_DISMISS] = UI_VIEW_MAX + 1U;
    urig_vw(&R, 3, NOTICE);
    CHECK_EQ_U64(t, ui_finding_count(&U), 1);
    CHECK(t, urig_finding_is(&R, 0, UI_R_REPLAY_FAILED, 3, 0));
    begin(t, 1, 250); /* the second and third runs */
    script(GONE, GONE, GONE);
    W.rc[UI_REPLAY_DISMISS_WAIT] = -3;
    urig_vw(&R, 3, NOTICE);
    CHECK_EQ_U64(t, ui_finding_count(&U), 1);
    CHECK(t, urig_finding_is(&R, 0, UI_R_REPLAY_FAILED, 3, 0));
    CHECK_EQ_U64(t, W.replay_calls, 2);
    begin(t, 1, 250);
    script(GONE, GONE, GONE);
    W.rc[UI_REPLAY_WAIT] = -1;
    urig_vw(&R, 3, NOTICE);
    CHECK_EQ_U64(t, ui_finding_count(&U), 1);
    CHECK_EQ_U64(t, W.replay_calls, 3);
    begin(t, 1, 250);
    script(GONE, "[]", GONE);
    urig_vw(&R, 3, NOTICE);
    CHECK_EQ_U64(t, ui_finding_count(&U), 1);
    CHECK_EQ_U64(t, W.replay_calls, 2);
    begin(t, 1, 250);
    script(GONE, GONE, "[]");
    urig_vw(&R, 3, NOTICE);
    CHECK_EQ_U64(t, ui_finding_count(&U), 1);
    CHECK_EQ_U64(t, W.replay_calls, 3);
}

static void t_only_every_nth_notice_is_checked(ctest_t *t) {
    static char n[4][900];
    begin(t, 3, 250);
    script(GONE, NULL, NULL);
    for (uint32_t i = 0; i < 4U; i++) {
        const char *phrases[4] = {"reject_invalid", "reject_unknown", "saved", "not_saved"};
        snprintf(n[i], sizeof n[i], "%s", urig_welcome("bg", urig_notice("banner", "overlay", phrases[i], "null"), ""));
    }
    urig_vw(&R, 0, n[0]); /* notice 0: checked */
    CHECK_EQ_U64(t, W.replay_calls, 1);
    urig_vw(&R, 1, n[0]);
    urig_vw(&R, 2, n[1]); /* 1 */
    urig_vw(&R, 3, n[2]); /* 2 */
    CHECK_EQ_U64(t, W.replay_calls, 1);
    urig_vw(&R, 4, n[3]); /* 3: checked */
    CHECK_EQ_U64(t, W.replay_calls, 2);
    CHECK_EQ_U64(t, W.records[1], 4);
    urig_vw(&R, 5, GONE);
    urig_vw(&R, 6, n[0]); /* 4 */
    urig_vw(&R, 7, n[1]); /* 5 */
    urig_vw(&R, 8, n[2]); /* 6: checked */
    CHECK_EQ_U64(t, W.replay_calls, 3);
    CHECK_EQ_U64(t, W.records[2], 8);
    CHECK_EQ_U64(t, ui_counts(&U).i8_checks, 3);
    CHECK_EQ_U64(t, ui_counts(&U).notices, 7);
    CHECK_EQ_U64(t, ui_finding_count(&U), 0);
}

static void t_i8_needs_a_replay_and_a_sample_rate(ctest_t *t) {
    ui_cfg_t c;
    begin(t, 1, 250);
    script(GONE, GONE, GONE);
    urig_cfg(&c);
    c.sample_every = 0;
    c.tick_ms = 0;
    urig_start(&R, t, &U, &W, &c, 3);
    urig_vw(&R, 0, NOTICE);
    CHECK_EQ_U64(t, W.replay_calls, 0);
    CHECK_EQ_U64(t, ui_counts(&U).i8_checks, 0);
    CHECK_EQ_U64(t, ui_counts(&U).notices, 1);
    c.sample_every = 1;
    c.tick_ms = 250;
    urig_start(&R, t, &U, &W, &c, 1); /* a catalogue but no replay */
    urig_vw(&R, 0, NOTICE);
    CHECK_EQ_U64(t, ui_counts(&U).i8_checks, 0);
    CHECK_EQ_U64(t, ui_finding_count(&U), 0);
}

CTEST_SUITE("ui_i8",
    { "one_ms", t_a_countdown_of_one_millisecond_is_still_a_countdown },
    { "three_runs", t_a_notice_is_dismissed_and_the_world_is_asked_three_things },
    { "tick", t_the_tick_is_the_apps },
    { "no_countdown", t_a_notice_without_a_countdown_is_asked_once },
    { "kept", t_a_notice_that_survives_its_dismiss_is_found },
    { "screen", t_the_screen_under_the_notice_stays },
    { "expiry", t_dismissing_and_waiting_is_waiting },
    { "replay_fails", t_a_replay_that_fails_is_a_finding_and_stops_the_checks },
    { "sampling", t_only_every_nth_notice_is_checked },
    { "off", t_i8_needs_a_replay_and_a_sample_rate })
