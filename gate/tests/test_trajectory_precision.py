"""Unit tests for the precision work of `rigor trajectory` (T019, backlog B20): loops, expansions, collapse."""

import sys
import unittest

from rigor_lib import trajectory as trajectory_module
from rigor_lib import trajectory_code as code
from rigor_lib import trajectory_flow as flow
from rigor_lib import trajectory_literals as literals
from rigor_lib import trajectory_proc as proc
from rigor_lib import trajectory_shell as shell
from tests import test_trajectory_cases as cases
from tests.test_trajectory import TrajectoryCase


def commands(text):
    return [[w.text for w in c.words] for c in shell.parse(text)]


class LexerTests(unittest.TestCase):
    def test_a_leading_reserved_word_is_not_the_command(self):
        found = shell.parse("for n in a b; do X=1; Y=2 echo $X; done")
        self.assertEqual(commands("for n in a b; do X=1; done"), [["for", "n", "in", "a", "b"], [], ["done"]])
        self.assertEqual([n for n, _ in found[1].assigns], ["X"])
        self.assertEqual([w.text for w in found[2].words], ["echo", "$X"])
        self.assertEqual([n for n, _ in found[2].assigns], ["Y"])

    def test_a_quoted_reserved_word_is_a_command(self):
        self.assertEqual(commands("'do' x"), [["do", "x"]])

    def test_while_and_for_stay_in_the_word_list(self):
        self.assertEqual(commands("while read x; do :; done")[0], ["while", "read", "x"])

    def test_arithmetic_is_not_a_command_substitution(self):
        word = shell.parse("x=$((a+1)) echo")[0].assigns[0][1]
        self.assertEqual((word.text, word.subs), (shell.UNRESOLVED, []))
        word = shell.parse('echo "$(($(date +%s) - 1))"')[0].words[1]
        self.assertEqual(word.subs, ["date +%s"])

    def test_a_subshell_in_a_substitution_is_still_a_substitution(self):
        word = shell.parse("echo $((echo hi) )")[0].words[1]
        self.assertEqual(word.subs, ["(echo hi) "])


    def test_subshell_depth_counts_parentheses_and_ignores_case_patterns(self):
        found = shell.parse("a; (b; (c); d); e")
        self.assertEqual([c.depth for c in found], [0, 1, 2, 1, 0])
        self.assertEqual([c.depth for c in shell.parse("case $x in a) b;; esac; c")], [0, 0, 0, 0])


class LoopTests(TrajectoryCase):
    def rules_of(self, *steps):
        _, result = self.audit_steps(list(steps), fast=True)
        return sorted(f["rule"] for f in result["findings"])

    def test_loop_values(self):
        self.assertEqual(flow._done_index(shell.parse("for a in 1; do for b in 2; do :; done; done; x"), 0), 4)
        self.assertEqual(flow._done_index(shell.parse("for a in 1; do :"), 0), -1)
        self.assertIsNone(flow._header_name(shell.parse("for ((i=0;i<3;i++)); do x; done")[0]))
        self.assertEqual(flow._header_name(shell.parse("for a in 1; do x; done")[0]), "a")

    def test_a_list_that_is_empty_or_too_long_leaves_the_body_audited_once(self):
        long_list = " ".join(str(n) for n in range(flow.MAX_VALUES + 1))
        for command in ('X=""; for p in $X; do gh pr list; done', "for p in %s; do gh pr list; done" % long_list):
            self.assertEqual(self.rules_of(cases.bash(command)), ["cmd-gh"])

    def test_the_iteration_budget_is_bounded(self):
        inner = "for c in %s; do echo $a$b$c > %s/x; done" % (" ".join("c%d" % n for n in range(40)), cases.SCRATCH)
        command = "for a in %s; do for b in %s; do %s; done; done" % (
            " ".join("a%d" % n for n in range(40)), " ".join("b%d" % n for n in range(40)), inner)
        self.assertEqual(self.rules_of(cases.bash(command + "; gh pr list")), ["cmd-gh"])

    def test_identical_hits_of_the_iterations_collapse_to_one(self):
        _, result = self.audit_steps([cases.bash("for m in a b c; do gh pr list; done")], fast=True)
        self.assertEqual([f["rule"] for f in result["findings"]], ["cmd-gh"])

    def test_the_loop_variable_does_not_leak_a_stale_value(self):
        self.assertEqual(self.rules_of(cases.bash("for p in $(ls); do cat /var/tmp/cache/T001/$p; done")),
                         ["read-other-cache"])
        self.assertEqual(self.rules_of(cases.bash("p=/etc; for p in $(ls); do cat $p; done")), ["path-unresolved"])


