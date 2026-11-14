/* The strict view parser through ui_parse: every shape of the canonical text of the fixture schema, and every way a view can be wrong. */
#include <stdio.h>
#include <string.h>

#include "sim/inv/tests/ui_rig.h"

#define NOTICE_OK "{\"kind\":\"dialog\",\"dismiss\":\"overlay\",\"phrase\":\"reject_invalid\",\"args\":{},\"warning\":false,\"countdown_ms\":8000}"
#define FAULT_NOTICE                                                                                                         \
    "{\"kind\":\"snackbar\",\"dismiss\":\"banner_sync\",\"phrase\":\"fault\",\"args\":{\"fault\":\"relay_busy\",\"door\":\"maybe_opened\",\"locker\":12}," \
    "\"warning\":true,\"countdown_ms\":null}"
#define BANNERS_OK \
    "{\"id\":\"not_saved\",\"phrase\":\"not_saved\",\"args\":{},\"warning\":false},{\"id\":\"sync\",\"phrase\":\"sync_rejected\",\"args\":{\"status\":503},\"warning\":true}"

enum { B_PLAIN, B_NOTICE, B_BANNERS, B_FAULT, B_CHOOSE, B_OPENED, B_SPLASH, B_COUNT };

static const char *base(uint32_t which) {
    static char texts[B_COUNT][900];
    static int built;
    if (built == 0) {
        built = 1;
        snprintf(texts[B_PLAIN], sizeof texts[0], "%s", urig_welcome("bg", "null", ""));
        snprintf(texts[B_NOTICE], sizeof texts[0], "%s", urig_welcome("bg", NOTICE_OK, ""));
        snprintf(texts[B_BANNERS], sizeof texts[0], "%s", urig_welcome("en", "null", BANNERS_OK));
        snprintf(texts[B_FAULT], sizeof texts[0], "%s", urig_welcome("bg", FAULT_NOTICE, ""));
        snprintf(texts[B_CHOOSE], sizeof texts[0], "%s",
                 urig_screen("choose", "bg", "\"sizes\":[{\"size\":0,\"free\":3},{\"size\":2,\"free\":0}]", "null", ""));
        snprintf(texts[B_OPENED], sizeof texts[0], "%s", urig_screen("opened", "bg", "\"locker\":12,\"first_time\":true", "null", ""));
        snprintf(texts[B_SPLASH], sizeof texts[0], "%s", urig_screen("splash", "bg", "", "null", ""));
    }
    return texts[which];
}

static ui_rule_t parse(ctest_t *t, const char *text, ui_view_t *v, uint32_t *at) {
    const ui_schema_t *s = urig_schema(t);
    return ui_parse(s, (const uint8_t *)text, (uint32_t)strlen(text), v, at);
}

typedef struct {
    uint32_t base;
    const char *old, *rep;
    ui_rule_t rule;
} row_t;

#define SYN UI_R_SYNTAX
#define KEY UI_R_KEY
#define ENM UI_R_ENUM
#define FLT UI_R_FLOAT
#define RNG UI_R_RANGE
#define FUL UI_R_FULL_SCREEN
#define NOD UI_R_NO_DISMISS
#define ORD UI_R_BANNER_ORDER
#define GOOD UI_R_NONE

