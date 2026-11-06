"""Gate-owned third-party libraries (`third_party/`): what the gate trusts without scanning.

Two plain-text lists live next to the vendored code and are read, never executed:

* `ALLOWED_LABELS`: one exact label per line (`gate//third_party/<dir>:<name>`). A product `BUCK` may
  name exactly these as `deps`; a facts file of kind `c_third_party` is trusted only for these.
* `ALLOWED_TEST_LABELS`: the same format, for libraries only a `c_test` may depend on (the TLS test
  peer). Disjoint from `ALLOWED_LABELS`. Trusted like the others (not scanned), but a non-test
  target that reaches one through any chain of deps is a `test-only-dep` finding (`facts_symbols`).
* `RESERVED_PREFIXES`: one prefix per line (`mbedtls_`). A product may not define an external symbol
  that starts with one, whether or not it depends on the library.

Both are strict (no comments, no blank lines, no duplicates, no symlink, a final newline); any
defect is exit 2. The exports of a trusted library come from its `_facts` target (computed by the
build from the objects), never from a list written by hand.
"""

import os
import re
from dataclasses import dataclass

from rigor_lib.errors import InternalError
from rigor_lib.findings import finding

KIND = "c_third_party"
ALLOWED_FILE = "ALLOWED_LABELS"
TEST_ALLOWED_FILE = "ALLOWED_TEST_LABELS"
PREFIXES_FILE = "RESERVED_PREFIXES"
GATE_PREFIX = "gate"

LABEL = re.compile(r"gate//third_party/[a-z0-9_]+:[a-z0-9_]+")
PREFIX = re.compile(r"[A-Za-z][A-Za-z0-9_]*_")

DEFAULT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                           "third_party")


@dataclass(frozen=True)
class ThirdParty:
    allowed: frozenset
    prefixes: tuple
    test_allowed: frozenset = frozenset()

    @property
    def trusted(self):
        return self.allowed | self.test_allowed


def canonical(label):
    """The `gate//` spelling of a label a gate-cell target prints (`//x:y` when the gate is the root)."""
    return GATE_PREFIX + label if label.startswith("//") else label


def _lines(path, pattern, what):
    if os.path.islink(path) or not os.path.isfile(path):
        raise InternalError("%s: not a regular file" % path)
    with open(path, "rb") as handle:
        raw = handle.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InternalError("%s: not UTF-8" % path) from exc
    if text == "":
        return ()
    if not text.endswith("\n"):
        raise InternalError("%s: missing final newline" % path)
    lines = text[:-1].split("\n")
    for line in lines:
        if not pattern.fullmatch(line):
            raise InternalError("%s: not a valid %s: %r" % (path, what, line))
    if len(set(lines)) != len(lines):
        raise InternalError("%s: duplicate entry" % path)
    return tuple(lines)


def load_allowed_labels(path):
    return frozenset(_lines(path, LABEL, "label"))


def load(directory=None):
    directory = DEFAULT_DIR if directory is None else directory
    if not os.path.isdir(directory):
        raise InternalError("third-party directory not found: %s" % directory)
    allowed = load_allowed_labels(os.path.join(directory, ALLOWED_FILE))
    test_allowed = load_allowed_labels(os.path.join(directory, TEST_ALLOWED_FILE))
    if allowed & test_allowed:
        raise InternalError("%s and %s share an entry: %s" % (ALLOWED_FILE, TEST_ALLOWED_FILE,
                                                              sorted(allowed & test_allowed)))
    return ThirdParty(allowed, _lines(os.path.join(directory, PREFIXES_FILE), PREFIX, "prefix"), test_allowed)


def split(facts_by_label, third):
    """(product facts, trusted third-party facts, findings). A `c_third_party` facts file whose
    label the allowlist does not name is a finding and is not trusted (it is dropped)."""
    products, trusted, found = {}, {}, []
    for label in sorted(facts_by_label):
        facts = facts_by_label[label]
        if facts.kind != KIND:
            products[label] = facts
        elif canonical(label) in third.trusted:
            trusted[label] = facts
        else:
            found.append(finding("third-party-not-allowed", target=label))
    return products, trusted, found


def check_policy(policy, third):
    """Policy defects are exit 2: permissions for labels the gate does not allow, or a module entry
    for a trusted library."""
    for label, module in sorted(policy.modules.items()):
        outside = sorted(module.third_party - third.trusted)
        if outside:
            raise InternalError("policy: module %s permits third-party labels the gate does not allow: %s"
                                % (label, outside))
        if canonical(label) in third.trusted:
            raise InternalError("policy: %s is a trusted third-party library, not a module" % label)


def test_only_findings(products, third):
    """`test-only-dep`: a target that is not a `c_test` and reaches a test-only library through its deps,
    directly or through any chain of product targets (a test target included). A dep with no facts that
    names a test-only label counts too (fail closed)."""
    found = []
    for label in sorted(products):
        if products[label].kind == "c_test":
            continue
        seen, hits, stack = set(), set(), list(products[label].deps)
        while stack:
            dep = stack.pop()
            if dep in seen:
                continue
            seen.add(dep)
            if canonical(dep) in third.test_allowed:
                hits.add(dep)
            elif dep in products:
                stack.extend(products[dep].deps)
        found.extend(finding("test-only-dep", target=label, dep=dep) for dep in sorted(hits))
    return found
