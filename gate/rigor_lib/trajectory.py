"""`rigor trajectory`: structured audit of a contributor agent's tool-use transcript (backlog B10).

The input is a Claude Code subagent transcript (JSONL). Every tool call is checked against the rule
table in trajectory_rules.py: forbidden reads, writes outside the worktree, forbidden commands and
tamper signals. `block` findings fail the audit (exit 1); `review` findings are printed only.
Anything the audit cannot parse is a finding; an empty or unreadable transcript is exit 2.
"""

import json
import re

from rigor_lib import jsonio
from rigor_lib import trajectory_rules as rules
from rigor_lib.errors import InternalError
from rigor_lib.runner import EXIT_FAIL, EXIT_PASS
from rigor_lib.trajectory_bash import Analyzer
from rigor_lib.trajectory_paths import PathPolicy
from rigor_lib.trajectory_task import load_task

GATE_ID = "trajectory"
_READ_TOOLS = ("read", "grep", "glob", "ls", "notebookread", "lsp")
_WRITE_TOOLS = {"write": "rewrite", "edit": "edit", "multiedit": "edit", "notebookedit": "edit"}
_SPAWN_TOOLS = ("agent", "task", "workflow", "sendmessage")
_WEB_TOOLS = ("webfetch", "websearch")
_PATH_KEYS = ("file_path", "path", "notebook_path")
_ALIAS_RE = re.compile(r"`(\w+)` was read as `(\w+)`")
_ALIAS_TARGETS = {"file_path", "notebook_path", "content", "old_string", "new_string", "new_source"}
_KEPT_RE = re.compile(r"^kept (/var/tmp/rigor-grade\.[A-Za-z0-9]{6})$", re.M)
# `tools/job run` prints `job NAME: pid N, deadline ...`; `echo $!` prints N; the shell's job line is `[1] N`
_JOB_PID_RE = re.compile(r"^job (\S+): pid (\d+),", re.M)
_ECHO_PID_RE = re.compile(r"^(\d+)\s*$", re.M)
_JOB_LINE_RE = re.compile(r"^\[\d+\]\s+(\d+)\s*$", re.M)
# the canary runner's own last line (canaries/runner.py): `SUMMARY: N canaries (...), ..., wall Ns, jobs N, scratch DIR`
_CANARY_DIR_RE = re.compile(
    r"^SUMMARY: \d+ canaries \([^\n()]*\), [^\n]*, wall \d+s, jobs \d+, scratch (/var/tmp/rigor-canaries\.[a-z0-9_]{8})$",
    re.M)


# -- transcript parsing --------------------------------------------------------------------------
def read_transcript(path):
    """[(line number, object or None)]; None marks a line that is not a JSON object."""
    data = jsonio.read_bytes(path)
    if not data.strip():
        raise InternalError("empty transcript")
    lines = data.split(b"\n")
    if lines[-1] == b"":
        lines.pop()
    parsed = []
    for number, raw in enumerate(lines, start=1):
        try:
            obj = jsonio.strict_loads(raw)
        except (ValueError, UnicodeDecodeError, RecursionError):
            obj = None
        parsed.append((number, obj if isinstance(obj, dict) else None))
    return parsed


def find_worktree(parsed, given):
    if given:
        return given
    for _, obj in parsed:
        if obj is not None and isinstance(obj.get("cwd"), str) and obj["cwd"].startswith("/"):
            return obj["cwd"]
    raise InternalError("no worktree: pass --worktree (the transcript has no cwd)")


def blocks_of(obj):
    """(blocks, malformed) of a transcript line's message content."""
    message = obj.get("message")
    if message is None:
        return [], obj.get("type") in ("assistant", "user")
    if not isinstance(message, dict):
        return [], True
    content = message.get("content")
    if isinstance(content, str) or content is None:
        return [], content is None and obj.get("type") == "assistant"
    if not isinstance(content, list):
        return [], True
    return content, False


def result_text(block):
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(item.get("text", "") for item in content
                         if isinstance(item, dict) and isinstance(item.get("text"), str))
    return ""


