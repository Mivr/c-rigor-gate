"""Findings, the abstraction key and the built-in judges of `rigor ui-explore` (U05, P004 3.7, 4.3, 4.5).

A finding is one JSON object of the schema of P004 4.5 (docs/ui-explore.md). Its `id` is
`ui-explore.<check>/<12 hex>`, the sha256 of the check and an identity that names states by their abstraction key and
events by their path word, never by exploration order, so the same defect has the same id in every strategy and in
`replay`.

The judge interface: a step judge is a callable `judge(step, path, contract) -> iterable of findings`, called once per
observed step of every first run, in path order; `step` is a `StepView`, `path` the StepViews before it (the path so
far), `contract` the UI contract (`ui_contract.Contract`) or None. The built-in step judge is `timer-starvation`. The
run-pair checks (probe errors, run-twice) and the run-level checks (coverage, depth, key-too-coarse) are here too.
"""

from dataclasses import dataclass

from rigor_lib import jsonio
from rigor_lib.ui_explore_probe import FRAME_MS, SEMANTIC_FIELDS
from rigor_lib.ui_explore_run import first_difference, starving

GATE = "ui-explore"
LAYERS = {"model-nondeterministic": "L0", "run-twice-mismatch": "L0", "timer-starvation": "L0"}
CHECKS = ("ui-coverage-gap", "model-nondeterministic", "run-twice-mismatch", "timer-starvation", "depth-unsaturated",
          "key-too-coarse", "probe-internal-error", "ui-explore-timeout")
SEVERITY = {"key-too-coarse": "info"}
PRIVATE = "_evidence"     # evidence files of a finding ({name: JSON data}); removed before the finding is written     # P004 3.7: I -> E after report-first; every other check is an error


@dataclass(frozen=True)
class StepView:
    """What a judge sees of one step: its index and word, the step (`ui_explore_run.Step`), its abstraction key
    (hex, None when the step failed) and the key of the state before it (None before `open`)."""
    index: int
    word: str
    step: object
    key: object
    key_before: object
    origin_ms: int


def finding_id(check, identity):
    digest = jsonio.sha256_hex(jsonio.canonical_dumps([check, identity]))
    return "%s.%s/%s" % (GATE, check, digest[:12])


def make(check, identity, state_key, origin_ms, path, observed):
    """One finding of the P004 4.5 schema; `blame` and `evidence` are filled later or stay empty."""
    if check not in CHECKS:
        raise ValueError("unknown check %r" % check)
    state = None if state_key is None else {"key": state_key, "origin_ms": origin_ms}
    return {"id": finding_id(check, identity), "gate": GATE, "check": check, "layer": LAYERS.get(check, "meta"),
            "severity": SEVERITY.get(check, "error"), "state": state, "path": list(path), "observed": observed,
            "blame": [], "evidence": [], "explanation": None}


# ---- the abstraction key ---------------------------------------------------------------------------------------
def deadline_bucket(step):
    due = step.obs["due"]
    if due is None:
        return "none"
    return "within-frame" if due - step.now <= FRAME_MS else "pending"


def projection(step, key):
    """The owner-declared projection of a completed step: per node its `key` and the declared fields, plus the facts."""
    index = [SEMANTIC_FIELDS.index(name) for name in key.fields]
    nodes = [[record.fields[0]] + [record.fields[i] for i in index] for record in step.obs["semantic"]]
    facts = {}
    if "deadline" in key.facts:
        facts["deadline"] = deadline_bucket(step)
    if "env-inputs" in key.facts:
        facts["env-inputs"] = [list(item) for item in step.obs["env"]]
    return {"nodes": nodes, "facts": facts}


def key_of(step, key):
    return jsonio.sha256_hex(jsonio.canonical_dumps(projection(step, key)))


def normalised_tree(step, key):
    """The semantic records without the fields the key declares as ignored (what key-too-coarse compares)."""
    keep = [i for i, name in enumerate(SEMANTIC_FIELDS) if name not in key.ignore]
    return [[record.fields[i] for i in keep] for record in step.obs["semantic"]]


def views(run, key):
    """StepViews of the completed steps of a run (a failed step has no key)."""
    out, before = [], None
    origin = int(run.words[0].split(" ")[1])
    for step in run.steps:
        current = key_of(step, key) if step.error is None else None
        out.append(StepView(step.index, step.word, step, current, before, origin))
        before = current
    return out


# ---- run-pair checks: probe errors and run-twice -----------------------------------------------------------------
def error_finding(run, steps):
    """The finding of a run that ended with a ProbeError, or None."""
    if run.error is None:
        return None
    index, error = run.error
    check = "ui-explore-timeout" if error.kind == "timeout" else "probe-internal-error"
    before = steps[index].key_before
    observed = {"kind": error.kind, "command": error.command, "detail": error.detail, "step": index}
    word = run.steps[index].word
    path = run.words[:index + 1] if word != "quit" else run.words
    return make(check, [error.kind, error.command, before, word], before, steps[0].origin_ms, path, observed)


