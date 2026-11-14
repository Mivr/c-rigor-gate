/* The schema parser through ui_schema_parse: the fixture schema parses, and every way of writing a bad one is refused with its error and line. */
#include <stdio.h>
#include <string.h>

#include "sim/inv/tests/ui_rig.h"

static ui_schema_t S;

#define V24 "a1 a2 a3 a4 a5 a6 a7 a8 a9 a10 a11 a12 a13 a14 a15 a16 a17 a18 a19 a20 a21 a22 a23 a24"

typedef struct {
    const char *old, *rep;
    const char *old2, *rep2; /* a second edit of the result, or NULL */
    const char *at;          /* the line expected is the line of this text in the fixture (old when NULL) */
    int err, delta;          /* the error and the lines after `at`; delta < 0: the whole schema (line 0) */
} row_t;

#define OK UI_SE_OK
#define SYN UI_SE_SYNTAX
#define LIM UI_SE_LIMIT
#define DUP UI_SE_DUPLICATE
#define REF UI_SE_REF
#define CTX UI_SE_CONTEXT
#define ROL UI_SE_ROLE
#define INC UI_SE_INCOMPLETE

static const row_t ROWS[] = {
    /* enums */
    {"enum lang bg en\n", "enum Lang bg en\n", 0, 0, 0, SYN, 0},
    {"enum lang bg en\n", "enum lang\n", 0, 0, 0, SYN, 0},
    {"enum lang bg en\n", "enum lang bg Bg\n", 0, 0, 0, SYN, 0},
    {"enum lang bg en\n", "enum lang bg bg\n", 0, 0, 0, DUP, 0},
    {"enum lang bg en\n", "enum lang bg en\nenum lang x y\n", 0, 0, 0, DUP, 1},
    {"object sizeitem\n", "object sizeitem\nenum zz a\n", 0, 0, 0, CTX, 1},
    {"enum door nothing_opened maybe_opened opened\n", "enum door nothing_opened maybe_opened opened\nenum x1 a\nenum x2 a\n", 0, 0, 0, OK, -1},
    {"enum door nothing_opened maybe_opened opened\n", "enum door nothing_opened maybe_opened opened\nenum x1 a\nenum x2 a\nenum x3 a\n", 0, 0, 0, LIM, 3},
    {"enum lang bg en\n", "enum lang bg en\nenum x1 " V24 "\n", 0, 0, 0, OK, -1},
    {"enum lang bg en\n", "enum lang bg en\nenum x1 " V24 " a25\n", 0, 0, 0, LIM, 1},
    /* objects */
    {"object view\n", "object View\n", 0, 0, 0, SYN, 0},
    {"object view\n", "object view x\n", 0, 0, 0, SYN, 0},
    {"object banner\n", "object banner\nobject q\n", 0, 0, 0, CTX, 1},
    {"object view\n", "object sizeitem\nend\nobject view\n", 0, 0, 0, DUP, 0},
    {"object view\n", "object zz\nend\nobject view\n", 0, 0, 0, LIM, 2},
    {"top view\n", "end x\ntop view\n", 0, 0, 0, SYN, 0},
    {"top view\n", "end\ntop view\n", 0, 0, 0, CTX, 0},
    {"  endswitch\n  field notice", "  end\n  field notice", 0, 0, 0, CTX, 0},
    /* fields */
    {"top view\n", "field x bool\ntop view\n", 0, 0, 0, CTX, 0},
    {"  field size uint 7\n", "  field size\n", 0, 0, 0, SYN, 0},
    {"  field size uint 7\n", "  field Size uint 7\n", 0, 0, 0, SYN, 0},
    {"  field size uint 7\n", "  field size uint\n", 0, 0, 0, SYN, 0},
    {"  field size uint 7\n", "  field size uint x\n", 0, 0, 0, SYN, 0},
    {"  field size uint 7\n", "  field size uint 7 nul\n", 0, 0, 0, SYN, 0},
    {"  field size uint 7\n", "  field size uint 7 null x\n", 0, 0, 0, SYN, 0},
    {"  field size uint 7\n", "  field size uint 1234567890\n", 0, 0, 0, SYN, 0},
    {"  field size uint 7\n", "  field size uint 123456789\n", 0, 0, 0, OK, -1},
    {"  field size uint 7\n", "  field size uint 7 null\n", 0, 0, 0, OK, -1},
    {"  field first_time bool\n", "  field first_time bool x\n", 0, 0, 0, SYN, 0},
    {"  field first_time bool\n", "  field first_time float\n", 0, 0, 0, SYN, 0},
    {"  field kind enum nkind\n", "  field kind enum nokind\n", 0, 0, 0, REF, 0},
    {"  field kind enum nkind\n", "  field kind enum nkind x\n", 0, 0, 0, SYN, 0},
    {"  field kind enum nkind\n", "  field kind enum\n", 0, 0, 0, SYN, 0},
    {"  field args obj args by phrase\n", "  field args obj nope by phrase\n", 0, 0, 0, REF, 0},
    {"  field args obj args by phrase\n", "  field args obj args\n", 0, 0, 0, REF, 0},
    {"  field args obj args by phrase\n", "  field args obj args by\n", 0, 0, 0, REF, 0},
    {"  field args obj args by phrase\n", "  field args obj args by nokey\n", 0, 0, 0, REF, 0},
    {"  field args obj args by phrase\n", "  field args obj args by kind\n", 0, 0, 0, REF, 0},
    {"  field args obj args by phrase\n", "  field args obj args by phrase junk\n", 0, 0, 0, SYN, 0},
    {"  field args obj args by phrase\n", "  field args obj args by phrase null\n", 0, 0, 0, OK, -1},
    {"  field args obj args by phrase\n", "  field args obj args null by phrase\n", 0, 0, 0, SYN, 0},
    {"  field args obj args by phrase\n", "  field args obj banner\n", 0, 0, 0, REF, 0},
    {"  field args obj args by phrase\n", "  field args obj\n", 0, 0, 0, SYN, 0},
    {"  field notice obj notice null\n", "  field notice obj notice by lang null\n", 0, 0, 0, REF, 0},
    {"  field notice obj notice null\n", "  field notice obj notice by countdown_ms null\n", 0, 0, 0, REF, 0},
    {"  field size uint 7\n", "  field me obj sizeitem\n", 0, 0, 0, REF, 0},
    {"  field sizes list sizeitem 4\n", "  field sizes list sizeitem\n", 0, 0, 0, SYN, 0},
    {"  field sizes list sizeitem 4\n", "  field sizes list sizeitem 0\n", 0, 0, 0, SYN, 0},
    {"  field sizes list sizeitem 4\n", "  field sizes list sizeitem x\n", 0, 0, 0, SYN, 0},
    {"  field sizes list sizeitem 4\n", "  field sizes list sizeitem 256\n", 0, 0, 0, LIM, 0},
    {"  field sizes list sizeitem 4\n", "  field sizes list sizeitem 255\n", 0, 0, 0, OK, -1},
    {"  field sizes list sizeitem 4\n", "  field sizes list sizeitem 1\n", 0, 0, 0, OK, -1},
    {"  field sizes list sizeitem 4\n", "  field sizes list nope 4\n", 0, 0, 0, REF, 0},
    {"  field sizes list sizeitem 4\n", "  field sizes list sizeitem 4 x\n", 0, 0, 0, SYN, 0},
    {"  field size uint 7\n", "  field size uint 7\n  field size bool\n", 0, 0, 0, DUP, 1},
    {"  on fault_relay\n  field fault enum fault\n", "  on fault_relay\n  field fault enum fault\n  field fault bool\n", 0, 0, 0, DUP, 2},
    {"  endswitch\n  field notice obj", "  endswitch\n  field pad_len bool\n  field notice obj", 0, 0, 0, DUP, 1},
    {"  on welcome\n  field pad_len", "  on welcome\n  field screen bool\n  field pad_len", 0, 0, 0, DUP, 1},
    {"  switch screen\n  on welcome\n", "  switch screen\n  field zz bool\n  on welcome\n", 0, 0, 0, CTX, 1},
    /* switches */
    {"  switch screen\n", "  switch screen\n  switch lang\n", 0, 0, 0, CTX, 1},
    {"top view\n", "switch screen\ntop view\n", 0, 0, 0, CTX, 0},
    {"  switch screen\n", "  switch\n", 0, 0, 0, SYN, 0},
    {"  switch screen\n", "  switch screen lang bg\n", 0, 0, 0, SYN, 0},
    {"  switch @ phrase\n", "  switch @ nokind\n", 0, 0, 0, REF, 0},
    {"  switch screen\n", "  switch @\n", 0, 0, 0, REF, 0},
    {"  switch screen\n", "  switch nokey\n", 0, 0, 0, REF, 0},
    {"  switch screen\n", "  switch countdown_ms\n", 0, 0, 0, REF, 0},
    {"  switch @ phrase\n", "  switch @ phrase extra\n", 0, 0, 0, SYN, 0},
    {"  endswitch\nend\nobject notice\n", "  endswitch\n  switch @ fault\n  endswitch\nend\nobject notice\n", 0, 0, "  endswitch\nend\nobject notice\n", REF, 1},
    {"  endswitch\nend\nobject notice\n", "  endswitch\n  switch @ phrase\n  on saved\n  field zz bool\n  endswitch\nend\nobject notice\n", 0, 0, 0, OK, -1},
    {"  on welcome\n", "  on nokind\n", 0, 0, 0, REF, 0},
    {"  on welcome\n", "  on\n", 0, 0, 0, SYN, 0},
    {"  on welcome\n", "  on welcome extra\n", 0, 0, 0, SYN, 0},
    {"top view\n", "on welcome\ntop view\n", 0, 0, 0, CTX, 0},
    {"object banner\n", "object banner\non x\n", 0, 0, 0, CTX, 1},
    {"top view\n", "endswitch\ntop view\n", 0, 0, 0, CTX, 0},
    {"  endswitch\n  field notice", "  endswitch x\n  field notice", 0, 0, 0, SYN, 0},
    /* top */
    {"top view\n", "top\n", 0, 0, 0, SYN, 0},
    {"top view\n", "top view x\n", 0, 0, 0, SYN, 0},
    {"top view\n", "top view\ntop view\n", 0, 0, 0, DUP, 1},
    {"top view\n", "top nope\n", 0, 0, 0, REF, 0},
    {"top view\n", "", 0, 0, "top view\n", INC, -1},
    {"object banner\n", "object banner\ntop view\n", 0, 0, 0, CTX, 1},
    /* roles */
    {"role lang view lang\n", "role lang view\n", 0, 0, 0, SYN, 0},
    {"role lang view lang\n", "role nope view lang\n", 0, 0, 0, SYN, 0},
    {"role lang view lang\n", "role lang nope lang\n", 0, 0, 0, REF, 0},
    {"role lang view lang\n", "role lang view nope\n", 0, 0, 0, REF, 0},
    {"role lang view lang\n", "role lang view lang\nrole lang view lang\n", 0, 0, 0, ROL, 1},
    {"role lang view lang\n", "role lang view screen\n", 0, 0, 0, ROL, 0},
    {"role lang view lang\n", "role lang view notice\n", 0, 0, 0, ROL, 0},
    {"object banner\n", "object banner\nrole lang view lang\n", 0, 0, 0, CTX, 1},
    {"  field countdown_ms uint 300000 null\nend\nobject banner", "  field countdown_ms uint 300000\nend\nobject banner", 0, 0, "role n_countdown", ROL, 0},
    {"  field notice obj notice null\n", "  field notice obj notice\n", 0, 0, "role notice view", ROL, 0},
    {"role b_phrase banner phrase\n", "role b_phrase view fault\n", 0, 0, 0, ROL, 0},
    {"role b_phrase banner phrase\n", "", 0, 0, 0, INC, -1},
    {"role notice view notice\n", "", 0, 0, 0, INC, -1},
    {"role banners view banners\n", "", 0, 0, 0, INC, -1},
    {"role n_phrase notice phrase\n", "", 0, 0, 0, INC, -1},
    {"role n_countdown notice countdown_ms\n", "", 0, 0, 0, INC, -1},
    {"role lang view lang\n", "role lang notice tone\n", "  field countdown_ms uint 300000 null\nend\nobject banner", "  field countdown_ms uint 300000 null\n  field tone enum lang\nend\nobject banner", "role lang view lang\n", ROL, -1},
    {"role n_kind notice kind\n", "role n_kind banner tone\n", "  field warning bool\nend\nobject view", "  field warning bool\n  field tone enum nkind\nend\nobject view", "role n_kind notice kind\n", ROL, -1},
    {"role b_id banner id\n", "role b_id notice tone\n", "  field countdown_ms uint 300000 null\nend\nobject banner", "  field countdown_ms uint 300000 null\n  field tone enum bannerid\nend\nobject banner", "role b_id banner id\n", ROL, -1},
    {"  field banners list banner 4\n", "  field banners list banner 9\n", 0, 0, "role banners", ROL, -1},
    {"  field banners list banner 4\n", "  field banners list banner 8\n", 0, 0, 0, OK, -1},
    {"role screen view screen\n", "bannerdismiss not_saved banner_not_saved\nrole screen view screen\n", 0, 0, 0, REF, 0},
    {"role screen view screen\n", "idle welcome\nrole screen view screen\n", 0, 0, 0, REF, 0},
    /* banner dismiss */
    {"bannerdismiss audit banner_audit\n", "bannerdismiss audit\n", 0, 0, 0, SYN, 0},
    {"bannerdismiss audit banner_audit\n", "bannerdismiss nope banner_audit\n", 0, 0, 0, REF, 0},
    {"bannerdismiss audit banner_audit\n", "bannerdismiss audit nope\n", 0, 0, 0, REF, 0},
    {"bannerdismiss audit banner_audit\n", "bannerdismiss audit banner_audit\nbannerdismiss audit banner_sync\n", 0, 0, 0, DUP, 1},
    {"bannerdismiss sync banner_sync\n", "", 0, 0, 0, INC, -1},
    {"bannerdismiss not_saved banner_not_saved\n", "", 0, 0, 0, INC, -1},
    /* forbid, idle, language, expiring */
    {"forbid message text title\n", "forbid\n", 0, 0, 0, SYN, 0},
    {"forbid message text title\n", "forbid Bad\n", 0, 0, 0, SYN, 0},
    {"forbid message text title\n", "forbid a b c d e\n", 0, 0, 0, LIM, 0},
    {"forbid message text title\n", "forbid a b c d\n", 0, 0, 0, OK, -1},
    {"forbid message text title\n", "forbid a b c\nforbid d e\n", 0, 0, 0, LIM, 1},
    {"forbid message text title\n", "forbid a b\nforbid c d\n", 0, 0, 0, OK, -1},
    {"idle welcome\n", "idle\n", 0, 0, 0, SYN, 0},
    {"idle welcome\n", "idle nope\n", 0, 0, 0, REF, 0},
    {"idle welcome\n", "idle welcome\nidle choose\n", 0, 0, 0, DUP, 1},
    {"idle welcome\n", "", 0, 0, 0, INC, -1},
    {"lang_default bg\n", "lang_default\n", 0, 0, 0, SYN, 0},
    {"lang_default bg\n", "lang_default nope\n", 0, 0, 0, REF, 0},
    {"lang_default bg\n", "lang_default bg\nlang_default en\n", 0, 0, 0, DUP, 1},
    {"lang_default bg\n", "", 0, 0, 0, INC, -1},
    {"expiring dialog snackbar\n", "expiring\n", 0, 0, 0, SYN, 0},
    {"expiring dialog snackbar\n", "expiring dialog nope\n", 0, 0, 0, REF, 0},
    {"expiring dialog snackbar\n", "expiring dialog snackbar banner\n", 0, 0, 0, OK, -1},
    {"expiring dialog snackbar\n", "expiring dialog\nexpiring banner\n", 0, 0, 0, OK, -1},
    {"expiring dialog snackbar\n", "", 0, 0, 0, INC, -1},
    /* names that look like the first one, or the first object, or the first enum value */
    {"enum lang bg en\n", "enum screen x y\nenum lang bg en\n", 0, 0, 0, DUP, 0},
    {"role screen view screen\n", "expiring dialog snackbar\nrole screen view screen\n", 0, 0, 0, REF, 0},
    {"role screen view screen\n", "lang_default bg\nrole screen view screen\n", 0, 0, 0, REF, 0},
    {"enum lang bg en\n", "enum nkind x y\nenum lang bg en\n", 0, 0, 0, DUP, 2},
    {"object sizeitem\n", "object sizeitem\nobject q\n", 0, 0, 0, CTX, 1},
    {"object sizeitem\n", "object sizeitem\ntop view\n", 0, 0, 0, CTX, 1},
    {"object sizeitem\n", "object sizeitem\nrole lang view lang\n", 0, 0, 0, CTX, 1},
    {"  switch screen\n  on welcome\n", "  switch screen\n  on splash\n  field zz bool\n  on welcome\n", 0, 0, 0, OK, -1},
    {"object sizeitem\n", "object sizeitem\n  switch @ screen\n  on lockout\n  field zz bool\n  endswitch\n", 0, 0, 0, OK, -1},
    {"  switch screen\n  on welcome\n", "  switch lang\n  on bg\n  field zz bool\n  endswitch\n  switch screen\n  on welcome\n", 0, 0, 0, OK, -1},
    {"role lang view lang\n", "role lang sizeitem size\n", 0, 0, 0, ROL, 0},
    {"top view\n", "top sizeitem\n", 0, 0, 0, ROL, -1},
    {"enum screen splash welcome", "enum bannerid not_saved audit sync\nenum screen splash welcome", "enum bannerid not_saved audit sync\nenum phrase", "enum phrase", "enum screen", OK, -1},
    {"enum dismiss overlay banner_not_saved banner_audit banner_sync\n", "", "enum screen splash welcome", "enum dismiss overlay banner_not_saved banner_audit banner_sync\nenum screen splash welcome", "enum screen", OK, -1},
    {"enum nkind dialog banner snackbar\n", "", "enum screen splash welcome", "enum nkind dialog banner snackbar\nenum screen splash welcome", "enum screen", OK, -1},
    {"forbid message text title\n", "forbid a b c d\nforbid e\n", 0, 0, 0, LIM, 1},
    {"  field kind enum nkind\n  field dismiss enum dismiss\n  field phrase enum phrase\n  field args", "  field phrase enum phrase\n  field kind enum nkind\n  field dismiss enum dismiss\n  field args", 0, 0, 0, OK, -1},
    {"  field phrase enum phrase\n  field args obj args by phrase\n", "  field phrase enum phrase\n  field cnt uint 5\n  field args obj args by cnt\n", 0, 0, 0, REF, 2},
    {"  field size uint 7\n", "  field size uint 7:\n", 0, 0, 0, SYN, 0},
    {"  field size uint 7\n", "  field size uint /\n", 0, 0, 0, SYN, 0},
    /* the text itself */
    {"top view\n", "frobnicate x\ntop view\n", 0, 0, 0, SYN, 0},
    {"top view\n", "\n\n   \n  # an indented comment\n#bare\ntop    view   \n", 0, 0, 0, OK, -1},
    {"enum lang bg en\n", "enum\tlang bg en\n", 0, 0, 0, SYN, 0},
    {"enum lang bg en\n", "enum lang bg en\r\n", 0, 0, 0, SYN, 0},
    {"expiring dialog snackbar\n", "expiring dialog snackbar", 0, 0, 0, OK, -1},
};

