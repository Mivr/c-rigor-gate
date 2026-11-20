"""The oracle bundle and the `vm-trace/1` reader (T2G7, P330 §3.2 and §3.4; docs/oracle.md).

The bundle is the hidden half of the oracle replay: Rust traces the grader holds and the implementer never sees. Its
layout mirrors the witness bundle (witness_bundle.py): a directory with exactly two entries,

    <bundle>/oracle.toml
    <bundle>/files/<trace id>.trace          # one vm-trace/1 file per trace, flat

    product = "business-apps"                # must equal product.toml's name
    origin = "T2C2"                          # the task or run that produced it (information)
    produced_from = "<40-hex>"               # the club-apps commit the traces were produced from (information)
    [trace."scripted-01"]                    # one table per file, exactly these keys
    sha256 = "<64-hex>"                      # of files/scripted-01.trace
    steps = 12                               # the number of `in` lines

Every defect (symlinks, special files, unsafe names, extra or missing files, unknown keys, a wrong hash or step count, a
trace that is not valid `vm-trace/1`) is an InternalError (exit 2), never a pass. `load` reads everything once; nothing
later goes back to the directory.

`vm-trace/1` is JSON lines, LF only, compact, keys in the order shown (docs/oracle.md has the table):

    {"k":"cfg",...}                                      first line, once
    {"k":"in","t":N,"op":"digit","d":3}                  an input
    {"k":"fx","t":N,"port":"opener.open",...}            zero or more, one per port call made while handling it
    {"k":"vw","t":N,"s":{...canonical ViewState...}}     after the input; `s` is compared as TEXT, never re-serialised
    {"k":"ns","t":N}                                     replayer output only: the input did not settle (`oracle-no-settle`)
"""

import json
import os
import re
import stat
import tomllib
from dataclasses import dataclass

from rigor_lib import jsonio
from rigor_lib.errors import InternalError

MANIFEST = "oracle.toml"
FILES_DIR = "files"
SUFFIX = ".trace"
VERSION = "vm-trace/1"
TRACE_ID = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,95}")
_SHA1 = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_TOP_KEYS = {"product", "origin", "produced_from", "trace"}
_TRACE_KEYS = {"sha256", "steps"}
MAX_TRACE_BYTES = 8 << 20
MAX_TRACES = 100000
PORTS = ("opener.open", "store.save", "store.load", "audit.append", "codes.role_of", "coils.read", "volume.free_mb", "sync.note")
CFG_KEYS = ("k", "v", "id", "src", "seed", "start_ms", "lang", "inventory", "codes", "pulse_units", "min_free_mb",
            "offline_age_ms")
# op -> the keys after `k`, `t`, `op`
OPS = {"digit": ("d",), "backspace": (), "submit": (), "scan": ("text",), "choose": ("size",), "cancel": (),
       "dismiss": ("intent",), "dismiss_report": (), "ack_opened": (), "lang": ("lang",), "tick": ("adv_ms",),
       "set_codes_offline": (), "fail": ("port", "count", "err")}
_VW = re.compile(rb'\{"k":"vw","t":([0-9]+),"s":(\{.*\})\}')


def _fail(where, why):
    raise InternalError("oracle: %s: %s" % (where, why))


@dataclass(frozen=True)
class Record:
    line: int        # 1-based line number in the file
    text: bytes      # the whole line, without the LF


@dataclass(frozen=True)
class Step:
    input: Record
    fx: tuple        # Records
    view: Record     # the `vw` line, or the `ns` line of a step that did not settle
    state: bytes     # the `s` text of the `vw` line; b"" for `ns`

    @property
    def settled(self):
        return self.state != b""


@dataclass(frozen=True)
class Trace:
    cfg: Record
    steps: tuple     # Steps
    sha256: str
    lines: int


@dataclass(frozen=True)
class Bundle:
    product: str
    origin: str
    produced_from: str
    traces: dict           # trace id -> Trace, in id order
    manifest_sha256: str   # sha256 of oracle.toml as read
    file_sha256: dict      # trace id -> sha256 of the file as read

    @property
    def ids(self):
        return tuple(sorted(self.traces))


# ------------------------------------------------------------------------------------------------ vm-trace/1

def _loads(where, data):
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=lambda pairs: dict(pairs))
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        _fail(where, "not valid JSON: %s" % exc)


