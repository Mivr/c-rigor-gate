/* The I7 rules through ui_feed: the parse verdicts, phrases, language reset, dismiss and timeout of a notice, and the engine's own contract. */
#include <stdio.h>
#include <string.h>

#include "sim/inv/tests/ui_rig.h"

static ui_t U;
static urig_world_t W;
static urig_t R;

static void begin(ctest_t *t, int with_world) {
    urig_start(&R, t, &U, &W, NULL, with_world);
}

static const char *plain(void) {
    return urig_welcome("bg", "null", "");
}

static const char *with_notice(const char *kind, const char *countdown) {
    static char text[900];
    snprintf(text, sizeof text, "%s", urig_welcome("bg", urig_notice(kind, "overlay", "reject_invalid", countdown), ""));
    return text;
}

static void t_init_refuses_what_it_cannot_run(ctest_t *t) {
    static ui_schema_t unready;
    ui_cfg_t c;
    const ui_schema_t *s = urig_schema(t);
    sim_rec_t rec = {{'v', 'w'}, 0, 0, 0, (const uint8_t *)"{}", 2};
    urig_cfg(&c);
    CHECK_EQ_I64(t, ui_init(NULL, s, &c, NULL), -1);
    CHECK_EQ_I64(t, ui_init(&U, NULL, &c, NULL), -1);
    CHECK_EQ_I64(t, ui_init(&U, s, NULL, NULL), -1);
    CHECK_EQ_I64(t, ui_feed(&U, &rec), -1); /* refused: nothing started */
    CHECK_EQ_I64(t, ui_schema_parse(&unready, "", 0), UI_SE_INCOMPLETE);
    CHECK_EQ_I64(t, ui_init(&U, &unready, &c, NULL), -1);
    c.n_ev_dismiss = 5;
    CHECK_EQ_I64(t, ui_init(&U, s, &c, NULL), -1);
    c.n_ev_dismiss = 4;
    CHECK_EQ_I64(t, ui_init(&U, s, &c, NULL), 0);
    c.n_ev_activity = 5;
    CHECK_EQ_I64(t, ui_init(&U, s, &c, NULL), -1);
    c.n_ev_activity = 4;
    CHECK_EQ_I64(t, ui_init(&U, s, &c, NULL), 0);
    c.sample_every = 1;
    c.tick_ms = 0;
    CHECK_EQ_I64(t, ui_init(&U, s, &c, NULL), -1);
    c.sample_every = 0;
    CHECK_EQ_I64(t, ui_init(&U, s, &c, NULL), 0);
    c.sample_every = 1;
    c.tick_ms = 1;
    CHECK_EQ_I64(t, ui_init(&U, s, &c, NULL), 0);
}

static void t_a_new_start_forgets_the_old_run(ctest_t *t) {
    begin(t, 0);
    urig_vw(&R, 5, " {}");
    CHECK_EQ_U64(t, ui_finding_count(&U), 1);
    begin(t, 0);
    CHECK_EQ_U64(t, ui_finding_count(&U), 0);
    CHECK_EQ_U64(t, ui_counts(&U).views, 0);
    CHECK_EQ_U64(t, ui_counts(&U).records, 0);
    CHECK(t, !ui_has_rule(&U, UI_R_SYNTAX));
    CHECK(t, !ui_has_inv(&U, UI_I7));
    urig_vw(&R, 1, plain()); /* time may start again below the old run's */
}

