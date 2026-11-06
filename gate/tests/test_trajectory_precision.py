"""Unit tests for the precision work of `rigor trajectory` (T019, backlog B20): loops, expansions, collapse."""

import sys
import unittest

from rigor_lib import trajectory as trajectory_module
from rigor_lib import trajectory_code as code
from rigor_lib import trajectory_flow as flow
from rigor_lib import trajectory_literals as literals
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