def _compact(value):
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _record(where, line, text, keys=None, prefix=None):
    """The parsed object of a plain record: compact, and with the keys in the required order (the first ones of PREFIX, or
    exactly KEYS)."""
    obj = _loads("%s line %d" % (where, line), text)
    if not isinstance(obj, dict) or _compact(obj) != text:
        _fail("%s line %d" % (where, line), "not a compact JSON object")
    names = tuple(obj)
    if keys is not None and names != keys:
        _fail("%s line %d" % (where, line), "keys must be %s, got %s" % (list(keys), list(names)))
    if prefix is not None and names[:len(prefix)] != prefix:
        _fail("%s line %d" % (where, line), "must start with the keys %s" % list(prefix))
    return obj


def _int(where, value):
    if type(value) is not int or value < 0:
        _fail(where, "must be a non-negative integer")
    return value


def _cfg(where, text):
    obj = _record(where, 1, text, keys=CFG_KEYS)
    if obj["k"] != "cfg" or obj["v"] != VERSION:
        _fail(where + " line 1", "must be a cfg record of %s" % VERSION)
    return obj


def _input(where, line, text):
    obj = _record(where, line, text, prefix=("k", "t", "op"))
    op = obj["op"]
    if obj["k"] != "in" or op not in OPS or tuple(obj)[3:] != OPS[op]:
        _fail("%s line %d" % (where, line), "not an input record of %s (op %r)" % (VERSION, op))
    return _int("%s line %d t" % (where, line), obj["t"])


def _effect(where, line, text, t):
    obj = _record(where, line, text, prefix=("k", "t", "port"))
    if obj["k"] != "fx" or obj["port"] not in PORTS or obj["t"] != t:
        _fail("%s line %d" % (where, line), "not an fx record of %s at the time of its input" % VERSION)


def _view(where, line, text, t, allow_ns):
    if allow_ns and text == b'{"k":"ns","t":%d}' % t:
        return b""
    match = _VW.fullmatch(text)
    if match is None or int(match.group(1)) != t or match.group(1) != b"%d" % t:
        _fail("%s line %d" % (where, line), "not a vw record at the time of its input")
    state = match.group(2)
    if not isinstance(_loads("%s line %d s" % (where, line), state), dict):
        _fail("%s line %d" % (where, line), "s is not a JSON object")
    return state


def parse_trace(where, data, allow_ns=False):
    """The Trace of the bytes of a vm-trace/1 file; any defect is an InternalError. `allow_ns`: replayer output."""
    if not data or len(data) > MAX_TRACE_BYTES or not data.endswith(b"\n") or b"\r" in data:
        _fail(where, "must be non-empty LF-terminated text without CR, at most %d bytes" % MAX_TRACE_BYTES)
    lines = data[:-1].split(b"\n")
    if any(not line for line in lines):
        _fail(where, "an empty line")
    _cfg(where, lines[0])
    steps, number = [], 1
    while number < len(lines):
        number += 1
        t = _input(where, number, lines[number - 1])
        first, effects = number, []
        while number < len(lines) and lines[number].startswith(b'{"k":"fx"'):
            number += 1
            _effect(where, number, lines[number - 1], t)
            effects.append(Record(number, lines[number - 1]))
        if number >= len(lines):
            _fail(where, "the input at line %d has no view" % first)
        number += 1
        state = _view(where, number, lines[number - 1], t, allow_ns)
        steps.append(Step(Record(first, lines[first - 1]), tuple(effects), Record(number, lines[number - 1]), state))
        if not state and number != len(lines):
            _fail(where, "records after the ns record at line %d" % number)
    return Trace(Record(1, lines[0]), tuple(steps), jsonio.sha256_hex(data), len(lines))


# ------------------------------------------------------------------------------------------------ the bundle

def _lstat(path):
    try:
        return os.lstat(path)
    except OSError as exc:
        raise InternalError("oracle bundle: cannot stat %s: %s" % (path, exc)) from exc


def _list_dir(path):
    try:
        names = os.listdir(path)
    except OSError as exc:
        raise InternalError("oracle bundle: cannot list %s: %s" % (path, exc)) from exc
    for name in names:
        try:
            name.encode("utf-8")
        except UnicodeEncodeError:
            raise InternalError("oracle bundle: non-UTF-8 name in %s" % path) from None
    return sorted(names)


