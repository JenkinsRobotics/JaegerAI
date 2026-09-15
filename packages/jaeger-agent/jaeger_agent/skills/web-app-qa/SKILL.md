---
name: web-app-qa
description: 'Exploratory QA of a web app: drive it in a browser, find bugs, capture
  evidence, write a report. Load this for ''test / QA / find bugs in / dogfood this
  site'' tasks.'
metadata:
  jros:
    tags:
    - qa
    - testing
    - browser
    - web
    category: software-development
    related_skills:
    - browser
    - jaeger-webui
    version: 2.2.0
    platforms:
    - linux
    - macos
    - windows
    requires-tools:
    - browser
    - append_file
    - write_file
    - read_file
    - execute_code
    - web_extract
---

# WEB APP QA — FIND BUGS, PROVE THEM, REPORT

Systematically exercise a web app, log every bug with evidence, produce a report.
Use for "test / QA / find bugs in / dogfood <site>". For just reading a page's
text, use `web_extract` — don't spin up the browser for that.

## THE TOOLS (exact — one browser tool, action-dispatched)
```
browser(action="open", url="https://…")   go to a page
browser(action="snapshot")                 read the page (DOM/accessibility text)
browser(action="click", element="…")       click an element
browser(action="type", element="…", text="…")  type into a field
browser(action="scroll", direction="down") scroll
browser(action="press", key="Enter")       press a key
browser(action="back")                      go back
```
Plus file tools for state: `append_file`, `write_file`, `read_file`.

QA ALWAYS RUNS IN THE AGENT'S OWN AUTOMATION BROWSER (`browser`) — never
`open_on_host` (that opens the USER's real browser, hijacks their session,
and can crash it).

## SOP (phased — never skip)

PHASE 1 — PLAN: from the user's scope, list the pages/flows to test (home, nav,
forms, login, edge/empty/404). Keep it short.

PHASE 2 — EXPLORE each target: `browser(action="open", url=…)` ->
`browser(action="snapshot")` to read it -> interact (click/type/scroll) ->
snapshot again to see what changed. Test invalid input and empty submits.

PHASE 3 — LOG EVIDENCE (file-backed — do NOT hold bugs in memory): the moment
you find a bug, `append_file(path="workspace/qa_issues.md", text=…)` in this
shape, one per bug:
```
SEVERITY: [Critical|High|Medium|Low]
CATEGORY: [Functional|Visual|Console|UX|Accessibility]
LOCATION: <url>
DETAILS: expected vs actual
```
For severity/category definitions if unsure: `read_file("references/issue-taxonomy.md")`.

PHASE 4 — REPORT: `read_file("workspace/qa_issues.md")` to get the full list. If
counting/grouping many issues, use `execute_code` to tally — don't count in your
head. For the exact report format: `read_file("templates/report-template.md")`,
then `write_file("workspace/qa_report.md", …)`.

## ERROR HATCH
- A page won't load / element not found twice -> snapshot again for fresh
  element refs; don't retry the same stale ref a third time.
- TargetClosedError (page/context/browser closed) -> the session is dead:
  `browser(action="open", url=...)` again and snapshot BEFORE any click/type.
  NEVER retry fill/click on a closed page — that is what crashed the run.
- HTTP 200 / health-ok / a process listening is NOT a passing result. Snapshot
  the live page. A "different version" / "hard refresh" / "hard reset" banner
  is a Critical Functional bug — the site is still broken; do not call it fixed.
- Console/JS errors are high-value findings — log them, don't skip.

## DONE WHEN
`workspace/qa_report.md` exists with an executive summary (issue counts by
severity) + one section per bug. The live snapshot must not show a blocking
recovery/version-skew banner. Then tell the user where the report is.