# -- the audit -------------------------------------------------------------------------------
class Audit:
    def __init__(self, policy, task):
        self.analyzer = Analyzer(policy, task)
        self.policy = policy
        self.findings = []
        self.seen_input = []
        self.tool_uses = 0
        self.repeats = 0
        self.commands = {}      # tool_use id -> the Bash command text
        self.pending = {}       # tool_use id -> (line, tool, input) of a Write/Edit judged by its own result
        self.facts = {}         # tool_use id -> CallFacts of that Bash call (trajectory_proof)

    def add(self, number, tool, rule, excerpt):
        self.findings.append({"rule": rule, "severity": rules.severity(rule), "line": number, "tool": tool,
                              "excerpt": rules.redact(excerpt)})

    def announce(self, obj, block, results):
        """Rule `persisted-output` (T049, R008 #4a). A tool_result that starts with the harness's own framing
        (`<persisted-output>` then `Output too large (...). Full output saved to: <path>`) makes that exact path
        readable, and only as far as `read-claude-state` goes. The path must be where the harness saves outputs
        (`.../.claude/projects/<project>/[<session>/]tool-results/<name>.txt`) and bound to this very result: the
        name is the result's own tool_use_id, or the line's harness metadata (`toolUseResult`) records exactly this
        `persistedOutputPath`. Text a command printed has neither. Ignored on an error result, on a line with
        several results (the metadata could belong to another), or when the agent typed the path before."""
        if block.get("is_error") or results != 1:
            return
        match = rules.OUTPUT_SAVED_RE.match(result_text(block))
        if match is None:
            return
        path = match.group(1)
        shape = rules.PERSISTED_PATH_RE.match(path)
        if shape is None or self.policy.normalize(path, "/") != path:
            return
        meta = obj.get("toolUseResult")
        if isinstance(meta, dict):
            if meta.get("persistedOutputPath") != path:
                return
        elif shape.group(1) != block.get("tool_use_id"):
            return
        if any(path in earlier for earlier in self.seen_input):
            return  # the agent already knew the path: not a harness-chosen file name
        if self.policy.read_rule(path) == "read-claude-state":
            self.policy.exempt.add(path)

    def own_dir(self, block):
        """Rules `own-grade-dir` and `own-canary-dir` (T031, B26; T052, R008 #4c). A line `kept /var/tmp/rigor-grade.XXXXXX`
        (grade) or the canary runner's `SUMMARY: ..., scratch /var/tmp/rigor-canaries.XXXXXXXX` makes that one
        directory the agent's own to remove, only when the call's CallFacts (trajectory_proof) show the line can only
        be the product script's: a grade keep run (`RIGOR_GRADE_KEEP=1`, a lexed command, not `--help`) in this call,
        or a read of such a run's own output file that nothing else wrote since (orchestrator ruling 2); for the
        canaries a `selftest/canaries.sh --keep` run in this very call; and nothing else in the call could print a
        path line (no echo/printf/other program reaching the result). Never a name the agent had already typed."""
        facts = self.facts.get(block.get("tool_use_id"))
        command = self.commands.get(block.get("tool_use_id"))
        if facts is None or command is None or block.get("is_error") or facts.forge_text:
            return
        text = result_text(block)
        found = _KEPT_RE.findall(text) if facts.grade else []
        if facts.canary:
            found += _CANARY_DIR_RE.findall(text)
        for path in found:
            if path not in command and not any(path in earlier for earlier in self.seen_input):
                self.policy.made.append(path)

    def own_pids(self, block):
        """Rule `kill-foreign` (T045; T052, R008 #4b): the pids of processes the agent started. Only from a call
        where nothing else could print digits (CallFacts.forge_digits): the `job NAME: pid N,` line of a lexed
        `tools/job run NAME` call of that call (one line per name), the bare number of `echo $!` after a command the
        lexer put in the background (orchestrator ruling 1), or the shell's `[1] N` job line for such a command.
        Any other number in any output (`echo`, `printf`, `ps`, `pgrep`, a log) proves nothing."""
        facts = self.facts.get(block.get("tool_use_id"))
        if facts is None or block.get("is_error") or facts.forge_digits:
            return
        text = result_text(block)
        jobs = _JOB_PID_RE.findall(text)
        for name, pid in jobs:
            if facts.jobs.get(name) == 1 and sum(1 for other, _ in jobs if other == name) == 1:
                self.analyzer.own_pids.add(pid)
        if facts.echo_bang:
            self.analyzer.own_pids.update(_ECHO_PID_RE.findall(text))
        if facts.background:
            self.analyzer.own_pids.update(_JOB_LINE_RE.findall(text))

    def tool_use(self, number, block):
        name, inp = block.get("name"), block.get("input")
        if not isinstance(name, str) or not isinstance(inp, dict):
            self.add(number, str(name), "malformed-entry", json.dumps(block, default=str))
            return
        if name.lower() == "bash" and isinstance(inp.get("command"), str):
            self.commands[block.get("id")] = inp["command"]
        self.tool_uses += 1
        self.seen_input.append(json.dumps(inp, sort_keys=True, default=str))
        if self.misnamed_write(name, inp) and block.get("id") is not None:
            self.pending[block["id"]] = (number, name, inp)
            return
        self.dispatch(name, inp)
        if name.lower() == "bash" and self.analyzer.facts is not None:
            self.facts[block.get("id")] = self.analyzer.facts
            self.analyzer.facts = None
        for rule, excerpt in self.analyzer.drain():
            self.add(number, name, rule, excerpt)

    @staticmethod
    def misnamed_write(name, inp):
        """A Write/Edit without `file_path` but with a string `path`: the harness may read it as an alias."""
        return (name.lower() in _WRITE_TOOLS and not isinstance(inp.get("file_path"), str)
                and not isinstance(inp.get("notebook_path"), str)
                and isinstance(inp.get("path"), str) and bool(inp["path"]))

    def judge_pending(self, block):
        """Rule `write-rejected` / alias reading. A Write/Edit with misnamed parameters is judged by its own
        result. Not an error and the note says `path` was read as `file_path`: audited as that write, with the
        names the tool says it used (and only those). An error: nothing was written, so it is `write-rejected`
        (review), and a path outside the allowed places is still `write-outside`. No result at all: unchanged,
        `malformed-entry`."""
        entry = self.pending.pop(block.get("tool_use_id"), None)
        if entry is None:
            return
        number, name, inp = entry
        if block.get("is_error"):
            self.rejected(number, name, inp["path"])
            return
        aliases = {old: new for old, new in _ALIAS_RE.findall(result_text(block)) if new in _ALIAS_TARGETS}
        if aliases.get("path") not in ("file_path", "notebook_path"):
            self.add(number, name, "malformed-entry", json.dumps(inp, default=str)[:160])
            return
        mapped = {aliases.get(key, key): value for key, value in inp.items()}
        self.check_write(name.lower(), mapped)
        self.flush(number, name)

    def rejected(self, number, name, path):
        an = self.analyzer
        an.add("write-rejected", name.lower() + " " + path)
        normal = self.policy.normalize(path, self.policy.worktree)
        if normal is None:
            an.add("write-unresolved", path)
        elif not self.policy.write_ok(normal):
            an.add("write-outside", path)
        self.flush(number, name)

    def flush(self, number, name):
        for rule, excerpt in self.analyzer.drain():
            self.add(number, name, rule, excerpt)

    def dispatch(self, name, inp):
        key = name.lower()
        an = self.analyzer
        if key == "bash":
            command = inp.get("command")
            if not isinstance(command, str):
                an.add("malformed-entry", json.dumps(inp, default=str))
                return
            an.bash(command)
        elif key in _READ_TOOLS:
            self.check_paths(inp, force=True)
            pattern = inp.get("pattern")
            if key == "glob" and isinstance(pattern, str):
                an.read_word(pattern, pattern, key)
            self.recursive_tool(key, inp, pattern)
        elif key in _WRITE_TOOLS:
            self.check_write(key, inp)
        elif key in _SPAWN_TOOLS:
            an.add("spawn-agent-tool", name + " " + json.dumps(inp, default=str))
        elif key in _WEB_TOOLS:
            an.add("web-tool", name + " " + json.dumps(inp, default=str))
        elif key.startswith("mcp__"):
            an.add("mcp-tool", name)
        else:
            self.check_paths(inp, force=False)

    def recursive_tool(self, key, inp, pattern):
        """T052 (R008 #7): the Grep tool searches below its `path` (default: the working directory); the Glob tool
        below its `path`, or below an absolute pattern's directory when the pattern holds `**`."""
        path = inp.get("path") if isinstance(inp.get("path"), str) and inp.get("path") else None
        if key == "grep":
            root = path or self.analyzer.cwd
        elif key == "glob" and path is not None:
            root = path
        elif key == "glob" and isinstance(pattern, str) and "**" in pattern:
            root = pattern if pattern.startswith(("/", "~")) else self.analyzer.cwd
        else:
            return
        self.analyzer.recursive_root(root, self.analyzer.cwd, "%s path=%s" % (key, root))

    def check_paths(self, inp, force):
        for key in _PATH_KEYS:
            value = inp.get(key)
            if isinstance(value, str) and value:
                self.analyzer.read_word(value, key + "=" + value, "read", force=force)

    def check_write(self, key, inp):
        an = self.analyzer
        path = inp.get("file_path") or inp.get("notebook_path")
        if not isinstance(path, str) or not path:
            an.add("malformed-entry", json.dumps(inp, default=str)[:160])
            return
        an.write(path, _WRITE_TOOLS[key], key + " " + path)
        texts = [inp.get(k) for k in ("content", "new_string", "new_source")]
        edits = inp.get("edits")
        if isinstance(edits, list):
            texts.extend(e.get("new_string") for e in edits if isinstance(e, dict))
        for text in texts:
            if isinstance(text, str):
                for match in rules.SECRET_NAME_RE.finditer(text):
                    an.add("secret-env-in-file", key + " " + path, match.group(0))
        if key == "write":
            an.record_file(path, inp.get("content"))

    def line(self, number, obj):
        blocks, malformed = blocks_of(obj)
        if malformed:
            self.add(number, "", "malformed-entry", json.dumps(obj, default=str))
        results = sum(1 for b in blocks if isinstance(b, dict) and b.get("type") == "tool_result")
        for block in blocks:
            if not isinstance(block, dict):
                self.add(number, "", "malformed-entry", json.dumps(block, default=str))
            elif block.get("type") == "tool_use":
                self.tool_use(number, block)
            elif block.get("type") == "tool_result":
                self.announce(obj, block, results)
                self.own_dir(block)
                self.own_pids(block)
                self.judge_pending(block)