static void t_feed_takes_records_in_time_order(ctest_t *t) {
    static const sim_rec_t good = {{'v', 'w'}, 100, 0, 0, (const uint8_t *)"x", 1};
    static const sim_rec_t nobytes = {{'v', 'w'}, 100, 0, 0, NULL, 1};
    static const sim_rec_t empty = {{'v', 'w'}, 200, 0, 0, NULL, 0};
    static const sim_rec_t back = {{'e', 'v'}, 99, 0, 0, NULL, 0};
    static const sim_rec_t same = {{'e', 'v'}, 100, 0, 0, NULL, 0};
    static const sim_rec_t other = {{'f', 'x'}, 200, 0, 0, NULL, 0};
    begin(t, 0);
    CHECK_EQ_I64(t, ui_feed(&U, NULL), -1);
    CHECK_EQ_I64(t, ui_feed(&U, &nobytes), -1);
    CHECK_EQ_U64(t, ui_counts(&U).records, 0);
    CHECK_EQ_I64(t, ui_feed(&U, &good), 0);
    CHECK_EQ_U64(t, ui_counts(&U).records, 1);
    CHECK_EQ_U64(t, ui_counts(&U).views, 1);
    CHECK_EQ_U64(t, ui_finding_count(&U), 1); /* "x" is not a view */
    CHECK_EQ_I64(t, ui_feed(&U, &back), -1);
    CHECK_EQ_U64(t, ui_counts(&U).records, 1);
    CHECK_EQ_I64(t, ui_feed(&U, &same), 0);
    CHECK_EQ_I64(t, ui_feed(&U, &other), 0); /* other kinds only advance time and count */
    CHECK_EQ_U64(t, ui_counts(&U).records, 3);
    CHECK_EQ_U64(t, ui_counts(&U).views, 1);
    CHECK_EQ_I64(t, ui_feed(&U, &empty), 0); /* a view with no text is not a view */
    CHECK_EQ_U64(t, ui_finding_count(&U), 2);
    CHECK_EQ_I64(t, ui_feed(&U, &back), -1);
    CHECK_EQ_I64(t, ui_finish(&U, 199), -1);
    CHECK_EQ_I64(t, ui_finish(&U, 200), 0);
    CHECK_EQ_I64(t, ui_finish(&U, 300), 0);
    CHECK_EQ_I64(t, ui_feed(&U, &other), -1);
}

static void t_finish_needs_a_started_engine(ctest_t *t) {
    ui_cfg_t c;
    urig_cfg(&c);
    c.sample_every = 1;
    c.tick_ms = 0;
    CHECK_EQ_I64(t, ui_init(&U, urig_schema(t), &c, NULL), -1);
    CHECK_EQ_I64(t, ui_finish(&U, 0), -1);
}

typedef struct {
    const char *old, *rep;
    ui_rule_t rule;
} bad_t;

static void t_every_parse_verdict_is_a_finding_at_its_record(ctest_t *t) {
    static const bad_t BAD[] = {
        {"\"lang\":\"bg\"", "\"lang\": \"bg\"", UI_R_SYNTAX},
        {"\"notice\":null", "\"zzz\":null", UI_R_KEY},
        {"\"lang\":\"bg\"", "\"lang\":\"zz\"", UI_R_ENUM},
        {"\"pad_len\":3", "\"pad_len\":3.5", UI_R_FLOAT},
        {"\"pad_len\":3", "\"pad_len\":65", UI_R_RANGE},
        {"\"screen\":\"welcome\"", "\"screen\":\"message\"", UI_R_FULL_SCREEN},
        {"\"notice\":null", "\"message\":null", UI_R_FULL_SCREEN},
    };
    for (uint32_t i = 0; i < sizeof BAD / sizeof BAD[0]; i++) {
        begin(t, 3);
        urig_vw(&R, 10, plain());
        urig_ev(&R, 20, U_EV_OTHER);
        urig_vw(&R, 1030, urig_edit(plain(), BAD[i].old, BAD[i].rep));
        urig_vw(&R, 2000, plain());
        CHECK_EQ_U64(t, ui_finding_count(&U), 1);
        CHECK(t, urig_finding_is(&R, 0, BAD[i].rule, 1030, 2));
        CHECK(t, ui_has_rule(&U, BAD[i].rule));
        CHECK(t, ui_has_inv(&U, UI_I7));
        CHECK(t, !ui_has_inv(&U, UI_I8));
        CHECK_EQ_U64(t, ui_counts(&U).views, 3);
        CHECK_EQ_U64(t, ui_counts(&U).phrases, 0);
    }
    begin(t, 3);
    urig_vw(&R, 0, urig_welcome("bg", urig_edit(urig_notice("dialog", "overlay", "reject_invalid", "5000"), "\"dismiss\":\"overlay\",", ""), ""));
    CHECK(t, urig_finding_is(&R, 0, UI_R_NO_DISMISS, 0, 0));
    begin(t, 3);
    urig_vw(&R, 0, urig_welcome("bg", "null", "{\"id\":\"sync\",\"phrase\":\"saved\",\"args\":{},\"warning\":false},{\"id\":\"audit\",\"phrase\":\"saved\",\"args\":{},\"warning\":false}"));
    CHECK(t, urig_finding_is(&R, 0, UI_R_BANNER_ORDER, 0, 0));
}

