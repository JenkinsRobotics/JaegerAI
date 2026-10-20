import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { JaegerSource } from "./api/source";
import { PrimaryPicker } from "./agents/PrimaryPicker";
import { AgentManagement } from "./agents/AgentManagement";
import { AgentDetails } from "./agents/AgentDetails";
import { agentsSidebarSlots, type Selection } from "./agents/AgentsSidebar";
import { useAgentsStore } from "./agents/agentsStore";
import { label, visible } from "./agents/agentsLogic";
import { agentSlug, NewChatMenu } from "./agents/NewChatMenu";
import { loadPins, pin, savePins, unpin, MAX_PINS } from "./agents/pins";
import { HistoryPanel } from "./agents/HistoryPanel";
import { ChatPane } from "./chat/ChatPane";
import { autoHome, contractHome, fallbackHome, httpGetJson, type HomeSessions } from "./chat/homeSession";
import { NativeHost } from "./chat/nativeHost";
import { WebHost } from "./chat/webHost";
import { ConnectAppsDialog } from "./connect-apps/ConnectAppsDialog";
import { SettingsDialog } from "./settings/SettingsDialog";
import { JumpTo } from "./agents/JumpTo";
import { detectHost } from "./platform/host";
import { onNativeEvent } from "./platform/native";
import { AppShell } from "./shell/AppShell";
import { ErrorState } from "./shell/ErrorState";
import { TasksBoard } from "./tasks/TasksBoard";
import { PhoneChat, PhoneList } from "./phone/PhoneShell";
import { usePhone } from "./phone/usePhone";
import { AgentContextMenu, AgentPrompt, type AgentMenuAction } from "./agents/AgentContextMenu";
import { capabilitiesOf, type HostCapabilities } from "./chat/hostH8";
import { agentCaps, conversationIdForAgent } from "./api/agentActions";
import type { Agent } from "./api/types";
import "./phone/phone.css";

const LEAD_ID = "native:jaeger";

/** The home-chat contract (landed 417d8a0c) is the default, feature-detected per gateway (autoHome);
 * `?home=fallback` (or localStorage jaeger.ui.home-contract=0) forces today's most-recent-chat fallback. */
