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
    if "label" in o:
        return o["label"]["target"]
    if "layer" in o and "key" in o:
        return "%s/%s" % (o["layer"], o["key"])
    if "keys" in o:
        return "/".join(o["keys"])
    return o.get("key", o.get("role", o.get("group")))


def judge_all():
    """{frame number: {(check, subject, severity)}} and the run-level findings."""
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
        per[number] = {(f["check"], subject(f), f["severity"])
                       for f in judges.step_judge(step, PathSoFar([Step(0, OPEN)], 1), None)}
    return per, judges.finish(OPEN)


# The expected findings, each classified in docs/ui-judges.md ("The real kiosk"):
# - occluded-target on a scrim (296, 280, 264, 272, 288; part layer-unreachable): a persistent banner's scrim carries the
#   dismiss intent but its card has the same rectangle, so no tap reaches it (the known defect of the banner set's
#   tap-outside, business-apps docs/lockers/ui-model.md); a TRUE DEFECT
# - frames 17, 18, occluded-target on 11 and 12: the fourth stacked banner covers the BG/EN switch; a TRUE DEFECT
# - frames 13, 14: the snackbar's full-window dismissing scrim (capture-and-dismiss) takes the first tap on BG, EN and
#   Done (occluded-target and overlay-policy, the F3b class); TRUE by P004's rule, a spec decision to make (ui-rules.md
#   wants tap-outside dismissal; P004 wants the covered controls declared inert)
# - frames 13, 14, stage-unmatched: the snackbar's card and parts are drawn at 128,626-1151,791, not at the scene's
#   360,476 560x300 (notice parts ignore the scene's rect, P004 F3b root cause); a TRUE DEFECT (the unowned labels are
#   the same parts seen from the rendered side, info)
# - frame 19, text-clipped and text-overflow on 8: the Bulgarian licences line needs 2 lines of 18 px in a 20 px row;
#   the known TRUE DEFECT (X2)
# - frame 22, stage-text-mismatch on 5: the fault screen's staff detail is drawn as "?40" instead of the scene's
#   sentence; a TRUE DEFECT
# - every contract-pending: a consequence of a pending value of the lockers contract (q9 the panel, q7 importance,
#   wrap scopes per role, the banner's layer policy)
# frame -> the findings that are not contract-pending: (check, subject, severity)
FINDINGS = {
    1: {('occluded-target', '296', 'error')},
    2: {('occluded-target', '296', 'error')},
    3: {('occluded-target', '296', 'error')},
    4: {('occluded-target', '296', 'error')},
    13: {('occluded-target', '11', 'error'),
        ('occluded-target', '12', 'error'),
        ('occluded-target', '16', 'error'),
        ('overlay-policy', '320/11', 'error'),
        ('overlay-policy', '320/12', 'error'),
        ('overlay-policy', '320/16', 'error'),
        ('stage-unmatched', '321', 'error'),
        ('stage-unmatched', '322', 'info'),
        ('stage-unmatched', '323', 'error'),
        ('stage-unmatched', '326', 'info'),
        ('stage-unmatched', 'node/lv_label/152/650/1127/685/1e5810d5', 'info'),
        ('stage-unmatched', 'node/lv_label/573/694/705/729/1ef1a425', 'info'),
        ('stage-unmatched', 'node/lv_label/621/750/657/767/e4599adb', 'info')},
    14: {('occluded-target', '11', 'error'),
        ('occluded-target', '12', 'error'),
        ('occluded-target', '16', 'error'),
        ('overlay-policy', '320/11', 'error'),
        ('overlay-policy', '320/12', 'error'),
        ('overlay-policy', '320/16', 'error'),
        ('stage-unmatched', '321', 'error'),
        ('stage-unmatched', '322', 'info'),
        ('stage-unmatched', '323', 'error'),
        ('stage-unmatched', '326', 'info'),
        ('stage-unmatched', 'node/lv_label/152/650/1127/685/09ca1220', 'info'),
        ('stage-unmatched', 'node/lv_label/578/694/700/729/48845bff', 'info'),
        ('stage-unmatched', 'node/lv_label/629/750/649/767/fdff4548', 'info')},
    15: {('occluded-target', '280', 'error'),
        ('occluded-target', '296', 'error')},
    16: {('occluded-target', '280', 'error'),
        ('occluded-target', '296', 'error')},
    17: {('occluded-target', '11', 'error'),
        ('occluded-target', '12', 'error'),
        ('occluded-target', '264', 'error'),
        ('occluded-target', '272', 'error'),
        ('occluded-target', '288', 'error'),
        ('occluded-target', '296', 'error')},
    18: {('occluded-target', '11', 'error'),
        ('occluded-target', '12', 'error'),
        ('occluded-target', '264', 'error'),
        ('occluded-target', '272', 'error'),
        ('occluded-target', '288', 'error'),
        ('occluded-target', '296', 'error')},
    19: {('text-clipped', '8', 'error'),
        ('text-overflow', '8', 'error')},
    22: {('stage-text-mismatch', '5', 'error')},
}
# frame -> the contract-pending findings: '<check> <entry>' (all errors)
PENDING = {
    (1, 2, 3, 4, 5, 6, 11, 12, 15, 16, 17, 18): ('hierarchy-violated table:importance', 'occluded-target panel.diagonal_in', 'overlay-policy layer.banner-scrim', 'overlay-policy panel.diagonal_in', 'target-spacing panel.diagonal_in', 'text-overflow role_wrap.key_label', 'text-overflow role_wrap.screen_headline', 'text-overflow role_wrap.small_button_label', 'touch-target-small panel.diagonal_in', 'wrap-policy-undeclared role_wrap.key_label', 'wrap-policy-undeclared role_wrap.screen_headline', 'wrap-policy-undeclared role_wrap.small_button_label'),
    (7, 8): ('hierarchy-violated table:importance', 'occluded-target panel.diagonal_in', 'overlay-policy panel.diagonal_in', 'target-spacing panel.diagonal_in', 'text-overflow role_wrap.key_label', 'text-overflow role_wrap.screen_headline', 'text-overflow role_wrap.small_button_label', 'touch-target-small panel.diagonal_in', 'wrap-policy-undeclared role_wrap.key_label', 'wrap-policy-undeclared role_wrap.screen_headline', 'wrap-policy-undeclared role_wrap.small_button_label'),
    (9, 10, 13, 14): ('hierarchy-violated table:importance', 'occluded-target panel.diagonal_in', 'overlay-policy panel.diagonal_in', 'target-spacing panel.diagonal_in', 'text-overflow role_wrap.key_label', 'text-overflow role_wrap.small_button_label', 'touch-target-small panel.diagonal_in', 'wrap-policy-undeclared role_wrap.key_label', 'wrap-policy-undeclared role_wrap.small_button_label'),
    (19, 20): ('hierarchy-violated table:importance', 'occluded-target panel.diagonal_in', 'overlay-policy panel.diagonal_in', 'target-spacing panel.diagonal_in', 'text-overflow role_wrap.small_button_label', 'text-overflow role_wrap.staff_strong', 'touch-target-small panel.diagonal_in', 'wrap-policy-undeclared role_wrap.small_button_label', 'wrap-policy-undeclared role_wrap.staff_strong'),
    (21, 22, 23): ('hierarchy-violated table:importance', 'occluded-target panel.diagonal_in', 'overlay-policy panel.diagonal_in', 'target-spacing panel.diagonal_in', 'text-overflow role_wrap.screen_headline', 'touch-target-small panel.diagonal_in', 'wrap-policy-undeclared role_wrap.screen_headline'),
}

