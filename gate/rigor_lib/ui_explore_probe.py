"""The probe client of `rigor ui-explore` (U05, P004 4.2): starts a probe binary and speaks `ui-probe/1` strictly.

Every command has a deadline. Anything the protocol does not allow (a wrong greeting, a reply of the wrong shape, a
record that breaks the grammar of `ui/model/model.h`, an `err` reply, a `fail` reply, end of output, an exit status that
is not 0 after `quit`) raises `ProbeError` with a kind:

    protocol    a reply or record of the wrong shape, or an `err` reply (the probe saw a protocol error)
    fail        a `fail <command>` reply: the model returned false; the session is poisoned
    crash       the probe's output ended (it exited or closed stdout) before the reply was complete, or it exited
                non-zero after `quit`
    timeout     no complete reply within the deadline; the probe is killed

A `ProbeError` is a property of the product run, not of the gate: the explorer turns it into a finding. It never
shortens a run silently. Records of `semantic`, `patches` and `trace` are parsed and unescaped; `frame` lines are kept
verbatim (their grammar belongs to a later task).
"""

import os
import re
import select
import signal
import subprocess
import time
from dataclasses import dataclass

GREETING = b"ui-probe/1 ready"
MAX_LINE = 70000              # the env-inputs line reaches about 35 KB; a record buffer is at most 65536 bytes
MAX_LINES = 65536
FRAME_MS = 16
TEXT_MAX = 256
ENV_MAX = 64
ADVANCE_MAX_MS = 600000
TIME_MAX_MS = 1 << 52
ORIGIN_MAX_MS = 1 << 48
_UNSIGNED = re.compile(r"0|[1-9][0-9]{0,17}")
_SIGNED = re.compile(r"0|-?[1-9][0-9]{0,17}")
_HEX = re.compile(r"(?:[0-9a-f]{2}){1,%d}" % TEXT_MAX)
_ENV_ITEM = re.compile(r"1:(0|[1-9][0-9]*):(0|-?[1-9][0-9]*):(-|(?:[0-9a-f]{2})+)")
_ERR = re.compile(r"err [?a-z-]+ [a-z-]+")

SEMANTIC_FIELDS = ("key", "role", "label", "x", "y", "w", "h", "enabled", "intent", "flags", "style", "importance",
                   "input_policy", "wrap_policy")
PATCH_FIELDS = ("op", "key", "field", "old", "new")
TRACE_FIELDS = ("seq", "type", "mono_ms")
# fields that are numbers ("s" signed, "u" unsigned) or a 0/1 flag ("f"), by record kind
_FIELD_KINDS = {
    "semantic": {3: "s", 4: "s", 5: "s", 6: "s", 7: "f"},
    "patches": {},
    "trace": {0: "u", 2: "u"},
}
RECORD_FIELDS = {"semantic": SEMANTIC_FIELDS, "patches": PATCH_FIELDS, "trace": TRACE_FIELDS}


class ProbeError(Exception):
    """The probe broke `ui-probe/1`, failed, crashed or hung. `kind` is one of KINDS."""

    KINDS = ("protocol", "fail", "crash", "timeout")

    def __init__(self, kind, command, detail):
        if kind not in self.KINDS:
            raise ValueError("unknown probe error kind %r" % (kind,))
        super().__init__("%s: %s: %s" % (kind, command, detail))
        self.kind = kind
        self.command = command
        self.detail = detail


@dataclass(frozen=True)
class Record:
    """One record line: `raw` is the line as the probe wrote it (escaped, canonical), `fields` the escaped fields,
    `values` the unescaped bytes of each field."""
    raw: str
    fields: tuple
    values: tuple


def unescape(field):
    """Bytes of one escaped field (model.h grammar), or None if the escaping is not allowed."""
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


def parse_record(kind, line):
    """A record of `kind` (semantic, patches, trace), or a ProbeError of kind protocol."""
    names = RECORD_FIELDS[kind]
    if any(not (0x20 <= ord(c) <= 0x7e or c == "\t") for c in line):
        raise ProbeError("protocol", kind, "a record byte outside printable ASCII and TAB")
    fields = tuple(line.split("\t"))
    if len(fields) != len(names):
        raise ProbeError("protocol", kind, "a record with %d fields, wanted %d" % (len(fields), len(names)))
    values = []
    for index, field in enumerate(fields):
        value = unescape(field)
        if value is None:
            raise ProbeError("protocol", kind, "field %s has a bad escape" % names[index])
        how = _FIELD_KINDS[kind].get(index)
        if (how == "s" and not _SIGNED.fullmatch(field)) or (how == "u" and not _UNSIGNED.fullmatch(field)) \
                or (how == "f" and field not in ("0", "1")):
            raise ProbeError("protocol", kind, "field %s is not a number of its kind: %r" % (names[index], field))
        values.append(value)
    return Record(line, fields, tuple(values))


