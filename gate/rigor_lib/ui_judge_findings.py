"""Findings, pending values, exceptions and the judge set of the ui-scene and ui-fit judges (U06, P004 3.1, 3.2, 4.5).

A finding has the schema of docs/ui-explore.md ("Findings"); its id is `<gate>.<check>/<12 hex>` of sha256 over the
canonical JSON of [gate, check, identity]. Identities name scene nodes by their key, rendered nodes no scene node owns by
their walk index, and states by the abstraction key, never by exploration order. `observed` holds gate text, numbers and
scene keys only, never a label text; the records involved go to the evidence (`records.json`).

`contract-pending` (P004 6.2, docs/ui-contract.md): a check that needs a value the owner has not decided reports it with
identity [check, entry], so the explorer's de-duplication leaves one per check and entry for the whole run, and skips
only that check (or that part of it). Its severity is the loader's (`PENDING_SEVERITY`).

Exceptions: a contract `[[exception]]` row that has not expired on the run's date (UTC) turns exactly the finding with
its check and target into severity `info`, with the exception's id and expiry in `observed.exception`. At the end, every
exception whose rule is a check of a selected judge and that turned nothing (or has expired) is `exception-unused`.
"""

import datetime

from rigor_lib import jsonio, ui_contract, ui_judge_fit, ui_judge_scene
from rigor_lib.errors import InternalError
from rigor_lib.ui_judge_context import Context
from rigor_lib.ui_explore_judges import PRIVATE, state_of

SCENE_CHECKS = ("occluded-target", "overlay-policy", "touch-target-small", "target-spacing", "node-out-of-bounds",
                "text-overlap", "font-below-min", "hierarchy-violated", "raw-text", "wrap-policy-undeclared",
                "stage-unmatched", "scene-vocabulary", "contract-incomplete", "contract-pending", "exception-unused")
FIT_CHECKS = ("text-overflow", "text-clipped", "full-string-shown", "fit-unmeasurable", "glyph-missing",
              "stage-unmatched", "scene-vocabulary", "contract-pending", "exception-unused")
GATES = {"ui-scene": SCENE_CHECKS, "ui-fit": FIT_CHECKS}
ORDER = ("ui-scene", "ui-fit")          # the stage findings belong to the first selected gate in this order
LAYERS = {"stage-unmatched": "L3", "scene-vocabulary": "meta", "contract-incomplete": "meta",
          "contract-pending": "meta", "exception-unused": "meta"}       # every other check: L4 (P004 3.1, 3.2)
INFO = frozenset(("stage-unmatched",))


def finding_id(gate, check, identity):
    return "%s.%s/%s" % (gate, check, jsonio.sha256_hex(jsonio.canonical_dumps([gate, check, identity]))[:12])


class Exceptions:
    """The contract's exceptions for the selected gates, and which of them turned a finding."""

    def __init__(self, contract, gates, today):
        checks = {check for gate in gates for check in GATES[gate]}
        rows = [row for row in contract.tables["exception"] if row["rule"] in checks]
        live = {row["id"] for row in contract.active_exceptions(today)}
        self.active = {}
        for row in sorted((r for r in rows if r["id"] in live), key=lambda r: r["id"]):
            self.active.setdefault((row["rule"], row["target"]), []).append(row)   # a duplicate stays unused
        self.expired = [row for row in rows if row["id"] not in live]
        self.used = set()

    def apply(self, item, target):
        rows = self.active.get((item["check"], target)) if target is not None else None
        if not rows:
            return item
        row = rows[0]
        self.used.add(row["id"])
        expires = row["expires"]
        item["severity"] = "info"
        item["observed"] = dict(item["observed"], exception={"id": row["id"], "expires": str(expires)})
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

    def add(self, check, identity, observed, target=None, severity=None, records=None, stateless=False):
        if check not in GATES[self.gate]:
            raise ValueError("unknown check %r of %s" % (check, self.gate))
        item = {"id": finding_id(self.gate, check, identity if stateless else [identity, self.state_key]),
                "gate": self.gate, "check": check, "layer": LAYERS.get(check, "L4"),
                "severity": severity or ("info" if check in INFO else "error"),
                "state": None if stateless else self.state, "path": list(self.path), "observed": observed,
                "blame": [], "evidence": [], "explanation": None}
        if records:
            item[PRIVATE] = {"records.json": {"records": list(records)}}
        self.found.append(self.judges.exceptions.apply(item, target))

    def pending(self, check, error):
        """`contract-pending` for one check and entry: once per run whatever the state (identity [check, entry])."""
        self.add("contract-pending", [check, error.path],
                 {"check": check, "entry": error.path, "question": error.question}, stateless=True,
                 severity=ui_contract.PENDING_SEVERITY)


class JudgeSet:
    """The selected judges: one step judge for the explorer, and `finish` for the run-level findings."""

    def __init__(self, gates, contract, catalogue_key, today=None):
        if contract is None:
            raise InternalError("--judges %s need --contract (the UI contract)" % ",".join(gates))
        unknown = [g for g in gates if g not in GATES]
        if unknown or len(set(gates)) != len(gates) or not gates:
            raise InternalError("--judges: distinct names of %s" % ", ".join(ORDER))
        self.gates = tuple(g for g in ORDER if g in gates)
        self.contract, self.catalogue_key = contract, catalogue_key
        today = today or datetime.datetime.now(datetime.timezone.utc).date()
        self.exceptions = Exceptions(contract, self.gates, today)

    def step_judge(self, step, path, contract):
        del contract
        context = Context(self, step)
        out = context.stage_findings(Reporter(self.gates[0], self, step, path))
        if "ui-scene" in self.gates:
            out += ui_judge_scene.judge(context, Reporter("ui-scene", self, step, path))
        if "ui-fit" in self.gates:
            out += ui_judge_fit.judge(context, Reporter("ui-fit", self, step, path))
        return out

    def finish(self, open_word):
        """`exception-unused` for every exception of a selected gate's check that turned no finding or has expired."""
        out = []
        for row, expired in self.exceptions.unused():
            gate = next(g for g in self.gates if row["rule"] in GATES[g])
            identity = ["exception", row["id"]]
            out.append({"id": finding_id(gate, "exception-unused", identity), "gate": gate,
                        "check": "exception-unused", "layer": "meta", "severity": "error", "state": None,
                        "path": [open_word],
                        "observed": {"exception": row["id"], "rule": row["rule"], "target": row["target"],
                                     "expires": str(row["expires"]), "expired": expired},
                        "blame": [], "evidence": [], "explanation": None})
        return out
