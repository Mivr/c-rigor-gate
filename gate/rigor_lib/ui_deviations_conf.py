"""`ui_deviations_conf`: invisible and look-alike characters (docs/ui-deviations.md "Confusables").

`fold(text)` removes the invisible format characters (zero width spaces and joiners, bidi controls, soft hyphen, BOM), applies
NFKC (fullwidth and small forms become ASCII) and maps the Cyrillic and Greek letters that look like Latin ones. A comment line
that would be a heading or hold a tag only after folding is `deviation-malformed` (`why=confusable`).
"""

import unicodedata

# (look-alike, Latin) pairs: Cyrillic and Greek letters of the same shape as a Latin one, both cases.
_PAIRS = (
    "аa еe оo рp сc уy хx іi јj ѕs ӏl ԁd ԛq ԝw "
    "АA ВB ЕE КK МM НH ОO РP СC ТT ХX ІI ЈJ ЅS "
    "οo νv ιi ρp αa εe υu κk ΑA ΒB ΕE ΖZ ΗH ΙI "
    "ΚK ΜM ΝN ΟO ΡP ΤT ΥY ΧX"
).split()
TABLE = {ord(pair[0]): pair[1] for pair in _PAIRS}


def fold(text):
    kept = "".join(c for c in text if unicodedata.category(c) != "Cf")
    return unicodedata.normalize("NFKC", kept).translate(TABLE)
