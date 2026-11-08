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
function checkedDoc(value: Doc, expectedId?: string): Doc {
  if (!value || typeof value.id !== "string" || !value.id || (expectedId !== undefined && value.id !== expectedId) || typeof value.title !== "string" || typeof value.body !== "string" || typeof value.updated_at !== "number" || !Number.isFinite(value.updated_at)) throw Error("Invalid document response; your draft has been retained");
  return value;
}
type Draft = Pick<Doc, "title" | "body">;
interface StoredDraft { base: Doc; draft: Draft; unreconciled?: boolean }
function decodeDraft(raw: string, id: string): StoredDraft {
  const value = JSON.parse(raw) as StoredDraft;
  if (value.base?.id !== id || typeof value.base.updated_at !== "number" || !Number.isFinite(value.base.updated_at) || typeof value.base.title !== "string" || typeof value.base.body !== "string" || typeof value.draft?.title !== "string" || typeof value.draft.body !== "string") throw Error("invalid draft");
  return value;
}
const draftPrefix = "jaeger.ui.documents.draft.v1.";
const draftKey = (id: string) => `${draftPrefix}${id}`;
// Per-tab session storage survives workspace navigation and reload without overwriting another tab.
// Also serialize mutations across a workspace unmount/remount.
const writes = new Set<string>();
// Storage can be unavailable or full. Keep a session-only fallback through workspace navigation.
const volatileDrafts = new Map<string, StoredDraft>();
// Remain active even when the Documents workspace is unmounted.
if (typeof window !== "undefined") window.addEventListener("beforeunload", (event) => {
  let unsaved = volatileDrafts.size > 0;
  try { for (let i = 0; i < sessionStorage.length; i++) if (sessionStorage.key(i)?.startsWith(draftPrefix)) unsaved = true; }
  catch { /* The session-only fallback is checked above. */ }
  if (unsaved) { event.preventDefault(); event.returnValue = ""; }
});
const ACTIONS = [["improve", "Improve"], ["fix", "Fix grammar"], ["shorten", "Shorten"], ["expand", "Expand"], ["summarize", "Summarize"], ["outline", "Outline"]] as const;

