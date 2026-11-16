"""Findings and the judges of `rigor ui-explore` (U05, P004 3.7, 4.5).

A finding is one JSON object of the schema of P004 4.5 (docs/ui-explore.md). Its `id` is
`ui-explore.<check>/<12 hex>`, the sha256 of the check and an identity that names states by abstraction key, events by
path word and run-level facts by the catalogue's sha256, never by exploration order.

Three kinds of judge (docs/ui-explore.md, "The judge interface"):
  step judge         judge(step, path, contract) -> findings; once per completed step of every first run, in order
  run judge          judge(first, second, contract) -> findings; once per path, with both runs
  exploration judge  judge(exploration, contract) -> (evaluated, findings); once at the end (ui_explore_coverage)
A judge attaches evidence by putting `{file name: JSON data}` under the key PRIVATE of a finding; the explorer writes
those files next to the finding's `paths.json` and removes the key before the finding is written.
"""

from rigor_lib import jsonio
from rigor_lib.ui_explore_key import normalised, readable
from rigor_lib.ui_explore_probe import NOT_A_REPLY
from rigor_lib.ui_explore_run import first_difference

GATE = "ui-explore"
LAYERS = {"model-nondeterministic": "L0", "run-twice-mismatch": "L0", "timer-starvation": "L0"}
CHECKS = ("ui-coverage-gap", "model-nondeterministic", "run-twice-mismatch", "timer-starvation", "timer-unreachable",
          "depth-unsaturated", "key-too-coarse", "key-fact-unmatched", "event-never-accepted", "event-accepted",
          "intent-missed", "tap-misrouted", "noop-tap-effect", "probe-internal-error", "ui-explore-timeout",
          "ambient-missing", "ambient-extra", "taps-injected", "ambient-restart")
# P004 3.7: I -> E after report-first; every other check is an error. `taps-injected` (U05c) says that the taps of the
# run were injected at a product's own pointer indev: a fact about the run's fidelity, not a product defect.
# `ambient-restart` (U05d) records that a tap's change was judged a declared countdown restart: a fact, not a defect.
# U05e: counted in the summary only by a run with scene taps or a contract (a run without them keeps its bytes).
# `taps-capped` (info) records that a state had more scene taps than the per-state cap: a fact about the run.
SCENE_CHECKS = ("blocked-target-live", "tap-swallowed-first", "taps-capped", "scene-unreadable", "scene-taps-vacuous",
                "scene-word-unbound")
# `scene-word-unbound` is info for a hand-written replay path; `--strict-paths` makes it an error (ui_explore.py).
SEVERITY = {"key-too-coarse": "info", "taps-injected": "info", "ambient-restart": "info", "taps-capped": "info",
            "scene-word-unbound": "info"}
PRIVATE = "_evidence"


def finding_id(check, identity):
    digest = jsonio.sha256_hex(jsonio.canonical_dumps([check, identity]))
    return "%s.%s/%s" % (GATE, check, digest[:12])


def state_of(key, proj, catalogue_key, origin_ms):
    """A finding's `state`: the key hash, the readable projection and the clock origin; None without a state."""
    if key is None:
        return None
    return {"key": key, "origin_ms": origin_ms, "projection": readable(proj, catalogue_key)}


def make(check, identity, state, path, observed, evidence=None):
    if check not in CHECKS and check not in SCENE_CHECKS:
        raise ValueError("unknown check %r" % check)
    item = {"id": finding_id(check, identity), "gate": GATE, "check": check, "layer": LAYERS.get(check, "meta"),
            "severity": SEVERITY.get(check, "error"), "state": state, "path": list(path), "observed": observed,
            "blame": [], "evidence": [], "explanation": None}
    if evidence:
        item[PRIVATE] = evidence
    return item


def origin_of(words):
    return int(words[0].split(" ")[1])


# ---- step judges ----------------------------------------------------------------------------------------------
def starvation_judge(catalogue_key):
    """`timer-starvation`: more than `starve_firings` deadline firings within `starve_window_frames` frames of virtual
    time (ui_explore_words.fired). Reported once per run, at the step that crossed the limit; the state is the one
    before the first firing of that window. O(1) per step: the run counts the firings."""
    def judge(step, path, contract):
        del contract
        if step.starved is None:
            return []
        info = step.starved
        observed = {name: info[name] for name in ("firings", "limit", "window_ms", "first_ms", "last_ms")}
        return [make("timer-starvation", ["window", info["start_key"]],
                     state_of(info["start_key"], info["start_proj"], catalogue_key, step.origin),
                     [view.word for view in path] + [step.word], observed)]
    return judge


