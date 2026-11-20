/* ctest internal: sanitizer log handling. See sanlog.h. */
#define _GNU_SOURCE
#include "sanlog.h"

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

enum { PATH_CAP = 1024, KIND_CAP = 96, LOC_CAP = 120, FUNC_CAP = 64, LINE_CAP = 512 };

/* Scratch space is static (the parent is single-threaded here) so no frame outgrows the 512-byte limit. */
static char s_path[PATH_CAP];
static char s_line[LINE_CAP];
static char s_kind[KIND_CAP + 32];
static char s_func[FUNC_CAP];
static char s_loc[LOC_CAP];
static char s_pl[LOC_CAP];
static char s_word[KIND_CAP];

size_t sanlog_take(const char *prefix, long pid, char *buf, size_t cap) {
    size_t len = 0;
    int fd;
    if (snprintf(s_path, sizeof s_path, "%s.%ld", prefix, pid) >= (int)sizeof s_path || cap < 2) {
        return 0;
    }
    fd = open(s_path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0) {
        return 0;
    }
    while (len < cap - 1) {
        ssize_t n = read(fd, buf + len, cap - 1 - len);
        if (n < 0 && errno == EINTR) {
            continue;
        }
        if (n <= 0) {
            break;
        }
        len += (size_t)n;
    }
    (void)close(fd);
    (void)unlink(s_path);
    buf[len] = '\0';
    return len;
}

static int is_hex(char c) {
    return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F');
}

static int is_word(char c) {
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_';
}

/* A shadow-memory row: optional "=>" then "0x<hex>:". Its bytes depend on the heap layout. */
static int is_shadow_row(const char *l, const char *end) {
    while (l < end && (*l == ' ' || *l == '=' || *l == '>')) {
        l++;
    }
    if (end - l < 3 || l[0] != '0' || l[1] != 'x') {
        return 0;
    }
    l += 2;
    while (l < end && is_hex(*l)) {
        l++;
    }
    return l < end && *l == ':';
}

/* TSan prints "(pid=7703)" and "(tid=7708, running)": the number of "pid=" or "tid=" at `l`, as the length of
 * "pid=" plus its digits, or 0. The ids differ on every run. */
static size_t id_field_len(const char *l, const char *end) {
    const char *q = l + 4;
    if (end - l < 5 || (memcmp(l, "pid=", 4) != 0 && memcmp(l, "tid=", 4) != 0)) {
        return 0;
    }
    while (q < end && *q >= '0' && *q <= '9') {
        q++;
    }
    return q > l + 4 ? (size_t)(q - l) : 0;
}

/* Copies one line, rewriting pids, tids and hex numbers; returns the number of bytes written. */
static size_t copy_line(char *dst, const char *l, const char *end) {
    size_t w = 0;
    while (l < end) {
        const char *q = l + 1;
        size_t id_len = id_field_len(l, end);
        if (id_len != 0 && (w == 0 || !is_word(dst[w - 1]))) { /* not the tail of a longer word */
            for (int i = 0; i < 4; i++) { /* "pid=" or "tid=", one byte at a time: dst may be src */
                dst[w++] = l[i];
            }
            dst[w++] = 'N';
            l += id_len; /* past the digits */
            continue;
        }
        if (l[0] == '=' && l + 1 < end && l[1] == '=') { /* ==<pid>== */
            q = l + 2;
            while (q < end && q[0] >= '0' && q[0] <= '9') {
                q++;
            }
            if (q > l + 2 && q + 1 < end && q[0] == '=' && q[1] == '=') {
                dst[w++] = '=';
                dst[w++] = '=';
                l = q + 2;
                continue;
            }
        }
        if (l[0] == ' ' && l + 11 < end && memcmp(l, " (BuildId: ", 11) == 0) { /* varies per binary */
            while (q < end && *q != ')') {
                q++;
            }
            l = q < end ? q + 1 : q;
            continue;
        }
        if (l[0] == '0' && l + 2 < end && l[1] == 'x' && is_hex(l[2])) {
            q = l + 2;
            while (q < end && is_hex(*q)) {
                q++;
            }
            memcpy(dst + w, "0x_", 3);
            w += 3;
            l = q;
            continue;
        }
        dst[w++] = *l++;
    }
    return w;
}

