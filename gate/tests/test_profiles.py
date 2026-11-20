"""Profiles (T127): the technique matrix of P003 4.1, the union rule, the floor rules and the level floor."""

import unittest

from rigor_lib import facts_data, profiles, structure_data
from rigor_lib.profiles import GATE, REPORT

ORDER = ("pure", "parser", "adapter", "concurrent", "wiring", "ui", "safety")
# P003 4.1, one row per technique, one token per profile in ORDER. `-` blank; `G`/`R` gate/report at every level;
# `G2` gates from L2 up; `R3G4` reports at L3 and gates from L4. Written out independently of profiles.MATRIX.
GRID = {
    "tests_release_san":        "G  G  G  G  G  G  G",
    "msan":                     "G  G  R  R  -  -  G",
    "tsan":                     "-  -  -  G  G  -  -",
    "mutation_zero_survivors":  "G3 G3 R  R  -  -  G",
    "pseudo_tested_zero":       "G2 G2 G2 G  G  G  G",
    "model_or_property":        "G3 G  -  -  -  -  G",
    "fuzz":                     "-  G  G  -  -  -  G",
    "fault_injection_sweep":    "-  -  G  -  -  -  G",
    "real_os_tests":            "-  -  G  G  -  -  -",
    "cproof_no_ub":             "-  R3G4 - - -  -  G",
    "cproof_safety_properties": "-  -  -  -  -  -  G",
    "mcdc":                     "-  -  -  -  -  -  G4",
    "whole_app_simulation":     "-  -  -  -  G  G  G",
    "oracle_trace_replay":      "-  -  -  -  G  G  -",
    "catalogue_and_layout":     "-  -  -  -  -  G  -",
    "perf_class":               "G  G  G  -  -  -  G",
    "structure_caps":           "R  R  R  R  R  R  G4",
}


def expected(token, level):
    rank = int(level[1])
    if token == "-":
        return None
    if token == "R3G4":
        return REPORT if rank == 3 else GATE if rank >= 4 else None
    mode = GATE if token[0] == "G" else REPORT
    return mode if rank >= int(token[1:] or 1) else None


def facts(kind="c_library", undefined=(), defined=(), identifiers=(), data=(), deps=()):
    unit = facts_data.Unit("a.c.o", frozenset(defined), frozenset(), frozenset(undefined), (), (),
                           tuple((n, "a.c", 1) for n in identifiers), (), data=tuple(data))
    return facts_data.Facts("//m:m", kind, tuple(deps), (unit,))


def structure(*functions):
    funcs = tuple(structure_data.Func(name, name, "a.c", 1, 2, 1, False, False, 1, 0, 1, 1, (), (), (), type=ty)
                  for name, ty in functions)
    return structure_data.Structure("//m:m", "c_library", (), ("a.c",),
                                    (structure_data.Unit("a.c", (), funcs, ()),))


class MatrixTest(unittest.TestCase):
    def test_every_cell_at_every_level(self):
        self.assertEqual(set(GRID), set(profiles.TECHNIQUES))
        self.assertEqual(ORDER, profiles.PROFILES)
        for technique, row in GRID.items():
            tokens = row.split()
            self.assertEqual(len(tokens), 7, technique)
            for profile, token in zip(ORDER, tokens):
                for level in profiles.LEVELS:
                    want = expected(token, level)
                    got = profiles.required([profile], level).get(technique)
                    self.assertEqual(got, want, "%s / %s / %s" % (technique, profile, level))

    def test_union_gate_wins_over_report(self):
        # msan: parser gates, adapter reports -> gate; mutation: adapter reports, pure gates at L3+
        both = profiles.required(["adapter", "parser"], "L3")
        self.assertEqual(both["msan"], GATE)
        self.assertEqual(both["mutation_zero_survivors"], GATE)
        self.assertEqual(profiles.required(["adapter", "concurrent"], "L3")["msan"], REPORT)

    def test_union_adds_techniques(self):
        union = profiles.required(["pure", "parser"], "L3")
        for technique in ("fuzz", "cproof_no_ub", "model_or_property", "perf_class"):
            self.assertIn(technique, union)
        self.assertNotIn("tsan", union)
        self.assertEqual(profiles.required(["pure", "parser"], "L3"), profiles.required(["parser", "pure"], "L3"))

    def test_union_is_each_cell_maximum(self):
        for level in profiles.LEVELS:
            for pair in (("pure", "wiring"), ("adapter", "safety"), ("ui", "concurrent")):
                merged = profiles.required(pair, level)
                alone = [profiles.required([p], level) for p in pair]
                self.assertEqual(set(merged), set(alone[0]) | set(alone[1]))
                for technique, mode in merged.items():
                    self.assertEqual(mode == GATE, GATE in (a.get(technique) for a in alone))

    def test_unknown_input_is_refused(self):
        with self.assertRaises(ValueError):
            profiles.required(["fast"], "L3")
        with self.assertRaises(ValueError):
            profiles.required(["pure"], "L9")

    def test_no_profile_no_technique(self):
        self.assertEqual(profiles.required([], "L5"), {})