static void t_a_view_that_does_not_parse_changes_nothing_else(ctest_t *t) {
    begin(t, 0);
    urig_vw(&R, 0, with_notice("dialog", "8000"));
    urig_ev(&R, 500, U_EV_DISMISS);
    urig_vw(&R, 1000, " {}");
    urig_vw(&R, 2000, plain());
    CHECK_EQ_U64(t, ui_finding_count(&U), 1); /* the bad view only; the dismiss still counts for the clear */
    CHECK_EQ_U64(t, ui_counts(&U).dismissed, 1);
    CHECK_EQ_U64(t, ui_counts(&U).expired, 0);
}

static void t_the_findings_are_capped_and_counted(ctest_t *t) {
    begin(t, 0);
    for (uint32_t i = 0; i < 20U; i++) {
        urig_vw(&R, i, " {}");
    }
    CHECK_EQ_U64(t, ui_finding_count(&U), 16);
    CHECK_EQ_U64(t, ui_dropped(&U), 4);
    CHECK(t, ui_finding(&U, 15) != NULL);
    CHECK(t, ui_finding(&U, 16) == NULL);
    CHECK(t, urig_finding_is(&R, 15, UI_R_SYNTAX, 15, 15));
    CHECK(t, ui_finding(&U, 1000) == NULL);
    begin(t, 0);
    CHECK_EQ_U64(t, ui_dropped(&U), 0);
    CHECK(t, ui_finding(&U, 0) == NULL); /* none yet: index == count */
    urig_vw(&R, 0, " {}");
    CHECK(t, ui_finding(&U, 0) != NULL);
    CHECK(t, ui_finding(&U, 1) == NULL);
}

