#include "sim/inv/ui.h"

#include <string.h>

ui_inv_t ui_rule_inv(ui_rule_t rule) {
    if (rule >= UI_R_DISMISS_KEPT) {
        return UI_I8;
    }
    return rule >= UI_R_SYNTAX ? UI_I7 : (ui_inv_t)0;
}

const char *ui_inv_name(ui_inv_t inv) {
    switch (inv) {
    case UI_I7:
        return "I7";
    case UI_I8:
        return "I8";
    default:
        return NULL;
    }
}

const char *ui_rule_name(ui_rule_t rule) {
    switch (rule) {
    case UI_R_SYNTAX:
        return "syntax";
    case UI_R_KEY:
        return "key";
    case UI_R_ENUM:
        return "enum";
    case UI_R_FLOAT:
        return "float";
    case UI_R_RANGE:
        return "range";
    case UI_R_FULL_SCREEN:
        return "full-screen-message";
    case UI_R_NO_DISMISS:
        return "notice-without-dismiss";
    case UI_R_BANNER_ORDER:
        return "banner-order";
    case UI_R_TIMEOUT_NO_COUNTDOWN:
        return "timeout-without-countdown";
    case UI_R_COUNTDOWN_EARLY:
        return "countdown-early";
    case UI_R_LANG_NOT_RESET:
        return "lang-not-reset";
    case UI_R_PHRASE_UNKNOWN:
        return "phrase-unknown";
    case UI_R_PHRASE_NO_BG:
        return "phrase-without-bg";
    case UI_R_DISMISS_KEPT:
        return "dismiss-kept";
    case UI_R_DISMISS_SCREEN:
        return "dismiss-screen-changed";
    case UI_R_DISMISS_VS_EXPIRY:
        return "dismiss-vs-expiry";
    case UI_R_REPLAY_FAILED:
        return "replay-failed";
    default:
        return NULL;
    }
}

static void flag(ui_t *u, ui_rule_t rule) {
    ui_inv_t inv = ui_rule_inv(rule);
    u->rules_seen |= 1U << (unsigned)rule;
    u->inv_seen |= 1U << (unsigned)inv;
    if (u->nfindings < UI_MAX_FINDINGS) {
        u->findings[u->nfindings] = (ui_finding_t){inv, rule, u->now, u->records};
        u->nfindings++;
    } else {
        u->dropped++;
    }
}

/* The same notice in two views: the text of the object is the same, but for the value of its countdown, which falls from view to view. */
static int same_notice(const uint8_t *ab, const ui_view_t *a, const uint8_t *bb, const ui_view_t *b) {
    uint32_t a_head = a->n_cd_off - a->notice_off;
    uint32_t b_head = b->n_cd_off - b->notice_off;
    uint32_t a_tail = a->notice_off + a->notice_len - (a->n_cd_off + a->n_cd_len);
    uint32_t b_tail = b->notice_off + b->notice_len - (b->n_cd_off + b->n_cd_len);
    return a_head == b_head && a_tail == b_tail && memcmp(ab + a->notice_off, bb + b->notice_off, a_head) == 0 &&
           memcmp(ab + a->n_cd_off + a->n_cd_len, bb + b->n_cd_off + b->n_cd_len, a_tail) == 0;
}

static void check_phrase(ui_t *u, ui_role_t role, uint8_t value) {
    const ui_schema_t *s = u->schema;
    int status = u->world.phrase_status(u->world.ctx, s->enums[s->role_ref[role]].values[value]);
    u->counts.phrases++;
    if (status < 0) {
        flag(u, UI_R_PHRASE_NO_BG);
    } else if (status == 0) {
        flag(u, UI_R_PHRASE_UNKNOWN);
    }
}

static void check_phrases(ui_t *u) {
    if (u->world.phrase_status == NULL) {
        return;
    }
    if (u->cur.has_notice != 0U) {
        check_phrase(u, UI_ROLE_N_PHRASE, u->cur.n_phrase);
    }
    for (const uint8_t *b = u->cur.banner_phrase; b != u->cur.banner_phrase + u->cur.n_banners; b++) {
        check_phrase(u, UI_ROLE_B_PHRASE, *b);
    }
}

