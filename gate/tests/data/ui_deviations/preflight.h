/* apps/lockers/lk/preflight/preflight.h: the `--check-config` judges and report text, evaluated from readings.
 *
 * Pure: every reading is an argument, nothing is read, written, timed or pulsed. No allocation, no mutable
 * static data, no clock. Level L3. Included as "apps/lockers/lk/preflight/preflight.h".
 * Used only by lkapp/checkconfig (the installer preflight runner, which gathers the readings and prints the
 * text). Deps: core (core_str_t, core_buf_t). It does not use lk/types, fmt or lk/selftest.
 * Split from lk/selftest on purpose (low fan-out): selftest owns the boot and end-of-shift `checks` token,
 * this module owns the seven installer lines.
 *
 * ORACLE. The Rust kiosk, domain/lockers-preflight/src/lib.rs ("RS" below is that file, with its line numbers;
 * "RSA" is apps/lockers/src/preflight.rs, which only gathers the readings). Where the docs disagree, Rust wins.
 *
 * ENGLISH HERE ON PURPOSE. `--check-config` output is installer CLI text: it is not translated (the i18n
 * exemption for CLI tools, logs and --check-config). Every sentence below is byte for byte the Rust sentence,
 * numbers included. A line is "<MARK> <words>" where MARK is OK, WARN or FAIL, and a report line ends in LF.
 * `{n}` below means a number in plain decimal (no sign, no leading zeros, "0" for zero, up to
 * 18446744073709551615 for a uint64_t); `{s}` means a borrowed string copied byte for byte.
 *
 * CHECK (RS 25-37). lk_pf_check_t is a mark (LK_PF_OK, LK_PF_WARN, LK_PF_FAIL) plus its words: a NUL
 * terminated string of at most LK_PF_WORDS_MAX (127) bytes in `words[LK_PF_WORDS_CAP]` (128). The words are
 * plain language, never a code or a token. Every function that fills a check either fills it completely (mark
 * set, words NUL terminated, every byte after the NUL zero) and returns true, or returns false and sets the
 * WHOLE struct to zero bytes (mark LK_PF_OK, empty words). It returns false iff an argument is NULL (where the
 * argument is documented as required) or the finished words would be longer than 127 bytes (only the
 * borrowed strings `message`, `label`, `kiosk_id`, `belongs_to` and `config_says` can do that). A false return
 * never writes anything else. The enum fields of every reading hold one of their named values; any other value
 * is not promised. A payload field is read only when its kind says so and is ignored otherwise.
 *
 * MARK NAMES (RS 14-22): lk_pf_mark_name gives "OK", "WARN", "FAIL"; NULL for any other value.
 * A check whose mark is outside OK/WARN/FAIL: lk_pf_line returns false and writes nothing; lk_pf_render skips it
 * (no mark text, no LF) without setting overflow.
 * LINE (RS 34-36, lk_pf_line): "<MARK> <words>", one space between, no LF, appended to a core_buf_t in ONE
 * all-or-nothing append (core_buf rules). Empty words give "<MARK> " (the trailing space stays).
 *
 * THE JUDGES. Each takes one reading and fills one check. The sentences, with their RS line:
 *  J1 judge_config (RS 144-150). lk_pf_config_t.kind LK_PF_CONFIG_ACCEPTED reads mode_0600 (bool);
 *     LK_PF_CONFIG_REJECTED reads message (core_str_t, borrowed; the sentence boot prints when it refuses the
 *     file; the empty string is allowed).
 *       ACCEPTED, mode_0600 true   -> OK   "config"                                   (RS 146)
 *       ACCEPTED, mode_0600 false  -> WARN "config mode is not 0600"                   (RS 147)
 *       REJECTED                   -> FAIL {message}                                   (RS 148)
 *  J2 judge_data (RS 153-186). lk_pf_data_t: creatable, mode_0700, writable, created (bool); free_known (bool)
 *     and free_mb (uint64_t; read only when free_known; free_known false is Rust `free_mb: None`); min_free_mb
 *     (uint64_t, used as given). `free` below is free_mb. The FIRST rule that applies wins, in this order:
 *       1. !creatable                          -> FAIL "could not create the data directory"                (RS 155)
 *       2. !writable                           -> FAIL "data directory is not writable"                     (RS 158)
 *       3. !free_known                         -> FAIL "free space could not be read"                       (RS 161)
 *       4. free < min_free_mb (strictly)       -> FAIL "data directory has {free} MB free, below min_free_mb {min_free_mb}"  (RS 163-167)
 *       5. !mode_0700                          -> WARN "data directory mode is not 0700, {free} MB free"    (RS 169-173)
 *       6. near_full(free, min_free_mb)        -> WARN "data directory writable, {free} MB free, near min_free_mb {min_free_mb}" (RS 174-179)
 *       7. created                             -> OK   "data directory created, mode 0700, {free} MB free"  (RS 180-184)
 *       8. otherwise                           -> OK   "data directory writable, {free} MB free"            (RS 185)
 *     near_full (RS 189-194): false when min_free_mb == 0; else free < sat_mul(min_free_mb, 2), where sat_mul
 *     saturates at UINT64_MAX (so free == min is near; free == 2*min is not; and for min_free_mb > UINT64_MAX/2
 *     the bar is UINT64_MAX: free == UINT64_MAX is not near, any smaller free at or above min is near).
 *     creatable false wins over everything, writable over free, and so on in the order above. `created` is read
 *     only by rules 7 and 8.
 *  J3 judge_book (RS 197-208). lk_pf_book_t.kind LK_PF_BOOK_ABSENT, _LOADED (reads uncertain, uint32_t) or
 *     _UNREADABLE.
 *       ABSENT                  -> OK   "no book file, 0 uncertain entries blocking lockers"            (RS 199)
 *       LOADED, uncertain == 0  -> OK   "book loaded, 0 uncertain entries blocking lockers"            (RS 201)
 *       LOADED, uncertain >= 1  -> WARN "{uncertain} uncertain entries are blocking lockers"           (RS 204)
 *                                  (always "entries": "1 uncertain entries are blocking lockers")
 *       UNREADABLE              -> FAIL "could not load the reservation book"                          (RS 206)
 *  J4 judge_inventory (RS 226-261). lk_pf_inventory_t.kind LK_PF_INV_LOADED (reads n and sizes[0..n)) or
 *     LK_PF_INV_UNREADABLE. n is at most LK_PF_SIZES_MAX (6, = LK_SIZES_CAP); n > 6 on a LOADED reading is
 *     false (the check is zeroed). Each lk_pf_size_t is a label (core_str_t, borrowed; any bytes, may be
 *     empty) and a count (uint32_t). `words` = for each size in order, "{label} {count}", joined by ", "
 *     (RS 246-257; e.g. "Small 9, Medium 0, Large 0"; label "" and count 3 give " 3").
 *       UNREADABLE                         -> FAIL "could not load the locker inventory"                (RS 228)
 *       LOADED, n == 0                     -> WARN "inventory has no sizes"                             (RS 235)
 *       LOADED, every count == 0 (n >= 1)  -> WARN "inventory has no lockers: {words}"                  (RS 240)
 *       LOADED, some count >= 1            -> OK   "inventory {words}"                                  (RS 242)
 *     (the Rust total saturates at u32::MAX; it is zero iff every count is zero, so UINT32_MAX plus 1 is "some".)
 *  J4b counts_by_size (RS 212-223, lk_pf_counts_by_size): builds the LOADED inventory from rows of
 *     lk_pf_row_t {core_str_t label; size_t count}. The result has kind LOADED, n = n_rows, and for each row
 *     the same label (same pointer and length, not copied) and count = count, except a count above UINT32_MAX
 *     becomes UINT32_MAX (Rust `u32::try_from(count).unwrap_or(u32::MAX)`). The order is kept. Returns false
 *     (and sets the whole *out to zero bytes when out is non-NULL) when out is NULL, when rows is NULL and
 *     n_rows > 0, or when n_rows > LK_PF_SIZES_MAX. n_rows == 0 is valid (rows may be NULL). Every slot of
 *     sizes[] at index >= n_rows is zero.
 *  J5 judge_codes (RS 264-310). lk_pf_codes_t: fetch kind LK_PF_FETCH_LISTED (reads active and staff,
 *     uint32_t), _REJECTED or _UNREACHABLE; cache kind LK_PF_CACHE_MISSING, _UNREADABLE or _KNOWN (reads
 *     cache_age_ms, uint64_t); max_age_ms (uint64_t, the codes_cache_max_age in milliseconds). `cache` words:
 *       MISSING   -> "no saved cache"                                                                  (RS 302)
 *       UNREADABLE-> "saved cache unreadable"                                                          (RS 303)
 *       KNOWN     -> "cache age {cache_age_ms / 1000}s" (integer division: 999 ms is "0s", 1000 is "1s")(RS 304, 309)
 *       LISTED, active == 0   -> WARN "codes active 0, staff {staff}, {cache}"      (any cache)        (RS 267-269)
 *       LISTED, active >= 1   -> "codes active {active}, staff {staff}, {cache}", mark WARN when the cache is
 *                                UNREADABLE, else OK                                                   (RS 270-277)
 *       REJECTED              -> FAIL "codes token was rejected, {cache}"                              (RS 278)
 *       UNREACHABLE           -> "codes server unreachable, {cache}", mark WARN when the cache can boot, else
 *                                FAIL                                                                  (RS 279-285)
 *     The cache can boot (RS 293-298) iff the cache is KNOWN and cache_age_ms <= max_age_ms (inclusive: equal
 *     passes); MISSING and UNREADABLE never can, whatever max_age_ms is.
 *  J6 judge_relay (RS 313-321, lk_pf_judge_relay(uint8_t reading, check*)): LK_PF_RELAY_ALL_OFF, _SOME_ON,
 *     _KIOSK_RUNNING (another process holds the shared relay lock), _UNREACHABLE, _LOCK_UNAVAILABLE.
 *       ALL_OFF -> OK "relay coils all off"   SOME_ON -> FAIL "relay a coil is on"
 *       KIOSK_RUNNING -> WARN "relay kiosk running"   UNREACHABLE -> FAIL "relay board not reachable"
 *       LOCK_UNAVAILABLE -> FAIL "relay lock unavailable"                                              (RS 315-319)
 *  J7 judge_sync (RS 324-347). lk_pf_sync_t.kind LK_PF_SYNC_OFF, _TOKEN (reads kiosk_id, core_str_t; and
 *     has_last_seq, bool, with last_seq, uint64_t, read only when has_last_seq), _REJECTED, _MISMATCH (reads
 *     belongs_to and config_says, core_str_t) or _UNREACHABLE. Strings are borrowed and may be empty.
 *       OFF         -> OK   "sync not configured"                                                      (RS 326)
 *       TOKEN       -> OK   "sync token for {kiosk_id}, last seq {seq}" with {seq} = "none" when
 *                           !has_last_seq, else last_seq in decimal ("0" for zero)                     (RS 327-330, 342-347)
 *       REJECTED    -> FAIL "sync token rejected"                                                      (RS 331)
 *       MISMATCH    -> FAIL "sync token belongs to {belongs_to}, config says {config_says}"            (RS 332-337)
 *       UNREACHABLE -> FAIL "sync server unreachable"                                                  (RS 338)
 *
 * THE REPORT (RS 132-141, 352-366). lk_pf_input_t holds config, data, inventory, codes, sync as POINTERS
 * (all five required, non-NULL), book as a value and relay as a value.
 *   lk_pf_report_len(in): 1 when in->config->kind is LK_PF_CONFIG_REJECTED (a rejected config stops the
 *     report: later probes did not run, even when its message is too long to build), else 7. 0 when `in` or
 *     any of the five pointers is NULL.
 *   lk_pf_report_check(in, index, out): fills `out` with the index-th check of the assembled report, or returns
 *     false (out zeroed when non-NULL) when `in` or a pointer is NULL, index >= lk_pf_report_len(in), or that
 *     judge returns false. The order is fixed (RS 357-365): 0 config (J1), 1 data (J2), 2 book (J3),
 *     3 inventory (J4), 4 codes (J5), 5 relay (J6), 6 sync (J7). With a rejected config only index 0 exists:
 *     the config FAIL. A WARN config (mode not 0600) does not stop the report.
 *   lk_pf_any_failed(checks, n) (RS 369-371): true iff some check has mark FAIL; false for n == 0 (checks may
 *     then be NULL) and for NULL with n > 0. Only FAIL counts; WARN never does.
 *   lk_pf_exit_code(checks, n) (RS 375-377): 1 when lk_pf_any_failed, else 0.
 *   lk_pf_render(checks, n, b) (RS 381-388): for each check in order appends its line (LINE above) and one LF,
 *     each line+LF in ONE all-or-nothing append. n == 0 appends nothing. Overflow is sticky, as core_buf: the
 *     first line+LF that does not fit sets the overflow flag, the buffer keeps the whole lines before it, and
 *     every later line is ignored (so the text is always a whole number of lines, a prefix of the full
 *     report). Returns true iff `b` is non-NULL, `checks` is non-NULL or n == 0, and the overflow flag of `b`
 *     is clear on return (so false when b was already overflowed on entry, even for n == 0).
 *   lk_pf_render_report(in, b): the same text as lk_pf_render over the lk_pf_report_len(in) checks of the
 *     report, without needing the array. Returns false (and appends nothing for the failing line and after) when
 *     `in`/`b` or a pointer is NULL (then `b` is not touched at all), when a judge returns false (words too long; the whole lines before it were
 *     appended and the overflow flag is NOT set by this), or on overflow as above.
 *   lk_pf_report_exit_code(in): the exit code of the assembled report: 1 when any check of the report is
 *     FAIL, or when a check cannot be built (a judge returns false: the safe side), or when `in` or a pointer
 *     is NULL; else 0. It never looks at an output buffer: an overflowed render does NOT change the exit
 *     code; the caller sees the overflow from the false return of render (and core_buf_overflow) instead.
 *
 * DISAGREEMENTS (Rust wins). The design.md row put `lk_preflight_line(const lk_pf_item_t*, core_buf_t*)` on
 * lk/selftest; it moved here (the Rust crate is a separate unit, and this keeps selftest small). Its role is
 * lk_pf_line plus lk_pf_render. design.md's one-item API is replaced by the check/array API above, because the
 * Rust tests are over Vec<Check>. Rust returns an owned String; here words are a fixed 128-byte field, so a
 * borrowed string that makes a sentence longer than 127 bytes is the one case Rust has no counterpart for
 * (false return, see CHECK).
 */
