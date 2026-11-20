/* The view invariants I7 and I8 of P330 section 2.3 (T2G5), over the `vw` records of sim/trace_fmt.h.
 *
 *   I7  every published view parses under the CLOSED schema of the product's ViewState canonical form (unknown key, unknown enum
 *       text, float, whitespace, a key out of order: a violation); no full-screen message (the screen is in the closed set, a message
 *       exists only as a `notice` or a banner, which sit over a screen); every notice has a dismiss intent; a notice that clears with no
 *       dismiss has shown a countdown (an auto-timeout may remain only with a visible countdown), and not before it ran out; banners
 *       are in ascending id order and each id has a dismiss intent; the language is the default after the idle time; every phrase is in
 *       the product's catalogue (a callback) with a non-empty Bulgarian text. Text fit and goldens are W9, not here.
 *   I8  dismiss works (metamorphic): for every Nth notice the engine asks the world to re-run the trace up to that record on a fresh
 *       world, apply the notice's dismiss intent and run one tick; the notice must be gone (or another one), the screen under it
 *       unchanged; and dismissing then letting the countdown's time pass gives the same view as letting the countdown end alone.
 *
 * The engine does not know the product. The SHAPE of a view is DATA: a schema text (`ui_schema_parse`, grammar below) that the product
 * supplies and the gate parses; no field name of any product is in this code. The rules of the product (event ids, timers) are plain
 * numbers in `ui_cfg_t`; the phrase catalogue and the re-run are callbacks of the world. Static memory: the caller owns a `ui_schema_t`
 * (about 14 KiB) and a `ui_t` (about 13 KiB); keep both static. No recursion: a schema lists an object before it uses it.
 *
 * A `vw` record: `bytes` is the canonical text of the view (compact JSON, keys in the schema's order, integers in decimal only,
 * booleans, null); `a` and `b` are the world's (the engine ignores them). Records must arrive in time order.
 *
 * SCHEMA TEXT. Lines of tokens separated by spaces (indentation allowed), `#` starts a comment line. Names are [a-z][a-z0-9_]* of 1 to 31
 * characters. Order matters: a thing is declared before it is used.
 *
 *   enum NAME V1 V2 ...             a closed set of texts (1 to 24 values, 10 enums)
 *   object NAME                     an object type (5 objects, 24 fields each) ... until `end`
 *     field KEY uint MAX [null]     a decimal integer 0..MAX; `null` allows the text null instead (and then 0 is not canonical: it is null)
 *     field KEY bool                true or false
 *     field KEY enum ENUM           a text of the enum
 *     field KEY obj OBJ [by KEY2] [null]   an earlier object type; `by KEY2` hands the value of the enum field KEY2 (an earlier sibling) to it
 *     field KEY list OBJ MAX        an array of 0 to MAX (1 to 255) earlier objects
 *     switch KEY | switch @ ENUM    the fields up to `endswitch` exist only for some values of the enum field KEY (an earlier sibling) or
 *                                   of the selector handed down with `by` (`@`, its enum named)
 *     on VALUE                      the fields that follow belong to that value; a value with no `on` has no fields
 *     endswitch
 *   end
 *   top OBJ                         the type of a view
 *   role ROLE OBJ KEY               which field plays a role (all required, each once): screen lang notice banners (in the top object),
 *                                   n_kind n_dismiss n_phrase n_countdown (in the notice's object), b_id b_phrase (in the banners' object)
 *   bannerdismiss ID DISMISS        the dismiss intent (a value of the n_dismiss enum) of a banner id: required for every banner id
 *   forbid KEY ...                  keys that mean a full-screen message when they appear where another key is expected (up to 4)
 *   idle VALUE                      the screen value of the idle (welcome) screen
 *   lang_default VALUE              the language value of the default language
 *   expiring VALUE ...              the notice kinds that clear on their own (a dialog, a snackbar): they must show a countdown
 */
#ifndef SIM_INV_UI_H
#define SIM_INV_UI_H

#include <stddef.h>
#include <stdint.h>

#include "sim/trace_fmt.h"