/* The idle screen, after the idle time with no visitor activity, must be in the default language. */
static void lang_rule(ui_t *u, const ui_view_t *v) {
    if (u->cfg.idle_reset_ms == 0U || v->screen != u->schema->idle_screen) {
        return;
    }
    if (u->now - u->last_activity < (uint64_t)u->cfg.idle_reset_ms + u->cfg.slack_ms) {
        return;
    }
    u->counts.lang_checks++;
    if (v->lang != u->schema->default_lang) {
        flag(u, UI_R_LANG_NOT_RESET);
    }
}

/* One re-run of the world; its view must parse. 0 when `out` holds the view. */
static int replay_view(ui_t *u, ui_replay_mode_t mode, uint32_t advance, uint8_t *buf, ui_view_t *out, uint32_t *len) {
    int rc = u->world.replay(u->world.ctx, mode, u->records, u->cur.n_dismiss, advance, buf, UI_VIEW_MAX, len);
    if (rc < 0 || ui_parse(u->schema, buf, *len, out, NULL) != UI_R_NONE) {
        flag(u, UI_R_REPLAY_FAILED);
        return 1;
    }
    return 0;
}

/* Dismissing and waiting for the countdown's time gives the view that waiting alone gives. */
static void expiry_rule(ui_t *u) {
    uint32_t advance = u->cur.n_countdown_ms + u->cfg.tick_ms;
    uint32_t la;
    uint32_t lb;
    ui_view_t a;
    ui_view_t b;
    if (replay_view(u, UI_REPLAY_DISMISS_WAIT, advance, u->buf_a, &a, &la) != 0 || replay_view(u, UI_REPLAY_WAIT, advance, u->buf_b, &b, &lb) != 0) {
        return;
    }
    if (la != lb || memcmp(u->buf_a, u->buf_b, la) != 0) {
        flag(u, UI_R_DISMISS_VS_EXPIRY);
    }
}

static void run_i8(ui_t *u) {
    uint32_t la;
    ui_view_t a;
    u->counts.i8_checks++;
    if (replay_view(u, UI_REPLAY_DISMISS, u->cfg.tick_ms, u->buf_a, &a, &la) != 0) {
        return;
    }
    if (a.has_notice != 0U && same_notice(u->buf_a, &a, u->cur_bytes, &u->cur)) {
        flag(u, UI_R_DISMISS_KEPT);
    }
    if (a.screen != u->cur.screen) {
        flag(u, UI_R_DISMISS_SCREEN);
    }
    if (u->cur.n_countdown_ms > 0U) {
        expiry_rule(u);
    }
}

/* The notice of the previous view is gone: by a dismiss, or by itself. */
static void notice_cleared(ui_t *u) {
    const ui_view_t *p = &u->prev;
    if (u->dismissed_since != 0U) {
        u->counts.dismissed++;
        return;
    }
    if (((1U << p->n_kind) & u->schema->expiring_mask) == 0U) {
        return;
    }
    u->counts.expired++;
    if (p->n_countdown_ms == 0U) {
        flag(u, UI_R_TIMEOUT_NO_COUNTDOWN);
    } else if (u->now + u->cfg.slack_ms < u->prev_t + p->n_countdown_ms) {
        flag(u, UI_R_COUNTDOWN_EARLY);
    }
}

static void notice_flow(ui_t *u) {
    int had = u->have_prev != 0U && u->prev.has_notice != 0U;
    int same = had && u->cur.has_notice != 0U && same_notice(u->prev_text, &u->prev, u->cur_bytes, &u->cur);
    if (had && u->cur.has_notice == 0U) {
        notice_cleared(u);
    }
    if (u->cur.has_notice != 0U && !same) {
        uint32_t ord = u->notice_ord++;
        u->counts.notices++;
        if (u->world.replay != NULL && u->cfg.sample_every > 0U && ord % u->cfg.sample_every == 0U) {
            run_i8(u);
        }
    }
}

