"""The probe client of `rigor ui-explore` (U05, P004 4.2): starts a probe binary and speaks `ui-probe/1` strictly.

Every command has a deadline (`deadline_s`), and every session shares the run's wall-clock `Budget`. Anything the
protocol does not allow raises `ProbeError` with a kind:

    protocol    a reply or record of the wrong shape, an `err` reply, output nobody asked for (bytes left over after a
                reply, before a command or after `ok quit`), a `fail` reply to a command that never fails
    fail        a `fail <command>` reply of a command that may fail: the model returned false; the session is poisoned
    zero-delay  a deadline at or before now (the probe's `err next-due|advance model-contract`, or a `next-due` reply
                not after now): 0-delay rescheduling, which the explorer reports as `timer-starvation`
    contract    the gate saw the model break the interface (a refused input that changed the model)
    crash       the probe's output ended before the reply was complete, or it exited non-zero after `quit`
    timeout     no complete reply within the deadline; the probe group is killed

The detail of an error is gate text; the probe's own bytes go to `raw` (evidence, never into a finding). When the
run's budget, not the command's deadline, runs out, `BudgetSpent` is raised instead. A probe that cannot be executed at
all is the gate's input error (`InternalError`, exit 2). Every live probe is in `LIVE`; `kill_all()` kills their process
groups (the explorer calls it on SIGTERM and SIGINT).
"""

import os
import re
import select
import signal
import subprocess
import time

from rigor_lib.errors import InternalError
from rigor_lib.ui_explore_grammar import (BUF_MAX, DOMAIN_MAX, FRAME_FIELDS, INK_FIELDS, MAX_LINE, UNSIGNED,
                                          GrammarError, pairs, parse_env_inputs, parse_frame_line, parse_identity,
                                          parse_record, parse_typed_line, printable)

GREETING = "ui-probe/1 ready"
# what a greeting may announce, in this order (docs/ui-model.md "The greeting"; the C probe announces the first six, and
# `pointer` (U05c) when the product's taps go through its own pointer entry; no explorer behaviour depends on it, a
# catalogue may require it; `identity` (U24) when the product reports its scene identity, read for the ui-scene judge)
CAPABILITIES = ("frame-facts", "ink", "hit-test", "tap", "apply-missed", "crop", "pointer", "identity")
TAP_CAPS = ("hit-test", "tap")          # catalogue taps (u2, u3) need both: every tap is preceded by its hit query
FRAME_MS = 16
ADVANCE_MAX_MS = 600000
TIME_MAX_MS = 1 << 52
ORIGIN_MAX_MS = 1 << 48
MAX_LINES = BUF_MAX                     # every line of a framed reply carries at least its LF
# the commands whose model call may return false (docs/ui-model.md); a `fail` reply to any other is a protocol error
FAILABLE = ("open", "env-inputs", "apply", "advance", "frame", "semantic", "patches", "trace", "domain-at", "tap",
            "identity")
LIVE = set()
_DUE = re.compile(r"0|[1-9][0-9]{0,19}")       # next-due: the full uint64 range the C probe can print
_NODE = re.compile(r"none|0|[1-9][0-9]{0,4}")    # a walk index (lvprobe: at most 32767) or none
_HEX = re.compile(r"[0-9a-f]*")
# Output nobody asked for may arrive before the next command is sent or be read as its reply, depending on timing:
# both are the same finding, with the same gate text.
NOT_A_REPLY = "a line that is not the reply to this command"


class ProbeError(Exception):
    KINDS = ("protocol", "fail", "zero-delay", "contract", "crash", "timeout")

    def __init__(self, kind, command, detail, raw=None):
        if kind not in self.KINDS:
            raise ValueError("unknown probe error kind %r" % (kind,))
        super().__init__("%s: %s: %s" % (kind, command, detail))
        self.kind, self.command, self.detail, self.raw = kind, command, detail, raw


class BudgetSpent(Exception):
    """The wall-clock budget of the whole run is spent."""


