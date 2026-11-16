/* apps/lockers/lkrx/vstate/vstate.h: the lockers kiosk ViewState as plain C types, and its canonical JSON.
 *
 * Plain data plus two pure functions. No IO, clock, allocation, recursion or mutable static data. Level L3.
 * Included as "apps/lockers/lkrx/vstate/vstate.h". Deps: jw, lk/types, core. Used by lkrx/view (builds a
 * lk_view_t), lkui/screens and lkui/notices (read one), and P2 replay (compares canonical lines).
 *
 * Citations: RUST = viewmodel/lockers-state (Screen, NoticeKind, BannerId, DismissIntent, Phrase,
 * RejectReason, FaultKind, DoorState, Notice, ViewState), UI = docs/lockers/ui-rules.md, P001 R14, R19, R20,
 * DESIGN = docs/design.md (lkrx/vstate row and its type sketch), types = apps/lockers/lk/types/types.h.
 *
 * ---- Rules ----------------------------------------------------------------------------------------------
 * V1  A lk_view_t is a screen, at most one notice over it, a banner set, a screen countdown and the language
 *     (RUST ViewState). There is no "message" screen: LKS_* lists only the ui-rules full-screen states (UI
 *     "Allowed full-screen states"; P001 R14), so a full-screen message cannot be represented.
 * V2  A notice always carries a dismiss intent (UI "Every notice carries a dismiss intent"; RUST Notice.dismiss).
 *     The intent enum LK_DISMISS_* has no "none" value: 0 is the overlay dismiss.
 * V3  The banner set is the array banners[LK_BANNER_KINDS] with n_banners used entries; each banner kind may
 *     occur at most once, so overflow is unrepresentable (the array is as long as the closed kind set).
 * V4  Zero is a valid blank view: a view of all zero bytes is the splash, language bg, no notice, no banners,
 *     no countdown (RUST ViewState::at(Screen::Starting)).
 * V5  Every string a person reads is a phrase code plus plain arguments (P001 R19, R20); no sentence is stored.
 * V6  A countdown is a number of milliseconds; 0 means "no countdown" (RUST Option::None). The largest valid
 *     countdown is LK_VS_COUNTDOWN_MAX (the longest timer, the 5 min report).
 * V7  Fields that do not belong to the current case are IGNORED: neither validated nor written. That is the
 *     screen fields of another screen, `notice` while has_notice is false, array entries at or after n_sizes /
 *     n_banners, and the arguments a phrase does not use (listed under "Arguments"). Garbage there changes
 *     neither the status nor the encoding.
 *
 * ---- Rust / doc disagreements (D8: Rust wins unless listed here) ---------------------------------------
 * D1  RUST Screen::Idle { entered: String } carries the typed digits. C carries only pad_len (0..64): the
 *     digits are a plaintext code and must not reach traces ("plaintext; never durable", DESIGN event table).
 * D2  RUST has Screen::StartupFault { kind, title, text, detail }. C has the two fault screens of the DESIGN
 *     sketch (LKS_FAULT_STORAGE, LKS_FAULT_RELAY), each with the fault kind; title, text and detail are phrase
 *     catalog data of the UI. RUST FaultKind::LockUnavailable { reason } drops `reason` (a sentence).
 * D3  RUST Phrase::Raw is dropped (P001 R20). RUST Phrase::Rejection(RejectReason) is three phrase codes.
 *     RUST Phrase::SelfTest { issues } keeps only which checks failed (a bit set), not their counts.
 * D4  RUST ShiftReport is not modelled; LKS_REPORT carries the four numbers of lk_vreport_t. The shift
 *     inspection progress is LKS_SHIFT's done/total.
 * D5  RUST Notice.countdown is Option<Duration>; C uses ms with 0 = none (V6). RUST banners are a Vec in
 *     insertion order with their own countdown and detail; C banners are a set (V3), written in ascending
 *     banner kind order (canonical), with no countdown (UI: banners have none) and no detail (a phrase).
 * D6  RUST Screen::ChooseSize { sizes: Vec<SizeAvailability> } becomes up to LK_SIZES_CAP {size, free} pairs.
 * D7  Not modelled: SessionPorts, KioskMachine and the timeout constants other than the ones in lk/types
 *     (SPLASH_REAL_TICKS and UNKNOWN_LIMIT belong to boot and pad; lk/types has LK_LOCKOUT_ATTEMPTS).
 *     codes_offline_line is a sentence: it is the phrase LK_PH_CODES_OFFLINE with hour and minute.
 */
