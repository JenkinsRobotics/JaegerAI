/* Grok-style grouping of the agent list by server section (section_id): Pinned first (server pinned, by
 * pin_order), then each section in order, then the rest under "Other". Hidden — one flat group, no headers —
 * while the gateway has no sections. */
import type { Section } from "../api/agentActions";
import type { SidebarRow } from "./agentsLogic";

export interface RowGroup { id: string; title?: string; rows: SidebarRow[] }

export function groupRows(rows: SidebarRow[], sections: Section[], { pinnedGroup = true } = {}): RowGroup[] {
  if (!sections.length) return [{ id: "all", rows }];
  const pinned = pinnedGroup ? rows.filter((r) => r.agent.pinned).sort((a, b) => (a.agent.pin_order ?? 0) - (b.agent.pin_order ?? 0)) : [];
  const rest = rows.filter((r) => !pinned.includes(r));
  const known = new Set(sections.map((s) => s.id));
  const groups: RowGroup[] = [];
  if (pinned.length) groups.push({ id: "pinned", title: "Pinned", rows: pinned });
  for (const s of [...sections].sort((a, b) => (a.order ?? 0) - (b.order ?? 0))) {
    const inSection = rest.filter((r) => r.agent.section_id === s.id);
    if (inSection.length) groups.push({ id: s.id, title: s.name, rows: inSection });
  }
  const other = rest.filter((r) => !r.agent.section_id || !known.has(r.agent.section_id));
  if (other.length) groups.push({ id: "other", title: "Other", rows: other });
  return groups;
}