#ifndef LK_PREFLIGHT_H
#define LK_PREFLIGHT_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "lib/base/core/buf.h"
#include "lib/base/core/str.h"

#define LK_PF_WORDS_CAP 128u
#define LK_PF_WORDS_MAX 127u
#define LK_PF_SIZES_MAX 6u
#define LK_PF_REPORT_CHECKS 7u

enum { LK_PF_OK = 0, LK_PF_WARN = 1, LK_PF_FAIL = 2 };
enum { LK_PF_CONFIG_ACCEPTED = 0, LK_PF_CONFIG_REJECTED = 1 };
enum { LK_PF_BOOK_ABSENT = 0, LK_PF_BOOK_LOADED = 1, LK_PF_BOOK_UNREADABLE = 2 };
enum { LK_PF_INV_LOADED = 0, LK_PF_INV_UNREADABLE = 1 };
enum { LK_PF_FETCH_LISTED = 0, LK_PF_FETCH_REJECTED = 1, LK_PF_FETCH_UNREACHABLE = 2 };
enum { LK_PF_CACHE_MISSING = 0, LK_PF_CACHE_UNREADABLE = 1, LK_PF_CACHE_KNOWN = 2 };
enum {
    LK_PF_RELAY_ALL_OFF = 0,
    LK_PF_RELAY_SOME_ON = 1,
    LK_PF_RELAY_KIOSK_RUNNING = 2,
    LK_PF_RELAY_UNREACHABLE = 3,
    LK_PF_RELAY_LOCK_UNAVAILABLE = 4
};
enum {
    LK_PF_SYNC_OFF = 0,
    LK_PF_SYNC_TOKEN = 1,
    LK_PF_SYNC_REJECTED = 2,
    LK_PF_SYNC_MISMATCH = 3,
    LK_PF_SYNC_UNREACHABLE = 4
};

