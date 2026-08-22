---
name: file-organization
description: "Organize, move, copy, rename, or clean up files — 'move my screenshots to a folder', 'copy this to backups', 'clean up my downloads', 'rename these files', 'find and organize X'. Load this for any file-tidying task; it hands you the safe list -> confirm -> move pattern and the exact sandbox boundaries."
version: 1.0.0
platforms: [linux, macos, windows]
requires_tools: [move_file, copy_file, search_files, list_skill_dir]
requires_toolsets: [files]
metadata:
  jros:
    tags: [files, organization, move, copy, cleanup, sandbox]
    category: productivity
    related_skills: [process-monitoring]
---

# FILE ORGANIZATION — MOVE / COPY / CLEAN UP

`move_file(src, dst)` and `copy_file(src, dst)` do the actual work
(`shutil.move` / `shutil.copy2` under the hood). Both are WRITE_LOCAL
tier — every call is audited and git-autocommitted like any other write.

## THE TOOLS (exact)
```
list_skill_dir(path=".")                       list a directory (no path = workspace)
search_files(query="...", path=".", max_results=50)   grep file CONTENTS, not names
move_file(src="...", dst="...")                move/rename (tier: write)
copy_file(src="...", dst="...")                copy (tier: write)
```

## SANDBOX BOUNDARIES (read before touching anything)

Both `src` and `dst` are resolved the SAME way `write_file` resolves a
path: `workspace/...` (or a path that's already absolute inside the
instance) stays where it is; anything else routes under the instance's
`skills/` sandbox. A `src` OR `dst` that tries to escape the sandbox is
refused, and the error names which side failed. This means:

- You can reorganize freely WITHIN the instance's writable area
  (workspace/ and skills/).
- You CANNOT use `move_file`/`copy_file` to reach arbitrary system
  paths (Desktop, Downloads, external drives) the way `read_file` /
  `list_skill_dir` can read them. If the user's "screenshots" or
  "downloads" live outside the sandbox, `list_skill_dir`/`search_files`
  can still LIST/READ them (unsandboxed), but moving/copying them is a
  job for `terminal(command="mv ...")` — tier-4 PRIVILEGED, a much
  heavier confirmation, and outside this skill's scope. Say so rather
  than silently downgrading to a shell command without flagging it.
- A path escape error is not a bug to route around — it's the tool
  correctly refusing to touch something outside its remit.

## THE SAFE PATTERN — LIST -> CONFIRM -> MOVE

Never move/copy files sight-unseen from a vague instruction ("clean up
my downloads"). Always:

1. **List** — `list_skill_dir(path=...)` (or `search_files` if the user
   named content/a pattern, not just a location) to see what's actually
   there.
2. **Confirm** — state the exact file(s) and the exact destination
   before acting, when the request is broad/plural/ambiguous ("move my
   screenshots" could mean 3 files or 300). A precise single-file
   request ("move report.pdf to workspace/archive") doesn't need a
   confirmation round-trip — the destination write-tier prompt IS the
   confirmation gate; just be sure `src` unambiguously names one file.
3. **Move** — `move_file`/`copy_file` per file. For a batch, do them
   one at a time and track which succeeded — don't assume a batch is
   all-or-nothing.
4. Report exactly what moved where, including any that failed (sandbox
   refusal, not found) — don't summarize a partial batch as "done."

## ERROR HATCH

- `move_file`/`copy_file` returns a sandbox-escape error -> that path is
  outside the writable area; tell the user (don't retry with a
  "fixed" path unless they gave you one inside workspace/skills).
- Destination already has a file with that name -> default to NOT
  overwriting silently; ask, or pick a non-colliding name, unless the
  user explicitly said to overwrite/replace.
- "Move" vs "copy" — if the user's wording is genuinely ambiguous and
  the source is something they'd miss if it vanished (not a duplicate,
  not disposable), prefer `copy_file` and mention you kept the
  original, or just ask.

## EVAL EXAMPLES

| User ask | Expected chain |
|---|---|
| "move my screenshots to a folder" | list_skill_dir/search_files first, THEN move_file per file |
| "copy report.pdf to workspace/archive" | copy_file directly (single unambiguous file) |
| "move ~/Desktop/foo.png into my project" | sandbox check — Desktop path likely escapes; explain, offer terminal(mv) as the alternative with its own (heavier) confirmation |
| "clean up my downloads" | list first — this is exactly the broad/ambiguous case that needs a look before acting |

## DONE WHEN

Every requested file is confirmed moved/copied (`move_file`/`copy_file`
returned success) and the user was told the exact before/after
locations — including any file that was refused or skipped, not just
the successes.