def _read_regular(path):
    """Read a regular file without following a symlink at the last component."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError as exc:
        raise InternalError("oracle bundle: cannot open %s: %s" % (path, exc)) from exc
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise InternalError("oracle bundle: not a regular file: %s" % path)
        chunks = []
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
    finally:
        os.close(fd)


def _string(value, what):
    if not isinstance(value, str) or value == "":
        _fail(MANIFEST, "%s must be a non-empty string" % what)
    return value


def parse_manifest(data):
    """(product, origin, produced_from, {id: (sha256, steps)}) from the bytes of oracle.toml."""
    try:
        document = tomllib.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise InternalError("oracle.toml is not valid UTF-8 TOML: %s" % exc) from exc
    if set(document) != _TOP_KEYS:
        _fail(MANIFEST, "must have exactly the keys %s" % ", ".join(sorted(_TOP_KEYS)))
    produced = _string(document["produced_from"], "produced_from")
    if not _SHA1.fullmatch(produced):
        _fail(MANIFEST, "produced_from must be 40 lowercase hex")
    table = document["trace"]
    if not isinstance(table, dict) or not table or len(table) > MAX_TRACES:
        _fail(MANIFEST, "[trace] must list at least one trace")
    entries = {}
    for trace_id, row in table.items():
        if not TRACE_ID.fullmatch(trace_id):
            _fail(MANIFEST, "bad trace id %r" % (trace_id,))
        if not isinstance(row, dict) or set(row) != _TRACE_KEYS:
            _fail(MANIFEST, "trace %s must have exactly the keys %s" % (trace_id, ", ".join(sorted(_TRACE_KEYS))))
        if not isinstance(row["sha256"], str) or not _SHA256.fullmatch(row["sha256"]):
            _fail(MANIFEST, "trace %s sha256 must be 64 lowercase hex" % trace_id)
        entries[trace_id] = (row["sha256"], _int("%s trace %s steps" % (MANIFEST, trace_id), row["steps"]))
    return _string(document["product"], "product"), _string(document["origin"], "origin"), produced, entries


def load(directory):
    """Read and validate a bundle directory. Any defect is an InternalError."""
    if not stat.S_ISDIR(_lstat(directory).st_mode):
        raise InternalError("oracle bundle is not a directory (or is a symlink): %s" % directory)
    entries = _list_dir(directory)
    if entries != sorted([MANIFEST, FILES_DIR]):
        raise InternalError("oracle bundle must hold exactly %s and %s/, found %s" % (MANIFEST, FILES_DIR, entries))
    manifest = _read_regular(os.path.join(directory, MANIFEST))
    product, origin, produced, listed = parse_manifest(manifest)
    root = os.path.join(directory, FILES_DIR)
    if not stat.S_ISDIR(_lstat(root).st_mode):
        raise InternalError("oracle bundle: %s is not a directory" % FILES_DIR)
    names = _list_dir(root)
    wanted = sorted(trace_id + SUFFIX for trace_id in listed)
    if names != wanted:
        extra, missing = sorted(set(names) - set(wanted)), sorted(set(wanted) - set(names))
        _fail(FILES_DIR, "files and [trace] differ (unlisted: %s; missing: %s)" % (extra[:3], missing[:3]))
    traces, hashes = {}, {}
    for trace_id in sorted(listed):
        data = _read_regular(os.path.join(root, trace_id + SUFFIX))
        sha, steps = listed[trace_id]
        if jsonio.sha256_hex(data) != sha:
            _fail(trace_id, "sha256 of the file is not the one oracle.toml lists")
        trace = parse_trace("trace " + trace_id, data)
        if len(trace.steps) != steps:
            _fail(trace_id, "oracle.toml says %d steps, the file has %d" % (steps, len(trace.steps)))
        traces[trace_id], hashes[trace_id] = trace, sha
    return Bundle(product, origin, produced, traces, jsonio.sha256_hex(manifest), hashes)


def digest_entries(bundle):
    """The digested list: oracle.toml first, then every file by its bundle path (`files/...`), sorted."""
    return [[MANIFEST, bundle.manifest_sha256]] + [[FILES_DIR + "/" + trace_id + SUFFIX, bundle.file_sha256[trace_id]]
                                                    for trace_id in sorted(bundle.traces)]


def digest(bundle):
    """`oracle_sha256`: independent of where the bundle was stored (the witness bundle's scheme)."""
    return jsonio.sha256_hex(jsonio.canonical_dumps(digest_entries(bundle)))


def check(bundle, product_name):
    """The bundle is for this product."""
    if bundle.product != product_name:
        raise InternalError("oracle bundle is for product %r, not %r" % (bundle.product, product_name))
