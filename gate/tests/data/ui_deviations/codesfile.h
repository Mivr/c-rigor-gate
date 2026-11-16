/* apps/lockers/lk/codesfile/codesfile.h: the /v1/codes JSON streamed into a codeset, the codes.cache file
 * (codes-cache-v2) encoded and decoded, and the offline-start rule. Pure.
 * Level L3. Included as "apps/lockers/lk/codesfile/codesfile.h". Depends on lib/fmt/jpull (the streaming JSON
 * tokenizer), lib/fmt/lines, lk/codeset (+ lk/code, lk/types), lib/fmt/fmt and lib/base/core, and on nothing else.
 * No allocation, no mutable static data, no clock, no IO, no DOM. The caller gives every byte of storage: the jpull
 * scratch, the parser state, the codeset blob. Used by lkadp/codeshttp (parse a fetched body, write and read the
 * cache) and lkrx/boot (the offline-start rule).
 *
 * Citations. RUST = the Rust kiosk, the behaviour oracle (D8: where this header and the docs disagree, the Rust
 * code wins and the disagreement is listed under "Disagreements"): parse_codes, role_from, load_cache,
 * parse_fetched_at, store_cache, CACHE_MAGIC, MAX_RESPONSE_BYTES, MAX_CACHE_BYTES in adapters/codes-http
 * (codes-http lib.rs); accept_offline, miss_of in lockers-codes (lib.rs); cache_max_age_millis in lockers-config.
 * WORKER = services/codes-worker (the body: {"revision":N,"codes":[{code,role,active}...]}). DESIGN =
 * docs/design.md (row lk/codesfile, "Allowed codes" capacity row, D6). SPEC = docs/lockers/lockers-spec.md (Codes).
 *
 * ================================ PART 1: PARSE THE /v1/codes BODY ===========================================
 * Rules (the body is JSON text, read as serde_json::Value would read it; RUST parse_codes):
 * P1  GRAMMAR. The body is exactly one JSON document in RFC 8259 grammar as lib/fmt/jpull accepts it (strict
 *     UTF-8, escapes decoded, a lone surrogate escape refused, whitespace only space/TAB/LF/CR, nothing after
 *     the root but whitespace, a BOM refused, an empty or whitespace-only body refused). Nesting depth (containers
 *     open at once, the root object counts 1; `1` has depth 0) is at most LK_CODES_DEPTH_MAX = 127: depth 127 is
 *     accepted, 128 is BAD. This is serde_json's recursion limit: Deserializer::remaining_depth starts at 128, every
 *     array or object start decrements it and the start that brings it to 0 fails with "recursion limit exceeded".
 *     serde_json::Value has no unknown-field handling, so the limit applies to EVERY value in the body, ignored
 *     members and earlier duplicates included. (The orchestrator's brief said 128/129; the serde_json source says
 *     127/128: change LK_CODES_DEPTH_MAX and the tests follow.) lib/fmt/jpull today stops at JPULL_MAX_DEPTH 64
 *     and cannot be asked for more (jpull_init refuses it): the implementation needs jpull's depth cap raised to
 *     at least LK_CODES_DEPTH_MAX (its object bit set is one 64-bit word; a second word fits in jpull_t) or its own
 *     depth tracking. The depth state is part of lk_codes_parser_t; the SCRATCH needs nothing for depth (P7).
 * P1b NUMBERS. A number is read as serde_json reads it into an f64: one whose magnitude is too large for a finite
 *     f64 makes the whole body BAD wherever it stands, in an ignored member, in a nested array, in an earlier
 *     duplicate member, in an item's other members ("1e400", "-1e400", "1E+400", "123e400", "0.5e401", a 400-digit
 *     integer, "1e99999999999"). Accepted: magnitude up to 1.7e308, zero in any form ("0e999", "0.0e400",
 *     "-0e99999999999"), and any tiny magnitude ("1e-400", "1e-99999999999" read as 0). A magnitude of 1.8e308 or
 *     more is out of range. Magnitudes within 1e-9 (relative) of the rounding limit f64::MAX are not specified.
 *     A number's text longer than the scratch is SCRATCH first (P7). Out-of-range is a JSON-level error (P6.2).
 * P2  ROOT. The root value must be an object, else BAD. Members other than "codes" are ignored whatever their
 *     value (WORKER sends "revision"; the Rust test body has "extra":true).
 * P3  "codes". Member names are compared after escape decoding ("codes" is "codes"). If "codes" occurs more
 *     than once in the root object the LAST occurrence is the one that counts (serde_json::Value keeps the last
 *     duplicate); earlier occurrences are ignored completely: whatever they hold (wrong type, bad items, too many
 *     items) cannot cause any refusal, only their JSON grammar counts (P1). No "codes" member at all: BAD. The
 *     counting one must be an array, else BAD (RUST: "codes":"nope" is refused). An empty array is fine: an empty
 *     sealed set, 0 entries.
 * P4  ITEMS. Every element of the counting array must be an object, else BAD (RUST: [1] is refused). In an item,
 *     again the LAST member of a name counts, and members other than "code", "role", "active" are ignored:
 *       "code"   must be present and a string, whose decoded bytes are 6..64 ASCII digits (SPEC Codes; RUST
 *                Code::parse; leading zeros are fine, "000121" is a code, "bad code" and "12345" are BAD);
 *       "role"   must be present and the string "visitor" or "staff" exactly (RUST role_from: case-sensitive,
 *                "admin" is BAD, "Visitor" is BAD; escapes are decoded first, so "visitor" is "visitor");
 *       "active" must be present and the JSON literal true or false (RUST as_bool: 1, "true", null are BAD).
 *     The entries are added to the codeset in array order with lk_codeset_add(code, role, active). Inactive
 *     entries are kept (the codeset counts them in its len and not in its active counts). DUPLICATE CODES ARE
 *     LEGAL (RUST does not check): the codeset's own rule decides (the first entry for a code answers).
 * P5  CAPS (DESIGN "Allowed codes"). (a) A body longer than LK_CODES_BODY_MAX (65536) bytes is TOO_LARGE; exactly
 *     65536 bytes is fine (RUST MAX_RESPONSE_BYTES, `> 65536` refuses). (b) A counting array with more than
 *     min(lk_codeset_cap(set), LK_CODES_CAP) elements is TOO_LARGE; exactly that many is fine. LK_CODES_CAP is
 *     10240 (DESIGN D6); a JSON body of 65536 bytes cannot hold that many elements, so in practice the set's own
 *     capacity is what limits (Disagreement D5).
 * P6  RESULT PRECEDENCE (the result depends on the document only, never on how it is chunked):
 *       1. ARG (see the functions) wins, and changes nothing.
 *       2. then SCRATCH or BAD from the JSON level: the first jpull error or out-of-range number (P1b) in
 *          document order decides: a key, string or number longer than the scratch (P7) is SCRATCH; any other
 *          grammar error (P1, P1b) is BAD;
 *       3. then BAD from the shape rules P2-P4 (any one violated);
 *       4. then TOO_LARGE (P5), whichever cap is exceeded;
 *       5. else OK.
 *     So a body of 70000 valid bytes is TOO_LARGE, a body of 70000 bytes with a syntax error is BAD, and a
 *     shape error anywhere makes BAD even when a cap is also exceeded.
 * P7  SCRATCH. The scratch is used only for the decoded text of ONE key or string at a time and for the text of ONE
 *     number. A key or string whose decoded length, or a number whose text length, is greater than scratch_cap is
 *     SCRATCH; a length equal to scratch_cap is fine. LK_CODES_SCRATCH_BYTES (65536) always suffices for a body
 *     within P5(a). scratch may be NULL only with scratch_cap 0 (then any key, string or number is SCRATCH).
 * P8  RESULT STATE. OK: the set is SEALED and holds exactly the entries of the counting array (lk_codeset_len ==
 *     the element count) and *meta is filled. Any result other than OK, MORE or ARG: the set is BUILDING and empty
 *     (as after lk_codeset_reset; never sealed, no partial list) and *meta, if given, is all zero. Nothing else of
 *     the caller's memory except the scratch, the parser state and the set is written. The body and chunk bytes
 *     are never modified or kept after the call returns.
 *
 * Meta (RUST tally): entries = lk_codeset_len of the set, active = number of entries with active true, staff =
 * number of ACTIVE entries whose role is staff (so staff <= active <= entries). Same numbers as the codeset's
 * counts. Nothing else of the body is of interest to the kiosk ("revision" is ignored by RUST).
 */
