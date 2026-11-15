"""`ui_pseudo`: the pseudo-locale generator of the UI gate (P004 3.8, U17a). docs/ui-pseudo.md.

From the `.pot` files and the product's `.po` files, one pseudo-locale `.po` per `.pot` (language `xx`). The result is
a pure function of the file bytes: no clock, no paths, no locale, and independent of the order of the inputs.
Runs in unit tests, as `rigor ui-pseudo`, and in a Buck2 action (`rules/ui_pseudo.bzl`); Python 3 stdlib only.

One mode: the grammar of `po2c` (`{0}`..`{9}`, `{{`, `}}`; no msgctxt, no plural, no fuzzy). Everything `po2c`
refuses is refused here, and `po2c` is run over the inputs plus the generated file before anything is written.

Length, per line of a msgid, of the CONTENT (the text between the delimiters; a placeholder counts as its characters,
`{{` and `}}` as one):

    max( ENVELOPE(English length), ceil(English length * (100 + pct) / 100), longest real translation of the line + 1 )

where `pct` is `thresholds.pseudo_expansion_overall_pct` of the UI contract and ENVELOPE is the running maximum of the
IBM table (so a longer English text never gets a shorter result). The delimiters come on top.
"""

import os
import re
import sys

from rigor_lib import po2c

# IBM's expansion guideline for translated text, by the length of the English text (characters): the upper end of
# each band. Source: IBM Globalization guidelines "Text expansion", as reproduced in Microsoft's pseudolocalisation
# note (P004 3.8, [E: Practitioner 2022 (prac)]). (upper bound of the band, percent of the English length)
IBM_TABLE = ((10, 300), (20, 200), (30, 180), (50, 160), (70, 140), (None, 130))
START = "["
END = "]"
# Tallest (Й: breve above the cap height; Щ and ц: tail below the baseline) and deepest (р, у: descender; щ: tail).
PADDING = "ЙщрЩуцЩйр"
LANG = "xx"
TOKEN = re.compile(r"\{\{|\}\}|\{[0-9]\}")


class PseudoError(Exception):
    """A refusal; the text names the file, the line and the msgid when known."""


def show(text):
    return po2c.show(text)


def ibm_percent(length):
    for bound, percent in IBM_TABLE:
        if bound is None or length <= bound:
            return percent
    raise AssertionError("unreachable")