static void t_the_fixture_schema_parses_and_every_bad_edit_of_it_is_refused(ctest_t *t) {
    for (uint32_t i = 0; i < sizeof ROWS / sizeof ROWS[0]; i++) {
        const row_t *r = &ROWS[i];
        const char *text = urig_edit(URIG_SCHEMA, r->old, r->rep);
        uint32_t want_line = r->delta < 0 ? 0U : urig_line_of(URIG_SCHEMA, r->at != NULL ? r->at : r->old) + (uint32_t)r->delta;
        CHECK(t, text != NULL);
        if (text != NULL && r->old2 != NULL) {
            text = urig_edit(text, r->old2, r->rep2);
            CHECK(t, text != NULL);
        }
        if (text == NULL) {
            printf("row %u: the edit did not apply\n", i);
            continue;
        }
        ui_schema_err_t err = ui_schema_parse(&S, text, (uint32_t)strlen(text));
        if ((int)err != r->err || ui_schema_error_line(&S) != want_line) {
            printf("row %u: got error %d line %u, want %d line %u\n", i, (int)err, ui_schema_error_line(&S), r->err, want_line);
        }
        CHECK_EQ_I64(t, err, r->err);
        CHECK_EQ_U64(t, ui_schema_error_line(&S), want_line);
    }
}


