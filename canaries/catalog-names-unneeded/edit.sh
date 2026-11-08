set -eu
cp -r "$CANARY_DIR/../_catalog/files/." .
# an override for a msgid whose derived name collides with nothing: a free-form rename.
sed -i 's|names = {"hello!": "HELLO_BANG"}|names = {"hello!": "HELLO_BANG", "Locker {0}": "LOCKER_X"}|' cat/BUCK