class FloorTest(unittest.TestCase):
    def floor(self, f, s=None, **kw):
        return profiles.profile_floor(f, s, **kw)

    def test_pure(self):
        self.assertEqual(self.floor(facts(undefined=["memcpy", "strlen"], defined=["f"])), {"pure"})

    def test_f_adapter_syscall(self):
        self.assertEqual(self.floor(facts(undefined=["read"])), {"adapter"})
        self.assertEqual(self.floor(facts(undefined=["clock_gettime", "memcpy"])), {"adapter"})
        reasons = profiles.floor_reasons(facts(undefined=["write", "close"]))
        self.assertEqual(reasons, {"adapter": [("F-adapter", "close"), ("F-adapter", "write")]})

    def test_f_adapter_every_name_of_the_spec(self):
        for name in ("open", "openat", "read", "write", "close", "fsync", "rename", "socket", "connect", "send", "recv",
                     "poll", "getaddrinfo", "clock_gettime"):
            self.assertIn(name, profiles.SYSCALL_IO_SYMBOLS)

    def test_f_adapter_third_party_prefix_and_dep(self):
        self.assertEqual(self.floor(facts(undefined=["mbedtls_ssl_read"]), prefixes=("mbedtls_",)), {"adapter"})
        self.assertEqual(self.floor(facts(undefined=["mbedtls_ssl_read"])), {"pure"})
        dep = facts(deps=["//third_party/mbedtls:mbedtls"])
        self.assertEqual(self.floor(dep, third_labels=frozenset(["gate//third_party/mbedtls:mbedtls"])), {"adapter"})
        self.assertEqual(self.floor(dep, third_labels=frozenset(["gate//third_party/x:x"])), {"pure"})

    def test_f_concurrent_symbols(self):
        for name in ("pthread_create", "thrd_create", "mtx_lock", "cnd_wait"):
            self.assertEqual(self.floor(facts(undefined=[name])), {"concurrent"}, name)
        self.assertEqual(self.floor(facts(undefined=["pthreadish", "mtx", "thread_x"])), {"pure"})

    def test_f_concurrent_builtins(self):
        self.assertEqual(self.floor(facts(identifiers=["__atomic_load_n"])), {"concurrent"})
        self.assertEqual(self.floor(facts(identifiers=["__sync_fetch_and_add"])), {"concurrent"})
        self.assertEqual(self.floor(facts(identifiers=["__builtin_trap", "atomic_load"])), {"pure"})

    def test_f_parser_shapes(self):
        for ty in ("int ( unsigned_char * , unsigned_long )", "int ( char * , int )", "long ( void * , unsigned_int )",
                   "void ( int , char * , unsigned_long , int )", "int ( signed_char * , long_long )"):
            self.assertEqual(self.floor(facts(defined=["f"]), structure(("f", ty))), {"parser"}, ty)

    def test_f_parser_non_shapes(self):
        for ty in ("int ( unsigned_long , unsigned_char * )", "int ( int * , unsigned_long )", "int ( char * )",
                   "int ( char * * , unsigned_long )", "int ( char * , double )", "int ( char * , int * )",
                   "int ( void )", "int ( )", "int ( char * , ... )", None):
            self.assertEqual(self.floor(facts(defined=["f"]), structure(("f", ty))), {"pure"}, ty)

    def test_f_parser_exported_only_and_needs_structure(self):
        ty = "int ( unsigned_char * , unsigned_long )"
        self.assertEqual(self.floor(facts(defined=[]), structure(("f", ty))), {"pure"})   # static: not exported
        self.assertEqual(self.floor(facts(defined=["f"])), {"pure"})                      # no structure facts
        reasons = profiles.floor_reasons(facts(defined=["f"]), structure(("f", ty)))
        self.assertEqual(reasons, {"parser": [("F-parser", "f")]})

    def test_f_wiring(self):
        for section in ("data", "bss", "tls"):
            self.assertEqual(self.floor(facts(data=[("g", 4, section, True)])), {"wiring"}, section)
        self.assertEqual(self.floor(facts(data=[("tab", 64, "ro", False)])), {"pure"})
        self.assertEqual(self.floor(facts(kind="c_test", data=[("g", 4, "bss", True)])), {"pure"})

    def test_floors_combine_and_ui_safety_are_never_floors(self):
        f = facts(undefined=["read", "pthread_create"], data=[("g", 4, "bss", True)])
        self.assertEqual(self.floor(f), {"adapter", "concurrent", "wiring"})
        for profile in ("ui", "safety", "pure"):
            self.assertNotIn(profile, profiles.FLOORED)


