"""Findings, pending values, exceptions, vacuity and the judge set of the ui-scene, ui-fit and ui-render judges (U06,
U07, P004 3.1, 3.2, 3.3, 4.5, 6.4).

A finding has the schema of docs/ui-explore.md ("Findings"); its id is `<gate>.<check>/<12 hex>` of sha256 over the
canonical JSON of [gate, check, [identity, state key]] ([gate, check, identity] for findings about the contract or the
run). Identities name scene nodes by key and rendered nodes without a scene node by class, box and a hash of their
text, never by walk index or exploration order. `observed` holds gate text, numbers and keys, never a label text.

`contract-pending`: identity [check, entry], one per check and entry per run; only what needs the value is skipped.
Exceptions: a live `[[exception]]` row (its expiry compared with `--today`, never the wall clock) turns exactly the
finding with its check and target into `info`. At the end of the run: `exception-unused` for an exception that turned
nothing (error when its target was visited or it expired, info otherwise), one `checks-examined` (info) per judge with
the verdicts each check reached per state (a node skipped for a pending or missing contract value is no verdict), and
`check-vacuous` (error) for a check that applies to the contract and reached no verdict in any state.
"""

from rigor_lib import jsonio, ui_contract, ui_judge_fit, ui_judge_render, ui_judge_scene
from rigor_lib.errors import InternalError
from rigor_lib.ui_explore_judges import PRIVATE, state_of
from rigor_lib.ui_judge_context import Context

SCENE_NODE_CHECKS = ("occluded-target", "overlay-policy", "touch-target-small", "target-spacing", "node-out-of-bounds",
                     "text-overlap", "font-below-min", "hierarchy-violated", "raw-text", "wrap-policy-undeclared",
                     "toggle-group-indistinct")
FIT_NODE_CHECKS = ("text-overflow", "text-clipped", "full-string-shown", "fit-unmeasurable", "glyph-missing",
                   "font-shrunk")
RENDER_NODE_CHECKS = ("invisible-node", "contrast-low", "ink-unmeasurable", "flag-mismatch", "align-mismatch",
                      "line-height-mismatch")
COMMON = ("stage-unmatched", "stage-text-mismatch", "stage-unowned-target", "scene-vocabulary", "contract-incomplete", "contract-pending",
          "exception-unused", "checks-examined", "check-vacuous")
NODE_CHECKS = {"ui-scene": SCENE_NODE_CHECKS, "ui-fit": FIT_NODE_CHECKS, "ui-render": RENDER_NODE_CHECKS}
GATES = {gate: checks + COMMON for gate, checks in NODE_CHECKS.items()}
ORDER = ("ui-scene", "ui-fit", "ui-render")   # the stage findings belong to the first selected gate in this order
MODULES = {"ui-scene": ui_judge_scene, "ui-fit": ui_judge_fit, "ui-render": ui_judge_render}
LAYERS = {"stage-unmatched": "L3", "stage-text-mismatch": "L3", "stage-unowned-target": "L3", "font-shrunk": "L3",
          "flag-mismatch": "L3", "align-mismatch": "L3", "line-height-mismatch": "L3"}
INK_GATES = frozenset(("ui-render",))         # the judges that need the probe's `ink` (U07)
META = frozenset(("scene-vocabulary", "contract-incomplete", "contract-pending", "exception-unused", "checks-examined",
                  "check-vacuous"))


def finding_id(gate, check, identity):
    return "%s.%s/%s" % (gate, check, jsonio.sha256_hex(jsonio.canonical_dumps([gate, check, identity]))[:12])


def _item(gate, check, identity, severity, state, path, observed):
    return {"id": finding_id(gate, check, identity), "gate": gate, "check": check,
            "layer": "meta" if check in META else LAYERS.get(check, "L4"), "severity": severity, "state": state,
            "path": list(path), "observed": observed, "blame": [], "evidence": [], "explanation": None}


def applies(check, contract):
    """Whether the contract declares what a check applies to (a check that never examines a node is then vacuous)."""
    if check in ("touch-target-small", "occluded-target", "target-spacing"):
        return any(row["touch_dp_min"] > 0 for row in contract.rows("role_min"))
    if check == "overlay-policy":
        return bool(contract.rows("input_layer"))
    if check == "toggle-group-indistinct":
        return bool(contract.rows("toggle_group"))
    return bool(contract.rows("role"))


