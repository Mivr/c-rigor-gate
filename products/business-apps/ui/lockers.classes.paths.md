# `lockers.classes.paths.json`: the kiosk's screen-class paths (DRAFT, unsigned)

**Status: a DRAFT, not sealed, not signed.** Nothing in the gate grades with it; it is the input of the U09 evidence
run (docs/ui-lockers-first-run.md, "ui-time on the class paths") and of its loader test
(`gate/tests/test_ui_lockers_classes.py`). The owner may seal or reject it.

**Provenance.** Copied byte for byte (U09) from `/var/tmp/cache/boot/lockers-classes.paths.json`, which the product's
adapter task produced and tested: business-apps `docs/lockers/ui-model.md`, "Reaching every screen class by a path"
(U04g; business-apps checkout `3e8c46e`), written as gate path words of the draft catalogue
`lockers.events.toml` (its event words and the path words `open` and `at`). sha256
`b9b2a7b700d80b33d0682b4e07b6a58d9f4cea1063858686d23ec23beccdd0f1` (the loader test checks it, so an edit is seen).

29 paths (`ui-explore-paths/1`, no criteria), one per row of that table, in its order: the splash; Welcome with the
self-test banner (bg, en); Welcome (bg, en); Welcome with four digits (bg, en); the "code not recognised" dialog
(bg, en); Choose size (bg, en); opened (bg, en, also under a hanging relay); the reservation-saved snackbar path (bg,
en); the codes-offline banner (bg, en); the three banners after 300 s (bg, en); the report (bg, en); the two startup
faults; the lockout (bg, en); the inspection (bg, en). The table's `advance T` is the path word `at T - 1000` (the
origin is 1000).
