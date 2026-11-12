/* The eight framework responsibilities as live status, computed only from real
 * Gateway events up to the playhead (no seeded or demo values). Each returns
 * what was last observed for the selected turn; "—" means not observed yet. */
import type { GatewayEvent } from "../api/types";
import type { StreamHealth } from "./useProcessEvents";

export type RespId = "models" | "tools" | "loop" | "state" | "permissions" | "orchestration" | "reliability" | "events";
export type RespTone = "idle" | "active" | "ok" | "warn" | "fault";
export interface Resp { id: RespId; label: string; tone: RespTone; value: string; detail: string; count: number; lastEventId?: number }

export const RESP_ORDER: { id: RespId; label: string }[] = [
  { id: "models", label: "Models" }, { id: "tools", label: "Tools" }, { id: "loop", label: "Execution loop" },
  { id: "state", label: "State & memory" }, { id: "permissions", label: "Permissions" },
  { id: "orchestration", label: "Orchestration" }, { id: "reliability", label: "Reliability" }, { id: "events", label: "Events" },
];

/** Which responsibility an event reports on (null = not one of the eight). */
export function respOf(event: string): RespId | null {
  if (event.startsWith("model.")) return "models";
  if (event.startsWith("tool.") || event.startsWith("subagent.tool.")) return "tools";
  if (event.startsWith("loop.") || event === "turn.start" || event === "turn.finish" || event === "turn.checkpoint") return "loop";
  if (event.startsWith("state.") || event === "turn.plan" || event.startsWith("task.")) return "state";
  if (event === "policy.decision" || event.startsWith("approval.") || event === "hook.decision" || event.startsWith("clarify.")) return "permissions";
  if (event === "route.selected" || event === "subagent.started" || event === "subagent.finished" || event.startsWith("agent.handoff")) return "orchestration";
  if (event.startsWith("reliability.") || ["turn.failed", "turn.cancelled", "turn.unknown", "turn.reconciled"].includes(event)) return "reliability";
  return null;
}

