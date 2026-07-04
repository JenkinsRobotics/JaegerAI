# excel-author patterns — skeleton, merged headers, sensitivity tables

Overflow from SKILL.md. Copy these patterns, don't reinvent them.

## Workbook skeleton (Inputs / calc / Checks)

```python
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.comments import Comment
from openpyxl.utils import get_column_letter
from pathlib import Path

BLUE = Font(color="0000FF")          # hardcoded input
GREEN = Font(color="006100")         # cross-sheet / external link
BOLD = Font(bold=True)
HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
HEADER_FONT = Font(color="FFFFFF", bold=True)

wb = Workbook()

# --- Inputs tab ---
inp = wb.active
inp.title = "Inputs"
inp["A1"] = "MARKET DATA & KEY INPUTS"
inp["A1"].font = HEADER_FONT
inp["A1"].fill = HEADER_FILL
inp.merge_cells("A1:C1")

inp["B3"] = "Revenue FY2024"
inp["C3"] = 1_250_000_000
inp["C3"].font = BLUE
inp["C3"].comment = Comment("Source: 10-K FY2024 p.47", "model")

inp["B4"] = "Growth Rate"
inp["C4"] = 0.12
inp["C4"].font = BLUE

# --- Calc tab (formulas only, default black font) ---
calc = wb.create_sheet("DCF")
calc["B2"] = "Projected Revenue"
calc["C2"] = "=Inputs!C3*(1+Inputs!C4)"

# --- Checks tab ---
chk = wb.create_sheet("Checks")
chk["A2"] = "BS balances"
chk["B2"] = "=ABS(BS!D20-BS!D21-BS!D22)<0.01"

Path("out").mkdir(exist_ok=True)
wb.save("out/model.xlsx")
```

## Named ranges

```python
from openpyxl.workbook.defined_name import DefinedName
wb.defined_names["WACC"] = DefinedName("WACC", attr_text="Inputs!$C$8")
# elsewhere:
calc["D30"] = "=D29/WACC"
```

## Section headers with merged cells (openpyxl quirk)

Set the value on the TOP-LEFT cell only; style each cell of the range
separately — styling the merged range directly does not fill it.

```python
ws["A7"] = "CASH FLOW PROJECTION"
ws["A7"].font = HEADER_FONT
ws.merge_cells("A7:H7")
for col in range(1, 9):  # A..H
    ws.cell(row=7, column=col).fill = HEADER_FILL
```

## Sensitivity table (5x5, loop-built)

Rules: odd row/col count so a true center exists; center row/col headers equal
the model's ACTUAL base WACC and terminal g, so the center output must equal
the base-case answer (the sanity check); highlight the center; every cell is a
full recalculation formula, never an approximation.

```python
# 5x5: WACC (rows) x terminal growth (cols)
wacc_axis = [0.08, 0.085, 0.09, 0.095, 0.10]   # center = base 9.0%
term_axis = [0.02, 0.025, 0.03, 0.035, 0.04]   # center = base 3.0%

start_row = 40
ws.cell(row=start_row, column=1).value = "Implied Share Price ($)"
ws.cell(row=start_row, column=1).font = BOLD

for j, g in enumerate(term_axis):
    ws.cell(row=start_row + 1, column=2 + j).value = g
    ws.cell(row=start_row + 1, column=2 + j).font = BLUE

for i, w in enumerate(wacc_axis):
    r = start_row + 2 + i
    ws.cell(row=r, column=1).value = w
    ws.cell(row=r, column=1).font = BLUE
    for j, g in enumerate(term_axis):
        # Full DCF recalc formula (simplified for illustration —
        # a real model references the full projection block).
        ws.cell(row=r, column=2 + j).value = (
            f"=SUMPRODUCT(FCF_range,1/(1+{w})^year_offset) + "
            f"FCF_terminal*(1+{g})/({w}-{g})/(1+{w})^terminal_year"
        )

center = ws.cell(row=start_row + 2 + len(wacc_axis) // 2,
                 column=2 + len(term_axis) // 2)
center.fill = PatternFill("solid", fgColor="BDD7EE")
center.font = BOLD
```

## Recalc before delivery

openpyxl writes formula strings, computes nothing. `scripts/recalc.py`
(bundled with this skill) runs LibreOffice headless to compute + resave in
place, so downstream `load_workbook(..., data_only=True)` reads real values:

```bash
python <skill_folder>/scripts/recalc.py out/model.xlsx
```

Manual equivalent:

```bash
libreoffice --headless --calc --convert-to xlsx out/model.xlsx --outdir out/
```

## When NOT to use this skill

- Plain tabular export, no formulas → `pandas.to_excel` or csv in one
  `execute_code` call.
- Interactive dashboards/charts → a real BI tool, not openpyxl.

## Attribution

Blue/black/green, formulas-over-hardcodes, named-range, and sensitivity rules
adapted from Anthropic's Claude for Financial Services plugin suite
(Apache-2.0): https://github.com/anthropics/financial-services
