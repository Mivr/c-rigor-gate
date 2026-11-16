/* apps/lockers/lkui/screens/screens.h: the lockers kiosk screens as a scene tree (the ui path of design 4.7).
 *
 * One pure function: lkui_build turns the screen of a lk_view_t, and the fields that screen shows, into scene nodes,
 * through scene_add only. No allocation, no mutable static data, no recursion, no clock, no IO. Level L3. Included as
 * "apps/lockers/lkui/screens/screens.h". Deps: scene, lkrx/vstate, lkrx/vstate2, lkui/catalog, i18n (types only), core.
 * Messages (dialogs, banners, snackbars) are lkui/notices: this module never creates a message-role node and never
 * sets SC_NOTICE. Language is not applied here: nodes carry catalog ids (LK_CATALOG_*, apps/lockers/lkui/catalog/
 * catalog.h) and arguments; the renderer picks the language. The view's language only decides which button of the
 * language switch is marked selected (L6).
 *
 * Citations: RUST = the staged kiosk Slint sources lockers-*.slint (lockers.slint window, idle/choose/opened/shift/
 * status screens, copy, language) and kit-*.slint (metrics, numpad); UI = docs/lockers/ui-rules.md; VS = vstate.h;
 * SC = scene.h. D8 applies: Rust wins over the docs; the places it cannot be followed are listed in DISAGREEMENTS.
 *
 * ---- Contract -------------------------------------------------------------------------------------------------
 * lkui_build(v, s) returns true iff the whole tree was written. In this order:
 *  B1  v NULL, s NULL, or s uninitialised (zero-filled)                     -> false, nothing written, no crash.
 *  B2  lk_view_check(v) != LK_VS_OK                                         -> false, the scene byte for byte
 *      unchanged (scene_begin is NOT called). Fields of other screens are ignored (VS V7).
 *  B3  Otherwise it calls scene_begin(s) itself (so the result depends on the view alone, and a scene built before
 *      is replaced), then adds the nodes below in the order given (pre-order, parents first, so the order is the
 *      scene_dump order). The caller does NOT call scene_begin before lkui_build. lkui/notices adds its nodes
 *      afterwards, on the same scene, and calls scene_end last; this module never calls scene_end. On true,
 *      scene_check(s) == SCENE_OK, scene_overflow(s) is false, and no node has role SC_SCRIM/SC_DIALOG/SC_BANNER/
 *      SC_SNACKBAR or flag SC_NOTICE.
 *  B4  OVERFLOW: if any scene_add fails (a capacity overflow, or a refusal), lkui_build stops at once and returns
 *      false. The nodes added before stay (a valid prefix tree, in the order below); scene_overflow(s) is true when
 *      the cause was capacity. Storage of LKUI_NODES_MAX nodes and LKUI_ARGS_MAX argument bytes always suffices; the
 *      exact need per screen is listed in COUNTS.
 *  Every node has parent = the key of a node added before it, pad_ zero (SC), and keys below LKUI_KEY_LIMIT (256);
 *  keys 256..65535 are free for lkui/notices. Intent ids 1..8 are the screens' (LKUI_I_*); ids 9..255 are left to
 *  lkui/notices. A node that has an intent is a touch target; so are the nodes of role SC_BUTTON and SC_KEY (a
 *  DISABLED size button is a button with intent 0). The scene is 1280 x 800 dp; a renderer scales it uniformly.
 *
 * ---- Tokens (RUST kit-metrics.slint KioskMetrics, px = dp) ------------------------------------------------------
 *  LKUI_W 1280, LKUI_H 800   RUST lockers.slint preferred-width / preferred-height; window-fit scales type with the
 *                            window against 1280x800, which is what the uniform renderer scale does.
 *  LKUI_UNIT 8   unit            LKUI_TOUCH 48   touch (the 48 dp minimum; SCENE_MIN_TOUCH)
 *  LKUI_THUMB 88 thumb           LKUI_RADIUS 28 radius      LKUI_RADIUS_KEY 16 radius-key     LKUI_BAR 12 bar
 *  fonts, in dp: LKUI_FONT_DISPLAY 200 display, LKUI_FONT_HEADLINE 48, LKUI_FONT_TITLE 40, LKUI_FONT_BODY 32,
 *                LKUI_FONT_STAFF 24, LKUI_FONT_CAPTION 16.   LKUI_FONT_MIN = 16 = caption: the smallest font any
 *                node uses.
 *  LKUI_PAD 24 = unit*3 (RUST `pad`), LKUI_GAP 16 = unit*2 (RUST `gap`).
 *  THUMB, RADIUS and RADIUS_KEY are renderer-side (a scene node has no corner radius); no node carries them.
 *  LKUI_LINE(f) = f + f/4: the height of a one-line text of font f (RUST text height depends on font metrics; this
 *  is the pinned stand-in): 200 -> 250, 48 -> 60, 40 -> 50, 32 -> 40, 24 -> 30, 16 -> 20.
 *
 * ---- Node vocabulary ------------------------------------------------------------------------------------------
 *  style of TEXT, COUNTDOWN, BUTTON, KEY nodes = a STYLE token of docs/lockers/ui-look.md 4.2 (the closed set 1..21,
 *  LKUI_ST_*: font size, weight, colour, alignment and button fill; the renderer reads it). The LKUI_FONT_* sizes are
 *  no longer a node's style: they stay as the unit of the heights and widths (LKUI_LINE, LKUI_TEXT_H). Tokens 12..14
 *  are lkui/notices': this module never writes them. The token of every node is in "Node tokens" below.
 *  style of PANEL nodes = a tone: LKUI_TONE_NONE 0, INFO 1 (RUST secondary), SUCCESS 2 (primary), ERROR 3 (error),
 *  WARNING 4 (tertiary), SELECTED 5 (no longer written: the selected language is marked by the tokens 20 and 21 of the
 *  two buttons, O12), ATTRIBUTION 6 (the Slint AboutSlint badge), DOT 7 (a typed-digit marker). style of ROOT is 0.
 *  flags: only SC_DISABLED (a full size button) and SC_WARN (the write warning) are ever set. Nodes with text have msgid = a LK_CATALOG_* id and the INT
 *  arguments stated (the ECHO panel's msgid is its accessible label, X6); every other node has msgid SCENE_NO_MSG.
 *  No node carries free text (STR is used once: L9).
 *  Intents (scene intent / intent_arg):
 *    LKUI_I_DIGIT 1 (arg = the digit 0..9)   LKUI_I_BACKSPACE 2 (0)   LKUI_I_SUBMIT 3 (0)   LKUI_I_CHOOSE 4 (arg =
 *    the lk_vsize_t.size)   LKUI_I_CANCEL 5 (0)   LKUI_I_OPENED_DONE 6 (0)   LKUI_I_SHIFT_DONE 7 (0)
 *    LKUI_I_LANGUAGE 8 (arg = LK_LANG_BG 0 or LK_LANG_EN 1).     RUST callbacks digit-tapped, backspace-tapped,
 *    submit-tapped, size-chosen, cancel-tapped, opened-done, done-tapped, language-chosen.
 *  Node tokens (both languages alike; only the language buttons depend on the view):
 *    SPLASH TITLE 2.  LOCKOUT TITLE 2, MESSAGE 4, COUNTDOWN 6.
 *    FAULT_STORAGE, FAULT_RELAY TITLE 2, MESSAGE 4, DETAIL 7.
 *    WELCOME TITLE 2, MESSAGE 5 (muted, C12), numpad keys 32..43 15, LANG_BG / LANG_EN 20 (selected) and 21 (other).
 *    CHOOSE TITLE 2, COUNTDOWN 10, LANG_BG / LANG_EN 20 / 21, size buttons 48+k 16 (17 when n_sizes >= 5; a full one
 *      has the same token and SC_DISABLED), CANCEL 18 (19 when n_sizes >= 5).
 *    OPENED digit texts 64..66 1, MESSAGE 4, COUNTDOWN 10, LANG_BG / LANG_EN 20 / 21, DONE 16.
 *    SHIFT TITLE 8, LICENSES 10, DONE 17.  REPORT TITLE 3, COUNTDOWN 10, RELEASED 8, OK 9, FAULTS 9, WARNING 11 (with
 *      SC_WARN), LICENSES 10, DONE 17.
 *  Text rects (O11): a text rect is tall enough for the worst case in both languages, h = LKUI_TEXT_H(f, lines), f the
 *  font of its token and lines = ceil(worst characters x 0.6 x f / width) over the longest strings of ui-look 5. Every
 *  text has 1 line except the WELCOME MESSAGE (47 characters at 32 dp in 608: 2 lines, 80 tall) and the FAULT DETAIL
 *  (up to 93 characters at 24 dp in 1232: 2 lines, 60 tall). The renderer wraps inside the rect and never needs more.
 *  Keys (all screens; a screen uses a subset): ROOT 1, BAR 2, TITLE 3, MESSAGE 4, DETAIL 5, COUNTDOWN 6, ABOUT 7,
 *  LICENSES 8, LANG 9, LANG_SEL 10, LANG_BG 11, LANG_EN 12, ECHO 13, NUMPAD 14, NUMBER 15, DONE 16, CANCEL 17,
 *  TRACK 18, FILL 19, RELEASED 20, OK 21, FAULTS 22, WARNING 23 (LKUI_K_*), and the bases KEY 32 (+0..11),
 *  SIZE 48 (+0..5), DIGIT 64 (+0..2), CELL 128 (+0..63) (LKUI_K_KEY_BASE etc.).
 *  Digit ids: the catalog ids of "0".."9" are LK_CATALOG_N0 .. LK_CATALOG_N9; they are NOT consecutive (N8_S sits
 *  between N8 and N9), so use the names.
 *
 * ---- Layout rules ---------------------------------------------------------------------------------------------
 *  ROOT: SC_ROOT key 1 parent 0 @0,0 1280x800 style 0 msg none, first node, no intent.
 *  COLUMN(x, w, gap, rows): the rows are laid top to bottom, each row h tall, `gap` between rows; total = sum(h) +
 *    gap*(rows-1); the first row starts at y0 = (800 - total) / 2 (integer division). A row is x..x+w wide unless it
 *    states its own width, in which case it is centred: x + (w - rw) / 2. Absent (conditional) rows take no height
 *    and no gap. Rows are children of ROOT unless stated.
 *  COUNTDOWN row: shown iff v->screen_countdown_ms != 0 AND the screen is CHOOSE, OPENED, REPORT or LOCKOUT (RUST
 *    countdown-text: choose, opened, shift report, lockout; UI "Screen timers"). Node role SC_COUNTDOWN key 6, msg
 *    LK_CATALOG_N0_S ("{0} s") with one INT argument = the whole seconds, rounded DOWN: ms / 1000 (1 ms -> 0,
 *    999 -> 0, 1000 -> 1, 1001 -> 1, 1999 -> 1, 300000 -> 300); the row is still present for 1..999 ms (argument 0).
 *    On other screens the field is ignored. The countdown is never a notice.
 *  LANG row (48 tall, 200 wide, centred): PANEL key 9 style NONE; children, in this order: BUTTON key 11 at the
 *    panel's x, 96x48, msg LK_CATALOG_BG, intent LANGUAGE:0; BUTTON key 12 at panel x + 104, 96x48, msg
 *    LK_CATALOG_EN, intent LANGUAGE:1. Selected = v->language (BG for any value other than EN): its button has token
 *    LKUI_ST_BTN_LANG_ON (20), the other LKUI_ST_BTN_LANG_OFF (21). Key 10 and LKUI_TONE_SELECTED stay defined and
 *    are never written. (RUST language.slint: two 48 dp buttons, spacing unit, the current one primary-container.)
 *  ABOUT row (120 tall, 160 wide, centred): PANEL key 7 style ATTRIBUTION (the Slint attribution badge).
 *  LICENSES row: TEXT key 8, token 10 (CAPTION_MUTED, h 20),
 *    msg LK_CATALOG_OPEN_SOURCE_LICENSES_ARE_PACKAGED_WITH_THIS_APP.
 *
 * ---- Screens (the closed set LKS_*; every case below is the whole tree after ROOT) ---------------------------
 * Text rows are TEXT nodes of the column width, font f (the size of the token), h = LKUI_TEXT_H(f, 1) = LKUI_LINE(f)
 * unless stated, msg as shown.
 *  LKS_SPLASH (RUST status.slint mode 0)   COLUMN(24, 1232, 16): TEXT key 3 HEADLINE LK_CATALOG_LOCKERS; ABOUT.
 *      No input, no countdown, no language switch. 3 nodes.
 *  LKS_LOCKOUT (mode 1)   COLUMN(24, 1232, 16): PANEL key 2 h 12 style WARNING; TEXT key 3 HEADLINE
 *      LK_CATALOG_PLEASE_WAIT; TEXT key 4 BODY LK_CATALOG_TOO_MANY_ATTEMPTS_PLEASE_WAIT; COUNTDOWN row with token
 *      6 (font 40, h 50). No intent anywhere (lockout ignores input, UI). 4 or 5 nodes.
 *  LKS_FAULT_STORAGE, LKS_FAULT_RELAY (mode 2; identical trees)   COLUMN(24, 1232, 16): PANEL key 2 h 12 style
 *      ERROR; TEXT key 3 HEADLINE LK_CATALOG_SOMETHING_WENT_WRONG; TEXT key 4 BODY
 *      LK_CATALOG_PLEASE_ASK_STAFF_FOR_HELP_NOTHING_WAS_OPENED; TEXT key 5 STAFF (token 7),
 *      h LKUI_TEXT_H(LKUI_FONT_STAFF, 2) = 60, with the sentence of v->fault, in
 *      the order of LK_FAULT_*: RELAY_BUSY_A_RELAY_WAS_ALREADY_ON_SO_NOTHING_WAS (1), KIOSK_BUSY_ANOTHER_KIOSK_
 *      PROCESS_HOLDS_THE_RELAY (2), RELAY_LOCK_UNAVAILABLE_0 (3, one STR argument "" (len 0), L9),
 *      RELAY_SAFETY_STOP_A_RELAY_STAYED_ON_AND_WAS_FORC (4), RELAY_OFFLINE_THE_RELAY_BOARD_DID_NOT_ANSWER (5),
 *      RELAY_ERROR_THE_LOCKER_OPENER_FAILED (6), STORAGE_ERROR_THE_RESERVATION_BOOK_COULD_NOT_BE (7),
 *      CODES_UNAVAILABLE_THE_ALLOWED_CODE_LIST_COULD_NO (8), BOOK_REJECTED_THE_OPENING_WAS_NOT_RECORDED (9),
 *      LOCKER_MISSING_THAT_LOCKER_IS_NOT_IN_THE_INVENTO (10). No intent, no countdown, no language switch. 5 nodes.
 *      The column is bar 12 + title 60 + message 40 + detail 60 + 3 gaps = 220 tall, y0 = 290.
 *  LKS_WELCOME (RUST idle.slint)   left column COLUMN(24, 608, 16) + the numpad:
 *      TEXT key 3 HEADLINE LK_CATALOG_WELCOME; TEXT key 4 BODY_MUTED (token 5), h LKUI_TEXT_H(LKUI_FONT_BODY, 2) = 80,
 *      LK_CATALOG_SCAN_A_CODE_OR_ENTER_IT_ON_THE_PAD; LANG row; ECHO row: PANEL key 13, h 72, style NONE,
 *      msgid LK_CATALOG_DIGITS_ENTERED_0 with one argument [I18N_INT v->pad_len] (its accessible label, "Digits
 *      entered: 6"; a PANEL draws no text, so nothing of it is seen; X6, L1), with one child PANEL per typed digit
 *      (v->pad_len, 0..64):
 *      child i has key 128+i, style DOT, no text, size 16x16, parent ECHO. Each line of 25 dots is centred in
 *      the echo row (x 24, w 608): line r = i / 25 holds m = min(25, pad_len - 25 * r) dots, dot i is at
 *      x = 332 - 12 * m + 24 * (i % 25) (first dot at 24 + (608 - (24 * m - 8)) / 2; a full line starts at 32, a
 *      single dot is at 320), y = echo.y + 24 * r. The row itself does not depend on pad_len
 *      (the digits themselves are never in the scene, L1).
 *      NUMPAD: PANEL key 14 @648,24 608x752 style NONE, after the left column; its 12 children are SC_KEY nodes
 *      key 32+n (n = 0..11, row-major) at x = 664 + (n % 3) * 197, y = 40 + (n / 3) * 184, size 181x168, token 15,
 *      msgs/intents: n 0..8: digit n+1 (msg LK_CATALOG_N1..N9, intent DIGIT:digit); n 9: LK_CATALOG_DEL, intent
 *      BACKSPACE; n 10: digit 0 (LK_CATALOG_N0, intent DIGIT:0); n 11: LK_CATALOG_OK, intent SUBMIT. (RUST numpad.slint
 *      grid: 3 columns, 4 rows, spacing 16, padding 16.) No countdown. 20 + pad_len nodes. The left column is title
 *      60 + subtitle 80 + switch 48 + echo 72 + 3 gaps = 308 tall, y0 = 246.
 *  LKS_CHOOSE (RUST choose.slint)   top-down, not centred: x 24, w 1232, y starts at 24, gap 16:
 *      TEXT key 3 HEADLINE LK_CATALOG_CHOOSE_A_SIZE (h 60); LANG row (h 48); COUNTDOWN row (token 10, h 20);
 *      then the button row: y_row = the y after the last row above plus 16, height h_row = 800 - 24 - y_row
 *      (without the countdown y_row 164 and h_row 612; with it y_row 200 and h_row 576).
 *      Buttons, n = n_sizes + 1 of them side by side, each bw = (1232 - 16 * (n - 1)) / n wide (integer division),
 *      x_k = 24 + k * (bw + 16), height h_row, tokens 16 / 18 (font 32), or 17 / 19 (font 24) when
 *      n_sizes >= 5 (RUST wide-sizes).
 *      Size button k (k < n_sizes, array order): BUTTON key 48+k, label by sizes[k].size: 0 Small, 1 Medium, 2 Large,
 *      3 and above Extra large (L7). free > 0: msg LK_CATALOG_SMALL / MEDIUM / LARGE / EXTRA_LARGE, flags 0, intent
 *      CHOOSE:size. free == 0 ("Full"): msg LK_CATALOG_SMALL_FULL / MEDIUM_FULL / LARGE_FULL / EXTRA_LARGE_FULL, flags
 *      SC_DISABLED, intent 0. A size the inventory lacks is simply not in sizes[]: no node. The last button is
 *      Cancel: BUTTON key 17, LK_CATALOG_CANCEL, intent CANCEL:0, never disabled. All buttons are children of
 *      ROOT, in the order of the sizes, Cancel last (after the LANG row and the COUNTDOWN row). See COUNTS.
 *  LKS_OPENED (RUST opened.slint)   COLUMN(24, 1232, 8): [spacer 96 tall, no node, iff v->n_banners > 0 (RUST
 *      reserve-banner)]; NUMBER row: PANEL key 15 h 250, with nd (1..3) TEXT children key 64+i, token 1 (DISPLAY), msg
 *      LK_CATALOG_N<d> for the i-th decimal digit of v->locker (most significant first), rectangle (640 - 60*nd +
 *      120*i, row y, 120, 250); MESSAGE row: TEXT key 4 BODY (token 4),
 *      msg LK_CATALOG_YOUR_LOCKER_IS_0_REMEMBER_THE_NUMBER
 *      when v->first_time else LK_CATALOG_LOCKER_0_IS_OPEN, one INT argument v->locker; COUNTDOWN row (token 10);
 *      LANG row; DONE row: BUTTON key 16, h 56, token 16, LK_CATALOG_DONE, intent OPENED_DONE:0. See COUNTS.
 *  LKS_SHIFT (RUST shift.slint, inspection not live)   COLUMN(24, 1232, 8):
 *      TEXT key 3 STAFF_STRONG (token 8) LK_CATALOG_INSPECTED;
 *      TRACK row: PANEL key 18 h 12 style INFO, child PANEL key 19 style SUCCESS at the track's x,y, h 12, width
 *      fw = 0 when shift_total == 0, else min(shift_done, shift_total) * 1232 / shift_total (integer division, 32-bit);
 *      ABOUT; LICENSES; DONE row: BUTTON key 16, h 48, token 17, LK_CATALOG_DONE, intent SHIFT_DONE:0. No countdown.
 *      7 nodes.
 *  LKS_REPORT (RUST shift.slint, report live)   COLUMN(24, 1232, 8):
 *      TEXT key 3 TITLE (token 3) LK_CATALOG_END_OF_SHIFT;
 *      COUNTDOWN row (token 10); TEXT key 20 STAFF_STRONG LK_CATALOG_RELEASED_0 (INT report.released); TEXT key 21
 *      CAPTION LK_CATALOG_DOORS_OPENED_0 (INT report.ok); TEXT key 22 CAPTION
 *      LK_CATALOG_N0_UNCERTAIN_ENTRIES_ARE_BLOCKING_LOCKERS (INT report.faults); [TEXT key 23 CAPTION_ERROR (token 11),
 *      flags SC_WARN, LK_CATALOG_AUDIT_LOG_OR_RESERVATION_BOOK_A_WRITE_FAILED_DUR, iff report.write_failed]; ABOUT;
 *      LICENSES; DONE row as in SHIFT. See COUNTS. (L5, L8)
 *
 * ---- COUNTS (nodes, argument bytes; an INT argument is 9 bytes) ----------------------------------------------
 *  SPLASH 3/0; LOCKOUT 4/0, 5/9 with a countdown; FAULT 5/0 (fault 3: 5/3); WELCOME 20+pad_len/9 (84 at 64; the echo count, X6);
 *  CHOOSE 6+n_sizes (+1 with a countdown)/0 (+9); OPENED 7+nd (+1 with a countdown)/9 (+9), nd = decimal digits of
 *  the locker; SHIFT 7/0; REPORT 8 (+1 countdown, +1 warning)/27 (+9 with a countdown).
 *  LKUI_NODES_MAX 96, LKUI_ARGS_MAX 64 cover every valid view.
 *
 * ---- DISAGREEMENTS (where scene.h, vstate.h, ui-rules and the Rust Slint sources differ, and how each is pinned) --
 *  L1  RUST idle echo shows the typed digits (`entered`); VS D1 carries only pad_len. Pinned: one DOT marker per
 *      digit, never the digit. Each line of dots is centred in the echo row (ui-look 4.3, O7, C5).
 *  L2  RUST shows a version line (`version-line`, "Lockers {0}") on splash and shift/report; lk_view_t has no
 *      version stamp. Pinned: omitted. Likewise RUST "Ended {0}:{1} UTC" on the report: the view has no end time.
 *  L3  RUST sizes come from layout stretch and text metrics; the scene needs fixed rectangles. Pinned: the
 *      formulas above (LKUI_LINE, columns, equal-width buttons). Wrapping is not modelled either, but every text rect
 *      is tall enough for the worst case in both languages (O11, "Text rects" above): the renderer wraps inside it.
 *  L4  scene.h has no colour or fill: RUST fills (primary-container, secondary-container for Cancel, surface-
 *      container-high for a full size button, error/tertiary bars) become the PANEL tones and flags above only;
 *      Cancel has no distinct fill. The renderer chooses fills from role and flags.
 *  L5  RUST report has three columns with the inspected and blocked line lists, counters doors-opened, rejected,
 *      lockouts, relay-down, app-starts; VS D4 gives LKS_SHIFT done/total and LKS_REPORT four numbers. Pinned: one
 *      column; done/total is a progress track; released -> "Released", ok -> "Doors opened", faults -> "uncertain
 *      entries are blocking lockers" (the catalog has no phrase for a bare count or for "done of total");
 *      write_failed -> the write warning (RUST warning-text).
 *  L6  lk_view_t carries a language on every screen; RUST shows the BG | EN switch on welcome, choose and opened only.
 *      Pinned: the switch exists on those three screens only; elsewhere the language is ignored.
 *  L7  RUST names size buttons from the inventory (`raw`) beyond slot 3; lk_vsize_t has only the id, and the
 *      catalog has no phrase for sizes 4 and 5. Pinned: they show the Extra large labels (a follow-up catalog gap).
 *  L8  Countdown seconds: RUST receives an int; ui-look K5 settles it. Pinned: round down, ms / 1000.
 *  L9  RUST fault screen detail "Relay lock unavailable: {0}" has a reason string; VS D2 drops it. Pinned: an empty
 *      STR argument. The door state of RUST fault-visitor is not in the view: the fault screens always say
 *      "Nothing was opened".
 *  L10 The locker number needs a bare "{0}" phrase that the catalog lacks. Pinned: one digit glyph node per digit
 *      (catalog ids N0..N9).
 *  L11 scene.h makes `style` app-defined; here it is the STYLE token of ui-look 4.2 (text, button) or the tone
 *      (panel), above. C12: the welcome subtitle is muted (token 5).
 *  L12 No Rust test is staged (only the .slint sources), so no Rust test is ported; the tests are written from the
 *      Slint sources, vstate.h and this header. ui-rules and scene.h agree with this module: the lockout and the faults carry no touch node, opened and
 *      choose carry their Done / Cancel, and a message is never built here.
 *
 * ---- Version 2: lkui_build2 (F10/F11 step 3; ui-look 10.1) -----------------------------------------------------
 *   bool lkui_build2(const lk_view2_t *w, scene_t *s);
 * Added ALONGSIDE lkui_build so a user moves to lkrx/vstate2 one module at a time; lkui_build and everything above are
 * unchanged. Reuse note: used by lkapp/runtime once it moves to lk_view2_select. Same rules as B1-B4 with lk_view2_t:
 *  V1  w NULL, s NULL, or s uninitialised                                -> false, nothing written, no crash.
 *  V2  lk_view2_check(w) != LK_VS_OK                                     -> false, the scene byte for byte unchanged.
 *  V3  Screens other than SPLASH, SHIFT and REPORT: exactly what lkui_build(&w->v1, s) writes (nodes, argument bytes,
 *      return value). The version and report2 are not read there.
 *  V4  OVERFLOW as B4. Storage of LKUI2_NODES_MAX nodes and LKUI2_ARGS_MAX argument bytes always suffices.
 *  VERSION row: TEXT key LKUI_K2_VERSION 24, token 10 (CAPTION_MUTED), h 20, msg LK_CATALOG_LOCKERS_0 ("Lockers {0}"),
 *    one STR argument: the decimal version_major "." version_minor "." version_patch, no padding ("1.0.0"; at most
 *    "255.255.255", 11 bytes). RUST status.slint / shift.slint `version-line`.
 *  LKS_SPLASH   COLUMN(24, 1232, 16): TEXT key 3 HEADLINE LK_CATALOG_LOCKERS; VERSION row; ABOUT. 4 nodes. (RUST
 *      status.slint mode 0: title, version line, badge.)
 *  LKS_SHIFT    the column of lkui_build with the VERSION row added after the DONE row: COLUMN(24, 1232, 8) over
 *      title, track, ABOUT, LICENSES, DONE and VERSION. 8 nodes.
 *  LKS_REPORT   (ui-look 10.1; O14 reading A: three columns of 400, 16 apart, at x 24, 440, 856)
 *      Column 1, top-down from y 24, 8 between rows, every row 400 wide at x 24, children of ROOT:
 *        TEXT key 3 TITLE (token 3, h 50) LK_CATALOG_END_OF_SHIFT;
 *        COUNTDOWN row (token 10, h 20) as in lkui_build;
 *        TEXT key LKUI_K2_ENDED 25 CAPTION (token 9, h 20) LK_CATALOG_ENDED_0_1_UTC, two STR arguments: report2.
 *          ended_hour and ended_minute as two zero-padded digits each ("07", "05") when has_ended; "00", "00" when
 *          not (the hour and minute are then ignored, VS2 W3; RUST formats ended_at 0 the same). Shown always;
 *        TEXT key 20 STAFF_STRONG (token 8, h 30) LK_CATALOG_RELEASED_0 (INT v1.report.released);
 *        TEXT key 21 CAPTION (h 20) LK_CATALOG_DOORS_OPENED_0 (INT report2.doors_opened);
 *        TEXT key LKUI_K2_REJECTED 26 CAPTION (h 20) LK_CATALOG_REJECTED_CODES_0 (INT report2.rejected_codes);
 *        TEXT key LKUI_K2_LOCKOUTS 27 CAPTION (h 20) LK_CATALOG_LOCKOUTS_0 (INT report2.lockouts);
 *        TEXT key LKUI_K2_RELAY_DOWN 28 CAPTION (h 20) LK_CATALOG_RELAY_DOWN_0 (INT report2.relay_down);
 *        TEXT key LKUI_K2_APP_STARTS 29 CAPTION (h 20) LK_CATALOG_APP_STARTS_0 (INT report2.app_starts);
 *        [TEXT key 23 CAPTION_ERROR (token 11), flags SC_WARN, h LKUI_TEXT_H(16, 2) = 40 (64 characters at 16 dp
 *          in 400: 2 lines), LK_CATALOG_AUDIT_LOG_OR_RESERVATION_BOOK_A_WRITE_FAILED_DUR, iff v1.report.write_failed].
 *        The v1 FAULTS row ("N uncertain entries are blocking lockers") has no RUST counterpart and is not written
 *        (C13); v1.report.ok and v1.report.faults are not read.
 *      Column 2 (x 440): PANEL key LKUI_K2_BAR_INSPECTED 30, h 12, tone INFO, at y 24; TEXT key
 *        LKUI_K2_INSPECTED 31 STAFF_STRONG (token 8, h 30) LK_CATALOG_INSPECTED at y 44.
 *      Column 3 (x 856): PANEL key LKUI_K2_BAR_BLOCKED 192, h 12, tone ERROR, at y 24; TEXT key LKUI_K2_BLOCKED 193
 *        STAFF_STRONG (h 30) LK_CATALOG_BLOCKED at y 44; LICENSES: TEXT key 8 token 10 at x 864, w 384, h 20,
 *        y 539 (RUST: column height 665 minus 150, 8 in from each side; the badge is dropped, O10).
 *      The Inspected and Blocked line lists of 10.2 (report2.inspected) are NOT written by this version: they need
 *        the scroll list of K6 (C15-C17), a later version. report2.n_inspected and inspected[] are not read.
 *      DONE: BUTTON key 16 at (24, 705, 1232, 48), token 17, LK_CATALOG_DONE, intent SHIFT_DONE:0.
 *      VERSION row at (24, 761, 1232, 20).
 *      Order: ROOT, column 1, column 2, column 3, DONE, VERSION. 16 nodes (+1 countdown, +1 warning).
 *  COUNTS (v2): SPLASH 4/14 at most; SHIFT 8/14; REPORT 16 (+1, +1)/ 2 x 5 (ended) + 6 x 9 (released and the five
 *    counters) + 14 (version) = 78 (+9 with a countdown) = 87 at most. LKUI2_NODES_MAX 96, LKUI2_ARGS_MAX 128.
 *  L2 and L5 above stay true of lkui_build; lkui_build2 resolves them for the version line, the end time and the
 *  counters (VS2 W1-W7), and L5's lists stay open until the scroll list exists.
 */
