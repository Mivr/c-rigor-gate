"""Writes the fixture oracle bundle (T2G7): the Rust side of the toy pad kiosk as vm-trace/1 traces plus oracle.toml.

    python3 -I -B selftest/sim/oracle/gen_traces.py DIR      # DIR/oracle.toml and DIR/files/<id>.trace

The model here is the Rust viewmodel's stand-in; selftest/sim/oracle/replay.c is the C app's. Deterministic: running it twice
gives the same bytes (selftest/sim.sh checks the committed bundle against it).
"""

import hashlib
import json
import os
import sys

PRODUCT = "canary"
SRC = "0" * 40
PAD = 4


def compact(value):
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def cfg(trace_id, seed):
    return compact({"k": "cfg", "v": "vm-trace/1", "id": trace_id, "src": SRC, "seed": seed, "start_ms": 0, "lang": "bg",
                    "inventory": {"sizes": [1], "lockers": [{"id": 1, "size": 1, "row": 1, "col": 2}]},
                    "codes": [{"code": "1234", "role": "visitor"}], "pulse_units": 5, "min_free_mb": 10, "offline_age_ms": None})


class Pad:
    def __init__(self):
        self.entered, self.opened, self.countdown = 0, False, 0

    def step(self, t, op):
        """The fx lines (as dicts) of one input."""
        effects = []
        name = op["op"]
        if name == "digit" and not self.opened and self.entered < PAD:
            self.entered += 1
        elif name == "backspace" and not self.opened and self.entered > 0:
            self.entered -= 1
        elif name == "cancel" and not self.opened:
            self.entered = 0
        elif name == "submit" and not self.opened and self.entered == PAD:
            effects = [{"port": "codes.role_of"}, {"port": "opener.open", "row": 1, "col": 2}]
            self.opened, self.entered, self.countdown = True, 0, 3000
        elif name == "tick" and self.opened:
            self.countdown -= op["adv_ms"]
            if self.countdown <= 0:
                self.countdown, self.opened = 0, False
                effects = [{"port": "audit.append", "kind": "closed"}]
        elif name == "ack_opened" and self.opened:
            self.opened, self.countdown = False, 0
        return effects

    def view(self):
        # Written by hand, in the canonical order of the C text.
        return '{"screen":"%s","entered":%d,"countdown_ms":%d}' % ("opened" if self.opened else "pad", self.entered, self.countdown)


def trace(trace_id, seed, ops):
    lines, pad, t = [cfg(trace_id, seed)], Pad(), 0
    for op in ops:
        if op["op"] == "tick":
            t += op["adv_ms"]
        lines.append(compact(dict(k="in", t=t, **op)))
        lines.extend(compact(dict(k="fx", t=t, **fx)) for fx in pad.step(t, op))
        lines.append('{"k":"vw","t":%d,"s":%s}' % (t, pad.view()))
    return "\n".join(lines) + "\n", len(ops)


def random_ops(seed, count):
    state, ops = seed, []
    for _ in range(count):
        state = (state * 6364136223846793005 + 1442695040888963407) % (1 << 64)
        pick = (state >> 33) % 10
        if pick < 5:
            ops.append({"op": "digit", "d": (state >> 40) % 10})
        elif pick == 5:
            ops.append({"op": "backspace"})
        elif pick == 6:
            ops.append({"op": "submit"})
        elif pick == 7:
            ops.append({"op": "cancel"})
        elif pick == 8:
            ops.append({"op": "tick", "adv_ms": 250 * (1 + (state >> 45) % 8)})
        else:
            ops.append({"op": "ack_opened"})
    return ops


def digits(*ds):
    return [{"op": "digit", "d": d} for d in ds]


TRACES = {
    "scripted-01": (1, digits(1, 2, 3, 4) + [{"op": "submit"}, {"op": "tick", "adv_ms": 1000}, {"op": "tick", "adv_ms": 2000},
                                              {"op": "digit", "d": 9}, {"op": "submit"}]),
    "scripted-02": (2, digits(5, 6) + [{"op": "backspace"}, {"op": "cancel"}, {"op": "submit"}] + digits(1, 2, 3, 4, 5, 6)
                    + [{"op": "submit"}, {"op": "ack_opened"}, {"op": "tick", "adv_ms": 250}]),
}
for seed in (11, 12):
    TRACES["random-%04d" % seed] = (seed, random_ops(seed, 24))


def main(directory):
    os.makedirs(os.path.join(directory, "files"), exist_ok=True)
    rows = []
    for trace_id, (seed, ops) in sorted(TRACES.items()):
        text, steps = trace(trace_id, seed, ops)
        with open(os.path.join(directory, "files", trace_id + ".trace"), "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        rows.append('[trace."%s"]\nsha256 = "%s"\nsteps = %d\n' % (trace_id, hashlib.sha256(text.encode()).hexdigest(), steps))
    with open(os.path.join(directory, "oracle.toml"), "w", encoding="utf-8", newline="\n") as handle:
        handle.write('product = "%s"\norigin = "T2G7-fixture"\nproduced_from = "%s"\n\n' % (PRODUCT, SRC) + "\n".join(rows))


if __name__ == "__main__":
    main(sys.argv[1])