static void t_phrases_are_looked_up_in_the_catalogue(ctest_t *t) {
    const char *banners = "{\"id\":\"not_saved\",\"phrase\":\"saved\",\"args\":{},\"warning\":false},{\"id\":\"audit\",\"phrase\":\"audit\",\"args\":{},\"warning\":false}";
    begin(t, 1);
    urig_vw(&R, 0, urig_welcome("bg", urig_notice("dialog", "overlay", "reject_unknown", "null"), banners));
    CHECK_EQ_U64(t, W.phrase_calls, 3);
    CHECK_EQ_STR(t, W.phrases[0], "reject_unknown");
    CHECK_EQ_STR(t, W.phrases[1], "saved");
    CHECK_EQ_STR(t, W.phrases[2], "audit");
    CHECK_EQ_U64(t, ui_counts(&U).phrases, 3);
    CHECK_EQ_U64(t, ui_counts(&U).banners, 2);
    CHECK_EQ_U64(t, ui_finding_count(&U), 0);
    urig_vw(&R, 1, plain()); /* no notice and no banner: nothing to ask */
    CHECK_EQ_U64(t, W.phrase_calls, 3);
    urig_vw(&R, 2, urig_welcome("bg", "null", banners));
    CHECK_EQ_U64(t, W.phrase_calls, 5);
    CHECK_EQ_U64(t, ui_counts(&U).banners, 4);
    begin(t, 1);
    W.unknown = "reject_unknown";
    urig_vw(&R, 7, urig_welcome("bg", urig_notice("dialog", "overlay", "reject_unknown", "null"), banners));
    CHECK_EQ_U64(t, ui_finding_count(&U), 1);
    CHECK(t, urig_finding_is(&R, 0, UI_R_PHRASE_UNKNOWN, 7, 0));
    begin(t, 1);
    W.nobg = "audit";
    urig_vw(&R, 7, urig_welcome("bg", urig_notice("dialog", "overlay", "reject_unknown", "null"), banners));
    CHECK_EQ_U64(t, ui_finding_count(&U), 1);
    CHECK(t, urig_finding_is(&R, 0, UI_R_PHRASE_NO_BG, 7, 0));
    CHECK(t, ui_has_inv(&U, UI_I7));
    begin(t, 1);
    W.unknown = "saved";
    W.nobg = "reject_unknown";
    urig_vw(&R, 7, urig_welcome("bg", urig_notice("dialog", "overlay", "reject_unknown", "null"), banners));
    CHECK_EQ_U64(t, ui_finding_count(&U), 2);
    CHECK(t, urig_finding_is(&R, 0, UI_R_PHRASE_NO_BG, 7, 0));
    CHECK(t, urig_finding_is(&R, 1, UI_R_PHRASE_UNKNOWN, 7, 0));
    ui_cfg_t c;
    urig_cfg(&c);
    c.sample_every = 0;
    urig_start(&R, t, &U, &W, &c, 2); /* replay only: no catalogue, no phrase checks */
    urig_vw(&R, 0, urig_welcome("bg", urig_notice("dialog", "overlay", "reject_unknown", "null"), banners));
    CHECK_EQ_U64(t, ui_counts(&U).phrases, 0);
    CHECK_EQ_U64(t, ui_finding_count(&U), 0);
}

static void t_the_language_goes_back_to_the_default_after_the_idle_time(ctest_t *t) {
    begin(t, 0);
    urig_vw(&R, 31999, urig_welcome("en", "null", ""));
    CHECK_EQ_U64(t, ui_finding_count(&U), 0);
    CHECK_EQ_U64(t, ui_counts(&U).lang_checks, 0);
    urig_vw(&R, 32000, urig_welcome("en", "null", ""));
    CHECK_EQ_U64(t, ui_finding_count(&U), 1);
    CHECK(t, urig_finding_is(&R, 0, UI_R_LANG_NOT_RESET, 32000, 1));
    CHECK_EQ_U64(t, ui_counts(&U).lang_checks, 1);
    urig_vw(&R, 33000, urig_welcome("bg", "null", ""));
    CHECK_EQ_U64(t, ui_finding_count(&U), 1);
    CHECK_EQ_U64(t, ui_counts(&U).lang_checks, 2);
    begin(t, 0); /* an event in the activity list restarts the idle time; one outside it does not */
    urig_ev(&R, 10000, U_EV_LANG);
    urig_vw(&R, 41999, urig_welcome("en", "null", ""));
    CHECK_EQ_U64(t, ui_finding_count(&U), 0);
    urig_vw(&R, 42000, urig_welcome("en", "null", ""));
    CHECK_EQ_U64(t, ui_finding_count(&U), 1);
    begin(t, 0);
    urig_ev(&R, 10000, U_EV_OTHER);
    urig_vw(&R, 32000, urig_welcome("en", "null", ""));
    CHECK_EQ_U64(t, ui_finding_count(&U), 1);
    begin(t, 0);
    urig_ev(&R, 10000, U_EV_DIGIT);
    urig_vw(&R, 41999, urig_welcome("en", "null", ""));
    CHECK_EQ_U64(t, ui_finding_count(&U), 0);
    begin(t, 0);
    urig_ev(&R, 10000, U_EV_DISMISS);
    urig_vw(&R, 41999, urig_welcome("en", "null", ""));
    CHECK_EQ_U64(t, ui_finding_count(&U), 0);
}