#ifndef LKUI_SCREENS_H
#define LKUI_SCREENS_H

#include <stdbool.h>
#include <stdint.h>

#include "apps/lockers/lkc/uikeys/uikeys.h"
#include "apps/lockers/lkrx/vstate/vstate.h"
#include "apps/lockers/lkrx/vstate2/vstate2.h"
#include "lib/ui/scene/scene.h"

#define LKUI_W 1280
#define LKUI_H 800
#define LKUI_UNIT 8
#define LKUI_TOUCH 48
#define LKUI_THUMB 88
#define LKUI_RADIUS 28
#define LKUI_RADIUS_KEY 16
#define LKUI_BAR 12
#define LKUI_PAD 24
#define LKUI_GAP 16
#define LKUI_FONT_DISPLAY 200
#define LKUI_FONT_HEADLINE 48
#define LKUI_FONT_TITLE 40
#define LKUI_FONT_BODY 32
#define LKUI_FONT_STAFF 24
#define LKUI_FONT_CAPTION 16
#define LKUI_FONT_MIN LKUI_FONT_CAPTION
#define LKUI_LINE(f) ((f) + (f) / 4)
/* The height of a text rect of `lines` lines of font f. */
#define LKUI_TEXT_H(f, lines) ((lines) * LKUI_LINE(f))

