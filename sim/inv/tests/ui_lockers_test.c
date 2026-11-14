/* The lockers kiosk's schema (selftest/sim/lockers-view.schema, written from vstate.h of business-apps) parses, and the views of vstate.h's
 * canonical form under it parse and are judged: the API can say what the product's ViewState says. The text below is the file, line for line
 * (selftest/sim.sh compares them). It is not part of the mutation run: the engine's own tests are. */
#include <stdio.h>
#include <string.h>

#include "sim/inv/tests/ui_rig.h"

static const char LOCKERS_SCHEMA[] =
    "# The closed schema of the lockers kiosk's ViewState canonical form (T2G5), written from apps/lockers/lkrx/vstate/vstate.h of business-apps\n"
    "# (its \"CANONICAL FORM\" and its enums: LKS_*, LK_NK_*, LK_DISMISS_*, LK_PH_*, LK_DOOR_*, LK_BANNER_*, the bounds of \"Bounds\") and the rules of\n"
    "# docs/lockers/ui-rules.md. This is the product's file to own: the gate parses it with ui_schema_parse and knows no field name of it.\n"
    "# [V] the texts of the fault enum are `lk_fault_name` of lk/types: check them against the product before this file is used for a grade.\n"
    "enum screen splash welcome choose opened shift report lockout fault_storage fault_relay\n"
    "enum lang bg en\n"
    "enum nkind dialog banner snackbar\n"
    "enum dismiss overlay banner_not_saved banner_audit banner_sync banner_codes_offline banner_codes_stale banner_self_test\n"
    "enum bannerid not_saved audit sync codes_offline codes_stale self_test\n"
    "enum phrase reject_invalid reject_unknown reject_codes_unavailable no_locker fault saved not_saved audit sync_rejected sync_late codes_offline codes_stale self_test\n"
    "enum fault relay_busy kiosk_busy lock_unavailable relay_safety_stop relay_offline relay_error storage_error codes_unavailable book_rejected locker_missing\n"
    "enum door nothing_opened maybe_opened opened\n"
    "\n"
    "object sizeitem\n"
    "  field size uint 5\n"
    "  field free uint 65535\n"
    "end\n"
    "\n"
    "# The arguments of a phrase: the keys of its case, in the order of vstate.h; every other phrase has `{}`.\n"
    "object args\n"
    "  switch @ phrase\n"
    "  on fault\n"
    "  field fault enum fault\n"
    "  field door enum door\n"
    "  field locker uint 999 null\n"
    "  on sync_rejected\n"
    "  field status uint 65535\n"
    "  on sync_late\n"
    "  field hour uint 23\n"
    "  field minute uint 59\n"
    "  on codes_offline\n"
    "  field hour uint 23\n"
    "  field minute uint 59\n"
    "  on self_test\n"
    "  field issues uint 4095\n"
    "  endswitch\n"
    "end\n"
    "\n"
    "object notice\n"
    "  field kind enum nkind\n"
    "  field dismiss enum dismiss\n"
    "  field phrase enum phrase\n"
    "  field args obj args by phrase\n"
    "  field warning bool\n"
    "  field countdown_ms uint 300000 null\n"
    "end\n"
    "\n"
    "object banner\n"
    "  field id enum bannerid\n"
    "  field phrase enum phrase\n"
    "  field args obj args by phrase\n"
    "  field warning bool\n"
    "end\n"
    "\n"
    "object view\n"
    "  field screen enum screen\n"
    "  field lang enum lang\n"
    "  field countdown_ms uint 300000 null\n"
    "  switch screen\n"
    "  on welcome\n"
    "  field pad_len uint 64\n"
    "  on choose\n"
    "  field sizes list sizeitem 6\n"
    "  on opened\n"
    "  field locker uint 999\n"
    "  field first_time bool\n"
    "  on shift\n"
    "  field done uint 65535\n"
    "  field total uint 65535\n"
    "  on report\n"
    "  field released uint 65535\n"
    "  field ok uint 65535\n"
    "  field faults uint 65535\n"
    "  field write_failed bool\n"
    "  on fault_storage\n"
    "  field fault enum fault\n"
    "  on fault_relay\n"
    "  field fault enum fault\n"
    "  endswitch\n"
    "  field notice obj notice null\n"
    "  field banners list banner 6\n"
    "end\n"
    "\n"
    "top view\n"
    "role screen view screen\n"
    "role lang view lang\n"
    "role notice view notice\n"
    "role banners view banners\n"
    "role n_kind notice kind\n"
    "role n_dismiss notice dismiss\n"
    "role n_phrase notice phrase\n"
    "role n_countdown notice countdown_ms\n"
    "role b_id banner id\n"
    "role b_phrase banner phrase\n"
    "\n"
    "# A banner's dismiss intent is implied by its id (vstate.h, lk_banner_t).\n"
    "bannerdismiss not_saved banner_not_saved\n"
    "bannerdismiss audit banner_audit\n"
    "bannerdismiss sync banner_sync\n"
    "bannerdismiss codes_offline banner_codes_offline\n"
    "bannerdismiss codes_stale banner_codes_stale\n"
    "bannerdismiss self_test banner_self_test\n"
    "\n"
    "# A message that is a screen has no place in the closed schema: these keys name one.\n"
    "forbid message text title detail\n"
    "\n"
    "idle welcome\n"
    "lang_default bg\n"
    "# Dialogs and snackbars clear on their own (their countdown); a banner does not (docs/lockers/ui-rules.md, \"Screen timers\").\n"
    "expiring dialog snackbar\n";

