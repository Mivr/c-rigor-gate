"""Module profiles, the technique matrix and the computed floors (P003 section 4 and 10.1). Pure: no IO.

A module's **profile** says what kind of code it is (`pure`, `parser`, ...); the profile picks the techniques and the
level picks how much of each (`required`). Nothing here lets a declaration lower anything: `profile_floor` computes
the profiles a module needs from the facts the gate already has, `level_floor` the level from the dependency graph,
and `policy_check` rejects a policy that declares less. Every floor rule has an id (`F-adapter`, ...) that the finding
names. See docs/profiles.md for the limits of each rule.
"""

from rigor_lib import structure_types
from rigor_lib.facts_third_party import canonical

PROFILES = ("pure", "parser", "adapter", "concurrent", "wiring", "ui", "safety")
LEVELS = ("L1", "L2", "L3", "L4", "L5")
GATE = "gate"
REPORT = "report"
FLOORED = ("adapter", "concurrent", "parser", "wiring")    # `pure` is the default, `ui` and `safety` are declared only

# --- the technique matrix of P003 4.1 ---------------------------------------------------------------------------
# One row per technique, one cell per profile; a blank cell is absent. A cell is "STEP,STEP,..." with STEP = `G` (gates
# the verdict) or `R` (reported), optionally `:Ln` (from that level up). The steps of a cell are ordered by level.
TECHNIQUES = (
    "tests_release_san", "msan", "tsan", "mutation_zero_survivors", "pseudo_tested_zero", "model_or_property",
    "fuzz", "fault_injection_sweep", "real_os_tests", "cproof_no_ub", "cproof_safety_properties", "mcdc",
    "whole_app_simulation", "oracle_trace_replay", "catalogue_and_layout", "perf_class", "structure_caps",
)
MATRIX = {
    "tests_release_san": dict(pure="G", parser="G", adapter="G", concurrent="G", wiring="G", ui="G", safety="G"),
    "msan": dict(pure="G", parser="G", adapter="R", concurrent="R", safety="G"),
    "tsan": dict(concurrent="G", wiring="G"),
    "mutation_zero_survivors": dict(pure="G:L3", parser="G:L3", adapter="R", concurrent="R", safety="G"),
    "pseudo_tested_zero": dict(pure="G:L2", parser="G:L2", adapter="G:L2", concurrent="G", wiring="G", ui="G",
                               safety="G"),
    "model_or_property": dict(pure="G:L3", parser="G", safety="G"),
    "fuzz": dict(parser="G", adapter="G", safety="G"),
    "fault_injection_sweep": dict(adapter="G", safety="G"),
    "real_os_tests": dict(adapter="G", concurrent="G"),
    "cproof_no_ub": dict(parser="R:L3,G:L4", safety="G"),
    "cproof_safety_properties": dict(safety="G"),
    "mcdc": dict(safety="G:L4"),
    "whole_app_simulation": dict(wiring="G", ui="G", safety="G"),
    "oracle_trace_replay": dict(wiring="G", ui="G"),
    "catalogue_and_layout": dict(ui="G"),
    "perf_class": dict(pure="G", parser="G", adapter="G", safety="G"),
    "structure_caps": dict(pure="R", parser="R", adapter="R", concurrent="R", wiring="R", ui="R", safety="G:L4"),
}
# The qualifiers the table prints next to a cell. They narrow what the technique is applied to, not whether it runs,
# so `required` ignores them; they are data for the docs and for the later tasks that run the techniques.
QUALIFIERS = {
    ("mutation_zero_survivors", "pure"): "L3+",
    ("model_or_property", "parser"): "round trip",
    ("fuzz", "adapter"): "if it parses",
    ("fuzz", "safety"): "decoders",
    ("fault_injection_sweep", "safety"): "driver",
    ("mcdc", "safety"): "threshold is a proposal [P]",
    ("perf_class", "pure"): "where declared",
    ("perf_class", "adapter"): "per operation",
}