def pair_findings(first, second, key):
    """Probe errors of either run, and the run-twice comparison (P004 3.7): a trace that differs is
    `model-nondeterministic`, any other reply that differs is `run-twice-mismatch`; each names the first differing step."""
    steps = views(first, key)
    out = [item for item in (error_finding(first, steps), error_finding(second, views(second, key))) if item]
    trace_at, other = first_difference(first, second)
    for check, at, part in (("model-nondeterministic", trace_at, "trace"),
                            ("run-twice-mismatch",) + (other if other else (None, None))):
        if at is None:
            continue
        before = steps[at].key_before if at < len(steps) else steps[-1].key
        word = first.steps[at].word if at < len(first.steps) else second.steps[at].word
        values = [_part(first, at, part), _part(second, at, part)]
        observed = {"step": at, "word": word, "part": part, "item": _first_item(*values)}
        path = (first.words if len(first.words) >= len(second.words) else second.words)[:at + 1]
        item = make(check, [before, word, part], before, steps[0].origin_ms, path, observed)
        item[PRIVATE] = {"runs.json": {"first": values[0], "second": values[1]}}
        out.append(item)
    return out


def _part(run, index, part):
    if index >= len(run.steps):
        return None
    return run.steps[index].parts().get(part)


def _first_item(a, b):
    """The index of the first differing item when both parts are lists, else None. The differing values themselves
    can vary from run to run (that is the defect), so they go to the evidence, never into the finding."""
    if type(a) is not list or type(b) is not list:
        return None
    return next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))


# ---- step judges ----------------------------------------------------------------------------------------------
def starvation_judge(bound):
    """`timer-starvation` (P004 3.7): `bound` consecutive firings of a deadline each left the next deadline at most
    one frame away. Reported once, at the step that completes the streak; the state is where the streak began."""
    def judge(step, path, contract):
        del contract
        streak = 0
        for view in list(path) + [step]:
            streak = streak + 1 if starving(view.step) else 0
        if streak != bound:
            return []
        start = (list(path) + [step])[-bound]
        dues = [[view.step.now, view.step.obs["due"]] for view in (list(path) + [step])[-bound:]]
        words = [view.word for view in list(path) + [step]]
        return [make("timer-starvation", [start.key_before], start.key_before, step.origin_ms, words,
                     {"firings": bound, "now_and_next_due": dues, "frame_ms": FRAME_MS})]
    return judge


def run_step_judges(judges, first, key, contract):
    steps = views(first, key)
    out = []
    for index, view in enumerate(steps):
        if view.key is None:
            break
        for judge in judges:
            out.extend(judge(view, steps[:index], contract))
    return out


# ---- run-level checks ----------------------------------------------------------------------------------------
def coverage_c1(count, visited, open_word):
    """C1: every domain entry visited. The path is the bare `open`: replaying it visits no entry."""
    origin = int(open_word.split(" ")[1])
    return [make("ui-coverage-gap", ["C1", index], None, origin, [open_word],
                 {"criterion": "C1", "domain_entry": index, "domain_count": count})
            for index in range(count) if index not in visited]


def coverage_c8(reachable, exercised, events, origin_ms):
    """C8: every reachable (abstract state, catalogue event) pair exercised. `reachable` maps key -> path."""
    out = []
    for state in sorted(reachable):
        for event in events:
            if (state, event) not in exercised:
                out.append(make("ui-coverage-gap", ["C8", state, event], state, origin_ms, reachable[state],
                                {"criterion": "C8", "event": event}))
    return out


def undeclared_env(reachable_env, declared, origin_ms):
    """C8 also needs every enabled env input to be a catalogue event: one gap per undeclared input and state."""
    out = []
    for (state, item), path in sorted(reachable_env.items()):
        if item not in declared:
            out.append(make("ui-coverage-gap", ["C8-env", state, list(item)], state, origin_ms, path,
                            {"criterion": "C8", "undeclared_env_input": list(item)}))
    return out


class CoarseTable:
    """key-too-coarse: two completed steps with equal keys whose normalised semantic trees differ."""

    def __init__(self, key):
        self.key = key
        self.first = {}          # abstraction key -> (tree, path)
        self.found = []

    def add(self, view, path):
        tree = normalised_tree(view.step, self.key)
        seen = self.first.get(view.key)
        if seen is None:
            self.first[view.key] = (tree, list(path))
            return
        if seen[0] == tree:
            return
        at = next((i for i, (a, b) in enumerate(zip(seen[0], tree)) if a != b), min(len(seen[0]), len(tree)))
        observed = {"witness_path": seen[1], "first_differing_node": at,
                    "witness_node": seen[0][at] if at < len(seen[0]) else None,
                    "node": tree[at] if at < len(tree) else None}
        self.found.append(make("key-too-coarse", [view.key], view.key, view.origin_ms, path, observed))
