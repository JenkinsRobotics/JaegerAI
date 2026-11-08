/** Memory & Skills (unified UI): browse the gateway's skills, each agent's memory notes (search,
 * versions, edit) and the document library. All reads and edits use existing gateway controls. */
import { useEffect, useMemo, useState, type DependencyList } from "react";
import type { AgentMemoryControls, JaegerSource } from "../api/source";
import type { Agent } from "../api/types";
import { label, visible } from "../agents/agentsLogic";
import { AgentMemory } from "../agents/AgentMemory";
import { Markdown } from "../chat/Markdown";
import { NotesSources } from "./NotesSources";
import { Badge, Empty, Segmented, SkeletonRows, PageHead } from "./ui";

type Skill = { name: string; category: string; description: string; lifecycle: string };

// Each read owns its result, including failures. Cleanup invalidates requests already
// dispatched, not only the debounce timer; identity also hides old data on render.
function useKnowledgeRead<T>(load: () => Promise<T>, deps: DependencyList, delay = 0) {
  const [attempt, setAttempt] = useState(0);
  const request = useMemo(() => ({ load, delay }), [...deps, attempt]);
  const [result, setResult] = useState<{ request: typeof request; value?: T; error?: string }>();
  useEffect(() => {
    let current = true;
    const timer = setTimeout(() => {
      Promise.resolve().then(request.load).then(
        (value) => { if (current) setResult({ request, value }); },
        (error: unknown) => { if (current) setResult({ request, error: error instanceof Error ? error.message : String(error) }); },
      );
    }, request.delay);
    return () => { current = false; clearTimeout(timer); };
  }, [request]);
  return { value: result?.request === request ? result.value : undefined,
    error: result?.request === request ? result.error : undefined,
    retry: () => setAttempt((n) => n + 1) };
}

function ReadFailure({ error, retry }: { error: string; retry: () => void }) {
  return <div role="alert"><p className="jg-u-error">{error}</p><button type="button" className="jg-u-btn" onClick={retry}>Retry</button></div>;
}

export function KnowledgePage({ source, agents }: { source: JaegerSource; agents: Agent[] }) {
  const [tab, setTab] = useState<"skills" | "memory" | "library" | "notes">("skills");
  return (
    <div className="jg-u-page">
      <PageHead title={<>Memory &amp; Skills</>} subtitle="What your agents know and can do." actions={<><Segmented label="Section" value={tab} onChange={setTab} options={[{ value: "skills", label: "Skills" }, { value: "memory", label: "Memory" }, { value: "library", label: "Library" }, { value: "notes", label: "Notes" }]} /></>} />
      {tab === "skills" && <Skills source={source} />}
      {tab === "memory" && <Memory source={source} agents={agents.filter(visible)} />}
      {tab === "library" && <Library source={source} />}
      {tab === "notes" && <NotesSources />}
    </div>
  );
}