EXAMINED = {
    "ui-scene": {"occluded-target": 172, "overlay-policy": 26, "touch-target-small": 238, "target-spacing": 154,
                 "node-out-of-bounds": 466, "text-overlap": 351, "font-below-min": 357, "hierarchy-violated": 357,
                 "raw-text": 137, "wrap-policy-undeclared": 357, "toggle-group-indistinct": 36},
    "ui-fit": {"text-overflow": 109, "text-clipped": 357, "full-string-shown": 357, "fit-unmeasurable": 357,
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

    def test_the_exact_findings_of_every_frame(self):
        pending = {n: set(p) for frames, p in PENDING.items() for n in frames}
        self.assertEqual(sorted(pending), list(range(1, 24)))
        for number, found in sorted(self.per.items()):
            self.assertEqual({x for x in found if x[0] != "contract-pending"}, FINDINGS.get(number, set()), number)
            self.assertEqual({x[1] for x in found if x[0] == "contract-pending"}, pending[number], number)
            self.assertEqual({x[2] for x in found if x[0] == "contract-pending"} - {"error"}, set())

    def test_every_check_examined_real_nodes_and_none_is_vacuous(self):
        examined = {f["gate"]: f["observed"]["totals"] for f in self.end if f["check"] == "checks-examined"}
        self.assertEqual(examined, EXAMINED)
        self.assertEqual([f for f in self.end if f["check"] == "check-vacuous"], [])

    def test_the_correct_rejection_dialog_has_no_occlusion_or_overlay_finding(self):
        # frames 5 and 6: the welcome screen, its banner and the rejection dialog over an inert full-window panel (R5)
        for number in (5, 6):
            self.assertEqual({x for x in self.per[number] if x[0] in ("occluded-target", "overlay-policy")}, set())


if __name__ == "__main__":
    unittest.main()
