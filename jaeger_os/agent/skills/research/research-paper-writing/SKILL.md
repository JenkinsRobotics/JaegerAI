---
name: research-paper-writing
description: "End-to-end pipeline for publication-ready ML/AI papers (NeurIPS, ICML, ICLR, ACL, AAAI, COLM). Load this to design/run experiments, draft or revise any section, verify citations, self-review, or prep a submission or rebuttal."
version: 1.2.0
platforms: [linux, macos]
requires_tools: [terminal, execute_code, read_file, write_file, patch, append_file, web_search, web_extract, todo, memory, use_skill, list_skills, start_background, check_background, schedule_prompt, delegate_task]
metadata:
  jros:
    tags: [research, paper-writing, experiments, latex, citations, statistics]
    category: research
    related_skills: [arxiv, subagent-driven-development, plan, data-science]
---

# RESEARCH PAPER WRITING PIPELINE

Iterative loop (NOT linear): results trigger new experiments; reviews trigger new
analysis. This SKILL.md is the router. Each phase below is a summary — load the
matching reference file for full step-by-step detail.

## WHEN TO USE
- Starting a paper from a codebase or idea; designing/running experiments for claims.
- Writing or revising any section; converting between conference formats.
- Verifying citations; self-review; responding to reviews; submission prep.
- Non-empirical papers (theory, survey, benchmark, position) or human evaluations.

## TOOLS (real JROS names — never invent one)
- `terminal(...)` — LaTeX (`latexmk -pdf`), git, ps/tail/ls, launch scripts.
- `execute_code(...)` — citation verification, stats, aggregation (Python).
- `start_background(...)` / `check_background(id=…)` / `pending_background()` — experiments that outlive the turn.
- `read_file(...)` / `write_file(...)` / `patch(...)` / `append_file(...)` — paper + result files.
- `web_search(...)` then `web_extract(url=…)` — literature discovery + verification.
- `todo(action=…)` + `memory(action=…)` — cross-session state.
- `schedule_prompt(cron=…, prompt=…)` — periodic monitoring / deadline pings.
- `use_skill(name=…)` to load a companion; `list_skills(action="view", name=…)` to browse it.
- Full tool map + patterns: `read_file("references/jros-tooling.md")`.

## CORE PRINCIPLES
1. Be proactive: deliver complete drafts, then iterate. Don't stall on questions.
2. NEVER hallucinate citations (~40% error rate). Fetch programmatically; mark gaps `[CITATION NEEDED]`.
3. A paper is a story with ONE contribution stated in one sentence.
4. Every experiment must name the claim it supports. No orphan experiments.
5. Commit early and often — the git log is your experiment history.

## PHASED SOP
Full detail for every phase (commands, formulas, code): `read_file("references/pipeline-detailed.md")`.

- **Phase 0 — Setup.** Explore repo, lay out `workspace/{paper,experiments,code,results,tasks}`, git init, name the one-sentence contribution, seed `todo`, estimate compute budget. Optionally `use_skill(name="plan")`.
- **Phase 1 — Literature review.** Seed papers → breadth-first `web_search` rounds → `web_extract` key papers → verify EVERY citation programmatically. Depth: `read_file("references/citation-workflow.md")`; helper: `use_skill(name="arxiv")`.
- **Phase 2 — Experiment design.** Map each claim to an experiment, design fair baselines, define the eval protocol, write runner scripts. Human eval? `read_file("references/human-evaluation.md")`. Patterns: `read_file("references/experiment-patterns.md")`.
- **Phase 3 — Execution & monitoring.** Launch (use `start_background` for long runs), monitor, handle failures, commit each completed batch, keep an experiment journal.
- **Phase 4 — Analysis.** Aggregate results, compute significance (error bars, seeds, tests), identify the story, build figures/tables, decide more-experiments-vs-write. Iterative refinement / autoreason: `read_file("references/autoreason-methodology.md")`.
- **Phase 5 — Drafting.** Title → abstract (5-sentence formula) → Figure 1 → intro (≤1.5pp) → methods → experiments → related work → limitations (REQUIRED) → conclusion → appendix → ethics/broader-impact. Style: `read_file("references/writing-guide.md")`. LaTeX preamble, siunitx, subfigures, algorithm2e, TikZ, latexdiff, SciencePlots, templates + page budget: all inside `references/pipeline-detailed.md` (Phase 5).
- **Phase 6 — Self-review & revision.** Simulate an ensemble of reviewers, VLM visual pass, claim-verification pass, prioritize, revise, write rebuttal. Criteria + rebuttal template: `read_file("references/reviewer-guidelines.md")`.
- **Phase 7 — Submission.** Conference checklist, anonymization, formatting, pre-compile validation (`chktex`, cite/figure/label checks), final clean build, arXiv strategy, code packaging. Checklists: `read_file("references/checklists.md")`.
- **Phase 8 — Post-acceptance.** Poster, talk/spotlight, blog/social. Also: workshop & short papers, and non-empirical paper types — `read_file("references/paper-types.md")`.

## STATE OFFLOADING (mandatory once past a couple of steps)
- `todo(action="add"/"update"/"list")` for the task plan; `memory(action="add")` for the contribution framing, venue, and reviewer feedback.
- Write results and the experiment journal to files (`append_file`/`write_file`), never hold them only in context.
- Session startup: `todo(action="list")` → `memory(action="read")` → `git log --oneline -10` → check running/`pending_background()` → `ls results/`. See `references/jros-tooling.md`.

## ERROR HATCH
- LaTeX won't compile: run `chktex` and read the FIRST error only; fix undefined refs/citations by re-running `bibtex` + two `pdflatex` passes. If it fails twice, `read_file("references/pipeline-detailed.md")` LaTeX error checklist.
- Citation won't verify twice: mark it `[CITATION NEEDED]` and move on — never fabricate BibTeX.
- Parallel drafting: `delegate_task(["draft section X: …", "draft section Y: …"])` fans
  sections out to fresh sub-agents (max 2 concurrent; turns serialize). Or draft
  sequentially / offload long jobs to `start_background`.

## DONE WHEN
A compiling PDF that states one contribution in one sentence, every claim backed by an
experiment with significance reported, every citation verified (no `[CITATION NEEDED]`
left), required sections present (limitations + broader-impact), the venue checklist
passed, and the work committed to git.

## REFERENCE MAP
- `references/pipeline-detailed.md` — full step-by-step for all phases + LaTeX recipes.
- `references/jros-tooling.md` — real JROS tool map, monitoring/scheduling patterns, companion skills.
- `references/citation-workflow.md` · `references/experiment-patterns.md` · `references/autoreason-methodology.md` · `references/human-evaluation.md` · `references/writing-guide.md` · `references/reviewer-guidelines.md` · `references/checklists.md` · `references/paper-types.md` · `references/sources.md`
- `templates/` — NeurIPS 2025, ICML 2026, ICLR 2026, ACL, AAAI 2026, COLM 2025. See `templates/README.md`.
