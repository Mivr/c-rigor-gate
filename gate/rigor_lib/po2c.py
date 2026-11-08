"""`po2c`: gettext `.pot`/`.po` files -> one const C message catalog (T105, `c_catalog`, docs/grade.md).

Runs inside a Buck2 action (`rules/catalog.bzl`) and in the unit tests; Python 3.8+ stdlib only, no import of
the rest of the gate (a Buck action runs it with `python3 -I -B`).

    python3 -I -B po2c.py --symbol S --langs bg,en --source-lang en --header pkg/name.h --runtime-header RH
                          --pot FILE... [--po LANG FILE]... --out-h FILE --out-c FILE

The generated code targets the runtime `i18n.h` (`i18n_catalog_t`): `str[msgid * n_langs + lang]` and `n_args[msgid]`.
Every violation is a build error that names the file, the line and the msgid; the first one stops the run
(exit 1, message on stderr, no output file). The output is a pure function of the inputs (no clock, no paths).

The PO subset: `msgid`/`msgstr` with continuation lines (concatenated), `#` comments ignored, the header entry
(`msgid ""`) ignored except that a `Content-Type` charset other than UTF-8 fails. Escapes: `\\\\ \\" \\n \\t` only.
`msgctxt`, `msgid_plural`, `msgstr[n]` and `#, fuzzy` fail. Invalid UTF-8 fails.

Template rules (grammar of i18n.h): `{0}`..`{9}`, `{{`, `}}`, everything else with a brace is malformed.
`n_args` is the number of distinct placeholder indices of the SOURCE msgid, which must be exactly 0..n-1.
Every language must use the same set of indices as the source. Counts: an index the source uses exactly once is
used exactly once by every translation; an index the source repeats is used at least once (a translation may
repeat it fewer or more times).
"""

import argparse
import re
import sys

MAX_ARGS = 10
MAX_WORDS = 48
MAX_MSGS = 65535   # uint16_t msgid
MAX_LANGS = 255    # uint8_t lang
SYMBOL = re.compile(r"[A-Za-z][A-Za-z0-9_]*\Z")
HEADER_PATH = re.compile(r"[A-Za-z0-9_./+-]+\Z")
DIGITS = "0123456789"
ESCAPES = {"\\": "\\", '"': '"', "n": "\n", "t": "\t"}
UNSUPPORTED = ("msgctxt", "msgid_plural", "msgstr[")


class CatalogError(Exception):
    """A build error; the text names the file, the line and the msgid."""


def show(text):
    """A msgid on one line for a message."""
    return '"%s"' % text.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t").replace('"', '\\"')


def fail(path, line, msgid, why):
    where = "%s:%d" % (path, line) if line else path
    raise CatalogError("%s: %s%s" % (where, "msgid %s: " % show(msgid) if msgid is not None else "", why))


# ---------------------------------------------------------------------------------------------
# the PO subset
# ---------------------------------------------------------------------------------------------

def unquote(path, number, text, msgid):
    """The value of one `"..."` token (the whole text), escapes decoded."""
    if len(text) < 2 or text[0] != '"' or text[-1] != '"':
        fail(path, number, msgid, "expected a quoted string")
    out, body, i = [], text[1:-1], 0
    while i < len(body):
        char = body[i]
        if char == '"':
            fail(path, number, msgid, 'unescaped " inside a string')
        if char != "\\":
            out.append(char)
            i += 1
            continue
        if i + 1 >= len(body) or body[i + 1] not in ESCAPES:
            fail(path, number, msgid, "unsupported escape %s" % show(body[i:i + 2]))
        out.append(ESCAPES[body[i + 1]])
        i += 2
    return "".join(out)


def decode_lines(path, data):
    """-> [(line number, text)]; invalid UTF-8 fails with the line it is on."""
    lines = []
    for number, raw in enumerate(data.split(b"\n"), 1):
        try:
            lines.append((number, raw.decode("utf-8").strip(" \t\r")))
        except UnicodeDecodeError:
            fail(path, number, None, "invalid UTF-8")
    return lines


class Entry:
    def __init__(self, line):
        self.line, self.msgid, self.msgstr, self.field = line, None, None, None


def check_header(path, entry):
    for text in entry.msgstr.split("\n"):
        if text.lower().startswith("content-type:"):
            match = re.search(r"charset=([^\s;]+)", text, re.IGNORECASE)
            if match and match.group(1).upper() != "UTF-8":
                fail(path, entry.line, "", "charset %s is not UTF-8" % match.group(1))


