export type ToolSelectionReceipt = {
  mode: "progressive" | "full";
  selected_count: number;
  catalog_count: number;
  truncated: boolean;
  tools: { tool: string; source: string; selected: boolean; available: boolean; selection_reason: string; unavailable_reason: string }[];
};
/** Bounded public metadata only. Do not retain arbitrary registry/server payloads. */
export function toolSelection(value: unknown): ToolSelectionReceipt {
  const p = value && typeof value === "object" ? value as Record<string, unknown> : {};
  const text = (v: unknown) => typeof v === "string" ? v.slice(0, 240) : "";
  const count = (v: unknown) => typeof v === "number" && Number.isFinite(v) ? Math.max(0, Math.floor(v)) : 0;
  return { mode: p.mode === "progressive" ? "progressive" : "full",
    selected_count: count(p.selected_count), catalog_count: count(p.catalog_count), truncated: p.truncated === true,
    tools: (Array.isArray(p.tools) ? p.tools : []).slice(0, 250).filter(t => t && typeof t === "object").map(t => ({
      tool: text(t.tool), source: text(t.source), selected: t.selected === true, available: t.available === true,
      selection_reason: text(t.selection_reason), unavailable_reason: text(t.unavailable_reason),
    })),
  };
}