enum {
    UI_NAME_MAX = 32, /* a name with its end */
    UI_MAX_ENUMS = 10,
    UI_MAX_VALUES = 24,
    UI_MAX_OBJECTS = 5,
    UI_MAX_FIELDS = 24,
    UI_MAX_BANNERS = 8,
    UI_MAX_FORBID = 4,
    UI_MAX_EV = 4,
    UI_MAX_FINDINGS = 16,
    UI_MAX_DEPTH = 9, /* 2 * UI_MAX_OBJECTS - 1: a path has an object at most once (an object is declared before its use), and a list between two objects */
    UI_MAX_SLOTS = 4, /* the enum fields of one object that a `switch` or a `by` may read */
    UI_VIEW_MAX = 4096,  /* the longest view text; a longer one is a syntax violation */
    UI_SW_EXT = 255
};

typedef enum { UI_T_UINT = 1, UI_T_BOOL, UI_T_ENUM, UI_T_OBJ, UI_T_LIST } ui_type_t;

typedef enum {
    UI_ROLE_NONE = 0,
    UI_ROLE_SCREEN,
    UI_ROLE_LANG,
    UI_ROLE_NOTICE,
    UI_ROLE_BANNERS,
    UI_ROLE_N_KIND,
    UI_ROLE_N_DISMISS,
    UI_ROLE_N_PHRASE,
    UI_ROLE_N_COUNTDOWN,
    UI_ROLE_B_ID,
    UI_ROLE_B_PHRASE,
    UI_ROLE_COUNT
} ui_role_t;

/* The parts of a schema (plain data; fill them only through ui_schema_parse). */
typedef struct {
    char key[UI_NAME_MAX];
    uint8_t type, nullable, ref, role, by, sw_src, sw_case;
    uint8_t by_enum; /* with `by`: the enum of the field it names */
    uint8_t slot; /* an enum field that a switch or a `by` reads keeps its value in this slot (1 to UI_MAX_SLOTS, 0: none); `by` and `sw_src` name one */
    uint32_t max;
} ui_field_t;

typedef struct {
    char name[UI_NAME_MAX];
    uint8_t n_fields, has_ext, ext_enum, n_slots;
    ui_field_t fields[UI_MAX_FIELDS];
} ui_object_t;

typedef struct {
    char name[UI_NAME_MAX];
    uint8_t n_values;
    char values[UI_MAX_VALUES][UI_NAME_MAX];
} ui_enum_t;

typedef struct {
    ui_enum_t enums[UI_MAX_ENUMS];
    ui_object_t objects[UI_MAX_OBJECTS];
    uint8_t n_enums, n_objects, top, has_top;
    uint8_t role_seen[UI_ROLE_COUNT], role_obj[UI_ROLE_COUNT], role_ref[UI_ROLE_COUNT]; /* the object of a role's field; its enum (or object, for notice and banners) */
    uint32_t role_max[UI_ROLE_COUNT];
    uint8_t banner_dismiss[256]; /* 1 + the dismiss value of a banner id, 0: none */
    char forbid[UI_MAX_FORBID][UI_NAME_MAX];
    uint8_t n_forbid;
    uint8_t idle_screen, default_lang, has_idle, has_lang;
    uint32_t expiring_mask; /* bit per value of the n_kind enum */
    /* the parser's own state */
    uint8_t cur, open, sw_open, sw_on, sw_enum, sw_src, sw_case;
    uint8_t ready;
    uint32_t err_line;
} ui_schema_t;

typedef enum {
    UI_SE_OK = 0,
    UI_SE_SYNTAX,     /* an unknown directive, a wrong number of tokens, a token that is not a name or a number */
    UI_SE_LIMIT,      /* more enums, values, objects, fields or keys than the limits above, or a line over 600 bytes */
    UI_SE_DUPLICATE,  /* a name or key declared twice (keys may repeat only in different cases of one switch) */
    UI_SE_REF,        /* an unknown enum, object, key or value, or one declared after its use */
    UI_SE_CONTEXT,    /* a directive where it does not belong (a field outside an object, `on` outside a switch, `end` with no object) */
    UI_SE_ROLE,       /* a role on a field of the wrong type, object, or under a switch; a role given twice */
    UI_SE_INCOMPLETE  /* a missing top, role, banner dismiss, idle, lang_default or expiring, or an open object */
} ui_schema_err_t;

