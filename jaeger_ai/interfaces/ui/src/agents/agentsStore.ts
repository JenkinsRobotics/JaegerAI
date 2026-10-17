import { useCallback, useEffect, useState } from "react";
import type { JaegerSource } from "../api/source";
import type { Agent, AgentSummary } from "../api/types";
import { FALLBACK_ROSTER } from "./agentsLogic";
import { loadSeen, markSeen } from "./unread";

export interface AgentsState {
  agents: Agent[];
  summaries: AgentSummary[];
  seen: Record<string, number>;
  loading: boolean;
  error?: string;
}

const POLL_MS = 15_000;

export function useAgentsStore(source: JaegerSource) {
  const [state, setState] = useState<AgentsState>({ agents: [], summaries: [], seen: loadSeen(), loading: true });

  const refresh = useCallback(async () => {
    try {
      const [agents, summaries] = await Promise.all([source.agents(), source.agentsSummary().catch(() => [] as AgentSummary[])]);
      setState((s) => ({ ...s, agents: agents.length ? agents : FALLBACK_ROSTER, summaries, loading: false, error: undefined }));
    } catch (error) {
      setState((s) => ({ ...s, agents: s.agents.length ? s.agents : FALLBACK_ROSTER, loading: false, error: String((error as Error)?.message ?? error) }));
    }
  }, [source]);

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), POLL_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  const seeAgent = useCallback((agentId: string) => setState((s) => ({ ...s, seen: markSeen(agentId) })), []);
  return { ...state, refresh, seeAgent };
}
