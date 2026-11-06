"""Gate-owned third-party libraries (`third_party/`): what the gate trusts without scanning.

Two plain-text lists live next to the vendored code and are read, never executed:

* `ALLOWED_LABELS`: one exact label per line (`gate//third_party/<dir>:<name>`). A product `BUCK` may
  name exactly these as `deps`; a facts file of kind `c_third_party` is trusted only for these.
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
PREFIXES_FILE = "RESERVED_PREFIXES"
GATE_PREFIX = "gate"

LABEL = re.compile(r"gate//third_party/[a-z0-9_]+:[a-z0-9_]+")
PREFIX = re.compile(r"[A-Za-z][A-Za-z0-9]*_")

DEFAULT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                           "third_party")


@dataclass(frozen=True)
class ThirdParty:
    allowed: frozenset
    prefixes: tuple


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
    return ThirdParty(load_allowed_labels(os.path.join(directory, ALLOWED_FILE)),
                      _lines(os.path.join(directory, PREFIXES_FILE), PREFIX, "prefix"))


def split(facts_by_label, third):
    """(product facts, trusted third-party facts, findings). A `c_third_party` facts file whose
    label the allowlist does not name is a finding and is not trusted (it is dropped)."""
    products, trusted, found = {}, {}, []
    for label in sorted(facts_by_label):
        facts = facts_by_label[label]
        if facts.kind != KIND:
            products[label] = facts
        elif canonical(label) in third.allowed:
            trusted[label] = facts
        else:
            found.append(finding("third-party-not-allowed", target=label))
    return products, trusted, found


def check_policy(policy, third):
    """Policy defects are exit 2: permissions for labels the gate does not allow, or a module entry
    for a trusted library."""
    for label, module in sorted(policy.modules.items()):
        outside = sorted(module.third_party - third.allowed)
        if outside:
            raise InternalError("policy: module %s permits third-party labels the gate does not allow: %s"
                                % (label, outside))
        if canonical(label) in third.allowed:
            raise InternalError("policy: %s is a trusted third-party library, not a module" % label)
