#include "sim/inv/tests/ui_rig.h"

#include <stdio.h>
#include <string.h>

const char URIG_SCHEMA[] =
    "# the closed schema of a lockers-like kiosk\n"
    "enum screen splash welcome choose opened shift report lockout fault_storage fault_relay\n"
    "enum lang bg en\n"
    "enum nkind dialog banner snackbar\n"
    "enum dismiss overlay banner_not_saved banner_audit banner_sync\n"
    "enum bannerid not_saved audit sync\n"
    "enum phrase reject_invalid reject_unknown saved not_saved audit sync_rejected sync_late fault\n"
    "enum fault relay_busy relay_error\n"
    "enum door nothing_opened maybe_opened opened\n"
    "object sizeitem\n"
    "  field size uint 7\n"
    "  field free uint 65535\n"
    "end\n"
    "object args\n"
    "  switch @ phrase\n"
    "  on fault\n"
    "  field fault enum fault\n"
    "  field door enum door\n"
    "  field locker uint 65535 null\n"
    "  on sync_rejected\n"
    "  field status uint 65535\n"
    "  on sync_late\n"
    "  field hour uint 23\n"
    "  field minute uint 59\n"
    "  endswitch\n"
    "end\n"
    "object notice\n"
    "  field kind enum nkind\n"
    "  field dismiss enum dismiss\n"
    "  field phrase enum phrase\n"
    "  field args obj args by phrase\n"
    "  field warning bool\n"
    "  field countdown_ms uint 300000 null\n"
    "end\n"
    "object banner\n"
    "  field id enum bannerid\n"
    "  field phrase enum phrase\n"
    "  field args obj args by phrase\n"
    "  field warning bool\n"
    "end\n"
    "object view\n"
    "  field screen enum screen\n"
    "  field lang enum lang\n"
    "  field countdown_ms uint 300000 null\n"
    "  switch screen\n"
    "  on welcome\n"
    "  field pad_len uint 64\n"
    "  on choose\n"
    "  field sizes list sizeitem 4\n"
    "  on opened\n"
    "  field locker uint 999\n"
    "  field first_time bool\n"
    "  on shift\n"
    "  field done uint 65535\n"
    "  field total uint 65535\n"
    "  on report\n"
    "  field released uint 65535\n"
    "  field write_failed bool\n"
    "  on fault_storage\n"
    "  field fault enum fault\n"
    "  on fault_relay\n"
    "  field fault enum fault\n"
    "  endswitch\n"
    "  field notice obj notice null\n"
    "  field banners list banner 4\n"
    "end\n"
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
    "bannerdismiss not_saved banner_not_saved\n"
    "bannerdismiss audit banner_audit\n"
    "bannerdismiss sync banner_sync\n"
    "forbid message text title\n"
    "idle welcome\n"
    "lang_default bg\n"
    "expiring dialog snackbar\n";

enum { EDIT_BUFS = 4, EDIT_MAX = 12000 };

const char *urig_edit(const char *base, const char *old, const char *rep) {
    static char bufs[EDIT_BUFS][EDIT_MAX];
    static unsigned next;
    const char *at = strstr(base, old);
    if (at == NULL) {
        return NULL;
    }
    char *out = bufs[next++ % EDIT_BUFS];
    int n = snprintf(out, EDIT_MAX, "%.*s%s%s", (int)(at - base), base, rep, at + strlen(old));
    return n > 0 && n < EDIT_MAX ? out : NULL;
}

uint32_t urig_line_of(const char *text, const char *what) {
    const char *at = strstr(text, what);
    uint32_t line = 1;
    if (at == NULL) {
        return 0;
    }
    for (const char *p = text; p != at; p++) {
        line += *p == '\n' ? 1U : 0U;
    }
    return line;
}

const ui_schema_t *urig_schema(ctest_t *t) {
    static ui_schema_t s;
    CHECK_EQ_I64(t, ui_schema_parse(&s, URIG_SCHEMA, (uint32_t)strlen(URIG_SCHEMA)), UI_SE_OK);
    return &s;
}

void urig_cfg(ui_cfg_t *c) {
    memset(c, 0, sizeof *c);
    c->ev_dismiss[0] = U_EV_DISMISS;
    c->n_ev_dismiss = 1;
    c->ev_activity[0] = U_EV_DIGIT;
    c->ev_activity[1] = U_EV_LANG;
    c->ev_activity[2] = U_EV_DISMISS;
    c->n_ev_activity = 3;
    c->idle_reset_ms = 30000;
    c->slack_ms = 2000;
    c->sample_every = 1;
    c->tick_ms = 250;
}

