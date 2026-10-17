/* Read-only side panel for "N messages with X" (D4). Stub: lists the hand-off
 * records; the message list arrives with /v1/handoffs/{id}/messages. */
import { Dialog } from "@aether/ui";
import { useEffect, useState } from "react";
import type { JaegerSource } from "../api/source";
import type { Handoff } from "../api/types";

export function ExchangePanel({ source, handoffId, onClose }: { source: JaegerSource; handoffId: string | null; onClose: () => void }) {
  const [rows, setRows] = useState<Handoff[]>([]);
  useEffect(() => {
    if (!handoffId) return;
    source.handoffs().then((all) => setRows(all.filter((h) => h.id === handoffId)), () => setRows([]));
  }, [source, handoffId]);
  return (
    <Dialog open={Boolean(handoffId)} title="Exchange" onClose={onClose}>
      {rows.length ? rows.map((h) => (
        <p key={h.id} className="jg-muted">{h.task ?? h.id} · {h.status ?? "unknown"}</p>
      )) : <p className="jg-muted">Message history for this hand-off comes next.</p>}
    </Dialog>
  );
}
