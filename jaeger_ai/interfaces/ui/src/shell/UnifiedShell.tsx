/**
 * UnifiedShell — ONE adaptive shell for JaegerAI (Revision 2 / Phase 3).
 *
 * Replaces the nested StableDemo -> AppWindow -> App composition with:
 *   - ONE shared Gateway data store (useGatewayStore)
 *   - ONE ToastProvider and ONE command palette (JumpTo)
 *   - FIVE canonical destinations: Chat, Agents & Characters, Work, Library, Settings
 *   - First-class live AvatarPanel wired directly into active Chat (rendered only when toggled on & visible)
 *   - Standalone SettingsView (never mounts legacy App.tsx)
 *   - Adaptive Desktop rail + iPhone/iPad bottom bar with iOS visualViewport keyboard handling
 */
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { chatTitle, groupChatsByDate, visibleChats } from "../agents/chats";
import { visible } from "../agents/agentsLogic";
import { JumpTo, type JumpAction } from "../agents/JumpTo";
import { useAgentsStore } from "../agents/agentsStore";
import type { JaegerSource } from "../api/source";
import type { SessionRow } from "../api/types";
import type { ClipState } from "../avatar/avatar";
import { AvatarPanel } from "../avatar/AvatarPanel";
import { JaegerAvatar } from "../avatar/JaegerAvatar";
import { JaegerMark } from "../brand/JaegerMark";
import { ChatPane } from "../chat/ChatPane";
import { conversationPath, validConversationId } from "../chat/conversationLocation";
import { contractHome, httpGetJson } from "../chat/homeSession";
import { WebHost } from "../chat/webHost";
import {
  Bot,
  FolderOpen,
  MessageSquare,
  PanelLeft,
  PanelRight,
  Pencil,
  Plus,
  Search,
  Settings,
  Workflow,
} from "../components/Icons";
import { ConversationWorkPanel, type WorkView } from "../demo/ConversationWorkPanel";
import { DEMO_SESSION_KEY } from "../demo/StableDemo";
import { isBackgroundSession, sessionActivity, useGatewayStore } from "../sdk/gatewayStore";
import { parseSettingsRest, type Tab as SettingsTab } from "../settings/SettingsDialog";
import { SettingsView } from "../settings/SettingsView";
import { ApprovalTray } from "../unified/ApprovalTray";
import { SkeletonRows, ToastProvider } from "../unified/ui";
import { sendJson } from "../unified/webui";
import { useSizeClass } from "./breakpoints";
import {
  canonicalDestinationOf,
  navigate,
  useRoute,
  type CanonicalDestination,
} from "./router";
import "../unified/unified.css";
import "../unified/design.css";
import "./unifiedShell.css";

const AgentsRoster = lazy(() => import("../unified/AgentsRoster").then((m) => ({ default: m.AgentsRoster })));
const AgentsActivityPage = lazy(() => import("../orchestration/AgentsActivityPage").then((m) => ({ default: m.AgentsActivityPage })));
const CharactersPage = lazy(() => import("../unified/CharactersPage").then((m) => ({ default: m.CharactersPage })));
const KnowledgePage = lazy(() => import("../unified/KnowledgePage").then((m) => ({ default: m.KnowledgePage })));
const PixelOffice = lazy(() => import("../team/office/PixelOffice").then((m) => ({ default: m.PixelOffice })));
const TasksWorkspace = lazy(() => import("../unified/TasksWorkspace").then((m) => ({ default: m.TasksWorkspace })));
const TasksPage = lazy(() => import("../windows/TasksPage").then((m) => ({ default: m.TasksPage })));
const AutomationsPanel = lazy(() => import("../automations/AutomationsPanel").then((m) => ({ default: m.AutomationsPanel })));
const CalendarPage = lazy(() => import("../unified/CalendarPage").then((m) => ({ default: m.CalendarPage })));
const ProcessView = lazy(() => import("../process/ProcessView").then((m) => ({ default: m.ProcessView })));
const YouTubePage = lazy(() => import("../research/YouTubePage").then((m) => ({ default: m.YouTubePage })));
const StudioPage = lazy(() => import("../unified/StudioPage").then((m) => ({ default: m.StudioPage })));
const CompanionPage = lazy(() => import("../unified/CompanionPage").then((m) => ({ default: m.CompanionPage })));
const DocumentsPage = lazy(() => import("../unified/DocumentsPage").then((m) => ({ default: m.DocumentsPage })));
const ResearchPage = lazy(() => import("../unified/ResearchPage").then((m) => ({ default: m.ResearchPage })));
const WorkspaceBrowser = lazy(() => import("../unified/WorkspaceBrowser").then((m) => ({ default: m.WorkspaceBrowser })));

