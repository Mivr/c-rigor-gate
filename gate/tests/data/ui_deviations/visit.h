/* apps/lockers/lkrx/visit/visit.h: the visit saga of the lockers kiosk (DESIGN 4.1 row lkrx/visit, 4.3, 4.4; catalog R7, R10).
 * Level L3. Included as "apps/lockers/lkrx/visit/visit.h". Deps: ev, rxwire (rx_emit_t), lk/book, lk/code, lk/inventory,
 * lk/outcome, lk/types, lkrx/catalog, lkrx/fold_core (lk_session_t, lk_book_slice_t, lk_clock_t, lk_inventory_slice_t),
 * lkrx/fold_status (lk_relay_slice_t, lk_health_slice_t), core. Pure: it reads six slices, never writes them, emits through
 * rx_emit, allocates nothing, owns no mutable data, no recursion; every loop is bounded (the book scan is at most LK_BOOK_CAP
 * entries). Used by lkapp/wire (the reactor table, LK_RX_VISIT) and nobody else.
 * RS = viewmodel/lockers lib.rs (the oracle, D8: Rust wins over the docs), cited by line; RS:<name> = a Rust test of that file;
 * RSA = audit_tests.rs; CAT = catalog.h, FC = fold_core.h, FS = fold_status.h.
 *
 * void lk_react_visit(const void *const *slices, const ev_t *e, rx_emit_t *out);
 *
 * ---- Wiring (catalog row, pinned) -------------------------------------------------------------------------------
 * Inputs size_chosen, cancel, tick, code_recognised, book_saved, book_save_failed, open_result. Reads, in this order:
 *   slices[0] session (lk_session_t, incl. was_pending)           slices[1] book (lk_book_slice_t)         slices[2] inventory (lk_inventory_slice_t)
 *   slices[3] relay (lk_relay_slice_t)         slices[4] clock (lk_clock_t)             slices[5] health (lk_health_slice_t)
 * Emits visit_staged, visit_committed, visit_rolled_back, cmd_book_save, cmd_open, locker_assigned, door_opened, open_failed,
 * not_saved, no_locker_free, reservation_saved. max_emit 6; the most one call emits is 4 (V14). The reactor runs AFTER the folds
 * of the same event (rx), so every slice already includes the input: FC moved the phase on code_recognised, book_saved,
 * open_result ... before this code looks at it. That is why some rules read the phase the FOLD left behind (named in each rule).
 *
 * ---- Words ------------------------------------------------------------------------------------------------------
 * now      clock.wall_ms (the last tick's wall clock; the clock the book rules use: FC "book.now_ms"). The tick payload and the
 *          input's h.mono_ms are never read.
 * mono     clock.mono_ms; every emitted event gets h.mono_ms = mono (FS "contract for producers").
 * entry    a reservation of the book slice (lk_book_get / lk_book_active).
 * staged   the entry the fold wrote for this visit: pending == 1 and locker == session.locker (the first such entry in insertion
 *          order). FC clears session.code and keeps session.locker / session.first_time from visit_staged on.
 * CORR     LK_VISIT_CORR(first_time, locker) below. Every cmd_book_save and cmd_open of this reactor carries it as payload corr.
 *          The driver echoes it in open_result, and open_result has no locker, so it is how this reactor learns the locker and
 *          the context (new or return) of a result AFTER the fold has cleared the session (FC: open_result with a fault -> IDLE
 *          and clears locker/first_time). cmd_book_save(POST) of a tick retry carries LK_VISIT_CORR(0, 0).
 *
 * ---- Rules ------------------------------------------------------------------------------------------------------
 * V1  Nothing is emitted and nothing written (not even an overflow mark) when: slices or e is NULL; any of the six slices[i] is
 *     NULL (health is only checked, never read: V13); the event type is not one of the seven inputs; its h.ver is not 1 or ev_get
 *     refuses it; or a rule below says "nothing". A NULL out is handled by rx_emit (no check here); out->ev must be
 *     valid for out->cap events. Emission goes through rx_emit one event at a time, in the order the rules list; when out is full
 *     rx_emit sets out->n = cap + 1 and the remaining events are lost (RX_F_EMIT_OVERFLOW upstream).
 * V2  Built events: ev_put from LK_EV_TYPES (type, ver 1, payload zero-filled beyond its size), then h.mono_ms = mono and
 *     flags = corr = seq = 0 (the envelope corr is not used; the payload corr is, V3). All audit events (locker_assigned,
 *     door_opened, open_failed, not_saved) are lk_ev_audit_t with every byte 0 except what V9 names: code_hash is NEVER set (the
 *     visit reactor has no salt; RS records these kinds with code_hash None, lib.rs 966-1056) and the has bit CODE_HASH is 0.
 * V3  CORR = LK_VISIT_CORR_TAG | (first_time != 0) << 16 | locker, LK_VISIT_CORR_TAG = 0x56000000. open_result is acted on only if
 *     (corr & 0xFF000000) == LK_VISIT_CORR_TAG (other results belong to lkrx/shift) and the book holds a STAGED entry for
 *     locker = corr & 0xFFFF; first_time = bit 16. book_saved / book_save_failed corr is NOT inspected (the phase decides, V7, V8).
 *
 * code_recognised{code, role}  (RS visitor 929-940, offer 942-955, reopen 957-964)
 * V4  Only role LK_ROLE_VISITOR in phase LK_PHASE_CHOOSE with session.code equal (33 bytes) to the payload code and a
 *     well-formed code (lk_bcd_wellformed); FC has just moved IDLE -> CHOOSE and stored the code. Staff, another phase or another code:
 *     nothing. Then, the first row that applies decides:
 *       a. relay.state == LK_RLY_DOWN: REFUSE (V12): emit open_failed (1 event). UNKNOWN and UP do not refuse.
 *       b. lk_book_active(book, code, now) finds an entry (a RETURNING visit: the code holds a locker): STAGE it (V5), without a
 *          size choice (RS reopen): emit visit_staged, cmd_book_save(PRE).
 *       c. a NEW visit: lk_book_availability(book, inv, now) gives k flags. When k == 0 or every flag is false (RS every_size_full:
 *          `iter().all(!enabled)` is true for an empty list; lk/book says "n >= 1": Rust wins) emit no_locker_free (FC: CHOOSE ->
 *          NO_LOCKER). Otherwise NOTHING is emitted: the choose screen is FC's own state (CHOOSE, 30 s) and the sizes offered are
 *          the availability flags that lkrx/view derives.
 * V5  STAGE (returning): entry = the active entry. entry.openings == UINT32_MAX: nothing (it cannot be counted; the visitor waits
 *     for the CHOOSE timeout). Else visit_staged{first_scan_ms = entry.first_scan_ms, openings = entry.openings + 1, locker =
 *     entry.locker, undo = {code, was_pending = entry.pending}} then cmd_book_save{CORR(0, entry.locker), phase LK_SAVE_PRE}.
 *     FC makes openings >= 2 a lk_book_stage_reopen (pending = 1, openings + 1) and the session OPENING/SAVE with first_time 0.
 *
 * size_chosen{size}  (RS choose_size 758-771)
 * V6  Only in phase LK_PHASE_CHOOSE (RS pending_choice: anywhere else the tap does nothing, RS:choose_size_outside_that_screen_
 *     does_nothing) with a well-formed session.code; the code is session.code, first_scan_ms is session.first_scan_ms (FC: the last
 *     tick's wall_ms at the recognition = RS first_seen). The first row that applies decides:
 *       a. relay DOWN: REFUSE (V12), 1 event, as V4a.
 *       b. lk_book_active(book, session.code, now) finds an entry (a returning visitor whose staging V4a refused; RS has no such
 *          state): STAGE it as V5, the size is ignored. This keeps the book fold from refusing a new reservation for an active code
 *          (stage_new E_CODE_STILL_ACTIVE) while the session would move on.
 *       c. size >= inventory.n_sizes, or lk_book_assign(book, inv, size, now) finds no free locker of that size: NOTHING (RS:
 *          new_visitor_gets_the_lowest_small_locker..., 2626: tapping a size with no free locker leaves the choose screen).
 *          DISAGREES with the task text "no free locker of that size -> no_locker_free": Rust wins; the all-sizes-full case is V4c.
 *       d. otherwise STAGE NEW, the PICK RULE being lk_book_assign (RS lowest_free: the free locker of that size with the lowest
 *          id, inventory file order breaks nothing: ids are unique): emit visit_staged{first_scan_ms = session.first_scan_ms,
 *          openings = 1, locker = the pick, undo = {session.code, was_pending 0}}, cmd_book_save{CORR(1, pick), LK_SAVE_PRE}.
 *          (2 events.) FC: lk_book_stage_new, session OPENING/SAVE, first_time 1.
 *     locker_assigned is NOT emitted here (V7): RS records it only after the pre-save succeeded (lib.rs 966-1000;
 *     RSA a_save_that_fails_before_the_pulse_does_not_assign_a_locker). DESIGN 4.4 and the task text say size_chosen: Rust wins.
 *
 * book_saved{corr}  (RS open_intended 966-1056, retry_save 1148-1162)
 * V7  FC has just moved OPENING/SAVE -> OPENING/PULSE for the pre-save. When session.p.ph == LK_PHASE_OPENING and p.sub ==
 *     LK_OP_PULSE (ONLY then: after the cmd_open below FC moves the session to OPENING/WAIT, so a second, stale book_saved finds WAIT
 *     (or COMMIT) and emits NOTHING; exactly one cmd_open per visit, GAP-V2 closed, L216): staged = the entry for session.locker; none: NOTHING
 *     (never open a door that is not in the book: save BEFORE
 *     pulse is the invariant). Else, with cell = lk_inv_cell(inventory, session.locker):
 *       - found: [locker_assigned only if session.first_time] then cmd_open{CORR(first_time, locker), locker, pulse_units
 *         LK_VISIT_PULSE_UNITS (5, the default 500 ms: RELAY_PULSE_DEFAULT_UNITS), cell}. (1 or 2 events.) cmd_open is NEVER
 *         emitted before the pre-save's book_saved, by any rule.
 *       - not found (RS pulse() 1165: LockerMissing, flash_sent false, RSA 660-720 "missing"): [locker_assigned if first_time], then
 *         the ROLLBACK of V9 with fault LK_FAULT_LOCKER_MISSING and flash false: open_failed, visit_rolled_back,
 *         cmd_book_save(ROLLBACK). No cmd_open. (up to 4 events.)
 *     When session.p.ph == LK_PHASE_OPENED and session.not_saved != 0 (a retried save succeeded while the opened screen shows
 *     "not saved"): emit reservation_saved (FC clears not_saved, FS raises the 4 s snackbar; RS retry_save only touches Opened).
 *     Every other phase (the first post-save of a visit: OPENED with not_saved 0; a retry that succeeded after the screen
 *     left OPENED, RS retry_save shows no snackbar then): nothing.
 *
 * book_save_failed{corr, errno_class}  (RS persist 1124, open_intended 1034-1052)
 * V8  In phase OPENING with p.sub == LK_OP_SAVE (the pre-save failed; FC does not move the phase on a failure): staged = the entry
 *     for session.locker; none: nothing. Else ROLLBACK without a re-save: emit open_failed{locker, fault LK_FAULT_STORAGE_ERROR,
 *     door nothing} then visit_rolled_back{undo = {staged.code, 0}} (2 events; RS persist -> show_fault(StorageError,
 *     NothingOpened), no pulse, no locker_assigned). The in-memory book is rolled back by FC; the next tick retries the save (V10).
 *     In phase LK_PHASE_OPENED with session.not_saved == 0 (the post-save after the door opened failed): emit not_saved{locker =
 *     session.locker} (1 event; RS records NotSaved, FC GAP-7: it follows visit_committed and FC sets not_saved = 1).
 *     OPENED with not_saved already 1 (a retry failed again), and every other phase: nothing.
 *
 * open_result{corr, fault, flash_sent, ...}  (RS open_intended 1000-1056, door_after 1403, fault_kind 1431; lk/outcome)
 * V9  Acted on only per V3 (tag and a staged entry for the locker of corr). fault = payload.fault, a value above LK_FAULT_KINDS is
 *     taken as LK_FAULT_RELAY_ERROR. o = lk_outcome(fault, flash_sent != 0, first_time ? CTX_NEW : CTX_RETURN). The rows:
 *       fault 0 (o.book COMMIT): visit_committed{locker}, door_opened{has LOCKER, locker}, cmd_book_save{CORR(first_time, locker),
 *            LK_SAVE_POST}. (3 events, in this order; the door is open: the commit comes before the post-save, RS 1018-1031.)
 *       fault != 0, o.book ROLLBACK (a pulse kind with flash_sent false): open_failed, visit_rolled_back{undo = {staged.code, 0}},
 *            cmd_book_save{.., LK_SAVE_ROLLBACK}. (3 events; RS 1000-1017: audit, rollback_pending, save_book.)
 *       fault != 0, o.book KEEP_PENDING (flash_sent true, or an outside kind): open_failed only (1 event): the entry stays pending
 *            (uncertain), no save, no rollback; the end-of-shift opens it later (RS a_sent_pulse_stays_uncertain...).
 *     open_failed is lk_ev_audit_t{has = LOCKER | FAULT (| REASON when o.door == LK_OUTCOME_DOOR_MAYBE_OPENED), locker, fault,
 *     reason = LK_AUDIT_REASON_MAYBE_OPENED (4) iff maybe opened}. FS raises the fault dialog from it (door MAYBE_OPENED names the
 *     locker). For outcome rows with audit NONE (storage, book-rejected, codes-unavailable kinds) RS writes no audit line; C still emits
 *     open_failed, because it is the only event that raises the dialog (a disagreement, DISAGREE-3).
 *     undo.was_pending (GAP-V1 closed, L216): EVERY visit_rolled_back of this reactor (V8, V9 and the missing locker of V7) carries
 *     undo = {code, was_pending = session.was_pending}, the pending flag the entry had before the staging (FC copies it from
 *     visit_staged.undo.was_pending, V5, and keeps it across the IDLE an open_result with a fault leads to, so the reactor can read it after
 *     the fold). 1 only for a returning visit of an entry that was already uncertain: the book rollback then gives back openings - 1
 *     AND pending = 1 (RS failed_reopen_of_an_uncertain_entry_stays_pending, 3593). A new visit stages with 0, whose rollback removes the
 *     entry anyway.
 *
 * tick  (RS tick 800 + retry_save 1148)
 * V10 When book.save_failed != 0 and session.p.ph is not OPENING, SHIFT or REPORT (a save is in flight during OPENING; lkrx/shift owns
 *     the saves of SHIFT/REPORT): emit cmd_book_save{LK_VISIT_CORR(0, 0), LK_SAVE_POST}, on EVERY tick (RS retry on every tick, until
 *     book_saved clears save_failed). Otherwise nothing. The retry is not limited to the opened screen: RS needs_save outlives it
 *     (RS:post_save_failure_shows_the_number_and_tick_retries_until_saved 3620). After a pre-save failure V8 left save_failed = 1,
 *     so C also retries then (RS does not; the retried book is the rolled-back one, harmless).
 *
 * cancel  (RS cancel 773)
 * V11 Nothing, in every phase. In CHOOSE nothing is staged (staging moves the phase to OPENING in the same instant as size_chosen),
 *     so there is nothing to roll back: FC alone moves CHOOSE -> IDLE. In OPENING cancel is ignored by FC and here (RS: only CHOOSE).
 *
 * ---- Refusals, gates, fixed values ------------------------------------------------------------------------------
 * V12 REFUSE (relay DOWN): open_failed{has = FAULT, fault LK_FAULT_RELAY_OFFLINE, locker 0, reason 0}; nothing is staged, saved or
 *     pulsed. FS shows the fault dialog over the CHOOSE screen (door nothing); the session stays in CHOOSE until cancel or its
 *     30 s deadline. RS has no per-visit relay gate (hold_for_relay 654 is a boot screen, the pad is dead then); this is its C
 *     equivalent, and RS writes no audit line for a refusal (DISAGREE-3).
 * V13 health is read by nobody: RS audit_failed / book_write_failed only raise banners (lib.rs 293-306, 1134-1146) and gate
 *     nothing. Only the relay gate (V12) exists.
 * V14 Emit counts: new stage 2, returning stage 2, refusal 1, no_locker_free 1, book_saved pulse 1..2 (3..4 when the locker is
 *     missing), commit 3, rollback 3, keep pending 1, not_saved 1, pre-save failure 2, reservation_saved 1, retry 1. At most 4.
 *
 * ---- Disagreements with the docs and the task text (D8: Rust wins) and gaps -----------------------------------------
 * DISAGREE-1 locker_assigned is emitted with cmd_open after the pre-save (V6), not at size_chosen (DESIGN 4.4).
 * DISAGREE-2 a size with no free locker emits nothing (V6c), not no_locker_free; lk/book's "every flag false and n >= 1" is
 *            RS's "all not enabled", empty included (V4c).
 * DISAGREE-3 open_failed is emitted for the refusal (V12), the pre-save failure (V8) and the audit-NONE rows (V9) although RS
 *            writes no audit line there: it is the dialog's only carrier.
 * DISAGREE-4 RS forgets nothing on a failed rollback save (the pending entry stays in memory too, RS:pulse_failure_whose_rollback_
 *            cannot_be_saved_keeps_the_pending_entry); C rolls the memory back and retries the save on every tick (V10).
 * GAP-V1     (CLOSED, L216: V9, FC session.was_pending, CAT R18) undo.was_pending of every rollback was 0.
 * GAP-V2     (CLOSED, L216: V7, FC LK_OP_WAIT, CAT R18) a stale second pre-save book_saved while OPENING/PULSE emitted a second cmd_open.
 * GAP-V3     the audit events carry no code_hash (V2); lkapp must add the fingerprint if D1 needs it.
 */
#ifndef LKRX_VISIT_H
#define LKRX_VISIT_H

#include <stdint.h>

#include "apps/lockers/lkc/slices/slices.h"
#include "lib/rt/ev/ev.h"
#include "lib/rt/rxwire/rxwire.h"

#define LK_VISIT_PULSE_UNITS 5u            /* cmd_open.pulse_units: the default pulse, 500 ms */
#define LK_VISIT_CORR_TAG 0x56000000u      /* top byte of every corr this reactor sends ("V") */
#define LK_VISIT_CORR(first_time, locker) \
    (LK_VISIT_CORR_TAG | ((uint32_t)((first_time) != 0) << 16) | (uint32_t)(uint16_t)(locker))

void lk_react_visit(const void *const *slices, const ev_t *e, rx_emit_t *out);

#endif
