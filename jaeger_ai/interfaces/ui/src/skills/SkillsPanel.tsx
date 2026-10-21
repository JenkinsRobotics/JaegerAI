import { useEffect, useState } from "react";
import type { JaegerSource } from "../api/source";
export function SkillsPanel({ source }: { source: JaegerSource }) {
  const [query, setQuery] = useState(""), [attempt, setAttempt] = useState(0);
  const [rows, setRows] = useState<Awaited<ReturnType<NonNullable<JaegerSource["skills"]>>>>();
  const [error, setError] = useState<string>(), [loading, setLoading] = useState(false);
  useEffect(() => {
    let live = true; setLoading(true);
    const timer = setTimeout(() => { void source.skills?.(query).then(value => { if (live) { setRows(value); setError(undefined); } }, e => { if (live) setError(String((e as Error).message ?? e)); }).finally(() => { if (live) setLoading(false); }); }, 150);
    return () => { live = false; clearTimeout(timer); };
  }, [source, query, attempt]);
  if (!source.skills) return <p>Skills catalog is unavailable from this host.</p>;
  return <section aria-label="Skills catalog"><label>Find skill <input aria-label="Find skill" value={query} onChange={e => setQuery(e.target.value)} /></label>
    <p>Discovered Gateway playbooks. Lifecycle is reported by the registry; this view does not install, publish or grant tools.</p>
    {loading && <p role="status">Loading skills…</p>}{error && <p role="alert">Couldn't load skills: {error} <button type="button" onClick={() => setAttempt(n => n + 1)}>Retry skills</button></p>}
    {rows && <p>{rows.count} matching skills</p>}
    {rows?.skills.map(skill => <article className="jg-card" key={`${skill.category}/${skill.name}`}><strong>{skill.name}</strong><p>{skill.description}</p><p>{skill.category} · {skill.lifecycle}</p></article>)}
  </section>;
}