#define LKUI_NODES_MAX 96
#define LKUI_ARGS_MAX 64

/* STYLE tokens of ui-look 4.2 for TEXT, COUNTDOWN, BUTTON and KEY nodes. 12..14 are lkui/notices'. */
enum { LKUI_ST_DISPLAY = 1, LKUI_ST_HEADLINE = 2, LKUI_ST_TITLE = 3, LKUI_ST_BODY = 4, LKUI_ST_BODY_MUTED = 5,
       LKUI_ST_COUNT_LARGE = 6, LKUI_ST_STAFF = 7, LKUI_ST_STAFF_STRONG = 8, LKUI_ST_CAPTION = 9,
       LKUI_ST_CAPTION_MUTED = 10, LKUI_ST_CAPTION_ERROR = 11, LKUI_ST_NOTICE_TITLE = 12, LKUI_ST_NOTICE_BODY = 13,
       LKUI_ST_NOTICE_CAPTION = 14, LKUI_ST_BTN_KEY = 15, LKUI_ST_BTN_ACTION = 16, LKUI_ST_BTN_ACTION_SMALL = 17,
       LKUI_ST_BTN_CANCEL = 18, LKUI_ST_BTN_CANCEL_SMALL = 19, LKUI_ST_BTN_LANG_ON = 20, LKUI_ST_BTN_LANG_OFF = 21 };

