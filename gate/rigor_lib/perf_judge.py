"""Judging the cost counts of a `c_perf` target against a declared complexity class (T090, docs/perf.md "Judging").

Pure functions. A record list is the parsed `perf.jsonl` of one target (one record per size, in `sizes` order);
the first and the last record are compared (`n1` and `n2 = k * n1`, normally k = 4), once for `instructions` and
once for `libc_bytes`. A class allows the count at `n2` to be at most

    limit(c1) = floor(R * c1) + SLACK                      (SLACK = 16 counts: the counter's own jitter)

where R is, with k = n2 / n1:

    O(1)         1.10
    O(log n)     1 + log2(k) / 4           (1.5 for k = 4: exact for pure log growth from n1 >= 16), or the
                                           additive rule c2 <= c1 + max(64, c1 / 10), whichever is larger
    O(n)         1.10 * k                  (4.4 for k = 4)
    O(n log n)   1.10 * k * log2(n2) / log2(n1)

A count of zero at both sizes is always inside every class. All arithmetic on counts is integer except the one
float product R * c1, which is the same on every machine (IEEE doubles).
"""

import math

from rigor_lib.errors import InternalError

CLASSES = ("O(1)", "O(log n)", "O(n)", "O(n log n)")
COUNTERS = ("instructions", "libc_bytes")
SLACK = 16
LOG_ADDITIVE_FLOOR = 64
# Two runs of the same binary on the same CPU model agree on a count when they differ by at most
# COUNT_ABS + max(a, b) / 2^COUNT_REL_SHIFT (docs/perf.md "Determinism": 200 uncached executions on one model moved by
# up to 118 at 3.4e8 instructions and by up to 52 at 4.9e6; the bound allows 10463 and 166 there, 3 times the largest).
COUNT_ABS = 16
COUNT_REL_SHIFT = 15
# Runs on different CPU models are compared by what the judge reads: the class and the ratio between sizes. Two
# ratios agree when they are within the judge's own margin (R = 1.10 of every class).
CROSS_MODEL_MARGIN = 1.10
_KEYS = ("name", "seed", "n", "status", "counter", "input_len")
STATUSES = ("ok", "gen-overflow", "run-error", "crash", "timeout")


def _ratio_limit(cost_class, n1, n2):
    k = n2 / n1
    if cost_class == "O(1)":
        return 1.10
    if cost_class == "O(log n)":
        return 1 + math.log2(k) / 4
    if cost_class == "O(n)":
        return 1.10 * k
    return 1.10 * k * math.log2(n2) / math.log2(max(n1, 2))