class CollapseTests(TrajectoryCase):
    def test_identical_reviews_are_reported_once_with_a_count(self):
        step = cases.bash("for p in $(ls); do cat $p; done")
        _, result = self.audit_steps([step, step, step], fast=True)
        self.assertEqual([f["line"] for f in result["findings"]], [1])
        self.assertEqual(result["metadata"]["repeats_collapsed"], 2)

    def test_blocks_are_never_collapsed(self):
        step = cases.bash("cat /var/tmp/.config/club/token")
        _, result = self.audit_steps([step, step], fast=True)
        self.assertEqual([f["line"] for f in result["findings"]], [1, 3])
        self.assertEqual(result["metadata"]["repeats_collapsed"], 0)

    def test_different_excerpts_stay_apart(self):
        findings = [{"rule": "path-unresolved", "severity": "review", "tool": "Bash", "excerpt": e, "line": n}
                    for n, e in enumerate(["cat $a", "cat $b"], start=1)]
        self.assertEqual(trajectory_module.collapse_repeats(findings), (findings, 0))


class LiteralTests(unittest.TestCase):
    def test_only_literals_in_file_and_process_calls_count(self):
        code = "print('/b')\nx = '/c'\nopen('/d')\np = '/e'\nPath(p)\nsubprocess.run(['cat', '/f'])\n"
        self.assertEqual(literals.path_literals(code), ["/d", "/e", "cat", "/f", "cat/f"])

    def test_nested_calls_and_triple_quotes(self):
        self.assertEqual(literals.path_literals("open(os.path.join('/a', 'b'))"), ["/a", "b", "/ab"])
        self.assertEqual(literals.path_literals('Path("""/x""")'), ["/x"])

    def test_variables_and_strings_are_joined_in_source_order(self):
        code_text = "ROOT = '/a/b'\nshutil.rmtree(ROOT + '/_tmp')\n"
        self.assertEqual(literals.path_literals(code_text), ["/a/b", "/_tmp", "/a/b/_tmp"])

    def test_a_call_written_inside_a_string_is_text(self):
        self.assertEqual(literals.path_literals("old = \'\'\'x = open('/s/k')\'\'\'\nopen(p)\n"), [])
        self.assertEqual(literals.path_literals("old = \"open('/s/k')\"\n"), [])
        self.assertEqual(literals.path_literals("# it's here\nopen('/s/j')\n"), ["/s/j"])

    def test_code_inside_an_fstring_and_after_a_stray_quote_is_still_code(self):
        self.assertEqual(literals.path_literals("print(f\"{open('/s/k')}\")"), ["/s/k"])
        self.assertEqual(literals.path_literals("n = \"it's\"\nopen('/s/k')\n"), ["/s/k"])
        self.assertEqual(literals.path_literals("exec(\"open('/s/k')\")"), ["open('/s/k')"])

    def test_write_text_arguments_are_the_text_written(self):
        self.assertEqual(literals.path_literals("p.write_text('/s/k')\nPath('/s/j').write_text('x')"), ["/s/j"])

    def test_unterminated_input_never_raises(self):
        for code in ("open('", "open(", "x = 'a", 'open("""', "#", "f'", "rb", "\"\"\"#"):
            literals.path_literals(code)