typedef struct {
    const char *old[4], *rep[4];
    const char *at; /* the line expected is the line of this text in the edited schema, plus delta */
    int err, delta;
} row4_t;

static const row4_t ROWS4[] = {
    /* `by` names a field that is not an enum, with an enum of the same index as its own (0): only the type tells */
    {{"enum phrase reject_invalid reject_unknown saved not_saved audit sync_rejected sync_late fault\n", "enum screen splash",
      "  field phrase enum phrase\n  field args obj args by phrase\n", 0},
     {"", "enum phrase reject_invalid reject_unknown saved not_saved audit sync_rejected sync_late fault\nenum screen splash",
      "  field phrase enum phrase\n  field cnt uint 5\n  field args obj args by cnt\n", 0},
     "  field args obj args by cnt\n", REF, 0},
    /* a banner dismiss before the role of the dismiss enum, which is enum 0 */
    {{"enum dismiss overlay banner_not_saved banner_audit banner_sync\n", "enum screen splash", "role n_dismiss notice dismiss\n", "bannerdismiss sync banner_sync\n"},
     {"", "enum dismiss overlay banner_not_saved banner_audit banner_sync\nenum screen splash", "", "bannerdismiss sync banner_sync\nrole n_dismiss notice dismiss\n"},
     "bannerdismiss not_saved", REF, 0},
    /* the notice kinds named before their role */
    {{"role n_kind notice kind\n", "expiring dialog snackbar\n", 0, 0}, {"", "expiring dialog snackbar\nrole n_kind notice kind\n", 0, 0}, "expiring dialog", REF, 0},
    /* the screen role in another object than the top one */
    {{"role screen view screen\n", "  field countdown_ms uint 300000 null\nend\nobject banner", 0, 0},
     {"role screen notice tone\n", "  field countdown_ms uint 300000 null\n  field tone enum screen\nend\nobject banner", 0, 0}, NULL, ROL, -1},
};

