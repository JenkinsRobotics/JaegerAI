import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { JaegerSource } from "./api/source";
import { AgentDetails } from "./agents/AgentDetails";
import { agentsSidebarSlots, type Selection } from "./agents/AgentsSidebar";
import { useAgentsStore } from "./agents/agentsStore";
import { label, visible } from "./agents/agentsLogic";
import { useAgentChats, visibleChats } from "./agents/chats";
import { agentSlug, NewChatMenu } from "./agents/NewChatMenu";
import { ChatPane } from "./chat/ChatPane";
import { NativeHost } from "./chat/nativeHost";
import { WebHost } from "./chat/webHost";
import { ConnectAppsDialog } from "./connect-apps/ConnectAppsDialog";
import { detectHost } from "./platform/host";
import { onNativeEvent } from "./platform/native";
import { AppShell } from "./shell/AppShell";
import { ErrorState } from "./shell/ErrorState";
import { TasksBoard } from "./tasks/TasksBoard";

const LEAD_ID = "native:jaeger";
/** The chat this device last opened for each agent, kept across restarts. */
const CHOSEN_KEY = "jaeger.ui.chosen-chat";

function loadChosen(): Map<string, string> {
  try {
    return new Map(Object.entries(JSON.parse(localStorage.getItem(CHOSEN_KEY) ?? "{}") as Record<string, string>));
  } catch {
    return new Map();
  }
}

const message = (error: unknown) => String((error as Error)?.message ?? error);