typedef struct {
    uint8_t mark;
    char words[LK_PF_WORDS_CAP];
} lk_pf_check_t;

typedef struct {
    uint8_t kind;
    bool mode_0600;     /* ACCEPTED only */
    core_str_t message; /* REJECTED only */
} lk_pf_config_t;

typedef struct {
    bool creatable;
    bool mode_0700;
    bool writable;
    bool free_known;
    uint64_t free_mb; /* read only when free_known */
    uint64_t min_free_mb;
    bool created;
} lk_pf_data_t;

typedef struct {
    uint8_t kind;
    uint32_t uncertain; /* LOADED only */
} lk_pf_book_t;

typedef struct {
    core_str_t label;
    uint32_t count;
} lk_pf_size_t;

typedef struct {
    uint8_t kind;
    uint8_t n;                           /* LOADED only: 0..LK_PF_SIZES_MAX */
    lk_pf_size_t sizes[LK_PF_SIZES_MAX]; /* LOADED only: [0..n) */
} lk_pf_inventory_t;

typedef struct {
    core_str_t label;
    size_t count;
} lk_pf_row_t;

typedef struct {
    uint8_t fetch;
    uint32_t active; /* LISTED only */
    uint32_t staff;  /* LISTED only */
    uint8_t cache;
    uint64_t cache_age_ms; /* KNOWN only */
    uint64_t max_age_ms;
} lk_pf_codes_t;