def ceil_percent(length, percent):
    return -((-length * percent) // 100)


def envelope(n):
    """Monotone expansion target: max over m <= n of ceil(m * IBM(m)); the table is not monotone at the band edges
    (10 -> 30, 11 -> 22). Orchestrator ruling of 2026-11-15, open to the owner."""
    return max([0] + [ceil_percent(m, ibm_percent(m)) for m in range(1, n + 1)])


def displayed(text):
    """Characters shown: `{{` and `}}` are one each, a placeholder is its own text."""
    return len(text) - text.count("{{") - text.count("}}")


def target_length(n, real_longest, overall_pct):
    """The content length wanted for an English line of `n` displayed characters."""
    return max(envelope(n), ceil_percent(n, 100 + overall_pct), real_longest + 1)


# ---------------------------------------------------------------------------------------------
# padding
# ---------------------------------------------------------------------------------------------

def padding(count, word, breaks):
    """`count` characters of padding from the glyph cycle: at most `breaks` + 1 words, each of at least `word` glyphs
    (when `count` allows), one space between two words, never a space at an end."""
    words = max(1, min(breaks + 1, (count + 1) // (word + 1)))
    glyphs = count - (words - 1)
    out, k = [], 0
    for w in range(words):
        if w:
            out.append(" ")
        for _ in range(glyphs // words + (1 if w < glyphs % words else 0)):
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


def split_pieces(text):
    """-> (gaps, tokens): text == gaps[0] + tokens[0] + gaps[1] + ... + gaps[-1]. A brace left in a gap is refused."""
    gaps, tokens, last = [], [], 0
    for found in TOKEN.finditer(text):
        gaps.append(text[last:found.start()])
        tokens.append(found.group(0))
        last = found.end()
    gaps.append(text[last:])
    if any("{" in g or "}" in g for g in gaps):
        raise PseudoError("msgid %s: a brace that is not a placeholder" % show(text))
    return gaps, tokens


def edges(gap):
    body = gap.strip(" \t")
    lead = gap[:len(gap) - len(gap.lstrip(" \t"))]
    return lead, body, gap[len(lead) + len(body):]


def words_of(line):
    """(longest word in characters, word breaks) of a line; a placeholder is a word break, not a word."""
    pieces = TOKEN.sub(" ", line).split()
    return max([len(w) for w in pieces] + [1]), max(len(line.split()) - 1, 0)


def real_lines(reals, index, count):
    """The text of line `index` of every real version (a version with another line count: its longest line)."""
    out = []
    for text in reals:
        lines = text.split("\n")
        out.append(lines[index] if len(lines) == count else max(lines, key=displayed))
    return out


def line_parts(line, first, last):
    """-> (parts, tokens, live): `parts` are (lead, body, trail) per gap; the gap at a delimiter loses its white space
    on that side and is always padded, so a placeholder never touches a delimiter."""
    gaps, tokens = split_pieces(line)
    parts = [edges(g) for g in gaps]
    if first:
        parts[0] = ("", parts[0][1], parts[0][2])
    if last:
        parts[-1] = (parts[-1][0], parts[-1][1], "")
    live = [i for i, (_, body, _) in enumerate(parts)
            if body or (first and i == 0) or (last and i == len(parts) - 1)]
    return parts, tokens, live


def pad_line(line, versions, first, last, overall_pct):
    """The pseudo text of one line (no delimiters)."""
    parts, tokens, live = line_parts(line, first, last)
    if not live:
        return line
    longest_real = max([displayed(v) for v in versions] + [0])
    want = target_length(displayed(line), longest_real, overall_pct)
    fixed = sum(displayed(t) for t in tokens) + sum(len(a) + len(c) for a, _, c in parts)
    given = dict(zip(live, shares(max(want - fixed, len(live)), [max(len(parts[i][1]), 1) for i in live])))
    word = max(words_of(v)[0] for v in versions + [line])
    breaks = 0 if len(line.split()) <= 1 else max(words_of(v)[1] for v in versions + [line])
    breaks = max(breaks - sum(1 for lead, _, trail in parts for edge in (lead, trail) if edge), 0)
    out = []
    for i, (lead, _, trail) in enumerate(parts):
        text = padding(given[i], word, breaks) if i in given else ""
        breaks = max(breaks - text.count(" "), 0)
        out.append(lead + text + trail)
        if i < len(tokens):
            out.append(tokens[i])
    return "".join(out)


def has_content(line):
    return bool(TOKEN.sub("", line).strip(" \t"))


def pseudo_text(msgid, reals, overall_pct):
    """The pseudo msgstr of one msgid: START, the padded lines, END."""
    lines = msgid.split("\n")
    if not any(has_content(line) for line in lines):
        raise PseudoError("msgid %s: nothing but placeholders and white space to pad" % show(msgid))
    out = []
    for index, line in enumerate(lines):
        versions = real_lines(reals, index, len(lines))
        out.append(pad_line(line, versions, index == 0, index == len(lines) - 1, overall_pct))
    return START + "\n".join(out) + END


# ---------------------------------------------------------------------------------------------
# checks that do not use the generator's own pieces
# ---------------------------------------------------------------------------------------------

def check_text(msgid, text, reals):
    """The invariants of a generated string, measured with po2c's own placeholder reader."""
    name = show(msgid)
    if not (text.startswith(START) and text.endswith(END)):
        raise PseudoError("msgid %s: the pseudo text lacks its delimiters" % name)
    if po2c.placeholders(text) != po2c.placeholders(msgid):
        raise PseudoError("msgid %s: the pseudo text does not keep the placeholders (count and order)" % name)
    for brace in ("{{", "}}"):
        if text.count(brace) != msgid.count(brace):
            raise PseudoError("msgid %s: the pseudo text does not keep %s" % (name, brace))
    src, out = msgid.split("\n"), text[len(START):-len(END)].split("\n")
    if len(src) != len(out):
        raise PseudoError("msgid %s: the pseudo text does not keep the line breaks" % name)
    for index, (a, b) in enumerate(zip(src, out)):
        longest = max([displayed(v) for v in real_lines(reals, index, len(src))] + [0])
        if has_content(a) and displayed(b) <= longest:
            raise PseudoError("msgid %s: line %d of the pseudo text is not longer than every real translation"
                              % (name, index + 1))


def quote(text):
    return '"%s"' % text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")


def render(items, lang):
    lines = ['msgid ""', 'msgstr ""', '"Content-Type: text/plain; charset=UTF-8\\n"', '"Language: %s\\n"' % lang,
             '"X-Generator: rigor ui-pseudo\\n"', ""]
    for msgid, text in items:
        lines += ["msgid %s" % quote(msgid), "msgstr %s" % quote(text), ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------
# the whole run
# ---------------------------------------------------------------------------------------------

def po2c_accepts(pots, pos, source_lang):
    """po2c's own checks (grammar, translations, placeholders) without its enum names, which do not depend on text."""
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


def generate(pots, pos, source_lang, overall_pct, lang=LANG):
    """-> [str]: one .po text per pot. `pots`: [(path, bytes)]; `pos`: {lang: [(path, bytes)]}, one file per pot.
    Entries are written sorted by msgid, so the input order does not matter."""
    if type(overall_pct) is not int or not 0 <= overall_pct <= 500:
        raise PseudoError("the overall expansion floor must come from the UI contract (an integer 0..500)")
    if lang == source_lang or lang in pos:
        raise PseudoError("the pseudo language %s is already a language of the product" % lang)
    for name, files in pos.items():
        if len(files) != len(pots):
            raise PseudoError("%s: %d po files for %d pots" % (name, len(files), len(pots)))
    po2c_accepts(pots, pos, source_lang)
    out = []
    try:
        for k, (path, data) in enumerate(pots):
            tables = [{m: s for m, s, _ in po2c.parse_po(*files[k])} for _, files in sorted(pos.items())]
            items = []
            for msgid in sorted(m for m, _, _ in po2c.parse_po(path, data)):
                reals = [t[msgid] for t in tables if msgid in t]
                text = pseudo_text(msgid, reals, overall_pct)
                check_text(msgid, text, reals)
                items.append((msgid, text))
            out.append(render(items, lang))
    except po2c.CatalogError as error:
        raise PseudoError(str(error))
    pseudo = dict(pos)
    pseudo[lang] = [("%s.%s.po" % (p.rsplit("/", 1)[-1], lang), t.encode("utf-8")) for (p, _), t in zip(pots, out)]
    po2c_accepts(pots, pseudo, source_lang)
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


def contract_floor(path):
    """thresholds.pseudo_expansion_overall_pct of the UI contract. A defect of the file or a pending value is the
    contract's own typed error (InternalError / ContractPending), reported as a refusal, never a missing floor."""
    from rigor_lib import ui_contract
    from rigor_lib.errors import InternalError
    try:
        return ui_contract.load(path).get("thresholds", "pseudo_expansion_overall_pct")
    except (ui_contract.ContractPending, InternalError) as error:
        raise PseudoError("UI contract %s: %s" % (path, error))


def add_arguments(p):
    p.add_argument("--source-lang", required=True)
    p.add_argument("--contract", required=True, help="the UI contract file (thresholds.pseudo_expansion_overall_pct)")
    p.add_argument("--pot", action="append", default=[], required=True)
    p.add_argument("--po", action="append", nargs=2, metavar=("LANG", "FILE"), default=[])
    p.add_argument("--out", dest="outs", action="append", default=[], help="one per --pot; none = print (one --pot only)")
    p.add_argument("--lang", default=LANG)


def write_all(paths, texts):
    """Every output under a temporary name first, renamed only when all were written."""
    temps = []
    try:
        for path, text in zip(paths, texts):
            temps.append(path + ".tmp")
            with open(temps[-1], "wb") as handle:
                handle.write(text.encode("utf-8"))
        for temp, path in zip(temps, paths):
            os.replace(temp, path)
    except OSError as error:
        for temp in temps:
            try:
                os.unlink(temp)
            except OSError:
                pass
        raise PseudoError("cannot write the output: %s" % error)


def run(args):
    """-> the texts; writes the --out files when given. Raises PseudoError."""
    if args.outs and len(args.outs) != len(args.pot):
        raise PseudoError("%d --out for %d --pot" % (len(args.outs), len(args.pot)))
    if not args.outs and len(args.pot) != 1:
        raise PseudoError("printing needs exactly one --pot; give one --out per --pot")
    pct = contract_floor(args.contract)
    pos = {}
    for lang, path in args.po:
        pos.setdefault(lang, []).append(read(path))
    texts = generate([read(p) for p in args.pot], pos, args.source_lang, pct, args.lang)
    if args.outs:
        write_all(args.outs, texts)
    return texts


def emit(args, texts):
    if not args.outs:
        sys.stdout.buffer.write(texts[0].encode("utf-8"))
        sys.stdout.buffer.flush()


def handle(args):
    """`rigor ui-pseudo`: a refusal prints the house message and exits 2 (never a traceback)."""
    try:
        texts = run(args)
    except PseudoError as error:
        print("rigor: ui-pseudo: refused: %s" % error, file=sys.stderr)
        raise SystemExit(2)
    emit(args, texts)
    return 0


def add_parser(subparsers):
    parser = subparsers.add_parser("ui-pseudo", allow_abbrev=False,
                                   help="the pseudo-locale .po of a catalogue (P004 3.8, docs/ui-pseudo.md)")
    add_arguments(parser)
    parser.set_defaults(handler=handle)


def main(argv):
    """Entry of the Buck2 action: exit 0 = written, 2 = refused."""
    import argparse
    p = argparse.ArgumentParser(prog="ui_pseudo", allow_abbrev=False)
    add_arguments(p)
    args = p.parse_args(argv)
    try:
        texts = run(args)
    except PseudoError as error:
        print("ui_pseudo: refused: %s" % error, file=sys.stderr)
        return 2
    emit(args, texts)
    return 0