enum { VIEW_BUFS = 6, VIEW_MAX = 1200 };

static char *view_buf(void) {
    static char bufs[VIEW_BUFS][VIEW_MAX];
    static unsigned next;
    return bufs[next++ % VIEW_BUFS];
}

const char *urig_screen(const char *screen, const char *lang, const char *fields, const char *notice, const char *banners) {
    char *b = view_buf();
    snprintf(b, VIEW_MAX, "{\"screen\":\"%s\",\"lang\":\"%s\",\"countdown_ms\":null%s%s,\"notice\":%s,\"banners\":[%s]}", screen, lang,
             fields[0] != '\0' ? "," : "", fields, notice, banners);
    return b;
}

const char *urig_welcome(const char *lang, const char *notice, const char *banners) {
    return urig_screen("welcome", lang, "\"pad_len\":3", notice, banners);
}

const char *urig_notice(const char *kind, const char *dismiss, const char *phrase, const char *countdown) {
    char *b = view_buf();
    snprintf(b, VIEW_MAX, "{\"kind\":\"%s\",\"dismiss\":\"%s\",\"phrase\":\"%s\",\"args\":{},\"warning\":false,\"countdown_ms\":%s}", kind, dismiss,
             phrase, countdown);
    return b;
}

const char *urig_banner(const char *id, const char *phrase) {
    char *b = view_buf();
    snprintf(b, VIEW_MAX, "{\"id\":\"%s\",\"phrase\":\"%s\",\"args\":{},\"warning\":false}", id, phrase);
    return b;
}

static int cb_phrase(void *ctx, const char *phrase) {
    urig_world_t *w = (urig_world_t *)ctx;
    if (w->phrase_calls < 8U) {
        snprintf(w->phrases[w->phrase_calls], sizeof w->phrases[0], "%s", phrase);
    }
    w->phrase_calls++;
    if (w->unknown != NULL && strcmp(w->unknown, phrase) == 0) {
        return 0;
    }
    return w->nobg != NULL && strcmp(w->nobg, phrase) == 0 ? -1 : 1;
}

static int cb_replay(void *ctx, ui_replay_mode_t mode, uint32_t record, uint32_t dismiss, uint32_t advance_ms, uint8_t *out, uint32_t cap,
                     uint32_t *len) {
    urig_world_t *w = (urig_world_t *)ctx;
    uint32_t i = w->replay_calls++;
    if (i < 8U) {
        w->modes[i] = mode;
        w->records[i] = record;
        w->dismisses[i] = dismiss;
        w->advances[i] = advance_ms;
        w->caps[i] = cap;
    }
    const char *text = w->out[mode];
    uint32_t n = text != NULL ? (uint32_t)strlen(text) : 0U;
    if (text != NULL && n <= cap) {
        memcpy(out, text, n);
    }
    *len = w->forced_len[mode] != 0U ? w->forced_len[mode] : n;
    return w->rc[mode];
}

void urig_start(urig_t *r, ctest_t *t, ui_t *u, urig_world_t *w, const ui_cfg_t *cfg, int with_world) {
    ui_cfg_t c;
    ui_world_t world = {w, (with_world & 1) != 0 ? cb_phrase : NULL, (with_world & 2) != 0 ? cb_replay : NULL};
    memset(w, 0, sizeof *w);
    urig_cfg(&c);
    r->t = t;
    r->u = u;
    r->w = w;
    CHECK_EQ_I64(t, ui_init(u, urig_schema(t), cfg != NULL ? cfg : &c, with_world != 0 ? &world : NULL), 0);
}

void urig_vw(urig_t *r, uint64_t t_ms, const char *text) {
    sim_rec_t rec = {{'v', 'w'}, t_ms, 0, 0, (const uint8_t *)text, (uint32_t)strlen(text)};
    CHECK_EQ_I64(r->t, ui_feed(r->u, &rec), 0);
}

void urig_ev(urig_t *r, uint64_t t_ms, uint32_t type) {
    sim_rec_t rec = {{'e', 'v'}, t_ms, type, 0, NULL, 0};
    CHECK_EQ_I64(r->t, ui_feed(r->u, &rec), 0);
}

int urig_finding_is(const urig_t *r, uint32_t index, ui_rule_t rule, uint64_t t_ms, uint32_t record) {
    const ui_finding_t *f = ui_finding(r->u, index);
    return f != NULL && f->rule == rule && f->inv == ui_rule_inv(rule) && f->t_ms == t_ms && f->record == record;
}
