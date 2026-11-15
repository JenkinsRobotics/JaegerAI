import { useEffect, useState } from "react";
import type { JaegerSource, SkillRevision } from "../api/source";

type Version = { version: string; bytes: number; ts: string; origin: string; summary: string };

const when = (ts: string) => { const d = new Date(ts); return isNaN(d.getTime()) ? ts : d.toLocaleString(); };

/** Self-improvement log: skills Jaeger created or edited, with per-skill history and rollback. */
export function SkillRevisions({ source }: { source: JaegerSource }) {
  const api = source.skillRevisions;
  const [rows, setRows] = useState<SkillRevision[]>(), [error, setError] = useState(""), [attempt, setAttempt] = useState(0);
  const [open, setOpen] = useState<string>(), [versions, setVersions] = useState<Version[]>([]), [mutable, setMutable] = useState(false);
  const [preview, setPreview] = useState<{ version: string; content: string }>(), [notice, setNotice] = useState(""), [busy, setBusy] = useState(false);
  useEffect(() => { let live = true; void api?.recent().then(v => { if (live) { setRows(v.revisions); setError(""); } }, e => { if (live) setError(String((e as Error).message ?? e)); }); return () => { live = false; }; }, [api, attempt]);
  const show = async (name: string) => {
    if (open === name) { setOpen(undefined); return; }
    setOpen(name); setPreview(undefined); setNotice("");
    try { const h = await api!.history(name); setVersions(h.versions); setMutable(h.mutable); } catch (e) { setError(String(e)); }
  };
  const view = async (name: string, version: string) => { try { setPreview({ version, ...(await api!.version(name, version)) }); } catch (e) { setError(String(e)); } };
  const rollback = async (name: string, version: string) => {
    if (busy || !window.confirm(`Roll ${name} back to ${version}? The current text is kept as a version too.`)) return;
    setBusy(true); setNotice("");
    try { const r = await api!.rollback(name, version); setNotice(r.ok ? (r.changed ? `${name} restored from ${version} (now ${r.version}).` : `${name} already matches ${version}.`) : (r.error ?? "Rollback failed")); setAttempt(n => n + 1); const h = await api!.history(name); setVersions(h.versions); }
    catch (e) { setError(String(e)); } finally { setBusy(false); }
  };
  if (!api) return null;
  const latest = new Map<string, SkillRevision>();
  for (const r of rows ?? []) if (!latest.has(r.skill)) latest.set(r.skill, r);
  return <section aria-label="Skill self-improvement" className="skill-revisions">
    <h3>Self-improvement</h3>
    <p>After a task with several tool calls, Jaeger reviews the work and may save or update a skill. Every change is versioned; you can view or roll back any version.</p>
    {error && <p role="alert">{error} <button type="button" onClick={() => { setError(""); setAttempt(n => n + 1); }}>Retry</button></p>}
    {notice && <p role="status">{notice}</p>}
    {!rows && !error && <p>Loading revisions…</p>}
    {rows && latest.size === 0 && <p>No skill changes yet.</p>}
    <ul style={{ listStyle: "none", padding: 0 }}>
      {[...latest.values()].map(r => <li key={r.skill} style={{ borderTop: "1px solid var(--border, #3333)", padding: "6px 0" }}>
        <div style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
          <strong>{r.skill}</strong><span>{r.version}</span><span style={{ opacity: .7 }}>{r.origin === "self-improvement" ? "by Jaeger" : r.origin} · {when(r.ts)}</span>
          <button type="button" onClick={() => void show(r.skill)}>{open === r.skill ? "Hide history" : "History"}</button>
        </div>
        {r.summary && <div style={{ opacity: .85 }}>{r.summary}</div>}
        {open === r.skill && <div style={{ marginTop: 6 }}>
          {versions.length === 0 && <p>No saved versions for this skill (recorded before version history existed).</p>}
          {versions.map(v => <div key={v.version} style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
            <code>{v.version}</code><span style={{ opacity: .7 }}>{v.ts ? when(v.ts) : "original"}</span><span>{v.summary}</span>
            <button type="button" onClick={() => void view(r.skill, v.version)}>View</button>
            {mutable && v !== versions[0] && <button type="button" disabled={busy} onClick={() => void rollback(r.skill, v.version)}>Roll back to {v.version}</button>}
          </div>)}
          {preview && <pre style={{ maxHeight: 280, overflow: "auto", whiteSpace: "pre-wrap", fontSize: 12 }} aria-label={`${r.skill} ${preview.version}`}>{preview.content}</pre>}
        </div>}
      </li>)}
    </ul>
  </section>;
}
