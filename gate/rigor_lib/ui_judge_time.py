"""The `ui-time` judge (U09, P004 3.5): reads every path of the explorer as a timeline (ui_judge_time_model) and judges
how long timed elements stay, their countdowns, flashes, silent auto-transitions, dwell against reading time and the
clock origin (ui_judge_time_checks). docs/ui-judges-time.md has the rules, the time-probing mode and its bound, and the
honesty table.

The judge is called once per path the explorer runs (`path(runner, steps)`, with the steps of the first run) and once
at the end (`finish`). Through `runner` (ui_explore_time) it runs the time-probing runs and the clock-origin replays;
both are counted (`checks-examined`: cost) and spend the explorer's wall budget. Findings have the schema of
docs/ui-explore.md, gate `ui-time`, ids `ui-time.<check>/<12 hex of sha256([gate, check, [identity, state key]])>`
(the state key of the element's first appearance), or `[gate, check, identity]` for run-level and static findings.
"""

import hashlib

from rigor_lib import jsonio, ui_contract
from rigor_lib.ui_contract_dwell import char_count, reading_ms
from rigor_lib.ui_explore_judges import state_of
from rigor_lib.ui_judge_time_checks import (bracket, countdown_verdicts, flash_verdicts, invisible_verdicts,
                                            lifetime_verdicts, plan, refine)
from rigor_lib.ui_judge_time_model import Binding, appearances, timeline

GATE = "ui-time"
CHECKS = ("notice-lifetime-short", "notice-lifetime-short-floor", "notice-lifetime-long", "flash", "countdown-wrong",
          "invisible-auto-transition", "dwell-below-reading-time", "clock-origin-divergence")
META = ("contract-pending", "exception-unused", "checks-examined", "check-vacuous", "check-blocked")
ALL = CHECKS + META
ORIGINS = (1, 1000, 10**9, 2**32 + 7, 2**40)     # P004 3.5, ms
ORIGIN_PATHS = 8       # paths replayed at the other origins: the first ones (run order) that show a timed element
MAX_PROBES = 64        # (state key, timer kind) appearances probed per exploration
MAX_PHASES = 4         # probing runs per appearance: the grid, then refinements to one tick
BLOCKED_PARTS = {      # what the gate has no fact for (the honesty table of docs/ui-judges-time.md)
    "countdown-wrong": "the formatted string against the oracle's at the same virtual time: no oracle in the gate",
    "invisible-auto-transition": "a user-relevant O1 (view-state) field: the probe protocol has no view-state stage",
    "unresponsive-intent": "the contract does not mark which intents are effective in which state class",
}


def _item(check, identity, severity, state, path, observed):
    digest = jsonio.sha256_hex(jsonio.canonical_dumps([GATE, check, identity]))[:12]
    layer = "meta" if check in META else ("L5" if check == "clock-origin-divergence" else "L4")
    return {"id": "%s.%s/%s" % (GATE, check, digest), "gate": GATE, "check": check, "layer": layer,
            "severity": severity, "state": state, "path": list(path), "observed": observed, "blame": [],
            "evidence": [], "explanation": None}


