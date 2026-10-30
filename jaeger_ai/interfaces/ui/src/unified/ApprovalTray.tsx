/**
 * Global approvals (unified UI): pending tool / handoff approvals from every recent chat,
 * on every page. Uses the same SessionApprovals + ApprovalCard the chat shows, so a
 * decision made here is the same gateway call (POST approve) and disappears from the chat too.
 */
import { useEffect, useState } from "react";
import type { JaegerSource } from "../api/source";
import { SessionApprovals } from "../chat/SessionApprovals";

const RECENT_SESSIONS = 12;

export function useApprovalSessions(source: JaegerSource, pollMs = 5000) {
  const [pending, setPending] = useState<{ sessionId: string; count: number; title?: string; agentId?: string | null }[]>([]);
  useEffect(() => {
    if (!source.pendingApprovals) return;
    let live = true;
    const read = async () => {
      try {
        const sessions = (await source.sessions()).slice(0, RECENT_SESSIONS);
        const rows = await Promise.all(sessions.map(async (s) => {
          const list = await source.pendingApprovals!(s.session_id).catch(() => []);
          return { sessionId: s.session_id, title: s.title, agentId: s.agent_id, count: list.filter((r) => r.status === "pending").length };
        }));
        if (live) setPending(rows.filter((r) => r.count > 0));
      } catch { /* gateway unreachable: keep the last read */ }
    };
    void read();
    const t = setInterval(() => void read(), pollMs);
    return () => { live = false; clearInterval(t); };
  }, [source, pollMs]);
  return pending;
}

export function approvalHost(source: JaegerSource) {
  return {
    pendingApprovals: (sessionId: string) => source.pendingApprovals?.(sessionId) ?? Promise.resolve([]),
    respondToConfirmation: (sessionId: string, approvalId: string, decision: "approve" | "deny") => source.approve(sessionId, approvalId, decision === "approve"),
  };
}

export function ApprovalList({ source, sessions, onOpenChat }: { source: JaegerSource; sessions: { sessionId: string; title?: string; agentId?: string | null }[]; onOpenChat?: (agentId?: string | null) => void }) {
  const host = approvalHost(source);
  if (!sessions.length) return <p className="jg-u-empty">Nothing is waiting for your approval.</p>;
  return <div className="jg-u-approvals">
    {sessions.map((s) => <div key={s.sessionId} className="jg-u-approvals__session">
      <button type="button" className="jg-u-link" onClick={() => onOpenChat?.(s.agentId)}>{s.title || "Conversation"}</button>
      <SessionApprovals sessionId={s.sessionId} host={host} />
    </div>)}
  </div>;
}

/** Dock badge + popover: approvals reachable from any page. */
export function ApprovalTray({ source, onOpenChat }: { source: JaegerSource; onOpenChat?: (agentId?: string | null) => void }) {
  const pending = useApprovalSessions(source);
  const [open, setOpen] = useState(false);
  const total = pending.reduce((n, p) => n + p.count, 0);
  if (!total && !open) return null;
  return <div className="jg-u-tray">
    <button type="button" className="jg-u-tray__button" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
      {total} approval{total === 1 ? "" : "s"} waiting
    </button>
    {open && <div className="jg-u-tray__panel" role="dialog" aria-label="Pending approvals">
      <ApprovalList source={source} sessions={pending} onOpenChat={(id) => { setOpen(false); onOpenChat?.(id); }} />
    </div>}
  </div>;
}
