"""`rigor trajectory`: structured audit of a contributor agent's tool-use transcript (backlog B10).

The input is a Claude Code subagent transcript (JSONL). Every tool call is checked against the rule
table in trajectory_rules.py: forbidden reads, writes outside the worktree, forbidden commands and
tamper signals. `block` findings fail the audit (exit 1); `review` findings are printed only.
Anything the audit cannot parse is a finding; an empty or unreadable transcript is exit 2.
"""

import json

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

    def add(self, number, tool, rule, excerpt):
        self.findings.append({"rule": rule, "severity": rules.severity(rule), "line": number, "tool": tool,
                              "excerpt": rules.redact(excerpt)})

    def announce(self, number, block):
        """A tool_result that says "Full output saved to: <path>" makes that exact path readable."""
        if block.get("is_error"):
            return
        match = rules.OUTPUT_SAVED_RE.match(result_text(block))
        if match is None:
            return
        path = match.group(1)
        if any(path in earlier for earlier in self.seen_input):
            return  # the agent already knew the path: not a harness-chosen file name
        normal = self.policy.normalize(path, self.policy.worktree)
        if normal is not None:
            self.policy.exempt.add(normal)

    def tool_use(self, number, block):
        name, inp = block.get("name"), block.get("input")
        if not isinstance(name, str) or not isinstance(inp, dict):
            self.add(number, str(name), "malformed-entry", json.dumps(block, default=str))
            return
        self.tool_uses += 1
        self.seen_input.append(json.dumps(inp, sort_keys=True, default=str))
        self.dispatch(name, inp)
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
        for block in blocks:
            if not isinstance(block, dict):
                self.add(number, "", "malformed-entry", json.dumps(block, default=str))
            elif block.get("type") == "tool_use":
                self.tool_use(number, block)
            elif block.get("type") == "tool_result":
                self.announce(number, block)


def audit(parsed, policy, task):
    run = Audit(policy, task)
    for number, obj in parsed:
        if obj is None:
            run.add(number, "", "unparseable-line", "line %d is not a JSON object" % number)
        else:
            run.line(number, obj)
    if run.tool_uses == 0:
        run.add(0, "", "no-tool-use", "no tool_use block in the transcript")
    run.findings.sort(key=lambda f: (f["line"], f["rule"], f["tool"], f["excerpt"]))
    return run


# -- output ----------------------------------------------------------------------------------
def result_document(run, task, worktree, lines):
    status = "FAIL" if any(f["severity"] == rules.BLOCK for f in run.findings) else "PASS"
    return {"gate": GATE_ID, "status": status, "findings": run.findings,
            "metadata": {"task": task.task_id, "role": task.role, "worktree": worktree, "lines": lines,
                         "tool_uses": run.tool_uses}}


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
