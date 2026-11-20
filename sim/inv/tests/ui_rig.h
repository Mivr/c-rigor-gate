/* Test kit of the view-invariant tests: a lockers-like schema text (the fixture product's: the engine knows no product), a text editor
 * for building bad schemas and bad views from good ones, canonical view builders, a fake phrase catalogue and a scripted replay. */
#ifndef SIM_INV_TESTS_UI_RIG_H
#define SIM_INV_TESTS_UI_RIG_H

#include "ctest/ctest.h"
#include "sim/inv/ui.h"

enum { U_EV_DIGIT = 1, U_EV_LANG = 2, U_EV_DISMISS = 3, U_EV_OTHER = 9 };

extern const char URIG_SCHEMA[];

/* `base` with the first occurrence of `old` replaced by `rep`, in one of four static buffers; NULL when `old` is not there. */
const char *urig_edit(const char *base, const char *old, const char *rep);
/* The 1-based line number of the first occurrence of `what` in `text`; 0 when absent. */
uint32_t urig_line_of(const char *text, const char *what);

/* The fixture schema, parsed (the parse must succeed). */
const ui_schema_t *urig_schema(ctest_t *t);
/* idle_reset 30000, slack 2000, every notice sampled, tick 250, dismiss ev 3, activity evs 1 2 3. */
void urig_cfg(ui_cfg_t *c);

/* Canonical views. `lang` is "bg" or "en"; `notice` is "null" or a notice object; `banners` is the inside of the array. */
const char *urig_welcome(const char *lang, const char *notice, const char *banners);
const char *urig_screen(const char *screen, const char *lang, const char *fields, const char *notice, const char *banners);
/* A dialog-like notice with plain arguments `{}`: kind, dismiss and phrase are the enum texts; `countdown` is "null" or a number. */
const char *urig_notice(const char *kind, const char *dismiss, const char *phrase, const char *countdown);
const char *urig_banner(const char *id, const char *phrase);

/* The fake world. */
typedef struct {
    const char *unknown, *nobg; /* the phrase texts the catalogue does not know / knows without Bulgarian */
    uint32_t phrase_calls;
    char phrases[8][32];
    uint32_t replay_calls;
    ui_replay_mode_t modes[8];
    uint32_t records[8], dismisses[8], advances[8], caps[8];
    const char *out[3]; /* the view returned for each mode */
    int rc[3];
    uint32_t forced_len[3]; /* when not 0 the length returned instead of the text's */
} urig_world_t;

typedef struct {
    ctest_t *t;
    ui_t *u;
    urig_world_t *w;
} urig_t;

/* Start `u` with the fixture schema and `cfg` (NULL: urig_cfg) and a world bound to `w` (`with_world`: bit 0 the phrase callback, bit 1 the replay callback, 0 none). */
void urig_start(urig_t *r, ctest_t *t, ui_t *u, urig_world_t *w, const ui_cfg_t *cfg, int with_world);
void urig_vw(urig_t *r, uint64_t t_ms, const char *text);
void urig_ev(urig_t *r, uint64_t t_ms, uint32_t type);
/* Is finding `index` exactly (rule, t, record)? */
int urig_finding_is(const urig_t *r, uint32_t index, ui_rule_t rule, uint64_t t_ms, uint32_t record);

#endif
