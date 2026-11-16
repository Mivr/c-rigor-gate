"""What is shown only INSIDE one time step, for the `ui-time` judge (U09 fix-up 2, docs/ui-judges-time.md "The
time-probing mode"): a time step whose patches create and then remove one key showed something no step end shows. Its
samples (ui_judge_time_probe.Prober.inside) give every element instance seen only inside the step (a timed kind, told
apart by its instance signature) and every created-and-removed key that no such instance's scope holds (a plain node:
only `flash` applies); both edges of each come from the samples, and each rule is decided, or undecided."""

from rigor_lib.ui_judge_time_checks import decisions, refine
from rigor_lib.ui_judge_time_probe import edges, keyed, seen


def hidden_pairs(facts):
    """{step index: [(key, role, text)]}: time steps (longer than one ms, patches that agree with the records) whose
    patches create and then remove one key (text None), or update one key's text and then back to the text it had
    (text: the one shown only inside the step: a text-only flash)."""
    out = {}
    for index in range(1, len(facts)):
        fact, created, texts = facts[index], {}, {}
        if fact.mode != "time" or fact.chain or fact.now - fact.prev_now <= 1:
            continue
        for op, key, name, old, new in fact.patches:
            if op == "create":
                created[key] = new.decode("ascii", "replace")
            elif op == "remove" and key in created:
                out.setdefault(index, []).append((key, created.pop(key), None))
            elif op == "update" and name == "text" and key not in created:
                first = texts.setdefault(key, (old, new))
                if new == first[0] and (key, first[1]) not in [(k, t) for k, _r, t in out.get(index, ())]:
                    role = fact.rolemap.get(key, ("text",))[0]
                    if role != "countdown":
                        out.setdefault(index, []).append((key, role, first[1]))
                    del texts[key]
    return out


def _plain(roles):
    return tuple(sorted((key, shown) for key, shown in roles.items() if shown[0] != "countdown"))


def _sig(fact, kind):
    """What tells one instance of a kind from another across runs: its topmost scope's keys, roles and labels (its
    countdown nodes aside, as instances are followed: ui_judge_time_model)."""
    return _plain(fact.roles.get(kind, {}))


def _shows(fact, kind, sig):
    """Whether `fact` shows the instance `sig` of `kind`, topmost or covered (its nodes as they were)."""
    return kind in fact.present and any(_plain(roles) == sig for _i, roles in fact.tracked.get(kind, ()))


def elements(samples, before, step, pairs):
    """[(name, kind or None, points)]: each instance seen only inside the step (name `<kind>#<n>`), then each created-
    and-removed key seen in a sample that no such instance's scope holds (name the key, kind None)."""
    instances, mapped, out = [], set(), []
    for _at, fact in sorted(samples.items()):
        for kind in sorted(fact.present):
            sig = _sig(fact, kind)
            if (kind, sig) not in instances and not _shows(before, kind, sig) and not _shows(step, kind, sig):
                instances.append((kind, sig))
    for n, (kind, sig) in enumerate(instances):
        if not sig:
            continue                       # a kind with no node of its own in its scope: nothing to follow
        out.append(("%s#%d" % (kind, n), kind, [(at, _shows(f, kind, sig)) for at, f in sorted(samples.items())]))
        mapped |= {key for f in samples.values() if _shows(f, kind, sig) for key in f.scopes.get(kind, ())}
    for pair in pairs:
        key, _role, text = pair
        if (text is not None or key not in mapped) and any(seen(f, pair) for f in samples.values()):
            out.append((key if text is None else key + "@text", None, keyed(samples, [pair])[0]))
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
