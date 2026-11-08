set -eu
cp -r "$CANARY_DIR/../_catalog/files/." .
# bg drops the {0} of "Locker {0}" in both pots.
sed -i 's/Shkafche {0}/Shkafche/' cat/a.bg.po cat/b.bg.po
