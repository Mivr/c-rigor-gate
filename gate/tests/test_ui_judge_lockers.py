"""The ui-scene and ui-fit judges on the REAL lockers kiosk (U06 fix-up): the 23 frames of business-apps
`apps/lockers/lkapp/uimodel/tests/screens.out` (commit f1274bf, copied to gate/tests/data/ui_judge/ with its sha256)
judged with the lockers contract. The exact findings of every frame are asserted, each classified in docs/ui-judges.md
("The real kiosk"): true product defects, consequences of pending contract values, and no false positive."""

import datetime
import hashlib
import unittest
from pathlib import Path
from types import SimpleNamespace

from rigor_lib import ui_contract
from rigor_lib.ui_explore_grammar import FRAME_FIELDS, parse_record, parse_typed_line
from rigor_lib.ui_explore_judges import PathSoFar
from rigor_lib.ui_explore_run import Step
from rigor_lib.ui_judge_findings import JudgeSet

HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "ui_judge"
LOCKERS = HERE.parent.parent / "products" / "business-apps" / "ui" / "lockers.toml"
OPEN = "open 1000 112"


def frames():
    """(frame lines, semantic lines) of every session of the transcript, in order."""
    lines = (DATA / "lockers-screens.out").read_text(encoding="ascii").split("\n")
    out, i = [], 0
    while i < len(lines):
        if lines[i].startswith("ok frame lines "):
            n = int(lines[i].split()[-1])
            frame, i = lines[i + 1:i + 1 + n], i + n + 1
            assert lines[i].startswith("ok semantic lines "), lines[i]
            m = int(lines[i].split()[-1])
            out.append((frame, lines[i + 1:i + 1 + m]))
            i += m
        i += 1
    return out


def subject(f):
    """What a finding is about, in the terms of docs/ui-judges.md: a scene key, a pair, a layer and a key, a contract
    entry, or a rendered label's name."""
    o = f["observed"]
    if f["check"] == "contract-pending":
        return "%s %s" % (o["check"], o["entry"])
    if f["check"] == "contract-incomplete":
        return o["name"]
    if "node" in o:
        return o["node"]["target"]
    if "label" in o:
        return o["label"]["target"]
    if "layer" in o and "key" in o:
        return "%s/%s" % (o["layer"], o["key"])
    if "keys" in o:
        return "/".join(o["keys"])
    return o.get("key", o.get("role", o.get("group")))


def judge_all():
    """{frame number: {(check, subject, part, severity)}} and the run-level findings."""
    contract = ui_contract.load(LOCKERS)
    judges = JudgeSet(["ui-scene", "ui-fit"], contract, SimpleNamespace(fields=("role",)), datetime.date(2026, 11, 16))
    per = {}
    for number, (frame, semantic) in enumerate(frames(), 1):
        step = Step(1, "frame-%d" % number)
        step.obs = {"semantic": tuple(parse_record("semantic", l) for l in semantic),
                    "frame": tuple(parse_typed_line(FRAME_FIELDS, l) for l in frame),
                    "patches": (), "trace": (), "due": None, "env": ()}
        step.key = hashlib.sha256(b"frame-%d" % number).hexdigest()
        step.proj, step.origin = {"nodes": [], "facts": {}}, 1000
        per[number] = {(f["check"], subject(f), f["observed"].get("part", f["observed"].get("what", "-")),
                        f["severity"])
                       for f in judges.step_judge(step, PathSoFar([Step(0, OPEN)], 1), None)}
    return per, judges.finish(OPEN)