static void t_rows_of_several_edits(ctest_t *t) {
    for (uint32_t i = 0; i < sizeof ROWS4 / sizeof ROWS4[0]; i++) {
        const row4_t *r = &ROWS4[i];
        const char *text = URIG_SCHEMA;
        for (uint32_t k = 0; k < 4U && r->old[k] != NULL; k++) {
            text = urig_edit(text, r->old[k], r->rep[k]);
            CHECK(t, text != NULL);
            if (text == NULL) {
                printf("row4 %u edit %u did not apply\n", i, k);
                return;
            }
        }
        ui_schema_err_t err = ui_schema_parse(&S, text, (uint32_t)strlen(text));
        uint32_t want_line = r->delta < 0 ? 0U : urig_line_of(text, r->at) + (uint32_t)r->delta;
        if ((int)err != r->err || ui_schema_error_line(&S) != want_line) {
            printf("row4 %u: got error %d line %u, want %d line %u\n", i, (int)err, ui_schema_error_line(&S), r->err, want_line);
        }
        CHECK_EQ_I64(t, err, r->err);
        CHECK_EQ_U64(t, ui_schema_error_line(&S), want_line);
    }
}

static char TEXT[3000];
static char MORE[1200];
static char FILLER[700];

static void t_sixteen_fields_are_the_most_an_object_holds(ctest_t *t) {
    MORE[0] = '\0';
    for (uint32_t i = 0; i < 14U; i++) {
        char line[40];
        snprintf(line, sizeof line, "  field f%u bool\n", i);
        strcat(MORE, line);
    }
    snprintf(TEXT, sizeof TEXT, "  field free uint 65535\n%s", MORE);
    const char *sixteen = urig_edit(URIG_SCHEMA, "  field free uint 65535\n", TEXT);
    CHECK(t, sixteen != NULL);
    CHECK_EQ_I64(t, ui_schema_parse(&S, sixteen, (uint32_t)strlen(sixteen)), UI_SE_OK); /* size, free and 14 more */
    snprintf(TEXT, sizeof TEXT, "  field free uint 65535\n%s  field f14 bool\n", MORE);
    const char *seventeen = urig_edit(URIG_SCHEMA, "  field free uint 65535\n", TEXT);
    CHECK(t, seventeen != NULL);
    CHECK_EQ_I64(t, ui_schema_parse(&S, seventeen, (uint32_t)strlen(seventeen)), UI_SE_LIMIT);
    CHECK_EQ_U64(t, ui_schema_error_line(&S), urig_line_of(URIG_SCHEMA, "  field free uint 65535\n") + 15U);
}