class ConcatFoldTests(unittest.TestCase):
    """T062: literal concatenations are folded before inline code is scanned."""

    def test_literal_chains_fold_into_one_literal(self):
        folded = {"open('/a/.co' + 'nfig')": 'open("/a/.config")', "open('/a/.co' 'nfig')": 'open("/a/.config")',
                  "my $p = '/a' . '/b';": 'my $p = "/a/b";', "b = '/a'\nq = b + '/c'": "b = '/a'\nq = \"/a/c\"",
                  "os.path.join('/a', 'b', 'c')": '"/a/b/c"', "os.path.join('/a', '/b')": '"/b"',
                  "Path('/a') / 'b' / 'c'": 'Path("/a/b/c")', "r'/a' + r'/b'": '"/a/b"'}
        for text, want in folded.items():
            self.assertEqual(literals.fold_concat(text), want, text)

    def test_strings_comments_and_computed_pieces_stay(self):
        kept = ("s = \'\'\'open('/a' + '/b')\'\'\'", "# '/a' + '/b'\nx = 1", "f'/a' + '/b'", "x = a + b",
                "'a'.join(['b'])", "e = d['k'] + 'z'", "s = 'a' + str(x)", "os.path.join(ROOT, 'x')")
        for text in kept:
            self.assertEqual(literals.fold_concat(text), text, text)

    def test_unterminated_input_never_raises(self):
        for text in ("'a' +", "'a' + '", "os.path.join('a'", "Path('a') /", "x = '", "#"):
            literals.fold_concat(text)


class ProcessCallTests(unittest.TestCase):
    """T062: the commands inline code runs and the pids it signals."""

    def test_commands_of_process_calls(self):
        self.assertEqual(proc.commands("os.system('gh api user')"), ["gh api user"])
        self.assertEqual(proc.commands("subprocess.run(['git', 'push'], check=True)"), ["'git' 'push'"])
        self.assertEqual(proc.commands("a = ['pkill', 'x']\nsubprocess.Popen(a)"), ["'pkill' 'x'"])
        self.assertEqual(proc.commands("subprocess.run('git push'.split())"), ["git push"])
        self.assertEqual(proc.commands("subprocess.run(f'pkill {n}', shell=True)"), ["pkill " + proc.UNKNOWN])
        self.assertEqual(proc.commands("system('gh', 'api')", "ruby"), ["'gh' 'api'"])
        self.assertEqual(proc.commands("puts `gh api`", "ruby"), ["gh api"])
        self.assertEqual(proc.commands("asyncio.create_subprocess_exec('git', 'push')"), ["'git' 'push'"])
        self.assertEqual(proc.commands("os.execlp('pkill', 'pkill', 'x')"), ["'pkill' 'x'"])

    def test_unknown_programs_text_and_python_exec_are_not_commands(self):
        for text in ("subprocess.run(cmd)", "os.system(line)", "subprocess.run([prog, 'x'])", "exec('x = 1')",
                     "s = \"os.system('gh api user')\"", "# os.system('gh api user')", "x = `a`"):
            self.assertEqual(proc.commands(text), [], text)

    def test_kill_targets_and_own_pids(self):
        text = "p = subprocess.Popen(['x'])\nos.kill(p.pid, 9)\nos.killpg(os.getpgid(p.pid), 9)\nos.kill(4242, 9)"
        self.assertEqual(proc.kill_targets(text), ["p.pid", "os.getpgid(p.pid)", "4242"])
        self.assertEqual([proc.own_target(t, text, set()) for t in proc.kill_targets(text)], [True, True, False])
        self.assertTrue(proc.own_target("4242", "", {"4242"}))
        self.assertTrue(proc.own_target("pid", "pid = os.fork()", set()))
        self.assertFalse(proc.own_target("int(sys.argv[1])", "", set()))
        self.assertEqual(proc.kill_targets("Process.kill('TERM', 7, 8)"), ["7", "8"])
        self.assertEqual(proc.kill_targets("kill 9, $pid;", "perl"), ["$pid"])
        self.assertEqual(proc.kill_targets("killall(1); $p->kill(2)", "perl"), [])

    def test_unterminated_input_never_raises(self):
        for text in ("os.system(", "subprocess.run([", "os.kill(", "system '", "`", "Process.kill("):
            proc.commands(text, "ruby")
            proc.kill_targets(text, "perl")


