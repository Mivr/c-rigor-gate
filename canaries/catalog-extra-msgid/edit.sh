set -eu
cp -r "$CANARY_DIR/../_catalog/files/." .
# the bg po carries a msgid its pot does not have.
printf '\nmsgid "Stale"\nmsgstr "Stara"\n' >> cat/a.bg.po