def parse_env_inputs(line):
    """The inputs of an `ok env-inputs <n> ...` line as (id, arg, hex) tuples, hex "" for no text."""
    parts = line.split(" ")
    if len(parts) < 3 or parts[:2] != ["ok", "env-inputs"] or not _UNSIGNED.fullmatch(parts[2]):
        raise ProbeError("protocol", "env-inputs", "bad reply header")
    count = int(parts[2])
    items = parts[3:]
    if count > ENV_MAX or len(items) != count:
        raise ProbeError("protocol", "env-inputs", "announces %d inputs, carries %d" % (count, len(items)))
    out = []
    for item in items:
        match = _ENV_ITEM.fullmatch(item)
        if not match or int(match.group(1)) > 0xffffffff or not -2**31 <= int(match.group(2)) < 2**31 \
                or (match.group(3) != "-" and (len(match.group(3)) > 2 * TEXT_MAX or "00" in _pairs(match.group(3)))):
            raise ProbeError("protocol", "env-inputs", "bad input %r" % item)
        out.append((int(match.group(1)), int(match.group(2)), "" if match.group(3) == "-" else match.group(3)))
    return tuple(out)


def _pairs(hex_text):
    return [hex_text[i:i + 2] for i in range(0, len(hex_text), 2)]


class Session:
    """One probe process. `argv` starts it; `deadline_s` bounds every reply (and the greeting, and the exit)."""

    def __init__(self, argv, deadline_s):
        self.deadline_s = deadline_s
        self.now = None
        self._buf = b""
        self._eof = False
        try:
            self._proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                          stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError as error:
            raise ProbeError("crash", "start", "cannot start the probe: %s" % error.strerror)
        self._fd = self._proc.stdout.fileno()
        os.set_blocking(self._fd, False)
        try:
            line = self._line("greeting", time.monotonic() + deadline_s)
            if line != GREETING.decode("ascii"):
                raise ProbeError("protocol", "greeting", "wrong greeting %r" % line[:80])
        except ProbeError:
            self.close()
            raise

    # ---- low level -------------------------------------------------------------------------------------------
    def _send(self, command):
        try:
            self._proc.stdin.write(command.encode("ascii") + b"\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, ConnectionResetError):
            raise self._crashed(command.split(" ")[0])

    def _crashed(self, command):
        try:
            code = self._proc.wait(timeout=self.deadline_s)
        except subprocess.TimeoutExpired:
            self.kill()
            return ProbeError("timeout", command, "output ended but the probe did not exit")
        return ProbeError("crash", command, "the probe ended its output (exit status %d)" % code)

    def _line(self, command, deadline):
        """One reply line (str, without LF)."""
        while True:
            end = self._buf.find(b"\n")
            if end >= 0:
                raw, self._buf = self._buf[:end], self._buf[end + 1:]
                if any(not (0x20 <= b <= 0x7e or b == 0x09) for b in raw):
                    raise ProbeError("protocol", command, "a reply byte outside printable ASCII and TAB")
                return raw.decode("ascii")
            if len(self._buf) > MAX_LINE:
                raise ProbeError("protocol", command, "a reply line longer than %d bytes" % MAX_LINE)
            if self._eof:
                raise self._crashed(command)
            left = deadline - time.monotonic()
            if left <= 0:
                self.kill()
                raise ProbeError("timeout", command, "no complete reply within %g s" % self.deadline_s)
            ready, _, _ = select.select([self._fd], [], [], left)
            if ready:
                chunk = os.read(self._fd, 65536)
                if chunk:
                    self._buf += chunk
                else:
                    self._eof = True

    def _reply(self, command):
        name = command.split(" ")[0]
        self._send(command)
        deadline = time.monotonic() + self.deadline_s
        line = self._line(name, deadline)
        if line.startswith("err "):
            raise ProbeError("protocol", name, "the probe replied %r" % line[:120]
                             if _ERR.fullmatch(line) else "a malformed err reply %r" % line[:120])
        if line == "fail " + name:
            raise ProbeError("fail", name, "the model failed (%s)" % line)
        return line, deadline

    def _exact(self, command, *allowed):
        line, _ = self._reply(command)
        if line not in allowed:
            raise ProbeError("protocol", command.split(" ")[0], "unexpected reply %r" % line[:120])
        return line

    def _number(self, command, name):
        line, _ = self._reply(command)
        head = "ok %s " % name
        if not line.startswith(head) or not _UNSIGNED.fullmatch(line[len(head):]):
            raise ProbeError("protocol", name, "unexpected reply %r" % line[:120])
        return int(line[len(head):])

    def _lines(self, name):
        line, deadline = self._reply(name)
        head = "ok %s lines " % name
        if not line.startswith(head) or not _UNSIGNED.fullmatch(line[len(head):]):
            raise ProbeError("protocol", name, "unexpected reply %r" % line[:120])
        count = int(line[len(head):])
        if count > MAX_LINES:
            raise ProbeError("protocol", name, "announces %d lines" % count)
        return [self._line(name, deadline) for _ in range(count)]

    def _need_open(self, name):
        if self.now is None:
            raise ProbeError("protocol", name, "the explorer sent a command before a successful open")

    # ---- the commands of ui-probe/1 ----------------------------------------------------------------------------
    def open(self, origin_ms, seed):
        if not 0 <= origin_ms <= ORIGIN_MAX_MS or not 0 <= seed < 2**64:
            raise ValueError("open: origin or seed out of range")
        self.now = None
        self._exact("open %d %d" % (origin_ms, seed), "ok open")
        self.now = origin_ms

    def env_inputs(self):
        self._need_open("env-inputs")
        line, _ = self._reply("env-inputs")
        return parse_env_inputs(line)

    def apply(self, kind, ident, arg, hex_text):
        """True when delivered, False when refused."""
        self._need_open("apply")
        if kind not in (1, 2, 3) or not 0 <= ident <= 0xffffffff or not -2**31 <= arg < 2**31 \
                or (hex_text and not _HEX.fullmatch(hex_text)) or "00" in _pairs(hex_text):
            raise ValueError("apply: bad input %r" % ((kind, ident, arg, hex_text),))
        line = self._exact("apply %d %d %d %s" % (kind, ident, arg, hex_text or "-"), "ok apply", "ok apply refused")
        return line == "ok apply"

    def next_due(self):
        """The next deadline in ms, or None."""
        self._need_open("next-due")
        line, _ = self._reply("next-due")
        if line == "ok next-due none":
            return None
        head = "ok next-due "
        if not line.startswith(head) or not _UNSIGNED.fullmatch(line[len(head):]):
            raise ProbeError("protocol", "next-due", "unexpected reply %r" % line[:120])
        due = int(line[len(head):])
        if due <= self.now:
            raise ProbeError("protocol", "next-due", "a deadline %d at or before now %d" % (due, self.now))
        return due

    def advance(self, to_ms):
        self._need_open("advance")
        if not self.now <= to_ms <= TIME_MAX_MS or to_ms - self.now > ADVANCE_MAX_MS:
            raise ValueError("advance: %d is out of range from %d" % (to_ms, self.now))
        now = self._number("advance %d" % to_ms, "advance")
        if now != to_ms:
            raise ProbeError("protocol", "advance", "reached %d, not %d" % (now, to_ms))
        self.now = now

    def frame(self):
        self._need_open("frame")
        return tuple(self._lines("frame"))

    def records(self, name):
        self._need_open(name)
        return tuple(parse_record(name, line) for line in self._lines(name))

    def domain_count(self):
        return self._number("domain-count", "domain-count")

    def domain_at(self, index):
        self._need_open("domain-at")
        self._exact("domain-at %d" % index, "ok domain-at")

    def quit(self):
        """`quit`, then end of output and exit status 0 (the probe counted no protocol error)."""
        self._send("quit")
        deadline = time.monotonic() + self.deadline_s
        line = self._line("quit", deadline)
        if line != "ok quit":
            raise ProbeError("protocol", "quit", "unexpected reply %r" % line[:120])
        self._proc.stdin.close()
        while not self._eof:
            left = deadline - time.monotonic()
            if left <= 0:
                self.kill()
                raise ProbeError("timeout", "quit", "output did not end after quit")
            ready, _, _ = select.select([self._fd], [], [], left)
            if ready:
                chunk = os.read(self._fd, 65536)
                if chunk:
                    raise ProbeError("protocol", "quit", "output after ok quit")
                self._eof = True
        try:
            code = self._proc.wait(timeout=max(deadline - time.monotonic(), 0.001))
        except subprocess.TimeoutExpired:
            self.kill()
            raise ProbeError("timeout", "quit", "the probe did not exit after quit")
        if code != 0:
            raise ProbeError("crash", "quit", "exit status %d after quit" % code)

    def kill(self):
        """Kill the probe and its process group; idempotent."""
        if self._proc.poll() is None:
            try:
                os.killpg(self._proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        self._proc.wait()

    def close(self):
        """Release the process whatever state it is in (after an error, or after quit)."""
        for stream in (self._proc.stdin, self._proc.stdout):
            try:
                stream.close()
            except OSError:
                pass
        self.kill()