class TimeJudge:
    def __init__(self, contract, catalogue_key, exceptions):
        self.contract, self.catalogue_key, self.exceptions = contract, catalogue_key, exceptions
        self.identity = None              # whether the probe announces `identity` (JudgeSet.wants_identity)
        self.counts = {check: 0 for check in CHECKS}
        self.pendings, self.lifetimes = {}, []
        self.probed, self.capped, self.paths = set(), 0, 0
        self.origin_done = set()
        self.runner = None

    # ---- contract values ------------------------------------------------------------------------------------------
    def _get(self, checks, section, key, words):
        try:
            return self.contract.get(section, key)
        except ui_contract.ContractPending as error:
            for check in checks:
                self.pendings.setdefault((check, error.path), _item(
                    "contract-pending", [check, error.path], ui_contract.PENDING_SEVERITY, None, words[:1],
                    {"check": check, "entry": error.path, "question": error.question}))
            return None

    def pending(self, check):
        return any(c == check for c, _entry in self.pendings)

    # ---- one path ---------------------------------------------------------------------------------------------------
    def path(self, runner, steps):
        """The findings of one path (the steps of its first run)."""
        self.runner = runner
        binding = Binding(self.contract, self.identity)
        facts = timeline(steps, runner.catalogue, binding)
        if not facts:
            return []
        self.paths += 1
        words = [step.word for step in steps[:len(facts)]]
        for fact in facts:
            self.exceptions.see(set(fact.present) | {raw.split("\t", 1)[0] for raw in fact.semantic})
        out = self._flash(facts, words) + self._invisible(facts, words)
        for index, kind in appearances(facts):
            out += self._probe(runner, binding, facts, words, index, kind)
        return out + self._origins(runner, facts, words)

    def _finding(self, verdict, facts, words, at):
        state_at = at if verdict["state_at"] is None else verdict["state_at"]
        path_at = at if verdict["path_at"] is None else verdict["path_at"]
        fact = facts[state_at]
        item = _item(verdict["check"], [verdict["identity"], fact.key], "error",
                     state_of(fact.key, fact.proj, self.catalogue_key, fact.origin), words[:path_at + 1],
                     verdict["observed"])
        return self.exceptions.apply(item, verdict["target"])

    def _flash(self, facts, words):
        threshold = self._get(("flash",), "thresholds", "flicker_floor_ms", words)
        if threshold is None:
            return []
        verdicts, judged = flash_verdicts(facts, threshold)
        self.counts["flash"] += judged
        return [self._finding(v, facts, words, 0) for v in verdicts]

    def _invisible(self, facts, words):
        verdicts, judged = invisible_verdicts(facts)
        self.counts["invisible-auto-transition"] += judged
        return [self._finding(v, facts, words, 0) for v in verdicts]

    # ---- dwell ------------------------------------------------------------------------------------------------------
    def _dwell(self, kind, appear, words, timer, binding):
        """(D, the floor approximation max(L, dwell_floor_ms), findings): D = max(L, max(floor, base + reading)) of
        the text the run shows (no message catalogue is given; docs/ui-judges-time.md); None while pending."""
        lifetime = timer["lifetime_ms"]
        floor = self._get(("notice-lifetime-short", "dwell-below-reading-time"), "thresholds", "dwell_floor_ms", words)
        base = self._get(("notice-lifetime-short", "dwell-below-reading-time"), "thresholds", "dwell_base_ms", words)
        per_word = self._get(("notice-lifetime-short", "dwell-below-reading-time"), "thresholds",
                             "dwell_chars_per_word", words)
        rate = self._get(("notice-lifetime-short", "dwell-below-reading-time"), "reading", "rate_wpm", words)
        floor_only = None if floor is None else max(lifetime, floor)
        if None in (floor, base, per_word, rate):
            return None, floor_only, []
        text = appear.texts.get(kind, "")
        least = max(floor, base + reading_ms(char_count(text), rate, per_word))
        if not binding.message(kind) or lifetime <= 0:
            return max(lifetime, least), floor_only, []
        self.counts["dwell-below-reading-time"] += 1
        if lifetime >= least:
            return max(lifetime, least), floor_only, []
        msgid = appear.msgids.get(kind)
        name = msgid.decode("utf-8", "replace") if msgid else "text:" + hashlib.sha256(text.encode()).hexdigest()[:16]
        item = _item("dwell-below-reading-time", [kind, name], "error", None, words,
                     {"kind": kind, "message": name, "chars": char_count(text), "lifetime_ms": lifetime,
                      "min_dwell_ms": least, "text_from": "the run" if not msgid else "the run (msgid from identity)"})
        return max(lifetime, least), floor_only, [self.exceptions.apply(item, kind)]

    # ---- the time-probing mode --------------------------------------------------------------------------------------
    def _probe(self, runner, binding, facts, words, index, kind):
        appear = facts[index]
        if (appear.key, kind) in self.probed:
            return []
        if len(self.probed) >= MAX_PROBES:
            self.capped += 1
            return []
        self.probed.add((appear.key, kind))
        timer = binding.timers[kind]
        prefix = words[:index + 1]
        tick = self._get(("notice-lifetime-short", "notice-lifetime-long", "countdown-wrong"), "clock", "tick_ms",
                         prefix)
        if tick is None:
            return []
        dwell, floor, out = self._dwell(kind, appear, prefix, timer, binding)
        instants = plan(appear, timer["lifetime_ms"], dwell if dwell is not None else floor, tick,
                        runner.catalogue.max_wait_ms)
        if not instants:
            return out
        first = self._sample(runner, binding, prefix, instants, index, kind)
        if first is None:
            return out
        seq, samples, run_facts, run_words = first
        lo_hi, phases = bracket(appear, samples, kind), 1
        while lo_hi[1] is not None and phases < MAX_PHASES:
            more = refine(lo_hi[0], lo_hi[1], tick, runner.catalogue.max_wait_ms)
            again = self._sample(runner, binding, prefix, more, index, kind) if more else None
            if again is None:
                break
            phases += 1
            samples = samples + again[1]
            lo_hi = bracket(appear, samples, kind)
        measured, verdicts = lifetime_verdicts(kind, appear, lo_hi, timer, dwell, floor, tick)
        self._count_lifetime(timer, dwell, floor)
        if timer["countdown_shown"]:
            verdicts += countdown_verdicts(kind, seq, timer)
            self.counts["countdown-wrong"] += 1
        self.lifetimes.append({"kind": kind, "state": appear.key, "appear_ms": appear.now - appear.origin,
                               "lifetime_ms": timer["lifetime_ms"], "dwell_ms": dwell, "floor_ms": floor,
                               "shown_more_than_ms": measured[0], "shown_at_most_ms": measured[1],
                               "phases": phases, "path": prefix})
        out += [self._finding(v, facts, words, index) for v in verdicts]
        return out + self._flash(run_facts, run_words) + self._invisible(run_facts, run_words)

    def _count_lifetime(self, timer, dwell, floor):
        if dwell is not None:
            self.counts["notice-lifetime-short"] += 1
        elif floor is not None:
            self.counts["notice-lifetime-short-floor"] += 1
        if timer["lifetime_ms"] > 0:
            self.counts["notice-lifetime-long"] += 1

    def _sample(self, runner, binding, prefix, instants, index, kind):
        """One probing run: the prefix, then `at` words at `instants`; (the observations from the appearance on, the
        samples taken, the run's facts and words), or None when the run does not show the element at the appearance
        step as the path did (the run ended early or the product diverged: its own findings say so)."""
        origin = int(prefix[0].split(" ")[1])
        steps = runner.probe(prefix + ["at %d" % (at - origin) for at in instants])
        run_facts = timeline(steps, runner.catalogue, binding)
        if len(run_facts) <= index or kind not in run_facts[index].present:
            return None
        wanted = set(instants)
        samples = [f for f in run_facts[index + 1:] if f.now in wanted and f.word.startswith("at ")]
        run_words = [step.word for step in steps[:len(run_facts)]]
        return run_facts[index:], samples, run_facts, run_words

    # ---- clock-origin-divergence ------------------------------------------------------------------------------------
    def _origins(self, runner, facts, words):
        """Replays the first ORIGIN_PATHS distinct paths that show a timed element at the other origins of ORIGINS and
        compares, step by step, the masked semantic records and the identity (docs/ui-judges-time.md)."""
        if len(self.origin_done) >= ORIGIN_PATHS or not any(f.present for f in facts) \
                or tuple(words) in self.origin_done:
            return []
        self.origin_done.add(tuple(words))
        seed = words[0].split(" ")[2]
        diverged = []
        for origin in ORIGINS:
            if origin == facts[0].origin:
                continue
            steps = runner.once(["open %d %s" % (origin, seed)] + words[1:])
            self.counts["clock-origin-divergence"] += 1
            other = timeline(steps, runner.catalogue, Binding(self.contract, self.identity))
            found = _divergence(facts, other)
            if found is not None:
                diverged.append((found[0], found[1], origin))
        if not diverged:
            return []
        at, part, _origin = min(diverged)
        before = facts[at - 1] if at > 0 else facts[0]
        item = _item("clock-origin-divergence", [["origin", words[at], part], before.key], "error",
                     state_of(before.key, before.proj, self.catalogue_key, before.origin), words,
                     {"step": at, "word": words[at], "part": part,
                      "origins": [[o, s, p] for s, p, o in sorted(diverged)]})
        return [self.exceptions.apply(item, words[at])]

    # ---- the end of the run -----------------------------------------------------------------------------------------
    def finish(self, open_word):
        binding = Binding(self.contract, bool(self.identity))
        out = list(self.pendings.values())
        for row, expired in self.exceptions.unused():
            visited = row["target"] in self.exceptions.visited
            out.append(_item("exception-unused", ["exception", row["id"]], "error" if visited or expired else "info",
                             None, [open_word], {"exception": row["id"], "rule": row["rule"], "target": row["target"],
                                                 "expires": str(row["expires"]), "expired": expired,
                                                 "target_visited": visited}))
        out += [_item("check-blocked", ["blocked", check, kind], "error", None, [open_word],
                      {"check": check, "kind": kind, "needs": "identity"}) for check, kind in _blocked(binding)]
        if self.identity is False:
            out.append(_item("check-blocked", ["blocked", "invisible-auto-transition"], "error", None, [open_word],
                             {"check": "invisible-auto-transition", "needs": "identity"}))
        cost = dict(self.runner.cost) if self.runner is not None else {}
        out.append(_item("checks-examined", ["examined"], "info", None, [open_word], {
            "paths": self.paths, "totals": dict(self.counts), "bound": list(binding.bound()),
            "blocked_kinds": list(binding.blocked()), "probes": len(self.probed), "probes_capped": self.capped,
            "origin_paths": len(self.origin_done), "cost": cost, "blocked_parts": BLOCKED_PARTS,
            "lifetimes": sorted(self.lifetimes, key=lambda r: (r["kind"], r["state"]))}))
        for check in CHECKS:
            if self.paths and self.counts[check] == 0 and not self.pending(check) and _applies(check, binding, self):
                out.append(_item("check-vacuous", ["vacuous", check], "error", None, [open_word],
                                 {"check": check, "paths": self.paths}))
        return out


