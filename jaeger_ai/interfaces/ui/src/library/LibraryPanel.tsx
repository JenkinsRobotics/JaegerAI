import { useEffect, useRef, useState } from "react";
import type { LibraryControls, LibraryDocument } from "../api/source";
const draftKey = (id: string) => `jaeger.ui.library.draft.v1.${encodeURIComponent(id)}`;
const OP = "jaeger.ui.library.operation.v1";
const backupKeys = (id: string) => { try { return Object.keys(localStorage).filter(key => key.startsWith(draftKey(id) + '.backup.')); } catch { return []; } };
type Draft = Pick<LibraryDocument, "title" | "content" | "revision">;
type Intent = { operationId: string; action: "create" | "save" | "archive" | "restore" | "version"; documentId: string };
/** Native documents only; indexed corpus previews cannot gain edit/file access. */
export function LibraryPanel({ controls }: { controls: LibraryControls }) {
  const [catalog, setCatalog] = useState<Awaited<ReturnType<LibraryControls["list"]>>>(), [attempt, setAttempt] = useState(0);
  const [selected, setSelected] = useState<string>(), [document, setDocument] = useState<LibraryDocument>();
  const [draft, setDraft] = useState<Draft>({ title: "", content: "" });
  const [query, setQuery] = useState(""), [results, setResults] = useState<{ id: string; title: string; snippet: string }[]>();
  const [versions, setVersions] = useState<{ revision: number; title: string; created_at: number }[]>();
  const [pending, setPending] = useState<Intent>(), [busy, setBusy] = useState(false), locked = useRef(false);
  const volatile = useRef(false);
  const generation = useRef(0);
  const [error, setError] = useState<string>(), [notice, setNotice] = useState<string>();
  useEffect(() => {
    try { const raw = localStorage.getItem(OP); if (raw) { const value = JSON.parse(raw); if (!value.operationId || !value.action || !value.documentId) throw Error("Invalid operation record; preserved"); setPending(value); } }
    catch (e) { setError(`Library operation recovery unavailable: ${String(e)}`); locked.current = true; }
  }, []);
  useEffect(() => { let live = true; void controls.list().then(value => { if (live) setCatalog(value); }, e => { if (live) setError(String(e)); }); return () => { live = false; }; }, [controls, attempt]);
  const storeDraft = (id: string, value: Draft) => localStorage.setItem(draftKey(id), JSON.stringify(value));
  const storeNewDraft = (value: Draft) => {
    const prior = localStorage.getItem(draftKey("new"));
    if (prior) localStorage.setItem(draftKey("new") + '.backup.' + crypto.randomUUID(), prior);
    storeDraft("new", value);
  };
  const update = (value: Draft) => {
    if (!selected) return; setDraft(value);
    try { storeDraft(selected, value); volatile.current = false; setError(undefined); } catch (e) { volatile.current = true; setError(`Draft not saved: ${String(e)}. Keep this editor open.`); }
  };
  const open = async (id: string) => {
    if (busy) return;
    if (volatile.current) { setError("Current draft is not saved; keep this editor open and copy its text before navigating"); return; }
    const owner = ++generation.current;
    setError(undefined); setNotice(undefined); setSelected(id); setDocument(undefined); setVersions(undefined);
    try {
      const raw = localStorage.getItem(draftKey(id));
      const saved: Draft | undefined = raw ? JSON.parse(raw) : undefined;
      if (saved && (typeof saved.title !== "string" || typeof saved.content !== "string")) throw Error("Invalid draft record; original preserved");
      if (id === "new") { setDraft(saved ?? { title: "", content: "" }); return; }
      const current = await controls.read(id);
      if (owner !== generation.current) return;
      setDocument(current); setDraft(saved ?? current);
      if (saved && saved.revision !== current.revision) setError("Document changed elsewhere. Your draft is preserved; review the saved document before merging.");
    } catch (e) { if (owner === generation.current) setError(String((e as Error).message ?? e)); }
  };
  const finish = async (intent: Intent, receipt: Awaited<ReturnType<LibraryControls["mutate"]>>) => {
    if (receipt.operation_id !== intent.operationId) throw Error("Document operation identity mismatch");
    if (!receipt.ok) { localStorage.removeItem(OP); setPending(undefined); throw Error(receipt.error ?? "Document action rejected"); }
    if (!receipt.document?.id || typeof receipt.document.revision !== "number") throw Error("Document receipt has no verified identity/revision");
    const current = await controls.read(receipt.document.id);
    const raw = localStorage.getItem(draftKey(intent.documentId));
    const next = (intent.action === "archive" || intent.action === "restore") && raw ? { ...JSON.parse(raw), revision: current.revision } : current;
    storeDraft(current.id, next);
    if (intent.action === "create") localStorage.removeItem(draftKey("new"));
    localStorage.removeItem(OP); setPending(undefined);
    setSelected(current.id); setDocument(current); setDraft(next); setVersions(undefined); setAttempt(n => n + 1);
    setNotice(`Document action saved at revision ${receipt.document.revision}.${intent.action === "version" ? " Previous unsaved draft backup retained." : ""}`);
  };
  const mutate = async (action: Intent["action"], revision?: number) => {
    if (locked.current || pending || !selected) return;
    locked.current = true; setBusy(true); setError(undefined); setNotice(undefined);
    const intent: Intent = { operationId: crypto.randomUUID(), action, documentId: selected };
    let submitted = false;
    try {
      storeDraft(selected, draft);
      // Reserve backup capacity BEFORE changing the saved version. Ordinary saves already have
      // server version history and must not grow an unbounded duplicate browser backup store.
      if (action === "version") localStorage.setItem(draftKey(selected) + '.backup.' + intent.operationId, JSON.stringify(draft));
      localStorage.setItem(OP, JSON.stringify(intent)); setPending(intent);
      const body = { operation_id: intent.operationId, ...(action === "create" ? { title: draft.title, content: draft.content } : { expected_revision: draft.revision }), ...(action === "save" ? { title: draft.title, content: draft.content } : {}), ...(action === "version" ? { revision } : {}) };
      submitted = true;
      const receipt = await controls.mutate(action, selected, body); await finish(intent, receipt);
    } catch (e) { setError(`${String((e as Error).message ?? e)}${submitted ? ". Check saved document action; nothing is automatically replayed." : ". Nothing submitted; draft remains in this editor."}`); }
    finally { locked.current = false; setBusy(false); }
  };
  const reconcile = async () => {
    if (!pending || locked.current) return; locked.current = true; setBusy(true); setError(undefined);
    try { const row = await controls.operation(pending.operationId); if (!row.receipt) throw Error("Document action remains unknown; no replay"); await finish(pending, row.receipt as Awaited<ReturnType<LibraryControls["mutate"]>>); }
    catch (e) { setError(String((e as Error).message ?? e)); }
    finally { locked.current = false; setBusy(false); }
  };
  const ready = selected === "new" || Boolean(document);
  const editable = selected === "new" || document?.editable === true;
  return <section aria-label="Library">
    <p>Managed Jaeger documents are editable. Existing indexed collections stay read-only; no new folder access is granted here.</p>
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {pending && <p role="alert">Document action needs reconciliation. <button type="button" disabled={busy} onClick={() => void reconcile()}>Check saved document action</button></p>}
    <button type="button" disabled={busy || Boolean(pending)} onClick={() => void open("new")}>New document</button><button type="button" disabled={busy} onClick={() => setAttempt(n => n + 1)}>Refresh library</button>
    <form onSubmit={e => { e.preventDefault(); void controls.search(query).then(value => setResults(value.results), e => setError(String(e))); }}><label>Search indexed documents <input aria-label="Search library" value={query} onChange={e => setQuery(e.target.value)} /></label><button>Search library</button></form>
    {catalog?.collections.map(collection => <p key={collection.id}>{collection.label} · {collection.kind}</p>)}
    <ul>{catalog?.documents.map(doc => <li key={doc.id}><button type="button" disabled={busy} onClick={() => void open(doc.id)}>{doc.title}{doc.archived ? " (Archived)" : ""} · revision {doc.revision}</button></li>)}</ul>
    {results && <ul aria-label="Library search results">{results.map(result => <li key={result.id}><button type="button" disabled={busy} onClick={() => void open(result.id)}>{result.title}</button><p>{result.snippet}</p></li>)}</ul>}
    {selected && !ready && !error && <p role="status">Loading document…</p>}
    {ready && selected && <section aria-label="Document editor">
      <label>Title <input aria-label="Document title" value={draft.title} disabled={!editable || busy || Boolean(pending) || Boolean(document?.archived)} onChange={e => update({ ...draft, title: e.target.value })} /></label>
      <label>Content <textarea aria-label="Document content" rows={12} value={draft.content} readOnly={!editable || Boolean(document?.archived)} disabled={busy || Boolean(pending)} onChange={e => update({ ...draft, content: e.target.value })} style={{ width: "100%", boxSizing: "border-box" }} /></label>
      {editable && !document?.archived && <button type="button" disabled={busy || Boolean(pending) || !draft.title.trim()} onClick={() => void mutate(selected === "new" ? "create" : "save")}>Save document</button>}
      {document?.editable && <><button type="button" disabled={busy || Boolean(pending)} onClick={() => void mutate(document.archived ? "restore" : "archive")}>{document.archived ? "Restore document" : "Archive document"}</button><button type="button" disabled={busy} onClick={() => { const owner = generation.current; void controls.versions(document.id).then(value => { if (owner === generation.current) setVersions(value.versions); }, e => { if (owner === generation.current) setError(String(e)); }); }}>Version history</button></>}
      {document && <button type="button" disabled={busy} onClick={() => void open(selected)}>Refresh saved preview (keep draft)</button>}
      {document && <details><summary>Current saved document (your draft stays above)</summary><pre style={{ whiteSpace: "pre-wrap" }}>{document.content}</pre></details>}
      {editable && <button type="button" disabled={busy || Boolean(pending)} onClick={() => { try { storeNewDraft({ title: draft.title + " copy", content: draft.content }); void open("new"); } catch (e) { setError(String(e)); } }}>Copy draft into new document</button>}
      {versions?.map(version => <p key={version.revision}>Revision {version.revision} · {version.title} <button type="button" disabled={busy || Boolean(pending) || Boolean(document?.archived)} onClick={() => void mutate("version", version.revision)}>Restore as new revision</button></p>)}
      {backupKeys(selected).map(key => <button key={key} type="button" disabled={busy || Boolean(pending)} onClick={() => { try { const backup = JSON.parse(localStorage.getItem(key)!); storeNewDraft({ title: backup.title + " recovered", content: backup.content }); void open("new"); } catch (e) { setError(String(e)); } }}>Recover unsaved version draft as new document</button>)}
    </section>}
  </section>;
}