typedef struct {
    uint8_t kind;
    core_str_t kiosk_id;    /* TOKEN only */
    bool has_last_seq;      /* TOKEN only */
    uint64_t last_seq;      /* TOKEN with has_last_seq only */
    core_str_t belongs_to;  /* MISMATCH only */
    core_str_t config_says; /* MISMATCH only */
} lk_pf_sync_t;

typedef struct {
    const lk_pf_config_t *config;
    const lk_pf_data_t *data;
    lk_pf_book_t book;
    const lk_pf_inventory_t *inventory;
    const lk_pf_codes_t *codes;
    uint8_t relay;
    const lk_pf_sync_t *sync;
} lk_pf_input_t;

const char *lk_pf_mark_name(uint8_t mark);
bool lk_pf_check_make(lk_pf_check_t *out, uint8_t mark, core_str_t words); /* out NULL or words > 127: false */
bool lk_pf_line(const lk_pf_check_t *c, core_buf_t *b);                    /* true iff appended; NULL args or b overflowed: false */

bool lk_pf_judge_config(const lk_pf_config_t *in, lk_pf_check_t *out);
bool lk_pf_judge_data(const lk_pf_data_t *in, lk_pf_check_t *out);
bool lk_pf_judge_book(const lk_pf_book_t *in, lk_pf_check_t *out);
bool lk_pf_counts_by_size(const lk_pf_row_t *rows, size_t n_rows, lk_pf_inventory_t *out);
bool lk_pf_judge_inventory(const lk_pf_inventory_t *in, lk_pf_check_t *out);
bool lk_pf_judge_codes(const lk_pf_codes_t *in, lk_pf_check_t *out);
bool lk_pf_judge_relay(uint8_t reading, lk_pf_check_t *out);
bool lk_pf_judge_sync(const lk_pf_sync_t *in, lk_pf_check_t *out);

size_t lk_pf_report_len(const lk_pf_input_t *in);
bool lk_pf_report_check(const lk_pf_input_t *in, size_t index, lk_pf_check_t *out);
bool lk_pf_any_failed(const lk_pf_check_t *checks, size_t n);
uint8_t lk_pf_exit_code(const lk_pf_check_t *checks, size_t n);
bool lk_pf_render(const lk_pf_check_t *checks, size_t n, core_buf_t *b);
bool lk_pf_render_report(const lk_pf_input_t *in, core_buf_t *b);
uint8_t lk_pf_report_exit_code(const lk_pf_input_t *in);

#endif