static void t_a_visit_on_another_screen_counts_as_activity(ctest_t *t) {
    begin(t, 0);
    urig_vw(&R, 20000, urig_screen("choose", "en", "\"sizes\":[]", "null", ""));
    urig_vw(&R, 51999, urig_welcome("en", "null", ""));
    CHECK_EQ_U64(t, ui_finding_count(&U), 0);
    CHECK_EQ_U64(t, ui_counts(&U).lang_checks, 0);
    urig_vw(&R, 52000, urig_welcome("en", "null", ""));
    CHECK_EQ_U64(t, ui_finding_count(&U), 1);
    begin(t, 0); /* the language of a non-idle screen is not judged however long it lasts */
    urig_vw(&R, 90000, urig_screen("choose", "en", "\"sizes\":[]", "null", ""));
    CHECK_EQ_U64(t, ui_finding_count(&U), 0);
    CHECK_EQ_U64(t, ui_counts(&U).lang_checks, 0);
}

static void t_the_language_rule_can_be_switched_off(ctest_t *t) {
    ui_cfg_t c;
    urig_cfg(&c);
    c.idle_reset_ms = 0;
    urig_start(&R, t, &U, &W, &c, 0);
    urig_vw(&R, 500000, urig_welcome("en", "null", ""));
    CHECK_EQ_U64(t, ui_finding_count(&U), 0);
    CHECK_EQ_U64(t, ui_counts(&U).lang_checks, 0);
    CHECK_EQ_I64(t, ui_finish(&U, 900000), 0);
    CHECK_EQ_U64(t, ui_finding_count(&U), 0);
    c.idle_reset_ms = 1;
    c.slack_ms = 0;
    urig_start(&R, t, &U, &W, &c, 0);
    urig_vw(&R, 0, urig_welcome("en", "null", ""));
    CHECK_EQ_U64(t, ui_finding_count(&U), 0); /* a small time is still a time: now - last = 0 < 1 */
    urig_vw(&R, 1, urig_welcome("en", "null", ""));
    CHECK_EQ_U64(t, ui_finding_count(&U), 1);
}

static void t_the_run_ends_in_the_default_language(ctest_t *t) {
    begin(t, 0);
    CHECK_EQ_I64(t, ui_finish(&U, 100000), 0); /* no view at all: nothing to judge */
    CHECK_EQ_U64(t, ui_finding_count(&U), 0);
    begin(t, 0);
    urig_vw(&R, 100, urig_welcome("en", "null", ""));
    CHECK_EQ_I64(t, ui_finish(&U, 31999), 0);
    CHECK_EQ_U64(t, ui_finding_count(&U), 0);
    CHECK_EQ_I64(t, ui_finish(&U, 32000), 0);
    CHECK_EQ_U64(t, ui_finding_count(&U), 1);
    CHECK(t, urig_finding_is(&R, 0, UI_R_LANG_NOT_RESET, 32000, 1));
    begin(t, 0);
    urig_vw(&R, 100, urig_welcome("bg", "null", ""));
    CHECK_EQ_I64(t, ui_finish(&U, 99999), 0);
    CHECK_EQ_U64(t, ui_finding_count(&U), 0);
    CHECK_EQ_U64(t, ui_counts(&U).lang_checks, 1);
    begin(t, 0);
    urig_vw(&R, 100, urig_screen("choose", "en", "\"sizes\":[]", "null", ""));
    CHECK_EQ_I64(t, ui_finish(&U, 99999), 0);
    CHECK_EQ_U64(t, ui_finding_count(&U), 0);
    begin(t, 0); /* a view that did not parse is not the last view */
    urig_vw(&R, 100, urig_welcome("bg", "null", ""));
    urig_vw(&R, 200, " {}");
    CHECK_EQ_I64(t, ui_finish(&U, 99999), 0);
    CHECK_EQ_U64(t, ui_finding_count(&U), 1);
    CHECK_EQ_U64(t, ui_counts(&U).lang_checks, 1);
}