# The expected findings, each classified in docs/ui-judges.md ("The real kiosk"), with the check that owns each cause:
# - occluded-target, part layer-unreachable, on the banner scrims 296, 280, 264, 272, 288 (occluded-target owns it):
#   the scrim carries the dismiss intent but its card has the same rectangle, so no tap reaches it; TRUE DEFECT (the
#   known one of the persistent banners' tap-outside)
# - frames 13, 14, overlay-policy captures, basis rendered, 320/11, 320/12, 320/16 (overlay-policy owns it, occluded-
#   target does not repeat it): the sealed snackbar row does not block input below, but the rendered full-window scrim
#   is clickable over BG, EN and Done; TRUE DEFECT
# - frames 17, 18, overlay-policy captures, basis rendered, 288/11 and 288/12: the fourth stacked banner's clickable
#   scrim lies over the BG/EN switch; TRUE DEFECT
# - frames 13, 14, stage-unmatched 321, 323 (error), 322, 326 (info), the three unowned labels (info) and
#   stage-unowned-target for the drawn card and Dismiss (error): the snackbar is drawn at 128,626-1151,791, not at the
#   scene's 360,476 560x300 (the stage findings own it); TRUE DEFECT
# - frame 19, text-clipped and text-overflow (height) on 8: the Bulgarian licences line; TRUE DEFECT (X2)
# - frame 22, stage-text-mismatch on 5: the storage-fault detail drawn as "?40"; TRUE DEFECT
# - contract-incomplete role-wrap (key_label, muted_caption, screen_headline, staff_strong, large_countdown): the spec
#   decides wrapping per node and the contract has no element row for those nodes; a CONTRACT GAP for the owner
# - every contract-pending: a consequence of pending values (q9 the panel, q7 the importance table)
# frame -> the findings that are not contract-pending: (check, subject, part, severity)
FINDINGS = {
    1: {('contract-incomplete', 'key_label', 'role-wrap', 'error'),
        ('contract-incomplete', 'screen_headline', 'role-wrap', 'error'),
        ('occluded-target', '296', 'layer-unreachable', 'error')},
    2: {('contract-incomplete', 'key_label', 'role-wrap', 'error'),
        ('contract-incomplete', 'screen_headline', 'role-wrap', 'error'),
        ('occluded-target', '296', 'layer-unreachable', 'error')},
    3: {('contract-incomplete', 'key_label', 'role-wrap', 'error'),
        ('contract-incomplete', 'screen_headline', 'role-wrap', 'error'),
        ('occluded-target', '296', 'layer-unreachable', 'error')},
    4: {('contract-incomplete', 'key_label', 'role-wrap', 'error'),
        ('contract-incomplete', 'screen_headline', 'role-wrap', 'error'),
        ('occluded-target', '296', 'layer-unreachable', 'error')},
    5: {('contract-incomplete', 'key_label', 'role-wrap', 'error'),
        ('contract-incomplete', 'screen_headline', 'role-wrap', 'error')},
    6: {('contract-incomplete', 'key_label', 'role-wrap', 'error'),
        ('contract-incomplete', 'screen_headline', 'role-wrap', 'error')},
    7: {('contract-incomplete', 'muted_caption', 'role-wrap', 'error'),
        ('contract-incomplete', 'screen_headline', 'role-wrap', 'error')},
    8: {('contract-incomplete', 'muted_caption', 'role-wrap', 'error'),
        ('contract-incomplete', 'screen_headline', 'role-wrap', 'error')},
    9: {('contract-incomplete', 'muted_caption', 'role-wrap', 'error')},
    10: {('contract-incomplete', 'muted_caption', 'role-wrap', 'error')},
    11: {('contract-incomplete', 'key_label', 'role-wrap', 'error'),
        ('contract-incomplete', 'screen_headline', 'role-wrap', 'error')},
    12: {('contract-incomplete', 'key_label', 'role-wrap', 'error'),
        ('contract-incomplete', 'screen_headline', 'role-wrap', 'error')},
    13: {('contract-incomplete', 'key_label', 'role-wrap', 'error'),
        ('contract-incomplete', 'muted_caption', 'role-wrap', 'error'),
        ('overlay-policy', '320/11', 'captures', 'error'),
        ('overlay-policy', '320/12', 'captures', 'error'),
        ('overlay-policy', '320/16', 'captures', 'error'),
        ('stage-unmatched', '321', '-', 'error'),
        ('stage-unmatched', '322', '-', 'info'),
        ('stage-unmatched', '323', '-', 'error'),
        ('stage-unmatched', '326', '-', 'info'),
        ('stage-unmatched', 'node/lv_label/152/650/1127/685/1e5810d5', '-', 'info'),
        ('stage-unmatched', 'node/lv_label/573/694/705/729/1ef1a425', '-', 'info'),
        ('stage-unmatched', 'node/lv_label/621/750/657/767/e4599adb', '-', 'info'),
        ('stage-unowned-target', 'node/lv_button/549/694/729/741', '-', 'error'),
        ('stage-unowned-target', 'node/lv_obj/128/626/1151/791', '-', 'error')},
    14: {('contract-incomplete', 'key_label', 'role-wrap', 'error'),
        ('contract-incomplete', 'muted_caption', 'role-wrap', 'error'),
        ('overlay-policy', '320/11', 'captures', 'error'),
        ('overlay-policy', '320/12', 'captures', 'error'),
        ('overlay-policy', '320/16', 'captures', 'error'),
        ('stage-unmatched', '321', '-', 'error'),
        ('stage-unmatched', '322', '-', 'info'),
        ('stage-unmatched', '323', '-', 'error'),
        ('stage-unmatched', '326', '-', 'info'),
        ('stage-unmatched', 'node/lv_label/152/650/1127/685/09ca1220', '-', 'info'),
        ('stage-unmatched', 'node/lv_label/578/694/700/729/48845bff', '-', 'info'),
        ('stage-unmatched', 'node/lv_label/629/750/649/767/fdff4548', '-', 'info'),
        ('stage-unowned-target', 'node/lv_button/554/694/724/741', '-', 'error'),
        ('stage-unowned-target', 'node/lv_obj/128/626/1151/791', '-', 'error')},
    15: {('contract-incomplete', 'key_label', 'role-wrap', 'error'),
        ('contract-incomplete', 'screen_headline', 'role-wrap', 'error'),
        ('occluded-target', '280', 'layer-unreachable', 'error'),
        ('occluded-target', '296', 'layer-unreachable', 'error')},
    16: {('contract-incomplete', 'key_label', 'role-wrap', 'error'),
        ('contract-incomplete', 'screen_headline', 'role-wrap', 'error'),
        ('occluded-target', '280', 'layer-unreachable', 'error'),
        ('occluded-target', '296', 'layer-unreachable', 'error')},
    17: {('contract-incomplete', 'key_label', 'role-wrap', 'error'),
        ('contract-incomplete', 'screen_headline', 'role-wrap', 'error'),
        ('occluded-target', '264', 'layer-unreachable', 'error'),
        ('occluded-target', '272', 'layer-unreachable', 'error'),
        ('occluded-target', '288', 'layer-unreachable', 'error'),
        ('occluded-target', '296', 'layer-unreachable', 'error'),
        ('overlay-policy', '288/11', 'captures', 'error'),
        ('overlay-policy', '288/12', 'captures', 'error')},
    18: {('contract-incomplete', 'key_label', 'role-wrap', 'error'),
        ('contract-incomplete', 'screen_headline', 'role-wrap', 'error'),
        ('occluded-target', '264', 'layer-unreachable', 'error'),
        ('occluded-target', '272', 'layer-unreachable', 'error'),
        ('occluded-target', '288', 'layer-unreachable', 'error'),
        ('occluded-target', '296', 'layer-unreachable', 'error'),
        ('overlay-policy', '288/11', 'captures', 'error'),
        ('overlay-policy', '288/12', 'captures', 'error')},
    19: {('contract-incomplete', 'muted_caption', 'role-wrap', 'error'),
        ('contract-incomplete', 'staff_strong', 'role-wrap', 'error'),
        ('text-clipped', '8', '-', 'error'),
        ('text-overflow', '8', 'height', 'error')},
    20: {('contract-incomplete', 'muted_caption', 'role-wrap', 'error'),
        ('contract-incomplete', 'staff_strong', 'role-wrap', 'error')},
    21: {('contract-incomplete', 'screen_headline', 'role-wrap', 'error')},
    22: {('contract-incomplete', 'screen_headline', 'role-wrap', 'error'),
        ('stage-text-mismatch', '5', '-', 'error')},
    23: {('contract-incomplete', 'large_countdown', 'role-wrap', 'error'),
        ('contract-incomplete', 'screen_headline', 'role-wrap', 'error')},
}
PENDING = {
    (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23): ('hierarchy-violated table:importance', 'occluded-target panel.diagonal_in', 'overlay-policy panel.diagonal_in', 'target-spacing panel.diagonal_in', 'touch-target-small panel.diagonal_in'),
}


