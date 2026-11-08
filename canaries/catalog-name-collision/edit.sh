set -eu
cp -r "$CANARY_DIR/../_catalog/files/." .
# two different msgids that name the same enum constant.
printf 'msgid "hello"\nmsgstr ""\n\n' >> cat/a.pot
printf '\nmsgid "hello"\nmsgstr "zdrasti"\n' >> cat/a.bg.po
