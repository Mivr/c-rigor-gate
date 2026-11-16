# The identity checks of `ui-scene` (U24, P004 3.1)

What the scene IS, beside what it draws: the probe's scene identity (docs/ui-model.md, "Scene identity": the state
class of each state and, per scene node, its element id, msgid and formatted arguments) lets ui-scene judge the checks
below (`gate/rigor_lib/ui_judge_identity.py`; the contract tables `[[value]]`, `[[catalogue]]`, `[[identity_literal]]`
are `ui_contract_identity.py`'s, docs/ui-contract.md). Everything of docs/ui-judges.md about findings, exceptions,
`checks-examined`, `check-vacuous` and `check-blocked` applies; `raw-text`'s identity parts are described there.

## The checks

- **`required-element-missing`** (O2 + O3 + identity, U24). In a state whose identity names class C, every element id
  of C's `[[state_class]].required` that no DRAWN scene node IS. Which nodes are an element (`carries`): for a `[[role]]`
  id, the nodes whose typographic role (the gate's, from the style token) is it; for a structural role (`countdown`),
  the nodes of that scene role; for any other element id, the nodes the product tags with it. Drawn (`drawn`, fix-up 1:
  presence rests on what the gate observes, never on the product's claim alone): the node is not hidden by its scene
  flag `H`, it is associated with a rendered node, that node is shown (no hidden ancestor) with a non-empty visible box
  (cut by the display and its clip chain), and a text-bearing node (text, button, key, countdown) has a non-empty label
  that is the drawn one (no stage-text-mismatch). So a required element in the scene but hidden in LVGL, zero-sized,
  off-screen, empty or not drawn at all is missing. Identity `[C, element]`, target the element id; `observed.undrawn`
  the keys of the nodes that are the element but not drawn; the evidence records are the identity records and those
  nodes. A class with no `[[state_class]]` row is `contract-incomplete` (`state-class`, the class) and no verdict; an
  element only a node outside the scene vocabulary is tagged with gets no verdict (that node takes part in no check).
- **`value-split`** (O2 + O3 + identity, U24). For a `[[value]]` row, the DRAWN scene nodes that are its element (the
  same `carries` and `drawn` as above), when there are more than its `max_nodes` (1 when absent): identity
  `[value id]`, observed the sorted keys. A state with no such node is no verdict.
- **`identity-role-mismatch`** (O2 + identity, U24 fix-up 1, error). A node the product tags with a role id (a
  `[[role]]` id or a structural role) that is not the node's role as the gate reads it (the typographic role of its
  style, or its scene role): identity `[key]`, observed the tag, the typographic and the scene role. The tag is not
  taken for presence (the gate's role is). One verdict per node tagged with a role id; never `check-vacuous` (a
  product that tags no node with a role id gives it nothing to judge).
- **`state-class-unstable`** (identity, U24 fix-up 1, error, `state` null, identity `["unstable", key]`). The state
  class is the product's claim; one abstraction key whose identity named two classes in a run means the claim (or the
  key) does not describe the state. Reported once per key and further class.

## What the lockers adapter must emit

The real kiosk does not report identity yet: business-apps pins an older gate and its model adapter gains
`uim_identity_supported` / `uim_identity` in a product task. Until then its runs give `check-blocked` for
`required-element-missing` (the contract has `[[state_class]]` rows; it has no `[[value]]` or `[[catalogue]]` row, so
those two are not blocked: there is nothing to judge). What the adapter must emit, from `lockers.toml`:

- **The state line**: one of the `[[state_class]]` ids, the class of the screen or of the topmost message shown:
  `splash`, `welcome`, `choose_size`, `opened`, `report`, `lockout`, `inspection`, `startup_fault` (screens) and
  `dialog`, `snackbar`, `banner` (a message over a screen). The identity has ONE class per state, so a screen with a
  message over it is either the screen's class or the message's, and only that class's `required` is checked there: a
  known limit (a list of classes per state would need a second grammar change; reported, not done). The language, a
  countdown and the digits entered do not change the class.
- **Element ids** of the `required` lists, on the node that IS that element (from ui-look.md 3.2, 4.1, 6.1 and the
  ui-rules.md rows the provenance cites): `screen_headline` (the headline text, key 3 on Welcome), `subtitle` (4),
  `numpad` (the pad panel, 14), `language_switch` (the BG/EN panel, 9), `countdown` (the countdown text of a timed
  screen or message), `size_buttons` (the panel of the size choices), `cancel` (17), `hero_number` (the locker number),
  `body`, `done` (16), `report_title`, `staff_strong`, `staff_detail`, `notice_body` and `dismiss` (a message's text
  and its dismiss control). A container the lists name (`numpad`, `language_switch`, `size_buttons`) must be a semantic
  node of its own (9 and 14 are today). Fix-up 1: for the ids that are `[[role]]` ids (`screen_headline`, `subtitle`,
  `hero_number`, `body`, `report_title`, `staff_strong`, `staff_detail`, `notice_body`) and for `countdown` (a scene
  role), the gate decides which node is the element from the node's own role; the tag is checked against it
  (`identity-role-mismatch`) and is not needed for presence. Every required element must be DRAWN (associated, shown,
  a non-empty box and label), not only be in the scene.
- **The `[[element]]` ids** on their keys: `lang_bg` 11, `lang_en` 12, `code_echo` 13, `numpad_32` .. `numpad_43`
  (keys 32..43), `done` 16, `cancel` 17, `size_48` .. `size_53`, `released` 20, `licenses` 8. A node has ONE element id:
  the pad keys carry `numpad_<key>` and the pad panel `numpad`; the BG/EN buttons `lang_*` and their panel
  `language_switch`.
- **Value elements** (rows the owner would add: `[[value]] id = "locker_number", element = "hero_number"` and
  `[[value]] id = "entered_code", element = "code_echo"`): every node that draws a digit of the locker number carries
  `hero_number` (the F5 split: two nodes "8" and "2", both `hero_number`, is then `value-split`), and the echo of the
  entered code carries `code_echo`.
- **Msgids and arguments**: every catalogue text node its gettext msgid (the English source text of
  `lkui/catalog/i18n/*.pot`, byte for byte) and its formatted arguments (the countdown's `{0}`, the locker number, the
  digit count). The lockers catalogues are `source-text`: a `[[catalogue]]` row `msgids = "source-text"` (the owner's)
  turns on the `no-msgid` part for its `text_roles`; the label == msgid part stays blocked on U17b.

