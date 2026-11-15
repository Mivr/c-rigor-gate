/* apps/lockers/lk/selftest/selftest.h: the boot and end-of-shift self-test, evaluated from readings.
 *
 * Pure: every reading is an argument, nothing is read, written, timed or pulsed. No allocation, no mutable
 * static data, no clock (the caller passes `now`). Level L3. Included as "apps/lockers/lk/selftest/selftest.h".
 * Used only by the lockers app (lkrx/boot for the `self_test` audit line, lkapp/checkconfig later).
 * Deps: lk/types (the shared lockers vocabulary; the `checks` audit field it feeds is plain `a-z0-9=,` text),
 * fmt (UTC wall-clock helpers for the last-upload time), core (core_buf_t, the token's output).
 * Scope: self-test evaluation only. The `--check-config` preflight lines are a later task.
 *
 * ORACLE. The Rust kiosk, lockers-self-test.rs (`evaluate_self_test` and the helpers named in each rule). Where
 * the docs disagree, Rust wins; the disagreements are listed under DISAGREEMENTS.
 *
 * NO ENGLISH HERE (P001 R19: Rust passes phrase codes, never sentences). Each issue code below is a msgid for
 * the UI catalog task; the Rust `SelfTestIssue::english` sentence is beside it, and the numbers it takes.
 * `{n}` is the issue's `count`; `{HH}:{MM}` is hour and minute, each zero padded to two digits.
 *   LK_ST_RELAY_UNREACHABLE   "Relay board not reachable"
 *   LK_ST_RELAY_ON            "A relay is still on"
 *   LK_ST_CODES_UNAVAILABLE   "Codes unavailable"
 *   LK_ST_NO_ACTIVE_CODES     "No active codes"
 *   LK_ST_NOT_WRITABLE        "Data directory is not writable"
 *   LK_ST_SPACE_UNKNOWN       "Free space could not be read"
 *   LK_ST_DISK_FULL           "Disk almost full"
 *   LK_ST_BOOK_UNREADABLE     "Reservation book could not be loaded"
 *   LK_ST_UNCERTAIN           "{n} uncertain entries are blocking lockers"      (count = uncertain entries)
 *   LK_ST_CLOCK_WRONG         "Clock looks wrong"
 *   LK_ST_SYNC_WAITING        "Sync: {n} events still waiting"                  (count = pending events)
 *   LK_ST_SYNC_WAITING_SINCE  "Sync: {n} events still waiting, last upload {HH}:{MM}"  (count = pending, hour, minute)
 * The healthy staff line "Self-test OK" is not an issue: it is what a result with no issues is shown as.
 * A staff line is one sentence per issue, in issue order (staff_line).
 *
 * THE READINGS (lk_readings_t; one field group per Rust `*Sight` and `SyncSight`). A payload field is read only
 * when its kind says so and is ignored otherwise (Rust: the payload exists only on that variant).
 *   - now_ms, built_at_ms (uint64_t): unix milliseconds. Rust SelfTestInput.now, .built_at.
 *   - relay: LK_RELAY_SIGHT_UNREACHABLE, _ALL_OFF or _SOME_ON.     Rust RelaySight::{Unreachable, Coils{all_off}}.
 *   - codes: LK_CODES_SIGHT_UNAVAILABLE or _LISTED; codes_active (uint32_t) is read only for _LISTED.
 *   - writable (bool).                                             Rust SelfTestInput.writable.
 *   - space: LK_SPACE_SIGHT_UNKNOWN or _MEGABYTES; space_mb (uint64_t) is read only for _MEGABYTES.
 *   - min_free_mb (uint64_t): the free-space bar. Used as given: 0 means 0, there is no substitution of the
 *     default here (the caller passes LK_SELFTEST_DEFAULT_MIN_FREE_MB when config omits it).
 *   - book: LK_BOOK_SIGHT_UNREADABLE or _LOADED; book_uncertain (uint32_t) is read only for _LOADED.
 *   - audit: LK_AUDIT_SIGHT_UNREADABLE, _EMPTY or _NEWEST; audit_newest_ms (uint64_t) is read only for _NEWEST.
 *   - sync_configured (bool): false is Rust `sync: None`; sync_has_last, sync_last_ms and sync_pending are read
 *     only when it is true. sync_has_last false is Rust `last_success: None`.
 * The enum fields hold one of their named values; any other value is not promised.
 *
 * THE RULES (lk_selftest_eval). Each check below adds its issue(s) in THIS order, the fixed order of the Rust
 * `evaluate_self_test` (relay_line, codes_line, storage_lines, clock_line, sync_line):
 *   R1 relay_line:   _UNREACHABLE -> RELAY_UNREACHABLE; _SOME_ON -> RELAY_ON; _ALL_OFF -> pass. relay_ok = no issue.
 *   R2 codes_line:   _UNAVAILABLE -> CODES_UNAVAILABLE; _LISTED with codes_active == 0 -> NO_ACTIVE_CODES;
 *                    _LISTED with codes_active >= 1 -> pass. codes_ok = no issue.
 *   R3 storage_lines, three parts in this order; storage_ok is true iff none of them adds an issue:
 *      R3a writable false -> NOT_WRITABLE.
 *      R3b space_ok / space_issue: _UNKNOWN -> SPACE_UNKNOWN; _MEGABYTES passes iff space_mb > min_free_mb
 *          (STRICTLY greater: space_mb == min_free_mb fails), else DISK_FULL.
 *      R3c book_ok:     _UNREADABLE -> BOOK_UNREADABLE; _LOADED with book_uncertain >= 1 -> UNCERTAIN with
 *          count = book_uncertain; _LOADED with 0 -> pass.
 *   R4 clock_line / clock_ok: ONE issue, CLOCK_WRONG, when any of: now_ms < built_at_ms (strictly; equal passes);
 *      audit is _UNREADABLE; audit is _NEWEST and audit_newest_ms > sat_add(now_ms, LK_SELFTEST_ONE_DAY_MS),
 *      where sat_add saturates at UINT64_MAX (so the clock may sit one day behind the newest audit line, no
 *      further; equal to the bound passes). audit _EMPTY adds nothing. clock_ok = no issue.
 *   R5 sync_line:    sync_configured false -> no check at all (no issue, no sync in the token). Else
 *      sync_pending == 0 -> pass (whatever sync_has_last says); sync_pending >= 1 and sync_has_last ->
 *      SYNC_WAITING_SINCE with count = sync_pending and (hour, minute) = utc_hhmm(sync_last_ms); sync_pending >= 1
 *      and not sync_has_last -> SYNC_WAITING with count = sync_pending. sync_ok = no issue.
 *   R6 utc_hhmm: secs = ms / 1000; day = secs % 86400; hour = day / 3600; minute = (day % 3600) / 60. UTC, no
 *      leap seconds, any uint64_t is valid (so hour 0..23, minute 0..59; 86400000 ms is 00:00 again).
 *   R7 passed is true iff there are no issues. At most LK_SELFTEST_MAX_ISSUES (7) can exist at once: one per
 *      R1, R2, R3a, R3b, R3c, R4, R5.
 *
 * THE TOKEN (lk_selftest_token; Rust `token` and `mark`): the audit `checks` text, exactly
 *   "relay=<m>,codes=<m>,storage=<m>,clock=<m>" and, only when sync_configured, ",sync=<m>", where <m> is
 * "pass" when that check's flag is true and "fail" when false. It is built from the five flags and
 * sync_configured of lk_selftest_t only (never from the issue list). At most LK_SELFTEST_TOKEN_MAX bytes.
 *
 * DISAGREEMENTS (Rust wins). (1) Runbook section 9 and P001 R30 list four checks `relay,codes,storage,clock`;
 * Rust appends `sync=` when sync is configured, and so does the token here. (2) Runbook section 9 says the
 * self-test reads "the board, the code list, the data directory, and the clock"; Rust also has the reservation
 * book (part of `storage`) and the sync backlog (`sync`). (3) design.md names no return type for the two
 * functions; both return bool here (false on a NULL argument or, for the token, a buffer that is too small).
 */
