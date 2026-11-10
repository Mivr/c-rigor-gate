set -eu
F="$CANARY_DIR/../_fuzz/files"
mkdir parse
cp "$F/parse.h" parse/parse.h
cp "$F/bug.c" parse/parse.c
cp "$F/fz_call.c" parse/fz_fuzz.c
cp "$F/BUCK" parse/BUCK