function Skills({ source }: { source: JaegerSource }) {
  const [q, setQ] = useState("");
  const [sel, setSel] = useState<Skill>();
  const list = useKnowledgeRead(async () => source.skills ? (await source.skills()).skills : [], [source]);
  const skills = list.value;
  const details = useKnowledgeRead(async () => {
    if (!sel || !source.skillDetail) return null;
    const value = await source.skillDetail(sel.name, sel.category);
    if (value.name !== sel.name || value.category !== sel.category) throw new Error("Skill identity mismatch");
    return value;
  }, [source, sel]);
  const detail = details.value;
  const groups = useMemo(() => {
    const m = new Map<string, Skill[]>();
    for (const s of skills ?? []) if (!q || `${s.name} ${s.description} ${s.category}`.toLowerCase().includes(q.toLowerCase())) m.set(s.category, [...(m.get(s.category) ?? []), s]);
    return [...m.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [skills, q]);
  return (
    <div className="jg-ui-split">
      <section className="jg-u-card" aria-label="Skills">
        <div className="jg-ui-toolbar jg-spread jg-mb-3">
          <h2 className="jg-m-0">Skills {skills && <Badge>{skills.length}</Badge>}</h2>
          <input className="jg-u-search" type="search" placeholder="Search skills" aria-label="Search skills" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        {!source.skills ? <Empty title="Skills unavailable">This gateway doesn't list skills.</Empty> : list.error ? <ReadFailure error={list.error} retry={list.retry} /> : !skills ? <SkeletonRows n={6} /> : !groups.length ? <Empty title={q ? "No skills match" : "No skills installed"} /> : groups.map(([cat, list]) => (
          <div key={cat} className="jg-kn__group"><h3>{cat} <span className="jg-u-count">{list.length}</span></h3>
            <ul className="jg-u-list">{list.map((s) => (
              <li key={`${cat}/${s.name}`}><button type="button" className="jg-u-row" aria-current={(sel?.name === s.name && sel?.category === s.category) || undefined} onClick={() => setSel(s)}>
                <span className="jg-u-row__text"><strong>{s.name}</strong><span>{s.description}</span></span></button></li>))}</ul></div>))}
      </section>
      <aside className="jg-ui-inspector" aria-label="Skill details">
        {!sel ? <Empty title="Select a skill" /> : (<>
          <h3>{sel.category}</h3><strong>{sel.name}</strong><p className="jg-u-note jg-m-0">{sel.description}</p>
          <span><Badge>{sel.lifecycle}</Badge></span>
          {!source.skillDetail ? <Empty title="Skill details unavailable" /> : details.error ? <ReadFailure error={details.error} retry={details.retry} /> : detail === undefined ? <SkeletonRows /> : detail ? (
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
  const [editing, setEditing] = useState<{ agentId: string; controls: AgentMemoryControls }>();
  const [n, setN] = useState(0);
  // Never silently select a different agent when the selected one disappears.
  const selectedExists = agents.some((a) => a.id === agentId);
  useEffect(() => { if (!agentId && agents[0]) setAgentId(agents[0].id); }, [agents, agentId]);
  const memory = useKnowledgeRead(async () => {
    if (!source.agentMemory || !agentId || !selectedExists) return null;
    const value = await source.agentMemory.read(agentId, q || undefined);
    if (value.agent_id !== agentId) throw new Error("Memory identity mismatch");
    return value;
  }, [source, agentId, selectedExists, q, n], q ? 300 : 0);
  const snap = memory.value;
  if (!source.agentMemory) return <Empty title="Memory unavailable">This gateway doesn't expose agent memory.</Empty>;
  return (
    <div className="jg-ui-split">
      <section className="jg-u-card" aria-label="Memory">
        <div className="jg-ui-toolbar jg-mb-3">
          <select className="jg-u-search" aria-label="Agent" value={agentId} disabled={Boolean(editing) || !agents.length} onChange={(e) => setAgentId(e.target.value)}>{!selectedExists && <option value={agentId}>{agentId ? "Selected agent unavailable" : "No agent selected"}</option>}{agents.map((a) => <option key={a.id} value={a.id}>{label(a)}</option>)}</select>
          <input className="jg-u-search" type="search" placeholder="Search memory" aria-label="Search memory" value={q} onChange={(e) => setQ(e.target.value)} />
          {snap?.editable && <button type="button" className="jg-u-btn" onClick={() => setEditing({ agentId, controls: source.agentMemory! })}>Edit</button>}
        </div>
        {!agents.length ? <Empty title="No agents available" /> : !selectedExists ? <Empty title="Select an available agent" /> : memory.error ? <ReadFailure error={memory.error} retry={memory.retry} /> : !snap ? <SkeletonRows n={5} /> : q && snap.search ? (
          snap.search.matches.length ? <ul className="jg-u-list">{snap.search.matches.map((m) => <li key={m.line} className="jg-kn__match"><small>line {m.line}</small> {m.text}</li>)}</ul> : <Empty title="No matches" />
        ) : snap.notes.trim() ? <div className="jg-research__report"><Markdown text={snap.notes} /></div> : <Empty title="No memory notes yet" />}
      </section>
      <aside className="jg-ui-inspector" aria-label="Memory details">
        {!agents.length || !selectedExists ? <Empty title="No agent selected" /> : memory.error ? <Empty title="Memory details unavailable" /> : !snap ? <SkeletonRows /> : (<>
          <h3>Usage</h3>
          <dl className="jg-ui-kv"><dt>Size</dt><dd>{snap.chars} / {snap.max_chars} chars</dd><dt>In prompt</dt><dd>{snap.loaded_in_specialist_prompt ? `${snap.prompt_chars} chars${snap.prompt_truncated ? " (truncated)" : ""}` : "Not loaded"}</dd><dt>Editable</dt><dd>{snap.editable ? "Yes" : "No"}</dd></dl>
          <h3>Versions</h3>
          {snap.versions.length ? <ul className="jg-u-list">{snap.versions.slice(0, 8).map((v) => <li key={v.revision} className="jg-u-note">{new Date(v.saved_at * 1000).toLocaleString()}</li>)}</ul> : <p className="jg-u-note">No earlier versions.</p>}
        </>)}
      </aside>
      {editing && <AgentMemory key={editing.agentId} agentId={editing.agentId} controls={editing.controls} onClose={() => { setEditing(undefined); setN((x) => x + 1); }} />}
    </div>
  );
}

function Library({ source }: { source: JaegerSource }) {
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState<{ id: string; title: string }>();
  const list = useKnowledgeRead(async () => {
    if (!source.library) return [];
    return q ? (await source.library.search(q)).results : (await source.library.list()).documents.filter((d) => !d.archived);
  }, [source, q], q ? 300 : 0);
  const docs = list.value;
  const detail = useKnowledgeRead(async () => {
    if (!source.library || !selected) return null;
    const value = await source.library.read(selected.id);
    if (value.id !== selected.id) throw new Error("Document identity mismatch");
    return value;
  }, [source, selected]);
  const doc = detail.value;
  return (
    <div className="jg-ui-split">
      <section className="jg-u-card" aria-label="Library">
        <input className="jg-u-search jg-mb-3" type="search" placeholder="Search library" aria-label="Search library" value={q} onChange={(e) => setQ(e.target.value)} />
        {!source.library ? <Empty title="Library unavailable">This gateway has no document library.</Empty> : list.error ? <ReadFailure error={list.error} retry={list.retry} /> : !docs ? <SkeletonRows /> : !docs.length ? <Empty title={q ? "No results" : "Library is empty"} /> : (
          <ul className="jg-u-list">{docs.map((d) => <li key={d.id}><button type="button" className="jg-u-row" aria-current={selected?.id === d.id || undefined} onClick={() => setSelected(d)}><span className="jg-u-row__text"><strong>{d.title}</strong></span></button></li>)}</ul>)}
      </section>
      <aside className="jg-ui-inspector" aria-label="Document">{!source.library ? <Empty title="Document details unavailable" /> : selected ? <><h3>Document</h3><strong>{doc?.title ?? selected.title}</strong>{detail.error ? <ReadFailure error={detail.error} retry={detail.retry} /> : !doc ? <SkeletonRows /> : <><div className="jg-research__report"><Markdown text={doc.content} /></div></>}</> : <Empty title="Select a document" />}</aside>
    </div>
  );
}