#ifndef LKRX_VSTATE_H
#define LKRX_VSTATE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "apps/lockers/lk/types/types.h"
#include "lib/base/core/buf.h"

/* ---- Enums. Each has a count constant; valid values are 0 .. count-1. The values are stable. ---------- */

/* Screens (full-screen states only). The JSON text is in the comment. */
enum {
    LKS_SPLASH = 0,        /* "splash": boot splash */
    LKS_WELCOME = 1,       /* "welcome": welcome / code pad */
    LKS_CHOOSE = 2,        /* "choose": choose a size */
    LKS_OPENED = 3,        /* "opened": the opened locker number */
    LKS_SHIFT = 4,         /* "shift": staff end-of-shift inspection in progress */
    LKS_REPORT = 5,        /* "report": the end-of-shift report */
    LKS_LOCKOUT = 6,       /* "lockout": please wait */
    LKS_FAULT_STORAGE = 7, /* "fault_storage": fatal startup fault, the book could not be loaded */
    LKS_FAULT_RELAY = 8,   /* "fault_relay": fatal startup fault, the board did not answer at boot */
    LKS__COUNT = 9
};

/* Notice kinds (RUST NoticeKind order). */
enum {
    LK_NK_DIALOG = 0,   /* "dialog" */
    LK_NK_BANNER = 1,   /* "banner" */
    LK_NK_SNACKBAR = 2, /* "snackbar" */
    LK_NK__COUNT = 3
};

/* The banner kinds (LK_BANNER_*, LK_BANNER_KINDS) are defined in lk/types/types.h. */
#define LK_BANNERS_CAP LK_BANNER_KINDS /* the banner array length: one slot per kind */
_Static_assert(LK_BANNER_KINDS <= LK_BANNERS_CAP, "banner overflow is unrepresentable");

/* Dismiss intents (RUST DismissIntent: Overlay, Banner(id)). There is no "none". The banner intent of kind k is
 * LK_DISMISS_BANNER_NOT_SAVED + k. */
enum {
    LK_DISMISS_OVERLAY = 0,             /* "overlay": clear the dialog or snackbar */
    LK_DISMISS_BANNER_NOT_SAVED = 1,    /* "banner_not_saved" */
    LK_DISMISS_BANNER_AUDIT = 2,        /* "banner_audit" */
    LK_DISMISS_BANNER_SYNC = 3,         /* "banner_sync" */
    LK_DISMISS_BANNER_CODES_OFFLINE = 4, /* "banner_codes_offline" */
    LK_DISMISS_BANNER_CODES_STALE = 5,  /* "banner_codes_stale" */
    LK_DISMISS_BANNER_SELF_TEST = 6,    /* "banner_self_test" */
    LK_DISMISS__COUNT = 7
};

/* Phrases: the closed catalog ids (no raw text). `Arguments` says which lk_vargs_t fields a phrase uses. */
enum {
    LK_PH_REJECT_INVALID = 0,          /* "reject_invalid" */
    LK_PH_REJECT_UNKNOWN = 1,          /* "reject_unknown" */
    LK_PH_REJECT_CODES_UNAVAILABLE = 2, /* "reject_codes_unavailable" */
    LK_PH_NO_LOCKER = 3,               /* "no_locker" */
    LK_PH_FAULT = 4,                   /* "fault": uses fault, door, locker */
    LK_PH_SAVED = 5,                   /* "saved" */
    LK_PH_NOT_SAVED = 6,               /* "not_saved" */
    LK_PH_AUDIT = 7,                   /* "audit" */
    LK_PH_SYNC_REJECTED = 8,           /* "sync_rejected": uses status */
    LK_PH_SYNC_LATE = 9,               /* "sync_late": uses hour, minute */
    LK_PH_CODES_OFFLINE = 10,          /* "codes_offline": uses hour, minute */
    LK_PH_CODES_STALE = 11,            /* "codes_stale" */
    LK_PH_SELF_TEST = 12,              /* "self_test": uses issues */
    LK_PH__COUNT = 13
};

/* What the fault dialog may claim about a door (RUST DoorState order). */
enum {
    LK_DOOR_NOTHING_OPENED = 0, /* "nothing_opened" */
    LK_DOOR_MAYBE_OPENED = 1,   /* "maybe_opened" */
    LK_DOOR_OPENED = 2,         /* "opened" */
    LK_DOOR__COUNT = 3
};

/* ---- Bounds ---------------------------------------------------------------------------------------------- */

