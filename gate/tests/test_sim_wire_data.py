"""T2G3: the data behind the wire invariants: pinned recordings, the constants file against the C header, the converter."""

import hashlib
import importlib.util
import json
import re
import tomllib

from tests.helpers import GATE_DIR, TempDirTestCase

REPO = GATE_DIR.parent
DATA = REPO / "selftest" / "sim" / "data"
IPV4 = re.compile(r"(?<![0-9])[0-9]{1,3}(\.[0-9]{1,3}){3}(?![0-9])")
SPEC = importlib.util.spec_from_file_location("fixture_to_fr", REPO / "tools" / "sim" / "fixture_to_fr.py")
conv = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(conv)


def exchange(t, dt, request, response):
    return {"t_ms": t, "dt_ms": dt, "request": request, "response": response}


READ = "01010000001ebc02"
OFF = "01010400000000fbd1"
ON = "01010400100000fa14"
FLASH = "0105020c0005cc72"


class PinnedData(TempDirTestCase):
    def test_recordings_match_the_pin(self):
        sums = dict(line.split("  ", 1)[::-1] for line in (DATA / "SHA256SUMS").read_text().splitlines())
        self.assertEqual(sorted(sums), ["real-board-2026-10-07.json", "sim-docker-2026-10-07.json"])
        for name, digest in sums.items():
            self.assertEqual(hashlib.sha256((DATA / name).read_bytes()).hexdigest(), digest, name)

    def test_no_address_in_the_data(self):
        for path in DATA.iterdir():
            self.assertIsNone(IPV4.search(path.read_text()), path.name)
        self.assertIn("0b21f09", (DATA / "SOURCE").read_text())

    def test_generated_files_are_the_converter_output(self):
        header, source = conv.build([("real", str(DATA / "real-board-2026-10-07.json")),
                                     ("sim", str(DATA / "sim-docker-2026-10-07.json"))])
        tests = REPO / "sim" / "inv" / "tests"
        self.assertEqual((tests / "fixtures_data.h").read_text(), header)
        self.assertEqual((tests / "fixtures_data.c").read_text().rstrip("\n"), source.rstrip("\n"))
        self.assertIsNone(IPV4.search(header + source))


class Constants(TempDirTestCase):
    def test_header_equals_the_constants_file(self):
        table = tomllib.loads((REPO / "policy" / "sim_constants.toml").read_text())
        header = (REPO / "sim" / "inv" / "wire_consts.h").read_text()
        defined = {m.group(1): int(m.group(2), 0) for m in re.finditer(r"^    WIRE_([A-Z_0-9]+) = (0x[0-9A-Fa-f]+|[0-9]+),$", header, re.MULTILINE)}
        self.assertEqual(sorted(defined), sorted(table))
        for name, entry in table.items():
            self.assertEqual(defined[name], entry["value"], name)
            self.assertGreater(len(entry["source"]), 20, name)
        for name in ("PULSE_CAP_UNITS", "GAP_MS", "WATCHDOG_MARGIN_MS", "WATCHDOG_CAP_MS", "BURN_MS"):
            self.assertIn("HW", table[name]["source"])
        self.assertEqual([defined[n] for n in ("PULSE_CAP_UNITS", "GAP_MS", "WATCHDOG_MARGIN_MS", "WATCHDOG_CAP_MS", "BURN_MS")],
                         [8, 300, 150, 900, 1000])


class Converter(TempDirTestCase):
    def write(self, exchanges, name="rec.json", extra=None):
        path = self.tmp / name
        data = {"host": "x", "port": 1, "flagged": False, "exchanges": exchanges}
        data.update(extra or {})
        path.write_text(json.dumps(data))
        return str(path)

    def test_two_records_per_exchange_and_host_dropped(self):
        path = self.write([exchange(0, 10, READ, OFF), exchange(20, 10, FLASH, FLASH)], extra={"host": "real-board"})
        recs = conv.records(conv.load(path))
        self.assertEqual([(t, d) for t, d, _ in recs], [(0, 0), (10, 1), (20, 0), (30, 1)])
        self.assertEqual(recs[0][2], bytes.fromhex(READ))
        header, source = conv.build([("a", path)])
        self.assertNotIn("real-board", header + source)

    def test_segments_cut_at_the_verify_read_before_a_flash(self):
        ex = [exchange(0, 1, READ, OFF), exchange(10, 1, FLASH, FLASH), exchange(40, 1, READ, ON), exchange(460, 1, READ, OFF),
              exchange(470, 1, FLASH, FLASH), exchange(490, 1, READ, ON), exchange(950, 1, READ, OFF)]
        loaded = [conv.load(self.write(ex))][0]
        segs = conv.segments(loaded)
        self.assertEqual([len(s) for s in segs], [4, 4])
        self.assertEqual(segs[0][-1], segs[1][0])  # the verify read is the last of one and the first of the next
        # A pair (two flashes in a row) is one flight.
        pair = [exchange(0, 1, READ, OFF), exchange(10, 1, FLASH, FLASH), exchange(20, 1, FLASH, FLASH), exchange(40, 1, READ, OFF)]
        self.assertEqual(len(conv.segments(conv.load(self.write(pair, "pair.json")))), 1)
        # No flash, no cut.
        self.assertEqual(len(conv.segments(conv.load(self.write([exchange(0, 1, READ, OFF)] * 3, "none.json")))), 1)

    def test_refusals(self):
        with self.assertRaises(conv.ConvertError):
            conv.load(self.write([]))
        with self.assertRaises(conv.ConvertError):
            conv.load(self.write([{"t_ms": 1}]))
        (self.tmp / "bad.json").write_text("[1, 2")
        with self.assertRaises(conv.ConvertError):
            conv.load(str(self.tmp / "bad.json"))
        (self.tmp / "list.json").write_text("[1, 2]")
        with self.assertRaises(conv.ConvertError):
            conv.load(str(self.tmp / "list.json"))
        with self.assertRaises(conv.ConvertError):
            conv.load(self.write([exchange(0, 1, "", OFF)]))
        with self.assertRaises(conv.ConvertError):
            conv.load(self.write([exchange(0, 1, "00" * 17, OFF)]))
        with self.assertRaises(conv.ConvertError):
            conv.records(conv.load(self.write([exchange(100, 10, READ, OFF), exchange(105, 1, READ, OFF)], "back.json")))
        # The output names the input file: an address in that name is refused, never written.
        with self.assertRaises(conv.ConvertError):
            conv.build([("a", self.write([exchange(0, 1, READ, OFF)], "10.0.0.1.json"))])

    def test_check_mode_and_exit_codes(self):
        real = self.write([exchange(0, 1, READ, OFF), exchange(10, 1, FLASH, FLASH), exchange(40, 1, READ, OFF)], "r.json")
        out = self.tmp / "out"
        out.mkdir()
        args = ["--real", real, "--sim", real, "--out-dir", str(out)]
        self.assertEqual(conv.main(args), 0)
        self.assertEqual(conv.main(args + ["--check"]), 0)
        (out / "fixtures_data.c").write_text("changed")
        self.assertEqual(conv.main(args + ["--check"]), 1)
        self.assertEqual(conv.main(["--real", str(self.tmp / "missing.json"), "--sim", real, "--out-dir", str(out)]), 2)
