#include "sim/inv/tests/ui_model.h"

#include <stdio.h>
#include <string.h>

#include "sim/inv/tests/ui_rig.h"

enum { VF_MESSAGE = 1, VF_NO_DISMISS = 2, SCREEN_WELCOME = 0, SCREEN_CHOOSE = 1, SCREEN_OPENED = 2, IDLE_STEP = 5000, LANG_RESET_MS = 30000 };

typedef struct {
    uint8_t lang_en, screen, has_notice, cd_null;
    uint32_t pad, locker;
    uint64_t notice_end, last_act;
} mstate_t;

typedef struct {
    ui_t *u;
    uint64_t seed, rng, t_last, snap_t;
    umodel_bug_t bug;
    int rc, dry, stopped, bug_set;
    uint32_t stop_at, nrec, bug_record;
    mstate_t st, snap;
    char text[1100]; /* the view being fed: the engine reads it while the replay callback renders others */
    umodel_out_t out;
} model_t;

static model_t M;
static model_t D; /* the dry run of a replay */

/* splitmix64: the model's own seeded stream. */
static uint64_t rng_next(model_t *m) {
    uint64_t z = (m->rng += 0x9e3779b97f4a7c15ULL);
    z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ULL;
    z = (z ^ (z >> 27)) * 0x94d049bb133111ebULL;
    return z ^ (z >> 31);
}

/* The view of a state at a time (a ring buffer of the rig: use it before the next call). */
static const char *render(const mstate_t *s, uint64_t t, umodel_bug_t bug, uint32_t flags) {
    static char fields[80];
    static char countdown[24];
    const char *lang = s->lang_en != 0U && (bug == UMODEL_LANG_NOT_RESET || t - s->last_act < LANG_RESET_MS) ? "en" : "bg";
    const char *notice = "null";
    const char *screen = "welcome";
    snprintf(fields, sizeof fields, "\"pad_len\":%u", s->pad);
    if (s->screen == SCREEN_CHOOSE) {
        screen = "choose";
        snprintf(fields, sizeof fields, "\"sizes\":[]");
    } else if (s->screen == SCREEN_OPENED) {
        screen = "opened";
        snprintf(fields, sizeof fields, "\"locker\":%u,\"first_time\":true", s->locker);
    }
    if (s->has_notice != 0U) {
        snprintf(countdown, sizeof countdown, "%llu", (unsigned long long)(s->notice_end - t));
        notice = urig_notice("dialog", "overlay", "reject_invalid", s->cd_null != 0U ? "null" : countdown);
        notice = (flags & VF_NO_DISMISS) != 0U ? urig_edit(notice, "\"dismiss\":\"overlay\"", "\"dismiss\":null") : notice;
    }
    return urig_screen((flags & VF_MESSAGE) != 0U ? "message" : screen, lang, fields, notice, "");
}

static void count_record(model_t *m, uint64_t t) {
    if (m->dry != 0 && m->nrec == m->stop_at) {
        m->snap = m->st;
        m->snap_t = t;
        m->stopped = 1;
    }
    m->nrec++;
    m->t_last = t;
}

static void mark_bug(model_t *m) {
    if (m->bug_set == 0) {
        m->bug_set = 1;
        m->bug_record = m->nrec;
    }
}

static void emit_ev(model_t *m, uint64_t t, uint32_t type) {
    sim_rec_t rec = {{'e', 'v'}, t, type, 0, NULL, 0};
    if (m->stopped != 0) {
        return;
    }
    if (m->dry == 0 && ui_feed(m->u, &rec) != 0) {
        m->rc = -1;
    }
    count_record(m, t);
}

static void emit_view(model_t *m, uint64_t t, uint32_t flags) {
    sim_rec_t rec = {{'v', 'w'}, t, 0, 0, NULL, 0};
    if (m->stopped != 0) {
        return;
    }
    if (m->st.screen != SCREEN_WELCOME) {
        m->st.last_act = t;
    }
    if (m->bug == UMODEL_LANG_NOT_RESET && m->st.lang_en != 0U && m->st.screen == SCREEN_WELCOME && t - m->st.last_act >= LANG_RESET_MS + 2000U) {
        mark_bug(m);
    }
    snprintf(m->text, sizeof m->text, "%s", render(&m->st, t, m->bug, flags));
    rec.bytes = (const uint8_t *)m->text;
    rec.len = (uint32_t)strlen(m->text);
    if (m->dry == 0 && ui_feed(m->u, &rec) != 0) {
        m->rc = -1;
    }
    count_record(m, t);
}

static void idle_until(model_t *m, uint64_t t_to) {
    m->st.screen = SCREEN_WELCOME;
    m->st.pad = 0;
    for (uint64_t t = m->t_last + IDLE_STEP; t < t_to; t += IDLE_STEP) {
        emit_view(m, t, 0);
    }
}

