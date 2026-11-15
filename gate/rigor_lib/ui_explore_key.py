"""The abstraction key of `rigor ui-explore` (U05, P004 4.3 item 3): the owner-declared projection of one observation,
hashed exactly; the normalised record `key-too-coarse` compares; the readable state of a finding (P004 4.5).

An observation here is the dict of a step's replies (`semantic`, `due`, `env`) and the virtual time `now`.
"""

import bisect
import re
import unicodedata

from rigor_lib import jsonio
from rigor_lib.ui_explore_grammar import SEMANTIC_FIELDS

FRAME_MS = 16
_NUMBER = re.compile(r"0|-?[1-9][0-9]{0,17}")
_DIGIT_RUN = re.compile(rb"[0-9]{1,18}")


def deadline_bucket(obs, now):
    due = obs["due"]
    if due is None:
        return "none"
    return "within-frame" if due - now <= FRAME_MS else "pending"


def _chosen(records, fact):
    return [r for r in records if (fact.node is not None and r.fields[0] == fact.node)
            or (fact.role is not None and r.fields[1] == fact.role)]


def _measure(record, fact):
    index = SEMANTIC_FIELDS.index(fact.field)
    if fact.measure == "length":       # characters (NFC code points of UTF-8), not bytes: Bulgarian text counts right
        try:
            return len(unicodedata.normalize("NFC", record.values[index].decode("utf-8")))
        except UnicodeDecodeError:
            return None
    if fact.measure == "value":
        return int(record.fields[index]) if _NUMBER.fullmatch(record.fields[index]) else None
    run = _DIGIT_RUN.search(record.values[index])
    return int(run.group(0)) if run else None


def _bucket(value, bounds):
    return "none" if value is None else bisect.bisect_right(bounds, value)


def derived_matched(fact, obs):
    """Whether a record-selecting derived fact found a record in this observation (a model fact always does)."""
    return fact.model is not None or bool(_chosen(obs["semantic"], fact))


def derived_value(fact, obs, now):
    """The value of one derived fact (catalogue `[[key.derived]]`); plain JSON data."""
    if fact.model == "due-in-ms":
        return _bucket(None if obs["due"] is None else obs["due"] - now, fact.boundaries)
    if fact.model == "env-count":
        return _bucket(len(obs["env"]), fact.boundaries)
    chosen = _chosen(obs["semantic"], fact)
    if fact.op == "presence":
        return bool(chosen)
    if fact.op == "count":
        return len(chosen)
    if fact.op == "select":
        return [r.fields[SEMANTIC_FIELDS.index(fact.field)] for r in chosen]
    return [_bucket(_measure(r, fact), fact.boundaries) for r in chosen]


def all_facts(obs, now, key):
    """Every model fact and every derived fact of the key, declared or not (the normalised record)."""
    facts = {"deadline": deadline_bucket(obs, now), "env-inputs": [list(item) for item in obs["env"]]}
    for fact in key.derived:
        facts[fact.name] = derived_value(fact, obs, now)
    return facts


def projection(obs, now, key):
    """The declared projection: per node its `key` and the declared fields, the declared facts, the derived facts."""
    index = [SEMANTIC_FIELDS.index(name) for name in key.fields]
    nodes = [[record.fields[0]] + [record.fields[i] for i in index] for record in obs["semantic"]]
    facts = all_facts(obs, now, key)
    chosen = {name: facts[name] for name in key.facts}
    chosen.update({fact.name: facts[fact.name] for fact in key.derived})
    return {"nodes": nodes, "facts": chosen}


def key_hash(proj):
    return jsonio.sha256_hex(jsonio.canonical_dumps(proj))


def normalised(obs, now, key):
    """Everything but the justified `ignore` fields: every semantic field and every model and derived fact."""
    ignored = {item[0] for item in key.ignore}
    keep = [i for i, name in enumerate(SEMANTIC_FIELDS) if name not in ignored]
    return {"nodes": [[record.fields[i] for i in keep] for record in obs["semantic"]],
            "facts": all_facts(obs, now, key)}


def readable(proj, key):
    """The projection by name, for a finding's `state`: the nodes as objects of their declared fields, the facts."""
    names = ("key",) + key.fields
    return {"nodes": [dict(zip(names, node)) for node in proj["nodes"]], "facts": proj["facts"]}