class LevelFloorTest(unittest.TestCase):
    def test_dependency_takes_the_dependents_level(self):
        graph = {"top": {"mid": "pure"}, "mid": {"leaf": "pure"}, "leaf": {}}
        levels = {"top": "L3", "mid": "L1", "leaf": "L1"}
        self.assertEqual(profiles.level_floor(graph, levels), {"top": "L1", "mid": "L3", "leaf": "L3"})
        self.assertEqual(profiles.level_floor_detail(graph, levels)["leaf"], ("L3", "mid"))

    def test_data_and_port_edges_are_exempt(self):
        levels = {"a": "L4", "b": "L1", "c": "L1"}
        graph = {"a": {"b": "data", "c": "port"}}
        self.assertEqual(profiles.level_floor(graph, levels), {"a": "L1", "b": "L1", "c": "L1"})

    def test_unknown_and_composition_edges_count(self):
        levels = {"a": "L4", "b": "L1", "c": "L1"}
        graph = {"a": {"b": None, "c": "pure"}}
        self.assertEqual(profiles.level_floor(graph, levels)["b"], "L4")
        self.assertEqual(profiles.level_floor(graph, levels)["c"], "L4")

    def test_highest_dependent_wins_and_ties_are_stable(self):
        levels = {"x": "L2", "y": "L4", "z": "L4", "d": "L1"}
        graph = {"x": {"d": "pure"}, "y": {"d": "pure"}, "z": {"d": "pure"}}
        self.assertEqual(profiles.level_floor_detail(graph, levels)["d"], ("L4", "y"))

    def test_cycles_end_and_foreign_nodes_are_ignored(self):
        levels = {"a": "L2", "b": "L3"}
        graph = {"a": {"b": "pure", "ghost": "pure"}, "b": {"a": "pure"}, "ghost": {"a": "pure"}}
        self.assertEqual(profiles.level_floor(graph, levels), {"a": "L3", "b": "L3"})

    def test_a_module_without_dependents_floors_at_l1(self):
        self.assertEqual(profiles.level_floor({}, {"a": "L5"}), {"a": "L1"})
        self.assertEqual(profiles.level_floor_detail({}, {"a": "L5"})["a"], ("L1", None))

    def test_unknown_level_is_refused(self):
        with self.assertRaises(ValueError):
            profiles.level_floor({}, {"a": "L9"})


if __name__ == "__main__":
    unittest.main()
