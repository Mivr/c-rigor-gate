/* The commands `semantic`, `patches`, `trace` and (U24) `identity` (docs/ui-model.md): `ok <name> lines <n>` and the
 * n records verbatim, each checked by the record grammar (probe_records.c; identity: probe_identity.c). `semantic` is read-only: its failure does not poison. A file of
 * its own (U05c: out of probe_main.c, which was at the 500-line limit), so the probe's unit test, which links the
 * grammar check from the probe library, does not pull in the probe's `main`. Static memory only. */
#include "ui/model/probe.h"

typedef bool (*buffer_fn_t)(uim_t *, uim_buf_t *);

/* `semantic`, `patches` and `trace`: `ok <name> lines <n>` and the n records verbatim. */
static bool buffer_reply(probe_t *p, const char *name, buffer_fn_t fn, const probe_spec_t *spec, bool poisons)
{
    uim_buf_t buf;
    long lines = 0;
    size_t cap = 0;
    char *payload = probe_payload(&cap);
    buf.data = payload;
    buf.cap = cap;
    buf.len = 0;
    if (!fn(p->model, &buf)) {
        p->opened = p->opened && !poisons;
        return probe_reply_plain(name, false);
    }
    lines = (buf.data == payload && buf.cap == cap && buf.len <= buf.cap)
                ? probe_check_records(spec, payload, buf.len) : -1;
    if (lines < 0) {
        p->opened = p->opened && !poisons;   /* the read-only call leaves the model as it was */
        return probe_reply_err(name, "model-contract");
    }
    return probe_reply_lines(name, (size_t)lines, buf.len);
}

bool probe_cmd_semantic(probe_t *p, char **arg)
{
    (void)arg;
    return buffer_reply(p, "semantic", uim_semantic, &PROBE_SPEC_SEMANTIC, false);
}

bool probe_cmd_patches(probe_t *p, char **arg)
{
    (void)arg;
    return buffer_reply(p, "patches", uim_patches, &PROBE_SPEC_PATCHES, true);
}

bool probe_cmd_trace(probe_t *p, char **arg)
{
    (void)arg;
    return buffer_reply(p, "trace", uim_trace, &PROBE_SPEC_TRACE, true);
}

/* `identity` (U24): read-only like `semantic` (neither a failing call nor a breach poisons). A probe that did not
 * announce the capability (`uim_identity_supported()` false at the greeting) replies `err identity unsupported`; a
 * product whose answer changed since is `err identity model-contract`. */
bool probe_cmd_identity(probe_t *p, char **arg)
{
    uim_buf_t buf;
    long lines = 0;
    size_t cap = 0;
    char *payload = probe_payload(&cap);
    (void)arg;
    if (!p->identity) {
        return probe_reply_err("identity", "unsupported");
    }
    if (!uim_identity_supported()) {
        return probe_reply_err("identity", "model-contract");
    }
    buf.data = payload;
    buf.cap = cap;
    buf.len = 0;
    if (!uim_identity(p->model, &buf)) {
        return probe_reply_plain("identity", false);
    }
    lines = (buf.data == payload && buf.cap == cap && buf.len <= buf.cap) ? probe_check_identity(payload, buf.len) : -1;
    if (lines < 0) {
        return probe_reply_err("identity", "model-contract");
    }
    return probe_reply_lines("identity", (size_t)lines, buf.len);
}