def missed_judge(catalogue_key):
    """`intent-missed`: an input reached the product through the production path, but the product did not produce the
    intent it was aimed at (`ok apply missed`, a probe with apply-missed; or a catalogue tap that pressed a node and
    changed nothing, whose node box is the evidence image `tap-node.png`)."""
    def judge(step, path, contract):
        del contract
        if step.result != "missed":
            return []
        return [make("intent-missed", ["missed", step.key_before, step.word],
                     state_of(step.key_before, step.proj_before, catalogue_key, step.origin),
                     [view.word for view in path] + [step.word],
                     dict({"word": step.word, "applies": list(step.applies)},
                          **({"covered": step.covered} if step.covered else {})),
                     dict(step.images) or None)]
    return judge


def misrouted_judge(catalogue_key):
    """`tap-misrouted` (P004 3.4): a u2 tap aimed at a node (its declared `target` class at the point, in the frame
    before) pressed another node that is not a screen or layer root, whether or not anything changed."""
    def judge(step, path, contract):
        del contract
        if step.misrouted is None:
            return []
        return [make("tap-misrouted", ["misrouted", step.key_before, step.word],
                     state_of(step.key_before, step.proj_before, catalogue_key, step.origin),
                     [view.word for view in path] + [step.word], dict(step.misrouted, word=step.word),
                     dict(step.images) or None)]
    return judge


def noop_judge(catalogue_key):
    """`noop-tap-effect` (P004 3.4): a tap that must change nothing (a u3 complement tap, or a u2 tap that was blocked
    or pressed nothing or a root) changed the model."""
    def judge(step, path, contract):
        del contract
        if step.noop is None:
            return []
        return [make("noop-tap-effect", ["noop", step.key_before, step.word],
                     state_of(step.key_before, step.proj_before, catalogue_key, step.origin),
                     [view.word for view in path] + [step.word], dict(step.noop, word=step.word))]
    return judge


def ambient_judge(catalogue_key):
    """`ambient-missing` / `ambient-extra` (U05c): a tap through the product's pointer entry that did not post a
    declared ambient event exactly once at its instant (docs/ui-explore.md, "Ambient events")."""
    def judge(step, path, contract):
        del contract
        if step.ambient is None:
            return []
        found = []
        for check, part in (("ambient-missing", "missing"), ("ambient-extra", "extra")):
            if step.ambient[part]:
                found.append(make(check, [part, step.key_before, step.word],
                                  state_of(step.key_before, step.proj_before, catalogue_key, step.origin),
                                  [view.word for view in path] + [step.word],
                                  {"word": step.word, "types": list(step.ambient[part])}))
        return found
    return judge


def restart_judge(catalogue_key):
    """`ambient-restart` (U05d, info): a tap whose residual change was a declared countdown restart and so counted as
    "changed nothing" (docs/ui-explore.md, "Countdown restart"). One finding per restarted node, identity (key before,
    node key), so a sweep that taps the same screen again and again gives one per node and state: the explorer keeps
    one finding per id, the one with the shortest path."""
    def judge(step, path, contract):
        del contract
        words = [view.word for view in path] + [step.word]
        return [make("ambient-restart", ["restart", step.key_before, item["node"]],
                     state_of(step.key_before, step.proj_before, catalogue_key, step.origin), words,
                     dict(item, word=step.word)) for item in step.restart or ()]
    return judge


def layer_judge(catalogue_key):
    """U05e, with a contract: `blocked-target-live` (P004 3.4), a tap on a target that is inert under a modal layer
    (R7) had an effect; `tap-swallowed-first`, a tap under a layer the contract says does not block only removed the
    layer (docs/ui-explore.md, "Taps under a layer")."""
    def judge(step, path, contract):
        del contract
        words = [view.word for view in path] + [step.word]
        found = []
        unbound = {"word": step.word} if "unbound" in step.outcome else None
        for check, part in (("blocked-target-live", step.blocked), ("tap-swallowed-first", step.swallowed),
                            ("scene-word-unbound", unbound)):
            if part is not None:
                found.append(make(check, [check, step.key_before, step.word],
                                  state_of(step.key_before, step.proj_before, catalogue_key, step.origin), words,
                                  dict(part, word=step.word)))
        return found
    return judge


def unreachable_judge(catalogue_key):
    """`timer-unreachable`: a time word whose wait passes `max_wait_ms` or the protocol's clock limit."""
    def judge(step, path, contract):
        del contract
        if step.unreachable is None:
            return []
        words = [view.word for view in path] + [step.word]
        return [make("timer-unreachable", [step.key_before, step.word, step.unreachable["reason"]],
                     state_of(step.key_before, step.proj_before, catalogue_key, step.origin), words,
                     dict(step.unreachable, word=step.word))]
    return judge


