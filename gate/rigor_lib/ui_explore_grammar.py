"""The reply and record grammar of `ui-probe/1` as the explorer reads it (ui/model/model.h, docs/ui-model.md).

Pure functions: a violation raises `GrammarError` with a gate-written reason (never the offending bytes, which the
caller keeps as evidence). Limits come from the protocol: a framed reply carries at most `BUF_MAX` payload bytes, an
env input id is a uint32, its arg an int32, its text 1..256 bytes without NUL, at most 64 inputs.
"""

import re
from dataclasses import dataclass

BUF_MAX = 65536                 # UIM_BUF_MAX: the payload of one framed reply (record lines with their LF)
TEXT_MAX = 256
ENV_MAX = 64
DOMAIN_MAX = 65535              # uim_domain_count() is a uint16_t
# the longest reply line: a record line of a full payload, or the env-inputs line (about 35 KB)
MAX_LINE = BUF_MAX
SEMANTIC_FIELDS = ("key", "role", "label", "x", "y", "w", "h", "enabled", "intent", "flags", "style", "importance",
                   "input_policy", "wrap_policy")
PATCH_FIELDS = ("op", "key", "field", "old", "new")
TRACE_FIELDS = ("seq", "type", "mono_ms")
RECORD_FIELDS = {"semantic": SEMANTIC_FIELDS, "patches": PATCH_FIELDS, "trace": TRACE_FIELDS}
# The record types of a `frame` reply from a probe that announces frame-facts, and of `ink`, with their field counts
# (the type name included): docs/ui-model.md "Frame facts", docs/ui-lvprobe.md "Text format".
FRAME_FIELDS = {"lvprobe": 3, "frame": 4, "node": 21, "label": 15, "fit": 8, "region": 3, "life": 7, "taps": 2}
INK_FIELDS = {"ink": 8, "noink": 3}
# the numeric fields of those records the explorer reads (u: unsigned, s: signed): walk indexes, parents, boxes, sizes
_TYPED_KINDS = {"lvprobe": {2: "u"}, "frame": {1: "u", 2: "u"},
                "node": {1: "u", 2: "s", 3: "u", 5: "s", 6: "s", 7: "s", 8: "s"}}
_FIELD_KINDS = {"semantic": {3: "s", 4: "s", 5: "s", 6: "s", 7: "f"}, "patches": {}, "trace": {0: "u", 2: "u"}}
UNSIGNED = re.compile(r"0|[1-9][0-9]{0,17}")
_SIGNED = re.compile(r"0|-?[1-9][0-9]{0,17}")
_ENV_ITEM = re.compile(r"1:(0|[1-9][0-9]{0,9}):(0|-?[1-9][0-9]{0,9}):(-|(?:[0-9a-f]{2}){1,%d})" % TEXT_MAX)


class GrammarError(Exception):
    """A reply or record that breaks the grammar; the message is gate text only."""


@dataclass(frozen=True)
class Record:
    """One record line: `raw` as written (escaped, canonical), `fields` the escaped fields, `values` their bytes."""
    raw: str
    fields: tuple
    values: tuple


def printable(line):
    return all(0x20 <= ord(c) <= 0x7e or c == "\t" for c in line)


def unescape(field):
    """Bytes of one escaped field, or None if an escape is not allowed (model.h)."""
    out = bytearray()
    i, n = 0, len(field)
    while i < n:
        c = field[i]
        if c != "\\":
            out.append(ord(c))
            i += 1
            continue
        nxt = field[i + 1:i + 2]
        if nxt in ("\\", "t", "n"):
            out.append({"\\": 0x5c, "t": 0x09, "n": 0x0a}[nxt])
            i += 2
            continue
        digits = field[i + 2:i + 4]
        if nxt != "x" or not re.fullmatch(r"[0-9a-f]{2}", digits):
            return None
        byte = int(digits, 16)
        if 0x20 <= byte <= 0x7e or byte in (0x09, 0x0a):
            return None
        out.append(byte)
        i += 4
    return bytes(out)


def _split(line):
    if not printable(line):
        raise GrammarError("a record byte outside printable ASCII and TAB")
    fields = tuple(line.split("\t"))
    values = tuple(unescape(field) for field in fields)
    if None in values:
        raise GrammarError("field %d has a bad escape" % values.index(None))
    return fields, values


def parse_record(kind, line):
    """A record of `kind` (semantic, patches, trace): field count, escapes, numbers and flags checked."""
    names = RECORD_FIELDS[kind]
    fields, values = _split(line)
    if len(fields) != len(names):
        raise GrammarError("a %s record with %d fields, wanted %d" % (kind, len(fields), len(names)))
    for index, field in enumerate(fields):
        how = _FIELD_KINDS[kind].get(index)
        if (how == "s" and not _SIGNED.fullmatch(field)) or (how == "u" and not UNSIGNED.fullmatch(field)) \
                or (how == "f" and field not in ("0", "1")):
            raise GrammarError("%s field %s is not a number of its kind" % (kind, names[index]))
    return Record(line, fields, values)


def parse_frame_line(line):
    """A line of the `frame` reply of a probe without frame-facts: any number of TAB-separated fields, escaped as above."""
    fields, values = _split(line)
    return Record(line, fields, values)


def parse_typed_line(types, line):
    """A frame-facts or ink record: its type (the first field) is one of `types`, with exactly that many fields."""
    fields, values = _split(line)
    want = types.get(fields[0])
    if want is None:
        raise GrammarError("a record of a type this reply does not have")
    if len(fields) != want:
        raise GrammarError("a %s record with %d fields, wanted %d" % (fields[0], len(fields), want))
    for index, how in _TYPED_KINDS.get(fields[0], {}).items():
        if not (UNSIGNED if how == "u" else _SIGNED).fullmatch(fields[index]):
            raise GrammarError("a %s record whose field %d is not a number of its kind" % (fields[0], index))
    return Record(line, fields, values)


def parse_env_inputs(line):
    """The inputs of an `ok env-inputs <n> ...` line as (id, arg, hex) tuples, hex "" for no text."""
    parts = line.split(" ")
    if len(parts) < 3 or parts[:2] != ["ok", "env-inputs"] or not UNSIGNED.fullmatch(parts[2]):
        raise GrammarError("an env-inputs reply without its count")
    count = int(parts[2])
    if count > ENV_MAX or len(parts) - 3 != count:
        raise GrammarError("an env-inputs reply whose count does not match its inputs or exceeds %d" % ENV_MAX)
    out = []
    for item in parts[3:]:
        match = _ENV_ITEM.fullmatch(item)
        if not match:
            raise GrammarError("an env input that is not kind 1, a uint32 id, an int32 arg and hex text")
        ident, arg, text = int(match.group(1)), int(match.group(2)), match.group(3)
        if ident > 0xffffffff or not -2**31 <= arg < 2**31 or (text != "-" and "00" in pairs(text)):
            raise GrammarError("an env input outside the protocol's ranges")
        out.append((ident, arg, "" if text == "-" else text))
    return tuple(out)


def pairs(hex_text):
    return [hex_text[i:i + 2] for i in range(0, len(hex_text), 2)]