enum { LKUI_TONE_NONE, LKUI_TONE_INFO, LKUI_TONE_SUCCESS, LKUI_TONE_ERROR, LKUI_TONE_WARNING, LKUI_TONE_SELECTED,
       LKUI_TONE_ATTRIBUTION, LKUI_TONE_DOT };

/* LKUI_KEY_LIMIT, the intent ids LKUI_I_* and the node keys LKUI_K_* are the contract lkc/uikeys (P007 C4). */

/* See B1-B4. */
bool lkui_build(const lk_view_t *v, scene_t *s);

/* Version 2 (V1-V4 above). Keys of the new nodes, below LKUI_KEY_LIMIT and in ranges lkc/uikeys leaves free. */
enum { LKUI_K2_VERSION = 24, LKUI_K2_ENDED, LKUI_K2_REJECTED, LKUI_K2_LOCKOUTS, LKUI_K2_RELAY_DOWN, LKUI_K2_APP_STARTS,
       LKUI_K2_BAR_INSPECTED, LKUI_K2_INSPECTED, LKUI_K2_BAR_BLOCKED = 192, LKUI_K2_BLOCKED };
#define LKUI2_NODES_MAX 96
#define LKUI2_ARGS_MAX 128
bool lkui_build2(const lk_view2_t *w, scene_t *s);

#endif