def keyword_line(path, number, text, entry, entries):
    """Handle `msgid "..."` / `msgstr "..."`; returns the entry now being read."""
    word, _, rest = text.partition(" ")
    if word == "msgid":
        if entry is not None and entry.msgstr is None:
            fail(path, entry.line, entry.msgid, "msgid without a msgstr")
        entry = Entry(number)
        entry.msgid, entry.field = unquote(path, number, rest.strip(), None), "msgid"
        entries.append(entry)
        return entry
    if word == "msgstr":
        if entry is None or entry.msgstr is not None:
            fail(path, number, entry.msgid if entry else None, "msgstr without a msgid")
        entry.msgstr, entry.field = unquote(path, number, rest.strip(), entry.msgid), "msgstr"
        return entry
    fail(path, number, entry.msgid if entry else None, "syntax error: %s" % show(text[:40]))


def parse_po(path, data):
    """-> [(msgid, msgstr, line)] without the header entry. A msgid twice in one file fails."""
    entries, entry = [], None
    for number, text in decode_lines(path, data):
        if not text:
            continue
        if text.startswith("#"):
            if text.startswith("#,") and "fuzzy" in [t.strip() for t in text[2:].split(",")]:
                fail(path, number, None, "fuzzy entries are not supported")
            continue
        if text.startswith(UNSUPPORTED):
            fail(path, number, None, "%s is not supported" % text.split(" ")[0].split("[")[0])
        if text.startswith('"'):
            if entry is None or entry.field is None:
                fail(path, number, None, "a continuation line outside an entry")
            value = unquote(path, number, text, entry.msgid)
            if entry.field == "msgid":
                entry.msgid += value
            else:
                entry.msgstr += value
            continue
        entry = keyword_line(path, number, text, entry, entries)
    if entry is not None and entry.msgstr is None:
        fail(path, entry.line, entry.msgid, "msgid without a msgstr")
    return strip_header(path, entries)


def strip_header(path, entries):
    out, seen = [], set()
    for entry in entries:
        if entry.msgid in seen:
            fail(path, entry.line, entry.msgid, "msgid repeated in the same file")
        seen.add(entry.msgid)
        if entry.msgid == "":
            check_header(path, entry)
        else:
            out.append((entry.msgid, entry.msgstr, entry.line))
    return out


# ---------------------------------------------------------------------------------------------
# templates
# ---------------------------------------------------------------------------------------------

def placeholders(text):
    """The placeholder indices of a template in order of appearance; ValueError(why) when malformed."""
    found, i = [], 0
    while i < len(text):
        char, after = text[i], text[i + 1:i + 2]
        if char == "{" and after == "{":
            i += 2
        elif char == "{" and after != "" and after in DIGITS and text[i + 2:i + 3] == "}":
            found.append(int(after))
            i += 3
        elif char == "{":
            raise ValueError("malformed template: bad '{' at offset %d" % i)
        elif char == "}" and after == "}":
            i += 2
        elif char == "}":
            raise ValueError("malformed template: lone '}' at offset %d" % i)
        else:
            i += 1
    return found


def checked_placeholders(path, line, msgid, text):
    try:
        return placeholders(text)
    except ValueError as error:
        fail(path, line, msgid, str(error))


def source_args(path, line, msgid):
    """n_args of a source msgid, and its placeholders."""
    used = checked_placeholders(path, line, msgid, msgid)
    distinct = sorted(set(used))
    if distinct != list(range(len(distinct))):
        fail(path, line, msgid, "placeholder indices must be exactly 0..n-1, got %s" % distinct)
    assert len(distinct) <= MAX_ARGS
    return len(distinct), used


def check_translation(path, line, msgid, lang, text, source_used):
    used = checked_placeholders(path, line, msgid, text)
    if set(used) != set(source_used):
        fail(path, line, msgid, "%s uses placeholders %s, the source uses %s"
             % (lang, sorted(set(used)), sorted(set(source_used))))
    for index in sorted(set(source_used)):
        if source_used.count(index) == 1 and used.count(index) != 1:
            fail(path, line, msgid, "%s uses {%d} %d times, the source once" % (lang, index, used.count(index)))


# ---------------------------------------------------------------------------------------------
# the catalog
# ---------------------------------------------------------------------------------------------

