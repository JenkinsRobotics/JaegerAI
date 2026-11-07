/** Read-only workspace and Git view bound to one Gateway session. */
import { useCallback, useEffect, useState } from "react";
import type { JaegerSource } from "../api/source";
import type { SessionRow } from "../api/types";
import { Empty, PageHead, SkeletonRows } from "./ui";
import { getJson } from "./webui";
import "./workspaceBrowser.css";
import { FolderOpen, FileText } from "../components/Icons";

type Entry = { name: string; path: string; type?: string; is_dir?: boolean; target_outside_workspace?: boolean };
const isDir = (entry: Entry) => entry.type === "dir" || entry.is_dir === true;
type GitFile = { path: string; status: string; staged: boolean; unstaged: boolean; untracked: boolean };
type GitStatus = { is_git: boolean; branch?: string; files?: GitFile[]; truncated?: boolean };
type Branches = { current: string; local: { name: string }[]; remote: { name: string }[] };
const query = (path: string, values: Record<string, string>) => `${path}?${new URLSearchParams(values)}`;
const errorText = (error: unknown) => String(error).includes("HTTP 404") ? "This session has no workspace to browse. Choose another session." : (error as Error).message;

export function WorkspaceBrowser({ source, params }: { source: JaegerSource; params: URLSearchParams }) {
  const requested = params.get("session") ?? "";
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [sessionId, setSessionId] = useState(requested);
  const [folder, setFolder] = useState(".");
  const [entries, setEntries] = useState<Entry[]>([]);
  const [selected, setSelected] = useState("");
  const [content, setContent] = useState("");
  const [fileError, setFileError] = useState("");
  const [status, setStatus] = useState<GitStatus>();
  const [branches, setBranches] = useState<Branches>();
  const [diff, setDiff] = useState("");
  const [diffPath, setDiffPath] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [revision, setRevision] = useState(0);

  useEffect(() => { let live = true; source.sessions().then(all => { const rows = all.filter(s => s.workspace); if (live) { setSessions(rows); setSessionId(id => id || rows[0]?.session_id || ""); } }, e => { if (live) setError((e as Error).message); }); return () => { live = false; }; }, [source]);
  useEffect(() => { setSessionId(requested); setFolder("."); setSelected(""); setDiffPath(""); }, [requested]);
  useEffect(() => {
    if (!sessionId) return;
    const controller = new AbortController();
    setLoading(true); setError(""); setStatus(undefined); setBranches(undefined); setEntries([]);
    Promise.all([
      getJson<{ entries: Entry[] }>(query("/api/list", { session_id: sessionId, path: folder }), controller.signal),
      getJson<{ git: GitStatus }>(query("/api/git/status", { session_id: sessionId }), controller.signal),
      getJson<{ branches: Branches }>(query("/api/git/branches", { session_id: sessionId }), controller.signal).catch(() => null),
    ]).then(([tree, git, branchData]) => { if (!controller.signal.aborted) { setEntries(tree.entries); setStatus(git.git); setBranches(branchData?.branches); } }, e => { if (!controller.signal.aborted) setError(errorText(e)); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [sessionId, folder, revision]);
  useEffect(() => {
    if (!sessionId || !selected) return;
    const controller = new AbortController(); setContent(""); setFileError("");
    getJson<{ content?: string }>(query("/api/file", { session_id: sessionId, path: selected }), controller.signal)
      .then(data => { if (!controller.signal.aborted) setContent(data.content ?? "Preview unavailable for this file."); }, e => { if (!controller.signal.aborted) setFileError(String(e).includes("HTTP 404") ? "This file can't be opened here." : (e as Error).message); });
    return () => controller.abort();
  }, [sessionId, selected, revision]);
  useEffect(() => {
    if (!sessionId || !diffPath) return;
    const controller = new AbortController(); setDiff("");
    const cut = diffPath.indexOf(":"); const kind = diffPath.slice(0, cut); const path = diffPath.slice(cut + 1);
    getJson<{ diff: { diff: string; binary?: boolean; too_large?: boolean } }>(query("/api/git/diff", { session_id: sessionId, kind, path }), controller.signal)
      .then(data => { if (!controller.signal.aborted) setDiff(data.diff.binary ? "Binary diff unavailable." : data.diff.diff || "No diff for this file."); }, e => { if (!controller.signal.aborted) setDiff(errorText(e)); });
    return () => controller.abort();
  }, [sessionId, diffPath, revision]);
  const chooseSession = useCallback((id: string) => { setSessionId(id); setFolder("."); setSelected(""); setDiffPath(""); }, []);
  const parent = folder === "." ? "." : folder.split("/").slice(0, -1).join("/") || ".";
  return <div className="jg-u-page jg-workspace-browser">
    <PageHead title="Workspace" subtitle="Browse session files and Git changes. Read only." actions={<button type="button" className="jg-u-btn" onClick={() => setRevision(v => v + 1)}>Refresh</button>} />
    <label className="jg-workspace-browser__session">Session <select aria-label="Workspace session" value={sessionId} onChange={e => chooseSession(e.target.value)}><option value="">Choose a session</option>{sessionId && !sessions.some(s => s.session_id === sessionId) && <option value={sessionId}>{sessionId}</option>}{sessions.map(s => <option key={s.session_id} value={s.session_id}>{s.title || s.session_id}</option>)}</select></label>
    {!sessionId && <Empty title="No session selected">{sessions.length ? "Choose a Gateway session to browse its workspace." : "No sessions have a workspace yet."}</Empty>}
    {error && <p role="alert" className="jg-u-error">{error}</p>}
    {loading && <SkeletonRows n={3} />}
    {sessionId && !error && !loading && <div className="jg-workspace-browser__grid" data-file-selected={!!selected}>
      <section className="jg-u-card" aria-label="File browser"><h3>Files</h3><p className="jg-workspace-browser__path">{folder}</p>{folder !== "." && <button type="button" onClick={() => setFolder(parent)}>.. Parent folder</button>}
        {entries.length === 0 && <p>This workspace folder is empty.</p>}
        <ul>{entries.map(entry => <li key={entry.path}><button type="button" disabled={entry.target_outside_workspace} onClick={() => isDir(entry) ? (setFolder(entry.path), setSelected("")) : setSelected(entry.path)}>{isDir(entry) ? <FolderOpen size={16} /> : <FileText size={16} />} {entry.name}</button></li>)}</ul>
      </section>
      <section className="jg-u-card" aria-label="File viewer"><h3>{selected || "File viewer"}</h3>{selected ? <>{fileError && <p role="alert">{fileError}</p>}{!fileError && <pre>{content || "Loading file…"}</pre>}<a href={query("/api/file/raw", { session_id: sessionId, path: selected, download: "1" })}>Download original</a></> : <p>Select a file to read it.</p>}</section>
      <section className="jg-u-card" aria-label="Git status"><h3>Git status</h3>{status?.is_git ? <><p>Branch: {status.branch}</p>{status.files?.length ? <ul>{status.files.map(file => <li key={file.path}><span>{file.status} {file.path}</span>{file.staged && <button type="button" onClick={() => setDiffPath(`staged:${file.path}`)}>Staged diff</button>}{(file.unstaged || file.untracked) && <button type="button" onClick={() => setDiffPath(`unstaged:${file.path}`)}>Diff</button>}</li>)}</ul> : <p>No changes.</p>}{status.truncated && <p>Showing a limited set of changes.</p>}</> : <p>This workspace is not a Git repository.</p>}</section>
      <section className="jg-u-card" aria-label="Branches and diff"><h3>Branches</h3>{branches ? <><p>Current: {branches.current}</p><ul>{branches.local?.map(b => <li key={b.name}>{b.name}</li>)}</ul></> : <p>No branch list available.</p>}{diffPath && <><h3>Diff: {diffPath.slice(diffPath.indexOf(":") + 1)}</h3><pre>{diff || "Loading diff…"}</pre></>}</section>
    </div>}
  </div>;
}
