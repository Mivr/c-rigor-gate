"""Shared helpers for the rigor tests: run the real CLI and build tiny git repos."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from collections import namedtuple
from pathlib import Path

GATE_DIR = Path(__file__).resolve().parent.parent
RIGOR = GATE_DIR / "rigor"

Outcome = namedtuple("Outcome", "code stdout stderr")


def base_env():
    """Environment without any host git configuration."""
    env = {
        "PATH": os.environ.get("PATH", ""),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.invalid",
        "LC_ALL": "C",
    }
    return env


def run_rigor(args, path=None):
    """Run `gate/rigor` as a subprocess. `path` overrides PATH when given."""
    env = base_env()
    if path is not None:
        env["PATH"] = path
    argv = [sys.executable, "-I", "-B", str(RIGOR)] + [str(a) for a in args]
    done = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=120)
    return Outcome(done.returncode, done.stdout, done.stderr)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class TempDirTestCase(unittest.TestCase):
    """Gives each test a fresh temp directory in `self.tmp`."""

    def setUp(self):
        holder = tempfile.TemporaryDirectory(prefix="rigor-test-")
        self.addCleanup(holder.cleanup)
        self.tmp = Path(holder.name)

    def sub(self, name):
        path = self.tmp / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def assertExit(self, outcome, code):
        self.assertEqual(outcome.code, code, msg=outcome.stdout + outcome.stderr)


class Repo:
    """A tiny git repository driven through the git CLI."""

    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.git("init", "-q", "-b", "main")

    def git(self, *args, input_bytes=None):
        done = subprocess.run(
            ["git", "-C", str(self.root)] + [str(a) for a in args],
            env=base_env(), input=input_bytes, capture_output=True, timeout=60,
        )
        if done.returncode != 0:
            raise AssertionError("git %s failed: %s" % (args, done.stderr))
        return done.stdout.decode("utf-8", "replace").strip()

    def abs(self, rel):
        return os.path.join(os.fsencode(self.root), os.fsencode(rel))

    def write(self, rel, data, mode=None):
        full = self.abs(rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        payload = data.encode("utf-8") if isinstance(data, str) else data
        with open(full, "wb") as handle:
            handle.write(payload)
        if mode is not None:
            os.chmod(full, mode)

    def remove(self, rel):
        os.remove(self.abs(rel))

    def symlink(self, rel, target):
        full = self.abs(rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        os.symlink(os.fsencode(target), full)

    def add_gitlink(self, rel, sha):
        self.git("update-index", "--add", "--cacheinfo", "160000,%s,%s" % (sha, rel))

    def commit(self, message="c", add_all=True):
        if add_all:
            self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD")

    def branch(self, name):
        self.git("checkout", "-q", "-b", name)


class Signer:
    """A throwaway ssh key pair plus an allowed_signers file that trusts it."""

    NAMESPACE = "c-rigor-gate"

    def __init__(self, directory, name="owner", principal="owner", namespaces=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.key = self.directory / name
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", name,
                        "-f", str(self.key)], check=True, capture_output=True)
        public = (self.directory / (name + ".pub")).read_text(encoding="utf-8").strip()
        options = 'namespaces="%s"' % (namespaces or self.NAMESPACE)
        self.allowed_line = "%s %s %s\n" % (principal, options, public)

    def write_allowed_signers(self, path, extra_lines=()):
        Path(path).write_text("".join(extra_lines) + self.allowed_line, encoding="utf-8")
        return Path(path)

    def sign_file(self, data_path, namespace=None):
        subprocess.run(["ssh-keygen", "-Y", "sign", "-q", "-n", namespace or self.NAMESPACE,
                        "-f", str(self.key), str(data_path)], check=True, capture_output=True)
        return Path(str(data_path) + ".sig")