class EnvironmentCopyTests(unittest.TestCase):
    def found(self, text):
        match = code.whole_environment(text)
        return None if match is None else match.group(0)

    def test_whole_environment_itself_is_a_dump(self):
        for text in ("print(os.environ)", "x = os.environ", "print(dict(os.environ))", "f(os.environ.items())"):
            self.assertIsNotNone(self.found(text), text)

    def test_a_copy_used_for_a_child_is_not(self):
        quiet = ("e = dict(os.environ)\ne.update(A)\ne['B'] = 1\nrun(x, env=e)\n",
                 "run(x, env=dict(os.environ, A='1'))", "e = os.environ.copy()\ne.setdefault('A', 'b')",
                 "e: dict = {**os.environ, 'A': 'b'}\nprint(e['A'], e.get('B'))",
                 "def go(a, e):\n    return a\n\n\nenv = dict(os.environ)\ngo(1, env)\n")
        for text in quiet:
            self.assertIsNone(self.found(text), text)

    def test_any_other_use_of_the_copy_is_a_dump(self):
        loud = ("e = dict(os.environ)\nprint(e)", "e = dict(os.environ)\nfor k in e: pass",
                "e = dict(os.environ)\nunknown.call(e)", "e = os.environ.copy()\nreturn e",
                "def show(x):\n    print(x)\n\n\ne = dict(os.environ)\nshow(e)\n",
                "def show(x):\n    for k in x: pass\n\n\ne = dict(os.environ)\nshow(e)\n")
        for text in loud:
            self.assertIsNotNone(self.found(text), text)

    def test_a_deeply_nested_call_and_a_missing_callee_are_loud(self):
        self.assertIsNotNone(self.found("e = dict(os.environ)\n" + "(" * 3 + "e"))
        self.assertIsNotNone(self.found("e = dict(os.environ)\n[e]"))


if __name__ == "__main__":
    sys.exit(unittest.main())