export function DocumentsPage({ params }: { params: URLSearchParams }) {
  const toast = useToast();
  const [docs, setDocs] = useState<DocMeta[] | null>(null);
  const [doc, setDoc] = useState<Doc>();
  const [draft, setDraft] = useState({ title: "", body: "" });
  const [mode, setMode] = useState<"edit" | "split" | "preview">("split");
  const [models, setModels] = useState<LocalModel[]>([]);
  const [model, setModel] = useState("");
  const [modelError, setModelError] = useState<string>();
  const [ai, setAi] = useState<{ docId: string; version: number; action: string; from: number; to: number; original: string; text?: string; error?: string }>();
  const [custom, setCustom] = useState("");
  const [err, setErr] = useState<string>();
  const area = useRef<HTMLTextAreaElement>(null);
  const [busy, setBusy] = useState(false);
  const [unreconciled, setUnreconciled] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [notice, setNotice] = useState<string>();
  const mounted = useRef(false);
  const selection = useRef(0);
  const aiRequest = useRef(0);
  const editVersion = useRef(0);
  const current = useRef<{ doc?: Doc; draft: Draft; unreconciled?: boolean }>({ draft });
  const listRequest = useRef(0);
  const unreadableDrafts = useRef(new Set<string>());
  const dirty = doc ? unreconciled || draft.title !== doc.title || draft.body !== doc.body : false;
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; selection.current++; aiRequest.current++; }; }, []);
  const persist = useCallback((base: Doc, value: Draft) => {
    try {
      if (unreadableDrafts.current.has(base.id)) { volatileDrafts.set(base.id, { base, draft: value, unreconciled: current.current.unreconciled }); setNotice("Stored draft could not be read and has not been overwritten. Keep this editor open and copy your text before discarding the stored draft."); return; }
      // An in-flight save may commit a different version after navigation. Retain even
      // a return to the old base until that outcome is reconciled.
      if (!writes.has(base.id) && !current.current.unreconciled && base.title === value.title && base.body === value.body) sessionStorage.removeItem(draftKey(base.id));
      else sessionStorage.setItem(draftKey(base.id), JSON.stringify({ base, draft: value, unreconciled: current.current.unreconciled }));
      volatileDrafts.delete(base.id);
    } catch { volatileDrafts.set(base.id, { base, draft: value, unreconciled: current.current.unreconciled }); setNotice("Draft could not be stored on this device. Keep this editor open and copy your text before leaving."); }
  }, []);
  const edit = (value: Draft) => {
    const base = current.current.doc;
    current.current = { ...current.current, doc: base, draft: value }; editVersion.current++;
    setDraft(value); if (base) persist(base, value);
  };
  const dismissAi = () => { aiRequest.current++; setAi(undefined); };
  const list = useCallback(async () => {
    const request = ++listRequest.current;
    try { const r = await getJson<{ documents: DocMeta[] }>("/v1/documents"); if (mounted.current && request === listRequest.current) { setDocs(r.documents); setErr(undefined); } }
    catch (e) { if (mounted.current && request === listRequest.current) setErr((e as Error).message); }
  }, []);
  const install = useCallback((base: Doc, value: Draft, needsReconciliation = false) => {
    setUnreconciled(needsReconciliation);
    current.current = { doc: base, draft: value, unreconciled: needsReconciliation }; editVersion.current++;
    setDoc(base); setDraft(value); setBusy(false); setDeleting(false);
  }, []);
  const open = useCallback(async (id: string, discard = false) => {
    const request = ++selection.current;
    aiRequest.current++; setAi(undefined); setNotice(undefined);
    // Freeze the old editor until the requested document has loaded.
    current.current = { draft: { title: "", body: "" } }; setDoc(undefined);
    try {
      const d = checkedDoc(await getJson<Doc>(`/v1/documents/${encodeURIComponent(id)}`), id);
      if (!mounted.current || request !== selection.current) return;
      let saved: StoredDraft | undefined;
      try {
        if (discard) { sessionStorage.removeItem(draftKey(id)); unreadableDrafts.current.delete(id); volatileDrafts.delete(id); }
        const raw = sessionStorage.getItem(draftKey(id));
        if (raw) {
          saved = decodeDraft(raw, id);
        }
      } catch { unreadableDrafts.current.add(id); setNotice("Stored draft could not be read. It has not been removed. Copy any recoverable text before discarding it."); }
      const volatile = volatileDrafts.get(id);
      if (volatile) saved = volatile;
      if (saved) {
        // Keep the revision the draft was based on. Never rebase silently onto a newer server copy.
        install(saved.base, saved.draft, Boolean(saved.unreconciled) || saved.base.updated_at !== d.updated_at);
        setNotice(volatile ? "Draft restored from this session only. Device storage is unavailable; copy your text before closing the app." : saved.base.updated_at !== d.updated_at ? "Draft restored, but the server document changed. Copy your draft before discarding it to load the server version. Saving retains the original revision and may be rejected." : saved.unreconciled ? "Draft restored; the previous save outcome is unconfirmed. Copy your text before discarding and reloading to check." : "Unsaved draft restored.");
      } else install(d, { title: d.title, body: d.body });
    } catch (e) {
      if (!mounted.current || request !== selection.current) return;
      // A server outage or remote deletion must not hide the local recovery copy.
      let saved = volatileDrafts.get(id);
      if (!saved) {
        try { const raw = sessionStorage.getItem(draftKey(id)); if (raw) saved = decodeDraft(raw, id); }
        catch { unreadableDrafts.current.add(id); }
      }
      if (saved) {
        install(saved.base, saved.draft, true);
        setNotice(`Local draft recovered. Server document is unavailable (${(e as Error).message}). No document was recreated. Copy your text before discarding it.`);
      } else toast((e as Error).message, "error");
    }
  }, [toast, install]);
  const modelRequest = useRef(0);
  const refreshModels = useCallback(async () => {
    const request = ++modelRequest.current;
    try {
      const r = await loadModels();
      if (!mounted.current || request !== modelRequest.current) return;
      const m = r.models.filter((x) => !isEmbedding(x)); setModels(m);
      setModel((previous) => m.some(x => x.name === previous) ? previous : (m.find(x => !isCloud(x)) ?? m[0])?.name ?? "");
      setModelError(m.length ? undefined : "No editing models are available.");
    } catch (e) { if (mounted.current && request === modelRequest.current) setModelError(`Models could not be loaded: ${(e as Error).message}`); }
  }, []);
  useEffect(() => { void list(); void refreshModels(); return () => { modelRequest.current++; }; }, [list, refreshModels]);
  const requestedId = params.get("doc");
  useEffect(() => { if (requestedId) void open(requestedId); }, [requestedId, open]);
  const save = useCallback(async () => {
    const { doc: base, draft: submitted } = current.current;
    if (!base || writes.has(base.id) || (!current.current.unreconciled && base.title === submitted.title && base.body === submitted.body)) return;
    const request = selection.current;
    writes.add(base.id); setBusy(true);
    // Until a validated response arrives, the server may have committed this write.
    current.current = { ...current.current, unreconciled: true }; setUnreconciled(true);
    persist(base, submitted);
    try {
      const d = checkedDoc(await sendJson<Doc>("PUT", `/v1/documents/${encodeURIComponent(base.id)}`, { ...submitted, expected_updated_at: base.updated_at }), base.id);
      if (!mounted.current || request !== selection.current) return;
      const latest = current.current.draft;
      // Adopt server normalization only for fields unchanged since submission.
      const next = { title: latest.title === submitted.title ? d.title : latest.title, body: latest.body === submitted.body ? d.body : latest.body };
      install(d, next); setNotice(undefined);
      // The confirmed response has reconciled this mutation; normal clean-draft cleanup is safe.
      writes.delete(base.id); persist(d, next);
      toast(next.title === d.title && next.body === d.body ? "Saved" : "Saved submitted version; newer edits remain unsaved"); void list();
    } catch (e) {
      if (mounted.current && request === selection.current) {
        setNotice("Save outcome is unconfirmed. Your draft is retained; the server may have saved the submitted version. Copy your text before discarding and reloading to check.");
        toast((e as Error).message, "error");
      }
    }
    finally { writes.delete(base.id); if (mounted.current && request === selection.current) setBusy(false); }
  }, [toast, list, install, persist]);
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key === "s" && current.current.doc) { e.preventDefault(); void save(); } };
    addEventListener("keydown", k); return () => removeEventListener("keydown", k);
  }, [save]);
  const creating = useRef(false);
  const create = async () => {
    if (creating.current) return;
    creating.current = true;
    const request = ++selection.current; dismissAi();
    current.current = { draft: { title: "", body: "" } }; setDoc(undefined);
    try {
      const d = checkedDoc(await sendJson<Doc>("POST", "/v1/documents", { title: "Untitled", body: "# Untitled\n\n" }));
      if (!mounted.current) return;
      void list(); if (request === selection.current) { install(d, { title: d.title, body: d.body }); setNotice(undefined); }
    } catch (e) {
      if (mounted.current && request === selection.current) {
        setNotice("Creation outcome is unconfirmed. Check the refreshed document list before creating another document; the server may have created it.");
        toast((e as Error).message, "error"); void list();
      }
    }
    finally { creating.current = false; }
  };
  const remove = async () => {
    const base = current.current.doc;
    if (!base || writes.has(base.id) || !confirm(`Delete “${base.title}”?`)) return;
    const request = selection.current; writes.add(base.id); setBusy(true); setDeleting(true); dismissAi();
    current.current = { ...current.current, unreconciled: true }; setUnreconciled(true);
    persist(base, current.current.draft);
    try {
      await sendJson("DELETE", `/v1/documents/${encodeURIComponent(base.id)}`, { expected_updated_at: base.updated_at });
      if (!mounted.current || request !== selection.current) return;
      volatileDrafts.delete(base.id);
      try { sessionStorage.removeItem(draftKey(base.id)); } catch { /* Keep any residual recovery draft. */ }
      current.current = { draft: { title: "", body: "" } }; setDoc(undefined); setNotice(undefined); void list(); toast("Deleted");
    } catch (e) {
      if (mounted.current && request === selection.current) {
        setNotice("Deletion outcome is unconfirmed. A recovery copy is retained; the server may have deleted the document. Copy your text before discarding and reloading to check.");
        toast((e as Error).message, "error");
      }
    }
    finally { writes.delete(base.id); if (mounted.current && request === selection.current) setBusy(false); if (mounted.current && request === selection.current) setDeleting(false); }
  };
  const runAi = async (action: string, instruction?: string) => {
    const base = current.current;
    if (!base.doc || !model || deleting) return;
    const request = ++aiRequest.current;
    const el = area.current; const from = el && el.selectionEnd > el.selectionStart ? el.selectionStart : 0; const to = el && el.selectionEnd > el.selectionStart ? el.selectionEnd : base.draft.body.length;
    const original = base.draft.body.slice(from, to);
    const attempt = { docId: base.doc.id, version: editVersion.current, action, from, to, original };
    setAi(attempt);
    try { const r = await sendJson<{ text: string }>("POST", "/v1/documents/ai-edit", { action, instruction, text: original, model }); if (mounted.current && request === aiRequest.current) setAi({ ...attempt, text: r.text }); }
    catch (e) { if (mounted.current && request === aiRequest.current) setAi({ ...attempt, error: (e as Error).message }); }
  };
  const recovery = new Map<string, Doc>();
  try {
    for (let i = 0; i < sessionStorage.length; i++) {
      const key = sessionStorage.key(i);
      if (!key?.startsWith(draftPrefix)) continue;
      try { const saved = decodeDraft(sessionStorage.getItem(key)!, key.slice(draftPrefix.length)); recovery.set(saved.base.id, saved.base); } catch { /* Preserve malformed bytes for explicit recovery. */ }
    }
  } catch { /* Session-only fallback remains available below. */ }
  for (const saved of volatileDrafts.values()) recovery.set(saved.base.id, saved.base);
  const orphanDrafts = [...recovery.values()].filter(saved => !docs?.some(item => item.id === saved.id));
  const aiStale = Boolean(ai && (ai.docId !== doc?.id || ai.version !== editVersion.current));
  return (
    <div className="jg-u-page">
      <PageHead title="Documents" subtitle="Markdown documents with AI editing on your local models." actions={<><button type="button" className="jg-u-btn jg-u-btn--primary" onClick={() => void create()}>New document</button></>} />
      {dirty && <p className="jg-u-note">Unsaved drafts are kept in this browser tab only. Save to keep the document after closing the tab.</p>}
      {notice && <p className="jg-u-note" role="status">{notice}</p>}
      {err && <div role="alert"><p className="jg-u-error">{err}</p><button type="button" className="jg-u-btn" onClick={() => void list()}>Retry documents</button></div>}
      {modelError && <div role="alert"><p className="jg-u-error">{modelError}</p><button type="button" className="jg-u-btn" onClick={() => void refreshModels()}>Retry models</button></div>}
      <div className="jg-docs">
        <nav className="jg-u-card jg-docs__list" aria-label="Documents">
          {!docs ? err ? <Empty title="Documents unavailable" /> : <SkeletonRows /> : !docs.length ? <Empty title="No documents" /> : (
            <ul className="jg-u-list">{docs.map((d) => (
              <li key={d.id}><button type="button" className="jg-u-row" aria-current={d.id === doc?.id || undefined} onClick={() => void open(d.id)}>
                <span className="jg-u-row__text"><strong>{d.title}</strong><span>{new Date(d.updated_at * 1000).toLocaleString()} · {d.chars} chars</span></span>
              </button></li>))}</ul>)}
          {orphanDrafts.map(saved => <button key={saved.id} type="button" className="jg-u-btn" onClick={() => void open(saved.id)}>Recover draft: {saved.title}</button>)}
        </nav>
        {!doc ? <section className="jg-u-card"><Empty title="Open or create a document" action={<button type="button" className="jg-u-btn" onClick={() => void create()}>New document</button>} /></section> : (
          <section className="jg-u-card jg-docs__editor" aria-label="Editor">
            <div className="jg-ui-toolbar jg-spread">
              <input className="jg-docs__title" aria-label="Title" disabled={deleting} value={draft.title} maxLength={200} onChange={(e) => edit({ ...draft, title: e.target.value })} />
              <div className="jg-ui-toolbar">
                <Segmented label="Layout" value={mode} onChange={setMode} options={[{ value: "edit", label: "Edit" }, { value: "split", label: "Split" }, { value: "preview", label: "Preview" }]} />
                <button type="button" className="jg-u-btn jg-u-btn--primary" disabled={!dirty || busy} onClick={() => void save()}>{deleting ? "Deleting…" : busy ? "Saving…" : dirty ? "Save ⌘S" : "Saved"}</button>
                <button type="button" className="jg-u-btn jg-u-btn--danger" disabled={busy} onClick={() => void remove()}>Delete</button>
                <button type="button" className="jg-u-btn" disabled={busy} onClick={() => { if (confirm("Discard the local draft and load the server version? Copy any text you want to keep first.")) void open(doc.id, true); }}>Discard draft and reload</button>
              </div>
            </div>
            <div className="jg-ui-toolbar jg-docs__ai" aria-label="AI edit">
              <select className="jg-u-search" aria-label="AI model" value={model} onChange={(e) => setModel(e.target.value)} disabled={!models.length}>{models.map((m) => <option key={m.name} value={m.name}>{m.name}</option>)}</select>
              {ACTIONS.map(([id, text]) => <button key={id} type="button" className="jg-u-icon-btn" disabled={deleting || !model || Boolean(ai && !ai.text && !ai.error)} onClick={() => void runAi(id)}>{text}</button>)}
              <form className="jg-row" onSubmit={(e) => { e.preventDefault(); if (custom.trim()) void runAi("custom", custom); }}>
                <input className="jg-u-search jg-minw-select" placeholder="Custom instruction…" aria-label="Custom AI instruction" value={custom} onChange={(e) => setCustom(e.target.value)} />
              </form>
              <span className="jg-u-note">Applies to the selection, or the whole document.</span>
            </div>
            <div className="jg-docs__panes" data-mode={mode}>
              {mode !== "preview" && <textarea ref={area} aria-label="Markdown" disabled={deleting} value={draft.body} onChange={(e) => edit({ ...draft, body: e.target.value })} spellCheck />}
              {mode !== "edit" && <div className="jg-docs__preview"><Markdown text={draft.body} /></div>}
            </div>
          </section>)}
      </div>
      {ai && (
        <Sheet title={`AI: ${ai.action}`} onClose={dismissAi}>
          {!ai.text && !ai.error ? <SkeletonRows n={4} /> : ai.error ? <p className="jg-u-error" role="alert">{ai.error}</p> : <div className="jg-docs__preview jg-scroll-half"><Markdown text={ai.text!} /></div>}
          {aiStale && <p role="alert">Document changed. Discard this result and run the edit again.</p>}
          <div className="jg-ui-actions"><button type="button" className="jg-u-btn" onClick={dismissAi}>Discard</button>
            <button type="button" className="jg-u-btn jg-u-btn--primary" disabled={!ai.text || aiStale} onClick={() => { if (ai.docId !== current.current.doc?.id || ai.version !== editVersion.current || !ai.text) return; edit({ ...current.current.draft, body: current.current.draft.body.slice(0, ai.from) + ai.text + current.current.draft.body.slice(ai.to) }); dismissAi(); }}>Replace {ai.from === 0 && ai.to === draft.body.length ? "document" : "selection"}</button></div>
        </Sheet>)}
    </div>
  );
}