static ui_schema_t S;
static ui_t U;

static int feed_view(ui_t *u, uint64_t t_ms, const char *text) {
    sim_rec_t rec = {{'v', 'w'}, t_ms, 0, 0, (const uint8_t *)text, (uint32_t)strlen(text)};
    return ui_feed(u, &rec);
}

static void t_the_lockers_schema_parses(ctest_t *t) {
    CHECK_EQ_I64(t, ui_schema_parse(&S, LOCKERS_SCHEMA, (uint32_t)strlen(LOCKERS_SCHEMA)), UI_SE_OK);
    for (uint32_t id = 0; id < 6U; id++) {
        CHECK_EQ_I64(t, ui_schema_banner_dismiss(&S, (uint8_t)id), (int)id + 1); /* banner_X follows overlay in the dismiss enum */
    }
    CHECK_EQ_I64(t, ui_schema_banner_dismiss(&S, 6), -1);
}

static void t_the_canonical_views_of_vstate_h_parse(ctest_t *t) {
    static ui_view_t v;
    struct {
        const char *text;
        uint8_t screen;
    } views[] = {
        {"{\"screen\":\"splash\",\"lang\":\"bg\",\"countdown_ms\":null,\"notice\":null,\"banners\":[]}", 0},
        {"{\"screen\":\"welcome\",\"lang\":\"en\",\"countdown_ms\":null,\"pad_len\":4,\"notice\":null,\"banners\":[]}", 1},
        {"{\"screen\":\"choose\",\"lang\":\"bg\",\"countdown_ms\":30000,\"sizes\":[{\"size\":0,\"free\":3},{\"size\":2,\"free\":0}],\"notice\":null,\"banners\":[]}", 2},
        {"{\"screen\":\"opened\",\"lang\":\"bg\",\"countdown_ms\":8000,\"locker\":12,\"first_time\":true,\"notice\":null,\"banners\":[]}", 3},
        {"{\"screen\":\"shift\",\"lang\":\"bg\",\"countdown_ms\":null,\"done\":3,\"total\":40,\"notice\":null,\"banners\":[]}", 4},
        {"{\"screen\":\"report\",\"lang\":\"bg\",\"countdown_ms\":300000,\"released\":38,\"ok\":36,\"faults\":2,\"write_failed\":false,\"notice\":null,\"banners\":[]}", 5},
        {"{\"screen\":\"lockout\",\"lang\":\"en\",\"countdown_ms\":60000,\"notice\":null,\"banners\":[]}", 6},
        {"{\"screen\":\"fault_storage\",\"lang\":\"bg\",\"countdown_ms\":null,\"fault\":\"storage_error\",\"notice\":null,\"banners\":[]}", 7},
        {"{\"screen\":\"fault_relay\",\"lang\":\"bg\",\"countdown_ms\":null,\"fault\":\"relay_offline\",\"notice\":null,\"banners\":[]}", 8},
    };
    CHECK_EQ_I64(t, ui_schema_parse(&S, LOCKERS_SCHEMA, (uint32_t)strlen(LOCKERS_SCHEMA)), UI_SE_OK);
    for (uint32_t i = 0; i < sizeof views / sizeof views[0]; i++) {
        CHECK_EQ_I64(t, ui_parse(&S, (const uint8_t *)views[i].text, (uint32_t)strlen(views[i].text), &v, NULL), UI_R_NONE);
        CHECK_EQ_U64(t, v.screen, views[i].screen);
    }
}

