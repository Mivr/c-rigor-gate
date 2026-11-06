set -eu
printf 'def helper():\n    pass\n' > core/helper.bzl
printf '\nload("//core:helper.bzl", "helper")\n' >> core/BUCK