/* Parse `len` bytes of schema text into `s` (which is cleared first). Returns UI_SE_OK, or the first error with the 1-based line in
 * ui_schema_error_line. A schema that failed is never `ready`: ui_init and ui_parse refuse it. */
ui_schema_err_t ui_schema_parse(ui_schema_t *s, const char *text, uint32_t len);
uint32_t ui_schema_error_line(const ui_schema_t *s);
const char *ui_schema_error_name(ui_schema_err_t err);

/* ---- one view ---- */

/* What a view is, as the rules need it (the screen, language and kind are the values' indexes in their enums). */
typedef struct {
    uint8_t screen, lang, has_notice;
    uint8_t n_kind, n_dismiss, n_phrase;
    uint32_t n_countdown_ms; /* 0: null */
    uint32_t notice_off, notice_len; /* where the notice object's text is in the view's bytes */
    uint32_t n_cd_off, n_cd_len;     /* where the value of its countdown (a number or null) is: the identity of a notice leaves it out */
    uint8_t n_banners;
    uint8_t banner_id[UI_MAX_BANNERS], banner_phrase[UI_MAX_BANNERS];
} ui_view_t;

typedef enum {
    UI_I7 = 7,
    UI_I8 = 8
} ui_inv_t;

typedef enum {
    UI_R_NONE = 0,
    UI_R_SYNTAX = 1,          /* I7: not the canonical text (whitespace, a bad token, a leading zero, a sign, text after the view, over 4096 bytes) */
    UI_R_KEY,                 /* I7: an unknown, missing or out-of-order key */
    UI_R_ENUM,                /* I7: a text outside its closed set */
    UI_R_FLOAT,               /* I7: a number with a fraction or an exponent */
    UI_R_RANGE,               /* I7: a number above its maximum, a list over its maximum, or 0 where null is canonical */
    UI_R_FULL_SCREEN,         /* I7: a screen outside the closed set, or a forbidden key: a message that is a screen */
    UI_R_NO_DISMISS,          /* I7: a notice with no dismiss intent (missing or null) */
    UI_R_BANNER_ORDER,        /* I7: banner ids not in ascending order, or repeated */
    UI_R_TIMEOUT_NO_COUNTDOWN, /* I7: an expiring notice cleared with no dismiss and had shown no countdown */
    UI_R_COUNTDOWN_EARLY,     /* I7: it cleared before its countdown ran out */
    UI_R_LANG_NOT_RESET,      /* I7: the idle screen after the idle time, in another language than the default */
    UI_R_PHRASE_UNKNOWN,      /* I7: a phrase that is not in the catalogue */
    UI_R_PHRASE_NO_BG,        /* I7: a phrase with an empty Bulgarian text */
    UI_R_DISMISS_KEPT,        /* I8: the same notice after its dismiss intent and one tick */
    UI_R_DISMISS_SCREEN,      /* I8: the screen under the notice changed with the dismiss */
    UI_R_DISMISS_VS_EXPIRY,   /* I8: dismissing and letting the time pass differs from letting the countdown end */
    UI_R_REPLAY_FAILED,       /* I8: the world could not re-run (fails closed), or its view does not parse */
    UI_R_COUNT
} ui_rule_t;

/* Parse one view. Returns UI_R_NONE and fills `out`, or the rule it broke and (when `at` is not NULL) the byte offset it stopped at;
 * `out` is cleared first. A NULL argument, or a schema that is not ready, is UI_R_SYNTAX at 0. */
/* The dismiss intent (a value of the n_dismiss enum) of the banner id `id` (a value of the b_id enum): every id has one in a schema that
 * parsed. -1 for an id out of range. */
int ui_schema_banner_dismiss(const ui_schema_t *s, uint8_t id);

ui_rule_t ui_parse(const ui_schema_t *s, const uint8_t *bytes, uint32_t len, ui_view_t *out, uint32_t *at);

/* ---- the engine ---- */

typedef struct {
    uint32_t ev_dismiss[UI_MAX_EV];  /* `ev` types that are a dismiss intent landing (they may clear a notice) */
    uint32_t n_ev_dismiss;
    uint32_t ev_activity[UI_MAX_EV]; /* `ev` types that are a visitor doing something (digits, language switch, dismiss...) */
    uint32_t n_ev_activity;
    uint32_t idle_reset_ms;          /* the idle time after which the language is the default again; 0: the rule is off */
    uint32_t slack_ms;               /* tolerance of every timer (one republish period and a tick) */
    uint32_t sample_every;           /* I8 on every Nth notice, the first included; 0: I8 is off */
    uint32_t tick_ms;                /* one tick of the app; required when sample_every is not 0 */
} ui_cfg_t;

