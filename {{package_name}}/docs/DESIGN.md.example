# {{package_name}} — design notes

Copy to `DESIGN.md` (drop the `.example` suffix) once this module has a
real shape. This is the module's own design doc — decisions, tradeoffs,
and "why" that don't belong in code comments but also don't belong in the
repo-level `dev/docs/` tree (that tree is for the *repo's* history/
roadmap/vision; this one is scoped to this single module).

## What this module does

Replace with a real one-paragraph description. Follow CONVENTIONS.md's
"no spec ahead of code" rule — don't describe behavior that isn't
implemented yet; mark anything aspirational `(planned)`.

## Why it's shaped this way

- **Slot:** why this module fills the slot it does, and whether the slot
  is one-module or multi-module (ANY-OF readiness) in this project.
- **Topics:** why `consumes`/`produces` are what they are in `module.yaml`
  — what's the request/ack shape, and why (if applicable) work is queued
  in `tick()` rather than done inline in the subscriber callback.
- **Dependencies:** what's in `requires_libraries`/`requires_platform`
  and why — is any of it optional-degrade (available: false when
  missing) vs. hard-required.

## Open questions / known gaps

Track anything unresolved here rather than letting it rot as a TODO
comment nobody revisits. Move resolved items to
`dev/docs/reality/STATUS.md` at the repo root once they land.