size_t sanlog_normalize(char *buf, size_t len) {
    size_t r = 0;
    size_t w = 0;
    while (r < len) {
        const char *nl = memchr(buf + r, '\n', len - r);
        size_t ll = nl == NULL ? len - r : (size_t)(nl - (buf + r)) + 1; /* includes the newline */
        if (!is_shadow_row(buf + r, buf + r + ll)) {
            w += copy_line(buf + w, buf + r, buf + r + ll); /* output never outgrows input, w <= r */
        }
        r += ll;
    }
    buf[w] = '\0';
    return w;
}

/* The text after the first occurrence of `key`, or NULL. */
static const char *find_after(const char *text, const char *key) {
    const char *p = strstr(text, key);
    return p == NULL ? NULL : p + strlen(key);
}

static void take_until(char *out, size_t cap, const char *s, const char *stops) {
    size_t n = strcspn(s, stops);
    if (n >= cap) {
        n = cap - 1;
    }
    memcpy(out, s, n);
    out[n] = '\0';
}

static void sanlog_kind(const char *text, char *out, size_t cap) {
    const char *p = find_after(text, "ERROR: AddressSanitizer: ");
    if (p != NULL) {
        take_until(s_word, sizeof s_word, p, " \n");
        (void)snprintf(out, cap, "AddressSanitizer: %s", s_word);
    } else if ((p = find_after(text, "runtime error: ")) != NULL) {
        take_until(s_word, sizeof s_word, p, "\n");
        (void)snprintf(out, cap, "UBSan: %s", s_word);
    } else if (strstr(text, "LeakSanitizer: detected memory leaks") != NULL) {
        (void)snprintf(out, cap, "LeakSanitizer: detected memory leaks");
    } else {
        (void)snprintf(out, cap, "sanitizer output");
    }
}

/* Parses one NUL-terminated line "    #N 0x_ in <func> <file>:<line>[:<col>] ..." into func and "file:line". */
static int parse_frame(const char *l, char *func, char *loc) {
    const char *in = strstr(l, " in ");
    char *last;
    if (l[0] != ' ' || strchr(l, '#') == NULL || in == NULL) {
        return 0;
    }
    in += 4;
    take_until(func, FUNC_CAP, in, " ");
    in += strcspn(in, " ");
    if (*in != ' ') {
        return 0;
    }
    take_until(s_pl, sizeof s_pl, in + 1, " ");
    last = strrchr(s_pl, ':');
    if (last == NULL) {
        return 0;
    }
    if (last != strchr(s_pl, ':')) { /* file:line:col -> file:line */
        *last = '\0';
    }
    (void)snprintf(loc, LOC_CAP, "%s", s_pl);
    return 1;
}

static int is_product_loc(const char *loc) {
    size_t n = strcspn(loc, ":");
    static const char *const own[] = {"ctest/ctest.c", "ctest/sanlog.c"};
    if (loc[0] == '/' || loc[0] == '(' || loc[0] == '<' || n == 0) {
        return 0;
    }
    for (size_t i = 0; i < sizeof own / sizeof own[0]; i++) {
        size_t m = strlen(own[i]);
        if (n >= m && memcmp(loc + n - m, own[i], m) == 0) {
            return 0;
        }
    }
    return 1;
}

void sanlog_summary(const char *text, size_t len, char *out, size_t cap) {
    const char *l = text;
    const char *end = text + len;
    sanlog_kind(text, s_kind, sizeof s_kind);
    while (l < end) {
        const char *nl = memchr(l, '\n', (size_t)(end - l));
        size_t ll = nl == NULL ? (size_t)(end - l) : (size_t)(nl - l);
        if (ll >= sizeof s_line) {
            ll = sizeof s_line - 1;
        }
        memcpy(s_line, l, ll);
        s_line[ll] = '\0';
        if (parse_frame(s_line, s_func, s_loc) && is_product_loc(s_loc)) {
            (void)snprintf(out, cap, "%s at %s %s", s_kind, s_loc, s_func);
            return;
        }
        l = nl == NULL ? end : nl + 1;
    }
    (void)snprintf(out, cap, "%s; no frame in product code", s_kind);
}
