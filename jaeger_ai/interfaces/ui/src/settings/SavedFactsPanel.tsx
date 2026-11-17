import { useEffect, useState } from "react";
import type { JaegerSource, SavedFact } from "../api/source";

/** Facts Jaeger saved with `remember` (R7: one memory you can see). Same table the
 *  agent's recall/forget tools use; forgetting here is what "forget X" does in chat. */
export function SavedFactsPanel({ source }: { source: JaegerSource }) {
  const api = source.memoryFacts;
  const [facts, setFacts] = useState<SavedFact[]>(), [query, setQuery] = useState(""), [error, setError] = useState(""), [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    const t = window.setTimeout(() => void api?.list(query).then(r => { if (live) { setFacts(r.facts); setError(r.error ?? ""); } }, e => { if (live) setError(String((e as Error).message ?? e)); }), 200);
    return () => { live = false; window.clearTimeout(t); };
  }, [api, query, attempt]);
  if (!api) return null;
  const forget = async (f: SavedFact) => {
    if (!window.confirm(`Forget "${f.key}"? Jaeger stops using it from the next message.`)) return;
    try { await api.forget(f.key, f.subject); setAttempt(n => n + 1); } catch (e) { setError(String(e)); }
  };
  return <section aria-label="Saved facts" className="saved-facts">
    <h3>Saved facts</h3>
    <p>Things Jaeger remembered from your chats. It checks these before answering. Say "forget …" in chat or use Forget here.</p>
    <input type="search" aria-label="Search saved facts" placeholder="Search facts" value={query} onChange={e => setQuery(e.target.value)} style={{ width: "100%", marginBottom: 8 }} />
    {error && <p role="alert">{error}</p>}
    {!facts && !error && <p>Loading…</p>}
    {facts && facts.length === 0 && <p>No saved facts{query ? " match" : " yet"}.</p>}
    {facts && facts.length > 0 && <table style={{ width: "100%", fontSize: 12.5, borderCollapse: "collapse" }}>
      <thead><tr><th align="left">Fact</th><th align="left">Value</th><th align="left">About</th><th align="left">Updated</th><th /></tr></thead>
      <tbody>{facts.map(f => <tr key={`${f.subject}:${f.key}`} style={{ borderTop: "1px solid var(--border, #8883)" }}>
        <td style={{ verticalAlign: "top", padding: "4px 6px 4px 0" }}><code>{f.key}</code>{f.category ? <div style={{ opacity: .7 }}>{f.category}</div> : null}</td>
        <td style={{ verticalAlign: "top", padding: "4px 6px", maxWidth: 360, overflowWrap: "anywhere" }}>{f.value.length > 240 ? f.value.slice(0, 240) + "…" : f.value}</td>
        <td style={{ verticalAlign: "top", padding: "4px 6px" }}>{f.subject === "user" ? "You" : f.subject}</td>
        <td style={{ verticalAlign: "top", padding: "4px 6px", whiteSpace: "nowrap" }}>{f.updated_at ? new Date(f.updated_at).toLocaleDateString() : ""}</td>
        <td style={{ verticalAlign: "top" }}><button type="button" onClick={() => void forget(f)}>Forget</button></td>
      </tr>)}</tbody>
    </table>}
  </section>;
}
