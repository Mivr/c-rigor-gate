"""Shared fixtures of the ui-time judge tests (no tests here): a timed product simulated in Python, millisecond by
millisecond, that turns path words into the explorer's Steps (semantic, frame, patches, identity), and a runner over it.
Nothing reads the wall clock: every instant is virtual."""

import hashlib
from types import SimpleNamespace

from rigor_lib import ui_contract
from rigor_lib.ui_explore_grammar import FRAME_FIELDS, parse_identity, parse_record, parse_typed_line
from rigor_lib.ui_explore_run import Step

from tests.test_ui_judge_helpers import REPO, esc

TIME_CONTRACT = REPO / "selftest" / "ui_canary_product" / "time.toml"
INPUTS = ("show", "flash", "blink", "silent", "other", "later", "bump")


def contract(edit=None):
    text = TIME_CONTRACT.read_text()
    return ui_contract.loads(text if edit is None else edit(text))


def ceil_s(ms):
    return -(-ms // 1000)


class Sim:
    """The notice: `show` puts a dialog (keys 5 card, 6 text, 7 countdown) on the main screen (key 1). Knobs: `life`
    (ms, None: never leaves), `count(elapsed, life)` the countdown value, `wrap32` (the expiry kept modulo 2^32, so it
    expires at once from an origin of 2^32 or more), `identity`. `flash` creates and removes key 9 within the input,
    `blink` shows key 9 for 200 ms, `silent` turns the state class to `detail` 1000 ms later without any visible
    change, `other` shows a dialog of another text."""

    def __init__(self, life=4000, count=None, wrap32=False, identity=True, text="Saved.", diverge=False,
                 lie=False):
        self.life, self.wrap32, self.identity, self.text, self.diverge = life, wrap32, identity, text, diverge
        self.lie = lie            # patches that claim the countdown changed when the records say it did not
        self.count = count or (lambda elapsed, life: ceil_s(life - elapsed))
        self.runs = []

    def scene(self, t, st):
        nodes = {"1": ("text", "Title")}
        cls = "main"
        if st["shown"] is not None and t >= st["shown"] and (st["until"] is None or t < st["until"]):
            elapsed = t - st["shown"]
            nodes.update({"5": ("dialog", ""), "6": ("text", st["text"]),
                          "7": ("countdown", "%d s" % self.count(elapsed, self.life if self.life else 0))})
            cls = "dialog"
        if st["blink"] is not None and t < st["blink"]:
            nodes["9"] = ("panel", "")
        if st["silent"] is not None and t >= st["silent"] and cls == "main":
            cls = "detail"
        return nodes, cls

    def _input(self, word, now, st):
        if word in ("show", "other"):
            st["shown"], st["text"] = now, self.text if word == "show" else "Another notice, longer than the first."
            st["until"] = None if self.life is None else now + self.life
            if self.wrap32 and now >= 2**32:
                st["until"] = now           # the expiry modulo 2^32 compared with the 64-bit clock: already past
        elif word == "later":           # the product's own deadline shows the dialog 2 s after the input
            st["shown"], st["text"] = now + 2000, self.text
            st["until"] = None if self.life is None else now + 2000 + self.life
        elif word == "bump":            # restarts a shown dialog's countdown (an input that raises it)
            st["shown"], st["until"] = now, None if self.life is None else now + self.life
        elif word == "blink":
            st["blink"] = now + 200
        elif word == "silent":
            st["silent"] = now + 1000
        return [("create", "9", "node", "-", "panel"), ("remove", "9", "node", "panel", "-")] if word == "flash" else []

    def run(self, words):
        self.runs.append(list(words))
        if self.diverge and len(self.runs) > 1:
            words = [w if w != "show" else "other" for w in words]     # a product that differs on a later run
        origin = int(words[0].split(" ")[1])
        st = {"shown": None, "until": None, "text": "", "blink": None, "silent": None}
        now, steps, scene = origin, [], None
        for index, word in enumerate(words):
            extra = []
            target = now
            if word.startswith("at "):
                target = max(now, origin + int(word.split(" ")[1]))
            elif word == "fire-due":
                target = now + 1000
            elif index > 0:
                extra = self._input(word, now, st)
            patches = list(extra)
            if scene is None:
                scene = self.scene(now, st)[0]
            for t in range(now, target + 1):
                new = self.scene(t, st)[0]
                patches += _diff(scene, new)
                scene = new
            if self.lie and word.startswith("at "):
                patches.append(("update", "7", "text", "9 s", "8 s"))
            now = target
            steps.append(self._step(index, word, now, origin, st, patches))
        return steps

    def _step(self, index, word, now, origin, st, patches):
        nodes, cls = self.scene(now, st)
        semantic = tuple(parse_record("semantic", "\t".join([key, role, esc(label.encode()), "0", "0", "10", "10",
                                                             "1", "-", "-", "1", "-", "-", "-"]))
                         for key, (role, label) in nodes.items())
        crc = hashlib.sha256(repr(sorted(nodes.items())).encode()).hexdigest()[:8]
        step = Step(index, word, origin=origin, now=now)
        step.obs = {"semantic": semantic, "frame": tuple(parse_typed_line(FRAME_FIELDS, line) for line in
                                                         ("lvprobe\t1\t1", "frame\t320\t240\t" + crc)),
                    "patches": tuple(parse_record("patches", "\t".join(p)) for p in patches), "trace": (),
                    "due": None, "env": ()}
        if self.identity:
            step.obs["identity"] = parse_identity(["state\t" + cls])
        step.key = hashlib.sha256(repr(sorted(nodes.items())).encode()).hexdigest()
        step.proj = {"nodes": [], "facts": {}}
        return step


def _diff(old, new):
    out = []
    for key in old:
        if key not in new:
            out.append(("remove", key, "node", old[key][0], "-"))
        elif old[key][1] != new[key][1]:
            out.append(("update", key, "text", esc(old[key][1].encode()), esc(new[key][1].encode())))
    out += [("create", key, "node", "-", new[key][0]) for key in new if key not in old]
    return out


class Catalogue:
    def __init__(self, max_wait_ms=600000):
        self.max_wait_ms = max_wait_ms

    @staticmethod
    def by_id(word):
        if word == "fire-due":
            return SimpleNamespace(cls="t1")
        return SimpleNamespace(cls="u1") if word in INPUTS else None


class Runner:
    """The explorer's Runner (ui_explore_time) over the simulated product."""

    def __init__(self, sim, max_wait_ms=600000):
        self.sim, self.catalogue = sim, Catalogue(max_wait_ms)
        self.cost = {"probe_runs": 0, "origin_runs": 0, "probe_commands": 0, "virtual_ms": 0}

    def probe(self, words):
        self.cost["probe_runs"] += 1
        return self.sim.run(words)

    def once(self, words):
        self.cost["origin_runs"] += 1
        return self.sim.run(words)