function forcesFallback(): boolean {
  if (typeof location !== "undefined" && new URLSearchParams(location.search).get("home") === "fallback") return true;
  try { return localStorage.getItem("jaeger.ui.home-contract") === "0"; } catch { return false; }
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
  const phone = usePhone();
  const [phoneView, setPhoneView] = useState<"list" | "chat">("list");
  const [agentMenu, setAgentMenu] = useState<{ agentId: string; x: number; y: number } | null>(null);
  const [agentPrompt, setAgentPrompt] = useState<{ kind: "rename" | "delete" | "section" | "duplicate"; agent: Agent } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  useEffect(() => { if (!notice) return; const t = setTimeout(() => setNotice(null), 2600); return () => clearTimeout(t); }, [notice]);
  // Grok-style sessions: one home chat per agent, history read-only.
  const names = useRef<(id: string) => string>((id) => id);
  const home: HomeSessions = useMemo(() => {
    const opts = { agentName: (id: string) => names.current(id), onCursor: (sid: string, id: number) => host.noteCursor(sid, id) };
    if (source.homeSessions) return source.homeSessions(opts);
    const fallback = fallbackHome(source, opts);
    return forcesFallback() ? fallback : autoHome(contractHome(httpGetJson(), opts, source.stream.bind(source)), fallback);
  }, [source, host]);
  host.home = home;
  const [selection, setSelection] = useState<Selection>({ type: "agent", agentId: LEAD_ID });
  const [initialReady, setInitialReady] = useState(false);
  const [primaryPicker, setPrimaryPicker] = useState<{ expectedId: string } | null>(null);
  const defaultAgentId = store.agents.find((a) => a.primary)?.id ?? LEAD_ID;
  useEffect(() => {
    if (!initialReady && store.agents.length) {
      setSelection({ type: "agent", agentId: defaultAgentId });
      setInitialReady(true);
    }
  }, [initialReady, store.agents, defaultAgentId]);
  const [sessionId, setSessionId] = useState<string>();
  const [sessionError, setSessionError] = useState<string>();
  const [sessionAttempt, setSessionAttempt] = useState(0);
  const [connectOpen, setConnectOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsCaps, setSettingsCaps] = useState<HostCapabilities>(() => capabilitiesOf(host));
  useEffect(() => {
    if (!settingsOpen) return;
    let live = true;
    setSettingsCaps(capabilitiesOf(host));
    if (host instanceof NativeHost) void host.probeCapabilities().then((caps) => { if (live) setSettingsCaps({ ...caps }); }).catch(() => { if (live) setSettingsCaps({ voice: false }); });
    return () => { live = false; };
  }, [host, settingsOpen]);
  const [jumpOpen, setJumpOpen] = useState(false);
  const [newChatAnchor, setNewChatAnchor] = useState<HTMLElement | null>(null);
  const [detailsAgentId, setDetailsAgentId] = useState<string | null>(null);
  const [historyAgentId, setHistoryAgentId] = useState<string | null>(null);
  const [historySessionId, setHistorySessionId] = useState<string>();
  const [managementBusy, setManagementBusy] = useState(false);
  const pinQueue = useRef(Promise.resolve());
  const [pins, setPins] = useState<string[]>(loadPins);
  // Poll/SSE projections are authoritative on supporting servers; never upload local pins implicitly.
  const sharedPins = Boolean(source.agentActions?.savePins) && store.agents.some((a) => a.ui_actions?.pin);
  const projectedPins = store.agents.filter((a) => a.pinned).sort((a, b) => (a.pin_order ?? 0) - (b.pin_order ?? 0)).map((a) => a.id);
  const devicePins = loadPins().filter((id) => store.agents.some((a) => a.id === id && a.ui_actions?.pin));
  const pinSignature = JSON.stringify(projectedPins);
  useEffect(() => { if (sharedPins) setPins(JSON.parse(pinSignature) as string[]); }, [sharedPins, pinSignature]);
  const updatePins = useCallback((next: (cur: string[]) => string[]) => {
    if (!sharedPins || !source.agentActions?.savePins) {
      setPins((cur) => { const n = next(cur); savePins(n); return n; });
      return;
    }
    pinQueue.current = pinQueue.current.then(async () => {
      const fresh = await source.agents();
      const current = fresh.filter((a) => a.pinned).sort((a, b) => (a.pin_order ?? 0) - (b.pin_order ?? 0)).map((a) => a.id);
      await source.agentActions!.savePins!(next(current), current);
      await store.refresh();
    }).catch(async (error: unknown) => { setNotice(`Couldn't save pins: ${message(error)}`); await store.refresh(); });
  }, [sharedPins, source, store.refresh]);

  const selectedAgentId = selection.type === "agent" ? selection.agentId : undefined;
  const explicitSessionId = selection.type === "agent" ? selection.sessionId : undefined;

  // Selecting an agent opens its one home chat. An explicit session (a handoff's worker side) opens as is.
  useEffect(() => {
    if (!selectedAgentId || !initialReady) return;
    let live = true;
    setSessionError(undefined);
    (explicitSessionId ? Promise.resolve(explicitSessionId) : home.home(selectedAgentId)).then(
      (id) => { if (live) setSessionId(id); },
      (error: unknown) => { if (live) { setSessionId(undefined); setSessionError(message(error)); } },
    );
    store.seeAgent(selectedAgentId);
    return () => { live = false; };
  }, [selectedAgentId, explicitSessionId, home, store.seeAgent, sessionAttempt, initialReady]);

  /** There is one chat per agent now: "new chat with X" opens X's home chat. */
  const newChat = useCallback((agentId: string) => { if (agentId === selectedAgentId) void store.seeAgent(agentId); setSelection({ type: "agent", agentId }); }, [selectedAgentId, store.seeAgent]);

  const createAgent = useCallback(async (displayName: string, job: string) => {
    const agent = await source.createAgent({
      name: agentSlug(displayName), display_name: displayName, ...(job ? { metadata: { specialty: job } } : {}),
    });
    await store.refresh();
    newChat(agent.id);
  }, [source, store.refresh, newChat]);

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
    host.openDetails = (agentId: string) => { setHistoryAgentId(null); setDetailsAgentId(agentId); };
    host.openHistory = (agentId: string) => { setDetailsAgentId(null); setHistorySessionId(undefined); setHistoryAgentId(agentId); };
    host.openChat = (sessionId: string) => { setDetailsAgentId(null); setHistorySessionId(sessionId); setHistoryAgentId(selectedAgentId ?? defaultAgentId); };
    const byId = new Map(store.agents.map((a) => [a.id, label(a)]));
    names.current = (id: string) => byId.get(id) ?? id;
  }, [host, store.agents, openHandoff, selectedAgentId, defaultAgentId]);
  useEffect(() => onNativeEvent((detail) => { if (detail.type === "window.visibility") void store.refresh(); }), [store.refresh]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key === ",") { event.preventDefault(); setSettingsOpen(true); return; }
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); setJumpOpen((v) => !v); return; }
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "n") { event.preventDefault(); newChat(selectedAgentId ?? defaultAgentId); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [newChat, selectedAgentId, defaultAgentId]);

  const actions = source.agentActions;
  const caps = agentCaps(agentMenu ? store.agents.filter((a) => a.id === agentMenu.agentId) : store.agents, actions);
  const copy = (text: string, done: string) => host.copy(text).then(() => setNotice(done), () => setNotice("Couldn't copy"));
  const fail = (what: string) => (error: unknown) => setNotice(`Couldn't ${what}: ${message(error)}`);
  const onAgentAction = (action: AgentMenuAction, agent: Agent) => {
    switch (action) {
      case "open": if (selectedAgentId === agent.id) void store.seeAgent(agent.id); setSelection({ type: "agent", agentId: agent.id }); setDetailsAgentId(null); setHistoryAgentId(null); setPhoneView("chat"); return;
      case "profile": setHistoryAgentId(null); setDetailsAgentId(agent.id); return;
      case "history": setDetailsAgentId(null); setHistorySessionId(undefined); setHistoryAgentId(agent.id); return;
      case "replace-primary": setPrimaryPicker({ expectedId: defaultAgentId }); return;
      case "make-primary": void changePrimary(agent.id, defaultAgentId); return;
      case "unread":
        if (actions?.markUnread) void actions.markUnread(agent.id).then(() => store.refresh(), fail("mark it unread"));
        return;
      case "read": void store.seeAgent(agent.id); return;
      case "rename": setAgentPrompt({ kind: "rename", agent }); return;
      case "pin": case "unpin":
        updatePins((cur) => action === "pin" ? pin(cur, agent.id) : unpin(cur, agent.id)); return;
      case "hide": void changePresentation(agent, { archived: true }); return;
      case "template": if (actions) void actions.template(agent.id).then((t) => copy(JSON.stringify(t, null, 2), "Template copied"), fail("get the template")); return;
      case "copy-id":
        void conversationIdForAgent(agent.id, (id) => home.home(id), selectedAgentId && explicitSessionId ? { agentId: selectedAgentId, sessionId: explicitSessionId } : undefined)
          .then((id) => copy(id, "Conversation ID copied"), fail("resolve the conversation"));
        return;
      case "section": case "duplicate": case "delete": setAgentPrompt({ kind: action, agent }); return;
    }
  };
  const changePrimary = async (id: string, expectedId: string) => {
    if (!actions?.setPrimary || managementBusy) return;
    setManagementBusy(true);
    try {
      await actions.setPrimary(id, expectedId);
      await store.refresh();
      setPrimaryPicker(null);
      setNotice("Primary bot updated; your open chat and draft stay here");
    } catch (error) { fail("replace the primary bot")(error); await store.refresh(); }
    finally { setManagementBusy(false); }
  };
  const changePresentation = async (agent: Agent, patch: { display_name?: string | null; archived?: boolean }) => {
    if (!actions || managementBusy) return;
    setManagementBusy(true);
    try {
      await actions.patchAgent(agent.id, patch);
      await store.refresh();
      setNotice(patch.archived === true ? `${label(agent)} archived; its work and history are kept` : patch.archived === false ? `${label(agent)} restored` : 'Display name updated');
    } catch (error) { fail('update agent presentation')(error); }
    finally { setManagementBusy(false); }
  };
  const onPromptDone = (ok: boolean, value?: string) => {
    const p = agentPrompt; setAgentPrompt(null);
    if (!ok || !p || !actions) return;
    if (p.kind === "rename") {
      void changePresentation(p.agent, { display_name: value! });
    } else if (p.kind === "delete") {
      void actions.remove(p.agent.id).then(async () => {
        setNotice(`${label(p.agent)} deleted`);
        if (selectedAgentId === p.agent.id) { setSelection({ type: "agent", agentId: defaultAgentId }); setPhoneView("list"); }
        await store.refresh();
      }, fail("delete it"));
    } else if (p.kind === "section") {
      void actions.createSection(value!).then((sec) => actions.patchAgent(p.agent.id, { section_id: sec.id })).then(() => store.refresh(), fail("create the section"));
    } else {
      void actions.duplicate(p.agent.id, value || undefined).then(async (a) => { await store.refresh(); setNotice(`${label(a)} created`); }, fail("duplicate it"));
    }
  };
  const menuAgent = agentMenu ? store.agents.find((a) => a.id === agentMenu.agentId) : undefined;
  const openAgentMenu = (agentId: string, x: number, y: number) => setAgentMenu({ agentId, x, y });

  const slots = agentsSidebarSlots({
    state: store,
    selection: selection.type === "agent" ? { ...selection, sessionId } : selection,
    chats: [],
    onSelect: (next) => {
      if (next.type === "agent" && next.agentId === selectedAgentId) void store.seeAgent(next.agentId);
      setSelection(next);
    },
    onNewChatMenu: setNewChatAnchor,
    onRenameChat: () => {},
    onArchiveChat: () => {},
    onSearch: () => setJumpOpen(true),
    onConnectApps: () => setConnectOpen(true),
    onSettings: () => setSettingsOpen(true),
    onRetry: () => void store.refresh(),
    userInitials: "MJ",
    pins,
    onPin: (agentId, index) => updatePins((cur) => pin(cur, agentId, index)),
    onUnpin: (agentId) => updatePins((cur) => unpin(cur, agentId)),
    onInfo: (agentId) => { setSelection({ type: "agent", agentId }); host.openDetails?.(agentId); },
    onHistory: (agentId) => host.openHistory?.(agentId),
    onMarkRead: (agentId) => store.seeAgent(agentId),
    onAgentMenu: openAgentMenu,
    status: source.kind === "mock"
      ? { kind: "warn", label: "Mock data (dev)" }
      : store.error ? { kind: "error", label: "Gateway unreachable" } : { kind: "ok", label: "Connected" },
  });

  const detailsAgent = store.agents.find((a) => a.id === detailsAgentId);
  const historyAgent = store.agents.find((a) => a.id === historyAgentId);
  const chatBody = sessionError
    ? <ErrorState title="Couldn't open this chat" error={sessionError} onRetry={() => setSessionAttempt((n) => n + 1)} />
    : <ChatPane host={host} sessionId={sessionId} agents={store.agents} />;
  const phoneAgent = store.agents.find((a) => a.id === (selectedAgentId ?? defaultAgentId));
  const main = phone
    ? (phoneView === "chat"
      ? <PhoneChat agentId={phoneAgent?.id ?? LEAD_ID} agentName={phoneAgent ? label(phoneAgent) : "Jaeger"} avatarUrl={phoneAgent?.avatar_url}
          onBack={() => { setPhoneView("list"); void store.refresh(); }} onInfo={() => host.openDetails?.(phoneAgent?.id ?? LEAD_ID)}>{chatBody}</PhoneChat>
      : <PhoneList state={store} userInitials="MJ" statusOk={!store.error} onOpen={(agentId) => { newChat(agentId); setPhoneView("chat"); }}
          onSearch={() => setJumpOpen(true)} onNew={setNewChatAnchor} onSettings={() => setSettingsOpen(true)} onAgentMenu={openAgentMenu} />)
    : null;
  return (
    <>
      {phone ? main : <AppShell top={slots.top} primary={slots.primary} sections={slots.sections} footer={slots.footer}>
        {selection.type === "tasks"
          ? <TasksBoard source={source} agents={store.agents} />
          : (
            <div className="jg-main-row">
              {sessionError
                ? <ErrorState title="Couldn't open this chat" error={sessionError} onRetry={() => setSessionAttempt((n) => n + 1)} />
                : <ChatPane host={host} sessionId={sessionId} agents={store.agents} />}
              {detailsAgent && (
                <AgentDetails agent={detailsAgent} summary={store.summaries.find((s) => s.id === detailsAgent.id)}
                  onOpenHistory={() => { setDetailsAgentId(null); setHistoryAgentId(detailsAgent.id); }} onClose={() => setDetailsAgentId(null)} />
              )}
              {historyAgent && (
                <HistoryPanel agentId={historyAgent.id} agentName={label(historyAgent)} home={home} openSessionId={historySessionId}
                  onOpenLink={(url) => host.openExternal(url)} onClose={() => { setHistoryAgentId(null); setHistorySessionId(undefined); }} />
              )}
            </div>
          )}
      </AppShell>}
      {menuAgent && agentMenu && (
        <AgentContextMenu agent={menuAgent} at={agentMenu} phone={phone} caps={caps} unread={store.summaries.find((s) => s.id === menuAgent.id)?.unseen === true} pinned={pins.includes(menuAgent.id)} alternative={store.agents.some((a) => a.id !== menuAgent.id && a.ui_actions?.primary && visible(a))}
          preview={menuAgent.last_message?.preview ?? store.summaries.find((x) => x.id === menuAgent.id)?.last_preview ?? ""}
          onAction={onAgentAction} onClose={() => setAgentMenu(null)} />
      )}
      {primaryPicker && <PrimaryPicker agents={store.agents.filter((a) => a.ui_actions?.primary && a.id !== primaryPicker.expectedId && visible(a))} busy={managementBusy}
        onPick={(id) => void changePrimary(id, primaryPicker.expectedId)} onClose={() => { if (!managementBusy) setPrimaryPicker(null); }} />}
      {agentPrompt?.kind === "rename" && <AgentPrompt title={`Rename ${label(agentPrompt.agent)}`} confirm="Save display name" input={{ placeholder: "Display name", value: label(agentPrompt.agent) }} message="Presentation only. Agent ID, role, tools, context and conversations stay the same." onDone={onPromptDone} />}
      {agentPrompt?.kind === "delete" && <AgentPrompt title={`Delete ${label(agentPrompt.agent)}?`} danger confirm="Delete"
        message="It leaves the sidebar. Its home chat and history are kept and can be restored." onDone={onPromptDone} />}
      {agentPrompt?.kind === "section" && <AgentPrompt title="New Section" confirm="Create" input={{ placeholder: "Section name" }}
        message={`${label(agentPrompt.agent)} moves into it.`} onDone={onPromptDone} />}
      {agentPrompt?.kind === "duplicate" && <AgentPrompt title={`Duplicate ${label(agentPrompt.agent)}`} confirm="Duplicate"
        input={{ placeholder: "Name", value: `${label(agentPrompt.agent)} copy` }} onDone={onPromptDone} />}
      {notice && <div className="jg-toast" role="status">{notice}</div>}
      <NewChatMenu anchor={newChatAnchor} agents={store.agents.filter(visible)} onClose={() => setNewChatAnchor(null)}
        onNewChat={newChat} onCreateAgent={createAgent} />
      <ConnectAppsDialog open={connectOpen} onClose={() => setConnectOpen(false)} />
      <SettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} capabilities={settingsCaps} agentsPanel={<AgentManagement agents={store.agents} onPrimary={(a) => void changePrimary(a.id, defaultAgentId)} onProfile={(a) => { setSettingsOpen(false); host.openDetails?.(a.id); }} onHistory={(a) => { setSettingsOpen(false); host.openHistory?.(a.id); }} busy={managementBusy} onImportPins={sharedPins && devicePins.some((id) => !projectedPins.includes(id)) ? () => updatePins((cur) => [...new Set([...cur, ...devicePins])].slice(0, MAX_PINS)) : undefined} onRename={(agent) => setAgentPrompt({ kind: "rename", agent })} onResetName={(agent) => void changePresentation(agent, { display_name: null })} onPin={(agent, pinned) => updatePins((cur) => pinned ? pin(cur, agent.id) : unpin(cur, agent.id))} onArchive={(agent, archived) => void changePresentation(agent, { archived })} />} />
      <JumpTo open={jumpOpen} agents={store.agents.filter(visible)} onClose={() => setJumpOpen(false)}
        summaries={store.summaries} seen={store.seen} currentAgentId={selectedAgentId}
        onAgent={(agentId) => { newChat(agentId); if (phone) setPhoneView("chat"); }}
        actions={[
          { id: "new", label: "New chat", shortcut: "⌘N", run: () => newChat(selectedAgentId ?? defaultAgentId) },
          { id: "history", label: "Chat history", run: () => host.openHistory?.(selectedAgentId ?? defaultAgentId) },
          { id: "tasks", label: "Tasks", run: () => setSelection({ type: "tasks" }) },
          { id: "settings", label: "Settings", shortcut: "⌘,", run: () => setSettingsOpen(true) },
        ]} />
    </>
  );
}
