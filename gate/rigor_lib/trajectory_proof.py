"""Proofs read from a Bash call's own output (T052, R008 #4b, #4c).

Two exceptions trust a line in a tool result: a pid the agent started may be killed (`kill-foreign`), and a
scratch dir its own `selftest/grade.sh` / `selftest/canaries.sh --keep` run printed may be removed (`write-outside`).
A command can print any line, so a line proves something only when nothing else in that call could have printed it.
While the audit analyses a Bash call it records, per command, whose output can reach the result (`CallFacts`):

* `forge_text`: a command could print agent-chosen text containing `/` (a `kept`/`SUMMARY` line names a path);
* `forge_digits`: a command could print any agent-chosen text (a pid line is just digits).

What cannot forge: a command whose stdout and stderr both go to files; the product's own grade/canary keep run; the
`tools/job run` call itself (CMD's output goes to the job log); `echo $!` after a command the lexer put in the
background; a short list of programs that print nothing on success and only `prog: ...` errors (a word with a
newline voids that); `grep -q`; line filters (`head`, `tail`, `grep`, `cat`, `sort`, `uniq` without byte or `-o`
options) that read only their stdin or a keep run's own output file. `ls` without a wildcard and `git status` print
names without `/` (or behind a status column): they cannot forge a path line, but can forge digits. Everything
else (echo, printf, ps, pgrep, an interpreter, any other program) can forge both.
"""

import re

from rigor_lib import trajectory_cmds as cmds
from rigor_lib import trajectory_rules as rules
from rigor_lib.trajectory_shell import UNRESOLVED

_SILENT = ("cd", "export", "declare", "typeset", "local", "readonly", "unset", "true", "false", ":", "sleep", "wait",
           "mkdir", "rm", "rmdir", "chmod", "touch", "cp", "mv", "ln", "test", "[", "[[", "set", "shopt", "umask",
           "exit")
_DECLARERS = ("export", "declare", "typeset", "local", "readonly")
_FILTERS = ("head", "tail", "grep", "cat", "sort", "uniq")
_FILTER_VALUE_OPTS = ("-n", "-e", "-f", "-m", "-A", "-B", "-C", "--max-count", "--regexp", "--file", "-k", "-t")
_BAD_FILTER_OPT = re.compile(r"\A(?:-[A-Za-z]*[oc][A-Za-z0-9]*|--only-matching|--bytes(?:=.*)?|--count|-c\d*)\Z")
_QUIET = re.compile(r"\A(?:-[A-Za-z]*[qs][A-Za-z]*|--quiet|--silent)\Z")
_GLOB = re.compile(r"[*?\[]")
_TERMINALS = ("/dev/stdout", "/dev/stderr", "/dev/tty")
GRADE_SCRIPT = "selftest/grade.sh"
CANARY_SCRIPT = "selftest/canaries.sh"


class CallFacts:
    """What one Bash call could have printed, and which proofs it may carry."""
    __slots__ = ("forge_text", "forge_digits", "background", "echo_bang", "jobs", "grade", "canary", "job_json")

    def __init__(self):
        self.forge_text = False
        self.forge_digits = False
        self.background = 0     # commands the lexer put in the background (`&`)
        self.echo_bang = 0      # `echo $!` after such a command
        self.jobs = {}          # NAME -> number of `tools/job run NAME` calls whose own output reaches the result
        self.grade = False      # a grade keep run, or a read of one's own output file, is in this call
        self.canary = False     # a canary keep run is in this call
        self.job_json = False   # `cat .../job.json` of a file nothing in the transcript wrote (T100)

    def forge(self, text=True):
        self.forge_digits = True
        self.forge_text = self.forge_text or text


def _reaches(target):
    return target == "result" or target in _TERMINALS or target.startswith("/dev/fd/") or UNRESOLVED in target


def streams(redirects, expand):
    """(stdout reaches the result, stderr reaches it, stdout's file or None) after the redirections, in order.
    A pipe counts as the result: what a later stage prints of it is judged as that stage's own output."""
    out = err = "result"
    for redirect in redirects:
        op, fd = redirect.op, redirect.fd
        if op.startswith("<"):
            continue
        target = expand(redirect.target)
        if op in ("&>", "&>>") or (op == ">&" and fd is None and not target.isdigit() and target != "-"):
            out = err = target
        elif op == ">&":
            source = "closed" if target == "-" else out if target == "1" else err if target == "2" else "result"
            if fd == "2":
                err = source
            elif fd in (None, "1"):
                out = source
        elif op in (">", ">>", ">|"):
            if fd in (None, "1"):
                out = target
            elif fd == "2":
                err = target
    return _reaches(out), _reaches(err), (None if _reaches(out) or out == "closed" else out)


def _job_name(own):
    """NAME of a `tools/job run [OPTS] NAME` argv (without the `-- CMD` part), or None."""
    i = 2
    while i < len(own):
        if own[i] in ("--deadline", "--dir"):
            i += 2
        elif own[i].startswith("-"):
            i += 1
        else:
            return own[i]
    return None


