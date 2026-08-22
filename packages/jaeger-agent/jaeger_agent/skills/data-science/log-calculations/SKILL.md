---
name: log-calculations
description: "Compute statistics or numbers out of a log/data file — 'average response time in this log', 'how many errors yesterday', 'sum the second column', 'p95 of these numbers'. Load this whenever a question needs parsing structured/semi-structured text into numbers, not simple arithmetic (use `calculate` for that)."
version: 1.0.0
platforms: [linux, macos, windows]
requires_tools: [read_file, search_files, execute_code]
requires_toolsets: [files]
metadata:
  jros:
    tags: [logs, calculations, numpy, statistics, parsing, execute_code]
    category: data-science
    related_skills: [process-monitoring, web-research]
---

# LOG CALCULATIONS — PARSE -> EXECUTE_CODE

The pattern: get the raw text with a read tool, then do the actual math
in `execute_code` (numpy is available there) — never hand-count or
mentally-average a log by eye, and never use `calculate` for anything
beyond a single expression (it can't parse a file).

## THE TOOLS (exact)
```
read_file(path="...", offset=0, limit=None)         whole/paged file
search_files(query="...", path="...", max_results=50)   grep matching lines first (large files)
execute_code(code="...", timeout_s=10.0)              parse + compute with numpy
```

## SOP

1. **Locate + narrow.** Know the exact path. For a large file or a
   specific pattern (errors, a date range, a status code), `search_files`
   first to pull just the matching lines instead of reading everything.
2. **Read.** `read_file` the target (or the `search_files` matches are
   often already enough — check before re-reading the whole file).
3. **Compute in `execute_code`.** Paste/reference the text into the code
   you write, parse it (split lines, regex, `csv` module, whatever the
   format needs), extract the numeric field(s), then use `numpy` for the
   actual statistics — mean, sum, percentile, stddev. Print the result
   so it comes back in `stdout`.
4. State the numeric answer plainly, plus the sample size ("across 214
   matching lines") so the user can judge whether it's a solid stat.

## WORKED EXAMPLE

Question: "what's the average response time in this log, and the p95?"

```
read_file(path="workspace/access.log", limit=5)   # peek at the format first
```
Say the format is `... response_time_ms=123 ...` per line.

```
search_files(query="response_time_ms=", path="workspace/access.log", max_results=5000)
```
(If the file is small, skip straight to `read_file` on the whole thing
instead — don't `search_files` a 200-line file, that's just `read_file`
with extra steps.)

```
execute_code(code='''
import re, numpy as np

with open("workspace/access.log") as f:
    text = f.read()

times = [int(m) for m in re.findall(r"response_time_ms=(\\d+)", text)]
print(f"n={len(times)}")
print(f"mean={np.mean(times):.1f}ms")
print(f"p95={np.percentile(times, 95):.1f}ms")
print(f"max={np.max(times)}ms")
''')
```

Read the `stdout` back and report: "Across 4,812 requests, mean response
time was 118.3ms, p95 was 340.0ms, max 2,110ms."

## ERROR HATCH

- Regex/parse finds 0 matches -> `read_file(limit=10)` again and look at
  the ACTUAL format before assuming the data isn't there; a wrong field
  name/format is the far more common cause than an empty log.
- File too large for one `read_file` -> page it with `offset`/`limit`,
  or better, `search_files` down to just the relevant lines first.
- `execute_code` times out -> the file is likely huge; narrow with
  `search_files`/a line-count check before re-running the full parse.
- Numbers look implausible (e.g. p95 > max, mean way outside the
  observed range) -> that's a parsing bug, not a data anomaly; re-check
  the regex/field extraction before reporting the number.

## EVAL EXAMPLES

| User ask | Expected chain |
|---|---|
| "average response time in access.log" | read_file (peek format) -> execute_code (regex + np.mean) |
| "how many ERROR lines yesterday" | search_files (grep ERROR) -> execute_code (date filter + count), or count directly if search_files result IS the count |
| "p95 of the numbers in this CSV" | read_file -> execute_code (csv/regex parse + np.percentile) |
| "what's 15% of 340" | calculate (NOT this skill — no file involved) |

## DONE WHEN

The reported number(s) came from an actual `execute_code` run over the
real file contents this turn (not eyeballed or estimated), with the
sample size stated alongside the stat.