#ifndef LK_CODESFILE_H
#define LK_CODESFILE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "apps/lockers/lk/codeset/codeset.h"
#include "lib/base/core/buf.h"
#include "lib/base/core/str.h"
#include "lib/fmt/jpull/jpull.h"

#define LK_CODES_BODY_MAX 65536u        /* RUST MAX_RESPONSE_BYTES; DESIGN "Codes body" */
#define LK_CODES_CAP 10240u             /* DESIGN D6 / "Allowed codes" */
#define LK_CODES_SCRATCH_BYTES 65536u   /* a scratch that always suffices (P7) */
#define LK_CODES_DEPTH_MAX 127u         /* serde_json's recursion limit, P1 */

typedef enum {
    LK_CODES_OK = 0,    /* the body is accepted; the set is sealed (P8) */
    LK_CODES_MORE,      /* lk_codes_feed only: not the last chunk, send the next (nothing is decided yet) */
    LK_CODES_BAD,       /* the body is not a valid codes document (P1-P4, P6) */
    LK_CODES_TOO_LARGE, /* the body or the list exceeds a cap (P5) */
    LK_CODES_SCRATCH,   /* the scratch is too small for a key, string or number (P7) */
    LK_CODES_ARG        /* bad arguments or misuse; nothing is changed */
} lk_codes_rc_t;

