set -eu
# T089: a binary whose writable static data (64 bytes of `bss`) is one byte over its RAM budget (63).
# The module may hold mutable data (policy), so `mutable-data` is quiet: only the budget fails.
mkdir app
cat > app/BUCK <<'BUCK'
load("@gate//rules:c.bzl", "c_binary")

c_binary(name = "app", srcs = ["app.c"])
BUCK
cat > app/app.c <<'C'
static volatile unsigned char mem[64];

int main(void) {
    mem[0] = 1;
    return mem[0] == 1 ? 0 : 1;
}
C
