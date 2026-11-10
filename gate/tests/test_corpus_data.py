"""T135: what the line scan does with a fuzz corpus file (data, not code). Recorded, not exempted."""

import unittest

from rigor_lib import patterns


class CorpusFileScan(unittest.TestCase):
    def test_a_corpus_file_is_scanned_like_any_added_file(self):
        # No exemption: a corpus input that contains a forbidden text is a finding (an approval can cover it).
        self.assertEqual(patterns.matching_pattern_ids("fz/corpus/seed", "x -Wno-y NOLINT"), ["nolint", "wno-flag"])

    def test_plain_bytes_are_quiet(self):
        self.assertEqual(patterns.matching_pattern_ids("fz/corpus/seed", "PARS\x07\x00\xff"), [])

    def test_a_corpus_file_named_like_a_build_product_is_a_binary_artifact(self):
        self.assertTrue(patterns.is_binary_artifact_name("fz/corpus/crash.o"))
        self.assertFalse(patterns.is_binary_artifact_name("fz/corpus/crash-d5063fae"))


if __name__ == "__main__":
    unittest.main()
