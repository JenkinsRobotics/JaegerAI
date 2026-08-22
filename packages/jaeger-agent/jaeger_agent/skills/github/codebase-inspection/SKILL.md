---
name: codebase-inspection
description: "Count lines of code, language breakdown, and code-vs-comment ratios of a repo with pygount — load this when the user asks how big a codebase is, wants a LOC count, language ratios, or repo composition."
version: 1.1.0
platforms: [macos, linux, windows]
requires_tools: [terminal]
metadata:
  jros:
    tags: [loc, code-analysis, pygount, codebase, metrics, repository]
    category: github
    related_skills: [github-repo-management]
---

# CODEBASE INSPECTION (pygount)

Measure a repo: lines of code, language breakdown, file counts, code-vs-comment
ratios. All commands run through the `terminal` tool.

## WHEN TO USE
- "How big is this repo / how many lines of code?"
- Language breakdown or code-vs-comment ratio of a project.
- Repo size / composition questions.

## TOOLS
- `terminal(command="...")` — run every pygount / pip / shell command below.
- `write_file(path, content)` — only if the user wants the report saved.

## SETUP
```
terminal(command="pip install --break-system-packages pygount 2>/dev/null || pip install pygount")
```

## SOP

### 1. Basic summary (do this first — the most common ask)
```
terminal(command="cd /path/to/repo && pygount --format=summary --folders-to-skip='.git,node_modules,venv,.venv,__pycache__,.cache,dist,build,.next,.tox,.eggs,*.egg-info' .")
```
ALWAYS pass `--folders-to-skip`. Without it pygount crawls dependency/build
trees and hangs on large repos.

### 2. Tune the exclusions to the project type
```
# Python:      --folders-to-skip='.git,venv,.venv,__pycache__,.cache,dist,build,.tox,.eggs,.mypy_cache'
# JS/TS:       --folders-to-skip='.git,node_modules,dist,build,.next,.cache,.turbo,coverage'
# Catch-all:   --folders-to-skip='.git,node_modules,venv,.venv,__pycache__,.cache,dist,build,.next,.tox,vendor,third_party'
```

### 3. Filter by language (optional)
```
terminal(command="pygount --suffix=py --format=summary .")          # Python only
terminal(command="pygount --suffix=py,yaml,yml --format=summary .")  # Python + YAML
```

### 4. Detail or JSON (optional)
```
terminal(command="pygount --folders-to-skip='.git,node_modules,venv' .")            # per-file
terminal(command="pygount --format=json --folders-to-skip='.git,node_modules' .")   # programmatic
```

## READING THE SUMMARY
Columns: Language | Files | Code | Comment | %.
Pseudo-languages: `__empty__` empty files, `__binary__` binaries,
`__generated__` auto-generated, `__duplicate__` identical content,
`__unknown__` unrecognized.

## PITFALLS
- No `--folders-to-skip` → pygount hangs on node_modules/.git. Non-negotiable.
- Markdown reports 0 code lines — pygount counts all Markdown as comments. Expected.
- JSON files under-count code — use `terminal(command="wc -l file.json")` for exact lines.
- Huge monorepo → target languages with `--suffix` instead of scanning everything.

## ERROR HATCH
If pygount hangs or errors twice, fall back to a raw count:
`terminal(command="find . -name '*.py' -not -path './.git/*' | xargs wc -l | tail -1")`.

## DONE WHEN
You have reported the language breakdown (files + code lines per language) and
the total LOC for the repo the user named.
