set -eu
F="$CANARY_DIR/../_fuzz/files"
mkdir parse
cp "$F/parse.h" parse/parse.h
cp "$F/fixed.c" parse/parse.c
cp "$F/fz_nocall.c" parse/fz_fuzz.c
cp "$F/BUCK" parse/BUCK
