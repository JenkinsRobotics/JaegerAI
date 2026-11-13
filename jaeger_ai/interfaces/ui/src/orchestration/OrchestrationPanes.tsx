import { useMemo, useState } from "react";
import "./orchestration.css";
import { ErrorState } from "../shell/ErrorState";
import { SkeletonRows } from "../unified/ui";
import type { OrchestrationAdapter } from "./adapter";
import { ActivityFeed } from "./ActivityFeed";
import { handoffForId, LEAD_ID, namesFrom } from "./feed";
import { HandoffInspector } from "./HandoffInspector";
import { LeadCard } from "./LeadCard";
import type { Navigate } from "./OutputLinkView";
import { SpecialistStatusList } from "./SpecialistStatusList";
import { useOrchestration } from "./useOrchestration";

/** Three panes per RESPONSIVE-SYSTEM.md: team list (nav column) · activity
 * (content) · handoff inspector (docked ≥1200, trailing overlay 840–1199,
 * bottom sheet <840). Layout is driven by container queries on .jg-orch, so
 * it behaves the same inside the Agents tab or the harness. */
export function OrchestrationPanes({ adapter, onNavigate, now, initialCaller }: { adapter: OrchestrationAdapter; onNavigate: Navigate; now?: number; initialCaller?: string }) {
  const [caller, setCaller] = useState<string | undefined>(initialCaller);
  const s = useOrchestration(adapter, { callerId: caller });
  const [agentFilter, setAgentFilter] = useState<string>();
  const [handoffId, setHandoffId] = useState<string>();
  const names = useMemo(() => namesFrom(s.snapshot?.agents ?? []), [s.snapshot]);
  const lead = s.live.find((l) => l.agent.id === LEAD_ID || l.agent.role === "lead");
  const team = s.live.filter((l) => l !== lead);
  const handoff = handoffForId(handoffId, s.snapshot?.handoffs ?? [], s.rows);

  if (s.status === "error") return <div className="jg-orch"><ErrorState title="Couldn't load agent activity" error={s.error ?? "Unknown error"} onRetry={s.retry} /></div>;
  return (
    <div className="jg-orch" data-inspector={handoff ? "open" : undefined}>
      <div className="jg-orch-grid">
        <nav className="jg-orch-nav" aria-label="Agents">
          {s.status === "loading" ? <SkeletonRows n={4} /> : <><LeadCard lead={lead} team={team} rows={s.rows} /><SpecialistStatusList team={team} selected={agentFilter} onSelect={setAgentFilter} /></>}
        </nav>
        <main className="jg-orch-main">
          {s.status === "loading" ? <SkeletonRows n={6} /> : <ActivityFeed rows={s.rows} names={names} stream={s.stream} agentFilter={agentFilter} selectedHandoff={handoffId} onOpenHandoff={setHandoffId} onNavigate={onNavigate} now={now} onLoadOlder={s.loadOlder} historyError={s.historyError} caller={caller} onCaller={setCaller} />}
        </main>
        {handoff && <>
          <div className="jg-orch-scrim" onClick={() => setHandoffId(undefined)} aria-hidden />
          <HandoffInspector handoff={handoff} tasks={s.snapshot?.tasks ?? []} adapter={adapter} names={names} onNavigate={onNavigate} onClose={() => setHandoffId(undefined)} />
        </>}
      </div>
    </div>
  );
}
