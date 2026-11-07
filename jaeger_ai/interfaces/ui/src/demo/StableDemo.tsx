import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { JaegerSource } from "../api/source";
import type { Agent, SessionRow } from "../api/types";
import { ChatPane } from "../chat/ChatPane";
import { WebHost } from "../chat/webHost";
import { contractHome, httpGetJson } from "../chat/homeSession";
import { ApprovalTray } from "../unified/ApprovalTray";
import { ToastProvider } from "../unified/ui";
import "../unified/unified.css";
import "../unified/design.css";
import { applyAppearance, storedAppearance, type Appearance } from "../settings/SettingsDialog";
import { TaskArtifacts } from "../library/TaskArtifacts";
import { WorkspaceBrowser } from "../unified/WorkspaceBrowser";
import { AgentFace } from "../unified/AgentFace";
import { RobotIcon } from "../agents/RobotIcon";
import { Plus, MessageSquare, FolderOpen, FileText, CheckCircle, X, Settings, PanelLeft, Bot, Workflow, Search, Code, Cpu, MoreHorizontal, Pencil, Pin, Share, Copy, Clock, ChevronLeft, ChevronRight } from "../components/Icons";
import "./stableDemo.css";
import { SettingsWorkspace } from "./SettingsWorkspace";
import { navigate, pathOf, useRoute, type PageId } from "../shell/router";
import { AppWindow } from "../windows/AppWindow";