#ifndef LK_SELFTEST_H
#define LK_SELFTEST_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "apps/lockers/lk/types/types.h"
#include "lib/base/core/buf.h"
#include "lib/fmt/fmt/fmt.h"

#define LK_SELFTEST_DEFAULT_MIN_FREE_MB UINT64_C(200) /* Rust DEFAULT_MIN_FREE_MB */
#define LK_SELFTEST_ONE_DAY_MS UINT64_C(86400000)     /* Rust ONE_DAY_MS */
#define LK_SELFTEST_MAX_ISSUES 7u
#define LK_SELFTEST_TOKEN_MAX 55u /* "relay=fail,codes=fail,storage=fail,clock=fail,sync=fail" */

enum { LK_RELAY_SIGHT_UNREACHABLE = 0, LK_RELAY_SIGHT_ALL_OFF = 1, LK_RELAY_SIGHT_SOME_ON = 2 };
enum { LK_CODES_SIGHT_UNAVAILABLE = 0, LK_CODES_SIGHT_LISTED = 1 };
enum { LK_SPACE_SIGHT_UNKNOWN = 0, LK_SPACE_SIGHT_MEGABYTES = 1 };
enum { LK_BOOK_SIGHT_UNREADABLE = 0, LK_BOOK_SIGHT_LOADED = 1 };
enum { LK_AUDIT_SIGHT_UNREADABLE = 0, LK_AUDIT_SIGHT_EMPTY = 1, LK_AUDIT_SIGHT_NEWEST = 2 };