# --- the floor rules ---------------------------------------------------------------------------------------------
# F-adapter: an undefined symbol of this table (the syscalls and IO calls the product policies allow or deny today),
# or one that starts with a reserved prefix of a gate-owned third-party library, or a dependency on such a library.
SYSCALL_IO_SYMBOLS = frozenset((
    "open", "openat", "creat", "read", "write", "pread", "pwrite", "readv", "writev", "close", "lseek", "fsync",
    "fdatasync", "ftruncate", "fcntl", "flock", "ioctl", "dup", "dup2", "pipe", "rename", "renameat", "unlink",
    "unlinkat", "link", "linkat", "symlink", "mkdir", "rmdir", "stat", "fstat", "lstat", "__xstat", "__fxstat",
    "__lxstat", "opendir", "readdir", "closedir", "mmap", "munmap", "mprotect", "socket", "bind", "listen", "accept",
    "accept4", "connect", "send", "recv", "sendto", "recvfrom", "sendmsg", "recvmsg", "shutdown", "setsockopt",
    "getsockopt", "getsockname", "getpeername", "getaddrinfo", "freeaddrinfo", "poll", "ppoll", "select", "pselect",
    "epoll_create1", "epoll_ctl", "epoll_wait", "clock_gettime", "clock_nanosleep", "gettimeofday", "time",
    "nanosleep", "sleep", "usleep", "getrandom", "getenv", "getpid", "sysconf", "fopen", "fclose", "fread", "fwrite",
    "fflush", "fgets", "fputs", "fprintf", "printf", "puts", "putchar", "perror", "stdin", "stdout", "stderr",
))
CONCURRENT_PREFIXES = ("pthread_", "thrd_", "mtx_", "cnd_")
CONCURRENT_BUILTIN_PREFIXES = ("__atomic_", "__sync_", "__c11_atomic_")
# F-parser: an exported function with a parameter of type pointer to char / unsigned char / uint8_t / void followed
# by an integer parameter. The scanner's canonical types drop qualifiers and expand typedefs, so `const` is not seen
# and `uint8_t` is `unsigned_char`.
BYTE_POINTEES = frozenset(("char", "unsigned_char", "signed_char", "void"))
RULE_ADAPTER = "F-adapter"
RULE_CONCURRENT = "F-concurrent"
RULE_PARSER = "F-parser"
RULE_WIRING = "F-wiring"
RULES = {"adapter": RULE_ADAPTER, "concurrent": RULE_CONCURRENT, "parser": RULE_PARSER, "wiring": RULE_WIRING}
WRITABLE = ("data", "bss", "tls")
TEST_KINDS = ("c_test", "c_fuzz")


def _steps(cell):
    found = []
    for part in cell.split(","):
        mode, _, level = part.partition(":")
        found.append((LEVELS.index(level) if level else 0, GATE if mode == "G" else REPORT))
    return found


def _check(profiles, level):
    if level not in LEVELS:
        raise ValueError("unknown level %r" % (level,))
    for profile in profiles:
        if profile not in PROFILES:
            raise ValueError("unknown profile %r" % (profile,))


def required(profiles, level):
    """{technique: "gate" | "report"} a module with these `profiles` at `level` is held to.

    The union over the profiles; `gate` wins over `report`. A step of a cell applies from its level up (`G:L3` is
    nothing at L2, `R:L3,G:L4` reports at L3 and gates at L4 and L5). A technique no profile applies is absent.
    """
    _check(profiles, level)
    rank = LEVELS.index(level)
    found = {}
    for technique in TECHNIQUES:
        for profile in profiles:
            cell = MATRIX[technique].get(profile)
            if cell is None:
                continue
            modes = [mode for from_rank, mode in _steps(cell) if from_rank <= rank]
            if not modes:
                continue
            mode = modes[-1]
            if found.get(technique) != GATE:
                found[technique] = mode
    return found


# --- profile floor -----------------------------------------------------------------------------------------------

def _undefined(facts):
    return sorted(frozenset().union(*(unit.undefined for unit in facts.units)) if facts.units else frozenset())