def audit(parsed, policy, task):
    run = Audit(policy, task)
    for number, obj in parsed:
        if obj is None:
            run.add(number, "", "unparseable-line", "line %d is not a JSON object" % number)
        else:
            run.line(number, obj)
    for number, name, inp in run.pending.values():
        run.add(number, name, "malformed-entry", json.dumps(inp, default=str)[:160])
    if run.tool_uses == 0:
        run.add(0, "", "no-tool-use", "no tool_use block in the transcript")
    run.findings.sort(key=lambda f: (f["line"], f["rule"], f["tool"], f["excerpt"]))
    run.findings, run.repeats = collapse_repeats(run.findings)
    return run


def collapse_repeats(findings):
    """Keep the first of identical `review` findings (same rule, tool and excerpt); never touch a `block`.

    A script run twenty times is one thing for a reviewer to look at, not twenty. Returns the findings and
    the number collapsed."""
    seen, kept, dropped = set(), [], 0
    for finding in findings:
        key = (finding["rule"], finding["tool"], finding["excerpt"])
        if finding["severity"] == rules.REVIEW and key in seen:
            dropped += 1
            continue
        seen.add(key)
        kept.append(finding)
    return kept, dropped


# -- output ----------------------------------------------------------------------------------
def result_document(run, task, worktree, lines):
    status = "FAIL" if any(f["severity"] == rules.BLOCK for f in run.findings) else "PASS"
    return {"gate": GATE_ID, "status": status, "findings": run.findings,
            "metadata": {"task": task.task_id, "role": task.role, "worktree": worktree, "lines": lines,
                         "tool_uses": run.tool_uses, "repeats_collapsed": run.repeats}}


