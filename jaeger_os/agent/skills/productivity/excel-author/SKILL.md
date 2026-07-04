---
name: excel-author
description: "Build auditable .xlsx workbooks headless with openpyxl — banker-grade conventions: blue/black/green cell coloring, live formulas over hardcoded values, named ranges, a Checks tab, sensitivity tables. Load this when the user wants a financial model, reconciliation, or any Excel file with real formulas — for a plain data dump to Excel, pandas.to_excel in execute_code is enough, skip this skill."
version: 1.1.0
platforms: [linux, macos, windows]
requires_tools: [execute_code, terminal, read_file, write_file, web_search]
metadata:
  jros:
    tags: [excel, openpyxl, xlsx, finance, spreadsheet, modeling, audit]
    category: productivity
    related_skills: [ocr-and-documents, powerpoint]
---

# EXCEL AUTHOR

Produce an .xlsx on disk with `openpyxl`, following conventions that make the
workbook auditable by someone other than its builder. Conventions adapted from
Anthropic's financial-services xlsx-author skills (Apache-2.0).

## TOOLS

- `execute_code(code="...")` — run the openpyxl Python that builds the workbook.
- `terminal(command="pip install 'openpyxl>=3.0'")` — one-time setup if the
  import fails.
- `write_file(path, content)` — save the build script when it grows past ~60
  lines, then `terminal(command="python build_model.py")` — don't juggle a big
  script in context.
- `read_file("references/patterns.md")` — full workbook skeleton, merged-header
  quirk, sensitivity-table loop. Fetch before writing any code.

## OUTPUT CONTRACT

- Write to `out/<name>.xlsx` (create `out/` first). One logical model per file.
- Never append to an existing workbook unless explicitly asked.
- Final message states the file path.

## CORE CONVENTIONS (non-negotiable)

CELL COLOR tells a reviewer what each cell IS:
- Blue `Font(color="0000FF")` — hardcoded human input (drivers, market data).
- Black (default) — a live Excel formula. Every derived cell.
- Green `Font(color="006100")` — link to another sheet or file.

FORMULAS OVER HARDCODES — a calc cell is a formula STRING, never a value
computed in Python and pasted:
```python
ws["D20"] = revenue * (1 + growth)      # WRONG - dead value, silent bug
ws["D20"] = "=D19*(1+$B$8)"             # CORRECT - flexes with assumptions
```
Only three things may be hardcoded: raw historicals, assumption drivers the
user will flex, and current market data (with a sourced comment).

NAMED RANGES for anything referenced cross-sheet:
```python
from openpyxl.workbook.defined_name import DefinedName
wb.defined_names["WACC"] = DefinedName("WACC", attr_text="Inputs!$C$8")
```

CHECKS TAB — a `Checks` sheet of TRUE/FALSE ties: balance sheet balances,
cash flow ties to BS cash change, sum-of-parts ties to consolidated.
```python
chk["B2"] = "=ABS(BS!D20-BS!D21-BS!D22)<0.01"
```

COMMENT EVERY HARDCODE as you create it — never defer, never "TODO":
```python
ws["C3"].comment = Comment("Source: 10-K FY2024, p.47, revenue line", "model")
```

## SOP

1. PLAN THE LAYOUT FIRST: fix every section's row positions, write all
   headers/labels/dividers, THEN write formulas against the locked rows.
   Inserting a row after formulas exist shifts every downstream reference.
2. `read_file("references/patterns.md")` for the skeleton and copy its style
   constants (BLUE/GREEN/HEADER_FILL).
3. Build tab by tab: Inputs → calc sheets → Checks. Run `execute_code` after
   each tab and re-open the file (`load_workbook`) to confirm it saved.
4. CHECKPOINT WITH THE USER on large models (DCF, 3-statement, LBO): show the
   Inputs block before projecting, the revenue build before FCF, the valuation
   before sensitivity tables. A wrong margin caught early saves the rebuild.
5. Sensitivity tables last — odd-sized grid (5x5), center cell = base case and
   must equal the base-case output (that's the sanity check). Loop pattern in
   references/patterns.md.
6. RECALC BEFORE DELIVERY: openpyxl writes formula strings but computes
   nothing — a downstream `data_only=True` read sees None. Run
   `terminal(command="python {{skill_folder}}/scripts/recalc.py out/<name>.xlsx")`
   (LibreOffice headless; skippable if the user will open it in Excel).

## ERROR HATCH

- `ModuleNotFoundError: openpyxl` → `terminal(command="pip install 'openpyxl>=3.0'")`, rerun.
- recalc.py fails / LibreOffice missing → deliver anyway and say formulas
  compute on first open in Excel; don't chase a LibreOffice install.
- Same openpyxl error twice → don't retry a third time; `web_search` the exact
  message, or simplify (drop merged cells / styling) and re-add incrementally.

## DONE WHEN

`out/<name>.xlsx` exists and re-opens cleanly via `load_workbook`; every calc
cell is a formula; hardcodes are blue with source comments; a Checks tab shows
its ties; the final message gives the path and (for big models) the checkpoint
confirmations happened along the way.
