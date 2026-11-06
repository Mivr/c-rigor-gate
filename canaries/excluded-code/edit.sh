set -eu
mkdir -p core/docs
printf 'int hidden_one(void) { return 1; }\n' > core/docs/hidden.c
