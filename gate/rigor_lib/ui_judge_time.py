"""The `ui-time` judge (U09, P004 3.5): reads every path of the explorer as a timeline (ui_judge_time_model) and judges
how long timed elements stay, their countdowns, flashes, silent auto-transitions, dwell against reading time and the
clock origin (ui_judge_time_checks, ui_judge_time_probe, ui_judge_time_origin). docs/ui-judges-time.md has the rules,
the time-probing mode and its bound, and the honesty table.

The judge is called once per path the explorer runs (`path(runner, steps)`, with the steps of the first run) and once
at the end (`finish`, ui_judge_time_finish). Through `runner` (ui_explore_time) it runs the time-probing runs and the
clock-origin replays; both are counted (`checks-examined`: cost) and spend the explorer's wall budget. Findings have
the schema of docs/ui-explore.md, gate `ui-time`, ids `ui-time.<check>/<12 hex of sha256([gate, check, [identity,
state key]])>` (the state key of the element's first appearance), or `[gate, check, identity]` for run-level and
static findings.
"""

import hashlib

from rigor_lib import jsonio, ui_contract
from rigor_lib.ui_contract_dwell import char_count, reading_ms
from rigor_lib.ui_explore_judges import state_of
from rigor_lib.ui_judge_time_checks import (chain_verdicts, countdown_verdicts, decisions, flash_verdicts,
                                            increase_verdicts, invisible_verdicts, zero_verdicts)
from rigor_lib.ui_judge_time_model import Binding, appearances, timeline
from rigor_lib.ui_judge_time_origin import Origins
from rigor_lib.ui_judge_time_probe import Diverged, Prober

GATE = "ui-time"
CHECKS = ("notice-lifetime-short", "notice-lifetime-short-floor", "notice-lifetime-long", "flash", "countdown-wrong",
          "invisible-auto-transition", "dwell-below-reading-time", "clock-origin-divergence", "patches-inconsistent")
META = ("contract-pending", "contract-incomplete", "exception-unused", "checks-examined", "check-vacuous",
        "check-blocked", "lifetime-undecided", "probe-diverged", "time-probes-capped", "time-budget-cut")
ALL = CHECKS + META
LIFETIME = ("notice-lifetime-short", "notice-lifetime-short-floor", "notice-lifetime-long")
DWELL = ("notice-lifetime-short", "dwell-below-reading-time")
MAX_PROBES = 64        # (state key, timer kind) appearances probed per exploration


