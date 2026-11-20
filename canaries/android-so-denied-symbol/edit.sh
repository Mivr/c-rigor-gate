set -eu
cat >> core/BUCK <<'EOT'

c_android_so(name = "club", srcs = ["club.c"], exports = ["ANativeActivity_onCreate"])
EOT
sed -i 's/^load("@gate\/\/rules:c.bzl", "c_library", "c_test")$/load("@gate\/\/rules:c.bzl", "c_android_so", "c_library", "c_test")/' core/BUCK
printf '#include <stdlib.h>\n\nvoid ANativeActivity_onCreate(void *activity, void *saved, unsigned long n) {\n    (void)activity;\n    (void)saved;\n    (void)n;\n    (void)getenv("HOME");\n}\n' > core/club.c
grep -q 'getenv' core/club.c