static void t_a_notice_that_clears_by_itself_must_have_shown_a_countdown(ctest_t *t) {
    begin(t, 0);
    urig_vw(&R, 0, with_notice("dialog", "null"));
    urig_vw(&R, 1000, plain());
    CHECK_EQ_U64(t, ui_finding_count(&U), 1);
    CHECK(t, urig_finding_is(&R, 0, UI_R_TIMEOUT_NO_COUNTDOWN, 1000, 1));
    CHECK_EQ_U64(t, ui_counts(&U).expired, 1);
    begin(t, 0);
    urig_vw(&R, 0, with_notice("snackbar", "null"));
    urig_vw(&R, 1000, plain());
    CHECK(t, urig_finding_is(&R, 0, UI_R_TIMEOUT_NO_COUNTDOWN, 1000, 1));
    begin(t, 0); /* a kind that does not clear by itself (a banner) is left alone */
    urig_vw(&R, 0, with_notice("banner", "null"));
    urig_vw(&R, 1000, plain());
    CHECK_EQ_U64(t, ui_finding_count(&U), 0);
    CHECK_EQ_U64(t, ui_counts(&U).expired, 0);
    CHECK_EQ_U64(t, ui_counts(&U).dismissed, 0);
    begin(t, 0); /* a dismiss intent clears any notice */
    urig_vw(&R, 0, with_notice("dialog", "null"));
    urig_ev(&R, 500, U_EV_DISMISS);
    urig_vw(&R, 1000, plain());
    CHECK_EQ_U64(t, ui_finding_count(&U), 0);
    CHECK_EQ_U64(t, ui_counts(&U).dismissed, 1);
    CHECK_EQ_U64(t, ui_counts(&U).expired, 0);
    begin(t, 0); /* the dismiss is spent by the next view */
    urig_vw(&R, 0, with_notice("dialog", "null"));
    urig_ev(&R, 500, U_EV_DISMISS);
    urig_vw(&R, 1000, with_notice("dialog", "null"));
    urig_vw(&R, 2000, plain());
    CHECK_EQ_U64(t, ui_finding_count(&U), 1);
    CHECK(t, urig_finding_is(&R, 0, UI_R_TIMEOUT_NO_COUNTDOWN, 2000, 3));
    begin(t, 0); /* an event that is not a dismiss does not clear it */
    urig_vw(&R, 0, with_notice("dialog", "null"));
    urig_ev(&R, 500, U_EV_DIGIT);
    urig_vw(&R, 1000, plain());
    CHECK_EQ_U64(t, ui_finding_count(&U), 1);
}

static void t_a_notice_clears_when_its_countdown_has_run_out(ctest_t *t) {
    begin(t, 0);
    urig_vw(&R, 0, with_notice("dialog", "8000"));
    urig_vw(&R, 5999, plain());
    CHECK_EQ_U64(t, ui_finding_count(&U), 1);
    CHECK(t, urig_finding_is(&R, 0, UI_R_COUNTDOWN_EARLY, 5999, 1));
    begin(t, 0);
    urig_vw(&R, 0, with_notice("dialog", "8000"));
    urig_vw(&R, 6000, plain());
    CHECK_EQ_U64(t, ui_finding_count(&U), 0);
    CHECK_EQ_U64(t, ui_counts(&U).expired, 1);
    begin(t, 0); /* the last countdown shown counts, from the time it was shown */
    urig_vw(&R, 0, with_notice("dialog", "8000"));
    urig_vw(&R, 1000, with_notice("dialog", "7000"));
    urig_vw(&R, 1500, plain());
    CHECK_EQ_U64(t, ui_finding_count(&U), 1);
    CHECK(t, urig_finding_is(&R, 0, UI_R_COUNTDOWN_EARLY, 1500, 2));
    begin(t, 0);
    urig_vw(&R, 0, with_notice("dialog", "8000"));
    urig_vw(&R, 1000, with_notice("dialog", "7000"));
    urig_vw(&R, 6000, with_notice("dialog", "2000"));
    urig_vw(&R, 8000, plain());
    CHECK_EQ_U64(t, ui_finding_count(&U), 0);
    CHECK_EQ_U64(t, ui_counts(&U).notices, 1); /* the countdown is not the notice's identity */
    begin(t, 0); /* a dismiss before the end is not early */
    urig_vw(&R, 0, with_notice("dialog", "8000"));
    urig_ev(&R, 100, U_EV_DISMISS);
    urig_vw(&R, 200, plain());
    CHECK_EQ_U64(t, ui_finding_count(&U), 0);
    begin(t, 0); /* a banner kind is not judged, early or not */
    urig_vw(&R, 0, with_notice("banner", "8000"));
    urig_vw(&R, 200, plain());
    CHECK_EQ_U64(t, ui_finding_count(&U), 0);
}

