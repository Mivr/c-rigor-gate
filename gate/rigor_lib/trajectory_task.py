"""The task contract as `rigor trajectory` reads it: a TOML file, or TOML given on the command line."""

import os
import tomllib

from rigor_lib import globs, jsonio
from rigor_lib import trajectory_rules as rules
from rigor_lib.errors import InternalError

_KNOWN_KEYS = {"id", "allowed", "protected", "max_files", "role", "test_globs"}
ROLE_IMPLEMENTER = "implementer"


class Task:
    def __init__(self, task_id, allowed, protected, role, test_globs):
        self.task_id = task_id
        self.allowed = allowed        # compiled globs
        self.protected = protected    # compiled globs
        self.role = role
        self.test_globs = test_globs  # compiled globs

    def is_protected(self, rel):
        return any(globs.matches(g, rel) for g in self.protected)

    def is_allowed(self, rel):
        return not self.allowed or any(globs.matches(g, rel) for g in self.allowed)

    def is_test(self, rel):
        return any(globs.matches(g, rel) for g in self.test_globs)

    @property
    def implementer(self):
        return self.role == ROLE_IMPLEMENTER


def _string_list(table, key, required):
    value = table.get(key)
    if value is None:
        if required:
            raise InternalError("task is missing key %r" % key)
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise InternalError("task key %r must be a list of strings" % key)
    return value


def parse_task(text):
    try:
        table = tomllib.loads(text)
    except ValueError as exc:
        raise InternalError("task is not valid TOML: %s" % exc) from exc
    unknown = sorted(set(table) - _KNOWN_KEYS)
    if unknown:
        raise InternalError("unknown task keys: %s" % ", ".join(unknown))
    task_id = table.get("id")
    if not isinstance(task_id, str) or task_id == "":
        raise InternalError("task key 'id' must be a non-empty string")
    role = table.get("role", ROLE_IMPLEMENTER)
    if not isinstance(role, str) or role == "":
        raise InternalError("task key 'role' must be a non-empty string")
    test_globs = _string_list(table, "test_globs", False) or list(rules.DEFAULT_TEST_GLOBS)
    compile_all = lambda patterns: [globs.compile_glob(p) for p in patterns]  # noqa: E731
    return Task(task_id, compile_all(_string_list(table, "allowed", True)),
                compile_all(_string_list(table, "protected", False)), role, compile_all(test_globs))


def load_task(value):
    """`value` is a TOML file path, or (when no such file exists) TOML text with a `=`."""
    if os.path.exists(value):
        return parse_task(jsonio.read_bytes(value).decode("utf-8"))
    if "=" in value:
        return parse_task(value)
    raise InternalError("task %r is neither a file nor TOML text" % value[:80])