static void t_a_line_has_at_most_600_bytes_and_30_tokens(ctest_t *t) {
    memset(FILLER, 'x', sizeof FILLER);
    for (uint32_t n = 598; n <= 601U; n++) { /* the comment line is "# " plus n - 2 bytes */
        FILLER[n - 2U] = '\0';
        snprintf(TEXT, sizeof TEXT, "# %s\n%s", FILLER, URIG_SCHEMA);
        CHECK_EQ_I64(t, ui_schema_parse(&S, TEXT, (uint32_t)strlen(TEXT)), n <= 600U ? UI_SE_OK : UI_SE_LIMIT);
        CHECK_EQ_U64(t, ui_schema_error_line(&S), n <= 600U ? 0U : 1U);
        FILLER[n - 2U] = 'x';
    }
    for (uint32_t tokens = 29; tokens <= 31U; tokens++) {
        MORE[0] = '\0';
        for (uint32_t i = 0; i < tokens; i++) {
            strcat(MORE, "w ");
        }
        snprintf(TEXT, sizeof TEXT, "%s\n%s", MORE, URIG_SCHEMA);
        CHECK_EQ_I64(t, ui_schema_parse(&S, TEXT, (uint32_t)strlen(TEXT)), tokens <= 30U ? UI_SE_SYNTAX : UI_SE_LIMIT);
        CHECK_EQ_U64(t, ui_schema_error_line(&S), 1);
    }
}

static void t_names_are_1_to_31_lower_case_characters(ctest_t *t) {
    char name[40];
    char rep[120];
    for (uint32_t n = 31; n <= 32U; n++) {
        memset(name, 'a', sizeof name);
        name[n] = '\0';
        snprintf(rep, sizeof rep, "enum lang bg en\nenum %s v\n", name);
        const char *text = urig_edit(URIG_SCHEMA, "enum lang bg en\n", rep);
        CHECK(t, text != NULL);
        CHECK_EQ_I64(t, ui_schema_parse(&S, text, (uint32_t)strlen(text)), n == 31U ? UI_SE_OK : UI_SE_SYNTAX);
    }
    const char *bad[] = {"enum 1x v\n", "enum _x v\n", "enum xA v\n", "enum x-y v\n", "enum x.y v\n", "enum x{ v\n", "enum x` v\n", "enum x@ v\n", "enum x: v\n",
                         "enum x/ v\n", "enum {x v\n", "enum `x v\n", "enum @x v\n", "enum x0 v\n", "enum xz v\n", "enum a_9 v\n", "enum az09_ v\n"};
    for (uint32_t i = 0; i < sizeof bad / sizeof bad[0]; i++) {
        snprintf(rep, sizeof rep, "enum lang bg en\n%s", bad[i]);
        const char *text = urig_edit(URIG_SCHEMA, "enum lang bg en\n", rep);
        CHECK(t, text != NULL);
        int ok = i >= 13U;
        CHECK_EQ_I64(t, ui_schema_parse(&S, text, (uint32_t)strlen(text)), ok ? UI_SE_OK : UI_SE_SYNTAX);
    }
}