/* Issue codes; 0 is "no issue" (an unused slot). The values are stable. */
enum {
    LK_ST_NONE = 0,
    LK_ST_RELAY_UNREACHABLE = 1,
    LK_ST_RELAY_ON = 2,
    LK_ST_CODES_UNAVAILABLE = 3,
    LK_ST_NO_ACTIVE_CODES = 4,
    LK_ST_NOT_WRITABLE = 5,
    LK_ST_SPACE_UNKNOWN = 6,
    LK_ST_DISK_FULL = 7,
    LK_ST_BOOK_UNREADABLE = 8,
    LK_ST_UNCERTAIN = 9,
    LK_ST_CLOCK_WRONG = 10,
    LK_ST_SYNC_WAITING = 11,
    LK_ST_SYNC_WAITING_SINCE = 12
};

typedef struct {
    uint64_t now_ms;
    uint64_t built_at_ms;
    uint8_t relay;
    uint8_t codes;
    uint32_t codes_active;
    bool writable;
    uint8_t space;
    uint64_t space_mb;
    uint64_t min_free_mb;
    uint8_t book;
    uint32_t book_uncertain;
    uint8_t audit;
    uint64_t audit_newest_ms;
    bool sync_configured;
    bool sync_has_last;
    uint64_t sync_last_ms;
    uint32_t sync_pending;
} lk_readings_t;

/* One failing check: `code` is an LK_ST_* value. `count` is the uncertain count (LK_ST_UNCERTAIN) or the pending
 * count (LK_ST_SYNC_WAITING, LK_ST_SYNC_WAITING_SINCE); `hour` and `minute` are set only for
 * LK_ST_SYNC_WAITING_SINCE. Every number an issue does not carry is 0. */
typedef struct {
    uint8_t code;
    uint32_t count;
    uint8_t hour;
    uint8_t minute;
} lk_selftest_issue_t;

/* The result. issues[0..n_issues) are the failing checks in the fixed order of R1..R5; every other slot is
 * all zero. relay_ok, codes_ok, storage_ok, clock_ok are the per-check flags. sync_configured echoes the reading;
 * sync_ok is the sync flag when sync_configured and false otherwise. passed == (n_issues == 0). */
typedef struct {
    lk_selftest_issue_t issues[LK_SELFTEST_MAX_ISSUES];
    uint8_t n_issues;
    bool passed;
    bool relay_ok;
    bool codes_ok;
    bool storage_ok;
    bool clock_ok;
    bool sync_configured;
    bool sync_ok;
} lk_selftest_t;

/* Evaluate R1..R7. Returns true iff both arguments are non-NULL; then `*out` is completely overwritten (every
 * byte of the struct is defined by the rules above, the unused issue slots are zero). Returns false and writes
 * nothing when `in` or `out` is NULL. Every reading value is accepted; there is no other failure. */
bool lk_selftest_eval(const lk_readings_t *in, lk_selftest_t *out);

/* Append the token (see THE TOKEN) to `b` in ONE all-or-nothing append (core_buf_t rules: it fits iff
 * len + token_len + 1 <= cap; otherwise the content is unchanged and the sticky overflow flag is set). Returns
 * true iff the whole token was appended. Returns false when `st` or `b` is NULL (nothing happens), when the
 * token does not fit, and when `b` already has its overflow flag set (the call is ignored). */
bool lk_selftest_token(const lk_selftest_t *st, core_buf_t *b);

#endif
