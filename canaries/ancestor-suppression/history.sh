set -eu
# The suppression is committed in an ancestor of the graded range: the diff scan (base..head) never sees it.
git config user.name canary
git config user.email canary@example.invalid
printf '\n/* NOLINT */\n' >> core/core.c
git add -A
git commit -q -m "ancestor: suppression before base"
GRADED_BASE=$(git rev-parse HEAD)
printf '\n/* harmless */\n' >> core/core.c
git add -A
git commit -q -m "ancestor-suppression"
echo "$GRADED_BASE $(git rev-parse HEAD)"
