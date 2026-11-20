/* The fixture replayer of the oracle gate (T2G7): a toy pad kiosk. It reads one vm-trace/1 file on stdin and writes the replayed
 * one on stdout: the cfg and in lines as given, then the fx and vw lines of this kiosk for each input. The oracle bundle holds
 * the same pad as a Rust trace; the gate compares the two byte for byte. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define LINE_MAX_BYTES 320U   /* the fixture's longest line (cfg) is 258 bytes; a longer one is an error, never truncated */
#define PAD_DIGITS 4
#define OPEN_MS 3000L

typedef struct {
    int entered;
    int opened;
    long countdown_ms;
} pad_t;

static void emit_view(unsigned long t, const pad_t *pad) {
    printf("{\"k\":\"vw\",\"t\":%lu,\"s\":{\"screen\":\"%s\",\"entered\":%d,\"countdown_ms\":%ld}}\n", t, pad->opened ? "opened" : "pad",
           pad->entered, pad->countdown_ms);
}

static void emit_effect(unsigned long t, const char *rest) {
    printf("{\"k\":\"fx\",\"t\":%lu,\"port\":%s}\n", t, rest);
}

static void submit(unsigned long t, pad_t *pad) {
    if (pad->opened || pad->entered != PAD_DIGITS) {
        return;
    }
    emit_effect(t, "\"codes.role_of\"");
    emit_effect(t, "\"opener.open\",\"row\":1,\"col\":2");
    pad->opened = 1;
    pad->entered = 0;
    pad->countdown_ms = OPEN_MS;
}

static void tick(unsigned long t, pad_t *pad, long adv_ms) {
    if (!pad->opened) {
        return;
    }
    pad->countdown_ms -= adv_ms;
    if (pad->countdown_ms <= 0) {
        pad->countdown_ms = 0;
        pad->opened = 0;
        emit_effect(t, "\"audit.append\",\"kind\":\"closed\"");
    }
}

static int has_op(const char *line, const char *op) {
    char needle[48];
    (void)snprintf(needle, sizeof needle, "\"op\":\"%s\"", op);
    return strstr(line, needle) != NULL;
}

static long number_after(const char *line, const char *key) {
    const char *at = strstr(line, key);
    return at == NULL ? 0L : strtol(at + strlen(key), NULL, 10);
}

static void step(const char *line, pad_t *pad) {
    unsigned long t = (unsigned long)number_after(line, "\"t\":");
    if (has_op(line, "digit") && !pad->opened && pad->entered < PAD_DIGITS) {
        pad->entered++;
    } else if (has_op(line, "backspace") && !pad->opened && pad->entered > 0) {
        pad->entered--;
    } else if (has_op(line, "cancel") && !pad->opened) {
        pad->entered = 0;
    } else if (has_op(line, "submit")) {
        submit(t, pad);
    } else if (has_op(line, "tick")) {
        tick(t, pad, number_after(line, "\"adv_ms\":"));
    } else if (has_op(line, "ack_opened") && pad->opened) {
        pad->opened = 0;
        pad->countdown_ms = 0;
    }
    emit_view(t, pad);
}

int main(void) {
    char line[LINE_MAX_BYTES];
    pad_t pad = {0, 0, 0L};
    while (fgets(line, (int)sizeof line, stdin) != NULL) {
        if (strchr(line, '\n') == NULL) {
            return 1;
        }
        if (strncmp(line, "{\"k\":\"cfg\"", 10) == 0) {
            (void)fputs(line, stdout);
        } else if (strncmp(line, "{\"k\":\"in\"", 9) == 0) {
            (void)fputs(line, stdout);
            step(line, &pad);
        }
    }
    return 0;
}
