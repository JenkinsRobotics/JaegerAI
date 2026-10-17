import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { JaegerSource } from "./api/source";
import { agentsSidebarSlots, type Selection } from "./agents/AgentsSidebar";
import { useAgentsStore } from "./agents/agentsStore";
import { label } from "./agents/agentsLogic";
import { ExchangePanel } from "./agents/ExchangePanel";
import { ChatPane } from "./chat/ChatPane";
import { NativeHost } from "./chat/nativeHost";
import { WebHost } from "./chat/webHost";
import { ConnectAppsDialog } from "./connect-apps/ConnectAppsDialog";
import { detectHost, voiceFlag } from "./platform/host";
import { onNativeEvent } from "./platform/native";
import { AppShell } from "./shell/AppShell";
import { ErrorState } from "./shell/ErrorState";
import { TasksBoard } from "./tasks/TasksBoard";

const LEAD_ID = "native:jaeger";

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
  const [exchange, setExchange] = useState<string | null>(null);

  // Host wiring: names for markers, exchange panel, voice capability.
  useEffect(() => {
    host.setAgentNames(new Map(store.agents.map((a) => [a.id, label(a)])));
    host.openHandoff = (id: string) => setExchange(id);
  }, [host, store.agents]);
  useEffect(() => { if (host instanceof NativeHost) void host.probeCapabilities(voiceFlag()); }, [host]);
  useEffect(() => onNativeEvent((detail) => { if (detail.type === "window.visibility") void store.refresh(); }), [store.refresh]);

  // Resolve the selected agent to its chat session: the chat this device last
  // opened for that agent, else the summary row, else ?agent_id=, else create.
  // Keyed on the agent id only, so roster polling never switches chats.
  const summariesRef = useRef(store.summaries);
  summariesRef.current = store.summaries;
  const chosen = useRef(new Map<string, string>());
  const selectedAgentId = selection.type === "agent" ? selection.agentId : undefined;
  useEffect(() => {
    if (!selectedAgentId) return;
    let live = true;
    const agentId = selectedAgentId;
    const known = chosen.current.get(agentId) ?? summariesRef.current.find((s) => s.id === agentId)?.session_id ?? undefined;
    const resolve = known
      ? Promise.resolve(known)
      : source.sessions({ agent_id: agentId }).then((rows) => rows[0]?.session_id ?? source.createSession({ agent_id: agentId }).then((s) => s.session_id));
    setSessionError(undefined);
    resolve.then(
      (id) => { if (live) { chosen.current.set(agentId, id); setSessionId(id); } },
      (error: unknown) => { if (live) { setSessionId(undefined); setSessionError(String((error as Error)?.message ?? error)); } },
    );
    store.seeAgent(agentId);
    return () => { live = false; };
  }, [selectedAgentId, source, store.seeAgent, sessionAttempt]);

  const newChat = useCallback(() => {
    const agentId = selectedAgentId ?? LEAD_ID;
    void source.createSession({ agent_id: agentId }).then(
      (s) => { chosen.current.set(agentId, s.session_id); setSelection({ type: "agent", agentId }); setSessionId(s.session_id); },
      (error: unknown) => setSessionError(String((error as Error)?.message ?? error)),
    );
  }, [selectedAgentId, source]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "n") { event.preventDefault(); newChat(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [newChat]);

  const slots = agentsSidebarSlots({
    state: store,
    selection,
    onSelect: setSelection,
    onNewChat: newChat,
    onSearch: () => { /* search lands with /v1/sessions?q= */ },
    onConnectApps: () => setConnectOpen(true),
    onRetry: () => void store.refresh(),
    userInitials: "MJ",
    status: source.kind === "mock"
      ? { kind: "warn", label: "Mock data (dev)" }
      : store.error ? { kind: "error", label: "Gateway unreachable" } : { kind: "ok", label: "Connected" },
  });

  return (
    <>
      <AppShell
        top={slots.top}
        primary={slots.primary}
        sections={slots.sections}
        footer={slots.footer}
      >
        {selection.type === "tasks"
          ? <TasksBoard source={source} agents={store.agents} />
          : sessionError
            ? <ErrorState title="Couldn't open this chat" error={sessionError} onRetry={() => setSessionAttempt((n) => n + 1)} />
            : <ChatPane host={host} sessionId={sessionId} />}
      </AppShell>
      <ConnectAppsDialog open={connectOpen} onClose={() => setConnectOpen(false)} />
      <ExchangePanel source={source} handoffId={exchange} onClose={() => setExchange(null)} />
    </>
  );
}