def enum_words(msgid):
    """WORDS of the enum name: runs of non-[A-Za-z0-9] bytes -> `_`, upper case, trimmed, 48 characters, N before a digit."""
    words = re.sub(rb"[^A-Za-z0-9]+", b"_", msgid.encode("utf-8")).decode("ascii").upper().strip("_")
    words = words[:MAX_WORDS].rstrip("_")
    return "N" + words if words[:1] in DIGITS and words else words


class Message:
    def __init__(self, msgid, n_args, texts):
        self.msgid, self.n_args, self.texts = msgid, n_args, texts


def translations(files, other, pot_ids, source_lang, pot_path):
    """{lang: {msgid: (msgstr, line)}}; a po msgid that is not in its pot fails."""
    out = {}
    for lang in other:
        path, data = files[lang]
        table = {}
        for msgid, msgstr, line in parse_po(path, data):
            if msgid not in pot_ids:
                fail(path, line, msgid, "not in %s" % pot_path)
            table[msgid] = (msgstr, line)
        out[lang] = table
    return out


def merge(known, texts, pot_path, line):
    """A msgid seen in an earlier pot: every language's text must be identical."""
    for lang in sorted(texts):
        if known.texts[lang] != texts[lang]:
            fail(pot_path, line, known.msgid, "also in an earlier pot, with a different %s translation" % lang)


def add_pot(messages, index, pot, files, langs, source_lang):
    pot_path, pot_data = pot
    entries = parse_po(pot_path, pot_data)
    other = [lang for lang in langs if lang != source_lang]
    tables = translations(files, other, {e[0] for e in entries}, source_lang, pot_path)
    for msgid, _, line in entries:
        n_args, used = source_args(pot_path, line, msgid)
        texts = {source_lang: msgid}
        for lang in other:
            path = files[lang][0]
            msgstr, po_line = tables[lang].get(msgid, ("", 0))
            if msgstr == "":
                fail(path if po_line else pot_path, po_line or line, msgid, "no %s translation (empty or missing msgstr)" % lang)
            check_translation(path, po_line, msgid, lang, msgstr, used)
            texts[lang] = msgstr
        if msgid in index:
            merge(messages[index[msgid]], texts, pot_path, line)
        else:
            index[msgid] = len(messages)
            messages.append(Message(msgid, n_args, texts))


def check_names(langs, source_lang, pots, pos, symbol):
    if not SYMBOL.match(symbol or ""):
        raise CatalogError("symbol %s is not a C identifier" % show(str(symbol)))
    if not langs or len(set(langs)) != len(langs) or len(langs) > MAX_LANGS or source_lang not in langs:
        raise CatalogError("langs must be unique, at most %d, and contain the source language" % MAX_LANGS)
    if not pots:
        raise CatalogError("no pot files")
    if sorted(pos) != sorted(lang for lang in langs if lang != source_lang):
        raise CatalogError("po languages %s differ from langs without the source language" % sorted(pos))
    for lang, files in pos.items():
        if len(files) != len(pots):
            raise CatalogError("%s: %d po files for %d pots" % (lang, len(files), len(pots)))


def build(pots, pos, langs, source_lang, symbol):
    """-> [Message] in first-appearance order. `pots`: [(path, bytes)]; `pos`: {lang: [(path, bytes)]}."""
    check_names(langs, source_lang, pots, pos, symbol)
    messages, index = [], {}
    for k, pot in enumerate(pots):
        add_pot(messages, index, pot, {lang: pos[lang][k] for lang in pos}, langs, source_lang)
    if not messages:
        raise CatalogError("the pot files hold no message")
    if len(messages) > MAX_MSGS:
        raise CatalogError("%d messages do not fit a uint16_t msgid" % len(messages))
    return messages


def enum_names(messages, symbol):
    names, owner = [], {}
    prefix = symbol.upper()
    for message in messages:
        words = enum_words(message.msgid)
        if not words:
            raise CatalogError("msgid %s: no letter or digit to name it by" % show(message.msgid))
        name = "%s_%s" % (prefix, words)
        if name in owner:
            raise CatalogError("msgid %s: enum name %s is also the name of msgid %s"
                               % (show(message.msgid), name, show(owner[name])))
        owner[name] = message.msgid
        names.append(name)
    return names


# ---------------------------------------------------------------------------------------------
# C output
# ---------------------------------------------------------------------------------------------