class Budget:
    def __init__(self, seconds):
        self.seconds = seconds
        self.end = time.monotonic() + seconds

    def spent(self):
        return time.monotonic() >= self.end


STOP_SIGNALS = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)


def kill_all(reap=True, timeout=None):
    """Kill every live probe's process group and reap it. `reap=False` (the signal handler, U05e): only SIGKILL the
    groups, never wait: the interrupted code may be inside `Popen.wait`, whose lock is not reentrant (a wait here
    deadlocked); the main flow reaps them (`kill_all()` in `handle`'s finally, `Session.close`)."""
    for session in list(LIVE):
        if reap:
            session.kill(timeout)
        else:
            session.signal_group()


def _raw(data):
    return data[:400].decode("latin-1")


class Session:
    """One probe process."""

    def __init__(self, argv, deadline_s, budget, expect_caps=None):
        """`expect_caps`: the capabilities of the first launch; a launch that announces others is a protocol error."""
        self.deadline_s, self.budget = deadline_s, budget
        self.now = self.origin = None
        self.commands = self.virtual_ms = 0
        self._buf, self._eof, self._reaped = b"", False, False
        # the explorer's signals are blocked from the start of the probe until it is in LIVE, so a signal in between
        # cannot leak a probe the handler does not know; the probe itself starts with the old mask (U05e fix-up 3)
        old = signal.pthread_sigmask(signal.SIG_BLOCK, STOP_SIGNALS)
        try:
            try:
                self._proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                              stderr=subprocess.DEVNULL, start_new_session=True,
                                              preexec_fn=lambda: signal.pthread_sigmask(signal.SIG_SETMASK, old))
            except OSError as error:
                raise InternalError("cannot execute the probe %s: %s" % (argv[0], error.strerror))
            LIVE.add(self)
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, old)
        self._fd = self._proc.stdout.fileno()
        os.set_blocking(self._fd, False)
        try:
            self.caps = self._greeting(self._line("greeting", self._limit()))
            if expect_caps is not None and self.caps != tuple(expect_caps):
                raise ProbeError("protocol", "greeting", "capabilities differ from the first launch of this probe",
                                 " ".join(self.caps))
        except (ProbeError, BudgetSpent):
            self.close()
            raise

    @staticmethod
    def _greeting(line):
        if line != GREETING and not line.startswith(GREETING + " "):
            raise ProbeError("protocol", "greeting", "not the ui-probe/1 greeting", line)
        caps = line[len(GREETING):].split(" ")[1:]
        if any(c not in CAPABILITIES for c in caps) or caps != sorted(set(caps), key=CAPABILITIES.index):
            raise ProbeError("protocol", "greeting", "unknown, repeated or unordered capabilities", line)
        return tuple(caps)

    # ---- low level -------------------------------------------------------------------------------------------
    def _limit(self):
        return time.monotonic() + self.deadline_s

    def _read_ready(self, wait):
        ready, _, _ = select.select([self._fd], [], [], max(wait, 0))
        if not ready:
            return False
        chunk = os.read(self._fd, 65536)
        if chunk:
            self._buf += chunk
        else:
            self._eof = True
        return True

    def _drain(self, command):
        """Before a command nothing may be pending: what is buffered, or what one non-blocking read returns, is output
        nobody asked for (a protocol error)."""
        if not self._buf and not self._eof:
            self._read_ready(0)
        if self._buf:
            raise ProbeError("protocol", command, NOT_A_REPLY, _raw(self._buf))

    def _send(self, command):
        name = command.split(" ")[0]
        self._drain(name)
        self.commands += 1
        try:
            self._proc.stdin.write(command.encode("ascii") + b"\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, ConnectionResetError):
            raise self._crashed(name)

    def _exit_status(self, limit):
        """Wait until monotonic `limit` for the probe to exit, without reaping it (so its pid and process group stay
        valid for killpg); its exit status (negative: the signal), or None."""
        fd = os.pidfd_open(self._proc.pid)
        try:
            left = min(limit, self.budget.end) - time.monotonic()
            ready, _, _ = select.select([fd], [], [], max(left, 0))
            found = os.waitid(os.P_PID, self._proc.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) if ready else None
        finally:
            os.close(fd)
        if found is None:
            return None
        return found.si_status if found.si_code == os.CLD_EXITED else -found.si_status

    def _crashed(self, command):
        code = self._exit_status(self._limit())
        if code is None:
            self.kill()
            if self.budget.spent():
                raise BudgetSpent()
            return ProbeError("timeout", command, "output ended but the probe did not exit")
        return ProbeError("crash", command, "the probe ended its output (exit status %d)" % code)

    def _expired(self, command, limit):
        self.kill()
        if self.budget.end <= limit:
            raise BudgetSpent()
        raise ProbeError("timeout", command, "no complete reply within %g s" % self.deadline_s)

    def _line(self, command, limit):
        while True:
            end = self._buf.find(b"\n")
            if end > MAX_LINE:
                raise ProbeError("protocol", command, "a reply line longer than %d bytes" % MAX_LINE, _raw(self._buf))
            if end >= 0:
                raw, self._buf = self._buf[:end], self._buf[end + 1:]
                text = raw.decode("latin-1")
                if not printable(text):
                    raise ProbeError("protocol", command, "a reply byte outside printable ASCII and TAB", _raw(raw))
                return text
            if len(self._buf) > MAX_LINE:
                raise ProbeError("protocol", command, "a reply line longer than %d bytes" % MAX_LINE, _raw(self._buf))
            if self._eof:
                raise self._crashed(command)
            left = min(limit, self.budget.end) - time.monotonic()
            if left <= 0:
                self._expired(command, limit)
            self._read_ready(left)

    def _reply(self, command):
        name = command.split(" ")[0]
        self._send(command)
        limit = self._limit()
        line = self._line(name, limit)
        if line.startswith("err "):
            if line in ("err next-due model-contract", "err advance model-contract"):
                raise ProbeError("zero-delay", name, "the probe reports a deadline at or before now", line)
            raise ProbeError("protocol", name, "an err reply", line)
        if line == "fail " + name:
            if name not in FAILABLE:
                raise ProbeError("protocol", name, "a fail reply to a command that never fails", line)
            raise ProbeError("fail", name, "the model failed", line)
        return line, limit

    def _exact(self, command, *allowed):
        line, _ = self._reply(command)
        if line not in allowed:
            raise ProbeError("protocol", command.split(" ")[0], NOT_A_REPLY, line)
        return line

    def _number(self, command, name):
        line, _ = self._reply(command)
        head = "ok %s " % name
        if not line.startswith(head) or not UNSIGNED.fullmatch(line[len(head):]):
            raise ProbeError("protocol", name, NOT_A_REPLY, line)
        return int(line[len(head):])

    def _lines(self, name):
        return self._lines_of(name, name)

    def _lines_of(self, command, name):
        line, limit = self._reply(command)
        head = "ok %s lines " % name
        if not line.startswith(head) or not UNSIGNED.fullmatch(line[len(head):]):
            raise ProbeError("protocol", name, NOT_A_REPLY, line)
        count, out, total = int(line[len(head):]), [], 0
        if count > MAX_LINES:
            raise ProbeError("protocol", name, "a reply announcing more lines than the payload limit allows", line)
        for _ in range(count):
            out.append(self._line(name, limit))
            total += len(out[-1]) + 1
            if total > BUF_MAX:
                raise ProbeError("protocol", name, "a reply payload over %d bytes" % BUF_MAX)
        return out

    def _need_open(self, name):
        if self.now is None:
            raise InternalError("the explorer sent %s before a successful open" % name)

    def _parse(self, name, parse, lines):
        try:
            return tuple(parse(line) for line in lines)
        except GrammarError as error:
            raise ProbeError("protocol", name, str(error), "\n".join(lines)[:400])

    # ---- the commands of ui-probe/1 ----------------------------------------------------------------------------
    def open(self, origin_ms, seed):
        self.now = None
        self._exact("open %d %d" % (origin_ms, seed), "ok open")
        self.now = self.origin = origin_ms

    def env_inputs(self):
        self._need_open("env-inputs")
        line, _ = self._reply("env-inputs")
        try:
            return parse_env_inputs(line)
        except GrammarError as error:
            raise ProbeError("protocol", "env-inputs", str(error), line[:400])

    def apply(self, kind, ident, arg, hex_text):
        """"ok" (delivered), "refused" (not enabled; nothing changed) or "missed" (delivered through the production
        path, but the product did not produce the intent it was aimed at; only from a probe announcing apply-missed)."""
        self._need_open("apply")
        if kind not in (1, 2, 3) or "00" in pairs(hex_text):
            raise InternalError("apply: bad input %r" % ((kind, ident, arg, hex_text),))
        allowed = ("ok apply", "ok apply refused") + (("ok apply missed",) if "apply-missed" in self.caps else ())
        line = self._exact("apply %d %d %d %s" % (kind, ident, arg, hex_text or "-"), *allowed)
        return {"ok apply": "ok", "ok apply refused": "refused", "ok apply missed": "missed"}[line]

    def _need_cap(self, name, cap):
        self._need_open(name)
        if cap not in self.caps:
            raise InternalError("%s needs a probe that announces the %s capability" % (name, cap))

    def _node(self, name, word, line):
        if not _NODE.fullmatch(word) or (word != "none" and int(word) > 32767):
            raise ProbeError("protocol", name, NOT_A_REPLY, line)
        return None if word == "none" else int(word)

    def hit_test(self, x, y):
        """What LVGL's own search finds at (x, y): a walk index, None, or "blocked" (a tap would not be processed)."""
        self._need_cap("hit-test", "hit-test")
        line, _ = self._reply("hit-test %d %d" % (x, y))
        words = line.split(" ")
        if len(words) != 3 or words[:2] != ["ok", "hit-test"]:
            raise ProbeError("protocol", "hit-test", NOT_A_REPLY, line)
        return "blocked" if words[2] == "blocked" else self._node("hit-test", words[2], line)

    def tap(self, x, y):
        """A press and release through the production pointer path: "blocked", or (pressed, clicked), each a walk
        index or None."""
        self._need_cap("tap", "tap")
        line, _ = self._reply("tap %d %d" % (x, y))
        words = line.split(" ")
        if line == "ok tap blocked":
            return "blocked"
        if len(words) != 4 or words[:2] != ["ok", "tap"]:
            raise ProbeError("protocol", "tap", NOT_A_REPLY, line)
        pressed, clicked = self._node("tap", words[2], line), self._node("tap", words[3], line)
        if pressed is None and clicked is not None:
            raise ProbeError("protocol", "tap", "a tap that clicked a node it did not press", line)
        return pressed, clicked

    def crop(self, x, y, w, h):
        """The RGBA bytes of the box (x, y, w, h) of the current frame: h lines of 8 w lowercase hex digits."""
        self._need_cap("crop", "crop")
        lines = self._lines_of("crop %d %d %d %d" % (x, y, w, h), "crop")
        if len(lines) != h or any(len(row) != 8 * w or not _HEX.fullmatch(row) for row in lines):
            raise ProbeError("protocol", "crop", "a crop that is not %d rows of %d hex digits" % (h, 8 * w))
        return bytes.fromhex("".join(lines))

    def ink(self, node=None):
        """The `ink` and `noink` records of every node (or of `node`) of the current frame."""
        self._need_cap("ink", "ink")
        command = "ink" if node is None else "ink %d" % node
        return self._parse("ink", lambda line: parse_typed_line(INK_FIELDS, line), self._lines_of(command, "ink"))

    def next_due(self):
        """The next deadline in ms, or None."""
        self._need_open("next-due")
        line, _ = self._reply("next-due")
        if line == "ok next-due none":
            return None
        head = "ok next-due "
        if not line.startswith(head) or not _DUE.fullmatch(line[len(head):]) or int(line[len(head):]) >= 2**64:
            raise ProbeError("protocol", "next-due", NOT_A_REPLY, line)
        due = int(line[len(head):])
        if due <= self.now:
            raise ProbeError("zero-delay", "next-due", "a deadline at or before now", line)
        return due

    def advance(self, to_ms):
        """One `advance` command; the caller keeps it on the frame grid and within the protocol's limits."""
        self._need_open("advance")
        if not self.now < to_ms <= TIME_MAX_MS or to_ms - self.now > ADVANCE_MAX_MS:
            raise InternalError("advance: %d is out of range from %d" % (to_ms, self.now))
        now = self._number("advance %d" % to_ms, "advance")
        if now != to_ms:
            raise ProbeError("protocol", "advance", "the clock did not reach the target", "ok advance %d" % now)
        self.virtual_ms += now - self.now
        self.now = now

    def frame(self):
        """The frame lines: lvprobe's records and `life` lines, by type and field count, from a probe that announces
        frame-facts; seam lines of any shape (each escaped) from one that does not."""
        self._need_open("frame")
        parse = (lambda line: parse_typed_line(FRAME_FIELDS, line)) if "frame-facts" in self.caps else parse_frame_line
        return self._parse("frame", parse, self._lines("frame"))

    def records(self, name):
        self._need_open(name)
        return self._parse(name, lambda line: parse_record(name, line), self._lines(name))

    def identity(self):
        """The scene identity (U24): the `state` record, then the `node` records (parse_identity)."""
        self._need_cap("identity", "identity")
        lines = self._lines("identity")
        try:
            return parse_identity(lines)
        except GrammarError as error:
            raise ProbeError("protocol", "identity", str(error), "\n".join(lines)[:400])

    def domain_count(self):
        count = self._number("domain-count", "domain-count")
        if count > DOMAIN_MAX:
            raise ProbeError("protocol", "domain-count", "a count above %d" % DOMAIN_MAX, str(count))
        return count

    def domain_at(self, index):
        self._need_open("domain-at")
        self._exact("domain-at %d" % index, "ok domain-at")

    def quit(self):
        """`quit`: exactly `ok quit`, nothing after it, end of output and exit status 0 within the deadline."""
        self._send("quit")
        limit = self._limit()
        line = self._line("quit", limit)
        if line != "ok quit":
            raise ProbeError("protocol", "quit", NOT_A_REPLY, line)
        self._proc.stdin.close()
        while not self._eof:
            if self._buf:
                raise ProbeError("protocol", "quit", "output after ok quit", _raw(self._buf))
            left = min(limit, self.budget.end) - time.monotonic()
            if left <= 0:
                self._expired("quit", limit)
            self._read_ready(left)
        if self._buf:
            raise ProbeError("protocol", "quit", "output after ok quit", _raw(self._buf))
        code = self._exit_status(limit)
        if code is None:
            self._expired("quit", limit)
        if code != 0:
            raise ProbeError("crash", "quit", "exit status %d after quit" % code)

    def kill(self, timeout=None):
        """Kill the probe's whole process group (a grandchild holding stdout included), then reap the probe. The probe is
        never reaped before (waits use WNOWAIT), so its pid still names its group; after reaping, killpg is not called
        again. Idempotent."""
        if self._reaped:
            return
        try:
            os.killpg(self._proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            self._proc.wait(timeout)
        except subprocess.TimeoutExpired:     # a signalled teardown never waits without bound (fix-up 3)
            return
        self._reaped = True

    def signal_group(self):
        """SIGKILL the probe's process group without waiting, unless the probe is reaped (Popen's returncode is set as
        it reaps)."""
        if self._reaped or self._proc.returncode is not None:
            return
        try:
            os.killpg(self._proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    def close(self):
        for stream in (self._proc.stdin, self._proc.stdout):
            try:
                stream.close()
            except OSError:
                pass
        self.kill()
        LIVE.discard(self)
