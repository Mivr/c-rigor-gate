"""The forbidden-pattern table. This is the ONLY place patterns are defined.

Every pattern is case-sensitive and is searched for in each ADDED line of any file type.
Each id needs a red sample in tests/test_suppressions.py (a test checks the two agree).
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ForbiddenPattern:
    pattern_id: str
    regex: re.Pattern
    exempt_name_suffix: str = ""  # files whose name ends with this are exempt ("" = none)


FORBIDDEN_PATTERNS = (
    ForbiddenPattern("pragma-diagnostic",
                     re.compile(r"#\s*pragma\s+(clang|GCC)\s+(diagnostic|optimize|system_header)")),
    ForbiddenPattern("pragma-operator", re.compile(r"_Pragma\s*\(")),
    ForbiddenPattern("nolint", re.compile(r"NOLINT")),
    ForbiddenPattern("wno-flag", re.compile(r"-Wno-")),
    # `-w` as a flag: not glued to a word or another dash before it (so not "re-write", "--w").
    ForbiddenPattern("w-flag", re.compile(r"(?<![\w-])-w\b")),
    ForbiddenPattern("no-sanitize", re.compile(r"no_sanitize")),
    ForbiddenPattern("attribute-optnone",
                     re.compile(r"__attribute__\s*\(\(\s*(optnone|no_instrument_function)")),
    ForbiddenPattern("define-ndebug-assert", re.compile(r"#\s*(define|undef)\s+(assert|NDEBUG)\b")),
    ForbiddenPattern("sanitize-address-macro", re.compile(r"__SANITIZE_ADDRESS__")),
    ForbiddenPattern("has-feature-sanitizer", re.compile(r"__has_feature\s*\(\s*\w*sanitizer")),
    ForbiddenPattern("getenv-gate", re.compile(r'getenv\s*\(\s*"(CI|GATE|RIGOR|BUCK|TEST)')),
    ForbiddenPattern("llvm-profile", re.compile(r"LLVM_PROFILE|__llvm_profile")),
    ForbiddenPattern("fuzzer-entry", re.compile(r"LLVMFuzzer"), exempt_name_suffix="_fuzz.c"),
    ForbiddenPattern("fno-sanitize", re.compile(r"-fno-sanitize")),
    ForbiddenPattern("sanitizer-options", re.compile(r"UBSAN_OPTIONS|ASAN_OPTIONS|LSAN_OPTIONS")),
)

# File names that look like build products; adding or changing one is always a finding.
BINARY_ARTIFACT_SUFFIXES = (".o", ".a", ".so", ".profdata", ".profraw")


def _basename(path_text):
    return path_text.rsplit("/", 1)[-1]


def matching_pattern_ids(path_text, line_text):
    """Ids of every forbidden pattern found in one added line of the file `path_text`."""
    name = _basename(path_text)
    found = []
    for pattern in FORBIDDEN_PATTERNS:
        if pattern.exempt_name_suffix and name.endswith(pattern.exempt_name_suffix):
            continue
        if pattern.regex.search(line_text):
            found.append(pattern.pattern_id)
    return found


def is_binary_artifact_name(path_text):
    return _basename(path_text).endswith(BINARY_ARTIFACT_SUFFIXES)
