import {CompanionMode} from "./CompanionMode";
import {JaegerAvatar} from "../avatar/JaegerAvatar";
import {STATUS_TEXT,type ClipState} from "../avatar/avatar";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent } from "react";
import type { JaegerSource } from "../api/source";
import type { Agent, SessionRow } from "../api/types";
import { ChatPane } from "../chat/ChatPane";
import { isSessionMissingError } from "../chat/host";
import { WebHost } from "../chat/webHost";
import { contractHome, httpGetJson } from "../chat/homeSession";
import { ApprovalTray } from "../unified/ApprovalTray";
import { ToastProvider } from "../unified/ui";
import "../unified/unified.css";
import "../unified/design.css";
import { applyAppearance, storedAppearance, type Appearance } from "../settings/SettingsDialog";
import { TaskArtifacts } from "../library/TaskArtifacts";
import { WorkspaceBrowser } from "../unified/WorkspaceBrowser";
import { Plus, MessageSquare, FolderOpen, FileText, CheckCircle, X, Settings, PanelLeft, Bot, Workflow, Search, Image, Compass, Cpu, MoreHorizontal, Pencil, Pin, Share, Copy, Clock, ChevronLeft, ChevronRight, Trash2 } from "../components/Icons";
import "./stableDemo.css";
import { SettingsWorkspace } from "./SettingsWorkspace";
import { navigate, pathOf, useRoute, SUBTABS, type PageId } from "../shell/router";
import { AppWindow } from "../windows/AppWindow";
import { clampWidth, SIDEBAR } from "../shell/sidebarSizing";