def _adapter(facts, prefixes, third_labels):
    found = []
    for symbol in _undefined(facts):
        if symbol in SYSCALL_IO_SYMBOLS or (prefixes and symbol.startswith(tuple(prefixes))):
            found.append(symbol)
    for dep in sorted(d for d in facts.deps if canonical(d) in third_labels):
        found.append(dep)
    return found


def _concurrent(facts):
    found = [s for s in _undefined(facts) if s.startswith(CONCURRENT_PREFIXES)]
    for unit in facts.units:
        for name, _file, _line in unit.identifiers:
            if name.startswith(CONCURRENT_BUILTIN_PREFIXES):
                found.append(name)
    return sorted(set(found))


def _wiring(facts):
    if facts.kind in TEST_KINDS:
        return []
    return sorted({name for unit in facts.units for name, _size, section, _local in unit.data if section in WRITABLE})


def byte_buffer_params(canonical):
    """True when the canonical function type has a byte-pointer parameter directly followed by an integer one."""
    try:
        params = structure_types.parameters(canonical)
    except ValueError:
        return False
    params = params or []
    for first, second in zip(params, params[1:]):
        if len(first) == 2 and first[1] == "*" and first[0] in BYTE_POINTEES \
                and len(second) == 1 and second[0] in structure_types.INTEGERS:
            return True
    return False


def _parser(facts, structure):
    if structure is None:
        return []
    exported = frozenset().union(*(unit.defined for unit in facts.units)) if facts.units else frozenset()
    return sorted({func.name for unit in structure.units for func in unit.functions
                   if func.name in exported and func.type is not None and byte_buffer_params(func.type)})


def floor_reasons(facts, structure=None, prefixes=(), third_labels=frozenset()):
    """{profile: [(rule id, symbol or function), ...]} for the profiles `facts` forces; {} means `pure`.

    `facts` is a facts_data.Facts, `structure` the module's structure_data.Structure (None: F-parser cannot be
    decided and is not applied), `prefixes` the reserved prefixes of the gate-owned third-party libraries and
    `third_labels` their canonical labels. Every list is sorted, so the result is deterministic.
    """
    parts = {"adapter": _adapter(facts, prefixes, third_labels), "concurrent": _concurrent(facts),
             "parser": _parser(facts, structure), "wiring": _wiring(facts)}
    return {profile: [(RULES[profile], detail) for detail in details] for profile, details in parts.items() if details}


def profile_floor(facts, structure=None, prefixes=(), third_labels=frozenset()):
    """The set of profiles a module needs at least: the rules that apply, or {"pure"}."""
    return set(floor_reasons(facts, structure, prefixes, third_labels)) or {"pure"}


# --- level floor -------------------------------------------------------------------------------------------------
EXEMPT_EDGE_KINDS = ("data", "port")


def level_floor_detail(graph, levels):
    """{module: (floor level, the dependent that sets it)}; (L1, None) when nothing counts.

    `graph` is {dependent: {dependency: edge kind or None}}; `levels` {module: declared level}. A module is at least
    the *effective* level (declared, or its own floor if higher) of every dependent over an edge that is not `data`
    or `port`; an unknown kind (None) counts. Only modules of `levels` are nodes. No recursion: the floors only rise,
    so the loop ends after at most nodes x levels rounds.
    """
    for level in levels.values():
        if level not in LEVELS:
            raise ValueError("unknown level %r" % (level,))
    edges = sorted((dep, source) for source, deps in graph.items() if source in levels
                   for dep, kind in deps.items() if dep in levels and kind not in EXEMPT_EDGE_KINDS)
    floor = {label: (0, None) for label in levels}
    for _ in range(len(levels) * len(LEVELS) + 1):
        changed = False
        for dep, source in edges:
            effective = max(LEVELS.index(levels[source]), floor[source][0])
            if effective > floor[dep][0]:
                floor[dep] = (effective, source)
                changed = True
        if not changed:
            break
    return {label: (LEVELS[rank], who) for label, (rank, who) in floor.items()}


def level_floor(graph, levels):
    """{module: level}: the lowest level each module of `levels` may have (see `level_floor_detail`)."""
    return {label: level for label, (level, _who) in level_floor_detail(graph, levels).items()}
