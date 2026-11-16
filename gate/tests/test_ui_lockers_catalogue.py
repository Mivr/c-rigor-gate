"""The lockers event catalogue (U23): `products/business-apps/ui/lockers.events.toml` loaded together with the lockers
UI contract, and the structural facts that must not rot (docs/ui-lockers-first-run.md). It does not run the probe."""

import re
import tomllib
import unittest
from pathlib import Path

from rigor_lib import ui_contract, ui_explore_catalogue
from rigor_lib.ui_explore_probe import CAPABILITIES

ROOT = Path(__file__).resolve().parent.parent.parent
UI = ROOT / "products" / "business-apps" / "ui"
CATALOGUE = UI / "lockers.events.toml"
CONTRACT = UI / "lockers.toml"
# The adapter's environment rows (business-apps docs/lockers/ui-model.md, "The environment catalogue").
ADAPTER_ENV_IDS = tuple(range(2, 16)) + tuple(range(20, 26)) + tuple(range(30, 35)) + (40, 41, 50, 51)
# The FAKE codes of the adapter's fixtures (ui-model.md "The fixture data"; row 24's revision-4 code).
FIXTURE_CODES = {"121212", "666662", "666661", "343434", "999999"}
# U05e: the pad's digit map: "0" is scene key 42, "1".."9" are 32..40, every arg 0 (ui-model.md L76, screens.out L147)
PAD_MAP = (("0", 42, 0),) + tuple((str(d), 31 + d, 0) for d in range(1, 10))


def wedge_text(hex_text):
    return bytes.fromhex(hex_text).decode("ascii")


class LockersCatalogueTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = CATALOGUE.read_bytes()
        cls.raw = tomllib.loads(cls.data.decode("utf-8"))
        cls.cat = ui_explore_catalogue.load(str(CATALOGUE))
        cls.contract = ui_contract.load(str(CONTRACT))

    def events(self, cls):
        return [event for event in self.cat.events if event.cls == cls]

    def test_schema_and_draft_header(self):
        self.assertEqual(self.raw["schema"], "ui-events/1")
        self.assertEqual((self.cat.product, self.cat.app), ("business-apps", "lockers"))
        self.assertEqual(self.contract.product, "business-apps/lockers")
        self.assertIn("DRAFT by the U23 agent, unsigned, for the owner's review", self.data.decode("utf-8"))

    def test_requires_every_capability(self):
        # the seven capabilities the kiosk's probe announces; `identity` (U24) joins when its adapter reports it
        seven = ("frame-facts", "ink", "hit-test", "tap", "apply-missed", "crop", "pointer")
        self.assertEqual(self.cat.requires, seven)
        self.assertEqual(CAPABILITIES, seven + ("identity",))

    def test_drain_and_longest_timer(self):
        self.assertLessEqual(self.cat.drain_ms, 60000)
        lifetimes = [row["lifetime_ms"] for row in self.contract.tables["timer"]]
        self.assertGreaterEqual(self.cat.max_wait_ms, max(lifetimes))
        advances = [event.get("ms") for event in self.events("t1") if event.get("kind") == "advance"]
        for lifetime in lifetimes:
            if lifetime:
                self.assertTrue(any(ms >= lifetime for ms in advances), lifetime)
        kinds = {event.get("kind") for event in self.events("t1")}
        self.assertLessEqual({"fire-due", "before-due", "until-change"}, kinds)

    def test_ambient_declaration(self):
        self.assertEqual(self.cat.ambient, ("touch",))
        self.assertEqual(self.cat.countdown_role, "countdown")
        self.assertIsNone(self.cat.due_restart_ms)
        ambient = self.raw["ambient"]
        self.assertNotIn("due_restart_ms", ambient)
        self.assertNotIn("due_restart_provenance", ambient)

    def test_every_adapter_env_row_once(self):
        envs = [event.get("env") for event in self.events("e1")]
        self.assertEqual(sorted(envs), sorted(ADAPTER_ENV_IDS))
        self.assertEqual(len(envs), len(set(envs)))
        for event in self.events("e1"):
            self.assertEqual((event.get("arg"), event.get("hex"), event.get("expect")), (0, "", "accept"))

    def test_key_leaves_out_countdown_values_and_times(self):
        self.assertNotIn("label", self.cat.key.fields)
        self.assertEqual(self.cat.key.ignore, ())
        for fact in self.cat.key.derived:
            self.assertNotEqual(fact.role, "countdown", fact.name)
            if fact.op == "select" and fact.field == "label":
                self.assertIn(fact.role, ("button", "key"), fact.name)

    def test_only_fixture_codes(self):
        for event in self.events("u4"):
            code = wedge_text(event.get("hex")) if event.get("via") == "wedge" else event.get("digits")
            filler = set(code) <= {"0"} or set(code) <= {"1"}
            self.assertTrue(code in FIXTURE_CODES or filler or code == "12a456", (event.id, code))
            if event.get("via") == "pad":           # U05e: one scene key per digit (pad keys 42, 32..40), enter 43
                self.assertEqual((event.get("digit_map"), event.get("enter_intent")), (PAD_MAP, 43))
        # no network address of any kind (a dotted quad), so no LAN address either
        self.assertIsNone(re.search(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", self.data.decode("utf-8")))

    def test_u05e_scene_taps_boot_seeds_and_the_welcome_prefix(self):
        self.assertEqual((self.cat.taps.scope, self.cat.taps.intent_node), ("scene", "key"))
        self.assertEqual(self.cat.taps.grid_pct, tuple(self.contract.get("thresholds", "probe_grid_pct")))
        self.assertEqual([e for e in self.events("u2")], [])
        self.assertEqual(self.cat.boot_seeds, tuple(range(112, 121)))
        self.assertEqual(self.cat.prefix("welcome"), ("at 3200",))
        for name in ("taps", "boot", "prefix"):
            self.assertIn(name, self.raw)
        pads = {event.get("digits") for event in self.events("u4") if event.get("via") == "pad"}
        self.assertLessEqual({"121212", "666662", "666661"}, pads)

    def test_intents_are_scene_keys_with_arg_zero(self):
        for event in self.events("u1") + self.events("u5"):
            self.assertEqual(event.get("arg"), 0, event.id)
        self.assertEqual({e.get("intent") for e in self.events("u5")}, {11, 12})


if __name__ == "__main__":
    unittest.main()
