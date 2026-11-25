/**
 * Shared Gateway SDK data layer (Phase 3 UI Consolidation).
 *
 * Single owner of agents, durable sessions, organization groups/pins, and
 * connection status across the unified shell — eliminating overlapping 5s
 * pollers across nested shells.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type { Organization, OrganizationAction } from "../api/organization";
import type { JaegerSource } from "../api/source";
import type { Agent, SessionRow } from "../api/types";
import { httpGetJson } from "../chat/homeSession";

const JAEGER_HOME_AGENT = "native:jaeger";
const SYNC_INTERVAL_MS = 15_000;

export function sessionActivity(row: SessionRow): number {
  return row.last_activity_at ?? row.updated_at ?? row.created_at ?? 0;
}

export function isBackgroundSession(row: SessionRow): boolean {
  const title = (row.title || "").trim();
  const lowered = title.toLowerCase();
  if (!title) return false;
  if (lowered.includes("gateway_turn")) return true;
  if (title.startsWith("[skill-review") || lowered.startsWith("skill-review")) return true;
  if (lowered.includes("switch check")) return true;
  return false;
}

export interface GatewayStoreState {
  agents: Agent[];
  sessions: SessionRow[];
  organization: Organization | null;
  pinnedIds: Set<string>;
  executionHost: string;
  shareOrigin: string;
  ready: boolean;
  error: string;
  refresh: () => Promise<void>;
  organize: (actions: OrganizationAction[]) => Promise<void>;
  markSessionUnavailable: (sessionId: string) => void;
  setSessions: React.Dispatch<React.SetStateAction<SessionRow[]>>;
}

export function useGatewayStore(source: JaegerSource): GatewayStoreState {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [organization, setOrganization] = useState<Organization | null>(null);
  const [pinnedIds, setPinnedIds] = useState<Set<string>>(() => new Set());
  const [executionHost, setExecutionHost] = useState("");
  const [shareOrigin, setShareOrigin] = useState(() =>
    typeof location !== "undefined" ? location.origin : "",
  );
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const unavailable = useRef(new Set<string>());
  const inFlight = useRef(false);

  const markSessionUnavailable = useCallback((sessionId: string) => {
    unavailable.current.add(sessionId);
    setSessions((rows) => rows.filter((r) => r.session_id !== sessionId));
  }, []);

  const refresh = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      if (source.kind === "live") {
        try {
          await httpGetJson()(`/v1/agents/${encodeURIComponent(JAEGER_HOME_AGENT)}/home`);
        } catch {
          // Home is created on first successful visit.
        }
      }
      const [agentRows, sessionRows, org, conn] = await Promise.all([
        source.agents().catch(() => null),
        source.sessions({ agent_id: JAEGER_HOME_AGENT }).catch(() => null),
        source.organization ? source.organization.get().catch(() => null) : Promise.resolve(null),
        source.connectionInfo ? source.connectionInfo().catch(() => null) : Promise.resolve(null),
      ]);
      if (agentRows) setAgents(agentRows);
      if (org) {
        setOrganization(org);
        setPinnedIds(new Set(org.sessions.filter((r) => r.pinned).map((r) => r.session_id)));
      }
      if (sessionRows) {
        setSessions(
          sessionRows
            .filter(
              (row) =>
                !row.archived &&
                !isBackgroundSession(row) &&
                !unavailable.current.has(row.session_id),
            )
            .sort((a, b) => sessionActivity(b) - sessionActivity(a)),
        );
      }
      if (conn) {
        setExecutionHost(conn.host || "");
        if (
          typeof location !== "undefined" &&
          ["127.0.0.1", "localhost", "[::1]"].includes(location.hostname) &&
          conn.webui_origin
        ) {
          try {
            const u = new URL(conn.webui_origin);
            if (u.protocol === "https:" && !u.username && !u.password) {
              setShareOrigin(u.origin);
            }
          } catch {
            // retain current origin
          }
        }
      }
      setReady(true);
      setError("");
    } catch (exc) {
      setError(String((exc as Error)?.message ?? exc));
    } finally {
      inFlight.current = false;
    }
  }, [source]);

  const organize = useCallback(
    async (actions: OrganizationAction[]) => {
      if (!source.organization) return;
      const state = await source.organization.get();
      await source.organization.command({
        action: "apply",
        revision: state.revision,
        operation_id: crypto.randomUUID(),
        actions,
      });
      await refresh();
    },
    [source, refresh],
  );

  useEffect(() => {
    void refresh();
    const onFocus = () => {
      if (!document.hidden) void refresh();
    };
    const onReadState = () => {
      if (!document.hidden) void refresh();
    };
    const timer = window.setInterval(() => {
      if (!document.hidden) void refresh();
    }, SYNC_INTERVAL_MS);
    window.addEventListener("focus", onFocus);
    window.addEventListener("jg:read-state-changed", onReadState);
    document.addEventListener("visibilitychange", onFocus);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", onFocus);
      window.removeEventListener("jg:read-state-changed", onReadState);
      document.removeEventListener("visibilitychange", onFocus);
    };
  }, [refresh]);

  return {
    agents,
    sessions,
    organization,
    pinnedIds,
    executionHost,
    shareOrigin,
    ready,
    error,
    refresh,
    organize,
    markSessionUnavailable,
    setSessions,
  };
}
