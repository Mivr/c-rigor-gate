set -eu
sed -i 's/^    return ramp;/    ramp[count] = 0;\n    return ramp;/' util/util.c
grep -q 'ramp\[count\]' util/util.c