static const row_t ROWS[] = {
    /* the text is exact */
    {B_PLAIN, "\"screen\":\"welcome\"", "\"screen\": \"welcome\"", SYN},
    {B_PLAIN, "{\"screen\"", " {\"screen\"", SYN},
    {B_PLAIN, "{\"screen\"", "{ \"screen\"", SYN},
    {B_PLAIN, "[]}", "[]}\n", SYN},
    {B_PLAIN, "[]}", "[]}x", SYN},
    {B_PLAIN, "[]}", "[]}}", SYN},
    {B_PLAIN, "[]}", "[]", SYN},
    {B_PLAIN, "\"screen\":\"welcome\"", "\"Screen\":\"welcome\"", SYN},
    {B_PLAIN, "\"lang\":\"bg\"", "\"lang\":bg", SYN},
    {B_PLAIN, "\"lang\":\"bg\"", "\"lang\":\"Bg\"", SYN},
    {B_PLAIN, "\"lang\":\"bg\"", "\"lang\":\"bg", SYN},
    {B_PLAIN, "\"lang\":\"bg\"", "\"lang\":'bg'", SYN},
    {B_PLAIN, "\"lang\":\"bg\"", "\"lang\":\"b g\"", SYN},
    {B_PLAIN, "\"pad_len\"", "\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\"", KEY},
    {B_PLAIN, "\"pad_len\"", "\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\"", SYN},
    {B_PLAIN, "\"lang\":\"bg\"", "\"lang\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\"", ENM},
    {B_PLAIN, "\"lang\":\"bg\"", "\"lang\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\"", SYN},
    {B_PLAIN, "\"lang\":\"bg\"", "\"lang\":\"b0_\"", ENM},
    {B_PLAIN, "\"lang\":\"bg\"", "\"lang\":\"b\\u0067\"", SYN},
    {B_PLAIN, "\"lang\":\"bg\"", "\"lang\":\"a`\"", SYN},
    {B_PLAIN, "\"lang\":\"bg\"", "\"lang\":\"a{\"", SYN},
    {B_PLAIN, "\"lang\":\"bg\"", "\"lang\":\"a@\"", SYN},
    {B_PLAIN, "\"lang\":\"bg\"", "\"lang\":\"a/\"", SYN},
    {B_PLAIN, "\"lang\":\"bg\"", "\"lang\":\"a:\"", SYN},
    {B_PLAIN, "\"lang\":\"bg\"", "\"lang\":\"a_\"", ENM},
    {B_PLAIN, "\"lang\":\"bg\"", "\"lang\":\"a9\"", ENM},
    {B_PLAIN, "\"lang\":\"bg\"", "\"lang\":\"az\"", ENM},
    {B_PLAIN, "\"lang\":\"bg\"", "\"lang\":\"a0\"", ENM},
    /* keys: closed, in order, all present */
    {B_PLAIN, "\"screen\":\"welcome\",\"lang\":\"bg\"", "\"lang\":\"bg\",\"screen\":\"welcome\"", KEY},
    {B_PLAIN, "\"notice\":null,", "\"zzz\":null,", KEY},
    {B_PLAIN, "\"notice\":null,", "", KEY},
    {B_PLAIN, "\"countdown_ms\":null,", "", KEY},
    {B_PLAIN, "\"pad_len\":3,", "", KEY},
    {B_SPLASH, "\"countdown_ms\":null,", "\"countdown_ms\":null,\"pad_len\":3,", KEY},
    {B_PLAIN, "\"notice\":null", "\"message\":null", FUL},
    {B_PLAIN, "\"notice\":null", "\"title\":null", FUL},
    {B_PLAIN, "\"notice\":null", "\"text\":null", FUL},
    {B_PLAIN, "\"notice\":null", "\"texts\":null", KEY},
    {B_PLAIN, "\"notice\":null", "\"mes\":null", KEY},
    {B_PLAIN, "3,\"notice\"", "3\"notice\"", SYN},
    {B_PLAIN, "\"banners\":[]}", "\"banners\":[],\"x\":1}", SYN},
    {B_PLAIN, "\"notice\":null,", "\"notice\":null;", SYN},
    {B_PLAIN, "\"notice\":null,", "\"notice\" null,", SYN},
    /* enums */
    {B_PLAIN, "\"lang\":\"bg\"", "\"lang\":\"zzz\"", ENM},
    {B_PLAIN, "\"lang\":\"bg\"", "\"lang\":null", SYN},
    {B_PLAIN, "\"screen\":\"welcome\"", "\"screen\":\"message\"", FUL},
    {B_PLAIN, "\"screen\":\"welcome\"", "\"screen\":\"zzz\"", FUL},
    {B_PLAIN, "\"screen\":\"welcome\"", "\"screen\":7", SYN},
    {B_NOTICE, "\"kind\":\"dialog\"", "\"kind\":\"zzz\"", ENM},
    {B_NOTICE, "\"phrase\":\"reject_invalid\"", "\"phrase\":\"zzz\"", ENM},
    {B_BANNERS, "\"id\":\"sync\"", "\"id\":\"zzz\"", ENM},
    /* numbers */
    {B_PLAIN, "\"pad_len\":3", "\"pad_len\":64", GOOD},
    {B_PLAIN, "\"pad_len\":3", "\"pad_len\":0", GOOD},
    {B_PLAIN, "\"pad_len\":3", "\"pad_len\":65", RNG},
    {B_PLAIN, "\"pad_len\":3", "\"pad_len\":99999999999999999999", RNG},
    {B_PLAIN, "\"pad_len\":3", "\"pad_len\":4294967296", RNG},
    {B_PLAIN, "\"pad_len\":3", "\"pad_len\":4294967295", RNG},
    {B_PLAIN, "\"pad_len\":3", "\"pad_len\":007", SYN},
    {B_PLAIN, "\"pad_len\":3", "\"pad_len\":00", SYN},
    {B_PLAIN, "\"pad_len\":3", "\"pad_len\":-1", SYN},
    {B_PLAIN, "\"pad_len\":3", "\"pad_len\":+1", SYN},
    {B_PLAIN, "\"pad_len\":3", "\"pad_len\":3.5", FLT},
    {B_PLAIN, "\"pad_len\":3", "\"pad_len\":3.", FLT},
    {B_PLAIN, "\"pad_len\":3", "\"pad_len\":3e2", FLT},
    {B_PLAIN, "\"pad_len\":3", "\"pad_len\":3E2", FLT},
    {B_PLAIN, "\"pad_len\":3", "\"pad_len\":0.5", FLT},
    {B_PLAIN, "\"pad_len\":3", "\"pad_len\":99.5", FLT},
    {B_PLAIN, "\"pad_len\":3", "\"pad_len\":", SYN},
    {B_PLAIN, "\"pad_len\":3", "\"pad_len\":x", SYN},
    {B_PLAIN, "\"pad_len\":3", "\"pad_len\":null", SYN},
    {B_PLAIN, "\"pad_len\":3", "\"pad_len\":\"3\"", SYN},
    {B_PLAIN, "\"pad_len\":3", "\"pad_len\":3f", SYN},
    {B_PLAIN, "\"countdown_ms\":null", "\"countdown_ms\":0", RNG},
    {B_PLAIN, "\"countdown_ms\":null", "\"countdown_ms\":300000", GOOD},
    {B_PLAIN, "\"countdown_ms\":null", "\"countdown_ms\":300001", RNG},
    {B_PLAIN, "\"countdown_ms\":null", "\"countdown_ms\":1", GOOD},
    {B_PLAIN, "\"countdown_ms\":null", "\"countdown_ms\":nul", SYN},
    {B_PLAIN, "\"countdown_ms\":null", "\"countdown_ms\":nullx", SYN},
    {B_CHOOSE, "\"size\":2", "\"size\":7", GOOD},
    {B_CHOOSE, "\"size\":2", "\"size\":8", RNG},
    {B_CHOOSE, "\"free\":0", "\"free\":65535", GOOD},
    {B_CHOOSE, "\"free\":0", "\"free\":65536", RNG},
    /* booleans */
    {B_OPENED, "\"first_time\":true", "\"first_time\":false", GOOD},
    {B_OPENED, "\"first_time\":true", "\"first_time\":True", SYN},
    {B_OPENED, "\"first_time\":true", "\"first_time\":1", SYN},
    {B_OPENED, "\"first_time\":true", "\"first_time\":tru", SYN},
    {B_OPENED, "\"first_time\":true", "\"first_time\":null", SYN},
    {B_OPENED, "\"first_time\":true", "\"first_time\":", SYN},
    {B_PLAIN, "\"pad_len\":3", "\"pad_len\":3:", SYN},
    {B_PLAIN, "\"pad_len\":3", "\"pad_len\"3", SYN},
    {B_PLAIN, "\"countdown_ms\":null", "\"countdown_ms\"null", SYN},
    {B_PLAIN, "\"banners\":[]", "\"banners\":]", SYN},
    {B_PLAIN, "\"banners\":[]", "\"banners\":", SYN},
    {B_PLAIN, "\"banners\":[]", "\"banners\":,", SYN},
    {B_PLAIN, "\"notice\":null", "\"notice\":", SYN},
    {B_NOTICE, "\"notice\":{\"kind\"", "\"notice\":\"kind\"", SYN},
    {B_PLAIN, "\"pad_len\":3", "\"pad_len\":3/", SYN},
    {B_PLAIN, "\"lang\":\"bg\"", "\"lang\":\"\"", ENM},
    {B_OPENED, "\"locker\":12", "\"locker\":999", GOOD},
    {B_OPENED, "\"locker\":12", "\"locker\":1000", RNG},
    /* the notice */
    {B_PLAIN, "\"notice\":null", "\"notice\":nul", SYN},
    {B_PLAIN, "\"notice\":null", "\"notice\":{}", SYN},
    {B_PLAIN, "\"notice\":null", "\"notice\":[]", SYN},
    {B_PLAIN, "\"notice\":null", "\"notice\":0", SYN},
    {B_NOTICE, "\"dismiss\":\"overlay\"", "\"dismiss\":null", NOD},
    {B_NOTICE, "\"dismiss\":\"overlay\",", "", NOD},
    {B_NOTICE, "\"dismiss\":\"overlay\"", "\"dismiss\":\"zzz\"", ENM},
    {B_NOTICE, "\"dismiss\":\"overlay\"", "\"dismiss\":3", NOD},
    {B_NOTICE, "\"dismiss\":\"overlay\"", "\"dismissal\":\"overlay\"", NOD},
    {B_NOTICE, "\"dismiss\":\"overlay\"", "dismiss:\"overlay\"", NOD},
    {B_NOTICE, "\"kind\":\"dialog\",\"dismiss\":\"overlay\",\"phrase\":\"reject_invalid\",\"args\":{},\"warning\":false,\"countdown_ms\":8000", "\"kind\":\"dialog\"", NOD},
    {B_NOTICE, "\"kind\":\"dialog\",\"dismiss\":\"overlay\",", "\"dismiss\":\"overlay\",\"kind\":\"dialog\",", KEY},
    {B_NOTICE, "\"warning\":false,", "", KEY},
    {B_NOTICE, "\"countdown_ms\":8000", "\"countdown_ms\":0", RNG},
    {B_NOTICE, "\"countdown_ms\":8000", "\"countdown_ms\":null", GOOD},
    {B_NOTICE, "\"countdown_ms\":8000", "\"countdown_ms\":300000", GOOD},
    {B_NOTICE, "\"countdown_ms\":8000", "\"countdown_ms\":300001", RNG},
    {B_NOTICE, "\"countdown_ms\":8000", "\"countdown_ms\":8000.5", FLT},
    {B_NOTICE, "\"countdown_ms\":8000}", "\"countdown_ms\":8000", SYN},
    {B_NOTICE, "\"args\":{}", "\"args\":null", SYN},
    {B_NOTICE, "\"args\":{}", "\"args\":{\"status\":1}", SYN},
    {B_NOTICE, "\"args\":{}", "\"args\":[]", SYN},
    /* arguments follow the phrase */
    {B_FAULT, "\"locker\":12", "\"locker\":0", RNG},
    {B_FAULT, "\"locker\":12", "\"locker\":null", GOOD},
    {B_FAULT, "\"locker\":12", "\"locker\":65535", GOOD},
    {B_FAULT, "\"locker\":12", "\"locker\":65536", RNG},
    {B_FAULT, "\"fault\":\"relay_busy\",\"door\":\"maybe_opened\",\"locker\":12", "", SYN},
    {B_FAULT, "\"fault\":\"relay_busy\",\"door\":\"maybe_opened\"", "\"door\":\"maybe_opened\",\"fault\":\"relay_busy\"", KEY},
    {B_FAULT, "\"locker\":12", "\"locker\":12,\"x\":1", SYN},
    {B_FAULT, "\"door\":\"maybe_opened\"", "\"door\":\"zzz\"", ENM},
    {B_FAULT, "\"fault\":\"relay_busy\"", "\"fault\":\"relay_error\"", GOOD},
    {B_FAULT, "\"phrase\":\"fault\"", "\"phrase\":\"sync_rejected\"", KEY},
    {B_FAULT, "\"phrase\":\"fault\",\"args\":{\"fault\":\"relay_busy\",\"door\":\"maybe_opened\",\"locker\":12}", "\"phrase\":\"sync_rejected\",\"args\":{\"status\":65535}", GOOD},
    {B_FAULT, "\"phrase\":\"fault\",\"args\":{\"fault\":\"relay_busy\",\"door\":\"maybe_opened\",\"locker\":12}", "\"phrase\":\"sync_rejected\",\"args\":{\"status\":65536}", RNG},
    {B_FAULT, "\"phrase\":\"fault\",\"args\":{\"fault\":\"relay_busy\",\"door\":\"maybe_opened\",\"locker\":12}", "\"phrase\":\"sync_late\",\"args\":{\"hour\":23,\"minute\":59}", GOOD},
    {B_FAULT, "\"phrase\":\"fault\",\"args\":{\"fault\":\"relay_busy\",\"door\":\"maybe_opened\",\"locker\":12}", "\"phrase\":\"sync_late\",\"args\":{\"hour\":24,\"minute\":59}", RNG},
    {B_FAULT, "\"phrase\":\"fault\",\"args\":{\"fault\":\"relay_busy\",\"door\":\"maybe_opened\",\"locker\":12}", "\"phrase\":\"sync_late\",\"args\":{\"hour\":23,\"minute\":60}", RNG},
    {B_FAULT, "\"phrase\":\"fault\",\"args\":{\"fault\":\"relay_busy\",\"door\":\"maybe_opened\",\"locker\":12}", "\"phrase\":\"saved\",\"args\":{}", GOOD},
    /* banners */
    {B_BANNERS, "{\"id\":\"not_saved\"", "{\"id\":\"zzz\"", ENM},
    {B_BANNERS, "\"id\":\"not_saved\",\"phrase\":\"not_saved\"", "\"id\":\"sync\",\"phrase\":\"not_saved\"", ORD},
    {B_BANNERS, "\"id\":\"sync\",\"phrase\":\"sync_rejected\",\"args\":{\"status\":503}", "\"id\":\"not_saved\",\"phrase\":\"sync_rejected\",\"args\":{\"status\":503}", ORD},
    {B_BANNERS, "\"id\":\"sync\",\"phrase\":\"sync_rejected\",\"args\":{\"status\":503}", "\"id\":\"audit\",\"phrase\":\"sync_rejected\",\"args\":{\"status\":503}", GOOD},
    {B_BANNERS, "\"args\":{\"status\":503}", "\"args\":{}", SYN},
    {B_BANNERS, "},{\"id\":\"sync\"", "}{\"id\":\"sync\"", SYN},
    {B_BANNERS, "\"warning\":true}]", "\"warning\":true},]", SYN},
    {B_BANNERS, "\"warning\":true}]", "\"warning\":true}", SYN},
    {B_BANNERS, "\"banners\":[", "\"banners\":[,", SYN},
    {B_BANNERS, "\"banners\":[", "\"banners\":", SYN},
    {B_BANNERS, "\"banners\":[", "\"banners\":null", SYN},
    {B_BANNERS, "\"banners\":[", "\"banners\":{", SYN},
    {B_BANNERS, "{\"id\":\"not_saved\",\"phrase\":\"not_saved\",\"args\":{},\"warning\":false}", "[]", SYN},
    {B_BANNERS, "{\"id\":\"not_saved\",\"phrase\":\"not_saved\",\"args\":{},\"warning\":false},", "", GOOD},
    {B_BANNERS, "{\"id\":\"not_saved\",\"phrase\":\"not_saved\",\"args\":{},\"warning\":false}", "{\"id\":\"not_saved\",\"phrase\":\"not_saved\",\"args\":{},\"warning\":false,\"x\":1}", SYN},
    /* lists of sizes */
    {B_CHOOSE, "\"sizes\":[{\"size\":0,\"free\":3},{\"size\":2,\"free\":0}]", "\"sizes\":[]", GOOD},
    {B_CHOOSE, "\"sizes\":[{\"size\":0,\"free\":3},{\"size\":2,\"free\":0}]", "\"sizes\":[{\"size\":0,\"free\":0},{\"size\":1,\"free\":0},{\"size\":2,\"free\":0},{\"size\":3,\"free\":0}]", GOOD},
    {B_CHOOSE, "\"sizes\":[{\"size\":0,\"free\":3},{\"size\":2,\"free\":0}]", "\"sizes\":[{\"size\":0,\"free\":0},{\"size\":1,\"free\":0},{\"size\":2,\"free\":0},{\"size\":3,\"free\":0},{\"size\":4,\"free\":0}]", RNG},
    {B_CHOOSE, "{\"size\":2,\"free\":0}", "{\"size\":2,\"free\":0,\"x\":0}", SYN},
    {B_CHOOSE, "{\"size\":2,\"free\":0}", "{\"free\":0,\"size\":2}", KEY},
    {B_CHOOSE, "{\"size\":2,\"free\":0}", "{\"size\":2}", SYN},
};

