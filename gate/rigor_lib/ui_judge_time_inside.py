"""What is shown only INSIDE one time step, for the `ui-time` judge (U09 fix-up 2, docs/ui-judges-time.md "The
time-probing mode"): a time step whose patches create and then remove one key showed something no step end shows. Its
samples (ui_judge_time_probe.Prober.inside) give every element instance seen only inside the step (a timed kind, told
apart by its instance signature) and every created-and-removed key that no such instance's scope holds (a plain node:
only `flash` applies); both edges of each come from the samples, and each rule is decided, or undecided."""

from rigor_lib.ui_judge_time_checks import decisions, refine
from rigor_lib.ui_judge_time_probe import edges, keyed


def hidden_pairs(facts):
    """{step index: [(key, role)]}: time steps (longer than one ms, patches that agree with the records) whose patches
    create and then remove one key."""
    out = {}
    for index in range(1, len(facts)):
        fact, created = facts[index], {}
        if fact.mode != "time" or fact.chain or fact.now - fact.prev_now <= 1:
            continue
        for op, key, _name, old, new in fact.patches:
            if op == "create":
                created[key] = new.decode("ascii", "replace")
            elif op == "remove" and key in created:
                out.setdefault(index, []).append((key, created.pop(key)))
    return out


def _shows(fact, kind, sig):
    return kind in fact.present and fact.sigs.get(kind) == sig


def elements(samples, before, step, pairs):
    """[(name, kind or None, points)]: each instance seen only inside the step (name `<kind>#<n>`), then each created-
    and-removed key seen in a sample that no such instance's scope holds (name the key, kind None)."""
    instances, mapped, out = [], set(), []
    for _at, fact in sorted(samples.items()):
        for kind in sorted(fact.present):
            sig = fact.sigs.get(kind)
            if (kind, sig) not in instances and not _shows(before, kind, sig) and not _shows(step, kind, sig):
                instances.append((kind, sig))
    for n, (kind, sig) in enumerate(instances):
        out.append(("%s#%d" % (kind, n), kind, [(at, _shows(f, kind, sig)) for at, f in sorted(samples.items())]))
        mapped |= {key for f in samples.values() if _shows(f, kind, sig) for key in f.scopes.get(kind, ())}
    for key, _role in pairs:
        if key not in mapped and any(key in f.labels for f in samples.values()):
            out.append((key, None, keyed(samples, [key])[0]))
    return out


def judge(element, before, step, limits):
    """(decisions, (above, at_most), (appear, gone)) of one element; `limits(kind)` gives (L, D, floor, tick) of a
    kind, `limits(None)` the flash threshold (or None). Flash applies to every element (P004 3.5: any non-countdown
    element), the lifetime rules to a timed instance."""
    _name, kind, points = element
    (lo, first), gone = edges(points, before.now, step.now)
    appear = (lo + 1, first)
    found, bounds = decisions(appear, gone, *limits(kind)) if kind is not None else \
        ({}, (gone[0] - appear[1], gone[1] - appear[0]))
    threshold = limits(None)
    if threshold is not None:
        found["flash"] = True if bounds[1] < threshold else (False if bounds[0] + 1 >= threshold else None)
    return found, bounds, (appear, gone)


def wanted(samples, before, step, pairs, limits, max_wait):
    """The instants that would narrow the edges of every element whose rules are still undecided."""
    out = set()
    for element in elements(samples, before, step, pairs):
        found, _bounds, (appear, gone) = judge(element, before, step, limits)
        if None in found.values():
            out |= set(refine(appear[0] - 1, appear[1], max_wait)) | set(refine(gone[0], gone[1], max_wait))
    return sorted(out)[:15]