def item(check, identity, severity, state, path, observed):
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
        self.pendings, self.lifetimes, self.incomplete = {}, [], {}
        self.probed, self.capped, self.paths = set(), [], 0
        self.origins = Origins(contract)
        self.runner = None

    # ---- contract values ------------------------------------------------------------------------------------------
    def _get(self, checks, section, key, words):
        try:
            return self.contract.get(section, key)
        except ui_contract.ContractPending as error:
            for check in checks:
                self.pendings.setdefault((check, error.path), item(
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
        out = self._observed(facts, words, True)
        for index, kind in appearances(facts):
            out += self._lifetime(runner, binding, facts, words, index, kind)
        for index in _hidden_steps(facts):
            out += self._hidden(runner, binding, facts, words, index)
        if self.origins.offer(facts, words):
            self.origins.take(words)
            out += self.origin_findings(runner, facts, words)
        return out

    def _observed(self, facts, words, main):
        """flash, invisible-auto-transition, patches-inconsistent, countdown increases (on the main path, input steps
        included) and countdown formats, read from one run's observations."""
        verdicts = []
        threshold = self._get(("flash",), "thresholds", "flicker_floor_ms", words)
        if threshold is not None:
            found, judged = flash_verdicts(facts, threshold)
            verdicts, self.counts["flash"] = found, self.counts["flash"] + judged
        # a probing run repeats the path's prefix: its patches are judged (and reported) on the path itself
        for name, judge in (("invisible-auto-transition", invisible_verdicts),) \
                + ((("patches-inconsistent", chain_verdicts), ("countdown-wrong", increase_verdicts)) if main else ()):
            found, judged = judge(facts)
            verdicts, self.counts[name] = verdicts + found, self.counts[name] + judged
        for fact in facts:
            for kind in sorted(fact.present):
                if fact.unparsed and kind not in self.incomplete:
                    self.incomplete[kind] = item("contract-incomplete", ["countdown-format", kind], "error", None,
                                                 words[:1], {"what": "countdown-format", "kind": kind})
        return [self.finding(v, facts, words, 0) for v in verdicts]

    def finding(self, verdict, facts, words, at):
        state_at = at if verdict["state_at"] is None else verdict["state_at"]
        path_at = at if verdict["path_at"] is None else verdict["path_at"]
        fact = facts[state_at]
        found = item(verdict["check"], [verdict["identity"], fact.key], "error",
                     state_of(fact.key, fact.proj, self.catalogue_key, fact.origin), words[:path_at + 1],
                     verdict["observed"])
        return self.exceptions.apply(found, verdict["target"])

    # ---- dwell ------------------------------------------------------------------------------------------------------
    def _dwell(self, kind, appear, words, timer, binding):
        """(D, the floor approximation max(L, dwell_floor_ms), findings): D = max(L, max(floor, base + reading)) of
        the text the run shows (no message catalogue is given; docs/ui-judges-time.md); None while pending."""
        lifetime = timer["lifetime_ms"]
        floor = self._get(DWELL, "thresholds", "dwell_floor_ms", words)
        base = self._get(DWELL, "thresholds", "dwell_base_ms", words)
        per_word = self._get(DWELL, "thresholds", "dwell_chars_per_word", words)
        rate = self._get(DWELL, "reading", "rate_wpm", words)
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
        found = item("dwell-below-reading-time", [kind, name], "error", None, words,
                     {"kind": kind, "message": name, "chars": char_count(text), "lifetime_ms": lifetime,
                      "min_dwell_ms": least, "text_from": "the run" if not msgid else "the run (msgid from identity)"})
        return max(lifetime, least), floor_only, [self.exceptions.apply(found, kind)]

    # ---- the time-probing mode --------------------------------------------------------------------------------------
    def _lifetime(self, runner, binding, facts, words, index, kind):
        appear, timer, prefix = facts[index], binding.timers[kind], words[:index + 1]
        if (appear.key, kind) in self.probed:
            return []
        if len(self.probed) >= MAX_PROBES:
            self.capped.append([appear.key, kind])
            return []
        self.probed.add((appear.key, kind))
        dwell, floor, out = self._dwell(kind, appear, prefix, timer, binding)      # needs no tick
        tick = self._get(LIFETIME + ("countdown-wrong",), "clock", "tick_ms", prefix)
        if tick is None:
            return out
        try:
            probe = Prober(runner, binding, tick).probe(facts, words, index, kind, timer, (dwell, floor))
        except Diverged as error:
            return out + [self.finding({"check": "probe-diverged", "identity": [kind], "target": kind,
                                        "state_at": None, "path_at": None,
                                        "observed": {"kind": kind, "path": prefix, "probe_path": error.words}},
                                       facts, words, index)]
        return out + self._judge_probe(facts, words, index, kind, timer, (dwell, floor, tick), probe)

    def _judge_probe(self, facts, words, index, kind, timer, values, probe, inside=None):
        """Findings of one probed element; `inside` = (the state's step, an identity prefix) for a hidden one."""
        dwell, floor, tick = values
        found, bounds = decisions(probe.appear, probe.gone, timer["lifetime_ms"], dwell, floor, tick)
        out, observed = [], {"kind": kind, "lifetime_ms": timer["lifetime_ms"], "tick_ms": tick,
                             "appeared": list(probe.appear), "shown_more_than_ms": bounds[0],
                             "shown_at_most_ms": bounds[1]}
        for check, yes in sorted(found.items()):
            limit = {"notice-lifetime-short": dwell, "notice-lifetime-short-floor": floor}.get(check)
            if yes is None:
                out.append({"check": "lifetime-undecided", "identity": [kind, check], "target": kind,
                            "state_at": None, "path_at": None,
                            "observed": dict(observed, check=check, why=probe.why or "bracket", bound_ms=limit)})
                continue
            self.counts[check] += 1
            if yes:
                out.append({"check": check, "identity": [kind], "target": kind, "state_at": None, "path_at": None,
                            "observed": dict(observed, **({"dwell_ms": dwell} if check.endswith("short") else
                                                          {"floor_ms": floor} if check.endswith("floor") else {}))})
        if timer["countdown_shown"] and probe.seq:
            self.counts["countdown-wrong"] += 1
            parts = countdown_verdicts(kind, probe.seq, timer, probe.appear[0])
            seen = {p["identity"][1] for p in parts}
            out += parts + ([] if "zero" in seen else zero_verdicts(kind, probe.samples))
        self.lifetimes.append({"kind": kind, "state": facts[index].key, "lifetime_ms": timer["lifetime_ms"],
                               "dwell_ms": dwell, "floor_ms": floor, "appeared": list(probe.appear),
                               "shown_more_than_ms": bounds[0], "shown_at_most_ms": bounds[1], "runs": probe.runs,
                               "decided": {c: v for c, v in sorted(found.items())}, "path": words[:index + 1]})
        run_facts, run_words = probe.run
        if inside is not None:
            out = [dict(v, state_at=inside[0], path_at=index, identity=inside[1] + v["identity"]) for v in out]
        return [self.finding(v, facts, words, index) for v in out] + \
            (self._observed(run_facts, run_words, False) if run_facts else [])

    def _hidden(self, runner, binding, facts, words, index):
        """The timed elements shown only inside the time step `index`: their lifetime rules (no countdown)."""
        if (facts[index - 1].key, facts[index].word, "inside") in self.probed:
            return []
        self.probed.add((facts[index - 1].key, facts[index].word, "inside"))
        tick = self._get(LIFETIME, "clock", "tick_ms", words[:index + 1])
        if tick is None:
            return []
        prober = Prober(runner, binding, tick)
        try:
            probes, _samples = prober.hidden(facts, words, index)
        except Diverged as error:
            return [self.finding({"check": "probe-diverged", "identity": ["inside", facts[index].word],
                                  "target": facts[index].word, "state_at": index - 1, "path_at": index,
                                  "observed": {"path": words[:index + 1], "probe_path": error.words}},
                                 facts, words, index)]
        out = []
        for kind, probe in sorted(probes.items()):
            timer = binding.timers[kind]
            dwell, floor, found = self._dwell(kind, facts[index - 1], words[:index + 1], timer, binding)
            limits = (timer["lifetime_ms"], dwell, floor if dwell is None else None, tick)
            try:
                prober.refine_hidden(facts, words, index, kind, probe,
                                     lambda p: None not in decisions(p.appear, p.gone, *limits[:3], tick)[0].values())
            except Diverged:
                pass                       # the first hidden run reached the same step: the bracket stands as is
            out += found + self._judge_probe(facts, words, index, kind, timer, (dwell, floor, tick), probe,
                                             (index - 1, ["inside", facts[index].word]))
        return out

    # ---- clock-origin-divergence ------------------------------------------------------------------------------------
    def origin_findings(self, runner, facts, words):
        before_runs = self.origins.runs
        diverged = self.origins.replay(runner, self.identity, facts, words)
        self.counts["clock-origin-divergence"] += self.origins.runs - before_runs
        if not diverged:
            return []
        at, part, _origin = min(diverged)
        before = facts[at - 1] if at > 0 else facts[0]
        found = item("clock-origin-divergence", [["origin", words[at], part], before.key], "error",
                     state_of(before.key, before.proj, self.catalogue_key, before.origin), words,
                     {"step": at, "word": words[at], "part": part,
                      "origins": [[o, s, p] for s, p, o in sorted(diverged)]})
        return [self.exceptions.apply(found, words[at])]

    def finish(self, open_word):
        from rigor_lib.ui_judge_time_finish import finish
        return finish(self, open_word)


def _hidden_steps(facts):
    """Time steps whose patches create and later remove one key: something was shown only inside the step."""
    out = []
    for index in range(1, len(facts)):
        fact, created = facts[index], set()
        if fact.mode != "time" or fact.chain or fact.now - fact.prev_now <= 1:
            continue
        for op, key, _name, _old, _new in fact.patches:
            if op == "create":
                created.add(key)
            elif op == "remove" and key in created:
                out.append(index)
                break
    return out
