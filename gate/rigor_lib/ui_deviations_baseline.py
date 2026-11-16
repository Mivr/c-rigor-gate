"""`ui_deviations_baseline`: the two owner-sealed files of `rigor ui-deviations` (strict loaders; any defect is exit 2).

`products/<product>/ui/deviations.toml` pins every accepted tag id with its `until` and the sha256 of its canonical fields;
`products/<product>/ui/deviation-sections.toml` pins, per header, the entry labels the owner has acknowledged
(docs/ui-deviations.md). What the loaders return is immutable.
"""

import datetime
import posixpath
import re
import tomllib
from dataclasses import dataclass
from types import MappingProxyType

from rigor_lib import jsonio, paths
from rigor_lib.errors import InternalError
from rigor_lib.ui_deviations_tags import DATE_RE, HORIZON_DAYS, ID_RE, TASK_RE

SCHEMA = "ui-deviations/3"
SECTIONS_SCHEMA = "ui-deviation-sections/2"
BASELINE_RELATIVE = "ui/deviations.toml"
SECTIONS_RELATIVE = "ui/deviation-sections.toml"
BASELINE_KEYS = ("schema", "product", "cap", "accepted", "reference_bug_link_prefix")
ACCEPTED_KEYS = ("until", "sha256")
HEADER_KEYS = ("count", "labels")
MAX_CAP = 1000
MAX_ENTRIES = 999
MAX_LABEL = 80
_SHA = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class Baseline:
    product: str
    cap: int
    accepted: object          # MappingProxyType {id: (until, sha256)}
    link_prefix: str


@dataclass(frozen=True)
class Expectation:
    product: str
    headers: object           # MappingProxyType {path: acknowledged entries}
    labels: object            # MappingProxyType {path: tuple of the labels counted}


def _read(path):
    try:
        return tomllib.loads(jsonio.read_bytes(path).decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as error:
        raise InternalError("%s: %s" % (path, error))


def _until(path, ident, until, today):
    if type(until) is str and DATE_RE.fullmatch(until):
        try:
            when = datetime.date.fromisoformat(until)
        except ValueError:
            raise InternalError("%s: accepted.%s.until is not a calendar date" % (path, ident))
        if when > today + datetime.timedelta(days=HORIZON_DAYS):
            raise InternalError("%s: accepted.%s.until is more than %d days away" % (path, ident, HORIZON_DAYS))
    elif type(until) is not str or not TASK_RE.fullmatch(until):
        raise InternalError("%s: accepted.%s.until is not a task id or an ISO date" % (path, ident))


def _accepted(path, table, cap, today):
    if not isinstance(table, dict) or list(table) != sorted(table):
        raise InternalError("%s: accepted must be a table sorted by id" % path)
    out = {}
    for ident, entry in table.items():
        if not ID_RE.fullmatch(ident) or not isinstance(entry, dict) or set(entry) != set(ACCEPTED_KEYS):
            raise InternalError("%s: accepted.%s must hold exactly %s under a valid id" % (path, ident, list(ACCEPTED_KEYS)))
        _until(path, ident, entry["until"], today)
        if type(entry["sha256"]) is not str or not _SHA.fullmatch(entry["sha256"]):
            raise InternalError("%s: accepted.%s.sha256 must be 64 lower-case hex digits" % (path, ident))
        out[ident] = (entry["until"], entry["sha256"])
    if len(out) > cap:
        raise InternalError("%s: more accepted ids than the cap" % path)
    return MappingProxyType(out)


def load_baseline(path, product, today):
    table = _read(path)
    if set(table) != set(BASELINE_KEYS):
        raise InternalError("%s: keys must be exactly %s" % (path, sorted(BASELINE_KEYS)))
    if table["schema"] != SCHEMA:
        raise InternalError("%s: schema must be %r" % (path, SCHEMA))
    if table["product"] != product:
        raise InternalError("%s: product must be %r" % (path, product))
    cap, prefix = table["cap"], table["reference_bug_link_prefix"]
    if type(cap) is not int or not 0 <= cap <= MAX_CAP:
        raise InternalError("%s: cap must be an integer 0..%d" % (path, MAX_CAP))
    if (type(prefix) is not str or not prefix.startswith("https://") or not prefix.endswith("/")
            or re.search(r"\s", prefix) or len(prefix) > 200):
        raise InternalError("%s: reference_bug_link_prefix must be a literal https:// URL prefix ending in '/'" % path)
    return Baseline(product, cap, _accepted(path, table["accepted"], cap, today), prefix)


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
    counts, labels = {}, {}
    for name, entry in headers.items():
        if (paths.unsafe_path_reason(name) is not None or posixpath.normpath(name) != name or not name.endswith(".h")):
            raise InternalError("%s: bad header path %r (a normalised relative path ending in .h)" % (path, name))
        if not isinstance(entry, dict) or set(entry) != set(HEADER_KEYS):
            raise InternalError("%s: %s must hold exactly %s" % (path, name, list(HEADER_KEYS)))
        names = entry["labels"]
        if (not isinstance(names, list) or not all(type(x) is str and 0 < len(x) <= MAX_LABEL and x == x.strip() for x in names)
                or len(set(names)) != len(names)):
            raise InternalError("%s: %s: labels must be a list of distinct non-empty strings" % (path, name))
        if type(entry["count"]) is not int or not 1 <= entry["count"] <= MAX_ENTRIES or entry["count"] != len(names):
            raise InternalError("%s: %s: count must be an integer 1..%d equal to the number of labels" % (path, name, MAX_ENTRIES))
        counts[name], labels[name] = entry["count"], tuple(names)
    return Expectation(product, MappingProxyType(counts), MappingProxyType(labels))