typedef struct {
    uint32_t entries; /* all entries, inactive and duplicates included */
    uint32_t active;
    uint32_t staff;
} lk_codes_meta_t;

/* Whole body. Resets `set` (lk_codeset_reset: any initialised set, in any state, is fine; its storage and cap are
 * kept and give the P5(b) cap), then applies P1-P8 to body[0..len) and returns the result. `meta` may be NULL
 * (then nothing is reported). ARG (nothing changed, not even the set): set NULL, body.ptr NULL with body.len > 0
 * (a NULL ptr with len 0 is the empty body, which is BAD), scratch NULL with scratch_cap > 0. */
lk_codes_rc_t lk_codes_parse(core_str_t body, void *scratch, size_t scratch_cap, lk_codeset_t *set,
                             lk_codes_meta_t *meta);

/* ---- The same parse, fed in pieces ---------------------------------------------------------------------------
 * lk_codes_begin(p, scratch, scratch_cap, set) starts a parse into `set` (resets it, as lk_codes_parse does) and
 * returns true; false, changing nothing, for the ARG cases of lk_codes_parse (p NULL, set NULL, scratch NULL with
 * scratch_cap > 0). The scratch, the set and every chunk handed over must stay valid and untouched by the caller
 * until the final result. Begin may be called again on the same state to start a new parse.
 * lk_codes_feed(p, chunk, last, meta) hands over the next piece of the body, of any size 0.., in order. Chunk
 * boundaries are arbitrary: THE FINAL RESULT, THE SET AND THE META ARE THE SAME FOR EVERY WAY OF CUTTING THE BODY
 * (1 byte at a time, 7 bytes, the whole body at once, empty pieces anywhere), and equal what lk_codes_parse gives
 * for the concatenation. A call with last == false returns MORE (ARG for misuse), and the set is not to be used
 * until the final result. The call with last == true ends the body and returns the final result (OK, BAD,
 * TOO_LARGE, SCRATCH) with P6/P8 applied, and fills `meta` (may be NULL). After a final result every further feed
 * is ARG (changing nothing) until a new begin. ARG: p NULL, a p that has no successful begin (a zero-filled state
 * counts as such) or already got its
 * final result, chunk.ptr NULL with chunk.len > 0. */
typedef struct {
    uint64_t priv_[44]; /* private; 352 bytes at most; declare it static or in the caller's state, never copy */
} lk_codes_parser_t;

bool lk_codes_begin(lk_codes_parser_t *p, void *scratch, size_t scratch_cap, lk_codeset_t *set);
lk_codes_rc_t lk_codes_feed(lk_codes_parser_t *p, core_str_t chunk, bool last, lk_codes_meta_t *meta);

