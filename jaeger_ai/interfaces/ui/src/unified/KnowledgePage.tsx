/** Memory & Skills (unified UI): browse the gateway's skills, each agent's memory notes (search,
 * versions, edit) and the document library. All reads and edits use existing gateway controls. */
import { useEffect, useMemo, useState } from "react";
import type { AgentMemorySnapshot, JaegerSource, LibraryDocument, SkillDetail } from "../api/source";
import type { Agent } from "../api/types";
import { label, visible } from "../agents/agentsLogic";
import { AgentMemory } from "../agents/AgentMemory";
import { Markdown } from "../chat/Markdown";
import { Badge, Empty, Segmented, SkeletonRows } from "./ui";

type Skill = { name: string; category: string; description: string; lifecycle: string };

export function KnowledgePage({ source, agents }: { source: JaegerSource; agents: Agent[] }) {
  const [tab, setTab] = useState<"skills" | "memory" | "library">("skills");
  return (
    <div className="jg-u-page">
      <header className="jg-u-page__head">
        <div><h1>Memory &amp; Skills</h1><p>What your agents know and can do.</p></div>
        <div className="jg-ui-toolbar"><Segmented label="Section" value={tab} onChange={setTab} options={[{ value: "skills", label: "Skills" }, { value: "memory", label: "Memory" }, { value: "library", label: "Library" }]} /></div>
      </header>
      {tab === "skills" && <Skills source={source} />}
      {tab === "memory" && <Memory source={source} agents={agents.filter(visible)} />}
      {tab === "library" && <Library source={source} />}
    </div>
  );
}

