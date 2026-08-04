# dev/docs/ — the doc map

Mirrors JaegerOS's own `dev/docs/` layout in miniature. Four buckets,
each with a different job — don't mix content across them:

| Dir | What goes here |
|---|---|
| [`reality/`](reality/) | **What's true right now.** `STATUS.md` is the one doc a new contributor (human or agent) reads to get current truth without archaeology through commit history. See `CONVENTIONS.md` → "STATUS stays truthful": any commit that changes behavior updates it in the same commit. |
| [`history/`](history/) | **What happened, in order.** Per-release or per-milestone write-ups — the record of decisions made and why, kept even after the code around them changes. Append-only in spirit. |
| [`roadmap/`](roadmap/) | **What's planned, not yet built.** Anything here is explicitly `(planned)` — see `CONVENTIONS.md` → "No spec ahead of code." When an item ships, move its description to `reality/` (or delete it if `reality/STATUS.md` already covers it) rather than leaving two copies of the truth. |
| [`vision/`](vision/) | **Why, at the highest altitude.** The north-star documents — architecture, positioning, the thing every "where does this go" question gets tested against. Changes rarely; when it does, it's a deliberate ratified decision, not a drive-by edit. |

Module-scoped design notes (a single module's own tradeoffs) live beside
the module instead — `src/{{package_name}}/docs/DESIGN.md` — not here.
This tree is repo-scoped.
