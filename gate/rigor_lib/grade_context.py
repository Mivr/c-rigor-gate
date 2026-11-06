"""State shared by the steps of `rigor grade`, and the checks done before any step runs."""

import os
import shutil
import subprocess
from dataclasses import dataclass, field

from rigor_lib import gitrun
from rigor_lib.errors import InternalError

# gate/rigor_lib/grade_context.py -> the gate repository root
GATE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
ORDER_FILE = os.path.join(GATE_ROOT, "gate", "order.txt")
MODES = ("release", "san")
SEALED_PATH = "/usr/local/bin:/usr/bin:/bin"


@dataclass
class Grading:
    args: object          # parsed command line (paths already absolute)
    product: object       # ProductConfig
    gate_sha: str
    work: str
    src: str              # clone of the product repository
    tree: str             # the grading tree Buck2 builds in
    results: str          # one <gate id>.json per gate
    test_results: str     # per mode: a directory of *.jsonl
    base: str = ""
    head: str = ""
    # mode -> directory of results files; set by the build step only for a clean build
    built: dict = field(default_factory=dict)
    # gate id -> "PASS" | "FAIL" for the gates that have finished
    status: dict = field(default_factory=dict)
    # relative paths of the product files copied into the tree (set by the assemble step)
    product_paths: list = field(default_factory=list)
    # the facts build, done once for both fact gates (set by grade_checks)
    facts: object = None


def gate_checkout_sha():
    """Commit of the gate checkout this code runs from; refuse if tracked files differ from it."""
    dirty = gitrun.run_git(GATE_ROOT, ["status", "--porcelain=v1", "-z", "--untracked-files=no",
                                       "--ignore-submodules=none"])
    if dirty != b"":
        raise InternalError("the gate checkout has uncommitted changes to tracked files")
    sha = gitrun.run_git(GATE_ROOT, ["rev-parse", "--verify", "HEAD"]).decode("ascii").strip()
    return sha


def _make_writable(function, path, _info):
    os.chmod(os.path.dirname(path), 0o755)
    os.chmod(path, 0o755)
    function(path)


def remove_tree(path):
    shutil.rmtree(path, onerror=_make_writable)


def sealed_env(work):
    """The only environment any subprocess of a grading gets.

    Buck2 reads `$HOME/.buckconfig.local` and `$HOME/.buckconfig.d/*` (found by experiment;
    `~/.buckconfig` and XDG paths are not read), and honours BUCK*/LD_*/proxy variables, so HOME is an
    empty directory inside the work dir and nothing else is inherited.
    """
    home = os.path.join(work, "home")
    tmp = os.path.join(work, "tmp")
    os.makedirs(home, exist_ok=True)
    os.makedirs(tmp, exist_ok=True)
    return {"HOME": home, "PATH": SEALED_PATH, "LANG": "C.UTF-8", "TMPDIR": tmp}


def seal_process_environment(work):
    """Replace this process's environment (in-process git and ssh-keygen calls inherit it)."""
    env = sealed_env(work)
    os.environ.clear()
    os.environ.update(env)


def kill_daemon(tree):
    """Stop the Buck2 daemon of a grading tree. Never raises: this runs on every exit path."""
    script = os.path.join(tree, "gate", "tools", "buck2")
    if not os.path.isfile(script):
        return
    try:
        subprocess.run(["bash", script, "kill"], cwd=tree, stdin=subprocess.DEVNULL,
                       env=sealed_env(os.path.dirname(tree)), capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        pass


def prepare_work(work):
    """Create `work` and clear what an earlier run left in it (stopping its daemon first)."""
    os.makedirs(work, exist_ok=True)
    kill_daemon(os.path.join(work, "tree"))
    for name in ("src", "tree", "results", "test-results", "facts", "mutants-reports", "home", "tmp"):
        path = os.path.join(work, name)
        if os.path.lexists(path):
            remove_tree(path)
    os.makedirs(os.path.join(work, "results"))
    sealed_env(work)  # creates the empty HOME and TMPDIR
