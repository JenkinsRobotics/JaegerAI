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
import { detectHost } from "./platform/host";
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
  useEffect(() => onNativeEvent((detail) => { if (detail.type === "window.visibility") void store.refresh(); }), [store.refresh]);

  // One continuous conversation per agent: the chat this device last opened
  // for that agent, else its latest chat with messages, else an existing empty
  // one, else a new one. One lookup per agent at a time, so effect re-runs
  // never create a burst of empty chats. Keyed on the agent id only, so roster
  // polling never switches chats.
  const chosen = useRef(new Map<string, string>());
  const resolving = useRef(new Map<string, Promise<string>>());
  const selectedAgentId = selection.type === "agent" ? selection.agentId : undefined;
  useEffect(() => {
    if (!selectedAgentId) return;
    let live = true;
    const agentId = selectedAgentId;
    const known = chosen.current.get(agentId);
    let resolve = known ? Promise.resolve(known) : resolving.current.get(agentId);
    if (!resolve) {
      resolve = source.sessions({ agent_id: agentId }).then((rows) => {
        const thread = rows.find((r) => (r.message_count ?? 0) > 0 || r.last_message_preview) ?? rows[0];
        return thread?.session_id ?? source.createSession({ agent_id: agentId }).then((s) => s.session_id);
      }).finally(() => resolving.current.delete(agentId));
      resolving.current.set(agentId, resolve);
    }
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
