/** Repair informal pipe tables so remark-gfm can render them. */
const PIPE_ROW = /^\s*\|.*\|\s*$/;
const SEP_ROW = /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/;

function columns(row: string): number {
  const trimmed = row.trim().replace(/^\|/, "").replace(/\|$/, "");
  return trimmed.split("|").length;
}

function separator(cols: number): string {
  return `|${Array.from({ length: cols }, () => " --- ").join("|")}|`;
}

function splitPackedRows(line: string): string[] {
  if (!line.includes("|") || line.includes("\n")) return [line];
  // "| A | B | | C | D |" was written as one line, using an empty cell as a row break.
  const packed = line.split(/\s*\|\s*\|\s*/);
  if (packed.length < 2) return [line];
  return packed.map((part) => {
    let row = part.trim();
    if (!row.startsWith("|")) row = `| ${row}`;
    if (!row.endsWith("|")) row = `${row} |`;
    return row;
  });
}

export function repairPipeTables(text: string): string {
  const source = text.split("\n").flatMap(splitPackedRows);
  const out: string[] = [];
  for (let i = 0; i < source.length; i++) {
    const line = source[i]!;
    const next = source[i + 1];
    out.push(line);
    if (PIPE_ROW.test(line) && !SEP_ROW.test(line) && next && PIPE_ROW.test(next) && !SEP_ROW.test(next)) {
      out.push(separator(Math.max(columns(line), columns(next))));
    }
  }
  return out.join("\n");
}

const NUMERIC = /^\s*[-+$€£]?\d[\d,.]*%?\s*$/;

export function alignNumericTables(root: ParentNode): void {
  root.querySelectorAll("table").forEach((table) => {
    const rows = [...table.querySelectorAll("tr")];
    if (!rows.length) return;
    const width = Math.max(0, ...rows.map((row) => row.children.length));
    for (let col = 0; col < width; col++) {
      const cells = rows.map((row) => row.children[col]).filter((cell): cell is Element => Boolean(cell));
      const body = cells.filter((cell) => cell.tagName === "TD");
      if (body.length && body.every((cell) => NUMERIC.test((cell.textContent ?? "").replace(/\s+/g, " ")))) {
        cells.forEach((cell) => cell.classList.add("jg-md__num"));
      }
    }
  });
}
