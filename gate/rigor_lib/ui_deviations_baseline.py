"""`ui_deviations_baseline`: the two owner-sealed files of `rigor ui-deviations` (strict loaders; any defect is exit 2).

`products/<product>/ui/deviations.toml` pins every accepted tag id with its `until` and the sha256 of its canonical fields;
`products/<product>/ui/deviation-sections.toml` pins, per header, the number of deviation entries the owner has
acknowledged (docs/ui-deviations.md). What the loaders return is immutable.
"""

import posixpath
import re
import tomllib
from dataclasses import dataclass
from types import MappingProxyType

from rigor_lib import jsonio, paths
from rigor_lib.errors import InternalError
from rigor_lib.ui_deviations_tags import DATE_RE, ID_RE, TASK_RE

SCHEMA = "ui-deviations/2"
SECTIONS_SCHEMA = "ui-deviation-sections/1"
BASELINE_RELATIVE = "ui/deviations.toml"
SECTIONS_RELATIVE = "ui/deviation-sections.toml"
BASELINE_KEYS = ("schema", "product", "cap", "accepted", "reference_bug_link_prefix", "reference_bug_link_pattern")
ACCEPTED_KEYS = ("until", "sha256")
MAX_CAP = 1000
MAX_PATTERN = 200
MAX_ENTRIES = 999
_SHA = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class Baseline:
    product: str
    cap: int
    accepted: object          # MappingProxyType {id: (until, sha256)}
    link_prefix: str
    link_pattern: str


@dataclass(frozen=True)
class Expectation:
    product: str
    headers: object           # MappingProxyType {path: acknowledged entries}


def _read(path):
    try:
        return tomllib.loads(jsonio.read_bytes(path).decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as error:
        raise InternalError("%s: %s" % (path, error))


def _accepted(path, table, cap):
    if not isinstance(table, dict) or list(table) != sorted(table):
        raise InternalError("%s: accepted must be a table sorted by id" % path)
    out = {}
    for ident, entry in table.items():
        if not ID_RE.fullmatch(ident) or not isinstance(entry, dict) or set(entry) != set(ACCEPTED_KEYS):
            raise InternalError("%s: accepted.%s must hold exactly %s under a valid id" % (path, ident, list(ACCEPTED_KEYS)))
        until, digest = entry["until"], entry["sha256"]
        if type(until) is not str or not (DATE_RE.fullmatch(until) or TASK_RE.fullmatch(until)):
            raise InternalError("%s: accepted.%s.until is not a task id or an ISO date" % (path, ident))
        if type(digest) is not str or not _SHA.fullmatch(digest):
            raise InternalError("%s: accepted.%s.sha256 must be 64 lower-case hex digits" % (path, ident))
        out[ident] = (until, digest)
    if len(out) > cap:
        raise InternalError("%s: more accepted ids than the cap" % path)
    return MappingProxyType(out)


def load_baseline(path, product):
    table = _read(path)
    if set(table) != set(BASELINE_KEYS):
        raise InternalError("%s: keys must be exactly %s" % (path, sorted(BASELINE_KEYS)))
    if table["schema"] != SCHEMA:
        raise InternalError("%s: schema must be %r" % (path, SCHEMA))
    if table["product"] != product:
        raise InternalError("%s: product must be %r" % (path, product))
    cap, prefix, pattern = table["cap"], table["reference_bug_link_prefix"], table["reference_bug_link_pattern"]
    if type(cap) is not int or not 0 <= cap <= MAX_CAP:
        raise InternalError("%s: cap must be an integer 0..%d" % (path, MAX_CAP))
    if type(prefix) is not str or not prefix.startswith("https://") or prefix != prefix.strip() or " " in prefix:
        raise InternalError("%s: reference_bug_link_prefix must be a literal https:// URL prefix" % path)
    if type(pattern) is not str or not pattern or len(pattern) > MAX_PATTERN:
        raise InternalError("%s: reference_bug_link_pattern must be a string of 1..%d characters" % (path, MAX_PATTERN))
    try:
        compiled = re.compile(pattern)
    except re.error as error:
        raise InternalError("%s: reference_bug_link_pattern: %s" % (path, error))
    if compiled.fullmatch(""):
        raise InternalError("%s: reference_bug_link_pattern matches the empty string" % path)
    return Baseline(product, cap, _accepted(path, table["accepted"], cap), prefix, pattern)


def load_expectation(path, product):
    table = _read(path)
    if set(table) != {"schema", "product", "headers"}:
        raise InternalError("%s: keys must be exactly ['headers', 'product', 'schema']" % path)
    if table["schema"] != SECTIONS_SCHEMA:
        raise InternalError("%s: schema must be %r" % (path, SECTIONS_SCHEMA))
    if table["product"] != product:
        raise InternalError("%s: product must be %r" % (path, product))
    headers = table["headers"]
    if not isinstance(headers, dict) or list(headers) != sorted(headers):
        raise InternalError("%s: headers must be a table sorted by path" % path)
    for name, count in headers.items():
        if paths.unsafe_path_reason(name) is not None or posixpath.normpath(name) != name:
            raise InternalError("%s: bad header path %r" % (path, name))
        if type(count) is not int or not 1 <= count <= MAX_ENTRIES:
            raise InternalError("%s: %s: the acknowledged entries must be an integer 1..%d" % (path, name, MAX_ENTRIES))
    return Expectation(product, MappingProxyType(dict(headers)))