def _divergence(facts, other):
    """(step, part) of the first step whose masked semantic records or identity differ, or where one run ended."""
    for at, fact in enumerate(facts):
        if at >= len(other):
            return at, "ended"
        if fact.masked != other[at].masked:
            return at, "semantic"
        if fact.ident != other[at].ident:
            return at, "identity"
    return None


def _blocked(binding):
    """(check, kind) for every timer the run cannot bind (it needs identity) and the check would read."""
    out = []
    for kind in binding.blocked():
        timer = binding.timers[kind]
        out.append(("notice-lifetime-short", kind))
        if timer["lifetime_ms"] > 0:
            out.append(("notice-lifetime-long", kind))
        if timer["countdown_shown"]:
            out.append(("countdown-wrong", kind))
        if timer["class"] == "message" and timer["lifetime_ms"] > 0:
            out.append(("dwell-below-reading-time", kind))
    return out


def _applies(check, binding, judge):
    """Whether a check had something to judge in this contract and run (else no verdict is not vacuous)."""
    timers = [binding.timers[kind] for kind in binding.bound()]
    if check == "notice-lifetime-short-floor":
        return judge.pending("notice-lifetime-short") and bool(timers)
    if check in ("notice-lifetime-short", "clock-origin-divergence"):
        return bool(timers)
    if check == "notice-lifetime-long":
        return any(t["lifetime_ms"] > 0 for t in timers)
    if check == "countdown-wrong":
        return any(t["countdown_shown"] for t in timers)
    if check == "dwell-below-reading-time":
        return any(t["class"] == "message" and t["lifetime_ms"] > 0 for t in timers)
    if check == "invisible-auto-transition":
        return bool(judge.identity)
    return True
