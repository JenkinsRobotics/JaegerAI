/** Research › Knowledge › Notes: external note sources (Joplin, Obsidian, Notion, wiki MCP servers)
 * from the WebUI's read-only /api/notes endpoints. Search and preview are Joplin-only server-side. */
import { useEffect, useState } from "react";
import { getJson } from "./webui";
import { Markdown } from "../chat/Markdown";
import { Badge, Empty, SkeletonRows } from "./ui";

export interface NoteSource { name: string; label: string; enabled: boolean; active: boolean; status: string; tool_count: number }
export interface NotesSourcesResponse { enabled: boolean; sources: NoteSource[]; recent_ai_notes?: { id: string; title: string }[] }
interface NoteHit { id: string; title: string; snippet?: string }
interface Note { id: string; title: string; body: string }

export function NotesSources() {
  const [data, setData] = useState<NotesSourcesResponse | null>(null);
  const [err, setErr] = useState<string>();
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<NoteHit[] | null>(null);
  const [note, setNote] = useState<Note>();
  useEffect(() => { getJson<NotesSourcesResponse>("/api/notes/sources").then(setData, (e: Error) => setErr(e.message)); }, []);
  const joplin = !!data?.sources.some((s) => s.name.toLowerCase().includes("joplin") && s.active);
  useEffect(() => {
    if (!joplin || !q) { setHits(null); return; }
    const t = setTimeout(() => getJson<{ results: NoteHit[] }>(`/api/notes/search?source=joplin&q=${encodeURIComponent(q)}`).then((r) => setHits(r.results), (e: Error) => setErr(e.message)), 300);
    return () => clearTimeout(t);
  }, [q, joplin]);
  const open = (id: string) => getJson<{ note: Note }>(`/api/notes/item?source=joplin&id=${encodeURIComponent(id)}`).then((r) => setNote(r.note), (e: Error) => setErr(e.message));
  if (err) return <p className="jg-u-error">{err}</p>;
  if (!data) return <SkeletonRows />;
  if (!data.enabled) return <Empty title="Notes sources are off">Turn on external notes sources in Settings to browse Joplin, Obsidian or Notion here.</Empty>;
  const list = hits ?? data.recent_ai_notes ?? [];
  return (
    <div className="jg-ui-split">
      <section className="jg-u-card" aria-label="Notes sources">
        {!data.sources.length ? <Empty title="No notes sources connected" /> : (
          <ul className="jg-u-list">{data.sources.map((s) => <li key={s.name} className="jg-u-row"><span className="jg-u-row__text"><strong>{s.label}</strong></span><Badge>{s.active ? "active" : s.status}</Badge></li>)}</ul>)}
        {joplin && <>
          <input className="jg-u-search jg-mb-3" type="search" placeholder="Search Joplin" aria-label="Search Joplin" value={q} onChange={(e) => setQ(e.target.value)} />
          {!list.length ? <Empty title={q ? "No results" : "No recent notes"} /> : (
            <ul className="jg-u-list">{list.map((n) => <li key={n.id}><button type="button" className="jg-u-row" aria-current={note?.id === n.id || undefined} onClick={() => open(n.id)}><span className="jg-u-row__text"><strong>{n.title}</strong></span></button></li>)}</ul>)}
        </>}
      </section>
      <aside className="jg-ui-inspector" aria-label="Note">{note ? <><h3>Note</h3><strong>{note.title}</strong><div className="jg-research__report"><Markdown text={note.body} /></div></> : <Empty title="Select a note" />}</aside>
    </div>
  );
}