const JAEGER_HOME_ID = "agent-native:jaeger";
const JAEGER_HOME_AGENT = "native:jaeger";
const AVATAR_DOCK_KEY = "jaeger.unified.avatar-dock.v1";
const COMPACT_QUERY = "(max-width: 820px)";

const PageFallback = () => <div className="jg-u-page"><SkeletonRows n={5} /></div>;

function storedSession(): string {
  try { return localStorage.getItem(DEMO_SESSION_KEY) || ""; } catch { return ""; }
}
function storedAvatarDock(): boolean {
  try { return localStorage.getItem(AVATAR_DOCK_KEY) === "1"; } catch { return false; }
}
function isTopicId(id?: string | null): boolean {
  return Boolean(id && (id.startsWith("topic:") || id.startsWith("topic_")));
}
function topicIdent(id: string): string {
  return id.startsWith("topic:") ? id.slice(6) : id;
}

const DEST_ITEMS: readonly { id: CanonicalDestination; label: string; to: string; Icon: typeof MessageSquare }[] = [
  { id: "chat", label: "Chat", to: "/", Icon: MessageSquare },
  { id: "agents", label: "Agents", to: "/agents", Icon: Bot },
  { id: "work", label: "Work", to: "/work", Icon: Workflow },
  { id: "library", label: "Library", to: "/library", Icon: FolderOpen },
  { id: "settings", label: "Settings", to: "/settings", Icon: Settings },
];