#define LK_VS_PAD_MAX LK_CODE_MAX_DIGITS         /* pad_len 0..64 */
#define LK_VS_COUNTDOWN_MAX LK_REPORT_MS         /* 300000: valid countdown_ms is 0..300000 */
#define LK_VS_ISSUE_BITS 12u                     /* bit k of `issues` = self-test issue code k+1 (LK_ST_*) */
#define LK_VS_ISSUES_MAX UINT16_C(0x0FFF)        /* valid issues: 0..0x0FFF */
#define LK_VS_HOUR_MAX 23u
#define LK_VS_MINUTE_MAX 59u
/* Any VALID view encodes to fewer than this many bytes (so a buffer of this capacity never fills). */
#define LK_VS_CANON_MAX 2048u

/* ---- Types ---------------------------------------------------------------------------------------------- */

/* Phrase arguments. Used by phrase (the rest are ignored, V7):
 *   LK_PH_FAULT          fault (lk_fault_valid: LK_FAULT_RELAY_BUSY..LK_FAULT_LOCKER_MISSING), door
 *                        (< LK_DOOR__COUNT), locker (0 = no locker, else lk_locker_valid)
 *   LK_PH_SYNC_REJECTED  status (any value 0..65535, the HTTP status)
 *   LK_PH_SYNC_LATE, LK_PH_CODES_OFFLINE   hour (<= 23), minute (<= 59)
 *   LK_PH_SELF_TEST      issues (<= LK_VS_ISSUES_MAX)
 * No other phrase uses an argument. */
typedef struct {
    uint8_t fault;
    uint8_t door;
    uint16_t locker;
    uint16_t status;
    uint16_t issues;
    uint8_t hour;
    uint8_t minute;
} lk_vargs_t;

/* The one notice over the screen (dialog, snackbar, or a banner-kind notice). `dismiss` is always meaningful:
 * 0 .. LK_DISMISS__COUNT-1. Any combination of kind and dismiss in range is accepted. */
typedef struct {
    uint8_t kind;  /* LK_NK_* */
    uint8_t dismiss; /* LK_DISMISS_* */
    uint8_t phrase;  /* LK_PH_* */
    bool warning;    /* banner tone; ignored by dialogs and snackbars but still encoded */
    uint32_t countdown_ms; /* 0 = none, else <= LK_VS_COUNTDOWN_MAX */
    lk_vargs_t args;
} lk_notice_t;

/* One banner. Its dismiss intent is implied by id (LK_DISMISS_BANNER_NOT_SAVED + id), so it cannot disagree. */
typedef struct {
    uint8_t id;     /* LK_BANNER_* */
    uint8_t phrase; /* LK_PH_* */
    bool warning;
    lk_vargs_t args;
} lk_banner_t;

typedef struct {
    uint8_t size; /* lk_size_valid: < LK_SIZES_CAP */
    uint16_t free; /* lockers free in that size, any value */
} lk_vsize_t;

typedef struct {
    uint16_t released;  /* any value */
    uint16_t ok;
    uint16_t faults;
    bool write_failed;
} lk_vreport_t;

typedef struct {
    uint8_t screen;   /* LKS_* */
    uint8_t language; /* LK_LANG_BG or LK_LANG_EN (lk_lang_valid) */
    uint32_t screen_countdown_ms; /* 0 = none, else <= LK_VS_COUNTDOWN_MAX; any screen */
    /* Screen fields; only the current screen's are used (V7). */
    uint8_t pad_len;       /* LKS_WELCOME: typed digits, <= LK_VS_PAD_MAX */
    uint8_t n_sizes;       /* LKS_CHOOSE: used entries of sizes, <= LK_SIZES_CAP */
    lk_vsize_t sizes[LK_SIZES_CAP];
    uint16_t locker;       /* LKS_OPENED: lk_locker_valid */
    bool first_time;       /* LKS_OPENED */
    uint16_t shift_done;   /* LKS_SHIFT: any value */
    uint16_t shift_total;  /* LKS_SHIFT: any value */
    lk_vreport_t report;   /* LKS_REPORT */
    uint8_t fault;         /* LKS_FAULT_STORAGE, LKS_FAULT_RELAY: lk_fault_valid */
    /* Messages over the screen. */
    bool has_notice;       /* false: `notice` is ignored */
    lk_notice_t notice;
    uint8_t n_banners;     /* used entries of banners, <= LK_BANNERS_CAP */
    lk_banner_t banners[LK_BANNERS_CAP]; /* in any order, each id at most once among the first n_banners */
} lk_view_t;

/* ---- Status codes (int) ----------------------------------------------------------------------------------- */

