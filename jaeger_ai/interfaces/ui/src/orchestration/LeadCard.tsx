import { AgentAvatar } from "../agents/AgentAvatar";
import { label } from "../agents/agentsLogic";
import type { ActivityRow, AgentLive } from "./types";

/** The lead (Jaeger) and what it's coordinating right now. */
export function LeadCard({ lead, team, rows }: { lead?: AgentLive; team: AgentLive[]; rows: ActivityRow[] }) {
  if (!lead) return null;
  const busy = team.filter((t) => t.status !== "idle");
  const needs = rows.filter((r) => r.needsYou).length;
  return (
    <section className="jg-orch-lead" aria-label="Lead agent">
      <AgentAvatar id={lead.agent.id} name={label(lead.agent)} src={lead.agent.avatar_url} size={40} primary />
      <div className="jg-orch-lead-text">
        <strong>{label(lead.agent)}</strong>
        <span>{busy.length ? `Coordinating ${busy.length} specialist${busy.length === 1 ? "" : "s"}` : "No specialists working"}</span>
      </div>
      {needs > 0 && <span className="jg-orch-needs" aria-label={`${needs} need you`}>{needs}</span>}
    </section>
  );
}