const s = (v: unknown) => (typeof v === "string" ? v : v == null ? "" : String(v));
const fmt = (ms: unknown) => (typeof ms === "number" ? (ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`) : "");

export function responsibilities(events: readonly GatewayEvent[], upTo: number, runId: string | null, health: StreamHealth): Resp[] {
  const rid = runId?.replace(/^run:/, "") ?? null;
  const rows = new Map<RespId, Resp>(RESP_ORDER.map(({ id, label }) => [id, { id, label, tone: "idle", value: "—", detail: "not observed in this turn", count: 0 }]));
  const set = (id: RespId, e: GatewayEvent, tone: RespTone, value: string, detail = "") => {
    const r = rows.get(id)!; r.count++; r.tone = tone; r.value = value; r.detail = detail || r.detail; r.lastEventId = e.event_id;
  };
  let toolsRunning = 0, toolsDone = 0, toolsFailed = 0, retries = 0, fallbacks = 0, subRunning = 0, subDone = 0;
  let memReads = 0, memWrites = 0;
  for (let i = 0; i <= upTo && i < events.length; i++) {
    const e = events[i];
    const p = (e.payload ?? {}) as Record<string, unknown>;
    const eRun = s(p.request_id ?? e.trace?.run_id);
    if (rid && eRun && eRun !== rid) continue;
    if (rid && !eRun) continue;
    switch (e.event) {
      case "model.started": set("models", e, "active", `${s(p.model) || "model"} · step ${s(p.index)}`, [s(p.provider), s(p.location), s(p.route_reason)].filter(Boolean).join(" · ") || "calling"); break;
      case "model.finished": {
        const u = (p.usage ?? {}) as Record<string, number>;
        const usage = p.usage_reported === false ? "usage not reported by lane" : `${u.prompt_tokens ?? 0} in / ${u.completion_tokens ?? 0} out tokens`;
        set("models", e, p.ok === false ? "fault" : "ok", `${s(p.actual_model ?? p.model) || "model"} · ${fmt(p.duration_ms)}`,
          p.ok === false ? `failed: ${s(p.error) || "error"} (${s(p.provider)})` : `${s(p.provider)} · ${usage}`);
        break;
      }
      case "tool.started": case "subagent.tool.started": toolsRunning++; set("tools", e, "active", `${toolsRunning} running · ${toolsDone} done`, `${s(p.tool)} started`); break;
      case "tool.progress": set("tools", e, "active", `${toolsRunning} running · ${toolsDone} done`, `${s(p.tool)}: ${s(p.message)}`); break;
      case "tool.completed": case "tool.done": case "subagent.tool.finished": case "tool.failed": case "tool.error": {
        toolsRunning = Math.max(0, toolsRunning - 1);
        const failed = e.event.startsWith("tool.f") || e.event === "tool.error" || p.ok === false;
        if (failed) toolsFailed++; else toolsDone++;
        set("tools", e, toolsFailed ? "warn" : toolsRunning ? "active" : "ok", `${toolsDone} done${toolsFailed ? ` · ${toolsFailed} failed` : ""}${toolsRunning ? ` · ${toolsRunning} running` : ""}`,
          `${s(p.tool)} ${failed ? `failed${p.outcome ? ` (${s(p.outcome)})` : ""}` : `ok${p.elapsed_s != null ? ` in ${s(p.elapsed_s)} s` : ""}`}`);
        break;
      }
      case "turn.start": set("loop", e, "active", "turn started", "waiting for the first model step"); break;
      case "turn.checkpoint": set("loop", e, "active", `continuing · pass ${Number(p.step ?? 0) + 2}`, s(p.reason) || "owner continuation"); break;
      case "loop.iteration":
        if (p.subagent_id) { set("orchestration", e, "active", `sub-agent step ${s(p.index)} · ${s(p.decision)}`, s(p.reason)); break; }
        set("loop", e, "active", `step ${s(p.index)}/${s(p.max)} · ${s(p.decision)}`, s(p.reason)); break;
      case "loop.continuation": set("loop", e, "active", `continuing · pass ${s(p.pass)}`, s(p.reason)); break;
      case "loop.stop": if (p.subagent_id) break; set("loop", e, p.ok === false ? "warn" : "ok", `stopped · ${s(p.reason)}`, p.iterations != null ? `${s(p.iterations)} iteration(s)` : ""); break;
      case "state.memory": {
        if (p.op === "read" || p.op === "recall") memReads++; else memWrites++;
        set("state", e, p.ok === false ? "warn" : "ok", `memory ${memReads} read · ${memWrites} write`, `${s(p.fn)} ${p.ok === false ? "failed" : "ok"}${p.hit != null ? (p.hit ? " (hit)" : " (miss)") : ""}${p.count != null ? ` · ${s(p.count)} items` : ""}`);
        break;
      }
      case "state.saved": set("state", e, "ok", "session saved", `${s(p.what)} · ${s(p.messages)} messages`); break;
      case "turn.plan": set("state", e, "ok", "plan updated", "task progress recorded"); break;
      case "policy.decision": set("permissions", e, p.decision === "deny" ? "fault" : p.decision === "needs_approval" ? "warn" : "ok", `${s(p.decision)} · ${s(p.tool)}`, `${s(p.policy)}${p.reason ? `: ${s(p.reason)}` : ""}`); break;
      case "approval.request": set("permissions", e, "warn", "waiting for approval", s(p.prompt ?? p.kind)); break;
      case "approval.resolved": set("permissions", e, s(p.decision ?? p.status).includes("deny") ? "fault" : "ok", `approval ${s(p.decision ?? p.status)}`, s(p.kind)); break;
      case "hook.decision": set("permissions", e, p.action === "deny" ? "fault" : "ok", `hook ${s(p.action)} · ${s(p.tool)}`, `${s(p.hook)}${p.reason ? `: ${s(p.reason)}` : ""}`); break;
      case "route.selected": set("orchestration", e, "ok", `route · ${s(p.model) || "default model"}`, `${s(p.reason)}${p.lane ? ` · lane ${s(p.lane)}` : ""} · tools: ${s(p.tools)}`); break;
      case "subagent.started": subRunning++; set("orchestration", e, "active", `${subRunning} sub-agent(s) running`, `${s(p.name)}: ${s(p.task)}`); break;
      case "subagent.finished": subRunning = Math.max(0, subRunning - 1); subDone++; set("orchestration", e, p.status === "failed" ? "warn" : subRunning ? "active" : "ok", `${subDone} sub-agent(s) finished`, `${s(p.name)} ${s(p.status)} in ${s(p.elapsed_s)} s`); break;
      case "reliability.retry": retries++; set("reliability", e, "warn", `${retries} retr${retries === 1 ? "y" : "ies"}${fallbacks ? ` · ${fallbacks} fallback` : ""}`, `${s(p.adapter)} ${s(p.kind)} · attempt ${s(p.attempt)}/${s(p.of)}`); break;
      case "reliability.fallback": fallbacks++; set("reliability", e, "warn", `${fallbacks} fallback${retries ? ` · ${retries} retries` : ""}`, `${s(p.from)} → ${s(p.to)}: ${s(p.reason)}`); break;
      case "reliability.exhausted": set("reliability", e, "fault", "all adapters failed", s(p.reason)); break;
      case "reliability.timeout": set("reliability", e, "warn", "model call timed out", `${s(p.adapter)} after ${s(p.after_s)} s`); break;
      case "turn.failed": set("reliability", e, "fault", "turn failed", s(p.error ?? p.message)); break;
      case "turn.cancelled": set("reliability", e, "warn", "turn cancelled", s(p.reason)); break;
      case "turn.unknown": set("reliability", e, "fault", "outcome unknown", "interrupted before a terminal receipt"); break;
      case "turn.reconciled": set("reliability", e, "ok", "recovered", "outcome reconciled after restart"); break;
      case "turn.finish": {
        const r = rows.get("reliability")!;
        if (r.tone === "idle") { r.tone = "ok"; r.value = "no faults"; r.detail = "no retries, fallbacks or failures in this turn"; }
        break;
      }
      default: break;
    }
  }
  const ev = rows.get("events")!;
  ev.tone = health.link === "live" ? (health.gaps ? "warn" : "ok") : health.link === "retrying" ? "warn" : health.link === "unsupported" ? "fault" : "active";
  ev.value = `${health.link}${health.reconnects ? ` · ${health.reconnects} reconnect${health.reconnects === 1 ? "" : "s"}` : ""}`;
  ev.detail = `replayed ${health.replayed} from history · ${health.gaps} seq gap${health.gaps === 1 ? "" : "s"}${health.expired ? ` · cursor expired ${health.expired}×` : ""}`;
  ev.count = events.length;
  return RESP_ORDER.map(({ id }) => rows.get(id)!);
}
