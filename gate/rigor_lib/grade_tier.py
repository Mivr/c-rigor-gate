"""Grade tiers (P003 section 9, T137): `merge` defers the mutation that can only report; `nightly` is the whole grade.

`rigor grade --tier merge|nightly` (default `nightly`, exactly the grade before tiers). The tier is bound into the
verdict's `core.inputs`, so a merge PASS and a nightly PASS differ. The one thing a tier changes today is which
modules the `mutants` and `mutants-witness` gates mutate (`split`); docs/grade.md has the table of what each tier runs.

A module is deferred at tier `merge` when no finding of its mutation can be an error: without a declared `profile`
that is level L2 (a survivor is info there); with one, the technique matrix decides (`profiles.required`): the module is
deferred unless `mutation_zero_survivors` is a `gate` at its level. A deferred module is not built and not run.
"""

from rigor_lib import grade_policy, policy_check, profiles
from rigor_lib.findings import SEVERITY_INFO, finding

MERGE = "merge"
NIGHTLY = "nightly"
TIERS = (MERGE, NIGHTLY)
DEFAULT = NIGHTLY
TECHNIQUE = "mutation_zero_survivors"
RULE = "mutation-deferred"


def tier_of(g):
    """The tier of the grading; callers that build args by hand may omit it (nightly)."""
    return getattr(g.args, "tier", None) or DEFAULT


def deferral(level, declared):
    """The reason a module at LEVEL with the DECLARED profiles (a tuple, or None) is deferred at tier `merge`, or None
    when its mutation can raise an error and must run. An unknown level or profile is never deferred (the policy gate
    reports it; here the safe side is to mutate)."""
    if declared is None:
        return "level L2: a surviving mutant is an info finding" if level == "L2" else None
    try:
        mode = profiles.required(declared, level).get(TECHNIQUE)
    except ValueError:
        return None
    if mode == profiles.GATE:
        return None
    where = "reported" if mode == profiles.REPORT else "not applied"
    return "profile %s at %s: %s is %s" % ("+".join(declared), level, TECHNIQUE, where)


def declared_profiles(path):
    """{module label: tuple of declared profiles} of the policy file at PATH (modules without `profile` are absent)."""
    found = {}
    for label, table in grade_policy.module_tables(grade_policy.load_document(path)).items():
        names = policy_check.declared_profiles(label, table)
        if names is not None:
            found[label] = names
    return found


def split(g, modules):
    """(modules to mutate, [(module, reason)] deferred) for the grading G. Nothing is deferred at tier `nightly`."""
    if tier_of(g) != MERGE:
        return list(modules), []
    declared = declared_profiles(grade_policy.policy_path(g))
    kept, deferred = [], []
    for module in modules:
        reason = deferral(module.level, declared.get(module.label))
        if reason is None:
            kept.append(module)
        else:
            deferred.append((module, reason))
    return kept, deferred


def findings(deferred):
    """One info `mutation-deferred` finding per deferred module."""
    return [finding(RULE, SEVERITY_INFO, module=m.label, level=m.level, reason=reason) for m, reason in deferred]


def metadata(g, deferred):
    """Gate metadata about the tier: empty at `nightly`, so that grade's results stay byte-for-byte what they were."""
    return {"tier": MERGE, "deferred": len(deferred)} if tier_of(g) == MERGE else {}