typedef enum { UI_REPLAY_DISMISS = 0, UI_REPLAY_DISMISS_WAIT, UI_REPLAY_WAIT } ui_replay_mode_t;

typedef struct {
    void *ctx;
    /* Is `phrase` (the text of the phrase enum value) in the catalogue? 1: yes with a non-empty Bulgarian text; 0: no; < 0: yes, but the
     * Bulgarian text is empty. NULL: the phrase checks do not run. */
    int (*phrase_status)(void *ctx, const char *phrase);
    /* Re-run the trace up to and including the record `record` (counting from 0) on a fresh world, then:
     *   UI_REPLAY_DISMISS       apply the dismiss intent `dismiss` (a value of the n_dismiss enum), run `advance_ms`;
     *   UI_REPLAY_DISMISS_WAIT  the same intent, then run `advance_ms`;
     *   UI_REPLAY_WAIT          apply nothing, run `advance_ms`.
     * Write the view published then (canonical text) to out (at most `cap` bytes) and its length to *len. 0 on success, < 0 on failure. NULL:
     * I8 does not run. */
    int (*replay)(void *ctx, ui_replay_mode_t mode, uint32_t record, uint32_t dismiss, uint32_t advance_ms, uint8_t *out, uint32_t cap, uint32_t *len);
} ui_world_t;

typedef struct {
    ui_inv_t inv;
    ui_rule_t rule;
    uint64_t t_ms;
    uint32_t record;
} ui_finding_t;

typedef struct {
    uint32_t records, views, notices, banners, dismissed, expired, lang_checks, phrases, i8_checks;
} ui_counts_t;

typedef struct {
    const ui_schema_t *schema;
    ui_cfg_t cfg;
    ui_world_t world;
    uint64_t now, last_activity, prev_t;
    const uint8_t *cur_bytes; /* the text of the view being taken; only valid during ui_feed */
    uint32_t records, notice_ord;
    uint8_t started, have_prev, dismissed_since;
    ui_view_t prev;
    ui_view_t cur;
    uint8_t prev_text[UI_VIEW_MAX];
    uint8_t buf_a[UI_VIEW_MAX], buf_b[UI_VIEW_MAX];
    uint32_t rules_seen, inv_seen, nfindings, dropped;
    ui_finding_t findings[UI_MAX_FINDINGS];
    ui_counts_t counts;
} ui_t;

/* Start. Returns 0, or -1 (the engine then refuses every feed) for a schema that is not ready, a NULL, more than 4 event ids in a list,
 * or sample_every set with no tick_ms. `world` may be NULL (no callbacks). */
int ui_init(ui_t *u, const ui_schema_t *schema, const ui_cfg_t *cfg, const ui_world_t *world);
/* Take one record. Returns 0 when it was processed, -1 when it is malformed (NULL, bytes missing, time going backwards) or the engine
 * was not started: nothing changed. */
int ui_feed(ui_t *u, const sim_rec_t *rec);
/* The run ended at `t_end_ms`: the language rule once more on the last view. Returns 0 or -1 (time backwards). */
int ui_finish(ui_t *u, uint64_t t_end_ms);

uint32_t ui_finding_count(const ui_t *u);
const ui_finding_t *ui_finding(const ui_t *u, uint32_t index); /* NULL past the count or past UI_MAX_FINDINGS */
int ui_has_rule(const ui_t *u, ui_rule_t rule);
int ui_has_inv(const ui_t *u, ui_inv_t inv);
uint32_t ui_dropped(const ui_t *u); /* findings past the 16 kept */
ui_counts_t ui_counts(const ui_t *u); /* the antecedents, for the judge's non-vacuity check */

ui_inv_t ui_rule_inv(ui_rule_t rule);
const char *ui_inv_name(ui_inv_t inv);   /* "I7" "I8"; NULL otherwise */
const char *ui_rule_name(ui_rule_t rule); /* kebab case; NULL for UI_R_NONE and values out of range */

#endif
