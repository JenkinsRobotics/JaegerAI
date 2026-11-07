import { useEffect, useMemo, useState } from "react";
import type { JaegerSource } from "../api/source";
import type { Agent, SessionRow } from "../api/types";
import { ChatPane } from "../chat/ChatPane";
import { WebHost } from "../chat/webHost";
import { contractHome, httpGetJson } from "../chat/homeSession";
import { TasksWorkspace } from "../unified/TasksWorkspace";
import { ApprovalTray } from "../unified/ApprovalTray";
import { ToastProvider } from "../unified/ui";
import "../unified/unified.css";
import "../unified/design.css";
import { applyAppearance, storedAppearance, type Appearance } from "../settings/SettingsDialog";
import { TaskArtifacts } from "../library/TaskArtifacts";
import { WorkspaceBrowser } from "../unified/WorkspaceBrowser";
import { AgentFace } from "../unified/AgentFace";
import { RobotIcon } from "../agents/RobotIcon";
import { Plus, MessageSquare, FolderOpen, FileText, CheckCircle, X, Settings, PanelLeft, PanelRight } from "../components/Icons";
import "./stableDemo.css";

export const DEMO_SESSION_KEY = "jaeger.stable-demo.session.v1";
function storedSession() { try { return localStorage.getItem(DEMO_SESSION_KEY) || ""; } catch { return ""; } }
/** Recovery surface: existing chat renderer and Gateway-owned task runner, no parallel backend. */
export function StableDemo({ source }: { source: JaegerSource }) {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [appearance, setAppearance] = useState(storedAppearance);
  const [page, setPage] = useState<"chat" | "tasks">("chat");
  const [inspector, setInspector] = useState<"outputs" | "files" | null>(() => window.innerWidth > 1100 ? "outputs" : null);
  const [recent, setRecent] = useState<SessionRow[]>([]);
  const [historyError, setHistoryError] = useState("");
  const [agents, setAgents] = useState<Agent[]>([]);
  const [session, setSession] = useState(storedSession);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const host = useMemo(() => {
    const h = new WebHost(source);
    h.home = contractHome(httpGetJson(), { agentName: id => id === "native:jaeger" ? "Jaeger" : id, onCursor: (sid, cursor) => h.noteCursor(sid, cursor) }, source.stream.bind(source));
    return h;
  }, [source]);
  useEffect(() => {
    let live = true;
    Promise.all([source.agents(), session ? source.session(session) : Promise.resolve(null)]).then(([rows]) => {
      if (live) { setAgents(rows); setReady(true); setError(""); }
    }).catch((e: unknown) => { if (live) { setError(String((e as Error).message)); setReady(false); } });
    return () => { live = false; };
  }, [source, session]);
  useEffect(() => {
    let live = true;
    source.sessions({ agent_id: "native:jaeger" }).then(rows => {
      if (live) { setRecent(rows.filter(row => !row.archived)); setHistoryError(""); }
    }, e => { if (live) setHistoryError(String((e as Error).message)); });
    return () => { live = false; };
  }, [source, session]);
  const workspaceParams = useMemo(() => new URLSearchParams({ session }), [session]);
  const selectSession = (id: string) => {
    if (id !== session) { setReady(false); setSession(id); }
    setPage("chat");
    try { localStorage.setItem(DEMO_SESSION_KEY, id); } catch { setHistoryError("This browser could not remember the selected conversation."); }
  };
  const start = async () => {
    if (busy) return;
    setBusy(true); setError("");
    try {
      // Independent lead conversation: never reuse or replay the stuck Builder request.
      const row = await source.createSession({ agent_id: "native:jaeger", title: "Jaeger stable chat" });
      selectSession(row.session_id);
    } catch (e) { setError(String((e as Error).message)); }
    finally { setBusy(false); }
  };
  const agent = agents.find(a => a.id === "native:jaeger");
  return <ToastProvider><div className="jg-stable-demo" data-stable-demo="1" data-inspector={!!inspector} data-sidebar={sidebarOpen}>
    <aside id="jaeger-navigation" hidden={!sidebarOpen} className="jg-stable-demo__sidebar" aria-label="Jaeger navigation">
      <div className="jg-stable-demo__brand"><span className="jg-stable-demo__mark">J</span><strong>Jaeger</strong></div>
      <button className="jg-stable-demo__new" type="button" disabled={!ready || busy} onClick={() => void start()}><Plus size={18} />{busy ? "Opening…" : "New conversation"}</button>
      <nav aria-label="Demo navigation">
        <button type="button" aria-current={page === "chat" ? "page" : undefined} onClick={() => setPage("chat")}><MessageSquare size={18} />Chat</button>
        <button type="button" aria-current={page === "tasks" ? "page" : undefined} onClick={() => setPage("tasks")}><CheckCircle size={18} />Tasks</button>
      </nav>
      <a className="jg-stable-demo__workspace-link" href="/?full=1"><FolderOpen size={18} />Full workspace (preview)</a>
      <div className="jg-stable-demo__recents"><h2>Recents</h2>
        {historyError && <p role="alert">{historyError}</p>}
        {!recent.length && !historyError && <p>Your conversations will appear here.</p>}
        {recent.map(row => <button type="button" key={row.session_id} title={row.title || "Untitled conversation"} aria-current={session === row.session_id ? "true" : undefined} onClick={() => selectSession(row.session_id)}>{row.title || "Untitled conversation"}</button>)}
      </div>
      <label className="jg-stable-demo__appearance"><Settings size={16} />Appearance<select aria-label="Appearance" value={appearance} onChange={e => { const mode = e.target.value as Appearance; setAppearance(mode); applyAppearance(mode); }}><option value="system">System</option><option value="dark">Dark</option><option value="light">Light</option></select></label>
      <div className="jg-stable-demo__connection" role="status"><span className="jg-stable-demo__dot" data-ready={ready && !error} />{error ? "Connection error" : ready ? source.kind === "mock" ? "Design preview · sample data" : "Live Gateway" : "Connecting…"}</div>
    </aside>
    <main className="jg-stable-demo__main">
      <header className="jg-stable-demo__header">
        <button type="button" aria-label="Toggle navigation" title="Toggle navigation" aria-expanded={sidebarOpen} aria-controls="jaeger-navigation" onClick={() => setSidebarOpen(value => !value)}><PanelLeft size={18} /></button>
        <strong>{page === "tasks" ? "Tasks" : recent.find(row => row.session_id === session)?.title || "Chat with Jaeger"}</strong>
        <div className="jg-stable-demo__tools"><ApprovalTray source={source} onOpenChat={() => setPage("chat")} />
          <button type="button" aria-expanded={!!inspector} aria-controls="jaeger-work-panel" onClick={() => setInspector(inspector ? null : "outputs")}><PanelRight size={17} /><span>Work panel</span></button>
        </div>
      </header>
      {page === "chat" && <div className="jg-stable-demo__identity">{agent ? <AgentFace agent={agent} size={48} /> : <RobotIcon id="native:jaeger" name="Jaeger" size={48} />}<div><strong>Jaeger</strong><span>Your AI companion</span></div></div>}
      {error && <p role="alert">{error} <button onClick={() => location.reload()}>Reconnect</button></p>}
      <section className="jg-stable-demo__body" hidden={page !== "chat"} aria-label="Chat">
        {session && ready ? <ChatPane host={host} sessionId={session} agents={agent ? [agent] : agents} /> :
          <div className="jg-stable-demo__empty"><span className="jg-stable-demo__eyebrow">YOUR AI COMPANION</span><h1>What would you like to work on?</h1><p>Talk with Jaeger, follow a task, or explore your files.<br />Your conversation stays here when you return.</p>
          <button type="button" disabled={!ready || busy} onClick={() => void start()}><Plus size={18} />{busy ? "Opening…" : "Start conversation"}</button></div>}
      </section>
      <section className="jg-stable-demo__body" hidden={page !== "tasks"} aria-label="Tasks">
        {page === "tasks" && <TasksWorkspace source={source} agents={agents} params={new URLSearchParams()} onNavigate={(to) => { location.href = `${to}${to.includes("?") ? "&" : "?"}full=1`; }} />}
      </section>
      <footer className="jg-stable-demo__footer">Saved by Gateway · Automatic recovery after worker interruption is not verified.</footer>
    </main>
    {inspector && <aside id="jaeger-work-panel" className="jg-stable-demo__inspector" aria-label="Work panel">
      <header><strong>Work panel</strong><button type="button" aria-label="Close work panel" onClick={() => setInspector(null)}><X size={18} /></button></header>
      <div className="jg-stable-demo__tabs" role="group" aria-label="Work panel view">
        <button type="button" aria-pressed={inspector === "outputs"} onClick={() => setInspector("outputs")}><FileText size={16} />Outputs</button>
        <button type="button" aria-pressed={inspector === "files"} onClick={() => setInspector("files")}><FolderOpen size={16} />Files & changes</button>
      </div>
      <div className="jg-stable-demo__inspector-content">
        {inspector === "outputs" ? source.taskArtifacts ? <TaskArtifacts controls={source.taskArtifacts} sessionId={session || undefined} /> : <p>Artifact previews are unavailable on this Gateway.</p> : session ? <WorkspaceBrowser key={session} source={source} params={workspaceParams} /> : <div className="jg-stable-demo__panel-empty"><FolderOpen size={28} /><h2>Your working files</h2><p>Start a conversation to browse its workspace and Git changes.</p></div>}
      </div>
      <p className="jg-stable-demo__panel-note">Use Refresh to check for new outputs or file changes.</p>
    </aside>}
  </div></ToastProvider>;
}
