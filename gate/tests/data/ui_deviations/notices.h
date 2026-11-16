/* apps/lockers/lkui/notices/notices.h: the lockers kiosk's messages (one dialog, banners, a snackbar) as scene nodes.
 *
 * lkui_notices turns the notice, the banner set and the notice countdown of a lk_view_t into scene nodes, through
 * scene_add_notice (the ONLY constructor of the message nodes SC_SCRIM, SC_DIALOG, SC_BANNER, SC_SNACKBAR) plus
 * scene_add for the ordinary text rows of a card. A pure builder over caller storage: no allocation, no mutable
 * static data, no clock, no IO, no recursion. Level L3; deps scene, lkrx/vstate, lkui/catalog, i18n (types only)
 * and core. Included as "apps/lockers/lkui/notices/notices.h". Not thread-safe.
 *
 * Citations: RUST = ui/kit notice.slint (Notice), notice_kind.slint, metrics.slint (KioskMetrics) and
 * ui/lockers notice_host.slint (BannerHost, DialogHost); UI = docs/lockers/ui-rules.md; SCENE = lib/ui/scene/scene.h;
 * VSTATE = apps/lockers/lkrx/vstate/vstate.h.
 *
 * ---- Contract in one paragraph ---------------------------------------------------------------------------
 * The caller (lkui/screens, or a test) has built the screen into `s` first: node 0 of `s` is the scene root (role
 * SC_ROOT). lkui_notices appends, as children of that root, in this order: the banners (ascending banner id), then,
 * when the view has a dialog, one inert blocker, then the notice. Later nodes are painted above earlier ones and
 * receive input first, so a dialog covers its banners and the screen. Nothing is removed, edited or reordered.
 * With no notice and no banners the call writes nothing and returns true.
 *
 * ---- Language and screen ---------------------------------------------------------------------------------
 * The scene carries catalog ids (SCENE: msgid is an i18n message id) and I18N_MSG arguments; the renderer resolves
 * both with the view's language, so the NODES (keys, roles, msgids, arguments, styles, flags, intents) are the same
 * for bg and en. Only the GEOMETRY of a strip card (a banner of the set, a notice of kind banner) reads the view:
 * its row heights come from the banner line table by lk_view_t.language, and a banner of the set is narrow on the
 * welcome screen (lk_view_t.screen == LKS_WELCOME). Dialogs and snackbars read neither. Every msgid written is an
 * LK_CATALOG_* value of apps/lockers/lkui/catalog/catalog.h and every string a person reads is one of them; no text
 * is stored (VSTATE V5).
 *
 * ---- Keys (dense range 0x100..0x147; key space LKN_KEY_SPACE 0x148) -------------------------------------
 * Part numbers LKN_P_*. Banner of id b (LK_BANNER_*, b < LK_BANNER_KINDS = 6), part p: key LKN_KEY_BANNER(b, p) =
 * 0x100 + 8*b + p (0x100..0x12F). Notice, part p: key LKN_KEY_NOTICE(p) = 0x140 + p (0x140..0x147); 0x130..0x13F are
 * unused. The two key macros are for constant arguments (tests, static asserts, a fixed part of the notice): a key
 * computed from a variable is written at its use as LKN_KEY_FIRST + 8u * b + p, so the arithmetic is in the source
 * (a macro that computes from a variable hides it from the mutation gate, rule macro-hidden-code).
 * LKN_KEY_FIRST (0x100) is the first notice key and LKN_KEY_SPACE (0x148) is one above the largest: EVERY key
 * a scene holds after lkui_build and lkui_notices is below LKN_KEY_SPACE, so a renderer key map (lvr_init cap, 8 bytes
 * per key) and a scene-diff table (2 * key space u16) sized by it cost a few hundred entries (the old 0xE000..0xE1FF
 * keys forced about 690 KB against the few KiB of docs/design.md 5.1). The screens use keys below LKN_KEY_FIRST:
 * lkui/screens has the constant LKUI_KEY_LIMIT (256) and uses at most 191 (cell base 128 + 63). This header does not
 * include screens.h (no dependency), so it pins the bound it relies on, LKN_KEY_FIRST == LKUI_KEY_LIMIT == 256, and
 * the tests check it against screens.h and against every screen. The screen must not use keys in the range (a clash
 * makes the add refuse, see Errors). Parts: SCRIM 0 (role SC_SCRIM), CARD 1 (role SC_DIALOG/SC_BANNER/SC_SNACKBAR),
 * TEXT 2 (the body sentence), DISMISS 3 (the button), TITLE 4, DETAIL 5, COUNTDOWN 6, BLOCKER 7 (notice only).
 *
 * ---- Nodes of one card (a "card" = a banner of the set, or the notice) -----------------------------------
 * Added in this order (the first four by one scene_add_notice call, SCENE "scrim, card, text, dismiss"; the call
 * carries the per-part styles text_style and dismiss_style of scene_notice_t, see Styles below):
 *   1 SCRIM    parent = the root. rect, intent and style below; msgid SCENE_NO_MSG; flags SC_NOTICE.
 *   2 CARD     parent = the root. Role by kind. Flags SC_NOTICE, plus SC_WARN iff it is a banner whose warning is
 *              true (RUST: warn = strip && warning; a dialog or snackbar is never warned, whatever .warning says).
 *   3 TEXT     parent = CARD. Role SC_TEXT. The BODY sentence of the phrase, with its arguments (table below).
 *   4 DISMISS  parent = CARD. Role SC_BUTTON. msgid LK_CATALOG_DISMISS, no arguments, intent LKN_INTENT_DISMISS +
 *              d (d below), intent_arg a (a below). Rect w and h are at least 48 (SCENE_MIN_TOUCH; RUST touch 48 dp).
 *   5 TITLE    only when the phrase has a title: parent = CARD, role SC_TEXT, msgid = the title, no arguments.
 *   6 DETAIL   only for LK_PH_FAULT: parent = CARD, role SC_TEXT. With locker != 0: msgid LK_CATALOG_LOCKER_0_1,
 *              arguments [I18N_INT locker, I18N_MSG cause]. With locker == 0: msgid = the cause, no arguments.
 *   7 COUNTDOWN only for the NOTICE (banners have none, VSTATE D5) with countdown_ms != 0: parent = CARD, role
 *              SC_COUNTDOWN, msgid LK_CATALOG_N0_S, one argument [I18N_INT countdown_ms / 1000] (rounded DOWN: 1 ms -> 0,
 *              999 -> 0, 1000 -> 1, 1001 -> 1, 1999 -> 1, 300000 -> 300; the row is still present for 1..999 ms).
 * TITLE, DETAIL, COUNTDOWN and the BLOCKER have no intent: intent 0 and intent_arg 0; TITLE, DETAIL and COUNTDOWN
 * have flags 0 (of a banner of the set and of the notice alike).
 * Children of the CARD are therefore ordered TEXT, DISMISS, TITLE, DETAIL, COUNTDOWN (those present). Role of the
 * CARD: kind LK_NK_DIALOG -> SC_DIALOG, LK_NK_BANNER -> SC_BANNER, LK_NK_SNACKBAR -> SC_SNACKBAR; a banner of the
 * set is SC_BANNER.
 *
 * Styles (ui-look 4.2 "Mapping of notices.h"; the same for the notice and for a banner of the set): SCRIM and CARD
 * carry the card style, LKN_STYLE_DIALOG 1, LKN_STYLE_BANNER 2 or LKN_STYLE_SNACKBAR 3 by kind; TEXT (the body) carries
 * LKN_ST_BODY 13 (text_style of scene_notice_t), DISMISS LKN_ST_DISMISS 15 (dismiss_style), TITLE LKN_ST_TITLE 12,
 * DETAIL LKN_ST_CAPTION 14, COUNTDOWN LKN_ST_CAPTION 14 (the style of the rows added with scene_add); the BLOCKER has
 * style 0.
 *
 * Dismiss intent: d is notice.dismiss for the notice, and LK_DISMISS_BANNER_NOT_SAVED + id for a banner of the set
 * (VSTATE: implied by id). The scene intent is LKN_INTENT_DISMISS (0x0100) + d, never 0, because SCENE needs a
 * nonzero intent and LK_DISMISS_OVERLAY is 0. Every card has exactly one such DISMISS button.
 * Dismiss argument a (scene dismiss_arg, carried by the DISMISS button and by the scrim that has the intent): the
 * overlay dismiss names WHAT is dismissed (dismiss@1 carries notice_kind, notice.h, VSTATE), so for the NOTICE with
 * d == LK_DISMISS_OVERLAY a is the notice kind, LK_NK_DIALOG (0) or LK_NK_SNACKBAR (2) (a notice of kind
 * LK_NK_BANNER with d == LK_DISMISS_OVERLAY, which VSTATE accepts, gives LK_NK_BANNER, 1: the kind as given). For
 * every other card a is 0: a banner of the set (the banner kind is in d) and a notice whose d is a banner intent.
 *
 * SCRIM intent (SCENE): a dialog's scrim has no intent (0, arg 0: RUST "the scrim swallows the tap", UI "the scrim
 * does not dismiss"); the scrim of a banner or snackbar has the DISMISS intent (tap outside dismisses).
 *
 * ---- Geometry (dp, window 1280x800; all integer; RUST KioskMetrics) --------------------------------------
 * Tokens: LKN_W 1280, LKN_H 800, unit 8, PAD 24 (3 units), TOUCH 48, BAR 12, GAP 16 (2 units), LINE_TITLE 48,
 * LINE_BODY 40, LINE_CAPTION 24 (RUST title 40, body 32, caption 16 plus one unit of leading).
 * A text wraps with no line limit and no elision (ui-look 5) and C has no text measurer, so a row is
 * LKN_ROW_H(line, lines) = lines * line high, line being the LKN_LINE_* of the row: 48 TITLE, 40 TEXT, 24 DETAIL and
 * COUNTDOWN. lines = ceil(characters * 0.6 * font / row width), at least 1, the font being 40 (TITLE), 32 (TEXT), 16
 * (DETAIL, COUNTDOWN) and "characters" the Unicode code points of the text. The 0.6 * font advance is a stand-in for
 * the glyph advance, as the LINE_* are for the line heights.
 * Panel cards (dialog, snackbar; ui-look O11 reading A): one worst case per (row, card), the same for every phrase
 * and both languages, from the worst characters 22 (TITLE), 66 (TEXT), 105 (DETAIL: the longest cause plus
 * "Locker 999. "), under 10 (COUNTDOWN). Row widths dialog 672, snackbar 512. Lines and heights:
 *               dialog  snackbar
 *   TITLE        1 (48)   2 (96)
 *   TEXT         2 (80)   3 (120)
 *   DETAIL       2 (48)   2 (48)
 *   COUNTDOWN    1 (24)   1 (24)
 * Strip cards (a banner of the set, a notice of kind banner; owner, 2026-11-12: per-phrase line table for banners):
 * the BANNER LINE TABLE. For the TITLE, TEXT and DETAIL rows, `lines` is the formula above for THAT row's msgid in
 * the view's language at the strip's row width: narrow strip (608) TITLE 388, TEXT and DETAIL 592; wide strip (1232)
 * TITLE 1012, TEXT and DETAIL 1216. COUNTDOWN is 1 line. "Characters" is the longest rendering of the msgid with its
 * arguments: SYNC_REJECTED_0 with a 5-digit status (65535); SYNC_EVENTS_NOT_UPLOADED_SINCE_0 and
 * CODES_OFFLINE_USING_THE_LIST_SAVED_AT_0 with "HH:MM" (5 characters); LOCKER_0_1 with a 3-digit locker (999,
 * LK_LOCKER_MAX) and the longest cause of the FAULT detail table in that language; every other msgid of the table has
 * no argument. The values (bg / en code points; lines narrow / wide):
 *   TITLE  CODE_NOT_ACCEPTED 16/17 (bg 1/1, en 2/1); CODES_UNAVAILABLE 22/17 (2/1, 2/1); NO_LOCKER_FREE 20/14 (2/1,
 *          1/1); SOMETHING_WENT_WRONG 14/20 (1/1, 2/1); CODES_OFFLINE 18/13 (2/1, 1/1); NOT_SAVED, AUDIT_LOG, SYNC,
 *          CODES, SELF_TEST 1 line everywhere.
 *   TEXT   2 lines narrow, 1 wide: THE_CODE_LIST_IS_UNAVAILABLE_TRY_AGAIN_SHORTLY, EVERY_LOCKER_IS_IN_USE_PLEASE_ASK_THE_STAFF,
 *          the three PLEASE_ASK_STAFF_FOR_HELP_* bodies, AUDIT_LOG_AN_EVENT_COULD_NOT_BE_WRITTEN,
 *          SYNC_EVENTS_NOT_UPLOADED_SINCE_0, CODES_OFFLINE_USING_THE_LIST_SAVED_AT_0,
 *          CODES_THE_ALLOWED_CODE_LIST_COULD_NOT_BE_REFRESH, RESERVATION_BOOK_COULD_NOT_BE_LOADED;
 *          NOT_SAVED_THE_DOOR_OPENED_AND_THE_RESERVATION_WA 3 narrow, wide bg 2 / en 1; SYNC_REJECTED_0,
 *          DATA_DIRECTORY_IS_NOT_WRITABLE, FREE_SPACE_COULD_NOT_BE_READ bg 2 / en 1 narrow, 1 wide; every other body of
 *          the phrase table 1 line everywhere.
 *   DETAIL 2 lines narrow, 1 wide: KIOSK_BUSY_ANOTHER_KIOSK_PROCESS_HOLDS_THE_RELAY,
 *          STORAGE_ERROR_THE_RESERVATION_BOOK_COULD_NOT_BE, LOCKER_0_1; RELAY_BUSY_A_RELAY_WAS_ALREADY_ON_SO_NOTHING_WAS
 *          and RELAY_SAFETY_STOP_A_RELAY_STAYED_ON_AND_WAS_FORC bg 2 / en 1 narrow, 1 wide; every other cause 1 line.
 * Guard (the test notices_lines_test, built and run by every build): every msgid a strip row can carry has an entry
 * in both languages, each entry equals the formula on the catalog string of today, and no entry exceeds the old
 * worst case (narrow: TITLE 2, TEXT 3, DETAIL 2; wide: 1, 2, 1), so no strip is taller than before (a banner of the
 * set at most 236 with a title and a body, 288 with a detail). A catalog change that moves an entry fails the build.
 * Rows present: TITLE if the phrase has a title; TEXT always; DETAIL for a fault; COUNTDOWN if any.
 *
 * Panel cards (kind dialog or snackbar; RUST !strip): width LKN_DIALOG_W 720 (RUST min(720, 1280 - 4*24)) or
 * LKN_SNACKBAR_W 560 (RUST min(560, 1280 - 2*24)); x = (1280 - w) / 2. Starting at y0 = card.y + 24 the BAR (12 dp,
 * a painted accent, no node) is first; before each row come GAP 16; rows in order TITLE, TEXT, DETAIL, COUNTDOWN
 * (worst-case heights above), DISMISS (h 48); each row has x = card.x + 24 and w = card.w - 48.
 * card.h = 24 + 12 + sum(16 + row height) + 24. Dialog: card.y = (800 - card.h) / 2; snackbar:
 * card.y = 800 - card.h - 24.
 * Strip cards (kind banner; RUST strip): padding 8, spacing 4. The top row is max(48, TITLE height) high (the TITLE
 * height when there is a title, 48 without) at y = card.y + 8 and holds, left to right: the
 * painted accent bar (12 wide, no node), 16, TITLE (x = card.x + 36, w = card.w - 220), 16, DISMISS
 * (x = card.x + card.w - 168, w LKN_DISMISS_SLOT 160, h 48). Below it, each present row of TEXT, DETAIL, COUNTDOWN
 * is preceded by 4 and has x = card.x + 8, w = card.w - 16. card.h = 8 + top row + sum(4 + row height) + 8 (so a
 * one-line body gives 108, with or without a one-line title, which shares the 48-high top row with DISMISS). Without
 * a title the TITLE node is absent, the top row is 48 and still holds DISMISS.
 *   Notice of kind banner (RUST DialogHost, overlay): wide, card.w LKN_STRIP_W 1232 (1280 - 2*24), x 24, y 24, on
 *   every screen.
 *   Banner of the set (RUST BannerHost, overlay false; ui-look 6.3 and C9): x = LKN_PAD (24; RUST: the banner host
 *   sits at (pad, pad)); narrow, card.w LKN_SET_W_WELCOME 608 (the left half, the numpad stays free) when
 *   lk_view_t.screen is LKS_WELCOME, wide (LKN_STRIP_W 1232) on every other screen.
 *   The i-th banner shown (ascending id, i from 0) has y = 24 + sum over earlier shown banners j of (h_j + 16).
 * SCRIM rect: the whole window (0, 0, 1280, 800) for the notice (all kinds). For a banner of the set (RUST: the
 * card only, no overlay) it equals the card rect, so nothing outside the strip can dismiss it and the screen stays
 * usable. BLOCKER rect: the whole window.
 *
 * ---- Phrases -> nodes -------------------------------------------------------------------------------------
 * LK_PH_*                  TITLE (LK_CATALOG_)   BODY (TEXT msgid)                      body arguments
 * REJECT_INVALID           CODE_NOT_ACCEPTED     THAT_CODE_IS_NOT_VALID                 none
 * REJECT_UNKNOWN           CODE_NOT_ACCEPTED     THAT_CODE_IS_NOT_RECOGNISED            none
 * REJECT_CODES_UNAVAILABLE CODES_UNAVAILABLE     THE_CODE_LIST_IS_UNAVAILABLE_TRY_AGAIN_SHORTLY  none
 * NO_LOCKER                NO_LOCKER_FREE        EVERY_LOCKER_IS_IN_USE_PLEASE_ASK_THE_STAFF     none
 * FAULT                    SOMETHING_WENT_WRONG  by args.door: NOTHING_OPENED -> PLEASE_ASK_STAFF_FOR_HELP_NOTHING_WAS_OPENED,
 *                                                MAYBE_OPENED -> PLEASE_ASK_STAFF_FOR_HELP_A_DOOR_MAY_HAVE_OPENED,
 *                                                OPENED -> PLEASE_ASK_STAFF_FOR_HELP_A_DOOR_WAS_OPENED       none
 * SAVED                    (no title)            RESERVATION_SAVED                      none
 * NOT_SAVED                NOT_SAVED             NOT_SAVED_THE_DOOR_OPENED_AND_THE_RESERVATION_WA  none
 * AUDIT                    AUDIT_LOG             AUDIT_LOG_AN_EVENT_COULD_NOT_BE_WRITTEN         none
 * SYNC_REJECTED            SYNC                  SYNC_REJECTED_0                        [I18N_INT status]
 * SYNC_LATE                SYNC                  SYNC_EVENTS_NOT_UPLOADED_SINCE_0       [I18N_HHMM t]
 * CODES_OFFLINE            CODES_OFFLINE         CODES_OFFLINE_USING_THE_LIST_SAVED_AT_0  [I18N_HHMM t]
 * CODES_STALE              CODES                 CODES_THE_ALLOWED_CODE_LIST_COULD_NOT_BE_REFRESH  none
 * SELF_TEST                SELF_TEST             issues == 0: SELF_TEST_OK; else by the LOWEST set bit k of
 *                                                issues (VSTATE: bit k = issue code k+1), table SELFTEST_BODY: bit 0
 *                                                RELAY_BOARD_NOT_REACHABLE, 1 A_RELAY_IS_STILL_ON, 2 CODES_UNAVAILABLE,
 *                                                3 NO_ACTIVE_CODES, 4 DATA_DIRECTORY_IS_NOT_WRITABLE, 5 FREE_SPACE_COULD_NOT_BE_READ,
 *                                                6 DISK_ALMOST_FULL, 7 RESERVATION_BOOK_COULD_NOT_BE_LOADED, 9 CLOCK_LOOKS_WRONG;
 *                                                bits 8, 10, 11 (sentences that need a count the view does not carry,
 *                                                VSTATE D3) -> SOMETHING_WENT_WRONG                none
 * t = (hour * 60 + minute) * 60000 ms (the template prints HH:MM UTC). The FAULT detail cause, by args.fault:
 * RELAY_BUSY RELAY_BUSY_A_RELAY_WAS_ALREADY_ON_SO_NOTHING_WAS; KIOSK_BUSY KIOSK_BUSY_ANOTHER_KIOSK_PROCESS_HOLDS_THE_RELAY;
 * LOCK_UNAVAILABLE RELAY_LOCK_UNAVAILABLE (the arg-less lower-case variant; the reason is dropped, VSTATE D2);
 * RELAY_SAFETY_STOP RELAY_SAFETY_STOP_A_RELAY_STAYED_ON_AND_WAS_FORC; RELAY_OFFLINE RELAY_OFFLINE_THE_RELAY_BOARD_DID_NOT_ANSWER;
 * RELAY_ERROR RELAY_ERROR_THE_LOCKER_OPENER_FAILED; STORAGE_ERROR STORAGE_ERROR_THE_RESERVATION_BOOK_COULD_NOT_BE;
 * CODES_UNAVAILABLE CODES_UNAVAILABLE_THE_ALLOWED_CODE_LIST_COULD_NO; BOOK_REJECTED BOOK_REJECTED_THE_OPENING_WAS_NOT_RECORDED;
 * LOCKER_MISSING LOCKER_MISSING_THAT_LOCKER_IS_NOT_IN_THE_INVENTO.
 * The phrase of a notice or a banner is used as given: any kind may carry any phrase (VSTATE accepts every combination).
 *
 * ---- Input behind a dialog (the inert flag) ---------------------------------------------------------------
 * When the view has a notice of kind LK_NK_DIALOG, the module adds, after the banners and immediately before the
 * dialog's SCRIM, ONE node: key LKN_KEY_NOTICE(LKN_P_BLOCKER), parent the root, role SC_PANEL, rect the whole
 * window, style 0, flags SC_INERT, msgid SCENE_NO_MSG, no intent. Every node before it in tree order (the screen and
 * all banners, so their dismiss buttons too) is therefore behind an inert layer that ignores input; the dialog's
 * own nodes come after it and stay live. SCENE cannot mark earlier nodes inert, and scene_add_notice never sets
 * SC_INERT, so this node is the only inert node the module writes. With any other view (no notice, snackbar or
 * banner notice) no node written has SC_INERT. Banners and snackbars never block the pad (UI).
 *
 * ---- Errors ----------------------------------------------------------------------------------------------
 * lkui_notices returns true iff everything was written (or there was nothing to write). It returns false and
 * writes nothing, overflow flag unchanged, for: v NULL; s NULL or uninitialised (also when there is nothing to
 * write); lk_view_check(v) != LK_VS_OK (a bad range, a duplicate banner id: nothing is guessed); and a scene that
 * is initialised but has no node yet (no root), when there is something to write. With nothing to write (has_notice false and n_banners 0) it
 * returns true and the scene, even a full or overflowed one, is untouched.
 * OVERFLOW: when an add does not fit (SCENE: the sticky overflow flag is set by the scene), or is refused because
 * the flag was already set, or a key clashes, lkui_notices stops at once and returns false. The nodes written
 * before the failing add stay (a valid prefix: scene_check still gives SCENE_OK, because a scene_add_notice is all
 * or nothing, so every card present has its DISMISS; extra rows of the last card can be missing); nothing is rolled
 * back; the module never clears the overflow flag.
 * No free text, no business logic: the module only maps view fields to the nodes above; it holds no state, so
 * calling it twice on a scene rebuilt (scene_begin and the screen again) writes identical bytes.
 *
 * ---- Rust / doc / scene disagreements (D8: Rust wins unless listed here) ---------------------------------
 * N1  UI says a banner is dismissed by "Dismiss on the strip and a tap outside the strip". RUST BannerHost builds the
 *     banners of the set with overlay false (the card only); only the overlay banner of DialogHost has a tap-outside
 *     layer. Pinned as RUST: set banners have SCRIM == CARD rect; a notice of kind banner has the full-window scrim.
 * N2  SCENE's scene_add_notice has ONE text node; RUST Notice shows title, message, detail and countdown. The extra
 *     rows are ordinary nodes (SC_TEXT, SC_COUNTDOWN) added with scene_add; they are not message-role nodes.
 * N3  RUST measures wrapped text, DESIGN has no measurer: panel cards keep worst-case rows (O11 reading A); strip
 *     cards use the banner line table (owner, 2026-11-12), the same 0.6 * font estimate per msgid and language.
 * N4  RUST BannerHost has three fixed slots; VSTATE has a set of up to LK_BANNER_KINDS (6) banners, all shown,
 *     ascending id (VSTATE D5), stacked with a 16 dp gap as BannerHost does (gap = 2 units).
 * N5  RUST places the BannerHost at (pad, pad): x = LKN_PAD (24), y = 24; 608 wide on welcome and 1232 elsewhere
 *     (ui-look C9; RUST's welcome column is measured, C's is the fixed 608 of O5 reading A). RUST dismiss-slot is the measured label
 *     width * 1.5 + 32 dp (at least 48); a fixed LKN_DISMISS_SLOT 160 is pinned. RUST dismiss min-height max(48, label + 16): pinned 48.
 * N6  DESIGN "input behind a dialog marked inert" cannot mark earlier nodes (SCENE); an SC_INERT blocker node is
 *     written. RUST achieves it by a TouchArea layer and by `expose` (a banner's Dismiss is not exposed while a
 *     dialog is open); the blocker covers both.
 * N7  VSTATE dismiss 0 is a real intent (overlay) but SCENE intent 0 means none: the scene intent is offset by
 *     LKN_INTENT_DISMISS. DESIGN's sketch returns void; this returns bool.
 * N8  The Rust phrase text for rejection, fault, banner copy is not in the staged sources; the title/body/cause
 *     mapping above is pinned from the catalog ids and UI's message catalogue. VSTATE D2/D3 drop the lock reason and
 *     the self-test counts, so the matching sentences are approximated as listed.
 * N9  The task text speaks of 11 banner kinds; VSTATE has 6 (LK_BANNER_KINDS). The tests cover all 6 ids and 11
 *     banner phrase/tone variants.
 */