def c_string(text):
    """A C string literal: printable ASCII as is, every other byte (and `"`, `\\`, `?`) as a 3-digit octal escape."""
    out = []
    for byte in text.encode("utf-8"):
        if 0x20 <= byte < 0x7F and chr(byte) not in '"\\?':
            out.append(chr(byte))
        else:
            out.append("\\%03o" % byte)
    return '"%s"' % "".join(out)


def render_header(messages, symbol, runtime_header):
    prefix = symbol.upper()
    guard = "C_CATALOG_%s_H" % prefix
    lines = ["/* Generated by po2c.py from gettext catalogs. Do not edit. */",
             "#ifndef %s" % guard, "#define %s" % guard, "", '#include "%s"' % runtime_header, "",
             "typedef enum {"]
    lines += ["    %s = %d," % (name, number) for number, name in enumerate(enum_names(messages, symbol))]
    lines += ["    %s__COUNT = %d," % (prefix, len(messages)), "} %s_msg_t;" % symbol, "",
              "extern const i18n_catalog_t %s;" % symbol, "", "#endif", ""]
    return "\n".join(lines)


def render_source(messages, langs, symbol, header):
    count, n_langs = len(messages), len(langs)
    lines = ["/* Generated by po2c.py from gettext catalogs. Do not edit. */",
             '#include "%s"' % header, "", "#include <stddef.h>", "#include <stdint.h>", "",
             "/* Languages, in order: %s. */" % ", ".join(langs),
             "static const char *const %s_str[%d] = {" % (symbol, count * n_langs)]
    for message in messages:
        lines.append("    %s" % " ".join(c_string(message.texts[lang]) + "," for lang in langs))
    lines += ["};", "", "static const uint8_t %s_n_args[%d] = {" % (symbol, count)]
    lines += ["    %d," % message.n_args for message in messages]
    lines += ["};", ""]
    lines += ["_Static_assert(sizeof(%s_str) / sizeof(%s_str[0]) == (size_t)%d, \"str has n_msgs * n_langs entries\");"
              % (symbol, symbol, count * n_langs),
              "_Static_assert(sizeof(%s_n_args) / sizeof(%s_n_args[0]) == (size_t)%d, \"n_args has n_msgs entries\");"
              % (symbol, symbol, count),
              "_Static_assert((size_t)%s__COUNT == (size_t)%d, \"the enum counts the messages\");" % (symbol.upper(), count),
              "", "const i18n_catalog_t %s = {" % symbol, "    .n_msgs = %d," % count, "    .n_langs = %d," % n_langs,
              "    .str = %s_str," % symbol, "    .n_args = %s_n_args," % symbol, "};", ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------------------------

def read(path):
    try:
        with open(path, "rb") as handle:
            return path, handle.read()
    except OSError as error:
        raise CatalogError("%s: cannot read: %s" % (path, error.strerror))


def write(path, text):
    with open(path, "wb") as handle:
        handle.write(text.encode("ascii"))


def parser():
    p = argparse.ArgumentParser(prog="po2c", allow_abbrev=False)
    p.add_argument("--symbol", required=True)
    p.add_argument("--langs", required=True, help="comma separated, index = runtime lang")
    p.add_argument("--source-lang", required=True)
    p.add_argument("--header", required=True, help="include path of the generated header")
    p.add_argument("--runtime-header", required=True)
    p.add_argument("--pot", action="append", default=[])
    p.add_argument("--po", action="append", nargs=2, metavar=("LANG", "FILE"), default=[])
    p.add_argument("--out-h", required=True)
    p.add_argument("--out-c", required=True)
    return p


def run(args):
    langs = args.langs.split(",")
    for path in (args.header, args.runtime_header):
        if not HEADER_PATH.match(path) or ".." in path.split("/"):
            raise CatalogError("%s is not a plain include path" % show(path))
    pos = {}
    for lang, path in args.po:
        pos.setdefault(lang, []).append(read(path))
    messages = build([read(p) for p in args.pot], pos, langs, args.source_lang, args.symbol)
    header = render_header(messages, args.symbol, args.runtime_header)
    source = render_source(messages, langs, args.symbol, args.header)
    write(args.out_h, header)
    write(args.out_c, source)


def main(argv):
    args = parser().parse_args(argv)
    try:
        run(args)
    except CatalogError as error:
        print("po2c: error: %s" % error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