static void t_the_text_is_judged_row_by_row(ctest_t *t) {
    static ui_view_t v;
    for (uint32_t i = 0; i < sizeof ROWS / sizeof ROWS[0]; i++) {
        const row_t *r = &ROWS[i];
        const char *text = urig_edit(base(r->base), r->old, r->rep);
        CHECK(t, text != NULL);
        if (text == NULL) {
            printf("row %u: the edit did not apply\n", i);
            continue;
        }
        ui_rule_t got = parse(t, text, &v, NULL);
        if (got != r->rule) {
            printf("row %u: got %d, want %d: %s\n", i, (int)got, (int)r->rule, text);
        }
        CHECK_EQ_I64(t, got, r->rule);
    }
}

static void t_every_screen_has_its_own_fields(ctest_t *t) {
    static ui_view_t v;
    const char *shapes[][2] = {{"splash", ""},
                               {"welcome", "\"pad_len\":3"},
                               {"choose", "\"sizes\":[]"},
                               {"opened", "\"locker\":3,\"first_time\":false"},
                               {"shift", "\"done\":1,\"total\":2"},
                               {"report", "\"released\":1,\"write_failed\":true"},
                               {"lockout", ""},
                               {"fault_storage", "\"fault\":\"relay_busy\""},
                               {"fault_relay", "\"fault\":\"relay_error\""}};
    for (uint32_t i = 0; i < 9U; i++) {
        const char *text = urig_screen(shapes[i][0], "bg", shapes[i][1], "null", "");
        CHECK_EQ_I64(t, parse(t, text, &v, NULL), UI_R_NONE);
        CHECK_EQ_U64(t, v.screen, i);
        /* another screen's fields are not accepted here */
        const char *other = urig_screen(shapes[i][0], "bg", shapes[(i + 1U) % 9U][1], "null", "");
        CHECK_EQ_I64(t, parse(t, other, &v, NULL), (shapes[(i + 1U) % 9U][1][0] == '\0' && shapes[i][1][0] == '\0') || i == 7U ? UI_R_NONE : UI_R_KEY);
    }
    CHECK_EQ_I64(t, parse(t, urig_screen("shift", "en", "\"done\":1,\"total\":2", "null", ""), &v, NULL), UI_R_NONE);
    CHECK_EQ_U64(t, v.lang, 1);
    CHECK_EQ_I64(t, parse(t, urig_screen("report", "bg", "\"released\":1", "null", ""), &v, NULL), UI_R_KEY); /* a field of the case missing */
}