class Exceptions:
    """The contract's exceptions for the selected gates, which of them turned a finding, whose target was seen."""

    def __init__(self, contract, gates, today):
        checks = {check for gate in gates for check in GATES[gate]}
        rows = [row for row in contract.tables["exception"] if row["rule"] in checks]
        live = {row["id"] for row in contract.active_exceptions(today)}
        self.active = {}
        for row in sorted((r for r in rows if r["id"] in live), key=lambda r: r["id"]):
            self.active.setdefault((row["rule"], row["target"]), []).append(row)   # a duplicate stays unused
        self.expired = [row for row in rows if row["id"] not in live]
        self.targets = sorted({row["target"] for row in rows})
        self.used, self.visited = set(), set()

    def see(self, names):
        """Mark the targets one state shows: a name of it, or a pair `a/b` of two names of that same state."""
        for target in self.targets:
            if target in names or (target.count("/") == 1 and set(target.split("/")) <= names):
                self.visited.add(target)

    def apply(self, item, target):
        rows = self.active.get((item["check"], target)) if target is not None else None
        if not rows:
            return item
        row = rows[0]
        self.used.add(row["id"])
        item["severity"] = "info"
        item["observed"] = dict(item["observed"], exception={"id": row["id"], "expires": str(row["expires"])})
        return item

    def unused(self):
        rows = [(row, False) for group in self.active.values() for row in group if row["id"] not in self.used]
        rows += [(row, True) for row in self.expired]
        return sorted(rows, key=lambda pair: pair[0]["id"])


class Reporter:
    """Builds the findings of one step for one gate; the step's state, path and the exceptions are bound."""

    def __init__(self, gate, judges, step, path):
        self.gate, self.judges, self.found = gate, judges, []
        self.state = state_of(step.key, step.proj, judges.catalogue_key, step.origin)
        self.state_key = step.key
        self.path = [view.word for view in path] + [step.word]
        self.counts = {}
        self.pendings = set()

    def add(self, check, identity, observed, target=None, severity=None, records=None, stateless=False):
        if check not in GATES[self.gate]:
            raise ValueError("unknown check %r of %s" % (check, self.gate))
        item = _item(self.gate, check, identity if stateless else [identity, self.state_key],
                     severity or "error", None if stateless else self.state, self.path, observed)
        if records:
            item[PRIVATE] = {"records.json": {"records": list(records)}}
        self.found.append(self.judges.exceptions.apply(item, target))

    def examined(self, check, count=1):
        self.counts[check] = self.counts.get(check, 0) + count

    def pending(self, check, error):
        """`contract-pending` for one check and entry (identity [check, entry]), once per step."""
        if (check, error.path) in self.pendings:
            return
        self.pendings.add((check, error.path))
        self.add("contract-pending", [check, error.path],
                 {"check": check, "entry": error.path, "question": error.question}, stateless=True,
                 severity=ui_contract.PENDING_SEVERITY)

    def incomplete(self, what, name):
        self.add("contract-incomplete", [what, name], {"what": what, "name": name}, stateless=True)


class JudgeSet:
    """The selected judges: one step judge for the explorer, and `finish` for the run-level findings."""

    def __init__(self, gates, contract, catalogue_key, today):
        if contract is None:
            raise InternalError("--judges %s need --contract (the UI contract)" % ",".join(gates))
        if today is None:
            raise InternalError("--judges need --today YYYY-MM-DD (the date exceptions expire against)")
        unknown = [g for g in gates if g not in GATES]
        if unknown or len(set(gates)) != len(gates) or not gates:
            raise InternalError("--judges: distinct names of %s" % ", ".join(ORDER))
        self.gates = tuple(g for g in ORDER if g in gates)
        self.contract, self.catalogue_key = contract, catalogue_key
        self.exceptions = Exceptions(contract, self.gates, today)
        self.examined = {gate: {} for gate in self.gates}       # gate -> state key -> check -> nodes
        self.needs_ink = bool(INK_GATES & set(self.gates))     # the explorer then inks each new state (U07)

    def step_judge(self, step, path, contract):
        del contract
        context = Context(self, step)
        names = set(context.by_key) | {context.rendered_name(i)["target"] for i in context.frame.labels
                                       if i not in context.assoc.owner}
        self.exceptions.see(names)
        out = context.stage_findings(Reporter(self.gates[0], self, step, path))
        for gate in self.gates:
            report = Reporter(gate, self, step, path)
            out += MODULES[gate].judge(context, report)
            seen = self.examined[gate].setdefault(step.key, {})
            for check in NODE_CHECKS[gate]:
                seen[check] = max(seen.get(check, 0), report.counts.get(check, 0))
        return out

    def finish(self, open_word):
        """The run-level findings (path: the open word; state: null)."""
        out = []
        for row, expired in self.exceptions.unused():
            gate = next(g for g in self.gates if row["rule"] in GATES[g])
            visited = row["target"] in self.exceptions.visited
            out.append(_item(gate, "exception-unused", ["exception", row["id"]],
                             "error" if visited or expired else "info", None, [open_word],
                             {"exception": row["id"], "rule": row["rule"], "target": row["target"],
                              "expires": str(row["expires"]), "expired": expired, "target_visited": visited}))
        for gate in self.gates:
            states = self.examined[gate]
            totals = {check: sum(s.get(check, 0) for s in states.values()) for check in NODE_CHECKS[gate]}
            out.append(_item(gate, "checks-examined", ["examined"], "info", None, [open_word],
                             {"states": len(states), "totals": totals,
                              "per_state": {key: states[key] for key in sorted(states)}}))
            for check in NODE_CHECKS[gate]:
                if states and totals[check] == 0 and applies(check, self.contract):
                    out.append(_item(gate, "check-vacuous", ["vacuous", check], "error", None, [open_word],
                                     {"check": check, "states": len(states)}))
        return out
