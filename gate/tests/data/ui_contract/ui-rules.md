# Lockers UI rules

Deterministic rules for every kiosk message. AGENTS.md §4 is the short form. This file is the catalogue the guard and the viewmodel follow.

A **message** is copy the visitor or staff must read about an outcome, a warning, or a transient fact. It is never a screen. A **screen** is one of the full-window states listed below. `ViewState` is a screen plus an optional notice, and banners are a list. A full-screen message cannot be represented.

## Presentation

| Kind | When | Overlay | Dismiss |
|---|---|---|---|
| **Dialog** | The visitor must acknowledge an outcome before continuing. | Card over the current screen, with a scrim. The screen stays visible around the card. | A **Dismiss** button of at least 48 dp. The scrim does **not** dismiss: a stray tap must not skip an acknowledgement. |
| **Banner** | A persistent, non-blocking staff line. A failing check uses the warning tone. An OK self-test does not. | Strip over the current screen. The screen stays usable. | **Dismiss** on that strip. A tap outside the strip dismisses a notice of kind banner, but not a banner of the persistent set (see the clarification below). |
| **Snackbar** | Transient information. | Small card over the current screen. | **Dismiss**, a tap outside the card, and the countdown when one is set. |

Every notice carries a dismiss intent. Dismissing clears that notice. For a dialog that replaced an old full-screen message, the screen underneath is already the screen the visitor returns to (the pad, or the opened locker). An auto-timeout, when one remains, is a countdown on the notice. The same countdown is what the UI shows. When it reaches zero the notice clears, the same as a dismiss.

Input behind a **dialog** does nothing until the dialog is gone. Banners and snackbars do not block the pad, except that a tap outside a snackbar, or outside a notice of kind banner, dismisses it (a banner of the persistent set has no tap-outside area). Lockout is a screen and ignores input for its whole countdown.

The only Slint component that shows a message is `Notice` in `ui/kit`. `ui/lockers` passes message text into that component and does not paint it anywhere else.

## Allowed full-screen states

These are screens, not messages:

- Boot splash (kiosk name, version, Slint attribution). It is not dismissible. It leaves when boot finishes.
- Welcome / code pad.
- Choose a size.
- Opened (the locker number).
- Staff end-of-shift, including its report.
- Lockout ("Please wait").
- Fatal startup faults: the reservation book could not be loaded, and the relay board did not answer at boot. They are not visitor-dismissible. The boot relay fault leaves when the board answers. The storage fault stays, because an empty book must not be written.

## Screen timers

Visible countdown, and a dismiss control, except where a screen is specified to ignore input.

| Screen or notice | Limit | What the visitor sees | Dismiss |
|---|---|---|---|
| Choose a size | 30 s | Countdown on the choice screen. Nothing is reserved. | **Cancel**, or the countdown. |
| Opened | 8 s | Countdown on the opened screen. | **Done**, or the countdown. Returns to the pad. |
| Rejection, no-locker, and operational fault dialogs | 8 s | Countdown on the dialog. | **Dismiss**, or the countdown. The pad is already behind the dialog. |
| End-of-shift report | 5 min | Countdown on the report. | **Done**, or the countdown. |
| Lockout | 60 s | Countdown on the wait screen. | None. The pad and the scanner do nothing until the countdown ends. |
| Reservation saved snackbar | 4 s | Countdown on the snackbar. | **Dismiss**, tap outside, or the countdown. The pad stays usable. |

## Message catalogue

Visitor sentences stay the sentences the spec already uses. Staff sentences stay staff sentences. Only the presentation changes.

| Message | Kind | Underneath | Dismiss intent | Countdown |
|---|---|---|---|---|
| Code not accepted — "That code is not valid." (empty, not all digits, longer than 64, or 1 to 5 digits) | Dialog | Pad | Clear the dialog | 8 s |
| Code not accepted — "That code is not recognised." | Dialog | Pad | Clear the dialog | 8 s |
| Codes unavailable — "The code list is unavailable. Try again shortly." | Dialog | Pad | Clear the dialog | 8 s |
| No locker free — "Every locker is in use. Please ask the staff." | Dialog | Pad | Clear the dialog | 8 s |
| Operational fault, nothing opened — "Please ask staff for help. Nothing was opened." plus the staff cause (relay busy, kiosk busy, lock unavailable, safety stop, relay offline, relay error, storage, codes, book rejected, locker missing) | Dialog | Pad | Clear the dialog | 8 s |
| Operational fault, outcome unknown — "Please ask staff for help. A door may have opened." plus the staff cause and locker | Dialog | Pad | Clear the dialog | 8 s |
| Operational fault after a door opened and a later save failed in a context that is not the opened screen — "Please ask staff for help. A door was opened." | Dialog | Pad | Clear the dialog | 8 s |
| Not saved — "Not saved: the door opened, and the reservation was not saved." | Banner | Opened | Clear that banner. The locker number stays. | None |
| Audit log — "Audit log: an event could not be written." | Banner | Whatever screen is up | Clear that banner | None |
| Codes offline — "Codes offline: using the list saved at HH:MM". This is the one banner for a list served from disk, including when the refresh is also failing. | Banner | Whatever screen is up | Clear that banner | None |
| Codes stale — "Codes: the allowed-code list could not be refreshed." Only when the kiosk is not already showing the saved-list banner. The two sentences are one condition. | Banner | Whatever screen is up | Clear that banner | None |
| Sync behind — the uploader's staff sentence | Banner | Whatever screen is up | Clear that banner | None |
| Reservation saved — "Reservation saved." Shown after a not-saved open is saved while that outcome is still on screen. | Snackbar | The opened locker, or the pad if the opened screen has already timed out | Clear the snackbar | 4 s |
| Self-test failed — one sentence per failing check (`relay=fail` and the rest: board not reachable, a relay still on, codes, disk, book, clock, sync). Warning tone. | Banner | Welcome, once the splash has left. Hidden on the splash, the report, and the startup-fault screens. | Clear that banner. The next self-test shows it again. | None |
| Self-test OK — "Self-test OK". Not the warning tone. | Banner | Welcome, once the splash has left | Clear that banner. The next self-test shows it again. | None |
| End-of-shift write warning on the report ("Audit log or reservation book: a write failed during this shift.") | Part of the report screen, not a notice | The report | **Done** leaves the report | 5 min on the report |

Fatal startup faults use the same visitor and staff sentences as a relay-offline or storage fault, but they are the startup-fault **screen**, not a dialog. A relay fault later in a visit is a dialog. A storage fault later in a visit is a dialog.

**Rust-derived clarification (banner tap-outside).** The Banner row above says a banner is dismissed by its Dismiss button and by a tap outside the strip. In the Rust kiosk (`BannerHost`, `overlay: false`) that holds only for a *notice of kind banner* (shown through the dialog host, with a full-window scrim). A banner of the persistent *set* (not saved, audit, sync, codes offline, codes stale, self-test) is just its card: it has **no tap-outside area**, its scrim equals its card rectangle, and the screen behind it stays fully usable. Its Dismiss button is the one way to clear it. The rule that every message has a visible dismiss control is unchanged. (Header note N1 of `apps/lockers/lkui/notices/notices.h`; Rust wins, D8.)

Several banners can be visible together. Each has its own Dismiss. A dialog, when present, sits above them and blocks input until it is dismissed.