enum {
    LK_VS_OK = 0,
    LK_VS_E_NULL = 1,       /* a pointer argument is NULL */
    LK_VS_E_RANGE = 2,      /* an enum, count, id or number is outside its stated range */
    LK_VS_E_BANNER_DUP = 3, /* two of the first n_banners banners have the same id */
    LK_VS_E_FULL = 4        /* the output buffer is too small (or already overflowed) */
};

/* ---- Functions ---------------------------------------------------------------------------------------- */

/* Sets *v to the blank view of `screen` (RUST ViewState::at): every byte of *v is zero except `screen`.
 * Returns true iff v is non-NULL and screen < LKS__COUNT. On any failure, when v is non-NULL, *v is set to all
 * zero bytes (the blank splash) and false is returned. */
bool lk_view_at(lk_view_t *v, uint8_t screen);

/* Validates a view against the ranges above. Returns LK_VS_OK, LK_VS_E_NULL (v is NULL), LK_VS_E_RANGE or
 * LK_VS_E_BANNER_DUP (never LK_VS_E_FULL). Checked: screen, language, screen_countdown_ms; the current
 * screen's fields (V7); the notice when has_notice (kind, dismiss, phrase, countdown_ms, the arguments its
 * phrase uses); n_banners and each used banner (id, phrase, the arguments its phrase uses), then ids unique.
 * Pure; writes nothing. */
int lk_view_check(const lk_view_t *v);

/* Appends the canonical JSON of *v to b, AFTER any content b already holds (it does not clear b).
 *
 * Status, in this order of precedence: v or b NULL -> LK_VS_E_NULL; else lk_view_check(v) when it is not
 * LK_VS_OK; else LK_VS_E_FULL when b had its overflow flag set on entry, or the text does not fit (the text
 * plus the NUL that core_buf keeps need cap >= entry length + text length + 1); else LK_VS_OK.
 * On every status other than LK_VS_OK the content of b is exactly what it was on entry (no partial text is
 * left); only LK_VS_E_FULL for a text that does not fit sets the overflow flag; no other status touches b at
 * all. On LK_VS_OK exactly the canonical text is appended and the NUL is kept. The result is a function of the
 * used fields only (V7): byte-for-byte equal for equal views, whatever the array order of the banners.
 *
 * CANONICAL FORM. Compact JSON (no whitespace, no trailing newline), keys in exactly this order, integers in
 * decimal only (no floats, no signs, no exponents), booleans true/false, absent values null.
 *
 *   {"screen":S,"lang":L,"countdown_ms":C, <screen fields>, "notice":N,"banners":[B,...]}
 *
 *   S  screen text: "splash","welcome","choose","opened","shift","report","lockout","fault_storage",
 *      "fault_relay" (see LKS_*).
 *   L  "bg" or "en". C  screen_countdown_ms, or null when 0.
 *   <screen fields>, each followed by a comma to the next key as usual:
 *      splash, lockout:   none
 *      welcome:           "pad_len":N
 *      choose:            "sizes":[{"size":N,"free":N},...]   the first n_sizes entries in array order
 *      opened:            "locker":N,"first_time":BOOL
 *      shift:             "done":N,"total":N                  (shift_done, shift_total)
 *      report:            "released":N,"ok":N,"faults":N,"write_failed":BOOL
 *      fault_storage, fault_relay:  "fault":"<lk_fault_name(fault)>"   e.g. "relay_busy"
 *   N  null when has_notice is false, else
 *        {"kind":K,"dismiss":D,"phrase":P,"args":A,"warning":BOOL,"countdown_ms":C}
 *      K "dialog","banner","snackbar" (LK_NK_*); D the text beside LK_DISMISS_*; P the text beside LK_PH_*;
 *      countdown_ms null when 0.
 *   B  one banner, in ASCENDING id order whatever their order in the array:
 *        {"id":I,"phrase":P,"args":A,"warning":BOOL}
 *      I the text beside LK_BANNER_*. With n_banners == 0 the array is [].
 *   A  the arguments object of the phrase, keys in this order, nothing else:
 *        LK_PH_FAULT          {"fault":"<lk_fault_name>","door":"<text beside LK_DOOR_*>","locker":N or null when 0}
 *        LK_PH_SYNC_REJECTED  {"status":N}
 *        LK_PH_SYNC_LATE      {"hour":N,"minute":N}
 *        LK_PH_CODES_OFFLINE  {"hour":N,"minute":N}
 *        LK_PH_SELF_TEST      {"issues":N}
 *        every other phrase   {}
 * Example (the blank splash): {"screen":"splash","lang":"bg","countdown_ms":null,"notice":null,"banners":[]} */
int lk_view_canonical(const lk_view_t *v, core_buf_t *b);

#endif
