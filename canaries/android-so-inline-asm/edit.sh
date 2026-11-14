set -eu
cat >> core/BUCK <<'EOT'

c_android_so(name = "club", srcs = ["club.c"], exports = ["ANativeActivity_onCreate"])
EOT
sed -i 's/^load("@gate\/\/rules:c.bzl", "c_library", "c_test")$/load("@gate\/\/rules:c.bzl", "c_android_so", "c_library", "c_test")/' core/BUCK
printf 'void ANativeActivity_onCreate(void *activity, void *saved, unsigned long n) {\n    (void)activity;\n    (void)saved;\n    (void)n;\n    __asm__ volatile("nop");\n}\n' > core/club.c
grep -q nop core/club.c