export const DEMO_SESSION_KEY = "jaeger.stable-demo.session.v1";
const PINNED_SESSION_KEY = "jaeger.stable-demo.pinned-sessions.v1";
const SIDEBAR_WIDTH_KEY = "jaeger.stable-demo.sidebar-width.v1";
const COMPACT_SHELL_QUERY = "(max-width: 820px), (max-height: 520px) and (max-width: 1000px)";
function storedSession() { try { return localStorage.getItem(DEMO_SESSION_KEY) || ""; } catch { return ""; } }
function storedPins() { try { return new Set<string>(JSON.parse(localStorage.getItem(PINNED_SESSION_KEY) || "[]")); } catch { return new Set<string>(); } }
function storedSidebarWidth() { try { return clampWidth(Number(localStorage.getItem(SIDEBAR_WIDTH_KEY) || SIDEBAR.defaultWidth)); } catch { return SIDEBAR.defaultWidth; } }
function projectLabel(workspace: string) { return workspace.split(/[\\/]/).filter(Boolean).pop() || workspace; }
function sessionActivity(row: SessionRow) { return row.last_activity_at ?? row.updated_at ?? row.created_at ?? 0; }
function SummaryGlyph() { return <svg aria-hidden="true" width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><circle cx="6" cy="7" r="2"/><path d="M11 7h8"/><circle cx="6" cy="17" r="2"/><path d="M11 17h8"/></svg>; }
function TabsGlyph({ count }: { count: number }) { return <span className="jg-stable-demo__tabs-glyph" aria-hidden="true"><span>{count}</span></span>; }
type HeaderPopup = "menu" | "summary" | "tabs" | null;
type MenuPage = "main" | "copy" | "open";
function ConversationRow({ row, active, pinned, selecting, selected, onOpen, onSelect, onPin, onDelete }: { row: SessionRow; active: boolean; pinned: boolean; selecting: boolean; selected: boolean; onOpen(): void; onSelect(): void; onPin(): void; onDelete(): void }) {
  const title = row.title || "Untitled conversation";
  const generic = !row.title || ["Jaeger stable chat", "New conversation"].includes(row.title);
  return <div className="jg-stable-demo__session-row" data-selected={selected || undefined}>
    {selecting && <label className="jg-stable-demo__session-check"><input type="checkbox" aria-label={`Select ${title}`} checked={selected} onChange={onSelect} /></label>}
    <button className="jg-stable-demo__session-title" type="button" title={title} aria-current={active ? "true" : undefined} onClick={onOpen}>{title}{generic && <small className="jg-stable-demo__session-id">{row.session_id.slice(-8)}</small>}</button>
    {!selecting && <span className="jg-stable-demo__session-actions">
      <button type="button" aria-label={`${pinned ? "Unpin" : "Pin"} ${title}`} title={pinned ? "Unpin" : "Pin"} onClick={onPin}><Pin size={14} /></button>
      <button type="button" aria-label={`Delete ${title}`} title="Delete permanently" onClick={onDelete}><Trash2 size={14} /></button>
    </span>}
  </div>;
}
/** Recovery surface: existing chat renderer and Gateway-owned task runner, no parallel backend. */
export function StableDemo({ source }: { source: JaegerSource }) {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const closeSettings = useCallback(() => setSettingsOpen(false), []);
  const [sidebarOpen, setSidebarOpen] = useState(() => typeof matchMedia === "function" ? !matchMedia(COMPACT_SHELL_QUERY).matches : true);
  const [sidebarWidth, setSidebarWidth] = useState(storedSidebarWidth);
  const shellRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const viewport = window.visualViewport;
    const shell = shellRef.current;
    if (!viewport || !shell) return;
    // iOS leaves the layout viewport tall when the keyboard opens. Size the
    // shell to the visible viewport so the composer stays above the keyboard.
    const update = () => {
      if (viewport.scale !== 1) {
        shell.style.removeProperty("--jg-viewport-height");
        shell.style.removeProperty("--jg-viewport-top");
        delete shell.dataset.keyboard;
        return;
      }
      shell.style.setProperty("--jg-viewport-height", `${viewport.height}px`);
      shell.style.setProperty("--jg-viewport-top", `${viewport.offsetTop}px`);
      shell.dataset.keyboard = String(window.innerHeight - viewport.height > 120);
    };
    update();
    viewport.addEventListener("resize", update);
    viewport.addEventListener("scroll", update);
    return () => {
      viewport.removeEventListener("resize", update);
      viewport.removeEventListener("scroll", update);
    };
  }, []);
  const [headerPopup, setHeaderPopup] = useState<HeaderPopup>(null);
  const [menuPage, setMenuPage] = useState<MenuPage>("main");
  const [renameOpen, setRenameOpen] = useState(false);
  const [renameDraft, setRenameDraft] = useState("");
  const [pinnedSessions, setPinnedSessions] = useState(storedPins);
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedSessions, setSelectedSessions] = useState<Set<string>>(() => new Set());
  const [deleteConfirm, setDeleteConfirm] = useState<string[] | null>(null);
  const [deleting, setDeleting] = useState(false);
  const toolsRef = useRef<HTMLDivElement>(null);
  const [appearance, setAppearance] = useState(storedAppearance);
  const route = useRoute();
  const [inspector, setInspector] = useState<"outputs" | "files" | null>(null);
  const [recent, setRecent] = useState<SessionRow[]>([]);
  const [historyError, setHistoryError] = useState("");
  const [historyReady, setHistoryReady] = useState(false);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [session, setSession] = useState(storedSession);
  const [ready, setReady] = useState(false);
  const [avatarState, setAvatarState] = useState<ClipState>("idle");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const unavailableSessions = useRef(new Set<string>());
  const recoverMissingSession = useCallback((missingSession: string) => {
    unavailableSessions.current.add(missingSession);
    setRecent(rows => rows.filter(row => row.session_id !== missingSession));
    setError(""); setReady(true); setHeaderPopup(null);
    setSession(current => current === missingSession ? "" : current);
    try { if (localStorage.getItem(DEMO_SESSION_KEY) === missingSession) localStorage.removeItem(DEMO_SESSION_KEY); } catch { /* the in-memory recovery still works */ }
  }, []);
  useEffect(() => {
    if (!sidebarOpen) return;
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSidebarOpen(false);
    };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [sidebarOpen]);
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
    }).catch((e: unknown) => {
      if (!live) return;
      if (session && isSessionMissingError(e)) recoverMissingSession(session);
      else { setError(String((e as Error).message)); setReady(false); }
    });
    return () => { live = false; };
  }, [source, session, recoverMissingSession]);
  useEffect(() => {
    if (!headerPopup) return;
    const close = (event: MouseEvent) => { if (headerPopup !== "summary" && !toolsRef.current?.contains(event.target as Node)) setHeaderPopup(null); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") setHeaderPopup(null); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", escape); };
  }, [headerPopup]);
  useEffect(() => {
    if (typeof matchMedia !== "function") return;
    const compact = matchMedia(COMPACT_SHELL_QUERY);
    const adapt = (event: MediaQueryListEvent) => { if (event.matches) setSidebarOpen(false); };
    compact.addEventListener("change", adapt);
    return () => compact.removeEventListener("change", adapt);
  }, []);
  useEffect(() => {
    let live = true;
    source.sessions({ agent_id: "native:jaeger" }).then(rows => {
      if (!live) return;
      const available = rows.filter(row => !row.archived && !unavailableSessions.current.has(row.session_id)).sort((a, b) => sessionActivity(b) - sessionActivity(a));
      setRecent(available);
      setHistoryReady(true);
      setHistoryError("");
      // A new browser has no device-local selection yet. A returning phone can also retain
      // the id of a conversation deleted on another device. In either case, open Jaeger's
      // most recently active durable conversation instead of stranding the device on 404.
      const selectedStillExists = Boolean(session && available.some(row => row.session_id === session));
      if (source.kind === "live" && !selectedStillExists && available[0]) {
        setSession(available[0].session_id);
        try { localStorage.setItem(DEMO_SESSION_KEY, available[0].session_id); } catch { /* still usable for this visit */ }
      }
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
  const togglePinnedSession = (id: string) => {
    if (!id) return;
    setPinnedSessions(previous => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id); else next.add(id);
      try { localStorage.setItem(PINNED_SESSION_KEY, JSON.stringify([...next])); } catch { /* preference remains in memory */ }
      return next;
    });
  };
  const togglePinned = () => togglePinnedSession(session);
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
  const toggleSelected = (id: string) => setSelectedSessions(previous => {
    const next = new Set(previous);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const leaveSelectionMode = () => { setSelectionMode(false); setSelectedSessions(new Set()); };
  const deleteSessions = async () => {
    if (!deleteConfirm?.length || deleting) return;
    if (!source.deleteSession) { setHistoryError("This Gateway does not support permanent session deletion."); setDeleteConfirm(null); return; }
    setDeleting(true); setHistoryError("");
    const results = await Promise.allSettled(deleteConfirm.map(id => source.deleteSession!(id)));
    const deleted = deleteConfirm.filter((_, index) => results[index].status === "fulfilled" && (results[index] as PromiseFulfilledResult<{deleted:boolean}>).value.deleted);
    const failed = deleteConfirm.length - deleted.length;
    if (deleted.length) {
      const removed = new Set(deleted);
      setRecent(rows => rows.filter(row => !removed.has(row.session_id)));
      setPinnedSessions(previous => {
        const next = new Set([...previous].filter(id => !removed.has(id)));
        try { localStorage.setItem(PINNED_SESSION_KEY, JSON.stringify([...next])); } catch { /* preference remains in memory */ }
        return next;
      });
      setSelectedSessions(previous => new Set([...previous].filter(id => !removed.has(id))));
      if (removed.has(session)) {
        setSession(""); setReady(true); setHeaderPopup(null);
        try { localStorage.removeItem(DEMO_SESSION_KEY); } catch { /* session simply remains unpersisted */ }
        navigate("/");
      }
    }
    if (failed) setHistoryError(`${failed} conversation${failed === 1 ? "" : "s"} could not be deleted. The others were removed.`);
    setDeleting(false); setDeleteConfirm(null);
    if (!failed) leaveSelectionMode();
  };
  const persistSidebarWidth = (width: number) => { try { localStorage.setItem(SIDEBAR_WIDTH_KEY, String(width)); } catch { /* width remains in memory */ } };
  const beginSidebarResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    const left = shellRef.current?.getBoundingClientRect().left ?? 0;
    const move = (next: PointerEvent) => setSidebarWidth(clampWidth(next.clientX - left));
    const finish = (next: PointerEvent) => {
      const width = clampWidth(next.clientX - left);
      setSidebarWidth(width); persistSidebarWidth(width);
      document.removeEventListener("pointermove", move); document.removeEventListener("pointerup", finish);
    };
    document.addEventListener("pointermove", move); document.addEventListener("pointerup", finish, { once: true });
  };
  const resizeSidebarWithKeyboard = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const width = event.key === "Home" ? SIDEBAR.minWidth : event.key === "End" ? SIDEBAR.maxWidth : event.key === "ArrowLeft" ? clampWidth(sidebarWidth - SIDEBAR.keyStep) : event.key === "ArrowRight" ? clampWidth(sidebarWidth + SIDEBAR.keyStep) : null;
    if (width === null) return;
    event.preventDefault(); setSidebarWidth(width); persistSidebarWidth(width);
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
  const pinnedRows = recent.filter(row => pinnedSessions.has(row.session_id));
  const unpinnedRows = recent.filter(row => !pinnedSessions.has(row.session_id));
  const projectGroups = [...unpinnedRows.reduce((groups, row) => {
    if (!row.workspace) return groups;
    const rows = groups.get(row.workspace) ?? [];
    rows.push(row); groups.set(row.workspace, rows);
    return groups;
  }, new Map<string, SessionRow[]>())];
  const recentRows = unpinnedRows.filter(row => !row.workspace);
  const workspacePage = route.page !== "chat" && route.page !== "settings";
  const routeTitle: Record<PageId, string> = { library: "Library", automations: "Automations", feed: "Feed", home: "Chat", chat: "Chat", agents: "Agents", work: "Work", research: "Research", studio: "Imagine", models: "Models", machine: "Machine", settings: "Settings" };
  const activeSection = route.page === "work" && route.sub === "tasks" ? "tasks" : route.page === "models" ? "studio" : route.page === "home" ? "chat" : route.page;
  const openTabCount = (session ? 1 : 0) + (inspector ? 1 : 0);
  return <ToastProvider><div hidden={settingsOpen}><div ref={shellRef} className="jg-stable-demo" data-stable-demo="1" data-inspector={!!inspector || headerPopup === "summary"} data-summary={headerPopup === "summary"} data-sidebar={sidebarOpen} style={{ "--jg-stable-sidebar-width": `${sidebarWidth}px` } as CSSProperties}>
    <aside id="jaeger-navigation" hidden={!sidebarOpen} className="jg-stable-demo__sidebar" aria-label="Jaeger navigation">
      <div className="jg-stable-demo__rail">
        <button type="button" aria-label="Close sidebar" title="Close sidebar" aria-controls="jaeger-navigation" onClick={() => setSidebarOpen(false)}><PanelLeft size={20} /></button>
        <nav aria-label="Jaeger navigation">
          {([
            ["chat", "Chat", MessageSquare], ["studio", "Imagine", Image],
            ["library", "Library", FolderOpen], ["automations", "Automations", Clock],
            ["feed", "Feed", Compass], ["agents", "Agents", Bot],
          ] as const).map(([id, title, Icon]) => <button key={id} type="button" title={title} aria-label={title} aria-current={route.page === id ? "page" : undefined} onClick={() => navigate(pathOf(id))}><Icon size={20} /><span>{title}</span></button>)}
          <details className="jg-stable-demo__more"><summary aria-label="More tools" title="More tools"><MoreHorizontal size={20} /></summary>
            {([["work", "Work", Workflow], ["research", "Research", Search], ["machine", "Machine", Cpu]] as const).map(([id,title,Icon]) => <button key={id} type="button" title={title} aria-label={title} onClick={() => navigate(pathOf(id))}><Icon size={20}/><span>{title}</span></button>)}
          <button type="button" aria-label="Tasks" aria-current={activeSection === "tasks" ? "page" : undefined} onClick={() => navigate(pathOf("work", "tasks"))}><CheckCircle size={20} /><span>Tasks</span></button>
          </details>
        </nav>
        <button className="jg-stable-demo__rail-settings" type="button" aria-label="Settings" title="Settings" onClick={() => setSettingsOpen(true)}><Settings size={20} /><span>Settings</span></button>
      </div>
      <section className="jg-stable-demo__context" aria-label={`${routeTitle[route.page]} sidebar`}>
        <div className="jg-stable-demo__brand"><CompanionMode team={route.page === "agents"} onChange={team => navigate(pathOf(team ? "agents" : "chat"))} />{activeSection === "chat" && <button type="button" className="jg-stable-demo__manage" aria-pressed={selectionMode} onClick={() => selectionMode ? leaveSelectionMode() : setSelectionMode(true)}>{selectionMode ? "Done" : "Manage"}</button>}</div>
        {activeSection === "chat" && <>
          <button className="jg-stable-demo__new" type="button" disabled={!ready || busy} onClick={() => void start()}><Plus size={18} />{busy ? "Opening…" : "New conversation"}</button>
          {selectionMode && <div className="jg-stable-demo__selection-tools">
            <button type="button" onClick={() => setSelectedSessions(selectedSessions.size === recent.length ? new Set() : new Set(recent.map(row => row.session_id)))}>{selectedSessions.size === recent.length && recent.length ? "Clear all" : "Select all"}</button>
            <span>{selectedSessions.size} selected</span>
            <button className="jg-stable-demo__danger" type="button" disabled={!selectedSessions.size} onClick={() => setDeleteConfirm([...selectedSessions])}>Delete selected</button>
            <button className="jg-stable-demo__danger" type="button" disabled={!recent.length} onClick={() => setDeleteConfirm(recent.map(row => row.session_id))}>Delete all</button>
          </div>}
          <div className="jg-stable-demo__recents">
            {historyError && <p role="alert">{historyError}</p>}
            <section className="jg-stable-demo__session-section"><h2>Pinned</h2>
              {!pinnedRows.length && <p>Pin conversations you want to keep close.</p>}
              {pinnedRows.map(row => <ConversationRow key={row.session_id} row={row} active={session === row.session_id} pinned selecting={selectionMode} selected={selectedSessions.has(row.session_id)} onOpen={() => selectSession(row.session_id)} onSelect={() => toggleSelected(row.session_id)} onPin={() => togglePinnedSession(row.session_id)} onDelete={() => setDeleteConfirm([row.session_id])} />)}
            </section>
            <section className="jg-stable-demo__session-section"><h2>Projects</h2>
              {!projectGroups.length && <p>Conversations with a workspace appear here.</p>}
              {projectGroups.map(([workspace, rows]) => <div className="jg-stable-demo__project" key={workspace}><h3 title={workspace}><FolderOpen size={15} />{projectLabel(workspace)}</h3>{rows.map(row => <ConversationRow key={row.session_id} row={row} active={session === row.session_id} pinned={false} selecting={selectionMode} selected={selectedSessions.has(row.session_id)} onOpen={() => selectSession(row.session_id)} onSelect={() => toggleSelected(row.session_id)} onPin={() => togglePinnedSession(row.session_id)} onDelete={() => setDeleteConfirm([row.session_id])} />)}</div>)}
            </section>
            <section className="jg-stable-demo__session-section"><h2>Recents</h2>
              {!recentRows.length && !historyError && <p>{recent.length ? "All conversations are pinned or in projects." : "Your conversations will appear here."}</p>}
              {recentRows.map(row => <ConversationRow key={row.session_id} row={row} active={session === row.session_id} pinned={false} selecting={selectionMode} selected={selectedSessions.has(row.session_id)} onOpen={() => selectSession(row.session_id)} onSelect={() => toggleSelected(row.session_id)} onPin={() => togglePinnedSession(row.session_id)} onDelete={() => setDeleteConfirm([row.session_id])} />)}
            </section>
          </div>
        </>}
        {activeSection === "agents" && <div className="jg-stable-demo__context-list"><h2>Agent team</h2>{agents.map(row => <button key={row.id} type="button" onClick={() => navigate(pathOf("agents"))}><Bot size={17} />{row.display_name || row.name || row.id}</button>)}</div>}
        {(route.page === "work" || route.page === "research") && <div className="jg-stable-demo__context-list"><h2>{route.page === "work" ? "Your work" : "Explore"}</h2>{SUBTABS[route.page]?.map(tab => <button type="button" key={tab.id} aria-current={route.sub === tab.id ? "page" : undefined} onClick={() => navigate(pathOf(route.page,tab.id))}>{tab.title}</button>)}</div>}
        {activeSection === "studio" && <div className="jg-stable-demo__context-list"><h2>Create with Jaeger</h2>{[["create","Generate images"],["library","Saved images"],["board","Idea board"]].map(([section,title]) => <button type="button" key={section} aria-current={(route.params.get("section") || "create") === section ? "page" : undefined} onClick={() => navigate(`/studio?section=${section}`)}>{title}</button>)}</div>}
        {activeSection === "library" && <div className="jg-stable-demo__context-list"><h2>Your library</h2>{[["media","Media"],["documents","Documents"],["outputs","Task outputs"]].map(([section,title]) => <button type="button" key={section} aria-current={(route.params.get("section") || "media") === section ? "page" : undefined} onClick={() => navigate(`/library?section=${section}`)}>{title}</button>)}</div>}
        {activeSection === "automations" && <div className="jg-stable-demo__context-list"><h2>Routines</h2><button type="button" aria-current="page" onClick={() => navigate("/automations")}>Schedules and run history</button><p>Manage schedules, pause a routine, or review its latest runs.</p></div>}
        {activeSection === "feed" && <div className="jg-stable-demo__context-list"><h2>From Jaeger</h2><button type="button" aria-current="page" onClick={() => navigate("/feed")}>Agent updates</button><p>Recent activity and updates from your agent.</p></div>}
        {activeSection === "machine" && <div className="jg-stable-demo__context-list"><h2>System</h2><button type="button" aria-current="page" onClick={() => navigate(pathOf("machine"))}><Cpu size={17} />Machine</button></div>}
        <div className="jg-stable-demo__context-footer">
          <label className="jg-stable-demo__appearance">Appearance<select aria-label="Appearance" value={appearance} onChange={e => { const mode = e.target.value as Appearance; setAppearance(mode); applyAppearance(mode); }}><option value="system">System</option><option value="dark">Dark</option><option value="light">Light</option></select></label>
          <div className="jg-stable-demo__connection" role="status"><span className="jg-stable-demo__dot" data-ready={ready && !error} />{error ? "Connection error" : ready ? source.kind === "mock" ? "Design preview · sample data" : "Gateway connected" : "Connecting…"}</div>
        </div>
      </section>
      <div className="jg-stable-demo__resize" role="separator" aria-label="Resize navigation" aria-orientation="vertical" aria-valuemin={SIDEBAR.minWidth} aria-valuemax={SIDEBAR.maxWidth} aria-valuenow={sidebarWidth} tabIndex={0} onPointerDown={beginSidebarResize} onKeyDown={resizeSidebarWithKeyboard} />
    </aside>
    {sidebarOpen && <button className="jg-stable-demo__backdrop" aria-label="Dismiss navigation" onClick={() => setSidebarOpen(false)} />}
    <main className="jg-stable-demo__main">
      <header className="jg-stable-demo__header" aria-label="Conversation toolbar">
        <div className="jg-stable-demo__header-start">
          <button className="jg-stable-demo__top-button" type="button" aria-label="Toggle navigation" title="Toggle navigation" aria-expanded={sidebarOpen} aria-controls="jaeger-navigation" onClick={() => setSidebarOpen(value => !value)}><PanelLeft size={18} /></button>
          <button className="jg-stable-demo__top-button" type="button" aria-label="New conversation" title="New conversation" disabled={!ready || busy} onClick={() => void start()}><Pencil size={18} /></button>
        </div>
        <div className="jg-stable-demo__profile" title={workspacePage ? routeTitle[route.page] : currentTitle}>
          <span className="jg-stable-demo__profile-avatar"><JaegerAvatar portraitOverride={agent?.avatar_url} state={!ready || error ? "connecting" : avatarState} /></span>
          <span className="jg-stable-demo__profile-copy"><strong>Jaeger<span className="jg-clip-status" role="status">{(ready && !error && avatarState === "idle" ? "Idle" : STATUS_TEXT[!ready || error ? "connecting" : avatarState])}</span></strong><small>{workspacePage ? routeTitle[route.page] : currentTitle}</small></span>
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
          {headerPopup === "tabs" && <div className="jg-stable-demo__popover jg-stable-demo__popover--tabs" role="menu" aria-label="Open tabs menu"><h2>Working and shared tabs</h2>
            {session && <button role="menuitem" type="button" onClick={() => { navigate("/"); setHeaderPopup(null); }}><span className="jg-stable-demo__tab-mark">J</span>{currentTitle}</button>}
            {inspector === "outputs" && <button role="menuitem" type="button" onClick={() => setHeaderPopup(null)}><FileText size={18} />Outputs and artifacts</button>}
            {inspector === "files" && <button role="menuitem" type="button" onClick={() => setHeaderPopup(null)}><FolderOpen size={18} />Files and changes</button>}
            {!openTabCount && <p>No tabs are currently shared with Jaeger.</p>}
          </div>}
        </div>
      </header>
      {error && <p className="jg-stable-demo__connection-alert" role="alert"><span>{error}</span><button type="button" onClick={() => location.reload()}>Reconnect</button></p>}
      <section className="jg-stable-demo__body" hidden={workspacePage} aria-label="Chat">
        {session && ready ? <ChatPane onAvatarState={setAvatarState} host={host} sessionId={session} agents={agent ? [agent] : agents} onSessionMissing={recoverMissingSession} /> : !ready || !historyReady || historyError || session ?
          <div className="jg-stable-demo__empty" role="status"><h1>{error || historyError ? "Waiting to reconnect" : "Restoring your conversation"}</h1><p>{error || historyError ? "Jaeger is temporarily unavailable. Your saved conversation will return when the connection is restored." : "Loading your saved conversation from Jaeger."}</p></div> :
          <div className="jg-stable-demo__empty"><span className="jg-stable-demo__eyebrow">YOUR AI COMPANION</span><h1>What would you like to work on?</h1><p>Talk with Jaeger, follow a task, or explore your files.<br />Your conversation stays here when you return.</p>
          <button type="button" disabled={!ready || busy} onClick={() => void start()}><Plus size={18} />{busy ? "Opening…" : "Start conversation"}</button></div>}
      </section>
      <section className="jg-stable-demo__body jg-stable-demo__body--workspace" hidden={!workspacePage} aria-label={routeTitle[route.page]}>
        {workspacePage && <AppWindow source={source} embedded />}
      </section>
    </main>

          {headerPopup === "summary" && <div className="jg-stable-demo__popover jg-stable-demo__popover--summary jg-stable-demo__summary-dock" role="dialog" aria-label="Pinned workspace summary">
            <header className="jg-stable-demo__summary-heading"><strong>Conversation details</strong><button type="button" aria-label="Close summary" onClick={() => setHeaderPopup(null)}><X size={18} /></button></header><section><header><h2>Environment</h2><button type="button" aria-label="Open files and changes" onClick={() => { setInspector("files"); setHeaderPopup(null); }}><Plus size={19} /></button></header>
              <button type="button" onClick={() => { setInspector("files"); setHeaderPopup(null); }}><FileText size={18} /><span>Changes</span></button>
              <div><Cpu size={18} /><span>Connected Gateway</span></div>
              <div><FolderOpen size={18} /><span>{currentRow?.workspace ? currentRow.workspace.split("/").pop() : "No workspace attached"}</span></div>
            </section>
            <section><h2>Connection and activity</h2><div><span className="jg-stable-demo__status-dot" data-ready={ready && !error} /><span>{error ? "Connection error" : ready ? "Gateway connected (transport)" : "Connecting to Gateway"}</span></div><div><Bot size={18} /><span>{(agent?.display_name || agent?.name || "Jaeger") + " · " + (ready && !error && avatarState === "idle" ? "Idle" : STATUS_TEXT[!ready || error ? "connecting" : avatarState])}</span></div></section>
            <section><header><h2>Conversation outputs</h2><button type="button" aria-label="Open outputs" onClick={() => { setInspector("outputs"); setHeaderPopup(null); }}><Plus size={19} /></button></header><button type="button" onClick={() => { setInspector("outputs"); setHeaderPopup(null); }}><FileText size={18} /><span>Outputs and artifacts</span></button><button type="button" onClick={() => { setInspector("files"); setHeaderPopup(null); }}><FolderOpen size={18} /><span>Files and changes</span></button>{session && source.taskArtifacts && <TaskArtifacts controls={source.taskArtifacts} sessionId={session} />}</section>
          </div>}

    {inspector && headerPopup !== "summary" && <aside id="jaeger-work-panel" className="jg-stable-demo__inspector" aria-label="Work panel">
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
    {deleteConfirm && <div className="jg-stable-demo__dialog-backdrop" onMouseDown={event => { if (event.target === event.currentTarget && !deleting) setDeleteConfirm(null); }}>
      <div className="jg-stable-demo__delete-dialog" role="alertdialog" aria-modal="true" aria-labelledby="delete-conversations-title" aria-describedby="delete-conversations-description">
        <span className="jg-stable-demo__delete-icon"><Trash2 size={21} /></span>
        <h2 id="delete-conversations-title">Delete {deleteConfirm.length === 1 ? "this conversation" : `${deleteConfirm.length} conversations`}?</h2>
        <p id="delete-conversations-description">Messages, approvals, queued work, and saved turn data for {deleteConfirm.length === 1 ? "this conversation" : "these conversations"} will be permanently removed from the Gateway. This cannot be undone.</p>
        <div><button type="button" disabled={deleting} onClick={() => setDeleteConfirm(null)}>Cancel</button><button className="jg-stable-demo__delete-confirm" type="button" disabled={deleting} onClick={() => void deleteSessions()}>{deleting ? "Deleting…" : "Delete permanently"}</button></div>
      </div>
    </div>}
  </div></div>{settingsOpen && <SettingsWorkspace onClose={closeSettings} />}</ToastProvider>;
}
