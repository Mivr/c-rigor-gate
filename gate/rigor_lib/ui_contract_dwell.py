"""The dwell table of the UI contract (P004 3.10, docs/ui-contract.md "Checks"): characters as displayed, reading time,
minimum dwell and the contract's timer, and the findings `dwell-below-reading-time` and `contract-incomplete` for a timer
kind the contract lacks. Split out of ui_contract (U06 fix-up 3, the series' 500-line limit); no behaviour changed, and
`ui_contract` re-exports every public name.
"""

import re
import unicodedata
from fractions import Fraction
from types import MappingProxyType

from rigor_lib import findings
from rigor_lib.errors import InternalError

_PLACEHOLDER = re.compile(r"\{[^{}]*\}")


def _fail(why):
    raise InternalError("ui-contract: %s" % why)


def _is_str(v):
    return isinstance(v, str) and v != "" and v == v.strip() and "\n" not in v


def displayed_text(text, max_expansion=None):
    """The text as displayed: every `{placeholder}` replaced by its longest expansion. A placeholder without an
    expansion, or an expansion for a placeholder the text does not have, is an error."""
    expansion = {} if max_expansion is None else max_expansion
    if not isinstance(expansion, dict) or not all(_is_str(k) and _is_str(v) and not _PLACEHOLDER.search(v)
                                                  for k, v in expansion.items()):
        _fail("max_expansion must map each placeholder to a plain, non-empty text")
    names = set(_PLACEHOLDER.findall(text))
    if names - set(expansion):
        _fail("dwell: placeholder(s) %s have no max_expansion" % ", ".join(sorted(names - set(expansion))))
    if set(expansion) - names:
        _fail("dwell: max_expansion names %s, which the text does not contain" % ", ".join(sorted(set(expansion) - names)))
    return _PLACEHOLDER.sub(lambda found: expansion[found.group(0)], text)


def char_count(text):
    return len(unicodedata.normalize("NFC", text))


def reading_ms(chars, rate_wpm, chars_per_word):
    """chars / (rate * chars_per_word / 60) seconds, in whole ms rounded up, exactly (P004 3.10)."""
    per_minute = Fraction(str(rate_wpm)) * Fraction(str(chars_per_word))
    return -((-chars * 60000 * per_minute.denominator) // per_minute.numerator)


def _message(item):
    if not isinstance(item, dict) or not {"msgid", "lang", "kind", "text"} <= set(item) \
            or not set(item) <= {"msgid", "lang", "kind", "text", "max_expansion"}:
        _fail("dwell: a message is {msgid, lang, kind, text[, max_expansion]}, got %r" % (item,))
    for key in ("msgid", "lang", "kind", "text"):
        if not isinstance(item[key], str) or item[key].strip() == "":
            _fail("dwell: message %r has no usable %s" % (item.get("msgid"), key))
    return item


def dwell_table(contract, messages):
    """One row per (msgid, lang): characters as displayed, reading time, minimum dwell and the contract's timer.

    `messages` is an iterable of dicts {msgid, lang, kind, text, max_expansion}. Raises ContractPending while the
    reading rate is pending. A kind the contract has no timer for gets `lifetime_ms = None`.
    """
    rate = contract.get("reading", "rate_wpm")
    per_word = contract.get("thresholds", "dwell_chars_per_word")
    base = contract.get("thresholds", "dwell_base_ms")
    floor = contract.get("thresholds", "dwell_floor_ms")
    timers = {r["kind"]: r for r in contract.tables["timer"]}
    rows, seen = [], set()
    for item in sorted((_message(m) for m in messages), key=lambda m: (m["msgid"], m["lang"])):
        if (item["msgid"], item["lang"]) in seen:
            _fail("dwell: duplicate message %r in language %r" % (item["msgid"], item["lang"]))
        seen.add((item["msgid"], item["lang"]))
        chars = char_count(displayed_text(item["text"], item.get("max_expansion")))
        reading = reading_ms(chars, rate, per_word)
        timer = timers.get(item["kind"])
        rows.append(MappingProxyType({
            "msgid": item["msgid"], "lang": item["lang"], "kind": item["kind"], "chars": chars,
            "reading_ms": reading, "min_dwell_ms": max(floor, base + reading),
            "lifetime_ms": None if timer is None else timer["lifetime_ms"]}))
    return tuple(rows)


def dwell_findings(rows):
    """`dwell-below-reading-time` for a timed message shorter than its minimum (0 means untimed), and one
    `contract-incomplete` per timer kind the contract lacks."""
    found, missing = [], set()
    for row in rows:
        if row["lifetime_ms"] is None:
            missing.add(row["kind"])
        elif 0 < row["lifetime_ms"] < row["min_dwell_ms"]:
            found.append(findings.finding("dwell-below-reading-time", msgid=row["msgid"], lang=row["lang"],
                                          kind=row["kind"], lifetime_ms=row["lifetime_ms"],
                                          min_dwell_ms=row["min_dwell_ms"]))
    found.extend(findings.finding("contract-incomplete", what="timer-kind", name=kind) for kind in sorted(missing))
    return found
