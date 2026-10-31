import { useEffect, useState } from "react";
import type { Handoff, HandoffExchange, Task } from "../api/types";
import { SkeletonRows } from "../unified/ui";
import type { OrchestrationAdapter } from "./adapter";
import { CheckBadge } from "./CheckBadge";
import { artifactsFor, checkFor, sessionLink, taskForHandoff, taskLink } from "./feed";
import { OutputLinkView, type Navigate } from "./OutputLinkView";

/** Read-only side panel for one handoff: who, what, result, check, outputs. */
export function HandoffInspector({ handoff, tasks, adapter, names, onNavigate, onClose }: {
  handoff: Handoff; tasks: Task[]; adapter: OrchestrationAdapter; names: (id: string) => string; onNavigate: Navigate; onClose: () => void;
}) {
  const [ex, setEx] = useState<HandoffExchange | null>();
  const [err, setErr] = useState<string>();
  useEffect(() => {
    let alive = true; setEx(undefined); setErr(undefined);
    adapter.exchange(handoff.id).then((x) => alive && setEx(x), (e: unknown) => { if (alive) { setEx(null); setErr(e instanceof Error ? e.message : String(e)); } });
    return () => { alive = false; };
  }, [adapter, handoff.id]);
  const task = taskForHandoff(handoff, tasks);
  const check = checkFor(handoff, tasks);
  const outputs = [...artifactsFor(handoff), ...(task ? [taskLink(task)] : []), ...(handoff.to_agent_id ? [sessionLink(handoff.to_agent_id, `Open ${names(handoff.to_agent_id)}`)] : [])];
  return (
    <aside className="jg-orch-inspector" aria-label="Handoff details">
      <header><h2>{names(handoff.from_agent_id ?? "native:jaeger")} → {names(handoff.to_agent_id ?? "")}</h2><button type="button" className="jg-orch-close" aria-label="Close details" onClick={onClose}>✕</button></header>
      <dl>
        <dt>Task</dt><dd>{handoff.task ?? "—"}</dd>
        <dt>Status</dt><dd>{handoff.status ?? "—"}</dd>
        <dt>Result check</dt><dd><CheckBadge check={check} />{check.evidence && <OutputLinkView link={check.evidence} onNavigate={onNavigate} />}</dd>
        {check.note && <><dt>Check note</dt><dd>{check.note}</dd></>}
        <dt>Result</dt><dd className="jg-orch-fulltext">{ex === undefined ? <SkeletonRows n={1} /> : ex?.summary ?? handoff.result?.summary ?? (err ? `Couldn't load the exchange: ${err}` : "No result yet")}</dd>
      </dl>
      {outputs.length > 0 && <div className="jg-orch-outputs" aria-label="Outputs">{outputs.map((o) => <OutputLinkView key={o.href} link={o} onNavigate={onNavigate} />)}</div>}
    </aside>
  );
}
