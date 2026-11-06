"""Resource meter for a whole canary-pack run (T025). Python 3 standard library only.

    python3 -I -B canaries/measure.py [--sample S] -- selftest/canaries.sh [runner args]

Runs the command with TMPDIR pointing at a fresh private directory and samples /proc while it runs.
A process counts if it descends from the command or has its working directory inside that directory
(Buck2 daemons detach, so their cwd is the way to find them). Reports, as one line:
wall seconds, local CPU seconds (user+system of every counted process, daemons included), peak
total RSS (MiB) and peak scratch disk (MiB, apparent size of regular files). Worker time is not here:
it comes from tools/lanes/buck2_stats.py over the kept trees.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

TICK = os.sysconf("SC_CLK_TCK")
PAGE = os.sysconf("SC_PAGE_SIZE")


def read_stat(pid):
    try:
        with open("/proc/%d/stat" % pid, "rb") as handle:
            raw = handle.read()
    except OSError:
        return None
    rest = raw[raw.rindex(b")") + 2:].split()
    return int(rest[1]), (int(rest[11]) + int(rest[12])) / TICK, int(rest[21]) * PAGE


def counted(pid, ppid, roots, scratch):
    if ppid in roots:
        return True
    try:
        return os.readlink("/proc/%d/cwd" % pid).startswith(scratch)
    except OSError:
        return False


def disk_bytes(path):
    total = 0
    for base, _dirs, files in os.walk(path):
        for name in files:
            try:
                st = os.lstat(os.path.join(base, name))
            except OSError:
                continue
            total += st.st_blocks * 512
    return total


class Meter(threading.Thread):
    def __init__(self, root_pid, scratch, period):
        super().__init__(daemon=True)
        self.roots, self.scratch, self.period = {root_pid}, scratch, period
        self.cpu, self.peak_rss, self.peak_disk = {}, 0, 0
        self.stop = threading.Event()

    def sample(self):
        rss_now = 0
        for name in os.listdir("/proc"):
            if not name.isdigit():
                continue
            pid = int(name)
            stat = read_stat(pid)
            if stat is None:
                continue
            ppid, cpu, rss = stat
            if pid in self.roots or counted(pid, ppid, self.roots, self.scratch):
                self.roots.add(pid)
                self.cpu[pid] = max(self.cpu.get(pid, 0.0), cpu)
                rss_now += rss
        self.peak_rss = max(self.peak_rss, rss_now)

    def run(self):
        last_disk = 0.0
        while not self.stop.is_set():
            self.sample()
            if time.time() - last_disk > 10:
                self.peak_disk = max(self.peak_disk, disk_bytes(self.scratch))
                last_disk = time.time()
            self.stop.wait(self.period)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=float, default=0.5)
    parser.add_argument("--keep", action="store_true", help="leave the scratch directory (for buck2_stats)")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("no command")
    scratch = tempfile.mkdtemp(prefix="rigor-measure.", dir=os.environ.get("TMPDIR", "/var/tmp"))
    env = dict(os.environ, TMPDIR=scratch)
    started = time.time()
    child = subprocess.Popen(command, env=env)
    meter = Meter(child.pid, scratch, args.sample)
    meter.start()
    code = child.wait()
    wall = time.time() - started
    meter.stop.set()
    meter.join()
    print("RESOURCES: wall %.0fs, local cpu %.0fs, peak rss %.0f MiB, peak scratch %.0f MiB, exit %d" % (
        wall, sum(meter.cpu.values()), meter.peak_rss / 2**20, meter.peak_disk / 2**20, code))
    if args.keep:
        print("scratch kept: %s" % scratch)
    else:
        shutil.rmtree(scratch, ignore_errors=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
