set -eu
F="$CANARY_DIR/../_fuzz/files"
mkdir parse
cp "$F/parse.h" parse/parse.h
cp "$F/fixed.c" parse/parse.c
cp "$F/BUCK.lib" parse/BUCK
