/** Pending tool/handoff decisions survive navigation/reload without an active chat turn. */
import { useEffect, useRef, useState } from "react";
import type { PendingApproval } from "../api/source";
import { ApprovalCard } from "./ApprovalCard";

type Host = {
  pendingApprovals(sessionId: string): Promise<PendingApproval[]>;
  respondToConfirmation(sessionId: string, approvalId: string, decision: "approve" | "deny"): Promise<void>;
};

export function SessionApprovals({ sessionId, host, excludeIds = [] }: { sessionId: string; host: Host; excludeIds?: string[] }) {
  const resolved = useRef(new Set<string>());
  const deciding = useRef(false);
  const [rows, setRows] = useState<PendingApproval[]>([]);
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState<string>();
  useEffect(() => {
    let active = true;
    let reading = false;
    const read = async () => {
      if (reading) return;
      reading = true;
      try {
        const result = await host.pendingApprovals(sessionId);
        if (active) { setRows(result.filter((r) => !resolved.current.has(r.approval_id) && ["handoff", "tool", "tool_confirm"].includes(r.kind) && r.status === "pending" && r.session_id === sessionId)); setError(undefined); }
      } catch (e) { if (active) setError(String((e as Error).message ?? e)); }
      finally { reading = false; }
    };
    void read();
    const timer = setInterval(() => void read(), 1500);
    return () => { active = false; clearInterval(timer); };
  }, [host, sessionId]);
  const decide = async (id: string, decision: "approve" | "deny") => {
    if (deciding.current) return;
    deciding.current = true;
    setBusy(id);
    try {
      await host.respondToConfirmation(sessionId, id, decision);
      resolved.current.add(id);
      setRows((current) => current.filter((r) => r.approval_id !== id));
      setError(undefined);
    } catch (e) { setError(String((e as Error).message ?? e)); }
    finally { deciding.current = false; setBusy(undefined); }
  };
  return <div aria-label="Conversation approvals" aria-live="polite">
    {error && <p role="alert">Couldn’t load or decide approval: {error}</p>}
    {rows.filter(row => !excludeIds.includes(row.approval_id)).map((row) => <fieldset key={row.approval_id} disabled={Boolean(busy)} style={{ border: 0, padding: 0, margin: 0 }}>
      <ApprovalCard title={row.prompt} message={row.task ?? row.prompt} onDecide={(decision) => void decide(row.approval_id, decision)} />
    </fieldset>)}
  </div>;
}
