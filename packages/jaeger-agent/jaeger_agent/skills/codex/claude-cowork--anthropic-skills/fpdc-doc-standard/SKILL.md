---
name: fpdc-doc-standard
description: Apply the Quantum Space FPDC document formatting standard — CUI markings, cover page, headers/footers, heading hierarchy, body/list/table/caption styles, and page layout — to any new or existing technical document.
---

## When to use

Use this skill when:
- Creating a new FPDC-series document from scratch
- Formatting an existing document to match the Quantum Space FPDC standard
- Checking whether a document conforms to the FPDC formatting standard
- The user says "apply FPDC formatting", "use the FPDC standard", "format like FPDC-0010", or "standardize this document"

This skill defines the **formatting and structural standard** only. It does not generate content — the user or another skill provides the text; this skill ensures it looks correct.

---

## 1. Page Layout

Set on **every section** in the document:

| Property | Value |
|---|---|
| Paper size | Letter (612 × 792 pt) |
| Orientation | Portrait |
| Margins | 1 inch (72 pt) all four sides |
| Gutter | 0 pt |
| Header distance | 0.5 inch (36 pt) |
| Footer distance | 0.5 inch (36 pt) |
| Columns | 1 |
| Different first page | true |
| Different odd/even pages | true |

```javascript
const sections = context.document.sections;
sections.load("items");
await context.sync();
for (const sec of sections.items) {
  const ps = sec.pageSetup;
  ps.topMargin = 72;
  ps.bottomMargin = 72;
  ps.leftMargin = 72;
  ps.rightMargin = 72;
  ps.headerDistance = 36;
  ps.footerDistance = 36;
  ps.gutter = 0;
  ps.differentFirstPage = true;
  ps.differentOddAndEvenPages = true;
}
await context.sync();
```

Done when: `read_doc_section` on any paragraph shows margins at 72 pt.

---

## 2. Document Sections (Section Breaks)

The document uses **two Word sections**:

- **Section 0 (Cover Page)**: Title page, metadata fields, CUI marking block, Revision History table, and Prepared By / Approved By signature block. Ends with a section break before the TOC.
- **Section 1 (Main Body)**: Table of Contents, Table of Tables, Table of Figures, all numbered body sections (1–13), and back matter.

When creating a new document, insert a section break after the cover page content:
```javascript
// After inserting the last cover page element:
lastCoverPara.insertBreak("SectionNext", "After");
```

---

## 3. Headers and Footers

### Section 0 (Cover Page)

| Variant | Content |
|---|---|
| Primary Header | `CUI` (centered, 10 pt Times New Roman) |
| Primary Footer | `CUI` + newline + Distribution Statement B text (10 pt TNR) |
| First Page Header | `CUI` (centered) |
| First Page Footer | `CUI` only |
| Even Pages Header | `CUI` (centered) |

### Section 1 (Main Body)

| Variant | Content |
|---|---|
| Primary Header | `CUI` (centered, 10 pt Times New Roman) |
| Primary Footer | `CUI` + Distribution Statement B + `Page X of Y` (right-aligned page field) |
| First Page Header | `CUI` (centered) |
| First Page Footer | `CUI` + Distribution Statement B + `Page 1 of Y` |
| Even Pages Header | `CUI` (centered) |

Distribution Statement B text:
> Distribution Statement B:  Authorized to US Government agencies only. WARNING—Export Controlled.

Page numbers use a Word field (`Page` and `NumPages`), not literal text.

```javascript
const sec = sections.items[1];
const footer = sec.getFooter("Primary");
footer.clear();
const cuiPara = footer.insertParagraph("CUI", "Start");
cuiPara.font.name = "Times New Roman";
cuiPara.font.size = 10;
cuiPara.alignment = "Centered";
const distPara = footer.insertParagraph("Distribution Statement B:  Authorized to US Government agencies only. WARNING—Export Controlled.", "End");
distPara.font.name = "Times New Roman";
distPara.font.size = 10;
distPara.alignment = "Left";
// Page number field
const pageRange = footer.getRange("End");
pageRange.insertText("Page ", "End");
pageRange.insertField("End", "Page");
pageRange.insertText(" of ", "End");
pageRange.insertField("End", "NumPages");
await context.sync();
```

Done when: headers show `CUI`; footers show Distribution Statement B and page numbering.

---

## 4. Cover Page Structure (Section 0)

Build the cover page in this exact order:

1. **Spacer paragraphs** (NoSpacing style, TNR 12 pt, Justified) — 2 blank lines
2. **Company logo** (inline image, centered) — NoSpacing style, centered alignment
3. **Spacer paragraphs** — 6 blank NoSpacing lines
4. **Document title** — Title style (TNR 20 pt bold, centered)
5. **Spacer paragraphs** — 5 blank Body style lines
6. **Metadata fields** (Normal style, TNR 11 pt, Justified, lineSpacing 18 pt):
   - `Report Number (CDRL):\t[value]`
   - `Document Number:\t\t[value]`
   - `Program:\t\t\t[value]`
   - `Contractor Name:\t\t[value]`
   - `Contractor Address:\t\t[value]`
   - `Contract Number:\t\t[value]`
   - `Release Date:\t\t\t[value]`
7. **Spacer** — 2 blank Normal lines
8. **CUI Marking Block** — a single-column table (Table Grid style, TNR 10 pt), containing:
   - `Controlled by: [agency]`
   - `Controlled by: [office]`
   - `CUI Category: CTI/EXPORT CONTROLLED`
   - `Distribution Statement: DISTRO B`
   - `POC: [name, email]`
   - (blank row)
   - Distribution Statement B full text
   - Export control warning full text
9. **Page break** to Revision History

Done when: cover page contains logo, title, metadata fields, CUI block, and a page break.

---

## 5. Revision History (still in Section 0)

