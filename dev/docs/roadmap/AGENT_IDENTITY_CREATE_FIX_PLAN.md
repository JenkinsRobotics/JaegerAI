# Agent identity through the create flow — operator contract + fix plan

> subagent-driven; from the 2026-07-09 two-person fresh-install walk (the
> lilith/anakin mismatch). Moves to history/ when shipped.

**Operator contract:**
1. The instance DIR NAME is the fixed instance ID (already the universal key;
   no UUID project). `identity.yaml:name` is the freely-changeable AGENT NAME —
   the ONLY name the agent ever refers to itself by.
2. Characters are prompt/voice presets. After the character-selection page,
   the character's name appears nowhere except the review page's clearly-
   labeled "Character preset" row (so a name/preset mismatch is visible).
3. Wizard name field = agent name; DEFAULT = CLI-passed name if given, else
   the selected character's name; always editable; never empty.
4. Docs/help teach bare `./jaeger agent create` (name = documented option).

**Root cause (mapped, file:line in the recon):** `_launch_swift_app` pins
`JAEGER_INSTANCE_NAME` (main.py:3610) but onboarding never reads it;
`OnboardingAnswers.select` sets displayName = character.name
(OnboardingFlow.swift:72-76); `commandArgs()` (OnboardingFlow.swift:80-99)
NEVER sends `name`, so `create_instance` (setup_wizard.py:872) dirs the
instance as `slug(character-name)`. Result: dir `anakin-skywalker`,
identity "Anakin Skywalker", CLI's `lilith` orphaned in the env pin — and
main.py:1925's name-protection framing can't fire (names match).

---

### Task 1 — thread the name end-to-end (Python + Swift, one wire)

1. **Expose the pin to onboarding:** the bridge already emits the fatal
   `no_instance` frame (bridge.py:670-676) that opens OnboardingWindow. Add
   the pinned name to the onboarding data path (e.g. a `suggested_name` field
   on that frame or on the catalog/setup-defaults command the flow already
   calls — read the flow, pick the existing seam; protocol change = v1-additive
   field, update protocol.py + fixtures like the 0.7.2 `detail` precedent).
2. **Swift:** seed `OnboardingAnswers.displayName` from `suggested_name` when
   present; character selection sets displayName ONLY if it's empty/untouched
   (pin wins over preset; user edit wins over both). `commandArgs()` sends
   `name`: the pinned name verbatim when given, else `slug(displayName)` is
   fine server-side — just send the user-visible name and let
   `create_instance` slug the dir as it already does.
3. **IdentityStep copy:** subtitle stops echoing the character ("Prefilled
   from {character.name}" → "The agent's name — how it refers to itself.").
4. **ReviewStep:** row order/labels: `Agent name: <displayName>` (prominent,
   first) · `Instance ID: <slug>` (the fixed dir, small/dim) · `Character
   preset: <character.name>` (explicitly labeled as preset). The mismatch your
   coworker hit must be VISIBLE here.
5. **TUI wizard parity** (setup_wizard.py:413-416): same default order
   (CLI name → character → editable).
6. **Never-empty guarantee:** `create_instance` enforces identity.name
   non-empty (fallback: character display name, then "Jaeger").

### Task 2 — docs/help truth-up

`README.md:148` → bare `./jaeger agent create` (name shown as an option:
`./jaeger agent create --name ted` in the options table, not the headline);
check :135/:210 stay bare; `_print_agent_usage` (instance_verbs.py:90-96) +
`_print_setup_usage` (:48-64) reworded to the new contract ("name = the
agent's name; wizard defaults to your character pick when omitted");
install.sh next-steps already bare (verify). GitHub pages dir if present —
grep for `agent create lilith` everywhere.

### Walk-the-flow gate (MANDATORY — this is wizard work)

Scripted walks (no GUI click-through available headlessly; state what wasn't
walked): (a) `create_instance` direct: CLI-name+different-character → assert
dir=cli-slug, identity.name=cli-name, manifest bound_character=character, and
main.py's framing FIRES (agent_name != character.name); (b) no name +
character → dir=slug(character), identity.name=character-name, framing
correctly silent; (c) empty display name → fallback applied, never empty.
Swift: build-app.sh --dev green + protocol fixture suites (both languages)
green with the additive field. Boot smoke: footer agent_name == identity
name. Report which surfaces were walked vs inspected (the GUI click-through
itself is the operator's next fresh-install walk).

### Gates
Per-dir suites; Swift build + fixture parity suites; NO bench needed
(prompt fragments untouched — identity_name fragment unchanged; note it).
