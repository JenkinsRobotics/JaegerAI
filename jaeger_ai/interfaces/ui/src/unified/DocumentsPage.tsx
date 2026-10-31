/**
 * Documents (unified UI): Markdown documents stored by the WebUI (~/.jaeger/documents) with an
 * editor, live preview, and AI edit actions run on a local Ollama model (selection or whole
 * document; the result is shown for you to accept or discard). Saves check for conflicts.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { Markdown } from "../chat/Markdown";
import { Empty, Segmented, Sheet, SkeletonRows, useToast, PageHead } from "./ui";
import { getJson, sendJson } from "./webui";
import { isCloud, isEmbedding, loadModels, type LocalModel } from "./models";

interface DocMeta { id: string; title: string; updated_at: number; chars: number }
interface Doc { id: string; title: string; body: string; updated_at: number }
const ACTIONS = [["improve", "Improve"], ["fix", "Fix grammar"], ["shorten", "Shorten"], ["expand", "Expand"], ["summarize", "Summarize"], ["outline", "Outline"]] as const;

export function DocumentsPage({ params }: { params: URLSearchParams }) {
  const toast = useToast();
  const [docs, setDocs] = useState<DocMeta[] | null>(null);
  const [doc, setDoc] = useState<Doc>();
  const [draft, setDraft] = useState({ title: "", body: "" });
  const [mode, setMode] = useState<"edit" | "split" | "preview">("split");
  const [models, setModels] = useState<LocalModel[]>([]);
  const [model, setModel] = useState("");
  const [ai, setAi] = useState<{ action: string; from: number; to: number; original: string; text?: string; error?: string }>();
  const [custom, setCustom] = useState("");
  const [err, setErr] = useState<string>();
  const area = useRef<HTMLTextAreaElement>(null);
  const dirty = doc ? draft.title !== doc.title || draft.body !== doc.body : false;
  const list = useCallback(() => getJson<{ documents: DocMeta[] }>("/v1/documents").then((r) => setDocs(r.documents), (e: Error) => setErr(e.message)), []);
  const open = useCallback(async (id: string) => {
    try { const d = await getJson<Doc>(`/v1/documents/${id}`); setDoc(d); setDraft({ title: d.title, body: d.body }); } catch (e) { toast((e as Error).message, "error"); }
  }, [toast]);
  useEffect(() => { void list(); loadModels().then((r) => { const m = r.models.filter((x) => !isEmbedding(x)); setModels(m); setModel((m.find((x) => !isCloud(x)) ?? m[0])?.name ?? ""); }, () => {}); }, [list]);
  useEffect(() => { const id = params.get("doc"); if (id) void open(id); }, [params, open]);
  const save = useCallback(async () => {
    if (!doc) return;
    try { const d = await sendJson<Doc>("PUT", `/v1/documents/${doc.id}`, { ...draft, expected_updated_at: doc.updated_at }); setDoc(d); toast("Saved"); void list(); }
    catch (e) { toast((e as Error).message, "error"); }
  }, [doc, draft, toast, list]);
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key === "s" && doc) { e.preventDefault(); void save(); } };
    addEventListener("keydown", k); return () => removeEventListener("keydown", k);
  }, [save, doc]);
  const create = async () => {
    try { const d = await sendJson<Doc>("POST", "/v1/documents", { title: "Untitled", body: "# Untitled\n\n" }); await list(); setDoc(d); setDraft({ title: d.title, body: d.body }); } catch (e) { toast((e as Error).message, "error"); }
  };
  const remove = async () => {
    if (!doc || !confirm(`Delete “${doc.title}”?`)) return;
    try { await sendJson("DELETE", `/v1/documents/${doc.id}`); setDoc(undefined); await list(); toast("Deleted"); } catch (e) { toast((e as Error).message, "error"); }
  };
  const runAi = async (action: string, instruction?: string) => {
    const el = area.current; const from = el && el.selectionEnd > el.selectionStart ? el.selectionStart : 0; const to = el && el.selectionEnd > el.selectionStart ? el.selectionEnd : draft.body.length;
    const original = draft.body.slice(from, to);
    setAi({ action, from, to, original });
    try { const r = await sendJson<{ text: string }>("POST", "/v1/documents/ai-edit", { action, instruction, text: original, model }); setAi({ action, from, to, original, text: r.text }); }
    catch (e) { setAi({ action, from, to, original, error: (e as Error).message }); }
  };
  return (
    <div className="jg-u-page">
      <PageHead title="Documents" subtitle="Markdown documents with AI editing on your local models." actions={<><button type="button" className="jg-u-btn jg-u-btn--primary" onClick={() => void create()}>New document</button></>} />
      {err && <p className="jg-u-error" role="alert">{err}</p>}
      <div className="jg-docs">
        <nav className="jg-u-card jg-docs__list" aria-label="Documents">
          {!docs ? <SkeletonRows /> : !docs.length ? <Empty title="No documents" /> : (
            <ul className="jg-u-list">{docs.map((d) => (
              <li key={d.id}><button type="button" className="jg-u-row" aria-current={d.id === doc?.id || undefined} onClick={() => void open(d.id)}>
                <span className="jg-u-row__text"><strong>{d.title}</strong><span>{new Date(d.updated_at * 1000).toLocaleString()} · {d.chars} chars</span></span>
              </button></li>))}</ul>)}
        </nav>
        {!doc ? <section className="jg-u-card"><Empty title="Open or create a document" action={<button type="button" className="jg-u-btn" onClick={() => void create()}>New document</button>} /></section> : (
          <section className="jg-u-card jg-docs__editor" aria-label="Editor">
            <div className="jg-ui-toolbar jg-spread">
              <input className="jg-docs__title" aria-label="Title" value={draft.title} maxLength={200} onChange={(e) => setDraft((d) => ({ ...d, title: e.target.value }))} />
              <div className="jg-ui-toolbar">
                <Segmented label="Layout" value={mode} onChange={setMode} options={[{ value: "edit", label: "Edit" }, { value: "split", label: "Split" }, { value: "preview", label: "Preview" }]} />
                <button type="button" className="jg-u-btn jg-u-btn--primary" disabled={!dirty} onClick={() => void save()}>{dirty ? "Save ⌘S" : "Saved"}</button>
                <button type="button" className="jg-u-btn jg-u-btn--danger" onClick={() => void remove()}>Delete</button>
              </div>
            </div>
            <div className="jg-ui-toolbar jg-docs__ai" aria-label="AI edit">
              <select className="jg-u-search" aria-label="AI model" value={model} onChange={(e) => setModel(e.target.value)} disabled={!models.length}>{models.map((m) => <option key={m.name} value={m.name}>{m.name}</option>)}</select>
              {ACTIONS.map(([id, text]) => <button key={id} type="button" className="jg-u-icon-btn" disabled={!model || Boolean(ai && !ai.text && !ai.error)} onClick={() => void runAi(id)}>{text}</button>)}
              <form className="jg-row" onSubmit={(e) => { e.preventDefault(); if (custom.trim()) void runAi("custom", custom); }}>
                <input className="jg-u-search jg-minw-select" placeholder="Custom instruction…" aria-label="Custom AI instruction" value={custom} onChange={(e) => setCustom(e.target.value)} />
              </form>
              <span className="jg-u-note">Applies to the selection, or the whole document.</span>
            </div>
            <div className="jg-docs__panes" data-mode={mode}>
              {mode !== "preview" && <textarea ref={area} aria-label="Markdown" value={draft.body} onChange={(e) => setDraft((d) => ({ ...d, body: e.target.value }))} spellCheck />}
              {mode !== "edit" && <div className="jg-docs__preview"><Markdown text={draft.body} /></div>}
            </div>
          </section>)}
      </div>
      {ai && (
        <Sheet title={`AI: ${ai.action}`} onClose={() => setAi(undefined)}>
          {!ai.text && !ai.error ? <SkeletonRows n={4} /> : ai.error ? <p className="jg-u-error" role="alert">{ai.error}</p> : <div className="jg-docs__preview jg-scroll-half"><Markdown text={ai.text!} /></div>}
          <div className="jg-ui-actions"><button type="button" className="jg-u-btn" onClick={() => setAi(undefined)}>Discard</button>
            <button type="button" className="jg-u-btn jg-u-btn--primary" disabled={!ai.text} onClick={() => { setDraft((d) => ({ ...d, body: d.body.slice(0, ai.from) + ai.text + d.body.slice(ai.to) })); setAi(undefined); }}>Replace {ai.from === 0 && ai.to === draft.body.length ? "document" : "selection"}</button></div>
        </Sheet>)}
    </div>
  );
}