export function UnifiedShell({ source }: { source: JaegerSource }) {
  const route = useRoute();
  const dest = canonicalDestinationOf(route);
  const gw = useGatewayStore(source);
  const agentsStore = useAgentsStore(source);
  const shellRef = useRef<HTMLDivElement>(null);
  const size = useSizeClass(shellRef);

  const [sidebarOpen, setSidebarOpen] = useState(() =>
    typeof matchMedia === "function" ? !matchMedia(COMPACT_QUERY).matches : true,
  );
  const [avatarOpen, setAvatarOpen] = useState(storedAvatarDock);
  const [avatarState, setAvatarState] = useState<ClipState>("idle");
  const [workOpen, setWorkOpen] = useState(false);
  const [workView, setWorkView] = useState<WorkView | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [searchText, setSearchText] = useState("");
  const [busy, setBusy] = useState(false);
  const [sessionError, setSessionError] = useState("");

  const linkedSession = route.page === "chat" ? route.params.get("session") : null;
  const linkedTopic = route.page === "chat" ? route.params.get("topic") : null;
  const invalidLinked = linkedSession !== null && !validConversationId(linkedSession);
  const [sessionId, setSessionId] = useState(() =>
    linkedSession !== null ? (validConversationId(linkedSession) ? linkedSession : "") : storedSession(),
  );
  const [topic, setTopic] = useState<string | null>(linkedTopic);
  const topicRef = useRef<string | null>(linkedTopic);

  // Sync URL query params into active conversation
  useEffect(() => {
    if (linkedTopic !== topic) {
      topicRef.current = linkedTopic;
      setTopic(linkedTopic);
    }
    if (linkedSession !== null && !invalidLinked && linkedSession !== sessionId) {
      setSessionId(linkedSession);
    }
  }, [linkedSession, linkedTopic, invalidLinked, sessionId, topic]);

  // Auto-select durable home/recent session when none is selected
  useEffect(() => {
    if (linkedSession !== null || !gw.ready) return;
    if (sessionId && gw.sessions.some((s) => s.session_id === sessionId)) return;
    const fallback = gw.sessions.find((s) => s.session_id === JAEGER_HOME_ID) ?? gw.sessions[0];
    if (fallback) {
      setSessionId(fallback.session_id);
      try { localStorage.setItem(DEMO_SESSION_KEY, fallback.session_id); } catch { /* ignore */ }
    }
  }, [gw.ready, gw.sessions, linkedSession, sessionId]);

  // iOS Safari visualViewport keyboard-aware height
  useEffect(() => {
    const viewport = window.visualViewport;
    const shell = shellRef.current;
    if (!viewport || !shell) return;
    const update = () => {
      if (viewport.scale !== 1) {
        shell.style.removeProperty("--jg-viewport-height");
        delete shell.dataset.keyboard;
        return;
      }
      shell.style.setProperty("--jg-viewport-height", `${viewport.height}px`);
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

  // Global keyboard shortcuts: ⌘K palette, ⌘, settings, ⌥⌘A toggle live avatar, ⌘1-5 destinations
  const toggleAvatarDock = useCallback(() => {
    setAvatarOpen((prev) => {
      const next = !prev;
      try { localStorage.setItem(AVATAR_DOCK_KEY, next ? "1" : "0"); } catch { /* ignore */ }
      return next;
    });
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      } else if ((e.metaKey || e.ctrlKey) && e.key === ",") {
        e.preventDefault();
        navigate("/settings");
      } else if (e.altKey && e.metaKey && e.code === "KeyA") {
        e.preventDefault();
        toggleAvatarDock();
      } else if ((e.metaKey || e.ctrlKey) && /^[1-5]$/.test(e.key)) {
        e.preventDefault();
        const item = DEST_ITEMS[Number(e.key) - 1];
        if (item) navigate(item.to);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggleAvatarDock]);

  const host = useMemo(() => {
    const h = new WebHost(source);
    h.home = contractHome(
      httpGetJson(),
      {
        agentName: (id) => (id === JAEGER_HOME_AGENT ? "Jaeger" : id),
        onCursor: (sid, cursor) => h.noteCursor(sid, cursor),
        topicId: () => topicRef.current,
      },
      source.stream.bind(source),
    );
    h.openDetails = () => navigate("/agents");
    return h;
  }, [source]);

  const selectConversation = useCallback((id: string, nextTopic?: string | null) => {
    let targetId = id;
    let t = nextTopic ?? null;
    if (isTopicId(targetId) && !t) {
      t = topicIdent(targetId);
      targetId = JAEGER_HOME_ID;
    }
    setSessionId(targetId);
    topicRef.current = t;
    setTopic(t);
    setSessionError("");
    navigate(conversationPath(targetId, "", t));
    try { localStorage.setItem(DEMO_SESSION_KEY, targetId); } catch { /* ignore */ }
    if (typeof matchMedia === "function" && matchMedia(COMPACT_QUERY).matches) {
      setSidebarOpen(false);
    }
  }, []);

  const startConversation = useCallback(async () => {
    if (busy) return;
    setBusy(true);
    setSessionError("");
    try {
      if (source.kind === "live") {
        const res = await sendJson<{ session_id: string; topic: { topic_id: string } }>(
          "POST",
          `/v1/agents/${encodeURIComponent(JAEGER_HOME_AGENT)}/home/topics`,
          {},
        );
        selectConversation(res.session_id, res.topic.topic_id);
      } else {
        const row = await source.createSession({ agent_id: JAEGER_HOME_AGENT, title: "New chat" });
        selectConversation(row.session_id);
      }
      void gw.refresh();
    } catch (exc) {
      setSessionError(String((exc as Error)?.message ?? exc));
    } finally {
      setBusy(false);
    }
  }, [busy, source, selectConversation, gw]);

  const recoverMissing = useCallback((missingId: string) => {
    gw.markSessionUnavailable(missingId);
    if (sessionId === missingId) {
      setSessionId("");
      try { if (localStorage.getItem(DEMO_SESSION_KEY) === missingId) localStorage.removeItem(DEMO_SESSION_KEY); } catch { /* ignore */ }
    }
  }, [gw, sessionId]);

  const filteredSessions = useMemo(() => {
    const q = searchText.trim().toLowerCase();
    const base = visibleChats(
      gw.sessions.filter((r) => !r.archived && !isBackgroundSession(r)),
      sessionId,
    );
    const matched = q ? base.filter((r) => chatTitle(r).toLowerCase().includes(q)) : base;
    return matched.sort((a, b) => sessionActivity(b) - sessionActivity(a));
  }, [gw.sessions, searchText, sessionId]);

  const dateGroups = useMemo(() => groupChatsByDate(filteredSessions), [filteredSessions]);
  const currentRow = gw.sessions.find((r) => r.session_id === sessionId);
  const activeAgent = gw.agents.find((a) => a.id === (currentRow?.agent_id || JAEGER_HOME_AGENT)) ?? gw.agents[0];
  const headerLabel =
    dest === "chat"
      ? (currentRow ? chatTitle(currentRow) : "Jaeger")
      : dest === "agents"
        ? "Agents & Characters"
        : dest === "work"
          ? "Work"
          : dest === "library"
            ? "Library"
            : "Settings";

  const paletteActions = useMemo<JumpAction[]>(() => [
    { id: "new", label: "New conversation", shortcut: "⌘N", run: () => void startConversation() },
    ...DEST_ITEMS.map((d, idx) => ({
      id: `dest:${d.id}`,
      label: `Go to ${d.label}`,
      shortcut: `⌘${idx + 1}`,
      run: () => navigate(d.to),
    })),
    { id: "avatar", label: avatarOpen ? "Hide Live Avatar" : "Show Live Avatar", shortcut: "⌥⌘A", run: toggleAvatarDock },
    { id: "youtube", label: "Go to YouTube & Studio", hint: "Work", run: () => navigate("/work/youtube") },
    { id: "automations", label: "Go to Automations", hint: "Work", run: () => navigate("/automations") },
    { id: "workspace", label: "Go to Files & Workspace", hint: "Library", run: () => navigate("/research/workspace") },
  ], [startConversation, avatarOpen, toggleAvatarDock]);

  // Sub-tab helpers for the 5 consolidated destinations
  const agentsTab = route.page === "agents" ? (route.sub || "roster") : "roster";
  const workTab =
    route.page === "automations" ? "automations"
      : route.page === "studio" ? "studio"
        : route.page === "feed" ? "feed"
          : route.page === "work" ? (route.sub || "tasks") : "tasks";
  const libraryTab =
    route.page === "research"
      ? (route.sub === "documents" ? "documents" : route.sub === "workspace" ? "workspace" : "research")
      : (route.params.get("section") || "media");
  const { tab: settingsTab, segment: settingsSegment } =
    route.page === "machine"
      ? { tab: "machine" as SettingsTab, segment: route.params.get("section") || undefined }
      : parseSettingsRest(route.rest);

  return (
    <ToastProvider>
      <div
        ref={shellRef}
        className="jg-ushell"
        data-unified-shell="1"
        data-dest={dest}
      >
        <header className="jg-ushell__header" aria-label="Jaeger toolbar">
          <div className="jg-ushell__header-start">
            <button
              type="button"
              className="jg-ushell__icon-btn"
              aria-label="Toggle navigation"
              aria-expanded={sidebarOpen}
              onClick={() => setSidebarOpen((v) => !v)}
            >
              <PanelLeft size={18} />
            </button>
            <button
              type="button"
              className="jg-ushell__icon-btn"
              aria-label="New conversation"
              disabled={!gw.ready || busy}
              onClick={() => void startConversation()}
            >
              <Pencil size={17} />
            </button>
          </div>

          <div className="jg-ushell__title" title={headerLabel}>
            <JaegerAvatar portraitOverride={activeAgent?.avatar_url} state={!gw.ready || gw.error ? "connecting" : avatarState} />
            <span>{headerLabel}</span>
          </div>

          <div className="jg-ushell__header-end">
            <ApprovalTray source={source} onOpenChat={() => navigate("/")} />
            {dest === "chat" && (
              <button
                type="button"
                className="jg-ushell__icon-btn"
                aria-label="Toggle live avatar"
                aria-pressed={avatarOpen}
                title="Live Avatar (⌥⌘A)"
                onClick={toggleAvatarDock}
              >
                <Bot size={17} />
                <span>Avatar</span>
              </button>
            )}
            <button
              type="button"
              className="jg-ushell__icon-btn"
              aria-label="Toggle tools workspace"
              aria-pressed={workOpen}
              title="Tools & Inspector"
              onClick={() => { setWorkView((v) => v || "tools"); setWorkOpen((v) => !v); }}
            >
              <PanelRight size={18} />
            </button>
          </div>
        </header>

        <aside className="jg-ushell__sidebar" data-open={String(sidebarOpen)} aria-label="Primary navigation">
          <div className="jg-ushell__rail">
            <nav className="jg-ushell__rail-nav" aria-label="Destinations">
              {DEST_ITEMS.slice(0, 4).map(({ id, label, to, Icon }) => (
                <button
                  key={id}
                  type="button"
                  className="jg-ushell__rail-btn"
                  aria-label={label}
                  aria-current={dest === id ? "page" : undefined}
                  onClick={() => navigate(to)}
                >
                  <Icon size={20} />
                  <span>{label}</span>
                </button>
              ))}
            </nav>
            <button
              type="button"
              className="jg-ushell__rail-btn"
              aria-label="Settings"
              aria-current={dest === "settings" ? "page" : undefined}
              onClick={() => navigate("/settings")}
            >
              <Settings size={20} />
              <span>Settings</span>
            </button>
          </div>

          <section className="jg-ushell__context" hidden={!sidebarOpen} aria-label={`${headerLabel} sidebar`}>
            <div className="jg-ushell__brand">
              <span className="jg-ushell__brand-mark"><JaegerMark /><span>Jaeger</span></span>
            </div>

            {dest === "chat" && (
              <>
                <button
                  type="button"
                  className="jg-ushell__new-btn"
                  disabled={!gw.ready || busy}
                  onClick={() => void startConversation()}
                >
                  <Plus size={16} />
                  <span>{busy ? "Opening…" : "New conversation"}</span>
                </button>
                <label className="jg-ushell__search">
                  <Search size={15} aria-hidden="true" />
                  <input
                    type="search"
                    value={searchText}
                    placeholder="Search conversations"
                    aria-label="Search conversations"
                    onChange={(e) => setSearchText(e.target.value)}
                  />
                </label>
                <div className="jg-ushell__list">
                  <button
                    type="button"
                    className="jg-ushell__row"
                    aria-current={sessionId === JAEGER_HOME_ID && !topic ? "true" : undefined}
                    onClick={() => selectConversation(JAEGER_HOME_ID, null)}
                  >
                    Jaeger (Home)
                  </button>
                  {dateGroups.map((group) => (
                    <div key={group.label}>
                      <div className="jg-ushell__section-label">{group.label}</div>
                      {group.rows.map((row: SessionRow) => (
                        <button
                          key={row.session_id}
                          type="button"
                          className="jg-ushell__row"
                          aria-current={row.session_id === sessionId && !topic ? "true" : undefined}
                          onClick={() => selectConversation(row.session_id)}
                        >
                          {chatTitle(row)}
                        </button>
                      ))}
                    </div>
                  ))}
                </div>
              </>
            )}

            {dest === "agents" && (
              <div className="jg-ushell__list">
                <div className="jg-ushell__section-label">Entities</div>
                {[
                  ["roster", "Agents & Characters", "/agents"],
                  ["characters", "Character Library", "/agents/characters"],
                  ["knowledge", "Memory & Skills", "/agents/knowledge"],
                  ["team", "Office (Optional)", "/agents/team"],
                ].map(([id, title, to]) => (
                  <button key={id} type="button" className="jg-ushell__row" aria-current={agentsTab === id ? "page" : undefined} onClick={() => navigate(to)}>
                    {title}
                  </button>
                ))}
              </div>
            )}

            {dest === "work" && (
              <div className="jg-ushell__list">
                <div className="jg-ushell__section-label">Work & Creation</div>
                {[
                  ["tasks", "Tasks & Workflows", "/work/tasks"],
                  ["automations", "Automations", "/automations"],
                  ["youtube", "YouTube Production", "/work/youtube"],
                  ["studio", "Imagine & Media Studio", "/studio"],
                  ["calendar", "Calendar", "/work/calendar"],
                  ["process", "Process & Runs", "/work/process"],
                ].map(([id, title, to]) => (
                  <button key={id} type="button" className="jg-ushell__row" aria-current={workTab === id ? "page" : undefined} onClick={() => navigate(to)}>
                    {title}
                  </button>
                ))}
              </div>
            )}

            {dest === "library" && (
              <div className="jg-ushell__list">
                <div className="jg-ushell__section-label">Assets & Files</div>
                {[
                  ["media", "Media & Outputs", "/library?section=media"],
                  ["documents", "Documents", "/research/documents"],
                  ["research", "Research", "/research"],
                  ["workspace", "Files & Trusted Folders", "/research/workspace"],
                ].map(([id, title, to]) => (
                  <button key={id} type="button" className="jg-ushell__row" aria-current={libraryTab === id ? "page" : undefined} onClick={() => navigate(to)}>
                    {title}
                  </button>
                ))}
              </div>
            )}

            {dest === "settings" && (
              <div className="jg-ushell__list">
                <div className="jg-ushell__section-label">System</div>
                {[
                  ["appearance", "Appearance", "/settings/appearance"],
                  ["models", "Models & Failover", "/settings/models"],
                  ["voice", "Voice & Audio", "/settings/voice"],
                  ["integrations", "Integrations & MCP", "/settings/integrations"],
                  ["machine", "Machine & Trusted Paths", "/settings/machine"],
                  ["memory", "Memory & Profile", "/settings/memory"],
                  ["checkpoints", "Checkpoints", "/settings/checkpoints"],
                ].map(([id, title, to]) => (
                  <button key={id} type="button" className="jg-ushell__row" aria-current={settingsTab === id ? "page" : undefined} onClick={() => navigate(to)}>
                    {title}
                  </button>
                ))}
              </div>
            )}

            <div className="jg-ushell__footer" role="status">
              <span>{gw.error ? "Connection error" : gw.ready ? (gw.executionHost ? `Connected · ${gw.executionHost}` : "Connected") : "Connecting…"}</span>
            </div>
          </section>
        </aside>

        {sidebarOpen && (
          <button
            type="button"
            className="jg-ushell__backdrop"
            aria-label="Close navigation"
            onClick={() => setSidebarOpen(false)}
          />
        )}

        <main className="jg-ushell__main">
          {(gw.error || sessionError) && (
            <div className="jg-ushell__alert" role="alert">
              <span>{sessionError || gw.error}</span>
              <button type="button" className="jg-ushell__icon-btn" onClick={() => void gw.refresh()}>Retry</button>
            </div>
          )}

          {/* Chat stays mounted across tab switches so streams, drafts, voice, and scroll position persist */}
          <section className="jg-ushell__stage" hidden={dest !== "chat"} aria-label="Chat">
            <div className="jg-ushell__chat-host">
              {sessionId && gw.ready && !invalidLinked ? (
                <ChatPane
                  onAvatarState={setAvatarState}
                  host={host}
                  sessionId={sessionId}
                  topicId={sessionId === JAEGER_HOME_ID ? topic : null}
                  agents={activeAgent ? [activeAgent] : gw.agents}
                  onSessionMissing={recoverMissing}
                />
              ) : (
                <div className="jg-u-page">
                  <h1>{gw.ready ? "Ready when you are" : "Connecting to Jaeger…"}</h1>
                  {gw.ready && (
                    <button type="button" className="jg-ushell__new-btn" onClick={() => void startConversation()}>
                      <Plus size={16} /> Start conversation
                    </button>
                  )}
                </div>
              )}
            </div>
            {/* Real 3D/VRM/Rive AvatarPanel — renders ONLY when selected AND Chat is visible */}
            {dest === "chat" && avatarOpen && activeAgent && (
              <div className="jg-ushell__avatar-dock" data-avatar-dock="1">
                <AvatarPanel
                  clipState={gw.error ? "connecting" : avatarState}
                  size={size}
                  agent={activeAgent}
                  presence={agentsStore.summaries.find((s) => s.id === activeAgent.id)?.status}
                  onOpenAgents={(id) => navigate(`/agents/${encodeURIComponent(id)}/avatar`)}
                />
              </div>
            )}
          </section>

          {dest === "agents" && (
            <section className="jg-ushell__page" aria-label="Agents and Characters">
              <nav className="jg-ushell__subnav" aria-label="Agents sections">
                {[
                  ["roster", "Agents & Characters", "/agents"],
                  ["characters", "Characters", "/agents/characters"],
                  ["knowledge", "Memory & Skills", "/agents/knowledge"],
                  ["team", "Office", "/agents/team"],
                ].map(([id, title, to]) => (
                  <button key={id} type="button" className="jg-ushell__subnav-btn" aria-current={agentsTab === id ? "page" : undefined} onClick={() => navigate(to)}>
                    {title}
                  </button>
                ))}
              </nav>
              <div className="jg-ushell__page-body">
                <Suspense fallback={<PageFallback />}>
                  {agentsTab === "knowledge" ? (
                    <KnowledgePage source={source} agents={gw.agents} />
                  ) : agentsTab === "team" ? (
                    <PixelOffice source={source} onNavigate={navigate} params={route.params} />
                  ) : agentsTab === "characters" ? (
                    <CharactersPage characterId={route.params.get("character")} source={source} refresh={agentsStore.refresh} onNavigate={navigate} />
                  ) : route.rest === "activity" ? (
                    <AgentsActivityPage source={source} onNavigate={navigate} />
                  ) : (
                    <AgentsRoster
                      source={source}
                      store={agentsStore}
                      refresh={agentsStore.refresh}
                      onNavigate={navigate}
                      avatarFor={/^(.+)\/avatar$/.exec(route.rest)?.[1] ?? null}
                    />
                  )}
                </Suspense>
              </div>
            </section>
          )}

          {dest === "work" && (
            <section className="jg-ushell__page" aria-label="Work">
              <nav className="jg-ushell__subnav" aria-label="Work sections">
                {[
                  ["tasks", "Tasks", "/work/tasks"],
                  ["automations", "Automations", "/automations"],
                  ["youtube", "YouTube", "/work/youtube"],
                  ["studio", "Studio", "/studio"],
                  ["calendar", "Calendar", "/work/calendar"],
                  ["process", "Process", "/work/process"],
                ].map(([id, title, to]) => (
                  <button key={id} type="button" className="jg-ushell__subnav-btn" aria-current={workTab === id ? "page" : undefined} onClick={() => navigate(to)}>
                    {title}
                  </button>
                ))}
              </nav>
              <div className="jg-ushell__page-body">
                <Suspense fallback={<PageFallback />}>
                  {workTab === "automations" && source.schedules ? (
                    <AutomationsPanel controls={source.schedules} />
                  ) : workTab === "youtube" ? (
                    <YouTubePage params={route.params} onNavigate={navigate} />
                  ) : workTab === "studio" ? (
                    <StudioPage source={source} agents={gw.agents} onNavigate={navigate} />
                  ) : workTab === "calendar" ? (
                    <CalendarPage source={source} onNavigate={navigate} />
                  ) : workTab === "process" ? (
                    <ProcessView source={source} params={route.params} />
                  ) : workTab === "feed" ? (
                    <CompanionPage page="feed" source={source} agents={gw.agents} onNavigate={navigate} />
                  ) : route.sub === "tasks" && route.rest === "gallery" ? (
                    <TasksPage source={source} />
                  ) : (
                    <TasksWorkspace source={source} agents={gw.agents} params={route.params} onNavigate={navigate} />
                  )}
                </Suspense>
              </div>
            </section>
          )}

          {dest === "library" && (
            <section className="jg-ushell__page" aria-label="Library">
              <nav className="jg-ushell__subnav" aria-label="Library sections">
                {[
                  ["media", "Media & Outputs", "/library?section=media"],
                  ["documents", "Documents", "/research/documents"],
                  ["research", "Research", "/research"],
                  ["workspace", "Files & Folders", "/research/workspace"],
                ].map(([id, title, to]) => (
                  <button key={id} type="button" className="jg-ushell__subnav-btn" aria-current={libraryTab === id ? "page" : undefined} onClick={() => navigate(to)}>
                    {title}
                  </button>
                ))}
              </nav>
              <div className="jg-ushell__page-body">
                <Suspense fallback={<PageFallback />}>
                  {libraryTab === "documents" ? (
                    <DocumentsPage params={route.params} />
                  ) : libraryTab === "research" ? (
                    <ResearchPage source={source} agents={gw.agents} onNavigate={navigate} />
                  ) : libraryTab === "workspace" ? (
                    <WorkspaceBrowser source={source} params={route.params} />
                  ) : (
                    <CompanionPage page="library" source={source} agents={gw.agents} onNavigate={navigate} />
                  )}
                </Suspense>
              </div>
            </section>
          )}

          {dest === "settings" && (
            <section className="jg-ushell__page" aria-label="Settings">
              <SettingsView
                source={source}
                agents={gw.agents}
                sessionId={sessionId || undefined}
                tab={settingsTab}
                segment={settingsSegment}
                params={route.params}
                onTab={(t) => navigate(t ? `/settings/${t}` : "/settings", { replace: Boolean(t && settingsTab) })}
                onOpenConversation={(sid) => { selectConversation(sid); navigate("/"); }}
                onClose={() => navigate("/")}
              />
            </section>
          )}
        </main>

        {/* Responsive mobile/iPhone 5-destination bottom navigation */}
        <nav className="jg-ushell__bottom-nav" aria-label="Mobile navigation">
          {DEST_ITEMS.map(({ id, label, to, Icon }) => (
            <button
              key={id}
              type="button"
              className="jg-ushell__bottom-btn"
              aria-current={dest === id ? "page" : undefined}
              onClick={() => navigate(to)}
            >
              <Icon size={19} />
              <span>{label}</span>
            </button>
          ))}
        </nav>

        {workView && (
          <ConversationWorkPanel
            source={source}
            sessionId={sessionId}
            agents={gw.agents}
            recent={gw.sessions}
            onResize={() => undefined}
            open={workOpen}
            view={workView}
            onView={setWorkView}
            onClose={() => setWorkOpen(false)}
            onConversation={(sid) => { selectConversation(sid); navigate("/"); }}
          />
        )}

        <JumpTo
          open={paletteOpen}
          agents={gw.agents.filter(visible)}
          onClose={() => setPaletteOpen(false)}
          summaries={agentsStore.summaries}
          seen={agentsStore.seen}
          onAgent={() => navigate("/")}
          actions={paletteActions}
        />
      </div>
    </ToastProvider>
  );
}