#ifndef LKUI_NOTICES_H
#define LKUI_NOTICES_H

#include <stdbool.h>
#include <stdint.h>

#include "apps/lockers/lkc/uikeys/uikeys.h"
#include "apps/lockers/lkrx/vstate/vstate.h"
#include "apps/lockers/lkui/catalog/catalog.h"
#include "lib/ui/scene/scene.h"

#define LKN_W 1280
#define LKN_H 800
#define LKN_PAD 24
#define LKN_GAP 16
#define LKN_BAR 12
#define LKN_LINE_TITLE 48
#define LKN_LINE_BODY 40
#define LKN_LINE_CAPTION 24
#define LKN_DIALOG_W 720
#define LKN_SNACKBAR_W 560
#define LKN_STRIP_W 1232
#define LKN_SET_W_WELCOME 608
#define LKN_DISMISS_SLOT 160
#define LKN_ST_TITLE 12
#define LKN_ST_BODY 13
#define LKN_ST_CAPTION 14
#define LKN_ST_DISMISS 15
#define LKN_ROW_H(line, lines) ((lines) * (line))

enum { LKN_STYLE_DIALOG = 1, LKN_STYLE_BANNER = 2, LKN_STYLE_SNACKBAR = 3 };
/* LKN_INTENT_DISMISS is the contract lkc/uikeys (P007 C4). */
enum {
    LKN_P_SCRIM = 0, LKN_P_CARD = 1, LKN_P_TEXT = 2, LKN_P_DISMISS = 3,
    LKN_P_TITLE = 4, LKN_P_DETAIL = 5, LKN_P_COUNTDOWN = 6, LKN_P_BLOCKER = 7
};
#define LKN_KEY_FIRST 0x100u
#define LKN_KEY_SPACE 0x148u
#define LKN_KEY_BANNER(id, part) ((uint16_t)(0x100u + 8u * (unsigned)(id) + (unsigned)(part)))
#define LKN_KEY_NOTICE(part) ((uint16_t)(0x140u + (unsigned)(part)))

_Static_assert(LKN_KEY_BANNER(0, LKN_P_SCRIM) == LKN_KEY_FIRST, "banner keys start at LKN_KEY_FIRST");
_Static_assert(LKN_KEY_FIRST == 256u, "the screens use keys below 256 (LKUI_KEY_LIMIT), 191 at most");
_Static_assert(LKN_KEY_BANNER(LK_BANNER_KINDS - 1, LKN_P_BLOCKER) < LKN_KEY_NOTICE(LKN_P_SCRIM),
               "banner keys stay below the notice keys");
_Static_assert(LKN_KEY_NOTICE(LKN_P_BLOCKER) + 1u == LKN_KEY_SPACE, "LKN_KEY_SPACE is one above the largest notice key");

/* Appends the messages of *v to `s` (see the contract above). True iff all were written or nothing was due. */
bool lkui_notices(const lk_view_t *v, scene_t *s);

#endif