1. **Heading**: `Revision History` — Title 2 style (custom: TNR 12 pt bold, Justified)
2. **Table**: Grid Table 4 style, 4 columns: `Rev.`, `Date`, `Comment`, `Author`
   - Header row: TNR 10 pt bold, white text on accent background (#FFFFFF)
   - Data rows: TNR 10 pt, black text
3. **Signature block table** (Table Grid1 style): Prepared By / Title / Date and Approved By / Title / Date rows. TNR 10 pt, lineSpacing 13.8 pt.
4. **Page break** to Table of Contents

---

## 6. Front Matter (beginning of Section 1)

### Table of Contents
- Heading: `Table of Contents` — Heading 1 style
- TOC field: insert via `body.fields` or `insertField("TOC")`
- TOC 1 entries: 12 pt bold, italic, underline
- TOC 2 entries: 11 pt bold, underline
- Refresh TOC after any heading changes: `field.updateResult()`

### Table of Tables
- Heading: `Table Of Tables` — TOC 1 style (11 pt bold TNR)
- Lists all tables by caption text

### Table of Figures
- Heading: `Table Of Figures` — TOC 1 style (11 pt bold TNR)
- Lists all figures by caption text

Done when: TOC, Table of Tables, and Table of Figures exist and are populated.

---

## 7. Heading Styles

Three heading levels are used. **Never type section numbers as literal text** — headings are auto-numbered via the list attached to the style.

### Heading 1 (Top-level sections)
- Style: `Heading 1` (styleBuiltIn: `Heading1`)
- Font: Aptos Display, 18 pt, bold, #000000
- Alignment: Left
- Line spacing: 12 pt (single)
- Left indent: 0 pt
- Examples: `1. Executive Summary`, `2. Introduction`, `10. Design Risk Summary`
- **Note**: Heading 1 uses Aptos Display — a different font family from the body text. This is intentional; do not change it to Times New Roman.

### Heading 2 (Subsections)
- Style: `Heading 2` (styleBuiltIn: `Heading2`)
- Font: Times New Roman, 14 pt, bold, #000000
- Alignment: Left
- Line spacing: 12–13.8 pt
- Left indent: 13.5 pt
- Examples: `Overview`, `Stakeholder Expectations`, `MPS System Overview`

### Heading 3 (Sub-subsections)
- Style: `Heading 3` (styleBuiltIn: `Heading3`)
- Font: Times New Roman, 12 pt, bold, #000000
- Alignment: Left
- Line spacing: 12 pt
- Left indent: 0 pt
- Examples: `USFS Design Drivers`, `Injector (A) — High Priority`, `Key Equations`

```javascript
// Example: insert a new Heading 2
const h = anchor.insertParagraph("New Subsection Title", "After");
h.styleBuiltIn = "Heading2";
h.font.name = "Times New Roman";
h.font.size = 14;
h.font.bold = true;
h.font.color = "#000000";
h.alignment = "Left";
h.leftIndent = 13.5;
await context.sync();
```

Done when: headings render at the correct size, font, and indent per level.

---

## 8. Body Text Styles

### Body (primary — custom style, 395 paragraphs in reference doc)
- Style name: `Body` (set via `para.style = "Body"`, NOT `styleBuiltIn = "Normal"`)
- Font: Times New Roman, 12 pt, regular, #000000
- Alignment: Justified
- Line spacing: 12 pt (single)
- Left indent: 0 pt

### Normal (secondary body — used in some requirements and metadata)
- Style: `Normal` (styleBuiltIn: `Normal`)
- Font: Times New Roman, 12 pt, regular, #000000
- Alignment: Justified
- Line spacing: 12 pt (body) or 18 pt (cover page metadata fields)

**Rule**: Use `para.style = "Body"` for all main body paragraphs. Reserve Normal for cover page fields and auto-generated content (TOC entries).

### No Spacing (cover page spacers)
- Style: `No Spacing` (styleBuiltIn: `NoSpacing`)
- Font: Times New Roman, 12 pt, regular, #000000
- Alignment: Justified (centered for logo paragraph)
- Line spacing: 12 pt

Done when: body paragraphs use the `Body` custom style with TNR 12 pt justified.

---

## 9. List Styles

### List Bullet (custom style, 58 paragraphs in reference doc)
- Style name: `List Bullet` (set via `para.style = "List Bullet"`)
- Font: Times New Roman, 12 pt, regular, #000000
- Alignment: Justified
- Line spacing: 12 pt
- Left indent: 18 pt
- First-line indent: −18 pt (hanging)
- Marker: bullet character (rendered by style, never typed)

### List Number (custom style, 6 paragraphs in reference doc)
- Style name: `List Number` (set via `para.style = "List Number"`)
- Font: Times New Roman, 12 pt, regular, #000000
- Alignment: Left (first item) or Justified (subsequent)
- Line spacing: 12 pt
- Left indent: 18 pt
- First-line indent: −18 pt (hanging)
- Marker: `1.`, `2.`, etc. (auto-numbered, never typed)
- Usage: CONOPS sequence steps and similar ordered procedures
- The step label (e.g. `Safed:`, `Preheat:`) is bold inline within the paragraph

### List Paragraph (built-in, for requirements lists)
- Style: `List Paragraph` (styleBuiltIn: `ListParagraph`)
- Font: Times New Roman, 12 pt, regular, #000000
- Alignment: Justified
- Line spacing: 12 pt
- Left indent: 64.8 pt (deeper indent for requirements)
- First-line indent: −18 pt (hanging)
- Auto-numbered via list attachment (1., 2., 3., etc.)
- Usage: Stakeholder expectations, numbered requirements

Done when: list items use the correct custom style with proper hanging indent.

---

## 10. Table Formatting

### Table Caption
- Style: `Caption` (styleBuiltIn: `Caption`)
- Font: Times New Roman, 12 pt, italic, color #0E2841 (dark navy)
- Alignment: Left
- Line spacing: 12 pt
- Format: `Table: [descriptive name]` (e.g. `Table: PDC Design Concept Trade — Flight Selection`)
- **Always placed immediately before the table it describes**
- **Every table MUST have a caption paragraph**

### Primary Data Tables (architecture comparisons, component stacks, test matrices)
- Table style: `Grid Table 4 - Accent 1`
- Header row count: 1
- Header row font: Times New Roman, 10 pt, bold, white (#FFFFFF) on accent blue background
- Data row label column: Times New Roman, 10 pt, bold, #000000
- Data row values: Times New Roman, 10 pt, regular, #000000
- Cell style: Normal (styleBuiltIn)

### Trade Study / Evaluation Tables
- Table style: `Grid Table 4`
- Header row count: 1
- Header row font: Times New Roman, 10 pt, bold italic, white (#FFFFFF) on accent background
- Data rows: Times New Roman, 10 pt, italic, #000000
- Data row labels: bold italic, #000000
- Cell style: Body (custom) or Normal

### Risk Register Table
- Table style: `Grid Table 41` (variant)
- Header row count: 1
- Header row font: Times New Roman, 10 pt, bold italic, white (#FFFFFF)
- Risk ID column: bold italic
- Data cells: italic, #000000
- Columns: Risk ID, Description, Likelihood, Severity, Mitigation / Gate

### Revision History Table
- Table style: `Grid Table 4`
- Columns: Rev., Date, Comment, Author
- Header row: Title 2 style, 10 pt bold, white on accent

### Signature Block Table
- Table style: `Table Grid1`
- Font: TNR 10 pt, lineSpacing 13.8 pt
- Layout: Prepared By / Title / Date rows, then Approved By / Title / Date rows

```javascript
// Example: insert a caption + data table
const caption = anchor.insertParagraph("Table: Component Mass Summary", "After");
caption.styleBuiltIn = "Caption";
caption.font.name = "Times New Roman";
caption.font.size = 12;
caption.font.italic = true;
caption.font.color = "#0E2841";
caption.alignment = "Left";

const carrier = caption.insertParagraph("", "After");
carrier.styleBuiltIn = "Normal";
carrier.load("isListItem");
await context.sync();
if (carrier.isListItem) { carrier.detachFromList(); await context.sync(); }

const table = carrier.insertTable(rows, cols, "After", data);
table.style = "Grid Table 4 - Accent 1";
table.headerRowCount = 1;
// Set header row font
for (let c = 0; c < cols; c++) {
  const cell = table.getCell(0, c).body.paragraphs.getFirst();
  cell.font.name = "Times New Roman";
  cell.font.size = 10;
  cell.font.bold = true;
}
// Set data row font
for (let r = 1; r < rows; r++) {
  for (let c = 0; c < cols; c++) {
    const cell = table.getCell(r, c).body.paragraphs.getFirst();
    cell.font.name = "Times New Roman";
    cell.font.size = 10;
  }
}
await context.sync();
```

Done when: every table has a Caption-styled caption above it, uses the correct Grid Table style, and has TNR 10 pt throughout.

---

## 11. Title 2 (Custom Style)

- Style name: `Title 2` (set via `para.style = "Title 2"`)
- Font: Times New Roman, 12 pt, bold, #000000
- Alignment: Justified
- Line spacing: 12 pt
- Usage: Revision History heading, signature block labels in front matter
- When used as table header cells: 10 pt bold, white text (#FFFFFF) on accent background

---

## 12. Standard Section Structure

A conforming FPDC document contains these sections in order:

1. Cover page (Section 0)
2. Revision History
3. Table of Contents
4. Table of Tables
5. Table of Figures
6. **1. Executive Summary** — 1–2 paragraphs maximum; conclusions and critical risks, not a scope restatement
7. **2. Introduction** — Overview, System Description, System Tree (figure)
8. **3. Requirements** — Stakeholder Expectations (numbered list), Requirements Categories, Naming, then Functional / Performance / Environmental / Safety / Interface subsections
9. **4. Design Inputs** — Propellant properties tables
10. **5–8. Architecture Sections** — System-specific; each contains Design Overview, Component Architecture (with sub-subsections per component), Trade Studies (with trade tables), Design Rationale
11. **9. Verification and Testing** — Test program, test matrices (tables), qualification plan
12. **10. Design Risk Summary** — Risk register table (Risk ID, Description, Likelihood, Severity, Mitigation/Gate)
13. **11. Open Items and Action Log** — OI table (ID, Description, Owner, Due Gate, Status)
14. **12. References** — Grouped by: Internal Documents, External References, Propellant Properties, Fluid Mechanics, Catalyst/Coating, Applicable Standards
15. **13. Symbols, Abbreviations and Acronyms** — Alphabetized list

---

## 13. Verification Checklist

After applying formatting, verify:

- [ ] All body paragraphs use `Body` custom style (not Normal or direct formatting)
- [ ] Heading 1 uses Aptos Display 18 pt bold; Heading 2 uses TNR 14 pt bold with 13.5 pt indent; Heading 3 uses TNR 12 pt bold
- [ ] Every table has a Caption-styled paragraph immediately above it
- [ ] Table cells use TNR 10 pt; header rows are bold white on accent
- [ ] Lists use `List Bullet` or `List Number` custom styles with 18 pt hanging indent
- [ ] CUI marking appears in all headers (centered)
- [ ] Distribution Statement B appears in all footers
- [ ] Page numbers appear in Section 1 footers via Word fields
- [ ] Margins are 72 pt (1 inch) all sides
- [ ] TOC is present and refreshed
- [ ] No literal section numbers typed in heading text (all auto-numbered)
- [ ] No direct font overrides on body paragraphs (size, color, bold should come from style)

Run `verify_doc` to check style distribution, then `verify_doc_visual` on the cover page and a body section to confirm rendered appearance.
