import { useMemo, useState } from "react";
import { AgentAvatar } from "../agents/AgentAvatar";
import { Badge, Empty, Segmented } from "../unified/ui";
import { CheckBadge } from "./CheckBadge";
import { relativeTime } from "./feed";
import { OutputLinkView, type Navigate } from "./OutputLinkView";
import type { ActivityRow } from "./types";
import type { StreamState } from "./useOrchestration";

type Filter = "all" | "needs" | "handoffs" | "running" | "finished";
const STREAM_TEXT: Record<StreamState, string> = { connecting: "Connecting…", live: "Live", reconnecting: "Reconnecting…", polling: "Updating every 15s" };

export function ActivityFeed({ rows, names, stream, agentFilter, selectedHandoff, onOpenHandoff, onNavigate, now, onLoadOlder, historyError, caller, onCaller, groupWork }: {
  groupWork?: boolean;
  rows: ActivityRow[]; names: (id: string) => string; stream: StreamState; agentFilter?: string;
  selectedHandoff?: string; onOpenHandoff: (id: string) => void; onNavigate: Navigate; now?: number; onLoadOlder?: () => Promise<void>; historyError?: string; caller?: string; onCaller?: (id: string | undefined) => void;
}) {
  const [older, setOlder] = useState<"idle" | "loading" | "error">("idle");
  const [filter, setFilter] = useState<Filter>("all");
  const shown = useMemo(() => rows.filter((r) =>
    (!agentFilter || r.agentId === agentFilter) && (!caller || r.callerId === caller || r.agentId === caller)), [rows, agentFilter, caller]);
  const callers = useMemo(() => [...new Set([...rows.flatMap((r) => (r.callerId ? [r.callerId] : [])), ...(caller ? [caller] : [])])].sort(), [rows, caller]);
  const go: Navigate = (href) => (href.startsWith("handoff:") ? onOpenHandoff(href.slice(8)) : onNavigate(href));
  const groups = new Map<string, ActivityRow[]>();
  for (const r of shown) {
    const key = groupWork && r.handoffId ? `handoff:${r.handoffId}` : groupWork && r.taskId ? `task:${r.taskId}` : r.key;
    const group = groups.get(key);
    if (group) group.push(r); else groups.set(key, [r]);
  }
  const filtered = [...groups].filter(([, group]) => {
    const latest = group[0];
    const state = latest.statusPill?.text ?? "";
    if (filter === "needs") return group.some(r => r.needsYou);
    if (filter === "running") return /^(running|working)$/i.test(state);
    if (filter === "finished") return /^(done|completed|failed|cancelled|finished)$/i.test(state) || /completed|failed|cancelled/.test(latest.kind);
    return filter === "all" || latest.kind.startsWith("handoff");
  });
  const renderRow = (r: ActivityRow) => (
    <li key={r.key} className="jg-orch-row" data-needs={r.needsYou || undefined} aria-current={r.handoffId && r.handoffId === selectedHandoff ? "true" : undefined}>
      <AgentAvatar id={r.agentId} name={names(r.agentId)} size={24} />
      <div className="jg-orch-row-body">
        <p><strong>{names(r.agentId)}</strong> {r.action}</p>
        <div className="jg-orch-row-meta">
          <time>{relativeTime(r.at, now)}</time>
          {r.check && <CheckBadge check={r.check} />}
          {r.statusPill && <Badge tone={r.statusPill.tone}>{r.statusPill.text}</Badge>}
          {r.output && <OutputLinkView link={r.output} onNavigate={go} />}
        </div>
      </div>
    </li>
  );
  return (
    <section className="jg-orch-feed" aria-label="Activity">
      <header className="jg-orch-feed-head">
        <h2>{groupWork ? "Work and activity" : "Activity"}{agentFilter ? ` · ${names(agentFilter)}` : ""}</h2>
        <span className="jg-orch-stream" data-state={stream} role="status">{STREAM_TEXT[stream]}</span>
        {onCaller && callers.length > 0 && (
          <select className="jg-orch-caller" aria-label="From app" value={caller ?? ""} onChange={(e) => onCaller(e.target.value || undefined)}>
            <option value="">All sources</option>
            {callers.map((c) => <option key={c} value={c}>{names(c)}</option>)}
          </select>
        )}
        <Segmented label="Filter activity" value={filter} onChange={setFilter} options={[{ value: "all", label: "All work" }, { value: "needs", label: "Needs you" }, ...(groupWork ? [{ value: "running" as const, label: "Running" }, { value: "finished" as const, label: "Finished" }] : [{ value: "handoffs" as const, label: "Handoffs" }])]} />
      </header>
      {historyError && <p className="jg-orch-history-error" role="status">Older activity couldn't load ({historyError}). Showing current handoffs and tasks.</p>}
      {filtered.length === 0 ? <Empty title="No matching activity">Handoffs, tasks and approvals show up here as they happen.</Empty> : (
        <ol className="jg-orch-rows">
          {filtered.map(([key, group]) => group.length === 1 ? renderRow(group[0]) : (
            <li key={key}><details className="jg-orch-work-group"><summary>{names(group[0].agentId)} {group[0].action} · {group.length} updates</summary><ol className="jg-orch-rows">{group.map(renderRow)}</ol></details></li>
          ))}
        </ol>
      )}
      {onLoadOlder && <button type="button" className="jg-orch-older" disabled={older === "loading"} onClick={() => { setOlder("loading"); onLoadOlder().then(() => setOlder("idle"), () => setOlder("error")); }}>{older === "loading" ? "Loading…" : older === "error" ? "Couldn't load, try again" : "Load older"}</button>}
    </section>
  );
}