class ProofMixin:
    """Analyzer methods: record a call's CallFacts while its commands are analysed."""

    def note_output(self, item, argv, depth, env):
        facts = self.facts
        if facts is None or item.wrapped:
            return  # not inside a Bash call, or the CMD of `tools/job run` (its output goes to the job log)
        if item.cmd.background and depth == 0:
            facts.background += 1
        out, err, out_file = streams([] if item.wrapped else item.cmd.redirects,
                                     lambda word: self.expand(word, env))
        name = cmds.name_of(argv[0]) if argv else ""
        script = self._keep_run(item, argv, env) if depth == 0 else None
        if script is not None:
            self._source(facts, script, out_file)
            return
        if not (out or err):
            return
        if not argv:
            return  # assignments only
        if item.inner is not None and depth == 0:
            job = _job_name(argv)
            if out and job is not None and "\n" not in job:
                facts.jobs[job] = facts.jobs.get(job, 0) + 1
            return
        if depth == 0 and argv == ["echo", rules.BACKGROUND_PID] and facts.background:
            facts.echo_bang += 1
            return
        self._judge(facts, name, argv, item)

    def _judge(self, facts, name, argv, item):
        args = argv[1:]
        words = [w.text for w in item.cmd.words]
        if name in _SILENT and not any("\n" in w for w in words) and not (
                name in _DECLARERS and any(a.startswith("-") for a in args)):
            return
        if name == "grep" and any(_QUIET.match(a) for a in args):
            return
        if name == "ls" and not any(_GLOB.search(a) or UNRESOLVED in a for a in args):
            facts.forge(text=False)
            return
        if name == "git" and args[:1] == ["status"]:
            facts.forge(text=False)
            return
        if name == "cat" and self._job_records(args, item.cwd):
            facts.job_json = True  # tools/job's own record: its `pid` is a process the agent started (T100)
            return
        if name in _FILTERS and not any(_BAD_FILTER_OPT.match(a) for a in args):
            files = self._filter_files(name, args, item.cwd)
            if files is None:
                facts.forge()
                return
            if files:
                facts.forge(text=False)  # an output file holds digits too
                facts.grade = facts.grade or any(f in self.grade_outputs for f in files)
            return
        facts.forge()

    def _job_records(self, args, cwd):
        """True when `cat` reads only `.../job.json` files that tools/job wrote: none of them was written, copied or
        edited by anything in the transcript (T100)."""
        if not args or any(a.startswith("-") or not a.endswith("/job.json") for a in args):
            return False
        normals = [self.policy.normalize(a, cwd) for a in args]
        return all(n is not None and n not in self.touched for n in normals)

    def _filter_files(self, name, args, cwd):
        """The files a line filter reads ([] for stdin only), or None when one is not a keep run's output file."""
        indexes = cmds.positionals(args, _FILTER_VALUE_OPTS)
        if name == "grep" and not any(a in ("-e", "--regexp", "-f", "--file") for a in args):
            indexes = indexes[1:]  # the pattern
        files = []
        for index in indexes:
            normal = self.policy.normalize(args[index], cwd)
            if normal is None or normal not in self.grade_outputs | self.call_outputs:
                return None
            files.append(normal)
        return files

    def _keep_run(self, item, argv, env):
        """GRADE_SCRIPT or CANARY_SCRIPT when this command is a keep run of the product's own script, else None.
        Grade: `RIGOR_GRADE_KEEP=1` (prefix, `env`, or exported earlier in the call). Canaries: `--keep` is one of
        its own arguments. Never with `-h`/`--help`."""
        if not argv:
            return None
        start = 1 if cmds.name_of(argv[0]) in rules.SHELLS else 0
        plain = cmds.positionals(argv[start:])
        if start and not plain:
            return None
        at = start + plain[0] if start else 0
        normal = self.policy.normalize(argv[at], item.cwd)
        script = self.policy.relative_to_worktree(normal) if normal is not None else None
        args = argv[at + 1:]
        if script not in (GRADE_SCRIPT, CANARY_SCRIPT) or any(a in ("-h", "--help") for a in args):
            return None
        if script == CANARY_SCRIPT:
            return script if "--keep" in args else None
        prefix = item.words[:len(item.words) - len(argv)]
        keep = dict(env)
        keep.update({n: self.expand(w, env) for n, w in item.cmd.assigns})
        keep.update(cmds.env_wrappers(prefix)[0])
        return script if keep.get("RIGOR_GRADE_KEEP") == "1" else None

    def _source(self, facts, script, out_file):
        normal = self.policy.normalize(out_file, self.cwd) if out_file else None
        if script == GRADE_SCRIPT:
            facts.grade = True
            if normal is not None:
                self.grade_outputs.add(normal)  # ruling 2: a later call may read the kept line from this file
        else:
            facts.canary = True
            if normal is not None:
                self.call_outputs.add(normal)  # canary proofs stay inside this call

    def forget_output(self, normal):
        """Another command wrote a keep run's output file: what it holds no longer proves anything."""
        self.grade_outputs.discard(normal)
        self.call_outputs.discard(normal)