static void on_view(ui_t *u, const sim_rec_t *rec) {
    ui_rule_t rule = ui_parse(u->schema, rec->bytes, rec->len, &u->cur, NULL);
    u->counts.views++;
    if (rule != UI_R_NONE) {
        flag(u, rule);
        return;
    }
    u->cur_bytes = rec->bytes;
    u->counts.banners += u->cur.n_banners;
    check_phrases(u);
    if (u->cur.screen != u->schema->idle_screen) {
        u->last_activity = u->now;
    }
    lang_rule(u, &u->cur);
    notice_flow(u);
    u->prev = u->cur;
    memcpy(u->prev_text, rec->bytes, rec->len);
    u->prev_t = u->now;
    u->have_prev = 1;
    u->dismissed_since = 0;
}

static int listed(const uint32_t *list, uint32_t n, uint32_t type) {
    for (const uint32_t *p = list; p != list + n; p++) {
        if (*p == type) {
            return 1;
        }
    }
    return 0;
}

static void on_ev(ui_t *u, const sim_rec_t *rec) {
    if (listed(u->cfg.ev_dismiss, u->cfg.n_ev_dismiss, rec->a)) {
        u->dismissed_since = 1;
    }
    if (listed(u->cfg.ev_activity, u->cfg.n_ev_activity, rec->a)) {
        u->last_activity = u->now;
    }
}

static int advance(ui_t *u, uint64_t t_ms) {
    if (t_ms < u->now) {
        return -1;
    }
    u->now = t_ms;
    return 0;
}

int ui_init(ui_t *u, const ui_schema_t *schema, const ui_cfg_t *cfg, const ui_world_t *world) {
    if (u == NULL) {
        return -1;
    }
    memset(u, 0, sizeof *u);
    if (schema == NULL || cfg == NULL || schema->ready == 0U || cfg->n_ev_dismiss > (uint32_t)UI_MAX_EV || cfg->n_ev_activity > (uint32_t)UI_MAX_EV ||
        (cfg->sample_every > 0U && cfg->tick_ms == 0U)) {
        return -1;
    }
    u->schema = schema;
    u->cfg = *cfg;
    if (world != NULL) {
        u->world = *world;
    }
    u->started = 1;
    return 0;
}

int ui_feed(ui_t *u, const sim_rec_t *rec) {
    if (u->started == 0U || rec == NULL || (rec->len > 0U && rec->bytes == NULL) || advance(u, rec->t_ms) != 0) {
        return -1;
    }
    if (rec->kind[0] == 'e' && rec->kind[1] == 'v') {
        on_ev(u, rec);
    } else if (rec->kind[0] == 'v' && rec->kind[1] == 'w') {
        on_view(u, rec);
    }
    u->records++;
    u->counts.records++;
    return 0;
}

int ui_finish(ui_t *u, uint64_t t_end_ms) {
    if (u->started == 0U || advance(u, t_end_ms) != 0) {
        return -1;
    }
    if (u->have_prev != 0U) {
        lang_rule(u, &u->prev);
    }
    return 0;
}

uint32_t ui_finding_count(const ui_t *u) {
    return u->nfindings;
}

const ui_finding_t *ui_finding(const ui_t *u, uint32_t index) {
    return index < u->nfindings ? &u->findings[index] : NULL;
}

int ui_has_rule(const ui_t *u, ui_rule_t rule) {
    return (int)((u->rules_seen >> ((unsigned)rule & 31U)) & 1U);
}

int ui_has_inv(const ui_t *u, ui_inv_t inv) {
    return (int)((u->inv_seen >> ((unsigned)inv & 31U)) & 1U);
}

uint32_t ui_dropped(const ui_t *u) {
    return u->dropped;
}

ui_counts_t ui_counts(const ui_t *u) {
    return u->counts;
}