static void t_empty_null_and_truncated_text(ctest_t *t) {
    CHECK_EQ_I64(t, ui_schema_parse(&S, "", 0), UI_SE_INCOMPLETE);
    CHECK_EQ_I64(t, ui_schema_parse(&S, NULL, 0), UI_SE_INCOMPLETE);
    CHECK_EQ_I64(t, ui_schema_parse(&S, NULL, 5), UI_SE_SYNTAX);
    CHECK_EQ_I64(t, ui_schema_parse(&S, NULL, 1), UI_SE_SYNTAX);
    CHECK_EQ_I64(t, ui_schema_parse(&S, "x", 1), UI_SE_SYNTAX);
    CHECK_EQ_I64(t, ui_schema_parse(&S, "\n", 1), UI_SE_INCOMPLETE);
    CHECK_EQ_I64(t, ui_schema_parse(&S, "#", 1), UI_SE_INCOMPLETE);
    CHECK_EQ_I64(t, ui_schema_parse(&S, "enum a b\nobject o\n  field x bool\n", 33), UI_SE_INCOMPLETE); /* an open object */
    const char *cut = "enum screen a\nobject view\n  field screen enum screen\n  switch screen\n  on a\n";
    CHECK_EQ_I64(t, ui_schema_parse(&S, cut, (uint32_t)strlen(cut)), UI_SE_INCOMPLETE);
    /* only `len` bytes are read */
    CHECK_EQ_I64(t, ui_schema_parse(&S, URIG_SCHEMA, (uint32_t)strlen(URIG_SCHEMA) - 1U), UI_SE_OK);
    CHECK_EQ_I64(t, ui_schema_parse(&S, URIG_SCHEMA, (uint32_t)(strlen(URIG_SCHEMA) - strlen("expiring dialog snackbar\n"))), UI_SE_INCOMPLETE);
    /* a cut in the middle of the last line: the bytes after `len` are the text's, and are not read */
    CHECK_EQ_I64(t, ui_schema_parse(&S, URIG_SCHEMA, (uint32_t)strlen(URIG_SCHEMA) - 2U), UI_SE_REF); /* "snackba" */
    CHECK_EQ_U64(t, ui_schema_error_line(&S), urig_line_of(URIG_SCHEMA, "expiring dialog"));
    CHECK_EQ_I64(t, ui_schema_parse(&S, URIG_SCHEMA, (uint32_t)strlen(URIG_SCHEMA) - 1U), UI_SE_OK);
}

