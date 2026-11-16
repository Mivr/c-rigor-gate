"""The kiosk's screen-class paths (U09): `products/business-apps/ui/lockers.classes.paths.json`, a DRAFT copied byte
for byte from the product's adapter task (its note `lockers.classes.paths.md`), parses as `ui-explore-paths/1` and every
word is a path word or a word of the draft catalogue `lockers.events.toml`. It does not run the probe."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from rigor_lib import ui_explore_catalogue
from rigor_lib.ui_explore import load_paths
from rigor_lib.ui_explore_probe import CAPABILITIES

UI = Path(__file__).resolve().parent.parent.parent / "products" / "business-apps" / "ui"
PATHS = UI / "lockers.classes.paths.json"
NOTE = UI / "lockers.classes.paths.md"
SHA256 = "b9b2a7b700d80b33d0682b4e07b6a58d9f4cea1063858686d23ec23beccdd0f1"


class LockersClassPathsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalogue = ui_explore_catalogue.load(str(UI / "lockers.events.toml"))

    def test_the_draft_is_the_copied_file(self):
        self.assertEqual(hashlib.sha256(PATHS.read_bytes()).hexdigest(), SHA256)
        note = NOTE.read_text()
        self.assertIn(SHA256, note)
        self.assertIn("DRAFT", note)
        self.assertIn("Reaching every screen class by a path", note)

    def test_parses_as_paths_and_every_word_is_known(self):
        criteria, paths = load_paths(str(PATHS), self.catalogue, CAPABILITIES)
        self.assertEqual((criteria, len(paths)), ((), 29))
        ids = {event.id for event in self.catalogue.events}
        for words in paths:
            self.assertRegex(words[0], r"^open 1000 1[0-9]{2}$")
            for word in words[1:]:
                self.assertTrue(word in ids or (word.startswith("at ") and word[3:].isdigit()), word)

    def test_a_word_outside_the_catalogue_is_refused(self):
        data = json.loads(PATHS.read_bytes())
        data["paths"][0].append("no-such-event")
        with tempfile.TemporaryDirectory() as directory:
            bad = Path(directory) / "bad.paths.json"
            bad.write_text(json.dumps(data))
            with self.assertRaisesRegex(Exception, "not a path word or a catalogue event id"):
                load_paths(str(bad), self.catalogue, CAPABILITIES)


if __name__ == "__main__":
    unittest.main()