static void t_the_notices_and_banners_of_the_product_parse(ctest_t *t) {
    static ui_view_t v;
    const char *fault =
        "{\"screen\":\"welcome\",\"lang\":\"bg\",\"countdown_ms\":null,\"pad_len\":0,\"notice\":{\"kind\":\"dialog\",\"dismiss\":\"overlay\",\"phrase\":\"fault\","
        "\"args\":{\"fault\":\"relay_busy\",\"door\":\"maybe_opened\",\"locker\":12},\"warning\":false,\"countdown_ms\":8000},\"banners\":[]}";
    const char *banners =
        "{\"screen\":\"welcome\",\"lang\":\"bg\",\"countdown_ms\":null,\"pad_len\":0,\"notice\":null,\"banners\":["
        "{\"id\":\"not_saved\",\"phrase\":\"not_saved\",\"args\":{},\"warning\":false},"
        "{\"id\":\"audit\",\"phrase\":\"audit\",\"args\":{},\"warning\":true},"
        "{\"id\":\"sync\",\"phrase\":\"sync_rejected\",\"args\":{\"status\":503},\"warning\":true},"
        "{\"id\":\"codes_offline\",\"phrase\":\"codes_offline\",\"args\":{\"hour\":9,\"minute\":5},\"warning\":false},"
        "{\"id\":\"codes_stale\",\"phrase\":\"codes_stale\",\"args\":{},\"warning\":false},"
        "{\"id\":\"self_test\",\"phrase\":\"self_test\",\"args\":{\"issues\":4095},\"warning\":true}]}";
    CHECK_EQ_I64(t, ui_schema_parse(&S, LOCKERS_SCHEMA, (uint32_t)strlen(LOCKERS_SCHEMA)), UI_SE_OK);
    CHECK_EQ_I64(t, ui_parse(&S, (const uint8_t *)fault, (uint32_t)strlen(fault), &v, NULL), UI_R_NONE);
    CHECK_EQ_U64(t, v.n_phrase, 4); /* fault */
    CHECK_EQ_U64(t, v.n_countdown_ms, 8000);
    CHECK_EQ_I64(t, ui_parse(&S, (const uint8_t *)banners, (uint32_t)strlen(banners), &v, NULL), UI_R_NONE);
    CHECK_EQ_U64(t, v.n_banners, 6);
    CHECK_EQ_U64(t, v.banner_id[5], 5);
}

static void t_the_rules_run_on_the_lockers_views(ctest_t *t) {
    ui_cfg_t c;
    urig_cfg(&c);
    c.sample_every = 0;
    CHECK_EQ_I64(t, ui_schema_parse(&S, LOCKERS_SCHEMA, (uint32_t)strlen(LOCKERS_SCHEMA)), UI_SE_OK);
    CHECK_EQ_I64(t, ui_init(&U, &S, &c, NULL), 0);
    /* a Bulgarian kiosk whose visitor switched to English, left, and came back to English after the idle time */
    CHECK_EQ_I64(t, feed_view(&U, 0, "{\"screen\":\"welcome\",\"lang\":\"en\",\"countdown_ms\":null,\"pad_len\":0,\"notice\":null,\"banners\":[]}"), 0);
    CHECK_EQ_I64(t, feed_view(&U, 40000, "{\"screen\":\"welcome\",\"lang\":\"en\",\"countdown_ms\":null,\"pad_len\":0,\"notice\":null,\"banners\":[]}"), 0);
    CHECK_EQ_U64(t, ui_finding_count(&U), 1);
    CHECK(t, ui_has_rule(&U, UI_R_LANG_NOT_RESET));
    /* a full-screen message the closed schema cannot say */
    CHECK_EQ_I64(t, feed_view(&U, 40001, "{\"screen\":\"message\",\"lang\":\"bg\",\"countdown_ms\":null,\"notice\":null,\"banners\":[]}"), 0);
    CHECK(t, ui_has_rule(&U, UI_R_FULL_SCREEN));
}

CTEST_SUITE("ui_lockers",
    { "schema", t_the_lockers_schema_parses },
    { "screens", t_the_canonical_views_of_vstate_h_parse },
    { "notices", t_the_notices_and_banners_of_the_product_parse },
    { "rules", t_the_rules_run_on_the_lockers_views })