static void t_the_view_carries_what_the_rules_need(ctest_t *t) {
    static ui_view_t v;
    const char *text = base(B_NOTICE);
    CHECK_EQ_I64(t, parse(t, text, &v, NULL), UI_R_NONE);
    CHECK_EQ_U64(t, v.screen, 1);
    CHECK_EQ_U64(t, v.lang, 0);
    CHECK_EQ_U64(t, v.has_notice, 1);
    CHECK_EQ_U64(t, v.n_kind, 0);
    CHECK_EQ_U64(t, v.n_dismiss, 0);
    CHECK_EQ_U64(t, v.n_phrase, 0);
    CHECK_EQ_U64(t, v.n_countdown_ms, 8000);
    CHECK_EQ_U64(t, v.n_banners, 0);
    CHECK_EQ_U64(t, v.notice_off, (uint64_t)(strstr(text, NOTICE_OK) - text));
    CHECK_EQ_U64(t, v.notice_len, strlen(NOTICE_OK));
    CHECK_EQ_U64(t, v.n_cd_off, (uint64_t)(strstr(text, "8000") - text));
    CHECK_EQ_U64(t, v.n_cd_len, 4);
    text = base(B_FAULT);
    CHECK_EQ_I64(t, parse(t, text, &v, NULL), UI_R_NONE);
    CHECK_EQ_U64(t, v.n_kind, 2);    /* snackbar */
    CHECK_EQ_U64(t, v.n_dismiss, 3); /* banner_sync */
    CHECK_EQ_U64(t, v.n_phrase, 7);  /* fault */
    CHECK_EQ_U64(t, v.n_countdown_ms, 0);
    CHECK_EQ_U64(t, v.n_cd_len, 4); /* null */
    CHECK_EQ_STR(t, text + v.n_cd_off, "null},\"banners\":[]}");
    CHECK_EQ_U64(t, v.notice_len, strlen(FAULT_NOTICE));
    text = base(B_BANNERS);
    CHECK_EQ_I64(t, parse(t, text, &v, NULL), UI_R_NONE);
    CHECK_EQ_U64(t, v.lang, 1);
    CHECK_EQ_U64(t, v.has_notice, 0);
    CHECK_EQ_U64(t, v.notice_len, 0);
    CHECK_EQ_U64(t, v.n_banners, 2);
    CHECK_EQ_U64(t, v.banner_id[0], 0);
    CHECK_EQ_U64(t, v.banner_id[1], 2);
    CHECK_EQ_U64(t, v.banner_phrase[0], 3);
    CHECK_EQ_U64(t, v.banner_phrase[1], 5);
    CHECK_EQ_I64(t, parse(t, base(B_PLAIN), &v, NULL), UI_R_NONE);
    CHECK_EQ_U64(t, v.has_notice, 0);
    CHECK_EQ_U64(t, v.n_banners, 0);
    CHECK_EQ_U64(t, v.n_cd_len, 0);
    /* four banners are the most; a list element is a fresh object (its id is not the previous one's) */
    text = urig_welcome("bg", "null", "{\"id\":\"not_saved\",\"phrase\":\"saved\",\"args\":{},\"warning\":false},{\"id\":\"audit\",\"phrase\":\"audit\",\"args\":{},\"warning\":false},{\"id\":\"sync\",\"phrase\":\"saved\",\"args\":{},\"warning\":false}");
    CHECK_EQ_I64(t, parse(t, text, &v, NULL), UI_R_NONE);
    CHECK_EQ_U64(t, v.n_banners, 3);
    CHECK_EQ_U64(t, v.banner_id[2], 2);
    CHECK_EQ_U64(t, v.banner_phrase[1], 4);
}