def limit(cost_class, c1, n1, n2):
    """The largest count at `n2` that the class allows when the count at `n1` is `c1`."""
    base = int(math.floor(_ratio_limit(cost_class, n1, n2) * c1)) + SLACK
    if cost_class == "O(log n)":
        base = max(base, c1 + max(LOG_ADDITIVE_FLOOR, c1 // 10) + SLACK)
    return base


def parse_records(path, data):
    """The records of a `perf.jsonl` (bytes). The file comes out of a build action: any other shape is exit 2."""
    from rigor_lib import jsonio
    records = []
    for number, raw in enumerate(data.split(b"\n"), 1):
        if not raw:
            continue
        try:
            record = jsonio.strict_loads(raw)
        except ValueError as exc:
            raise InternalError("%s:%d: not JSON: %s" % (path, number, exc)) from exc
        if not isinstance(record, dict):
            raise InternalError("%s:%d: a record must be an object" % (path, number))
        records.append(record)
    return records


def count_bound(a, b):
    """The largest difference between two runs' counts `a` and `b` (non-negative ints) that still agrees."""
    return COUNT_ABS + (max(a, b) >> COUNT_REL_SHIFT)


def counts_agree(a, b):
    """True when two counts of the same measurement (same binary, same input, same CPU model) are within `count_bound`.
    Not used for a class verdict: a verdict reads one count per size and compares ratios."""
    return abs(a - b) <= count_bound(a, b)


def same_model(a, b):
    """True when two records name the same, non-empty CPU model string. A record without `cpu` matches nothing."""
    cpu = a.get("cpu")
    return type(cpu) is str and cpu != "" and cpu == b.get("cpu")


def _class_of(first, last, field):
    """The smallest class that allows the count at `last`, or None when even O(n log n) does not."""
    for cost_class in CLASSES:
        if last[field] <= limit(cost_class, first[field], first["n"], last["n"]):
            return cost_class
    return None


def _ratios_agree(a1, a2, b1, b2):
    """Ratios a2/a1 and b2/b1 within CROSS_MODEL_MARGIN of each other (integer cross products; a zero count only
    agrees with a zero count)."""
    if a1 == 0 or b1 == 0:
        return a1 == b1 and (a2 == 0) == (b2 == 0)
    left, right = a2 * b1, b2 * a1                      # a2/a1 against b2/b1, both sides times a1 * b1
    low, high = sorted((left, right))
    return high * 100 <= low * int(round(CROSS_MODEL_MARGIN * 100))


def run_differences(run_a, run_b):
    """[reason] why two runs (each the usable record list of one perf action) of the same measurement do not agree;
    [] when they agree. Same CPU model: every record's `instructions` within `count_bound`, `libc_bytes` equal. Different
    models (or an unnamed one): raw counts are never compared; per counter the complexity class (the smallest class that
    allows the count at the last size) must be the same and the ratio between the first and the last size must agree
    within CROSS_MODEL_MARGIN."""
    for run in (run_a, run_b):
        if usable(run)[2] is not None:
            return ["records are not usable"]
    (a1, a2, _), (b1, b2, _) = usable(run_a), usable(run_b)
    if (a1["n"], a2["n"]) != (b1["n"], b2["n"]) or len(run_a) != len(run_b):
        return ["sizes differ"]
    reasons = []
    if same_model(a1, b1):
        for ra, rb in zip(run_a, run_b):
            if ra["n"] != rb["n"] or not counts_agree(ra["instructions"], rb["instructions"]):
                reasons.append("n=%s: instructions %s vs %s are beyond the bound" % (ra["n"], ra["instructions"], rb["instructions"]))
            if ra["libc_bytes"] != rb["libc_bytes"]:
                reasons.append("n=%s: libc_bytes %s vs %s" % (ra["n"], ra["libc_bytes"], rb["libc_bytes"]))
        return reasons
    for field in COUNTERS:
        ca, cb = _class_of(a1, a2, field), _class_of(b1, b2, field)
        if ca != cb:
            reasons.append("%s: class %s vs %s" % (field, ca, cb))
        if not _ratios_agree(a1[field], a2[field], b1[field], b2[field]):
            reasons.append("%s: ratios %s/%s vs %s/%s are not within %s" % (field, a2[field], a1[field], b2[field], b1[field], CROSS_MODEL_MARGIN))
    return reasons


def _count(record, field):
    value = record.get(field)
    return value if type(value) is int and value >= 0 else None


def usable(records):
    """(first, last, why). `why` is None when the pair can be judged; else the rule's reason:
    'record' (fewer than two records, a status that is not ok, or a malformed record) or 'unavailable'
    (the counter could not be opened or multiplexed)."""
    if len(records) < 2:
        return None, None, "record"
    first, last = records[0], records[-1]
    for record in (first, last):
        if record.get("status") != "ok" or type(record.get("n")) is not int or record["n"] < 1:
            return first, last, "record"
    if first["n"] >= last["n"]:
        return first, last, "record"
    for record in (first, last):
        if record.get("counter") != "perf_event_open":
            return first, last, "unavailable"
    for record in (first, last):
        if any(_count(record, field) is None for field in COUNTERS):
            return first, last, "record"
    return first, last, None


def exceeded(cost_class, records):
    """[{counter, n1, n2, count1, count2, ratio, limit}] for every counter that leaves the class.
    The records must be `usable`."""
    first, last, why = usable(records)
    if why is not None:
        raise ValueError("records are not usable: %s" % why)
    found = []
    for field in COUNTERS:
        c1, c2 = first[field], last[field]
        bound = limit(cost_class, c1, first["n"], last["n"])
        if c2 > bound:
            ratio = "inf" if c1 == 0 else "%.3f" % (c2 / c1)
            found.append({"counter": field, "n1": first["n"], "n2": last["n"], "count1": c1, "count2": c2,
                          "ratio": ratio, "limit": bound})
    return found


def status_of(records):
    """The status to report for a target that cannot be judged: the first bad status, else 'malformed'."""
    for record in records:
        status = record.get("status")
        if status != "ok":
            return status if status in STATUSES else "malformed"
    return "malformed"
