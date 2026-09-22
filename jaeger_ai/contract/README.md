# contract — facts more than one layer has to agree on

If two parts of Jaeger both need to know something, that something is defined
**here, once**, and imported. It is never re-typed and never re-derived.

## Why this folder exists

Every bug that motivated it looked the same: two files each held a copy of one
fact, the copies drifted, and nothing failed loudly. Both files still looked
correct. The code still ran. Only the behaviour was wrong.

- A dead `ports.py` said `ANIMATION_BRIDGE_DEFAULT_PORT = 9999` while the live
  one said `8765`. One name, two answers, no way to tell which you imported.
- The framework table was re-derived in **eight** places, including once in
  JavaScript. Two disagreed, and a click on "OpenClaw" reached Hermes.

## What's in here

| File | The fact it owns |
| :--- | :--- |
| `frameworks.py` | The four backends a turn can run on, and every name each answers to — runtime, WebUI profile, display name, agent id, container. |
| `ports.py` | The default port for each service. |
| `model_ids.py` | The `@lane:model` picker id grammar, and the bare model name a provider accepts. |

## The one rule

**This package imports nothing from the rest of `jaeger_ai`.** That is what
makes it safe for anything to import, and it is load-bearing — the moment
`contract` depends on a layer above it, you get import cycles, and the
constants migrate back out to the places they came from.

## Where the line is

`jaeger_os.contract` (in `packages/jaeger-os/`) owns the **engine's** wire
truth: bus topics, the NDJSON client protocol and its cross-language fixtures,
hardware ports. This package owns the **application's** facts.

Engine facts go there. Application facts go here. Copying one into the other is
what produced the 9999-vs-8765 split, and `dev/tests/jaeger_ai/contract/` now
fails if it happens again.

## Adding a fact

1. Put it here with a comment saying what breaks if it drifts.
2. Delete every other copy and import this one.
3. Add a test in `dev/tests/jaeger_ai/contract/` asserting the old copies still
   agree — that test is the thing that keeps this folder honest.
