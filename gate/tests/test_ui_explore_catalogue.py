"""The event catalogue loader of `rigor ui-explore` (rigor_lib.ui_explore_catalogue) on the toy's catalogue and on
edited copies: every class required, a time event required, max_wait_ms capped, unknown keys, duplicate ids and names,
wrong types, an empty key, an unjustified ignore and malformed derived facts refused."""

import hashlib
import unittest

from rigor_lib import ui_explore_catalogue as cat
from rigor_lib.errors import InternalError
from tests import test_ui_explore_helpers as h

TEXT = h.TOY.read_text()
PRESS = '{ id = "tap-press", intent = 1, arg = 0, expect = "accept" },'
KEY = 'derived = []\nignore = []'


def load(text):
    return cat.loads(text.encode("utf-8"))


def with_derived(*tables):
    return TEXT.replace("derived = []", "derived = [ %s ]" % ", ".join(tables))


class CatalogueTest(unittest.TestCase):
    def test_the_toy_catalogue(self):
        catalogue = load(TEXT)
        self.assertEqual((catalogue.product, catalogue.app, catalogue.version, catalogue.max_wait_ms),
                         ("selftest", "toy", 1, 10000))
        self.assertEqual([(e.cls, e.id) for e in catalogue.events],
                         [("u1", "tap-press"), ("u4", "code-empty"), ("u4", "code-one-digit"), ("u4", "code-non-digit"),
                          ("e1", "env-offline"), ("t1", "fire-due"), ("t1", "before-due"), ("t1", "one-frame"),
                          ("t1", "idle-10s"), ("t1", "until-change"), ("t1", "at-10s")])
        self.assertEqual(catalogue.by_id("code-empty").get("expect"), "refuse")
        self.assertEqual(catalogue.by_id("at-10s").get("offset_ms"), 10000)
        self.assertIsNone(catalogue.by_id("open"))
        self.assertEqual(len(catalogue.key.fields), 13)
        self.assertEqual(catalogue.sha256, hashlib.sha256(TEXT.encode("utf-8")).hexdigest())
        for path in (h.TOY_COARSE, h.FIXTURE):
            load(path.read_text())

    def test_the_stub_catalogue_is_the_selftest_toy_catalogue_but_its_taps_and_requires(self):
        """The unit tests' stub catalogue may differ from the selftest's toy catalogue only by the two tap events and the
        capabilities the toy requires: every other key, field and event table is the same."""
        toy, stub = load(h.SELFTEST_TOY.read_text()), load(TEXT)
        taps = [(e.cls, e.id, dict(e.spec)) for e in toy.events if e.cls in ("u2", "u3")]
        self.assertEqual(taps, [("u2", "probe-press", {"x": 58, "y": 58, "target": "lv_button"}),
                                ("u3", "probe-blank", {"x": 150, "y": 10})])
        self.assertEqual([e for e in toy.events if e.cls not in ("u2", "u3")], list(stub.events))
        self.assertEqual((toy.requires, stub.requires),
                         (("frame-facts", "ink", "hit-test", "tap", "apply-missed", "crop"), ()))
        for name in ("product", "app", "version", "max_wait_ms", "drain_ms", "starve_firings", "starve_window_frames",
                     "key"):
            self.assertEqual(getattr(toy, name), getattr(stub, name), name)

    def test_a_pad_macro_and_derived_facts(self):
        text = TEXT.replace('{ id = "code-empty", boundary = "empty", via = "wedge", hex = "", expect = "refuse" },',
                            '{ id = "pad-max", boundary = "max", via = "pad", digits = "123", digit_intent = 10, '
                            'enter_intent = 11, expect = "accept" },')
        text = text.replace("derived = []", 'derived = [ { name = "pad-len", op = "bucket", node = "pad", '
                            'field = "label", measure = "length", boundaries = [1, 63, 64] }, '
                            '{ name = "due", op = "bucket", model = "due-in-ms", boundaries = [17] }, '
                            '{ name = "buttons", op = "count", role = "button" } ]')
        catalogue = load(text)
        self.assertEqual(catalogue.by_id("pad-max").get("digits"), "123")
        self.assertEqual([(d.name, d.op, d.node, d.role, d.model, d.boundaries) for d in catalogue.key.derived],
                         [("pad-len", "bucket", "pad", None, None, (1, 63, 64)),
                          ("due", "bucket", None, None, "due-in-ms", (17,)),
                          ("buttons", "count", None, "button", None, ())])

    def assert_refused(self, text, why):
        self.assertNotEqual(text, TEXT, why)
        with self.assertRaises(InternalError) as caught:
            load(text)
        self.assertIn(why, str(caught.exception))

    def test_refusals(self):
        cases = [
            (TEXT.replace("[u5]\nevents = []\n", ""), "missing key(s) u5"),
            (TEXT.replace("[u5]\nevents = []\n", "[u5]\n"), "u5: missing key(s) events"),
            (TEXT.replace('version = 1', 'version = 1\nsealed = true'), "unknown key(s) sealed"),
            (TEXT.replace("max_wait_ms = 10000\n", ""), "missing key(s) max_wait_ms"),
            (TEXT.replace("max_wait_ms = 10000", "max_wait_ms = 3600001"), "max_wait_ms: must be an integer"),
            (TEXT.replace("ms = 10000 }", "ms = 10001 }"), "ms: must be an integer in 1..10000"),
            (TEXT.replace("drain_ms = 1024\n", ""), "missing key(s) drain_ms"),
            (TEXT.replace("drain_ms = 1024", "drain_ms = 1000"), "drain_ms: must be a whole number of frames"),
            (TEXT.replace("drain_ms = 1024", "drain_ms = 60016"), "drain_ms: must be an integer in 16..60000"),
            (TEXT.replace("drain_ms = 1024", "drain_ms = 1024\nstarvation = { firings = 5, window_frames = 4 }"),
             "starvation: missing key(s) provenance"),
            (TEXT.replace("drain_ms = 1024", 'drain_ms = 1024\nstarvation = { firings = 1, window_frames = 4, '
                          'provenance = "owner:D1" }'), "starvation.firings: must be an integer"),
            (TEXT.replace('expect = "accept"', 'expect = "refuse"'), "needs at least one input event with expect"),
            (TEXT[:TEXT.index("[u1]")] + "[u1]\nevents = []\n[u2]\nevents = []\n[u3]\nevents = []\n[u4]\nevents = []\n"
             "[u5]\nevents = []\n[e1]\nevents = []\n" + TEXT[TEXT.index("[t1]"):], "needs at least one input event"),
            (TEXT.replace(PRESS, PRESS + "\n" + PRESS), "duplicate event id 'tap-press'"),
            (TEXT.replace(PRESS, PRESS.replace(', expect = "accept"', "")), "missing key(s) expect"),
            (TEXT.replace(PRESS, PRESS.replace('"accept"', '"maybe"')), "expect: must be one of"),
            (TEXT.replace(PRESS, PRESS.replace("intent = 1", "intent = true")), "intent: must be an integer"),
            (TEXT.replace(PRESS, PRESS.replace("tap-press", "wait-change")), "reserved path word"),
            (TEXT.replace('hex = "37"', 'hex = "3700"'), "a NUL byte cannot be sent"),
            (TEXT.replace('boundary = "one-digit"', 'boundary = "two-digit"'), "boundary: must be one of"),
            (TEXT.replace('kind = "before-due"', 'kind = "later"'), "kind: must be one of"),
            (TEXT.replace('{ id = "fire-due", kind = "fire-due" }', '{ id = "fire-due", kind = "fire-due", ms = 1 }'),
             "unknown key(s) ms"),
            (TEXT[:TEXT.index("[t1]")] + "[t1]\nevents = []\n", "needs at least one time event"),
            (TEXT.replace('schema = "ui-events/1"', 'schema = "ui-events/2"'), "schema: must be"),
            (TEXT.replace('facts = ["deadline", "env-inputs"]', 'facts = ["deadline", "clock"]'), "unknown name(s) clock"),
            (TEXT.replace("derived = []\n", ""), "key: missing key(s) derived"),
            (TEXT.replace('fields = ["role",', 'fields = ["key", "role",'), "unknown name(s) key"),
            (TEXT.replace("version = 1", "version = 1\nversion = 2"), "not valid UTF-8 TOML"),
        ]
        empty = TEXT[:TEXT.index("fields = [")] + 'fields = []\nfacts = []\n' + TEXT[TEXT.index("derived = []"):]
        cases.append((empty, "keys every state alike"))
        ignore = '{ field = "x", provenance = "spec:ui-look.md#4.2", reason = "geometry follows the label" }'
        cases += [(TEXT.replace("ignore = []", "ignore = [ %s ]" % ignore), "both in the key and ignored: x"),
                  (TEXT.replace('"x", "y", ', '"y", ').replace("ignore = []", "ignore = [ %s ]"
                                                                % ignore.replace("spec:ui-look.md#4.2", "because")),
                   "provenance 'because'"),
                  (TEXT.replace('"x", "y", ', '"y", ').replace("ignore = []", "ignore = [ %s ]"
                                                                % ignore.replace(', reason = "geometry follows the label"', "")),
                   "missing key(s) reason"),
                  (with_derived('{ name = "a", op = "count" }'), "needs exactly one of node and role"),
                  (with_derived('{ name = "a", op = "count", node = "n", role = "r" }'), "needs exactly one"),
                  (with_derived('{ name = "a", op = "select", node = "n" }'), "missing key(s) field"),
                  (with_derived('{ name = "a", op = "sum", node = "n" }'), "op: must be one of"),
                  (with_derived('{ name = "deadline", op = "count", node = "n" }'), "duplicate fact name 'deadline'"),
                  (with_derived('{ name = "a", op = "bucket", node = "n", field = "label", measure = "value", '
                                'boundaries = [2, 1] }'), "strictly increasing"),
                  (with_derived('{ name = "a", op = "bucket", model = "clock", boundaries = [1] }'), "model: must be"),
                  (with_derived('{ name = "a", op = "presence", node = "n", expr = "1+1" }'), "unknown key(s) expr"),
                  (with_derived('{ name = "a", op = "presence", node = "n\\\\q" }'), "escaped spelling"),
                  (with_derived('{ name = "a", op = "presence", node = "n\\\\x41" }'), "escaped spelling"),
                  (with_derived('{ name = "a", op = "presence", node = "\u00e9" }'), "escaped spelling")]
        for text, why in cases:
            self.assert_refused(text, why)
        escaped = load(with_derived('{ name = "a", op = "presence", node = "n\\\\x01\\\\t" }')).key.derived[0]
        self.assertEqual(escaped.node, "n\\x01\\t")
        ok = TEXT.replace('"x", "y", ', '"y", ').replace("ignore = []", "ignore = [ %s ]" % ignore)
        self.assertEqual(load(ok).key.ignore, (("x", "spec:ui-look.md#4.2", "geometry follows the label"),))
        with self.assertRaises(InternalError):
            cat.loads(b"\xff")
        with self.assertRaises(InternalError):
            cat.load("/nonexistent/catalogue.toml")
        with self.assertRaises(InternalError):
            cat.loads(b"x = " + b"[" * 100000 + b"]" * 100000)