static void t_a_failed_parse_says_where_it_stopped(ctest_t *t) {
    static ui_view_t v;
    uint32_t at = 99;
    const char *text = urig_edit(base(B_PLAIN), "[]}", "[]}x");
    CHECK_EQ_I64(t, parse(t, text, &v, &at), UI_R_SYNTAX);
    CHECK_EQ_U64(t, at, strlen(text) - 1U);
    text = urig_edit(base(B_PLAIN), "\"lang\":\"bg\"", "\"lang\":\"zzz\"");
    CHECK_EQ_I64(t, parse(t, text, &v, &at), UI_R_ENUM);
    CHECK_EQ_U64(t, at, (uint64_t)(strstr(text, "zzz") - text) + 4U); /* after the closing quote */
    text = urig_edit(base(B_PLAIN), "\"pad_len\":3", "\"pad_len\":65");
    CHECK_EQ_I64(t, parse(t, text, &v, &at), UI_R_RANGE);
    CHECK_EQ_U64(t, at, (uint64_t)(strstr(text, "65") - text) + 2U);
    text = urig_edit(base(B_PLAIN), "\"pad_len\":3", "\"pad_len\":3.5");
    CHECK_EQ_I64(t, parse(t, text, &v, &at), UI_R_FLOAT);
    CHECK_EQ_U64(t, at, (uint64_t)(strstr(text, "3.5") - text) + 1U);
    CHECK_EQ_I64(t, parse(t, " {}", &v, &at), UI_R_SYNTAX);
    CHECK_EQ_U64(t, at, 0);
    CHECK_EQ_I64(t, parse(t, "{\"x\":1}", &v, &at), UI_R_KEY);
    CHECK_EQ_U64(t, at, 5); /* after the key and its colon */
    CHECK_EQ_I64(t, parse(t, base(B_PLAIN), &v, &at), UI_R_NONE);
    CHECK_EQ_U64(t, at, strlen(base(B_PLAIN)));
    CHECK_EQ_I64(t, parse(t, "", &v, &at), UI_R_SYNTAX);
    CHECK_EQ_U64(t, at, 0);
    CHECK_EQ_I64(t, parse(t, "{", &v, &at), UI_R_SYNTAX);
    CHECK_EQ_U64(t, at, 1);
    CHECK_EQ_I64(t, parse(t, base(B_NOTICE), &v, NULL), UI_R_NONE); /* `at` may be NULL */
}

