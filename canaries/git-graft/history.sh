set -eu
git checkout -q -b side
mkdir -p docs && echo evil > docs/evil.txt
git add -A && git commit -q -m side
S=$(git rev-parse HEAD)
git checkout -q main
mkdir -p docs && echo evil > docs/evil.txt
git add -A && git commit -q -m evil
E=$(git rev-parse HEAD)
printf '\n/* change */\n' >> core/core.c
git add -A && git commit -q -m head
H=$(git rev-parse HEAD)
echo "$E $S" > .git/info/grafts
[ "$(git merge-base "$S" "$H")" = "$S" ] || { echo "fixture is not armed: the graft did not move the merge-base" >&2; exit 1; }
echo "$S $H"
