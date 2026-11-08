set -eu
cp -r "$CANARY_DIR/../_catalog/files/." .
# bg loses a translation: the msgstr of "Hello" is empty.
python3 - <<'PY'
p = "cat/a.bg.po"
s = open(p, encoding="utf-8").read()
open(p, "w", encoding="utf-8").write(s.replace('msgstr "Здравей"', 'msgstr ""'))
PY