export function App({ source }: { source: JaegerSource }) {
  const hostKind = detectHost();
  const host = useMemo(() => {
    const created = hostKind === "macos" ? new NativeHost(source) : new WebHost(source);
    // Dev mock only: show the voice controls for visual parity with the target.
    // Live default stays off (flag + native mic/tts probe).
    if (source.kind === "mock" && hostKind !== "macos") created.capabilities = { voice: true };
    return created;
  }, [source, hostKind]);
  const store = useAgentsStore(source);
  const [selection, setSelection] = useState<Selection>({ type: "agent", agentId: LEAD_ID });
  const [sessionId, setSessionId] = useState<string>();
  const [sessionError, setSessionError] = useState<string>();
  const [sessionAttempt, setSessionAttempt] = useState(0);
  const [connectOpen, setConnectOpen] = useState(false);
  const [newChatAnchor, setNewChatAnchor] = useState<HTMLElement | null>(null);
  const [detailsAgentId, setDetailsAgentId] = useState<string | null>(null);
  const [chatsVersion, setChatsVersion] = useState(0);
  const refreshChats = useCallback(() => setChatsVersion((n) => n + 1), []);

  const selectedAgentId = selection.type === "agent" ? selection.agentId : undefined;
  const explicitSessionId = selection.type === "agent" ? selection.sessionId : undefined;

  // Chats follow the roster poll, so a fresh chat appears once it has messages.
  useEffect(() => { refreshChats(); }, [store.summaries, refreshChats]);
  const chatRows = useAgentChats(source, selectedAgentId, chatsVersion);
  const chats = useMemo(() => visibleChats(chatRows, sessionId), [chatRows, sessionId]);
  const detailsRows = useAgentChats(source, detailsAgentId ?? undefined, chatsVersion);

  const chosen = useRef(loadChosen());
  const remember = useCallback((agentId: string, id: string | undefined) => {
    if (id) chosen.current.set(agentId, id);
    else chosen.current.delete(agentId);
    localStorage.setItem(CHOSEN_KEY, JSON.stringify(Object.fromEntries(chosen.current)));
  }, []);

  // Resolve the selection to a chat: the one asked for, else the one this
  // device last opened for that agent, else its latest chat with messages,
  // else an existing empty one, else a new one. One lookup per agent at a
  // time, so effect re-runs never create a burst of empty chats.
  const resolving = useRef(new Map<string, Promise<string>>());
  useEffect(() => {
    if (!selectedAgentId) return;
    let live = true;
    const agentId = selectedAgentId;
    // A remembered chat is only a hint: it may be archived or gone (another
    // device, a reset state), so it is checked against the agent's chats.
    const remembered = explicitSessionId ? undefined : chosen.current.get(agentId);
    let resolve = explicitSessionId ? Promise.resolve(explicitSessionId) : resolving.current.get(agentId);
    if (!resolve) {
      resolve = source.sessions({ agent_id: agentId }).then((rows) => {
        if (remembered && rows.some((r) => r.session_id === remembered && !r.archived)) return remembered;
        const thread = rows.find((r) => !r.archived && ((r.message_count ?? 0) > 0 || r.last_message_preview)) ?? rows.find((r) => !r.archived);
        return thread?.session_id ?? source.createSession({ agent_id: agentId }).then((s) => s.session_id);
      }).finally(() => resolving.current.delete(agentId));
      resolving.current.set(agentId, resolve);
    }
    setSessionError(undefined);
    resolve.then(
      (id) => { if (live) { remember(agentId, id); setSessionId(id); } },
      (error: unknown) => { if (live) { setSessionId(undefined); setSessionError(message(error)); } },
    );
    store.seeAgent(agentId);
    return () => { live = false; };
  }, [selectedAgentId, explicitSessionId, source, store.seeAgent, sessionAttempt, remember]);

  /** A fresh chat with `agentId`. The old chat keeps its place in the sidebar. */
  const newChat = useCallback((agentId: string) => {
    void source.createSession({ agent_id: agentId }).then(
      (s) => { remember(agentId, s.session_id); setSelection({ type: "agent", agentId, sessionId: s.session_id }); refreshChats(); },
      (error: unknown) => setSessionError(message(error)),
    );
  }, [source, remember, refreshChats]);

  const createAgent = useCallback(async (displayName: string, job: string) => {
    const agent = await source.createAgent({
      name: agentSlug(displayName), display_name: displayName, ...(job ? { metadata: { specialty: job } } : {}),
    });
    await store.refresh();
    newChat(agent.id);
  }, [source, store.refresh, newChat]);

  const renameChat = useCallback((id: string, title: string) => {
    void source.updateSession(id, { title }).then(refreshChats, (error: unknown) => setSessionError(message(error)));
  }, [source, refreshChats]);

  const archiveChat = useCallback((id: string) => {
    void source.updateSession(id, { archived: true }).then(() => {
      if (id === sessionId && selectedAgentId) {
        remember(selectedAgentId, undefined);
        setSelection({ type: "agent", agentId: selectedAgentId });
        setSessionAttempt((n) => n + 1);
      }
      refreshChats();
    }, (error: unknown) => setSessionError(message(error)));
  }, [source, sessionId, selectedAgentId, remember, refreshChats]);

  // A handoff marker opens the specialist's side of that exchange: its own
  // chat, selected under its agent in the sidebar.
  const openHandoff = useCallback((handoffId: string) => {
    source.handoffExchange(handoffId).then(
      (x) => setSelection({ type: "agent", agentId: x.to_agent_id, sessionId: x.worker_session_id }),
      (error: unknown) => setSessionError(`Couldn't open that exchange: ${message(error)}`),
    );
  }, [source]);

  // Host wiring: names for markers, handoff + details links.
  useEffect(() => {
    host.setAgentNames(new Map(store.agents.map((a) => [a.id, label(a)])));
    host.openHandoff = openHandoff;
    host.openDetails = (agentId: string) => setDetailsAgentId(agentId);
  }, [host, store.agents, openHandoff]);
  useEffect(() => onNativeEvent((detail) => { if (detail.type === "window.visibility") void store.refresh(); }), [store.refresh]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "n") { event.preventDefault(); newChat(selectedAgentId ?? LEAD_ID); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [newChat, selectedAgentId]);

  const slots = agentsSidebarSlots({
    state: store,
    selection: selection.type === "agent" ? { ...selection, sessionId } : selection,
    chats,
    onSelect: setSelection,
    onNewChatMenu: setNewChatAnchor,
    onRenameChat: renameChat,
    onArchiveChat: archiveChat,
    onSearch: () => { /* search lands with /v1/sessions?q= */ },
    onConnectApps: () => setConnectOpen(true),
    onRetry: () => void store.refresh(),
    userInitials: "MJ",
    status: source.kind === "mock"
      ? { kind: "warn", label: "Mock data (dev)" }
      : store.error ? { kind: "error", label: "Gateway unreachable" } : { kind: "ok", label: "Connected" },
  });

  const detailsAgent = store.agents.find((a) => a.id === detailsAgentId);
  return (
    <>
      <AppShell top={slots.top} primary={slots.primary} sections={slots.sections} footer={slots.footer}>
        {selection.type === "tasks"
          ? <TasksBoard source={source} agents={store.agents} />
          : (
            <div className="jg-main-row">
              {sessionError
                ? <ErrorState title="Couldn't open this chat" error={sessionError} onRetry={() => setSessionAttempt((n) => n + 1)} />
                : <ChatPane host={host} sessionId={sessionId} />}
              {detailsAgent && (
                <AgentDetails agent={detailsAgent} summary={store.summaries.find((s) => s.id === detailsAgent.id)}
                  chats={visibleChats(detailsRows, sessionId)} openId={sessionId}
                  onOpenChat={(id) => setSelection({ type: "agent", agentId: detailsAgent.id, sessionId: id })}
                  onNewChat={() => newChat(detailsAgent.id)} onClose={() => setDetailsAgentId(null)} />
              )}
            </div>
          )}
      </AppShell>
      <NewChatMenu anchor={newChatAnchor} agents={store.agents.filter(visible)} onClose={() => setNewChatAnchor(null)}
        onNewChat={newChat} onCreateAgent={createAgent} />
      <ConnectAppsDialog open={connectOpen} onClose={() => setConnectOpen(false)} />
    </>
  );
}