class UnknownCwdAndPipedTextTests(TrajectoryCase):
    """T072 (B21, B23): an unresolvable `cd`, `cat <<EOF | tee f`, and clones that were moved, copied or linked."""

    def rules_of(self, *commands):
        _, result = self.audit_steps([cases.bash(c) for c in commands], fast=True)
        return sorted(f["rule"] for f in result["findings"])

    # -- B21: the working directory after a `cd` the audit cannot resolve ---------------------------------
    def test_a_relative_read_after_an_unresolvable_cd_is_unresolved(self):
        self.assertEqual(self.rules_of('cd "$DIR" && cat sub/notes.txt'), ["path-unresolved"])
        self.assertEqual(self.rules_of('cd "$(pick)"; head -3 ./notes.txt'), ["path-unresolved"])

    def test_a_relative_script_after_an_unresolvable_cd_is_unresolved(self):
        self.assertEqual(self.rules_of('cd "$DIR" && ./run.sh'), ["path-unresolved"])
        self.assertEqual(self.rules_of('cd "$DIR" && sh run.sh'), ["path-unresolved"])

    def test_the_unknown_directory_lasts_into_the_next_call(self):
        self.assertEqual(self.rules_of('cd "$DIR"', "cat sub/notes.txt"), ["path-unresolved"])

    def test_a_resolvable_cd_makes_it_known_again(self):
        self.assertEqual(self.rules_of('cd "$DIR"; cd %s; cat sub/notes.txt' % cases.SC), [])

    def test_a_subshell_keeps_the_directory_known_outside(self):
        self.assertEqual(self.rules_of('cd %s && (cd "$DIR"; true); cat sub/notes.txt' % cases.SC), [])
        self.assertEqual(self.rules_of('cd "$DIR" && (cd %s; cat sub/notes.txt); true' % cases.SC), [])

    def test_a_relative_forbidden_read_after_an_unresolvable_cd_still_blocks(self):
        self.assertEqual(self.rules_of('cd "$DIR" && cat .config/club/token'), ["read-secret-dir"])
        self.assertEqual(self.rules_of('cd "$DIR" && cat .config'), ["read-secret-dir"])

    # -- B21: `cat <<EOF | tee f` ------------------------------------------------------------------------
    def piped(self, flag, body, *more):
        return "cd %s && cat <<'EOF' | tee %sr.sh\n%s\nEOF\n" % (cases.SC, flag, body) + "\n".join(more)

    def test_a_piped_here_document_is_the_text_of_the_file(self):
        self.assertEqual(self.rules_of(self.piped("", "ls", "sh r.sh")), [])

    def test_the_text_a_piped_here_document_wrote_is_audited_when_run(self):
        self.assertEqual(self.rules_of(self.piped("", "gh pr list", "sh r.sh")), ["cmd-gh"])

    def test_tee_append_extends_the_known_text(self):
        first = self.piped("", "ls")
        self.assertEqual(self.rules_of(first + "cat <<'EOF' | tee -a r.sh\ngh pr list\nEOF\nsh r.sh"), ["cmd-gh"])

    def test_another_feeder_leaves_the_file_unknown(self):
        self.assertEqual(self.rules_of(self.piped("", "ls", "echo x | tee -a r.sh", "sh r.sh")), ["cmd-unresolved"])
        self.assertEqual(self.rules_of("cd %s && cat <<'EOF' | sed s/a/b/ | tee r.sh\nls\nEOF\nsh r.sh" % cases.SC),
                         ["cmd-obfuscated-exec"])
        self.assertEqual(self.rules_of("cd %s && cat <<'EOF' | tee r.sh\nls\nEOF\ncat x.txt | tee -a r.sh\nsh r.sh"
                                       % cases.SC), ["cmd-unresolved"])

    def test_an_append_to_an_unknown_file_stays_unknown(self):
        self.assertEqual(self.rules_of(self.piped("-a", "ls", "sh r.sh")), ["cmd-obfuscated-exec"])

    # -- B23: moved, copied and linked clones --------------------------------------------------------------
    def clone_then(self, *commands):
        make = "mkdir -p %s && cd %s && %s" % (cases.SC, cases.SC, cases.LOCAL_CLONE)
        return self.rules_of(make, *commands)

    def test_a_clone_moved_within_scratch_stays_proven(self):
        sc, clone = cases.SC, cases.CLONE
        self.assertEqual(self.clone_then("mv %s %s/moved && cd %s/moved && git fetch -q origin" % (clone, sc, sc)), [])
        self.assertEqual(self.clone_then("mkdir -p %s/sub && mv %s %s/sub/ && cd %s/sub/annas-c && git pull -q origin"
                                         % (sc, clone, sc, sc)), [])

    def test_a_clone_copied_within_scratch_stays_proven_and_the_original_too(self):
        sc, clone = cases.SC, cases.CLONE
        self.assertEqual(self.clone_then("cp -r %s %s/copy && cd %s/copy && git fetch -q origin" % (clone, sc, sc)), [])
        self.assertEqual(self.clone_then("cp -r %s %s/copy && cd %s && git fetch -q origin" % (clone, sc, clone)), [])

    def test_a_link_made_in_scratch_to_a_clone_keeps_the_proof(self):
        sc, clone = cases.SC, cases.CLONE
        self.assertEqual(self.clone_then("ln -s %s %s/lnk && cd %s/lnk && git fetch -q origin" % (clone, sc, sc)), [])

    def test_moving_or_linking_out_of_scratch_loses_the_proof(self):
        sc, clone = cases.SC, cases.CLONE
        net = ["cmd-git-network", "write-outside"]
        self.assertEqual(self.clone_then("mv %s /var/tmp/away && cd /var/tmp/away && git fetch -q origin" % clone), net)
        self.assertEqual(self.clone_then("ln -s %s /var/tmp/lnk && cd /var/tmp/lnk && git fetch -q origin" % clone), net)
        self.assertEqual(self.clone_then("cp %s %s/copy && cd %s/copy && git fetch -q origin" % (clone, sc, sc)),
                         ["cmd-git-network"])  # no -r: nothing was copied

    def test_a_config_edit_loses_the_proof_of_a_moved_clone_and_of_a_link(self):
        sc, clone = cases.SC, cases.CLONE
        net = ["cmd-git-network"]
        self.assertEqual(self.clone_then("echo x >> %s/.git/config; mv %s %s/moved && cd %s/moved && git fetch origin"
                                         % (clone, clone, sc, sc)), net)
        self.assertEqual(self.clone_then("mv %s %s/moved; echo x >> %s/moved/.git/config; cd %s/moved && "
                                         "git fetch origin" % (clone, sc, sc, sc)), net)
        self.assertEqual(self.clone_then("ln -s %s %s/lnk; echo x >> %s/lnk/.git/config; cd %s && git fetch origin"
                                         % (clone, sc, sc, clone)), net)


