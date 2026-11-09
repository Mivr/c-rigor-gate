#!/usr/bin/env python3
"""Which selftests must run for a change (T044). Stdlib only; run as `python3 -I tools/affected.py ...`.

    tools/affected.py [--why] BASE HEAD   print the selftests to run for BASE..HEAD, one per line
    tools/affected.py --check             every tracked file must match a rule other than a catch-all

The map is tools/affected.toml: ordered rules, the first matching rule decides a path. Fails closed: a changed path
that no rule matches selects every selftest. `gate` is always selected. See docs/validation.md.
"""

import os
import re
import subprocess
import sys
import tomllib

ALL = (
    "gate", "grade", "mutate", "structure", "product_checks", "toolchain", "ctest", "fuzz", "third_party",
    "canaries", "tripwires", "trajectory_real", "perf", "profiles",
)
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RULES_FILE = os.path.join(HERE, "affected.toml")
CATCH_ALL = "**"


def glob_regex(glob):
    """`*` and `?` stay inside a path segment, `**` crosses segments; the pattern covers the whole path."""
    out = []
    i = 0
    while i < len(glob):
        c = glob[i]
        if glob.startswith("**", i):
            out.append(".*")
            i += 2
            continue
        if c == "*":
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(c))
        i += 1
    return re.compile("".join(out) + r"\Z")


# The tripwire pack (T086) runs wherever the canary pack runs ("tripwires" is added to every rule that selects
# "canaries"), plus on its own files. These rules sit before the rules file, which names only the canary pack.
TRIPWIRE_RULES = (("tripwires/**", frozenset({"tripwires"})), ("selftest/tripwires.sh", frozenset({"tripwires"})))


def load_rules(path=RULES_FILE):
    """Parse the rules file into [(glob, regex, frozenset(selftests))]; a bad entry is an error, never skipped."""
    with open(path, "rb") as handle:
        data = tomllib.load(handle)
    rules = []
    for entry in data.get("rule", []):
        if set(entry) != {"glob", "selftests"}:
            raise ValueError("rule needs exactly glob and selftests: %r" % (entry,))
        names = set()
        for name in entry["selftests"]:
            if name == "all":
                names.update(ALL)
            elif name in ALL:
                names.add(name)
            else:
                raise ValueError("unknown selftest %r in rule %r" % (name, entry["glob"]))
        if "canaries" in names:
            names.add("tripwires")
        rules.append((entry["glob"], glob_regex(entry["glob"]), frozenset(names)))
    return [(glob, glob_regex(glob), names) for glob, names in TRIPWIRE_RULES] + rules


def match_rule(rules, path):
    """The first rule matching `path`, or None."""
    for rule in rules:
        if rule[1].match(path):
            return rule
    return None


def select(paths, rules):
    """(selected set, {selftest: first reason}) for the changed paths. `gate` is always in."""
    chosen = {"gate"}
    why = {"gate": "always"}
    for path in paths:
        rule = match_rule(rules, path)
        if rule is None:
            names, reason = set(ALL), "%s: no rule matches (fail closed)" % path
        else:
            names, reason = rule[2], "%s: rule %s" % (path, rule[0])
        for name in sorted(names):
            if name not in chosen:
                why[name] = reason
        chosen |= names
    return chosen, why


def unmatched(paths, rules):
    """Paths with no rule, or only a catch-all rule."""
    bad = []
    for path in paths:
        rule = match_rule(rules, path)
        if rule is None or rule[0] == CATCH_ALL:
            bad.append(path)
    return bad


def git_lines(args):
    done = subprocess.run(["git", "-C", ROOT] + args, capture_output=True, check=False)
    if done.returncode != 0:
        sys.stderr.write("affected.py: git %s failed: %s\n" % (" ".join(args), done.stderr.decode(errors="replace").strip()))
        sys.exit(2)
    return [p.decode("utf-8", "surrogateescape") for p in done.stdout.split(b"\0") if p]


def changed_paths(base, head):
    """Every path touched between the two commits; a rename counts as both its old and new path."""
    return git_lines(["diff", "--name-only", "--no-renames", "-z", base, head, "--"])


def main(argv):
    why = "--why" in argv
    check = "--check" in argv
    rest = [a for a in argv if a not in ("--why", "--check")]
    try:
        rules = load_rules()
    except (OSError, ValueError, tomllib.TOMLDecodeError) as err:
        sys.stderr.write("affected.py: bad rules file: %s\n" % err)
        return 2
    if check:
        if rest:
            sys.stderr.write("usage: affected.py --check\n")
            return 2
        bad = unmatched(git_lines(["ls-files", "-z"]), rules)
        for path in bad:
            print(path)
        if bad:
            sys.stderr.write("affected.py: %d tracked file(s) match no specific rule\n" % len(bad))
            return 1
        print("affected.py: every tracked file matches a rule")
        return 0
    if len(rest) != 2:
        sys.stderr.write("usage: affected.py [--why] BASE HEAD | --check\n")
        return 2
    chosen, reasons = select(changed_paths(rest[0], rest[1]), rules)
    for name in ALL:
        if name in chosen:
            print("%s\t%s" % (name, reasons[name]) if why else name)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