static void t_a_notice_replaced_by_another_is_a_new_notice(ctest_t *t) {
    begin(t, 0);
    urig_vw(&R, 0, urig_welcome("bg", urig_notice("dialog", "overlay", "reject_invalid", "null"), ""));
    urig_vw(&R, 1000, urig_welcome("bg", urig_notice("dialog", "overlay", "reject_unknown", "null"), ""));
    CHECK_EQ_U64(t, ui_finding_count(&U), 0); /* replaced, not cleared */
    CHECK_EQ_U64(t, ui_counts(&U).notices, 2);
    urig_vw(&R, 2000, urig_welcome("bg", urig_notice("dialog", "overlay", "reject_unknown", "null"), ""));
    CHECK_EQ_U64(t, ui_counts(&U).notices, 2);
    urig_vw(&R, 3000, plain());
    CHECK_EQ_U64(t, ui_finding_count(&U), 1);
    urig_vw(&R, 4000, urig_welcome("bg", urig_notice("dialog", "overlay", "reject_unknown", "null"), ""));
    CHECK_EQ_U64(t, ui_counts(&U).notices, 3);
    begin(t, 0); /* any field of the notice but its countdown is its identity */
    urig_vw(&R, 0, urig_welcome("bg", urig_notice("dialog", "overlay", "reject_invalid", "null"), ""));
    urig_vw(&R, 1, urig_welcome("bg", urig_notice("dialog", "banner_sync", "reject_invalid", "null"), ""));
    urig_vw(&R, 2, urig_welcome("bg", urig_notice("snackbar", "banner_sync", "reject_invalid", "null"), ""));
    urig_vw(&R, 3, urig_edit(urig_welcome("bg", urig_notice("snackbar", "banner_sync", "reject_invalid", "null"), ""), "\"warning\":false", "\"warning\":true"));
    CHECK_EQ_U64(t, ui_counts(&U).notices, 4);
    CHECK_EQ_U64(t, ui_finding_count(&U), 0);
}

static void t_only_the_two_kinds_are_read(ctest_t *t) {
    const char *kinds[] = {"ex", "fv", "vx", "xw", "ee", "vv", "ww", "ve", "wv"};
    for (uint32_t i = 0; i < sizeof kinds / sizeof kinds[0]; i++) {
        sim_rec_t ev = {{kinds[i][0], kinds[i][1]}, 100, U_EV_DISMISS, 0, NULL, 0};
        sim_rec_t vw = {{kinds[i][0], kinds[i][1]}, 200, 0, 0, (const uint8_t *)plain(), (uint32_t)strlen(plain())};
        begin(t, 0);
        CHECK_EQ_I64(t, ui_feed(&U, &ev), 0);
        CHECK_EQ_I64(t, ui_feed(&U, &vw), 0);
        CHECK_EQ_U64(t, ui_counts(&U).views, 0);
        CHECK_EQ_U64(t, ui_counts(&U).records, 2);
        begin(t, 0); /* nor is the dismiss of another kind a dismiss */
        urig_vw(&R, 0, with_notice("dialog", "null"));
        CHECK_EQ_I64(t, ui_feed(&U, &ev), 0);
        urig_vw(&R, 150, plain());
        CHECK_EQ_U64(t, ui_finding_count(&U), 1);
    }
    begin(t, 0);
    urig_vw(&R, 0, with_notice("dialog", "null"));
    urig_ev(&R, 100, U_EV_DISMISS);
    urig_vw(&R, 150, plain());
    CHECK_EQ_U64(t, ui_finding_count(&U), 0);
}

