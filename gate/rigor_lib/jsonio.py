"""Strict JSON reading, canonical JSON writing, hashing and atomic file writes."""

import hashlib
import json
import os
import tempfile


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key: %r" % key)
        result[key] = value
    return result


def _reject_constant(name):
    raise ValueError("non-finite JSON number: %s" % name)


def strict_loads(data):
    """Parse UTF-8 JSON bytes; refuse duplicate keys, NaN and Infinity."""
    text = data.decode("utf-8")
    return json.loads(text, object_pairs_hook=_reject_duplicate_keys,
                      parse_constant=_reject_constant)


def canonical_dumps(obj):
    """Sorted keys, compact separators, ASCII only, trailing newline. Returns bytes."""
    text = json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)
    return text.encode("ascii") + b"\n"


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def read_bytes(path):
    """Read a whole file; any OS error propagates and becomes exit 2."""
    with open(path, "rb") as handle:
        return handle.read()


def write_atomic(path, data):
    """Write bytes to `path` through a temp file in the same directory."""
    directory = os.path.dirname(os.path.abspath(path))
    handle, temp_path = tempfile.mkstemp(dir=directory, prefix=".rigor-")
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        os.replace(temp_path, path)
    except BaseException:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise
