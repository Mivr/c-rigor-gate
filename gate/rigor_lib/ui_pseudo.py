"""`ui_pseudo`: the pseudo-locale generator of the UI gate (P004 3.8, U17a). docs/ui-pseudo.md.

From the `.pot` files and the product's `.po` files, one pseudo-locale `.po` per `.pot` (language `xx`). The result
is a pure function of the file bytes: no clock, no paths, no locale, and independent of the order of the inputs.
Runs inside a Buck2 action (`rules/ui_pseudo.bzl`, `python3 -I -B`) and in the unit tests; Python 3.8+ stdlib only.

    python3 -I -B ui_pseudo.py --source-lang en --pot FILE... [--po LANG FILE]... --out FILE...
                               [--lang xx] [--overall-pct N] [--extended]

`--out` is given once per `--pot`, in the same order, as `--po LANG FILE` is (one file per pot and language).
Exit 0 = written, 2 = refused (house error on stderr, no output file).

Length of the pseudo text of one msgid (characters, delimiters and placeholders included):

    max(longest real translation, ceil(len(msgid) * IBM_TABLE[len(msgid)]), ceil(len(msgid) * (1 + overall_pct/100)))

Content: START, then Cyrillic padding made of the tallest and deepest glyphs, then END. Placeholders, `{{`, `}}` and
line breaks of the source stay where they are, with the padding between them in proportion to the English text
between them; the white space at the edges of those pieces is kept.

Without `--extended` every input must be acceptable to `po2c` (it is run on them first); that is the same grammar
`c_catalog_gen` reads, so the generated files are accepted by it. `--extended` also reads `msgctxt`, `msgid_plural`
and `msgstr[n]` (and `%d`/`{name}` style placeholders) and writes them back; `po2c` itself refuses those today.
"""

import argparse
import re
import sys

# IBM's expansion guideline for translated text, by the length of the English text (characters): the upper end of
# each band. Source: IBM Globalization guidelines "Text expansion", reproduced in Microsoft's pseudolocalisation
# note (P004 3.8, [E: Practitioner 2022 (prac)]). (upper bound of the band, percent of the English length)
IBM_TABLE = ((10, 300), (20, 200), (30, 180), (50, 160), (70, 140), (None, 130))
START = "["
END = "]"
# Tallest (Й: breve above the cap height; Щ and ц: tail below the baseline) and deepest (р, у: descender; щ: tail).
PADDING = "ЙщрЩуцЩйр"
WORD = 5   # padding characters between two spaces, so that the line can wrap like text
LANG = "xx"
# What is kept verbatim: `{{`, `}}`, `{0}`, `{name}`, printf conversions and line breaks.
TOKEN = re.compile(r"\{\{|\}\}|\{[0-9]\}|\{[A-Za-z_][A-Za-z0-9_]*\}|%%|"
                       r"%(?:[0-9]+\$)?[-+ #0]*[0-9]*(?:\.[0-9]+)?(?:hh|h|ll|l|L|q|j|z|t)?[diouxXeEfgGcsp]|\n")
ESCAPES = {"\\": "\\", '"': '"', "n": "\n", "t": "\t"}


class PseudoError(Exception):
    """A refusal; the text names the file, the line and the msgid when known."""


def show(text):
    return '"%s"' % text.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t").replace('"', '\\"')


def ibm_percent(length):
    for bound, percent in IBM_TABLE:
        if bound is None or length <= bound:
            return percent
    raise AssertionError("unreachable")


def ceil_percent(length, percent):
    return -((-length * percent) // 100)


def target_length(english, real_lengths, overall_pct=None):
    """The length rule of the module docstring."""
    n = len(english)
    want = max([ceil_percent(n, ibm_percent(n)), *real_lengths])
    if overall_pct is not None:
        want = max(want, ceil_percent(n, 100 + overall_pct))
    return want


# ---------------------------------------------------------------------------------------------
# reading (a superset of the po2c subset)
# ---------------------------------------------------------------------------------------------

class Entry:
    def __init__(self, line):
        self.line, self.ctx, self.msgid, self.plural, self.strs, self.field = line, None, None, None, {}, None


def where(path, line):
    return "%s:%d" % (path, line)


def unquote(path, number, text):
    if len(text) < 2 or text[0] != '"' or text[-1] != '"':
        raise PseudoError("%s: expected a quoted string" % where(path, number))
    out, body, i = [], text[1:-1], 0
    while i < len(body):
        char = body[i]
        if char == '"':
            raise PseudoError('%s: unescaped " inside a string' % where(path, number))
        if char != "\\":
            out.append(char)
            i += 1
            continue
        if i + 1 >= len(body) or body[i + 1] not in ESCAPES:
            raise PseudoError("%s: unsupported escape %s" % (where(path, number), show(body[i:i + 2])))
        out.append(ESCAPES[body[i + 1]])
        i += 2
    return "".join(out)


def decode_lines(path, data):
    out = []
    for number, raw in enumerate(data.split(b"\n"), 1):
        try:
            out.append((number, raw.decode("utf-8").strip(" \t\r")))
        except UnicodeDecodeError:
            raise PseudoError("%s: invalid UTF-8" % where(path, number))
    return out


def add_value(path, number, entry, text):
    value = unquote(path, number, text)
    if entry is None or entry.field is None:
        raise PseudoError("%s: a continuation line outside an entry" % where(path, number))
    if entry.field == "ctx":
        entry.ctx += value
    elif entry.field == "msgid":
        entry.msgid += value
    elif entry.field == "plural":
        entry.plural += value
    else:
        entry.strs[entry.field] += value


KEYWORD = re.compile(r"(msgctxt|msgid_plural|msgid|msgstr\[[0-9]+\]|msgstr)\s+(.*)\Z")


def keyword_line(path, number, text, entry, entries):
    found = KEYWORD.match(text)
    if not found:
        raise PseudoError("%s: syntax error: %s" % (where(path, number), show(text[:40])))
    word, rest = found.group(1), found.group(2).strip()
    value = unquote(path, number, rest)
    if word == "msgctxt" or (word == "msgid" and (entry is None or entry.msgid is not None)):
        entry = Entry(number)
        entries.append(entry)
    if entry is None:
        raise PseudoError("%s: %s without an entry" % (where(path, number), word))
    if word == "msgctxt":
        entry.ctx, entry.field = value, "ctx"
    elif word == "msgid":
        entry.msgid, entry.field = value, "msgid"
    elif word == "msgid_plural":
        entry.plural, entry.field = value, "plural"
    else:
        index = 0 if word == "msgstr" else int(word[7:-1])
        if index in entry.strs:
            raise PseudoError("%s: %s twice" % (where(path, number), word))
        entry.strs[index], entry.field = value, index
    return entry


def parse(path, data):
    """-> [Entry] without the header entry; a (ctx, msgid) twice in one file is refused."""
    entries, entry = [], None
    for number, text in decode_lines(path, data):
        if not text or text.startswith("#"):
            continue
        if text.startswith('"'):
            add_value(path, number, entry, text)
        else:
            entry = keyword_line(path, number, text, entry, entries)
    out, seen = [], set()
    for item in entries:
        if item.msgid is None or not item.strs:
            raise PseudoError("%s: an entry without msgid or msgstr" % where(path, item.line))
        key = (item.ctx, item.msgid)
        if key in seen:
            raise PseudoError("%s: msgid %s repeated in the same file" % (where(path, item.line), show(item.msgid)))
        seen.add(key)
        if item.msgid != "" or item.ctx is not None:
            out.append(item)
    return out


# ---------------------------------------------------------------------------------------------
# the pseudo text
# ---------------------------------------------------------------------------------------------

def split_pieces(text, token):
    """-> (gaps, tokens): text == gaps[0] + tokens[0] + gaps[1] + ... + gaps[-1]."""
    gaps, tokens, last = [], [], 0
    for found in token.finditer(text):
        gaps.append(text[last:found.start()])
        tokens.append(found.group(0))
        last = found.end()
    gaps.append(text[last:])
    return gaps, tokens


def padding(count):
    """`count` characters of padding: words of WORD glyphs from the cycle, one space between two words."""
    out, k = [], 0
    for i in range(count):
        if i % (WORD + 1) == WORD and i != count - 1:
            out.append(" ")
        else:
            out.append(PADDING[k % len(PADDING)])
            k += 1
    return "".join(out)


def shares(budget, weights):
    """budget split in proportion to weights (largest remainder, ties to the earlier gap); the weights are > 0."""
    total = sum(weights)
    base = [budget * w // total for w in weights]
    order = sorted(range(len(weights)), key=lambda i: (-(budget * weights[i] % total), i))
    for i in order[:budget - sum(base)]:
        base[i] += 1
    return base


def edges(gap):
    body = gap.strip(" \t")
    lead = gap[:len(gap) - len(gap.lstrip(" \t"))]
    return lead, body, gap[len(lead) + len(body):]


def pseudo_text(msgid, want, token=TOKEN):
    """The pseudo text of one msgid, exactly `want` characters when that is feasible, else the shortest feasible."""
    gaps, tokens = split_pieces(msgid, token)
    parts = [edges(g) for g in gaps]
    live = [i for i, (_, body, _) in enumerate(parts) if body]
    if not live:
        raise PseudoError("msgid %s: nothing but placeholders and white space to pad" % show(msgid))
    fixed = len(START) + len(END) + sum(len(t) for t in tokens) + sum(len(a) + len(c) for a, _, c in parts)
    budget = max(want - fixed, len(live))
    given = dict(zip(live, shares(budget, [len(parts[i][1]) for i in live])))
    out = [START]
    for i, (lead, _, trail) in enumerate(parts):
        out.append(lead + (padding(given[i]) if i in given else "") + trail)
        if i < len(tokens):
            out.append(tokens[i])
    out.append(END)
    return "".join(out)


def forms_of(entry):
    """The English text of every form: msgid, then msgid_plural."""
    return [entry.msgid] if entry.plural is None else [entry.msgid, entry.plural]


def real_length(translations, index):
    """Longest real translation of plural form `index` (the last form given if the language has fewer)."""
    best = 0
    for strs in translations:
        if strs:
            key = index if index in strs else max(strs)
            best = max(best, len(strs[key]))
    return best


def pseudo_entry(entry, translations, overall_pct, token):
    """-> {form index: pseudo text}."""
    english = forms_of(entry)
    count = len(english) if entry.plural is None else max([len(english)] + [len(s) for s in translations])
    out = {}
    for index in range(count):
        source = english[min(index, len(english) - 1)]
        want = target_length(source, [real_length(translations, index)], overall_pct)
        out[index] = pseudo_text(source, want, token)
    return out


def tokens_of(text, token):
    return [t for t in token.findall(text) if t != "\n"]


def check_kept(entry, texts, token):
    """Placeholders: the same count and order as the English of every form."""
    english = forms_of(entry)
    for index, text in texts.items():
        source = english[min(index, len(english) - 1)]
        if tokens_of(text, token) != tokens_of(source, token):
            raise PseudoError("msgid %s: the pseudo text of form %d does not keep the placeholders of the source"
                              % (show(entry.msgid), index))
        if text.count("\n") != source.count("\n"):
            raise PseudoError("msgid %s: the pseudo text of form %d does not keep the line breaks"
                              % (show(entry.msgid), index))


# ---------------------------------------------------------------------------------------------
# writing
# ---------------------------------------------------------------------------------------------

def quote(text):
    return '"%s"' % text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")


def render(items, lang):
    """items: [(entry, {index: text})] -> the .po text."""
    lines = ['msgid ""', 'msgstr ""', '"Content-Type: text/plain; charset=UTF-8\\n"', '"Language: %s\\n"' % lang,
             '"X-Generator: rigor ui-pseudo\\n"', ""]
    for entry, texts in items:
        if entry.ctx is not None:
            lines.append("msgctxt %s" % quote(entry.ctx))
        lines.append("msgid %s" % quote(entry.msgid))
        if entry.plural is None:
            lines.append("msgstr %s" % quote(texts[0]))
        else:
            lines.append("msgid_plural %s" % quote(entry.plural))
            lines.extend("msgstr[%d] %s" % (i, quote(texts[i])) for i in sorted(texts))
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------
# the whole run
# ---------------------------------------------------------------------------------------------

def strict_check(pots, pos, source_lang):
    """Refuse what po2c refuses (the same files, the same grammar). The enum names of po2c are not checked: they
    do not depend on the text and `c_catalog_gen` of the product resolves them with its own `names`."""
    po2c = load_po2c()
    langs = [source_lang] + sorted(pos)
    try:
        po2c.check_names(langs, source_lang, pots, pos, "pseudo")
        messages, index = [], {}
        for k, pot in enumerate(pots):
            po2c.add_pot(messages, index, pot, {name: pos[name][k] for name in pos}, langs, source_lang)
        if not messages:
            raise po2c.CatalogError("the pot files hold no message")
    except po2c.CatalogError as error:
        raise PseudoError("po2c refuses the input: %s" % error)


def load_po2c():
    try:
        from rigor_lib import po2c
        return po2c
    except ImportError:
        import importlib.util
        import os
        spec = importlib.util.spec_from_file_location(
            "po2c", os.path.join(os.path.dirname(os.path.abspath(__file__)), "po2c.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


def sort_key(item):
    return (item.ctx or "", item.msgid)


def generate(pots, pos, source_lang, lang=LANG, overall_pct=None, extended=False):
    """-> [str]: one .po text per pot. `pots`: [(path, bytes)]; `pos`: {lang: [(path, bytes)]}, one file per pot.
    Entries are written sorted by (msgctxt, msgid), so the input order does not matter."""
    if not pots:
        raise PseudoError("no pot files")
    if lang == source_lang or lang in pos:
        raise PseudoError("the pseudo language %s is already a language of the product" % lang)
    for name, files in pos.items():
        if len(files) != len(pots):
            raise PseudoError("%s: %d po files for %d pots" % (name, len(files), len(pots)))
    if not extended:
        strict_check(pots, pos, source_lang)
    token = TOKEN
    out = []
    for k, (path, data) in enumerate(pots):
        tables = {name: {(e.ctx, e.msgid): e.strs for e in parse(*files[k])} for name, files in sorted(pos.items())}
        items = []
        for entry in sorted(parse(path, data), key=sort_key):
            if entry.msgid == "":
                raise PseudoError("%s: an empty msgid with a context is not supported" % where(path, entry.line))
            real = [t[(entry.ctx, entry.msgid)] for t in tables.values() if (entry.ctx, entry.msgid) in t]
            texts = pseudo_entry(entry, real, overall_pct, token)
            check_kept(entry, texts, token)
            items.append((entry, texts))
        out.append(render(items, lang))
    return out


# ---------------------------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------------------------

def read(path):
    try:
        with open(path, "rb") as handle:
            return path, handle.read()
    except OSError as error:
        raise PseudoError("%s: cannot read: %s" % (path, error.strerror))


def add_arguments(p):
    p.add_argument("--source-lang", required=True)
    p.add_argument("--pot", action="append", default=[], required=True)
    p.add_argument("--po", action="append", nargs=2, metavar=("LANG", "FILE"), default=[])
    p.add_argument("--out", dest="outs", action="append", default=[], help="one per --pot; none = print (one --pot only)")
    p.add_argument("--lang", default=LANG)
    p.add_argument("--overall-pct", type=int, default=None, help="UI contract thresholds.pseudo_expansion_overall_pct")
    p.add_argument("--extended", action="store_true", help="also msgctxt, plural forms and %%d placeholders")


def run(args):
    """-> the texts; writes the --out files when given. Raises PseudoError."""
    if args.outs and len(args.outs) != len(args.pot):
        raise PseudoError("%d --out for %d --pot" % (len(args.outs), len(args.pot)))
    if not args.outs and len(args.pot) != 1:
        raise PseudoError("printing needs exactly one --pot; give one --out per --pot")
    if args.overall_pct is not None and not 0 <= args.overall_pct <= 500:
        raise PseudoError("--overall-pct must be in 0..500")
    pos = {}
    for lang, path in args.po:
        pos.setdefault(lang, []).append(read(path))
    texts = generate([read(p) for p in args.pot], pos, args.source_lang, args.lang, args.overall_pct, args.extended)
    for path, text in zip(args.outs, texts):
        with open(path, "wb") as handle:
            handle.write(text.encode("utf-8"))
    return texts


def handle(args):
    """`rigor ui-pseudo`: prints (or writes) the pseudo-locale; a refusal is an internal error, exit 2."""
    from rigor_lib.errors import InternalError
    try:
        texts = run(args)
    except PseudoError as error:
        raise InternalError("ui-pseudo: %s" % error)
    if not args.outs:
        sys.stdout.buffer.write(texts[0].encode("utf-8"))
        sys.stdout.buffer.flush()
    return 0


def add_parser(subparsers):
    parser = subparsers.add_parser("ui-pseudo", allow_abbrev=False,
                                   help="the pseudo-locale .po of a catalogue (P004 3.8, docs/ui-pseudo.md)")
    add_arguments(parser)
    parser.set_defaults(handler=handle)


def main(argv):
    p = argparse.ArgumentParser(prog="ui_pseudo", allow_abbrev=False)
    add_arguments(p)
    try:
        args = p.parse_args(argv)
        texts = run(args)
    except PseudoError as error:
        print("ui_pseudo: error: %s" % error, file=sys.stderr)
        return 2
    if not args.outs:
        sys.stdout.buffer.write(texts[0].encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