function Skills({ source }: { source: JaegerSource }) {
  const [q, setQ] = useState("");
  const [skills, setSkills] = useState<Skill[] | null>(null);
  const [err, setErr] = useState<string>();
  const [sel, setSel] = useState<Skill>();
  const [detail, setDetail] = useState<SkillDetail | null>();
  useEffect(() => { if (!source.skills) { setErr("This gateway doesn't list skills."); return; } source.skills().then((r) => setSkills(r.skills), (e: Error) => setErr(e.message)); }, [source]);
  useEffect(() => { setDetail(undefined); if (sel && source.skillDetail) source.skillDetail(sel.name, sel.category).then(setDetail, () => setDetail(null)); }, [sel, source]);
  const groups = useMemo(() => {
    const m = new Map<string, Skill[]>();
    for (const s of skills ?? []) if (!q || `${s.name} ${s.description} ${s.category}`.toLowerCase().includes(q.toLowerCase())) m.set(s.category, [...(m.get(s.category) ?? []), s]);
    return [...m.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [skills, q]);
  return (
    <div className="jg-ui-split">
      <section className="jg-u-card" aria-label="Skills">
        <div className="jg-ui-toolbar" style={{ justifyContent: "space-between", marginBottom: 12 }}>
          <h2 style={{ margin: 0 }}>Skills {skills && <Badge>{skills.length}</Badge>}</h2>
          <input className="jg-u-search" type="search" placeholder="Search skills" aria-label="Search skills" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        {err ? <p className="jg-u-error">{err}</p> : !skills ? <SkeletonRows n={6} /> : !groups.length ? <Empty title="No skills match" /> : groups.map(([cat, list]) => (
          <div key={cat} className="jg-kn__group"><h3>{cat} <span className="jg-u-count">{list.length}</span></h3>
            <ul className="jg-u-list">{list.map((s) => (
              <li key={`${cat}/${s.name}`}><button type="button" className="jg-u-row" aria-current={sel === s || undefined} onClick={() => setSel(s)}>
                <span className="jg-u-row__text"><strong>{s.name}</strong><span>{s.description}</span></span></button></li>))}</ul></div>))}
      </section>
      <aside className="jg-ui-inspector" aria-label="Skill details">
        {!sel ? <Empty title="Select a skill" /> : (<>
          <h3>{sel.category}</h3><strong>{sel.name}</strong><p className="jg-u-note" style={{ margin: 0 }}>{sel.description}</p>
          <span><Badge>{sel.lifecycle}</Badge></span>
          {detail === undefined && source.skillDetail ? <SkeletonRows /> : detail ? (
            <dl className="jg-ui-kv">
              <dt>Origin</dt><dd>{detail.origin}</dd><dt>Tier</dt><dd>{detail.tier}</dd><dt>Availability</dt><dd>{detail.availability}</dd>
              {detail.platforms.length > 0 && <><dt>Platforms</dt><dd>{detail.platforms.join(", ")}</dd></>}
              {detail.requires_tools.length > 0 && <><dt>Needs tools</dt><dd>{detail.requires_tools.join(", ")}</dd></>}
              {detail.tags.length > 0 && <><dt>Tags</dt><dd>{detail.tags.join(", ")}</dd></>}
            </dl>) : null}
        </>)}
      </aside>
    </div>
  );
}

function Memory({ source, agents }: { source: JaegerSource; agents: Agent[] }) {
  const [agentId, setAgentId] = useState(agents[0]?.id ?? "");
  const [q, setQ] = useState("");
  const [snap, setSnap] = useState<AgentMemorySnapshot | null>(null);
  const [err, setErr] = useState<string>();
  const [editing, setEditing] = useState(false);
  const [n, setN] = useState(0);
  useEffect(() => { if (!agentId && agents[0]) setAgentId(agents[0].id); }, [agents, agentId]);
  useEffect(() => {
    if (!source.agentMemory || !agentId) return;
    setSnap(null); setErr(undefined);
    const t = setTimeout(() => source.agentMemory!.read(agentId, q || undefined).then(setSnap, (e: Error) => setErr(e.message)), q ? 300 : 0);
    return () => clearTimeout(t);
  }, [source, agentId, q, n]);
  if (!source.agentMemory) return <Empty title="Memory unavailable">This gateway doesn't expose agent memory.</Empty>;
  return (
    <div className="jg-ui-split">
      <section className="jg-u-card" aria-label="Memory">
        <div className="jg-ui-toolbar" style={{ marginBottom: 12 }}>
          <select className="jg-u-search" aria-label="Agent" value={agentId} onChange={(e) => setAgentId(e.target.value)}>{agents.map((a) => <option key={a.id} value={a.id}>{label(a)}</option>)}</select>
          <input className="jg-u-search" type="search" placeholder="Search memory" aria-label="Search memory" value={q} onChange={(e) => setQ(e.target.value)} />
          {snap?.editable && <button type="button" className="jg-u-btn" onClick={() => setEditing(true)}>Edit</button>}
        </div>
        {err ? <p className="jg-u-error">{err}</p> : !snap ? <SkeletonRows n={5} /> : q && snap.search ? (
          snap.search.matches.length ? <ul className="jg-u-list">{snap.search.matches.map((m) => <li key={m.line} className="jg-kn__match"><small>line {m.line}</small> {m.text}</li>)}</ul> : <Empty title="No matches" />
        ) : snap.notes.trim() ? <div className="jg-research__report"><Markdown text={snap.notes} /></div> : <Empty title="No memory notes yet" />}
      </section>
      <aside className="jg-ui-inspector" aria-label="Memory details">
        {!snap ? <SkeletonRows /> : (<>
          <h3>Usage</h3>
          <dl className="jg-ui-kv"><dt>Size</dt><dd>{snap.chars} / {snap.max_chars} chars</dd><dt>In prompt</dt><dd>{snap.loaded_in_specialist_prompt ? `${snap.prompt_chars} chars${snap.prompt_truncated ? " (truncated)" : ""}` : "Not loaded"}</dd><dt>Editable</dt><dd>{snap.editable ? "Yes" : "No"}</dd></dl>
          <h3>Versions</h3>
          {snap.versions.length ? <ul className="jg-u-list">{snap.versions.slice(0, 8).map((v) => <li key={v.revision} className="jg-u-note">{new Date(v.saved_at * 1000).toLocaleString()}</li>)}</ul> : <p className="jg-u-note">No earlier versions.</p>}
        </>)}
      </aside>
      {editing && <AgentMemory agentId={agentId} controls={source.agentMemory} onClose={() => { setEditing(false); setN((x) => x + 1); }} />}
    </div>
  );
}

function Library({ source }: { source: JaegerSource }) {
  const [docs, setDocs] = useState<{ id: string; title: string }[] | null>(null);
  const [q, setQ] = useState("");
  const [doc, setDoc] = useState<LibraryDocument>();
  const [err, setErr] = useState<string>();
  useEffect(() => {
    if (!source.library) { setErr("This gateway has no document library."); return; }
    const t = setTimeout(() => (q ? source.library!.search(q).then((r) => setDocs(r.results)) : source.library!.list().then((r) => setDocs(r.documents.filter((d) => !d.archived)))).catch((e: Error) => setErr(e.message)), q ? 300 : 0);
    return () => clearTimeout(t);
  }, [source, q]);
  return (
    <div className="jg-ui-split">
      <section className="jg-u-card" aria-label="Library">
        <input className="jg-u-search" type="search" placeholder="Search library" aria-label="Search library" value={q} onChange={(e) => setQ(e.target.value)} style={{ marginBottom: 12 }} />
        {err ? <p className="jg-u-error">{err}</p> : !docs ? <SkeletonRows /> : !docs.length ? <Empty title={q ? "No results" : "Library is empty"} /> : (
          <ul className="jg-u-list">{docs.map((d) => <li key={d.id}><button type="button" className="jg-u-row" aria-current={doc?.id === d.id || undefined} onClick={() => source.library!.read(d.id).then(setDoc, (e: Error) => setErr(e.message))}><span className="jg-u-row__text"><strong>{d.title}</strong></span></button></li>)}</ul>)}
      </section>
      <aside className="jg-ui-inspector" aria-label="Document">{doc ? <><h3>Document</h3><strong>{doc.title}</strong><div className="jg-research__report"><Markdown text={doc.content} /></div></> : <Empty title="Select a document" />}</aside>
    </div>
  );
}
