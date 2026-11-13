/** Unified diffs for file-edit tool rows (Codex / Cursor transcript standard). */
import type { ReactNode } from "react";

export type DiffLine = { kind: "add" | "del" | "ctx" | "hunk" | "meta"; text: string };

export interface FileDiffModel {
  path?: string;
  lines: DiffLine[];
  added: number;
  removed: number;
}

function rec(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
}

function str(value: unknown): string | undefined {
  return typeof value === "string" && value.length ? value : undefined;
}

function pathOf(input?: Record<string, unknown>, output?: Record<string, unknown>): string | undefined {
  for (const row of [input, output]) {
    if (!row) continue;
    for (const key of ["path", "file_path", "filePath", "filename", "file", "target"]) {
      const value = str(row[key]);
      if (value) return value;
    }
  }
  return undefined;
}

function looksLikeDiff(text: string): boolean {
  return /^(diff --git |--- |\+\+\+ |@@ )/m.test(text);
}

function parseUnified(text: string): DiffLine[] {
  const lines: DiffLine[] = [];
  for (const raw of text.replace(/\r\n/g, "\n").split("\n")) {
    if (raw.startsWith("@@")) lines.push({ kind: "hunk", text: raw });
    else if (raw.startsWith("+++") || raw.startsWith("---") || raw.startsWith("diff ") || raw.startsWith("index ")) lines.push({ kind: "meta", text: raw });
    else if (raw.startsWith("+")) lines.push({ kind: "add", text: raw.slice(1) });
    else if (raw.startsWith("-")) lines.push({ kind: "del", text: raw.slice(1) });
    else lines.push({ kind: "ctx", text: raw.startsWith(" ") ? raw.slice(1) : raw });
  }
  while (lines.length && !lines[lines.length - 1]!.text) lines.pop();
  return lines;
}

/** Shortest-path line diff for ordinary before/after payloads; falls back to a block replace when huge. */
function lineDiff(before: string, after: string): DiffLine[] {
  const a = before.replace(/\r\n/g, "\n").split("\n");
  const b = after.replace(/\r\n/g, "\n").split("\n");
  if (a.length * b.length > 250_000) {
    return [
      ...a.map((text) => ({ kind: "del" as const, text })),
      ...b.map((text) => ({ kind: "add" as const, text })),
    ];
  }
  const n = a.length, m = b.length;
  const prev = new Int32Array(m + 1);
  const cur = new Int32Array(m + 1);
  const rows: Int32Array[] = [new Int32Array(prev)];
  for (let i = 1; i <= n; i++) {
    cur[0] = 0;
    for (let j = 1; j <= m; j++) cur[j] = a[i - 1] === b[j - 1] ? prev[j - 1] + 1 : Math.max(cur[j - 1], prev[j]);
    rows.push(new Int32Array(cur));
    prev.set(cur);
  }
  const out: DiffLine[] = [];
  let i = n, j = m;
  while (i > 0 && j > 0) {
    if (a[i - 1] === b[j - 1]) { out.push({ kind: "ctx", text: a[i - 1]! }); i--; j--; }
    else if (rows[i]![j - 1]! >= rows[i - 1]![j]!) { out.push({ kind: "add", text: b[j - 1]! }); j--; }
    else { out.push({ kind: "del", text: a[i - 1]! }); i--; }
  }
  while (i > 0) { out.push({ kind: "del", text: a[i - 1]! }); i--; }
  while (j > 0) { out.push({ kind: "add", text: b[j - 1]! }); j--; }
  return out.reverse();
}

function pairFrom(row?: Record<string, unknown>): [string, string] | undefined {
  if (!row) return undefined;
  const keys: [string, string][] = [
    ["old_string", "new_string"], ["old_text", "new_text"], ["before", "after"],
    ["original", "updated"], ["old", "new"],
  ];
  for (const [a, b] of keys) {
    const left = str(row[a]), right = str(row[b]);
    if (left != null && right != null) return [left, right];
  }
  return undefined;
}

function stats(lines: DiffLine[]): { added: number; removed: number } {
  let added = 0, removed = 0;
  for (const line of lines) {
    if (line.kind === "add") added++;
    else if (line.kind === "del") removed++;
  }
  return { added, removed };
}

export function extractFileDiff(input: unknown, output?: unknown): FileDiffModel | undefined {
  const inn = rec(input);
  const out = rec(output);
  const path = pathOf(inn, out);
  const patch = str(inn?.diff) ?? str(inn?.patch) ?? str(inn?.unified_diff) ?? str(inn?.text)
    ?? (typeof output === "string" && looksLikeDiff(output) ? output : undefined)
    ?? str(out?.diff) ?? str(out?.patch) ?? str(out?.unified_diff);
  if (patch && looksLikeDiff(patch)) {
    const lines = parseUnified(patch);
    return { path, lines, ...stats(lines) };
  }
  const pair = pairFrom(inn) ?? pairFrom(out);
  if (pair) {
    const lines = lineDiff(pair[0], pair[1]);
    return { path, lines, ...stats(lines) };
  }
  const edits = inn?.edits ?? inn?.changes;
  if (Array.isArray(edits) && edits.length) {
    const lines: DiffLine[] = [];
    for (const edit of edits) {
      const p = pairFrom(rec(edit));
      if (!p) continue;
      if (lines.length) lines.push({ kind: "hunk", text: "@@" });
      lines.push(...lineDiff(p[0], p[1]));
    }
    if (lines.length) return { path, lines, ...stats(lines) };
  }
  return undefined;
}

export function FileDiff({ model }: { model: FileDiffModel }): ReactNode {
  return (
    <div className="jg-filediff">
      <div className="jg-filediff__path">{model.path ?? "Edited file"} <span>+{model.added} −{model.removed}</span></div>
      <pre className="jg-filediff__body">{model.lines.map((line, i) => (
        <span key={i} className={`jg-filediff__line jg-filediff__line--${line.kind}`}>{line.kind === "add" ? "+" : line.kind === "del" ? "−" : line.kind === "hunk" ? " " : " "}{line.text || " "}</span>
      ))}</pre>
    </div>
  );
}