def format_table(document):
    rows = [("LINE", "TOOL", "SEVERITY", "RULE", "EXCERPT")]
    rows += [(str(f["line"]), f["tool"], f["severity"], f["rule"], f["excerpt"]) for f in document["findings"]]
    widths = [max(len(row[i]) for row in rows) for i in range(4)]
    out = ["  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row[:4])) + "  " + row[4] for row in rows]
    blocks = sum(1 for f in document["findings"] if f["severity"] == rules.BLOCK)
    out.append("%s: %s (%d block, %d review)" % (GATE_ID, document["status"], blocks,
                                                 len(document["findings"]) - blocks))
    return "\n".join(out)


def run(args):
    task = load_task(args.task)
    parsed = read_transcript(args.transcript)
    worktree = find_worktree(parsed, args.worktree)
    policy = PathPolicy(worktree, args.allow_write or [], args.home)
    result = audit(parsed, policy, task)
    document = result_document(result, task, policy.worktree, len(parsed))
    payload = jsonio.canonical_dumps(document)
    if args.out:
        jsonio.write_atomic(args.out, payload)
    if args.json:
        print(payload.decode("ascii"), end="")
    else:
        print(format_table(document))
    return EXIT_FAIL if document["status"] == "FAIL" else EXIT_PASS


def add_parser(subparsers):
    parser = subparsers.add_parser("trajectory", allow_abbrev=False,
                                   help="audit a contributor agent's transcript for forbidden behaviour")
    parser.add_argument("--transcript", required=True, help="Claude Code subagent transcript (JSONL)")
    parser.add_argument("--task", required=True, help="task contract TOML file, or TOML text")
    parser.add_argument("--allow-write", action="append", default=[], metavar="DIR",
                        help="extra writable scratch directory (repeatable)")
    parser.add_argument("--worktree", help="the task worktree (default: cwd recorded in the transcript)")
    parser.add_argument("--home", default=rules.DEFAULT_HOME, help="what ~ means to the agent")
    parser.add_argument("--json", action="store_true", help="print the JSON result instead of the table")
    parser.add_argument("--out")
    parser.set_defaults(handler=run, gate_id=GATE_ID)
