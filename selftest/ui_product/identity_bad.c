/* U24 fix-up 1: a toy build whose scene identity breaks the interface, for the probe's rules (selftest/ui.sh): it
 * announces identity; its first `uim_identity` writes a node line without any identity (`err identity
 * model-contract`), its second names one key twice (the same), its third fails (`fail identity`); every later one is a
 * valid reply. None of them poisons: the commands after them still work. The calls are counted in the process (a
 * session of this probe is one process), not in the model, which this file cannot see. */
#include <string.h>

#include "ui/model/model.h"

static unsigned g_calls;

bool uim_identity_supported(void)
{
    return true;
}

static bool put(uim_buf_t *out, const char *text)
{
    size_t n = strlen(text);
    if (n > out->cap) {
        return false;
    }
    memcpy(out->data, text, n);
    out->len = n;
    return true;
}

bool uim_identity(uim_t *m, uim_buf_t *out)
{
    (void)m;
    out->len = 0;
    g_calls++;
    if (g_calls == 1u) {
        return put(out, "state\ttoy\nnode\tbutton\t-\t-\t0\n");
    }
    if (g_calls == 2u) {
        return put(out, "state\ttoy\nnode\tbutton\t-\ttoy.press\t0\nnode\tbutton\tb\t-\t0\n");
    }
    return g_calls != 3u && put(out, "state\ttoy\nnode\tbutton\t-\ttoy.press\t0\n");
}