/* The rejection dialog of an even visit: 8 s of countdown, dismissed on every second one, expiring on the others. */
static void notice_phase(model_t *m, uint32_t k, uint64_t t0) {
    mstate_t *s = &m->st;
    uint64_t end = t0 + 14500U;
    uint64_t first = t0 + 6500U;
    s->has_notice = 1;
    s->notice_end = end;
    s->cd_null = (uint8_t)(m->bug == UMODEL_COUNTDOWN_NULL && k == 2U);
    m->out.notices++;
    for (uint64_t t = first; t < end; t += 1000U) {
        uint32_t flags = 0;
        if (t == first && k == 2U && m->bug == UMODEL_FULL_SCREEN_MESSAGE) {
            flags = VF_MESSAGE;
            mark_bug(m);
        }
        if (t == first && k == 2U && m->bug == UMODEL_NOTICE_WITHOUT_DISMISS) {
            flags = VF_NO_DISMISS;
            mark_bug(m);
        }
        if (t == first && m->bug == UMODEL_DISMISS_IGNORED) {
            mark_bug(m);
        }
        if (k % 4U == 0U && t == t0 + 9500U) {
            s->last_act = t;
            emit_ev(m, t, U_EV_DISMISS);
            if (m->bug != UMODEL_DISMISS_IGNORED) {
                s->has_notice = 0;
                m->out.dismissed++;
                emit_view(m, t, 0);
                return;
            }
        }
        emit_view(m, t, flags);
    }
    s->has_notice = 0;
    m->out.expired++;
    if (m->bug == UMODEL_COUNTDOWN_NULL && k == 2U) {
        mark_bug(m);
    }
    emit_view(m, end, 0);
}

/* One visit from t0: typing, choosing, the opened screen, then the welcome screen, and the rejection of an even visit. */
static void visit(model_t *m, uint32_t k, uint64_t t0) {
    mstate_t *s = &m->st;
    if (k % 2U == 1U) {
        s->lang_en = 1;
        s->last_act = t0;
        emit_ev(m, t0, U_EV_LANG);
    }
    for (uint32_t i = 0; i < 3U; i++) {
        s->pad = i + 1U;
        s->last_act = t0 + 100U + 400U * i;
        emit_ev(m, s->last_act, U_EV_DIGIT);
        emit_view(m, s->last_act, 0);
    }
    s->screen = SCREEN_CHOOSE;
    emit_view(m, t0 + 1500U, 0);
    s->screen = SCREEN_OPENED;
    s->locker = 80U + k;
    for (uint32_t i = 0; i < 3U; i++) {
        emit_view(m, t0 + 2500U + 1000U * i, 0);
    }
    s->screen = SCREEN_WELCOME;
    s->pad = 0;
    emit_view(m, t0 + 5500U, 0);
    if (k % 2U == 0U) {
        notice_phase(m, k, t0);
    }
}

static void run_script(model_t *m) {
    uint32_t n = 3U + (uint32_t)(rng_next(m) % 3U);
    uint64_t t0 = 1000;
    emit_view(m, 0, 0);
    for (uint32_t k = 0; k < n; k++) {
        visit(m, k, t0);
        t0 += 60000U + rng_next(m) % 10000U;
        idle_until(m, t0);
        m->out.visits = k + 1U;
    }
    m->out.end_ms = t0;
}

static int cb_phrase(void *ctx, const char *phrase) {
    (void)ctx;
    (void)phrase;
    return 1;
}

/* Re-run the model to the record, apply the intent and let the time pass. */
static int cb_replay(void *ctx, ui_replay_mode_t mode, uint32_t record, uint32_t dismiss, uint32_t advance_ms, uint8_t *out, uint32_t cap, uint32_t *len) {
    const model_t *m = (const model_t *)ctx;
    mstate_t s;
    uint64_t t;
    const char *text;
    (void)dismiss;
    memset(&D, 0, sizeof D);
    D.dry = 1;
    D.stop_at = record;
    D.seed = m->seed;
    D.rng = m->seed;
    D.bug = m->bug;
    run_script(&D);
    if (D.stopped == 0) {
        return -1;
    }
    s = D.snap;
    t = D.snap_t + advance_ms;
    if (mode != UI_REPLAY_WAIT && m->bug != UMODEL_DISMISS_IGNORED) {
        s.has_notice = 0;
    }
    if (s.has_notice != 0U && t >= s.notice_end) {
        s.has_notice = 0;
    }
    text = render(&s, t, m->bug, 0);
    *len = (uint32_t)strlen(text);
    if (*len > cap) {
        return -1;
    }
    memcpy(out, text, *len);
    return 0;
}

int umodel_run(ui_t *u, uint64_t seed, umodel_bug_t bug, umodel_out_t *out) {
    ui_cfg_t cfg;
    ui_schema_t *schema;
    static ui_schema_t S;
    ui_world_t world = {&M, cb_phrase, cb_replay};
    memset(&M, 0, sizeof M);
    M.u = u;
    M.seed = seed;
    M.rng = seed;
    M.bug = bug;
    schema = &S;
    if (ui_schema_parse(schema, URIG_SCHEMA, (uint32_t)strlen(URIG_SCHEMA)) != UI_SE_OK) {
        return -1;
    }
    urig_cfg(&cfg);
    if (ui_init(u, schema, &cfg, &world) != 0) {
        return -1;
    }
    run_script(&M);
    if (ui_finish(u, M.out.end_ms) != 0) {
        M.rc = -1;
    }
    if (out != NULL) {
        *out = M.out;
        out->bug_record = M.bug_record;
    }
    return M.rc;
}
