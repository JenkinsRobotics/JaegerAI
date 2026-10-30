/**
 * Live list widgets for the Workspace (unified UI, 2026-10-30): agents status, open tasks,
 * recent chats, pending approvals and host metrics. Every value is read from the gateway or
 * the WebUI's /v1/system/metrics at load time; nothing is derived beyond counts.
 */
import { registerWidget } from "../registry";
import { SkeletonStat } from "../primitives/Skeleton";
import { Sparkline } from "../primitives/Sparkline";
import type { WidgetDef } from "../types";
import type { AgentSummary, SessionRow, Task } from "../../api/types";
import { getJson, type Metrics } from "../../unified/webui";

const OPEN = new Set(["queued", "running", "needs_owner", "paused", "blocked", "waiting_approval"]);
const List = ({ rows, empty }: { rows: { k: string; a: string; b?: string }[]; empty: string }) =>
  rows.length ? <ul className="wg-list">{rows.map((r) => <li key={r.k}><strong>{r.a}</strong>{r.b && <span>{r.b}</span>}</li>)}</ul> : <p className="wg-list__empty">{empty}</p>;

export const agentsStatusWidget: WidgetDef<void, AgentSummary[]> = {
  kind: "agents.status", title: "Agents", about: "See which agents are working or waiting on you", sizes: ["sm", "md", "lg"], hosts: ["page", "float", "overlay"], skeleton: <SkeletonStat />,
  async load(source) { if (!source.agentsSummary) throw new Error("This gateway has no agent summary."); return source.agentsSummary(); },
  view({ data, size }) {
    const busy = data.filter((a) => a.status && a.status !== "idle");
    if (size === "sm") return <div className="wg-health wg-health--compact"><span className="wg-health__value">{busy.length}</span><span className="wg-health__label">of {data.length} active</span></div>;
    return <List rows={data.map((a) => ({ k: a.id, a: a.display_name ?? a.id, b: a.status ?? "idle" }))} empty="No agents." />;
  },
};

export const openTasksWidget: WidgetDef<void, Task[]> = {
  kind: "tasks.open", title: "Open tasks", about: "Track running and waiting tasks", sizes: ["sm", "md", "lg"], hosts: ["page", "float", "overlay"], skeleton: <SkeletonStat />,
  async load(source) { return (await source.tasks()).filter((t) => OPEN.has(String(t.state))); },
  view({ data, size }) {
    if (size === "sm") return <div className="wg-health wg-health--compact"><span className="wg-health__value">{data.length}</span><span className="wg-health__label">open tasks</span></div>;
    return <List rows={data.slice(0, size === "lg" ? 12 : 6).map((t) => ({ k: t.task_id, a: t.goal ?? t.task_id, b: String(t.state) }))} empty="No open tasks." />;
  },
};

export const recentChatsWidget: WidgetDef<void, SessionRow[]> = {
  kind: "chats.recent", title: "Recent chats", about: "Jump back into recent conversations", sizes: ["md", "lg"], hosts: ["page", "float", "overlay"], skeleton: <SkeletonStat />,
  async load(source) { return (await source.sessions()).slice(0, 10); },
  view({ data, size }) { return <List rows={data.slice(0, size === "lg" ? 10 : 5).map((s) => ({ k: s.session_id, a: s.title || "Conversation", b: s.created_at ? new Date((s.created_at > 1e12 ? s.created_at : s.created_at * 1000)).toLocaleString() : undefined }))} empty="No chats yet." />; },
};

export const approvalsWidget: WidgetDef<void, { session: string; count: number }[]> = {
  kind: "approvals.pending", title: "Approvals", about: "Count approvals waiting on you", sizes: ["sm", "md"], hosts: ["page", "float", "overlay", "menubar"], skeleton: <SkeletonStat />,
  async load(source) {
    if (!source.pendingApprovals) throw new Error("This gateway does not expose approvals.");
    const sessions = (await source.sessions()).slice(0, 20);
    const counts = await Promise.all(sessions.map(async (s) => ({ session: s.title || s.session_id, count: (await source.pendingApprovals!(s.session_id).catch(() => [])).length })));
    return counts.filter((c) => c.count > 0);
  },
  view({ data, size }) {
    const n = data.reduce((a, c) => a + c.count, 0);
    if (size === "sm") return <div className="wg-health wg-health--compact"><span className="wg-health__value">{n}</span><span className="wg-health__label">to approve</span></div>;
    return <List rows={data.map((c) => ({ k: c.session, a: c.session, b: `${c.count} waiting` }))} empty="Nothing waiting for approval." />;
  },
};

export const hostMetricsWidget: WidgetDef<void, Metrics> = {
  kind: "host.metrics", title: "This Mac", about: "Watch CPU, memory and gateway latency", sizes: ["sm", "md", "lg"], hosts: ["page", "float", "overlay"], skeleton: <SkeletonStat />,
  load: () => getJson<Metrics>("/v1/system/metrics"),
  view({ data, size }) {
    const n = data.now;
    if (size === "sm") return <div className="wg-health wg-health--compact"><span className="wg-health__value">{n.cpu == null ? "–" : `${Math.round(n.cpu)}%`}</span><span className="wg-health__label">CPU · {n.mem == null ? "–" : `${Math.round(n.mem)}%`} RAM</span></div>;
    return (
      <div className="wg-metrics">
        <p><strong>CPU</strong> {n.cpu == null ? "–" : `${Math.round(n.cpu)}%`} · <strong>RAM</strong> {n.mem == null ? "–" : `${Math.round(n.mem)}%`} · <strong>Gateway</strong> {n.gateway.ok ? `${n.gateway.latency_ms} ms` : "down"}</p>
        <Sparkline points={data.history.map((s) => s.cpu ?? 0)} label="CPU %" height={size === "lg" ? 64 : 40} />
      </div>
    );
  },
};

registerWidget(agentsStatusWidget);
registerWidget(openTasksWidget);
registerWidget(recentChatsWidget);
registerWidget(approvalsWidget);
registerWidget(hostMetricsWidget);
