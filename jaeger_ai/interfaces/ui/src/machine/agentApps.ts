/** Machine › Agent Apps data helpers (Gateway /v1/apps via the WebUI proxy). */
export interface AppConfigInfo { path: string; format: string; editable_keys: string[]; rewritten_by_app: boolean; vendor_cli: string | null; exists: boolean }
export interface AgentApp { id: string; name: string; kind: "macapp" | "cli" | "launchd"; installed: boolean; running: boolean; actions: string[]; surfaces: string[]; notes: string; configs: AppConfigInfo[] }
export interface DiffRow { path: string; change: "added" | "removed" | "changed"; before?: unknown; after?: unknown }
export interface Proposal { id: string; app: string; app_name: string; action: string; status: "pending" | "approved" | "rejected" | "running" | "done" | "failed" | "rolled_back"; proposed_by: string; summary: string; created_at: string; diff?: DiffRow[]; reason?: string; prompt_preview?: string; error?: string; result?: { backup?: string; rollback?: string; output?: string; via?: string } }

export function groupApps(apps: AgentApp[]): { title: string; apps: AgentApp[] }[] {
  const installed = apps.filter((a) => a.installed);
  const svc = installed.filter((a) => a.id.startsWith("jaeger-"));
  const agents = installed.filter((a) => !a.id.startsWith("jaeger-")).sort((a, b) => Number(b.running) - Number(a.running) || a.name.localeCompare(b.name));
  return [{ title: "Agent apps", apps: agents }, { title: "Jaeger services", apps: svc }].filter((g) => g.apps.length);
}

export const actionLabel = (a: string) => (a.startsWith("invoke:") ? `Run ${a.slice(7)}` : a[0].toUpperCase() + a.slice(1));
export const isLifecycle = (a: string) => a === "start" || a === "stop" || a === "restart";
export const statusTone = (s: Proposal["status"]): "ok" | "warn" | "bad" | undefined =>
  s === "done" ? "ok" : s === "failed" || s === "rejected" ? "bad" : s === "pending" || s === "running" || s === "approved" ? "warn" : undefined;