/* ================================ PART 2: THE CACHE FILE (codes-cache-v2) ====================================
 * The file codes.cache is these bytes and nothing else (RUST store_cache `format!("{CACHE_MAGIC}\n{}\n{etag}\n{body}")`):
 *     codes-cache-v2 LF <fetched_ms in decimal> LF <tag> LF <body>
 * The whole file is UTF-8 text (C6).
 * C1  magic = the 14 bytes "codes-cache-v2" (LK_CACHE_MAGIC). Older files ("codes-cache-v1", "-v0") are refused.
 * C2  fetched_ms = the fetch time, epoch milliseconds, ASCII decimal digits only, no sign, no spaces, no
 *     separators, at least one digit, no leading zeros when written (0 is "0"). A reader accepts leading zeros
 *     ("007" is 7, RUST u64::parse) and any value up to UINT64_MAX (18446744073709551615); one more is refused
 *     (RUST `str::parse::<u64>` fails). A writer (lk_cache_encode) takes an int64 and writes 0..INT64_MAX only.
 * C3  tag = the cache tag exactly as the server sent it, NON-EMPTY, stored verbatim, no byte is added or removed. In
 *     practice it is the ETag with its double quotes: "9" is written as the 3 bytes "9" with the quotes
 *     (RUST test: `codes-cache-v2\n1700000000000\n"3"\n`); this module neither adds nor removes quotes. It contains
 *     no LF (a LF would end it).
 * C4  body = everything after the third LF to the end of the file, byte for byte; it may be empty (the decoder does
 *     not look into it: the caller runs lk_codes_parse on it, as RUST load_cache runs parse_codes), may contain LF,
 *     CR and NUL, and no LF or other byte is appended. No trailing newline is added.
 * C5  the whole file is at most LK_CACHE_MAX_BYTES = 65824 bytes (RUST MAX_CACHE_BYTES; = the 65536-byte body cap
 *     plus 288 bytes for the header lines); 65824 is accepted, 65825 is refused.
 *
 * lk_cache_encode(b, fetched_ms, tag, body): appends the file C1-C4 to the builder `b` after whatever it holds
 * (all-or-nothing: on any result other than OK the content of `b` is unchanged and nothing is appended). Result,
 * checked in this order:
 *   ARG        b NULL, fetched_ms < 0, tag empty, tag containing a LF byte, tag.ptr NULL with tag.len > 0, body.ptr
 *              NULL with body.len > 0. (RUST writes whatever it is given; these are files RUST's own reader would
 *              refuse or misread, the writer never makes them: Disagreement D4.)
 *   TOO_LARGE  the file would be longer than LK_CACHE_MAX_BYTES (C5), which a reader would refuse (D4).
 *   FULL       the file does not fit the builder (core_buf rules: len + file bytes + 1 <= cap), or b already has its
 *              overflow flag set. An empty body (ptr NULL, len 0) is fine.
 *   OK         b holds its old content followed by the file; core_buf keeps its NUL after it.
 * Byte-exact examples (fake data; every byte shown): fetched_ms 1700000000000, tag "\"3\"" (3 bytes), body "{}" gives
 * "codes-cache-v2\n1700000000000\n\"3\"\n{}" (14+1+13+1+3+1+2 = 35 bytes); fetched_ms 0, tag "x", body "" gives
 * "codes-cache-v2\n0\nx\n" (19 bytes).
 *
 * lk_cache_decode(in, out): reads a whole file image (RUST load_cache after the file-level checks). On OK writes
 * *out with fetched_ms, tag and body, tag and body being VIEWS into `in` (no copy; valid while `in` is). The
 * cut is: magic = bytes up to the first LF, fetched = up to the second LF, tag = up to the third LF, body = the rest
 * (after the third LF, possibly empty). Refusals, checked in this order (the first that applies decides), and then
 * *out is not written:
 *   ARG         out NULL, in.ptr NULL with in.len > 0 ({NULL,0} is not a file: BAD_MAGIC).
 *   TOO_LARGE   in.len > LK_CACHE_MAX_BYTES (C5), whatever the content.
 *   BAD_UTF8    `in` is not valid UTF-8 anywhere (C6): in the magic line, the time line, the tag line or the body.
 *   BAD_MAGIC   no LF in `in`, or the bytes before the first LF are not exactly the 14 bytes of C1 (RUST: "v0",
 *               "v1", "nope", the empty file; a magic with a trailing space or CR is not the magic).
 *   BAD_TIME    no second LF; or the field between the first and second LF is empty, holds any byte other than
 *               '0'..'9' ("nope", "+1", " 1", "1 ", "-1", "1.5"), or is greater than UINT64_MAX (C2).
 *   BAD_TAG     no third LF (so "codes-cache-v2\n1\n\"9\"" with no LF after the tag is refused), or an empty tag
 *               (RUST: `etag.is_empty()`; the "v1\n\n" shape).
 *   OK          the fields as above. An empty body is OK.
 * C6  UTF-8. RUST reads the file with read_to_string, so a file that is not valid UTF-8 anywhere is unreadable, before
 *     any line is looked at (strict UTF-8: no overlong forms, no surrogates, nothing above U+10FFFF, no truncated
 *     sequence; NUL bytes are valid). The check comes right after the size check and before BAD_MAGIC.
 * What this module does NOT decide (the adapter does, RUST load_cache): file mode 0600, file type, a missing
 * file, file read errors.
 */
#define LK_CACHE_MAGIC "codes-cache-v2"
#define LK_CACHE_MAGIC_LEN 14u
#define LK_CACHE_MAX_BYTES 65824u /* RUST MAX_CACHE_BYTES */

typedef enum {
    LK_CACHE_OK = 0,
    LK_CACHE_ARG,
    LK_CACHE_TOO_LARGE,
    LK_CACHE_FULL, /* encode only */
    LK_CACHE_BAD_MAGIC, /* decode only */
    LK_CACHE_BAD_TIME,  /* decode only */
    LK_CACHE_BAD_UTF8,  /* decode only */
    LK_CACHE_BAD_TAG    /* decode only */
} lk_cache_rc_t;

