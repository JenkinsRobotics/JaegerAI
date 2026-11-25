/* Agents › Activity (/agents/activity): the orchestration panes on the live
 * gateway. G1 history comes from /v1/activity when it answers; the other gaps
 * keep their derived stand-ins until they land. */
import { useMemo } from "react";
import { GatewayClient } from "../api/gateway";
import type { JaegerSource } from "../api/source";
import { derivedGaps, gatewayActivity, liveAdapter, type GapProvider } from "./adapter";
import { OrchestrationPanes } from "./OrchestrationPanes";

export function AgentsActivityPage({ source, onNavigate }: { source: JaegerSource; onNavigate: (to: string) => void }) {
  const adapter = useMemo(() => {
    // G1 only against the real gateway client; the dev mock source keeps the stand-ins.
    if (!(source instanceof GatewayClient)) return liveAdapter(source);
    const base = (source as unknown as { base?: unknown }).base;
    const gaps: GapProvider = { ...derivedGaps, kind: "gateway", activity: gatewayActivity(typeof base === "string" ? base : "") };
    return liveAdapter(source, gaps);
  }, [source]);
  return (
    <OrchestrationPanes embedded adapter={adapter} onNavigate={onNavigate} initialCaller={new URLSearchParams(location.search).get("agent_id") ?? undefined} />
  );
}