static void t_arguments_that_cannot_be_parsed_are_refused_and_out_is_cleared(ctest_t *t) {
    static ui_view_t v;
    static uint8_t big[UI_VIEW_MAX + 8];
    const ui_schema_t *s = urig_schema(t);
    const char *good = base(B_NOTICE);
    uint32_t at = 7;
    CHECK_EQ_I64(t, ui_parse(s, (const uint8_t *)good, (uint32_t)strlen(good), NULL, NULL), UI_R_SYNTAX);
    CHECK_EQ_I64(t, ui_parse(s, (const uint8_t *)good, (uint32_t)strlen(good), &v, NULL), UI_R_NONE);
    CHECK_EQ_U64(t, v.has_notice, 1);
    CHECK_EQ_I64(t, ui_parse(NULL, (const uint8_t *)good, (uint32_t)strlen(good), &v, &at), UI_R_SYNTAX);
    CHECK_EQ_U64(t, at, 0);
    CHECK_EQ_U64(t, v.has_notice, 0); /* out is cleared first */
    CHECK_EQ_I64(t, ui_parse(s, NULL, 5, &v, &at), UI_R_SYNTAX);
    /* the longest text is 4096 bytes: a garbage view of that size is judged, one byte more is refused before it is read */
    memset(big, ' ', sizeof big);
    memcpy(big, "{\"screen\":\"zzz\"", 15);
    CHECK_EQ_I64(t, ui_parse(s, big, UI_VIEW_MAX, &v, &at), UI_R_FULL_SCREEN);
    CHECK_EQ_U64(t, at, 15);
    CHECK_EQ_I64(t, ui_parse(s, big, UI_VIEW_MAX + 1U, &v, &at), UI_R_SYNTAX);
    CHECK_EQ_U64(t, at, 0);
}

/* The view is `len` bytes of a longer buffer: what is past `len` is the buffer's, not the view's, and must not be read. */
static ui_rule_t parse_cut(ctest_t *t, const char *text, const char *at_end_of, uint32_t extra, uint32_t *at) {
    static ui_view_t v;
    const char *cut = strstr(text, at_end_of);
    CHECK(t, cut != NULL);
    return ui_parse(urig_schema(t), (const uint8_t *)text, (uint32_t)(cut - text) + (uint32_t)strlen(at_end_of) + extra, &v, at);
}

static void t_bytes_past_the_length_are_not_read(ctest_t *t) {
    uint32_t at;
    /* before the last brace */
    CHECK_EQ_I64(t, parse_cut(t, base(B_PLAIN), "\"banners\":[]", 0, &at), UI_R_SYNTAX);
    CHECK_EQ_U64(t, at, strlen(base(B_PLAIN)) - 1U);
    /* right after `true`, and in the middle of it */
    CHECK_EQ_I64(t, parse_cut(t, base(B_OPENED), "\"first_time\":true", 0, &at), UI_R_SYNTAX);
    CHECK_EQ_U64(t, at, (uint64_t)(strstr(base(B_OPENED), "true") - base(B_OPENED)) + 4U);
    CHECK_EQ_I64(t, parse_cut(t, base(B_OPENED), "\"first_time\":tru", 0, &at), UI_R_SYNTAX);
    CHECK_EQ_U64(t, at, (uint64_t)(strstr(base(B_OPENED), "true") - base(B_OPENED)));
    /* in the middle of an enum text */
    CHECK_EQ_I64(t, parse_cut(t, base(B_PLAIN), "\"lang\":\"b", 0, &at), UI_R_SYNTAX);
    CHECK_EQ_U64(t, at, (uint64_t)(strstr(base(B_PLAIN), "bg") - base(B_PLAIN)) + 1U);
    /* in the middle of a number, and before a fraction */
    const char *twelve = urig_screen("welcome", "bg", "\"pad_len\":12", "null", "");
    CHECK_EQ_I64(t, parse_cut(t, twelve, "\"pad_len\":1", 0, &at), UI_R_SYNTAX);
    CHECK_EQ_U64(t, at, (uint64_t)(strstr(twelve, "12") - twelve) + 1U);
    const char *half = urig_edit(base(B_PLAIN), "\"pad_len\":3", "\"pad_len\":3.5");
    CHECK_EQ_I64(t, parse_cut(t, half, "\"pad_len\":3", 0, &at), UI_R_SYNTAX);
    CHECK_EQ_U64(t, at, (uint64_t)(strstr(half, "3.5") - half) + 1U);
    /* after the opening bracket of a list */
    CHECK_EQ_I64(t, parse_cut(t, base(B_PLAIN), "\"banners\":[", 0, &at), UI_R_SYNTAX);
    CHECK_EQ_U64(t, at, strlen(base(B_PLAIN)) - 2U);
    /* null in the middle */
    CHECK_EQ_I64(t, parse_cut(t, base(B_PLAIN), "\"countdown_ms\":nul", 0, &at), UI_R_SYNTAX);
    CHECK_EQ_U64(t, at, (uint64_t)(strstr(base(B_PLAIN), "null,\"pad") - base(B_PLAIN)));
}

CTEST_SUITE("ui_parse",
    { "past_len", t_bytes_past_the_length_are_not_read },
    { "rows", t_the_text_is_judged_row_by_row },
    { "screens", t_every_screen_has_its_own_fields },
    { "view", t_the_view_carries_what_the_rules_need },
    { "at", t_a_failed_parse_says_where_it_stopped },
    { "arguments", t_arguments_that_cannot_be_parsed_are_refused_and_out_is_cleared })
