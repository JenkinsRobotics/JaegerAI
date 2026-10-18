import { useCallback, useEffect, useState } from "react";
import type { JaegerSource } from "../api/source";
import type { Agent, AgentSummary } from "../api/types";
import { loadSeen, markSeen } from "./unread";

export interface AgentsState {
  agents: Agent[];
  summaries: AgentSummary[];
  seen: Record<string, number>;
  loading: boolean;
  /** Set when the last refresh failed. Agents keep the last REAL roster (or
   * stay empty); nothing is ever invented. */
  error?: string;
}

const POLL_MS = 15_000;

export async function loadRoster(source: Pick<JaegerSource, "agents" | "agentsSummary">) {
  const [agents, summaries] = await Promise.all([source.agents(), source.agentsSummary()]);
  return { agents, summaries };
}

export function useAgentsStore(source: JaegerSource) {
  const [state, setState] = useState<AgentsState>({ agents: [], summaries: [], seen: loadSeen(), loading: true });

  const refresh = useCallback(async () => {
    setState((s) => ({ ...s, loading: true }));
    try {
      const { agents, summaries } = await loadRoster(source);
      setState((s) => ({ ...s, agents, summaries, loading: false, error: undefined }));
    } catch (error) {
      setState((s) => ({ ...s, loading: false, error: String((error as Error)?.message ?? error) }));
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
