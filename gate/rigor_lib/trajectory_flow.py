"""Shell control flow for `rigor trajectory`: `for NAME in WORDS; do ...; done` with a literal word list.

The lexer yields a flat list of simple commands. A `for` loop whose word list is known (literals, known
variables, brace expansions) is unrolled: its body is audited once per value with the variable bound, so a
path built from the loop variable is resolved instead of being reported as unresolved. A list that cannot
be known (command substitution, glob, unknown variable, too long) leaves the variable unresolved and the
body is audited once, exactly as before.
"""

import re

from rigor_lib.trajectory_paths import expand_braces
from rigor_lib.trajectory_shell import UNRESOLVED

MAX_VALUES = 64
MAX_ITERATIONS = 1024
_LOOPS = ("for", "while", "until", "select")
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_GLOB = re.compile(r"[*?\[]")


def _first(command):
    if command.words and not command.words[0].quoted:
        return command.words[0].text
    return None


def _header_name(command):
    """The loop variable of a `for NAME in ...` header command, else None."""
    words = command.words
    if _first(command) == "for" and len(words) >= 3 and _NAME.match(words[1].text) and words[2].text == "in" \
            and not words[1].quoted and not words[2].quoted:
        return words[1].text
    return None


def _done_index(commands, start):
    """Index of the `done` that closes the loop whose header is commands[start], or -1."""
    depth = 1
    for index in range(start + 1, len(commands)):
        first = _first(commands[index])
        if first in _LOOPS:
            depth += 1
        elif first == "done":
            depth -= 1
            if depth == 0:
                return index
    return -1


class FlowMixin:
    """Methods of the Analyzer that need its state (expand, prepare, flush, hits)."""

    def run_commands(self, commands, env, depth):
        prepared = []
        index = 0
        while index < len(commands):
            command = commands[index]
            item = self.prepare(command, env, depth)
            if item is not None:
                prepared.append(item)
            name = _header_name(command)
            if name is not None:
                end = _done_index(commands, index)
                values = self._loop_values(command, env) if end > 0 else None
                if values is not None and self.iterations + len(values) <= MAX_ITERATIONS:
                    self.flush(prepared, depth, env)
                    prepared = []
                    self._unroll(name, values, commands[index + 1:end], env, depth)
                    index = end
                    continue
                env[name] = UNRESOLVED
            index += 1
        self.flush(prepared, depth, env)

    def _unroll(self, name, values, body, env, depth):
        start = len(self.hits)
        self.iterations += len(values)
        for value in values:
            env[name] = value
            self.run_commands(body, env, depth)
        seen, kept = set(), []
        for hit in self.hits[start:]:
            if hit not in seen:
                seen.add(hit)
                kept.append(hit)
        self.hits[start:] = kept

    def _loop_values(self, command, env):
        """The values of the loop's word list, or None when they cannot all be known."""
        values = []
        for word in command.words[3:]:
            if word.subs:
                return None
            text = self.expand(word, env)
            if UNRESOLVED in text:
                return None
            if word.quoted:
                values.append(text)
                continue
            for piece in text.split():
                if _GLOB.search(piece):
                    return None
                values.extend(expand_braces(piece))
        if not values or len(values) > MAX_VALUES:
            return None
        return values