static void t_a_failed_parse_clears_the_schema_and_a_later_parse_starts_fresh(ctest_t *t) {
    static ui_t u;
    ui_cfg_t cfg;
    uint8_t text[] = "{\"screen\":\"splash\"}";
    ui_view_t v;
    urig_cfg(&cfg);
    CHECK_EQ_I64(t, ui_schema_parse(&S, URIG_SCHEMA, (uint32_t)strlen(URIG_SCHEMA)), UI_SE_OK);
    CHECK_EQ_I64(t, ui_init(&u, &S, &cfg, NULL), 0);
    CHECK_EQ_I64(t, ui_schema_parse(&S, "enum x\n", 7), UI_SE_SYNTAX);
    CHECK_EQ_I64(t, ui_init(&u, &S, &cfg, NULL), -1);
    CHECK_EQ_I64(t, ui_parse(&S, text, (uint32_t)sizeof text - 1U, &v, NULL), UI_R_SYNTAX);
    CHECK_EQ_I64(t, ui_schema_banner_dismiss(&S, 0), -1);
    CHECK_EQ_I64(t, ui_schema_parse(&S, URIG_SCHEMA, (uint32_t)strlen(URIG_SCHEMA)), UI_SE_OK);
    CHECK_EQ_U64(t, ui_schema_error_line(&S), 0);
    CHECK_EQ_I64(t, ui_init(&u, &S, &cfg, NULL), 0);
}

static void t_banner_ids_have_their_dismiss_intents(ctest_t *t) {
    CHECK_EQ_I64(t, ui_schema_parse(&S, URIG_SCHEMA, (uint32_t)strlen(URIG_SCHEMA)), UI_SE_OK);
    CHECK_EQ_I64(t, ui_schema_banner_dismiss(&S, 0), 1); /* banner_not_saved */
    CHECK_EQ_I64(t, ui_schema_banner_dismiss(&S, 1), 2);
    CHECK_EQ_I64(t, ui_schema_banner_dismiss(&S, 2), 3);
    CHECK_EQ_I64(t, ui_schema_banner_dismiss(&S, 3), -1);
    CHECK_EQ_I64(t, ui_schema_banner_dismiss(&S, 23), -1);
    CHECK_EQ_I64(t, ui_schema_banner_dismiss(&S, 24), -1);
    CHECK_EQ_I64(t, ui_schema_banner_dismiss(&S, 255), -1);
    /* a dismiss value 0 is a value (overlay): the banner dismiss is stored +1 */
    const char *text = urig_edit(URIG_SCHEMA, "bannerdismiss audit banner_audit\n", "bannerdismiss audit overlay\n");
    CHECK(t, text != NULL);
    CHECK_EQ_I64(t, ui_schema_parse(&S, text, (uint32_t)strlen(text)), UI_SE_OK);
    CHECK_EQ_I64(t, ui_schema_banner_dismiss(&S, 1), 0);
}

static void t_error_names(ctest_t *t) {
    CHECK_EQ_STR(t, ui_schema_error_name(UI_SE_OK), "ok");
    CHECK_EQ_STR(t, ui_schema_error_name(UI_SE_SYNTAX), "syntax");
    CHECK_EQ_STR(t, ui_schema_error_name(UI_SE_LIMIT), "limit");
    CHECK_EQ_STR(t, ui_schema_error_name(UI_SE_DUPLICATE), "duplicate");
    CHECK_EQ_STR(t, ui_schema_error_name(UI_SE_REF), "reference");
    CHECK_EQ_STR(t, ui_schema_error_name(UI_SE_CONTEXT), "context");
    CHECK_EQ_STR(t, ui_schema_error_name(UI_SE_ROLE), "role");
    CHECK_EQ_STR(t, ui_schema_error_name(UI_SE_INCOMPLETE), "incomplete");
    CHECK(t, ui_schema_error_name((ui_schema_err_t)8) == NULL);
    CHECK(t, ui_schema_error_name((ui_schema_err_t)-1) == NULL);
}

CTEST_SUITE("ui_schema",
    { "rows", t_the_fixture_schema_parses_and_every_bad_edit_of_it_is_refused },
    { "rows4", t_rows_of_several_edits },
    { "sixteen_fields", t_sixteen_fields_are_the_most_an_object_holds },
    { "line_limits", t_a_line_has_at_most_600_bytes_and_30_tokens },
    { "names", t_names_are_1_to_31_lower_case_characters },
    { "empty_and_truncated", t_empty_null_and_truncated_text },
    { "failed_parse_clears", t_a_failed_parse_clears_the_schema_and_a_later_parse_starts_fresh },
    { "banner_dismiss", t_banner_ids_have_their_dismiss_intents },
    { "error_names", t_error_names })