static void t_rules_and_invariants_have_names(ctest_t *t) {
    static const char *const NAMES[UI_R_COUNT] = {NULL, "syntax", "key", "enum", "float", "range", "full-screen-message", "notice-without-dismiss",
                                                  "banner-order", "timeout-without-countdown", "countdown-early", "lang-not-reset", "phrase-unknown",
                                                  "phrase-without-bg", "dismiss-kept", "dismiss-screen-changed", "dismiss-vs-expiry", "replay-failed"};
    for (uint32_t r = 0; r < (uint32_t)UI_R_COUNT; r++) {
        const char *name = ui_rule_name((ui_rule_t)r);
        CHECK(t, (name == NULL) == (NAMES[r] == NULL));
        if (name != NULL && NAMES[r] != NULL) {
            CHECK_EQ_STR(t, name, NAMES[r]);
        }
        CHECK_EQ_U64(t, ui_rule_inv((ui_rule_t)r), r == 0U ? 0U : (r < (uint32_t)UI_R_DISMISS_KEPT ? 7U : 8U));
    }
    CHECK(t, ui_rule_name((ui_rule_t)UI_R_COUNT) == NULL);
    CHECK(t, ui_rule_name((ui_rule_t)1000) == NULL);
    CHECK(t, ui_rule_name((ui_rule_t)-1) == NULL);
    CHECK_EQ_STR(t, ui_inv_name(UI_I7), "I7");
    CHECK_EQ_STR(t, ui_inv_name(UI_I8), "I8");
    CHECK(t, ui_inv_name((ui_inv_t)0) == NULL);
    CHECK(t, ui_inv_name((ui_inv_t)6) == NULL);
    CHECK(t, ui_inv_name((ui_inv_t)9) == NULL);
    begin(t, 0);
    CHECK(t, !ui_has_rule(&U, UI_R_NONE));
    urig_vw(&R, 0, " {}");
    CHECK(t, ui_has_rule(&U, UI_R_SYNTAX));
    CHECK(t, !ui_has_rule(&U, UI_R_KEY));
    CHECK(t, !ui_has_rule(&U, UI_R_REPLAY_FAILED));
    CHECK(t, !ui_has_inv(&U, (ui_inv_t)0));
}

CTEST_SUITE("ui_rules",
    { "kinds", t_only_the_two_kinds_are_read },
    { "names", t_rules_and_invariants_have_names },
    { "init", t_init_refuses_what_it_cannot_run },
    { "restart", t_a_new_start_forgets_the_old_run },
    { "feed", t_feed_takes_records_in_time_order },
    { "finish_started", t_finish_needs_a_started_engine },
    { "parse_verdicts", t_every_parse_verdict_is_a_finding_at_its_record },
    { "bad_view_changes_nothing", t_a_view_that_does_not_parse_changes_nothing_else },
    { "findings_cap", t_the_findings_are_capped_and_counted },
    { "phrases", t_phrases_are_looked_up_in_the_catalogue },
    { "lang", t_the_language_goes_back_to_the_default_after_the_idle_time },
    { "lang_screens", t_a_visit_on_another_screen_counts_as_activity },
    { "lang_off", t_the_language_rule_can_be_switched_off },
    { "lang_finish", t_the_run_ends_in_the_default_language },
    { "timeout", t_a_notice_that_clears_by_itself_must_have_shown_a_countdown },
    { "countdown", t_a_notice_clears_when_its_countdown_has_run_out },
    { "identity", t_a_notice_replaced_by_another_is_a_new_notice })