class PathSoFar:
    """The steps before one step, without copying them (a judge called per step stays O(1) unless it walks it)."""

    def __init__(self, steps, end):
        self._steps, self._end = steps, end

    def __len__(self):
        return self._end

    def __iter__(self):
        return iter(self._steps[:self._end])

    def __getitem__(self, index):
        if isinstance(index, slice):
            return self._steps[:self._end][index]
        if not -self._end <= index < self._end:
            raise IndexError(index)
        return self._steps[index % self._end]


def run_step_judges(judges, run, contract):
    out = []
    for index, step in enumerate(run.steps):
        if step.key is None:
            break
        for judge in judges:
            out.extend(judge(step, PathSoFar(run.steps, index), contract))
    return out


# ---- run judges -----------------------------------------------------------------------------------------------
def _error_finding(run, catalogue_key):
    if run.error is None:
        return None
    index, error = run.error
    step = run.steps[index]
    if error.kind == "timeout":
        check = "ui-explore-timeout"
    elif error.kind == "zero-delay":
        check = "timer-starvation"
    else:
        check = "probe-internal-error"
    # Output nobody asked for is caught before a command or read as its reply, whichever the timing gives: the command
    # is then left out of the finding, so its id and bytes do not depend on timing (the evidence keeps it).
    command = None if error.detail == NOT_A_REPLY else error.command
    observed = {"kind": error.kind, "command": command, "detail": error.detail, "step": index}
    path = run.words[:index + 1] if step.word not in ("quit", "evidence") else run.words
    evidence = {"error.json": {"raw": error.raw, "command": error.command}} if error.raw is not None else None
    return make(check, [error.kind, command, step.key_before, step.word],
                state_of(step.key_before, step.proj_before, catalogue_key, origin_of(run.words)), path, observed,
                evidence)


def probe_error_judge(catalogue_key):
    """Every run that ended with a ProbeError: `ui-explore-timeout`, `timer-starvation` (zero-delay) or
    `probe-internal-error`, with the probe's own bytes as evidence."""
    def judge(first, second, contract):
        del contract
        return [item for item in (_error_finding(first, catalogue_key), _error_finding(second, catalogue_key)) if item]
    return judge


def _part(run, index, part):
    return run.steps[index].parts().get(part) if index < len(run.steps) else None


def _first_item(a, b):
    if type(a) is not list or type(b) is not list:
        return None
    return next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))


def run_twice_judge(catalogue_key):
    """L0: a `trace` that differs is `model-nondeterministic`; any other part that differs (in read order) is
    `run-twice-mismatch`. The differing values go to the evidence (`runs.json`), never into the finding."""
    def judge(first, second, contract):
        del contract
        out = []
        trace_at, other = first_difference(first, second)
        for check, at, part in (("model-nondeterministic", trace_at, "trace"),
                                ("run-twice-mismatch",) + (other if other else (None, None))):
            if at is None:
                continue
            longer = first if len(first.steps) >= len(second.steps) else second
            step = longer.steps[at]
            values = [_part(first, at, part), _part(second, at, part)]
            observed = {"step": at, "word": step.word, "part": part, "item": _first_item(*values)}
            out.append(make(check, [step.key_before, step.word, part],
                            state_of(step.key_before, step.proj_before, catalogue_key, origin_of(longer.words)),
                            longer.words[:at + 1], observed, {"runs.json": {"first": values[0], "second": values[1]}}))
        return out
    return judge


class CoarseTable:
    """key-too-coarse: two completed steps with equal keys whose normalised records differ."""

    def __init__(self, catalogue_key):
        self.key = catalogue_key
        self.first = {}
        self.found = []

    def add(self, step, words):
        """`words` are the run's words; the path of `step` is their first index + 1."""
        record = normalised(step.obs, step.now, self.key)
        seen = self.first.get(step.key)
        if seen is None:
            self.first[step.key] = (record, list(words[:step.index + 1]))
            return
        if seen[0] == record:
            return
        path = list(words[:step.index + 1])
        parts = [name for name in ("nodes", "facts") if seen[0][name] != record[name]]
        observed = {"witness_path": seen[1], "differs_in": parts}
        self.found.append(make("key-too-coarse", [step.key],
                               state_of(step.key, step.proj, self.key, step.origin), path, observed,
                               {"records.json": {"witness": seen[0], "this": record}}))