typedef struct {
    uint64_t fetched_ms; /* 0..UINT64_MAX */
    core_str_t tag;     /* non-empty, no LF; a view into the decoded input */
    core_str_t body;    /* may be empty; a view into the decoded input */
} lk_cache_view_t;

lk_cache_rc_t lk_cache_encode(core_buf_t *b, int64_t fetched_ms, core_str_t tag, core_str_t body);
lk_cache_rc_t lk_cache_decode(core_str_t in, lk_cache_view_t *out);

/* ================================ PART 3: THE OFFLINE-START RULE =============================================
 * When the startup fetch fails, the kiosk may still start from the saved list if it is fresh enough (RUST
 * accept_offline: lockers_code::offline_start(now, fetched_at, cache_max_age_millis(codes_cache_max_age))).
 * lk_offline_start(now_ms, fetched_ms, max_age_secs, age_ms), a pure function:
 * O1  max = max_age_secs * 1000, saturating at UINT64_MAX (RUST cache_max_age_millis: saturating_mul(1_000)); a
 *     value so large that the product saturates is simply "older than any age counts" (always ALLOWED).
 *     max_age_secs 0 is legal: max = 0 ms.
 * O2  Both times are unsigned (RUST Millis(u64)); there is no negative time.
 * O3  fetched_ms > now_ms (the list claims to be from the future): UNUSABLE (RUST test: fetched = now + 5 gives
 *     CodesMiss::Unreadable). *age_ms not written. (A future time is not tolerated, however small the excess; a
 *     fetch time read from a cache file as 9223372036854775808 or UINT64_MAX is just a far-future time: UNUSABLE.)
 * O4  otherwise age = now_ms - fetched_ms (>= 0; fetched_ms == now_ms is age 0):
 *       age <= max  -> ALLOWED     (an age exactly at the limit is allowed: RUST test, age 43_200_000 with the
 *                                   default 43 200 s)
 *       age >  max  -> TOO_OLD     (one millisecond over: 43_200_001 is TOO_OLD, RUST CodesMiss::TooOld)
 *     and *age_ms = age for both ALLOWED and TOO_OLD. age_ms may be NULL (nothing written).
 * The default limit is LK_CODES_CACHE_MAX_AGE_SECS = 43200 (12 h; RUST default_cache_max_age; runbook
 * `codes_cache_max_age_secs`). Missing or unreadable files are not this function's cases (they never reach it).
 */
#define LK_CODES_CACHE_MAX_AGE_SECS 43200u

typedef enum {
    LK_OFFLINE_ALLOWED = 0, /* start from the saved list */
    LK_OFFLINE_TOO_OLD,     /* "saved list too old" */
    LK_OFFLINE_UNUSABLE     /* from the future: "saved list unreadable" */
} lk_offline_t;

lk_offline_t lk_offline_start(uint64_t now_ms, uint64_t fetched_ms, uint64_t max_age_secs, uint64_t *age_ms);

/* ================================ Disagreements with RUST / the docs (D8: RUST wins unless listed here) =======
 * D1-D4 of the first round are closed: depth (P1), number range (P1b), the cache time range (C2) and UTF-8 (C6)
 *     now follow RUST. Two small remainders: encode refuses an empty tag, a tag with a LF and a file over 65824
 *     bytes (RUST writes whatever it is given; these are files its own reader would refuse), and takes an int64
 *     time (negative is ARG). The file mode, type and read errors stay with the adapter.
 * D5  RUST has no cap on the number of entries (only the 65536-byte body cap, applied in fetch, not in
 *     parse_codes or the cache loader: a cached body up to 65805 bytes loads in RUST); here lk_codes_parse applies
 *     P5 to every body, fetched or cached. DESIGN's LK_CODES_CAP 10240 is unreachable with a 65536-byte JSON body
 *     (a minimal entry is about 46 bytes), so tests use a small set capacity for the entry-cap edge.
 * D6  The signature of lk_codes_parse has the extra scratch arguments (DESIGN lists three), and a streaming pair
 *     begin/feed is added, because jpull needs caller scratch and the chunk independence must be checkable.
 * D7  The Rust source of lockers_code::offline_start was not available: O1-O4 are taken from the RUST tests of
 *     accept_offline (fresh age 1000; age 43_200_000 allowed; 43_200_001 TOO_OLD; future +5 unusable). That an age
 *     of exactly 0 is ALLOWED is inferred, not witnessed.
 */

#endif
