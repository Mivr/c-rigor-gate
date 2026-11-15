/* The `frame` command and the seam where `lvprobe` joins the probe (U05). This file is the one a later task extends. */
#include "ui/model/probe.h"

/* SEAM(U05): after `uim_frame` produced `disp`, U05 writes the facts of the frame (tree, ink, hit table, CRC) here as
 * printable ASCII and TAB lines, each ended by LF; they become the lines of the `frame` reply. The probe checks the
 * bytes. Today it writes none. */
static bool seam_frame_lines(struct _lv_display_t *disp, char *out, size_t cap, size_t *len)
{
    (void)disp;
    (void)out;
    (void)cap;
    *len = 0;
    return true;
}

bool probe_cmd_frame(probe_t *p, char **arg)
{
    struct _lv_display_t *disp = NULL;
    size_t cap = 0;
    char *payload = probe_payload(&cap);
    size_t len = 0;
    long lines = 0;
    (void)arg;
    if (!uim_frame(p->model, &disp)) {
        p->opened = false;
        return probe_reply_plain("frame", false);
    }
    if (disp != NULL && seam_frame_lines(disp, payload, cap, &len) && len <= cap) {
        lines = probe_check_records(NULL, payload, len);
    } else {
        lines = -1;
    }
    if (lines < 0) {
        p->opened = false;
        return probe_reply_err("frame", "model-contract");
    }
    return probe_reply_lines("frame", (size_t)lines, len);
}
