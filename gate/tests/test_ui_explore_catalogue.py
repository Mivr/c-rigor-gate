"""The event catalogue loader of `rigor ui-explore` (rigor_lib.ui_explore_catalogue) on the toy's catalogue and on
edited copies: every class required, unknown keys, duplicate ids and wrong types refused."""

import unittest

from rigor_lib import ui_explore_catalogue as cat
from rigor_lib.errors import InternalError
from tests import test_ui_explore_helpers as h

TEXT = h.TOY.read_text()


def load(text):
    return cat.loads(text.encode("utf-8"))


class CatalogueTest(unittest.TestCase):
    def test_the_toy_catalogue(self):
        catalogue = load(TEXT)
        self.assertEqual((catalogue.product, catalogue.app, catalogue.version), ("selftest", "toy", 1))
        self.assertEqual([(e.cls, e.id) for e in catalogue.events],
                         [("u1", "tap-press"), ("u4", "code-empty"), ("u4", "code-one-digit"), ("u4", "code-non-digit"),
                          ("e1", "env-offline"), ("t1", "fire-due"), ("t1", "before-due"), ("t1", "one-frame"),
                          ("t1", "idle-5min")])
        self.assertEqual(catalogue.by_id("code-non-digit").get("hex"), "41ff")
        self.assertEqual(catalogue.by_id("idle-5min").get("ms"), 300000)
        self.assertEqual(catalogue.key.facts, ("deadline", "env-inputs"))
        self.assertEqual(len(catalogue.key.fields), 13)
        self.assertEqual(load(h.TOY_COARSE.read_text()).key.fields,
                         ("role", "enabled", "intent", "flags", "style", "importance", "input_policy", "wrap_policy"))

    def test_a_pad_macro(self):
        text = TEXT.replace('{ id = "code-empty", boundary = "empty", via = "wedge", hex = "" },',
                            '{ id = "pad-max", boundary = "max", via = "pad", digits = "123", digit_intent = 10, '
                            'enter_intent = 11 },')
        event = load(text).by_id("pad-max")
        self.assertEqual((event.get("digits"), event.get("digit_intent"), event.get("enter_intent")), ("123", 10, 11))

    def assert_refused(self, text, why):
        with self.assertRaises(InternalError) as caught:
            load(text)
        self.assertIn(why, str(caught.exception))

    def test_refusals(self):
        press = '{ id = "tap-press", intent = 1, arg = 0 },'
        cases = [
            (TEXT.replace("[u5]\nevents = []\n", ""), "missing key(s) u5"),
            (TEXT.replace("[u5]\nevents = []\n", "[u5]\n"), "u5: missing key(s) events"),
            (TEXT.replace('version = 1', 'version = 1\nsealed = true'), "unknown key(s) sealed"),
            (TEXT.replace(press, press + "\n" + press), "duplicate event id 'tap-press'"),
            (TEXT.replace(press, press + '\n{ id = "fire-due", intent = 2, arg = 0 },'), "duplicate event id 'fire-due'"),
            (TEXT.replace(press, '{ id = "tap-press", intent = 1, arg = 0, extra = 1 },'), "unknown key(s) extra"),
            (TEXT.replace(press, '{ id = "tap-press", intent = 1 },'), "missing key(s) arg"),
            (TEXT.replace(press, '{ id = "tap-press", intent = true, arg = 0 },'), "intent: must be an integer"),
            (TEXT.replace(press, '{ id = "tap-press", intent = -1, arg = 0 },'), "intent: must be an integer"),
            (TEXT.replace(press, '{ id = "settle", intent = 1, arg = 0 },'), "reserved path word"),
            (TEXT.replace(press, '{ id = "Tap", intent = 1, arg = 0 },'), "must be a string matching"),
            (TEXT.replace('hex = "37"', 'hex = "3"'), "hex: must be a string matching"),
            (TEXT.replace('hex = "37"', 'hex = "3700"'), "a NUL byte cannot be sent"),
            (TEXT.replace('hex = "37"', 'hex = "4A"'), "hex: must be a string matching"),
            (TEXT.replace('boundary = "one-digit"', 'boundary = "two-digit"'), "boundary: must be one of"),
            (TEXT.replace('via = "wedge", hex = "37"', 'via = "keyboard", hex = "37"'), "via: must be"),
            (TEXT.replace('kind = "advance", ms = 16', 'kind = "advance", ms = 0'), "ms: must be an integer"),
            (TEXT.replace('kind = "advance", ms = 16', 'kind = "advance", ms = 600001'), "ms: must be an integer"),
            (TEXT.replace('{ id = "fire-due", kind = "fire-due" }', '{ id = "fire-due", kind = "fire-due", ms = 1 }'),
             "unknown key(s) ms"),
            (TEXT.replace('kind = "before-due"', 'kind = "later"'), "kind: must be one of"),
            (TEXT.replace('schema = "ui-events/1"', 'schema = "ui-events/2"'), "schema: must be"),
            (TEXT.replace('facts = ["deadline", "env-inputs"]', 'facts = ["deadline", "clock"]'), "unknown name(s) clock"),
            (TEXT.replace('facts = ["deadline", "env-inputs"]', 'facts = ["deadline", "deadline"]'), "duplicate entries"),
            (TEXT.replace('ignore = []', 'ignore = ["label"]'), "both in the key and ignored: label"),
            (TEXT.replace('fields = ["role",', 'fields = ["key", "role",'), "unknown name(s) key"),
            (TEXT.replace("[u2]\nevents = []", "[u2]\nevents = {}"), "u2.events: must be a list"),
            (TEXT.replace("version = 1", "version = 1\nversion = 2"), "not valid UTF-8 TOML"),
            (TEXT.replace('env = 1, arg = 0, hex = ""', 'env = 1, arg = 2147483648, hex = ""'), "arg: must be an integer"),
        ]
        for text, why in cases:
            self.assertNotEqual(text, TEXT, why)
            self.assert_refused(text, why)
        with self.assertRaises(InternalError):
            cat.loads(b"\xff")
        with self.assertRaises(InternalError):
            cat.load("/nonexistent/catalogue.toml")

    def test_the_digest_is_of_the_file_bytes(self):
        import hashlib
        self.assertEqual(load(TEXT).sha256, hashlib.sha256(TEXT.encode("utf-8")).hexdigest())