export const DEMO_SESSION_KEY = "jaeger.stable-demo.session.v1";
const PINNED_SESSION_KEY = "jaeger.stable-demo.pinned-sessions.v1";
function storedSession() { try { return localStorage.getItem(DEMO_SESSION_KEY) || ""; } catch { return ""; } }
function storedPins() { try { return new Set<string>(JSON.parse(localStorage.getItem(PINNED_SESSION_KEY) || "[]")); } catch { return new Set<string>(); } }
function SummaryGlyph() { return <svg aria-hidden="true" width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><circle cx="6" cy="7" r="2"/><path d="M11 7h8"/><circle cx="6" cy="17" r="2"/><path d="M11 17h8"/></svg>; }
function TabsGlyph({ count }: { count: number }) { return <span className="jg-stable-demo__tabs-glyph" aria-hidden="true"><span>{count}</span></span>; }
type HeaderPopup = "menu" | "summary" | "tabs" | null;
type MenuPage = "main" | "copy" | "open";
/** Recovery surface: existing chat renderer and Gateway-owned task runner, no parallel backend. */
export function StableDemo({ source }: { source: JaegerSource }) {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const closeSettings = useCallback(() => setSettingsOpen(false), []);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [headerPopup, setHeaderPopup] = useState<HeaderPopup>(null);
  const [menuPage, setMenuPage] = useState<MenuPage>("main");
  const [renameOpen, setRenameOpen] = useState(false);
  const [renameDraft, setRenameDraft] = useState("");
  const [pinnedSessions, setPinnedSessions] = useState(storedPins);
  const toolsRef = useRef<HTMLDivElement>(null);
  const [appearance, setAppearance] = useState(storedAppearance);
  const route = useRoute();
  const [inspector, setInspector] = useState<"outputs" | "files" | null>(null);
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
    h.openDetails = () => navigate(pathOf("agents"));
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
    if (!headerPopup) return;
    const close = (event: MouseEvent) => { if (!toolsRef.current?.contains(event.target as Node)) setHeaderPopup(null); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") setHeaderPopup(null); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", escape); };
  }, [headerPopup]);
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
    navigate("/");
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
  const currentRow = recent.find(row => row.session_id === session);
  const currentTitle = currentRow?.title || "Chat with Jaeger";
  const togglePopup = (popup: Exclude<HeaderPopup, null>) => {
    setHeaderPopup(value => value === popup ? null : popup);
    setMenuPage("main"); setRenameOpen(false);
  };
  const togglePinned = () => {
    if (!session) return;
    setPinnedSessions(previous => {
      const next = new Set(previous);
      if (next.has(session)) next.delete(session); else next.add(session);
      try { localStorage.setItem(PINNED_SESSION_KEY, JSON.stringify([...next])); } catch { /* preference remains in memory */ }
      return next;
    });
  };
  const renameSession = async () => {
    const title = renameDraft.trim();
    if (!session || !title) return;
    try { await source.updateSession(session, { title }); setRecent(rows => rows.map(row => row.session_id === session ? { ...row, title } : row)); setRenameOpen(false); }
    catch (e) { setHistoryError(String((e as Error).message)); }
  };
  const archiveSession = async () => {
    if (!session) return;
    try {
      await source.updateSession(session, { archived: true });
      setRecent(rows => rows.filter(row => row.session_id !== session));
      setSession(""); setHeaderPopup(null);
      try { localStorage.removeItem(DEMO_SESSION_KEY); } catch { /* session simply remains unpersisted */ }
      navigate("/");
    } catch (e) { setHistoryError(String((e as Error).message)); }
  };
  const copyText = async (text: string) => {
    try { await navigator.clipboard.writeText(text); setHeaderPopup(null); }
    catch { setHistoryError("Clipboard access was unavailable."); }
  };
  const shareConversation = async () => {
    try {
      if (navigator.share) await navigator.share({ title: currentTitle, url: location.href });
      else await navigator.clipboard.writeText(location.href);
      setHeaderPopup(null);
    } catch (e) { if ((e as DOMException).name !== "AbortError") setHistoryError("This conversation could not be shared."); }
  };
  const agent = agents.find(a => a.id === "native:jaeger");
  const workspacePage = route.page !== "chat" && route.page !== "settings";
  const routeTitle: Record<PageId, string> = { home: "Chat", chat: "Chat", agents: "Agents", work: "Work", research: "Research", studio: "Studio", models: "Models", machine: "Machine", settings: "Settings" };
  const openTabCount = (session ? 1 : 0) + (inspector ? 1 : 0);
  return <ToastProvider><div hidden={settingsOpen}><div className="jg-stable-demo" data-stable-demo="1" data-inspector={!!inspector} data-sidebar={sidebarOpen}>
    <aside id="jaeger-navigation" hidden={!sidebarOpen} className="jg-stable-demo__sidebar" aria-label="Jaeger navigation">
      <div className="jg-stable-demo__brand"><span className="jg-stable-demo__mark">J</span><strong>Jaeger</strong></div>
      <button className="jg-stable-demo__new" type="button" disabled={!ready || busy} onClick={() => void start()}><Plus size={18} />{busy ? "Opening…" : "New conversation"}</button>
      <nav aria-label="Jaeger navigation">
        <button type="button" aria-current={route.page === "chat" ? "page" : undefined} onClick={() => navigate("/")}><MessageSquare size={18} />Chat</button>
        <button type="button" aria-current={route.page === "agents" ? "page" : undefined} onClick={() => navigate(pathOf("agents"))}><Bot size={18} />Agents</button>
        <button type="button" aria-current={route.page === "work" && route.sub !== "tasks" ? "page" : undefined} onClick={() => navigate(pathOf("work"))}><Workflow size={18} />Work</button>
        <button type="button" aria-current={route.page === "work" && route.sub === "tasks" ? "page" : undefined} onClick={() => navigate(pathOf("work", "tasks"))}><CheckCircle size={18} />Tasks</button>
        <button type="button" aria-current={route.page === "research" ? "page" : undefined} onClick={() => navigate(pathOf("research"))}><Search size={18} />Research</button>
        <button type="button" aria-current={route.page === "studio" ? "page" : undefined} onClick={() => navigate(pathOf("studio"))}><Code size={18} />Studio</button>
        <button type="button" aria-current={route.page === "machine" ? "page" : undefined} onClick={() => navigate(pathOf("machine"))}><Cpu size={18} />Machine</button>
      </nav>
      <div className="jg-stable-demo__recents"><h2>Recents</h2>
        {historyError && <p role="alert">{historyError}</p>}
        {!recent.length && !historyError && <p>Your conversations will appear here.</p>}
        {recent.map(row => <button type="button" key={row.session_id} title={row.title || "Untitled conversation"} aria-current={session === row.session_id ? "true" : undefined} onClick={() => selectSession(row.session_id)}>{row.title || "Untitled conversation"}</button>)}
      </div>
      <button type="button" onClick={() => setSettingsOpen(true)}><Settings size={18} />Settings</button>
      <label className="jg-stable-demo__appearance"><Settings size={16} />Appearance<select aria-label="Appearance" value={appearance} onChange={e => { const mode = e.target.value as Appearance; setAppearance(mode); applyAppearance(mode); }}><option value="system">System</option><option value="dark">Dark</option><option value="light">Light</option></select></label>
      <div className="jg-stable-demo__connection" role="status"><span className="jg-stable-demo__dot" data-ready={ready && !error} />{error ? "Connection error" : ready ? source.kind === "mock" ? "Design preview · sample data" : "Live Gateway" : "Connecting…"}</div>
    </aside>
    <main className="jg-stable-demo__main">
      <header className="jg-stable-demo__header">
        <div className="jg-stable-demo__header-start">
          <button className="jg-stable-demo__top-button" type="button" aria-label="Toggle navigation" title="Toggle navigation" aria-expanded={sidebarOpen} aria-controls="jaeger-navigation" onClick={() => setSidebarOpen(value => !value)}><PanelLeft size={18} /></button>
          <button className="jg-stable-demo__top-button" type="button" aria-label="New conversation" title="New conversation" disabled={!ready || busy} onClick={() => void start()}><Plus size={18} /></button>
        </div>
        <div className="jg-stable-demo__profile">
          <span className="jg-stable-demo__profile-avatar">{agent ? <AgentFace agent={agent} size={44} /> : <RobotIcon id="native:jaeger" name="Jaeger" size={44} />}</span>
          <span className="jg-stable-demo__profile-copy"><strong>Jaeger</strong><small>{workspacePage ? routeTitle[route.page] : currentTitle}</small></span>
        </div>
        <div className="jg-stable-demo__tools" ref={toolsRef}><ApprovalTray source={source} onOpenChat={() => navigate("/")} />
          <button className="jg-stable-demo__top-button" type="button" aria-label="Conversation actions" data-tooltip="Conversation actions" aria-expanded={headerPopup === "menu"} onClick={() => togglePopup("menu")}><MoreHorizontal size={19} /></button>
          <button className="jg-stable-demo__top-button" type="button" aria-label="Toggle pinned summary" data-tooltip="Toggle pinned summary" aria-expanded={headerPopup === "summary"} onClick={() => togglePopup("summary")}><SummaryGlyph /></button>
          <button className="jg-stable-demo__top-button" type="button" aria-label="Open tabs" data-tooltip="Tabs Jaeger is using or you shared" aria-expanded={headerPopup === "tabs"} onClick={() => togglePopup("tabs")}><TabsGlyph count={openTabCount} /></button>
          {headerPopup === "menu" && <div className="jg-stable-demo__popover jg-stable-demo__popover--menu" role="menu" aria-label="Conversation actions menu">
            {menuPage !== "main" && <button className="jg-stable-demo__popover-back" type="button" onClick={() => setMenuPage("main")}><ChevronLeft size={16} />{menuPage === "copy" ? "Copy" : "Open in"}</button>}
            {menuPage === "main" && <>
              {renameOpen ? <form className="jg-stable-demo__rename" onSubmit={e => { e.preventDefault(); void renameSession(); }}><label htmlFor="jaeger-rename">Conversation name</label><input id="jaeger-rename" autoFocus value={renameDraft} onChange={e => setRenameDraft(e.target.value)} /><div><button type="button" onClick={() => setRenameOpen(false)}>Cancel</button><button type="submit" disabled={!renameDraft.trim()}>Save</button></div></form> : <button role="menuitem" type="button" disabled={!session} onClick={() => { setRenameDraft(currentTitle); setRenameOpen(true); }}><Pencil size={17} />Rename</button>}
              <button role="menuitem" type="button" disabled={!session} onClick={togglePinned}><Pin size={17} />{pinnedSessions.has(session) ? "Unpin" : "Pin"}</button>
              <button role="menuitem" type="button" disabled={!session} onClick={() => void archiveSession()}><FolderOpen size={17} />Archive</button>
              <div className="jg-stable-demo__menu-separator" />
              <button role="menuitem" type="button" onClick={() => void shareConversation()}><Share size={17} />Share</button>
              <button role="menuitem" type="button" onClick={() => setMenuPage("copy")}><Copy size={17} />Copy<ChevronRight className="jg-stable-demo__menu-chevron" size={16} /></button>
              <div className="jg-stable-demo__menu-separator" />
              <button role="menuitem" type="button" disabled={!ready || busy} onClick={() => { setHeaderPopup(null); void start(); }}><MessageSquare size={17} />New side chat</button>
              <button role="menuitem" type="button" disabled data-tooltip="Conversation forking needs Gateway support"><Workflow size={17} />Fork<span className="jg-stable-demo__soon">Gateway support needed</span></button>
              <button role="menuitem" type="button" disabled><Clock size={17} />Add scheduled task…</button>
              <div className="jg-stable-demo__menu-separator" />
              <button role="menuitem" type="button" onClick={() => setMenuPage("open")}><ChevronRight size={17} />Open in<ChevronRight className="jg-stable-demo__menu-chevron" size={16} /></button>
              <button role="menuitem" type="button" onClick={() => window.open(location.href, "_blank", "noopener,noreferrer")}><PanelLeft size={17} />Open in new window</button>
            </>}
            {menuPage === "copy" && <><button role="menuitem" type="button" onClick={() => void copyText(location.href)}><Copy size={17} />Conversation link</button><button role="menuitem" type="button" disabled={!session} onClick={() => void copyText(session)}><Copy size={17} />Conversation ID</button></>}
            {menuPage === "open" && <><button role="menuitem" type="button" onClick={() => { navigate("/"); setHeaderPopup(null); }}><MessageSquare size={17} />Chat</button><button role="menuitem" type="button" onClick={() => { navigate(pathOf("work", "tasks")); setHeaderPopup(null); }}><CheckCircle size={17} />Tasks</button><button role="menuitem" type="button" onClick={() => { navigate(pathOf("agents")); setHeaderPopup(null); }}><Bot size={17} />Agents</button><button role="menuitem" type="button" onClick={() => { setSettingsOpen(true); setHeaderPopup(null); }}><Settings size={17} />Settings</button></>}
          </div>}
          {headerPopup === "summary" && <div className="jg-stable-demo__popover jg-stable-demo__popover--summary" role="dialog" aria-label="Pinned workspace summary">
            <section><header><h2>Environment</h2><button type="button" aria-label="Open files and changes" onClick={() => { setInspector("files"); setHeaderPopup(null); }}><Plus size={19} /></button></header>
              <button type="button" onClick={() => { setInspector("files"); setHeaderPopup(null); }}><FileText size={18} /><span>Changes</span></button>
              <div><Cpu size={18} /><span>Local Gateway</span></div>
              <div><FolderOpen size={18} /><span>{currentRow?.workspace ? currentRow.workspace.split("/").pop() : "Conversation workspace"}</span></div>
            </section>
            <section><h2>Background processes</h2><div><span className="jg-stable-demo__status-dot" data-ready={ready && !error} /><span>{ready ? "Gateway connected" : "Connecting to Gateway"}</span></div><div><Bot size={18} /><span>{agent?.display_name || agent?.name || "Jaeger agent"}</span></div></section>
            <section><header><h2>Sources</h2><button type="button" aria-label="Open outputs" onClick={() => { setInspector("outputs"); setHeaderPopup(null); }}><Plus size={19} /></button></header><button type="button" onClick={() => { setInspector("outputs"); setHeaderPopup(null); }}><FileText size={18} /><span>Outputs and artifacts</span></button><button type="button" onClick={() => { setInspector("files"); setHeaderPopup(null); }}><FolderOpen size={18} /><span>Files and changes</span></button></section>
          </div>}
          {headerPopup === "tabs" && <div className="jg-stable-demo__popover jg-stable-demo__popover--tabs" role="menu" aria-label="Open tabs menu"><h2>Working and shared tabs</h2>
            {session && <button role="menuitem" type="button" onClick={() => { navigate("/"); setHeaderPopup(null); }}><span className="jg-stable-demo__tab-mark">J</span>{currentTitle}</button>}
            {inspector === "outputs" && <button role="menuitem" type="button" onClick={() => setHeaderPopup(null)}><FileText size={18} />Outputs and artifacts</button>}
            {inspector === "files" && <button role="menuitem" type="button" onClick={() => setHeaderPopup(null)}><FolderOpen size={18} />Files and changes</button>}
            {!openTabCount && <p>No tabs are currently shared with Jaeger.</p>}
          </div>}
        </div>
      </header>
      {error && <p role="alert">{error} <button onClick={() => location.reload()}>Reconnect</button></p>}
      <section className="jg-stable-demo__body" hidden={workspacePage} aria-label="Chat">
        {session && ready ? <ChatPane host={host} sessionId={session} agents={agent ? [agent] : agents} /> :
          <div className="jg-stable-demo__empty"><span className="jg-stable-demo__eyebrow">YOUR AI COMPANION</span><h1>What would you like to work on?</h1><p>Talk with Jaeger, follow a task, or explore your files.<br />Your conversation stays here when you return.</p>
          <button type="button" disabled={!ready || busy} onClick={() => void start()}><Plus size={18} />{busy ? "Opening…" : "Start conversation"}</button></div>}
      </section>
      <section className="jg-stable-demo__body jg-stable-demo__body--workspace" hidden={!workspacePage} aria-label={routeTitle[route.page]}>
        {workspacePage && <AppWindow source={source} embedded />}
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
  </div></div>{settingsOpen && <SettingsWorkspace onClose={closeSettings} />}</ToastProvider>;
}
