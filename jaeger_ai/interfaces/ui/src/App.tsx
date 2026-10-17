import { useCallback, useEffect, useMemo, useState } from "react";
import { createSource } from "./api";
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
import { Tray } from "./shell/Tray";
import { TasksBoard } from "./tasks/TasksBoard";

const LEAD_ID = "native:jaeger";

export function App({ source: injected }: { source?: JaegerSource }) {
  const [source] = useState<JaegerSource>(() => injected ?? createSource());
  const hostKind = detectHost();
  const host = useMemo(() => (hostKind === "macos" ? new NativeHost(source) : new WebHost(source)), [source, hostKind]);
  const store = useAgentsStore(source);
  const [selection, setSelection] = useState<Selection>({ type: "agent", agentId: LEAD_ID });
  const [sessionId, setSessionId] = useState<string>();
  const [connectOpen, setConnectOpen] = useState(false);
  const [exchange, setExchange] = useState<string | null>(null);

  // Host wiring: names for markers, exchange panel, voice capability.
  useEffect(() => {
    host.setAgentNames(new Map(store.agents.map((a) => [a.id, label(a)])));
    host.openHandoff = (id: string) => setExchange(id);
  }, [host, store.agents]);
  useEffect(() => { if (host instanceof NativeHost) void host.probeCapabilities(voiceFlag()); }, [host]);
  useEffect(() => onNativeEvent((detail) => { if (detail.type === "window.visibility") void store.refresh(); }), [store.refresh]);

  // Resolve the selected agent to its chat session (summary row, then ?agent_id=, then create).
  useEffect(() => {
    if (selection.type !== "agent") return;
    let live = true;
    const agentId = selection.agentId;
    const known = store.summaries.find((s) => s.id === agentId)?.session_id;
    const resolve = known
      ? Promise.resolve(known)
      : source.sessions({ agent_id: agentId }).then((rows) => rows[0]?.session_id ?? source.createSession({ agent_id: agentId }).then((s) => s.session_id));
    resolve.then((id) => live && setSessionId(id), () => live && setSessionId(undefined));
    store.seeAgent(agentId);
    return () => { live = false; };
  }, [selection, source, store.summaries, store.seeAgent]);

  const newChat = useCallback(() => {
    const agentId = selection.type === "agent" ? selection.agentId : LEAD_ID;
    void source.createSession({ agent_id: agentId }).then((s) => { setSelection({ type: "agent", agentId }); setSessionId(s.session_id); });
  }, [selection, source]);

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
    userInitials: "MJ",
  });

  return (
    <>
      <AppShell
        top={slots.top}
        primary={slots.primary}
        sections={slots.sections}
        footer={slots.footer}
        tray={<Tray status={source.kind === "mock" ? "warn" : store.error ? "error" : "ok"} label={source.kind === "mock" ? "Mock data" : store.error ? "Gateway unreachable" : "Connected"} />}
      >
        {selection.type === "tasks"
          ? <TasksBoard source={source} agents={store.agents} />
          : <ChatPane host={host} sessionId={sessionId} />}
      </AppShell>
      <ConnectAppsDialog open={connectOpen} onClose={() => setConnectOpen(false)} />
      <ExchangePanel source={source} handoffId={exchange} onClose={() => setExchange(null)} />
    </>
  );
}
