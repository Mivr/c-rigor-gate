# P004 visual/UI gate: owner summary

Full design: `P004-visual-gate.md` (same folder). Draft kept unchanged: `P004-visual-gate-draft.md`. Design only:
nothing is built yet.

## What it catches

All 11 escaped kiosk UI defects (F1–F11), plus 4 extra ones found in the same evidence (X1–X4). It also catches
their *classes*, so the next defect of each kind is caught too:
- dialogs that vanish too early or never go away (F1);
- typing with no visible echo (F2);
- overlays that cover keys or swallow taps (F3, F4);
- wrong size, alignment or emphasis; a number split into separate glyphs (F5, F7);
- clipped or truncated text, missing wrapping in Bulgarian (F6, F8);
- toggles with no visible selected state (F9);
- missing version lines and report sections (F10, F11).

Every failure is caught by at least two independent layers. Each also has at least one check that does not depend on
the Rust app, so it is still caught if Rust has the same bug. Today the business-apps commit `a318b33` must make the
gate fail for all 11 (the "historic canary").

## How it works

1. **Look where the visitor looks.** The gate observes four stages: view state, scene graph, the LVGL object tree
   *after* the renderer has applied it, and the framebuffer. It compares the stages with each other. 7 of the 11 bugs
   were in the renderer, where the scene was right; checks on the scene alone could not see them. The gate's a11y view
   is built from the LVGL tree.
2. **A stack of oracles, cheapest and most structural first**:
   - **L0:** every run is done twice and must give byte-identical results, with no retries.
   - **L1–L2:** parity with the Rust app, step by step and node by node (labels, layout relations, size classes,
     selected state).
   - **L3:** the renderer did what the scene asked (geometry, text, font, alignment, flags).
   - **L4:** rules that hold without Rust:
     - minimum dwell of messages, countdown cadence;
     - taps go through the real LVGL hit-test, overlays must declare their input policy, no dead buttons, echo on
       every digit;
     - text fits and is shown in full, legibility and contrast floors, required content.
   - **L5:** exact before/after comparisons: English, Bulgarian and a stretched pseudo-language; switching language
     changes exactly the translated texts; EN→BG→EN restores the screen; shifting the clock origin changes nothing.
   - **L6:** exact pixel goldens of the C app, made by the gate only after L0–L5 pass.
   - **L7:** an LLM may explain a failure but never decides one.
3. **Pixels last, tolerance 0.** No fuzzy image matching. No screenshot comparison between the Rust and C renderers.
   Published fuzzy and learned image checks have 10–40% false positives, which is unusable when no human reviews
   the results.
4. **A machine explores the app.** `rigor ui-explore` covers about 3k view classes, then searches every reachable
   state to depth 12 using a sealed list of events. The events include:
   - probe taps at many points of every button, through the real hit-test, plus taps that must do nothing;
   - code-entry boundary cases;
   - language switches;
   - virtual-time jumps: next deadline, one frame, just before expiry.

   The Rust app runs in lockstep where feasible. States are de-duplicated by a key you declare, never by a similarity
   guess.
5. **Sealed, not trusted.** Agents write all the code, so anything that could turn red to green without fixing the
   product is owner-sealed. That covers thresholds, the event list, the dedup key, the list of taps allowed to do
   nothing, allowlists and goldens. Sealed items never change in the same commit as the code they excuse. Deletions,
   skips and loosened tolerances count against a budget. Each night the gate mutation-tests itself, to find checks
   that cannot fail.

## Cost

- **Build:** about 21 tasks, roughly 55–75 agent-days in total, with about 25 on the critical path. The first task
  measures before anything else is built (ms per state, whether the merge tier fits, whether the Rust app can run
  headless in lockstep).
- **Runtime (estimate, to be measured):**
  - 40–80 ms per rendered state;
  - roughly 20–40 CPU-minutes per merge, which is a few minutes of wall time on the farm (target under 10 min);
  - text-fit and scene checks at lane take seconds.
- **Scope:** the merge cost is paid only by changes that touch UI-reachable code. Deeper exploration, a 2× text scale
  run and the gate's self-mutation run nightly. Real touch-to-screen latency is measured on the kiosk at release.

## Decisions needed from you

1. **Panel:** which kiosk display (size, so pixels per inch) and how far away people stand. The mm target sizes and
   text legibility checks need both.
2. **Target sizes for whom:** keypad ≥ 20 mm and other buttons ≥ 19 mm, which includes older users, or smaller
   values?
3. **Error dialogs:** keep the fixed 8 s, or keep them until acknowledged? Also choose the reading speed for message
   dwell: 175 or 130 words per minute.
4. **Product e2e tree:** should the kiosk's own test tree also come from the LVGL tree, so the club driver sees the
   real screen? (Recommended: yes.)
5. **Pad digits:** show the typed digits like Rust, or keep visible dots for privacy?
6. **Sealing:** who signs sealed files and how, and the size of each budget (deviations, allowlist, skips).
7. **Rust lockstep driver:** fund it (more than 5 days of club-apps work, parity on every explored state), or keep
   parity on the 23 scenarios only?
8. **Merge budget:** full exploration at every merge, or only around the changed screens, with the full run nightly
   (decide after the first measurement).
9. **Pseudo-language:** run it at merge or nightly only?
10. **Judgement entries** (importance levels, toggle groups, which overlays are modal): take them from the Rust app or
    declare them yourself?
11. **Starting numbers** for the few unvalidated values (size band, flicker window, hierarchy ratio): measure at the
    first pass and only tighten, or set them yourself?
12. **Contrast:** adopt WCAG ratios (4.5:1 text, 3:1 indicators), and require that selection is not shown by colour
    alone?
13. **Visibility:** may implementers see the Rust screenshots and labels?
14. **Real-window driver:** reuse the Rust e2e driver, or build a gate-owned C one?
15. **Goldens:** produce them headless or under Xvfb? (This needs the P003 owner too.)
16. **LLM explanations:** worth the calls at all, given they never affect a verdict?

Literature gaps you should know about: nothing in the corpus is on LVGL or kiosks; there is no Bulgarian text-expansion
or reading-rate data; no study of minimum message display time; no validated "prominent enough" threshold; no study of
clock-shift testing.