EXAMINED = {
    "ui-scene": {"occluded-target": 172, "overlay-policy": 26, "touch-target-small": 238, "target-spacing": 154,
                 "node-out-of-bounds": 466, "text-overlap": 351, "font-below-min": 357, "hierarchy-violated": 357,
                 "raw-text": 137, "wrap-policy-undeclared": 299, "toggle-group-indistinct": 36},
    "ui-fit": {"text-overflow": 294, "text-clipped": 357, "full-string-shown": 357, "fit-unmeasurable": 357,
               "glyph-missing": 357, "font-shrunk": 350},
}


class LockersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.per, cls.end = judge_all()

    def test_the_copy_is_the_recorded_one(self):
        for line in (DATA / "SHA256SUMS").read_text().splitlines():
            digest, name = line.split("  ")
            self.assertEqual(hashlib.sha256((DATA / name).read_bytes()).hexdigest(), digest, name)

    def test_23_frames_and_no_scene_vocabulary(self):
        self.assertEqual(len(self.per), 23)
        self.assertEqual([x for found in self.per.values() for x in found if x[0] == "scene-vocabulary"], [])

    def test_the_exact_findings_of_every_frame_with_their_part(self):
        pending = {n: set(p) for frames, p in PENDING.items() for n in frames}
        self.assertEqual(sorted(pending), list(range(1, 24)))
        for number, found in sorted(self.per.items()):
            self.assertEqual({x for x in found if x[0] != "contract-pending"}, FINDINGS.get(number, set()), number)
            self.assertEqual({x[1] for x in found if x[0] == "contract-pending"}, pending[number], number)
            self.assertEqual({x[3] for x in found if x[0] == "contract-pending"} - {"error"}, set())

    def test_every_check_reached_verdicts_on_real_nodes_and_none_is_vacuous(self):
        examined = {f["gate"]: f["observed"]["totals"] for f in self.end if f["check"] == "checks-examined"}
        self.assertEqual(examined, EXAMINED)
        self.assertEqual([f for f in self.end if f["check"] == "check-vacuous"], [])

    def test_the_correct_rejection_dialog_has_no_occlusion_or_overlay_finding(self):
        # frames 5, 6, 11, 12: the dialog's dimmed, clickable full-window scrim makes the background inert (R7)
        for number in (5, 6, 11, 12):
            self.assertEqual({x for x in self.per[number] if x[0] in ("occluded-target", "overlay-policy")}, set())


if __name__ == "__main__":
    unittest.main()
