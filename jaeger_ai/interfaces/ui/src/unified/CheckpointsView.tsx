/** Read-only checkpoint history for a Gateway session workspace. */
import { useEffect, useState } from "react";
import type { JaegerSource } from "../api/source";
import type { SessionRow } from "../api/types";
import { Empty, PageHead } from "./ui";
import { getJson } from "./webui";
import "./workspaceBrowser.css";

type Checkpoint = { id: string; message: string; date: string; date_display: string; files: number; files_changed: number };
const query = (path: string, values: Record<string, string>) => `${path}?${new URLSearchParams(values)}`;

export function CheckpointsView({ source, params }: { source: JaegerSource; params: URLSearchParams }) {
  const requested = params.get("session") ?? "";
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [sessionId, setSessionId] = useState(requested);
  const [checkpoints, setCheckpoints] = useState<Checkpoint[]>([]);
  const [selected, setSelected] = useState("");
  const [diff, setDiff] = useState("");
  const [changed, setChanged] = useState(0);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);

  useEffect(() => { let live = true; source.sessions().then(rows => { if (live) { const available = rows.filter(row => row.workspace); setSessions(available); setSessionId(id => id || available[0]?.session_id || ""); } }, e => { if (live) setError((e as Error).message); }); return () => { live = false; }; }, [source]);
  useEffect(() => { setSessionId(requested); setSelected(""); }, [requested]);
  useEffect(() => {
    if (!sessionId) return;
    const controller = new AbortController(); setError(""); setCheckpoints([]); setSelected("");
    getJson<{ checkpoints: Checkpoint[] }>(query("/api/checkpoints/list", { session_id: sessionId }), controller.signal)
      .then(data => { if (!controller.signal.aborted) setCheckpoints(data.checkpoints); }, e => { if (!controller.signal.aborted) setError((e as Error).message); });
    return () => controller.abort();
  }, [sessionId, revision]);
  useEffect(() => {
    if (!sessionId || !selected) return;
    const controller = new AbortController(); setDiff(""); setChanged(0);
    getJson<{ diff: string; total_changes: number }>(query("/api/checkpoints/diff", { session_id: sessionId, checkpoint: selected }), controller.signal)
      .then(data => { if (!controller.signal.aborted) { setDiff(data.diff || "No changes from the current workspace."); setChanged(data.total_changes); } }, e => { if (!controller.signal.aborted) setDiff((e as Error).message); });
    return () => controller.abort();
  }, [sessionId, selected]);
  return <div className="jg-u-page jg-workspace-browser">
    <PageHead title="Checkpoints" subtitle="Inspect saved workspace versions. Read only." actions={<button type="button" className="jg-u-btn" onClick={() => setRevision(v => v + 1)}>Refresh</button>} />
    <label className="jg-workspace-browser__session">Session <select aria-label="Checkpoint session" value={sessionId} onChange={e => setSessionId(e.target.value)}><option value="">Choose a session</option>{sessions.map(s => <option key={s.session_id} value={s.session_id}>{s.title || s.session_id}</option>)}</select></label>
    {!sessionId && <Empty title="No session selected">Choose a session with a workspace.</Empty>}
    {error && <p role="alert" className="jg-u-error">{error}</p>}
    {sessionId && !error && <div className="jg-workspace-browser__grid"><section className="jg-u-card" aria-label="Checkpoint list"><h3>Saved checkpoints</h3>{checkpoints.length === 0 && <p>No checkpoints found for this workspace.</p>}<ul>{checkpoints.map(item => <li key={item.id}><button type="button" onClick={() => setSelected(item.id)}>{item.message || "Checkpoint"} · {item.date_display || item.date} · {item.files_changed} changed files</button></li>)}</ul></section>
    <section className="jg-u-card" aria-label="Checkpoint diff"><h3>Diff {selected && `· ${changed} changed files`}</h3>{selected ? <pre>{diff || "Loading diff…"}</pre> : <p>Select a checkpoint to compare it with the current workspace.</p>}<button type="button" disabled title="Restore is unavailable until overwrite and undo safeguards are in place.">Restore</button><p>Restore is unavailable until overwrite and undo safeguards are in place.</p></section></div>}
  </div>;
}
