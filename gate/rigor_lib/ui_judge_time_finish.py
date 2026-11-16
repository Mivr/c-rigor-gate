"""The end of a run of the `ui-time` judge (U09, docs/ui-judges-time.md): the run-level findings: `contract-pending`, `contract-incomplete` (a countdown label of no known format),
`exception-unused`, `check-blocked`, `time-probes-capped` (info), `checks-examined` (info) and `check-vacuous`. Path:
the open word; state: null. (The waiting origin replays run before, in the explorer's budget: `TimeJudge.fill`.)"""

from rigor_lib.ui_judge_time import CHECKS, item
from rigor_lib.ui_judge_time_model import Binding

BLOCKED_PARTS = {      # what the gate has no fact for (the honesty table of docs/ui-judges-time.md)
    "countdown-wrong": "the formatted string against the oracle's at the same virtual time: no oracle in the gate",
    "flash": "life lines: no object identity, and node -1 also marks an event after a retried walk",
    "invisible-auto-transition": "a user-relevant O1 (view-state) field: the probe protocol has no view-state stage",
    "unresponsive-intent": "the contract does not mark which intents are effective in which state class",
}


def _run_level(judge, binding, open_word):
    out = list(judge.pendings.values()) + [judge.incomplete[kind] for kind in sorted(judge.incomplete)]
    for row, expired in judge.exceptions.unused():
        visited = row["target"] in judge.exceptions.visited
        out.append(item("exception-unused", ["exception", row["id"]], "error" if visited or expired else "info",
                        None, [open_word], {"exception": row["id"], "rule": row["rule"], "target": row["target"],
                                            "expires": str(row["expires"]), "expired": expired,
                                            "target_visited": visited}))
    out += [item("check-blocked", ["blocked", check, kind], "error", None, [open_word],
                 {"check": check, "kind": kind, "needs": "identity"}) for check, kind in blocked(binding)]
    if judge.identity is False:
        out.append(item("check-blocked", ["blocked", "invisible-auto-transition"], "error", None, [open_word],
                        {"check": "invisible-auto-transition", "needs": "identity"}))
    if judge.capped:
        out.append(item("time-probes-capped", ["capped"], "info", None, [open_word],
                        {"first": judge.capped[0], "capped": len(judge.capped), "probes": len(judge.probed)}))
    return out


def finish(judge, open_word):
    binding = Binding(judge.contract, bool(judge.identity))
    out = _run_level(judge, binding, open_word)
    cost = dict(judge.runner.cost) if judge.runner is not None else {}
    out.append(item("checks-examined", ["examined"], "info", None, [open_word], {
        "paths": judge.paths, "totals": dict(judge.counts), "bound": list(binding.bound()),
        "blocked_kinds": list(binding.blocked()), "probes": len(judge.probed), "probes_capped": len(judge.capped),
        "origin_paths": len(judge.origins.done), "cost": cost, "blocked_parts": BLOCKED_PARTS,
        "lifetimes": sorted(judge.lifetimes, key=lambda r: (r["kind"], r["state"]))}))
    for check in CHECKS:
        if judge.paths and judge.counts[check] == 0 and not judge.pending(check) and applies(check, binding, judge):
            out.append(item("check-vacuous", ["vacuous", check], "error", None, [open_word],
                            {"check": check, "paths": judge.paths}))
    return out


def blocked(binding):
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


def applies(check, binding, judge):
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
    return check != "patches-inconsistent"        # a protocol check: no verdict means one-step paths only
