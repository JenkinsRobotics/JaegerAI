import {SkillLifecycle} from "./SkillLifecycle";
import { useEffect, useRef, useState } from "react";
import type { JaegerSource, SkillDetail } from "../api/source";
export function SkillsPanel({ source }: { source: JaegerSource }) {
  const [detail, setDetail] = useState<SkillDetail>(), [detailError, setDetailError] = useState<string>(), [inspecting, setInspecting] = useState(false);
  const generation = useRef(0);
  useEffect(() => () => { generation.current++; }, [source]);
  const inspect = async (name: string, category: string) => {
    const current = ++generation.current; setInspecting(true); setDetail(undefined); setDetailError(undefined);
    try { const value = await source.skillDetail!(name, category); if (current !== generation.current) return;
      if (value.name !== name || value.category !== category) throw Error('Skill identity mismatch'); setDetail(value);
    } catch(e) { if(current === generation.current) setDetailError(String(e)); }
    finally { if(current === generation.current) setInspecting(false); }
  };
  const [query, setQuery] = useState(""), [attempt, setAttempt] = useState(0);
  const [rows, setRows] = useState<Awaited<ReturnType<NonNullable<JaegerSource["skills"]>>>>();
  const [error, setError] = useState<string>(), [loading, setLoading] = useState(false);
  useEffect(() => {
    let live = true; setLoading(true);
    const timer = setTimeout(() => { void source.skills?.(query).then(value => { if (live) { setRows(value); setError(undefined); } }, e => { if (live) setError(String((e as Error).message ?? e)); }).finally(() => { if (live) setLoading(false); }); }, 150);
    return () => { live = false; clearTimeout(timer); };
  }, [source, query, attempt]);
  if (!source.skills) return <p>Skills catalog is unavailable from this host.</p>;
  return <section aria-label="Skills catalog"><SkillLifecycle source={source}/><label>Find skill <input aria-label="Find skill" value={query} onChange={e => setQuery(e.target.value)} /></label>
    <p>Discovered Gateway playbooks. Lifecycle is reported by the registry; this view does not install, publish or grant tools.</p>
    {loading && <p role="status">Loading skills…</p>}{error && <p role="alert">Couldn't load skills: {error} <button type="button" onClick={() => setAttempt(n => n + 1)}>Retry skills</button></p>}
    {rows && <p>{rows.count} matching skills</p>}
    {rows?.skills.map(skill => <article className="jg-card" key={`${skill.category}/${skill.name}`}><strong>{skill.name}</strong><p>{skill.description}</p><p>{skill.category} · {skill.lifecycle}</p>{source.skillDetail && <button type="button" onClick={() => void inspect(skill.name, skill.category)}>Inspect {skill.name}</button>}</article>)}
    {inspecting && <p role="status">Reading skill metadata…</p>}{detailError && <p role="alert">{detailError}</p>}
    {detail && <section aria-label="Skill metadata"><h3>{detail.name}</h3><p>{detail.description}</p><p>Declared origin: {detail.origin} · {detail.lifecycle} · {detail.skill_class} · routing tier: {detail.tier}</p>
      <p>Origin is a registry declaration, not verified publisher identity. Availability is not probed. Inspection does not activate this skill, load toolsets or grant access.</p>
      {([['Platforms', detail.platforms], ['Required tools', detail.requires_tools], ['Optional tools', detail.optional_tools], ['Required toolsets', detail.requires_toolsets], ['Required plugins', detail.requires_plugins], ['Aliases', detail.aliases], ['Tags', detail.tags]] as [string,string[]][]).map(([title,values])=><p key={title}>{title}: {values.length ? values.join(', ') : 'None declared'}</p>)}
      <p>Registry auto-activation preference: {detail.auto_activate ? 'on' : 'off'}; actual execution remains subject to agent scope and policy.</p><button type="button" onClick={()=>{generation.current++;setDetail(undefined);setInspecting(false);}}>Close skill details</button>
    </section>}
  </section>;
}