class ShellValueTests(TrajectoryCase):
    """T074 (B22): `NAME=$(mktemp ...)` and `NAME=(a b)` are modelled, each only where every value is known."""

    def rules_of(self, *commands):
        _, result = self.audit_steps([cases.bash(c) for c in commands], fast=True)
        return sorted(f["rule"] for f in result["findings"])

    SC = cases.SC

    def test_lexer_reads_an_array_assignment_as_one_assignment_not_a_subshell(self):
        found = shell.parse("B=(tools/buck2 -x 'a b')")
        self.assertEqual(len(found), 1)
        name, word = found[0].assigns[0]
        self.assertEqual((name, [w.text for w in word.array]), ("B", ["tools/buck2", "-x", "a b"]))
        self.assertEqual(shell.parse("B=()")[0].assigns[0][1].array, ())

    def test_lexer_keeps_the_substitutions_of_array_elements_and_leaves_odd_arrays_alone(self):
        self.assertEqual(shell.parse("B=(a $(date) b)")[0].assigns[0][1].subs, ["date"])
        for odd in ("B=(a; b)", "B=(*.c)", "B=(a >f)", "B=(x=1)"):
            self.assertEqual([c.depth for c in shell.parse(odd)][-1], 1, odd)  # read as before: a subshell command

    # -- mktemp ----------------------------------------------------------------------------------
    def test_mktemp_under_a_known_tmpdir_is_a_known_fresh_path(self):
        sc = self.SC
        self.assertEqual(self.rules_of("export TMPDIR=%s/tmp; out=$(mktemp -d); echo hi > $out/x; rm -rf $out" % sc), [])
        self.assertEqual(self.rules_of("out=$(mktemp -d -p %s); echo hi > $out/x" % sc), [])
        self.assertEqual(self.rules_of("out=$(mktemp %s/x.XXXXXX); echo hi > $out" % sc), [])
        self.assertEqual(self.rules_of("cd %s; out=$(mktemp -d tmp.XXXX); echo hi > $out/x" % sc), [])

    def test_mktemp_without_a_known_tmpdir_stays_unresolved(self):
        sc = self.SC
        for command in ('d=$(mktemp -d); echo hi > "$d/x"', 'd=$(mktemp -d); rm -rf "$d/.."',
                        'd=$(mktemp -d); cat "$d/../claude-1000/x"'):
            self.assertIn("path-unresolved" if "cat" in command else "write-unresolved", self.rules_of(command), command)
        self.assertEqual(self.rules_of('d=$(mktemp -d); rm -rf "$d/.."; echo hi > %s/x' % sc).count("write-outside"), 0)

    def test_dot_dot_out_of_a_known_mktemp_dir_is_judged_against_the_real_layout(self):
        sc = self.SC
        export = "export TMPDIR=%s/tmp; d=$(mktemp -d); " % sc
        self.assertEqual(self.rules_of(export + 'echo hi > "$d/../x"'), [])  # still the scratch
        self.assertEqual(self.rules_of(export + 'rm -rf "$d/../../.."'), ["write-outside"])
        self.assertEqual(self.rules_of(export + 'echo hi > "$d/../../../T098/x"'), ["write-outside"])
        self.assertIn("read-other-cache", self.rules_of(export + 'cat "$d/../../../T098/x"'))
        self.assertEqual(self.rules_of("export TMPDIR=/tmp; d=$(mktemp -d); rm -rf \"$d/..\""), ["write-outside"])

    def test_mktemp_in_a_forbidden_place_still_blocks(self):
        self.assertEqual(self.rules_of("export TMPDIR=/etc; out=$(mktemp -d); echo hi > $out/x"), ["write-outside"])
        self.assertEqual(self.rules_of("out=$(mktemp -d -p /var/tmp/other); echo hi > $out/x"), ["write-outside"])
        self.assertEqual(self.rules_of("out=$(mktemp /var/tmp/x.XXXXXX); rm -f $out"), ["write-outside"])
        self.assertEqual(self.rules_of("cd /var/tmp; out=$(mktemp x.XXXXXX); echo hi > $out"), ["write-outside"])
        self.assertIn("read-secret-dir", self.rules_of("out=$(mktemp -d -p /var/tmp/.config); cat $out/x"))

    def test_mktemp_that_cannot_be_known_stays_unresolved(self):
        for command in ('out=$(mktemp -d -p "$WHERE"); echo hi > $out/x', "out=$(mktemp --foo); echo hi > $out",
                        'export TMPDIR="$WHERE"; out=$(mktemp -d); echo hi > $out/x',
                        "out=$(mktemp -d nox); echo hi > $out", "out=$(mktemp a.XXX b.XXX); echo hi > $out",
                        "echo hi > $(mktemp)", "cd $(mktemp -d); echo hi > x"):
            self.assertIn("write-unresolved", self.rules_of(command), command)

    # -- arrays ----------------------------------------------------------------------------------
    def test_a_known_array_starts_the_command(self):
        sc = self.SC
        self.assertEqual(self.rules_of('B=(ls -l); "${B[@]}" %s' % sc), [])
        self.assertEqual(self.rules_of("B=(ls -l); B=(ls); echo hi > %s/x; \"${B[@]}\" %s" % (sc, sc)), [])
        self.assertEqual(self.rules_of("B=(rm -rf /); echo hi"), [])  # an array assignment runs nothing

    def test_a_known_array_is_judged_as_the_command_it_spells(self):
        self.assertEqual(self.rules_of('B=(cat); "${B[@]}" /var/tmp/.config/x'), ["read-secret-dir"])
        self.assertEqual(self.rules_of('B=(cat /var/tmp/.config/x); "${B[@]}"'), ["read-secret-dir"])
        self.assertEqual(self.rules_of('B=(gh pr); "${B[@]}" list'), ["cmd-gh"])
        self.assertEqual(self.rules_of('B=(bash -c "gh pr list"); "${B[@]}"'), ["cmd-gh"])
        self.assertEqual(self.rules_of("B=($(gh pr list)); echo hi"), ["cmd-gh"])

    def test_an_array_that_is_not_fully_known_stays_unresolved(self):
        for command in ('B=(ls $X); "${B[@]}"', 'B=(ls); B=($X); "${B[@]}"', 'B=(ls *.c); "${B[@]}"',
                        'B=(ls); "${B[1]}"', 'B=(ls); B+=(x); "${B[@]}"', 'B=(ls); B=cat; "${B[@]}"',
                        'B=(ls); unset B; "${B[@]}"', 'B=(ls); read -a B; "${B[@]}"',
                        'B=(ls); declare -a B=(cat /var/tmp/.config/x); "${B[@]}"', 'B=(ls); printf -v B x; "${B[@]}"'):
            self.assertIn("cmd-unresolved", self.rules_of(command), command)
