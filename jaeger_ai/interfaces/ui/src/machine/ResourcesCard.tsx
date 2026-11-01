/** Machine › Overview: the resource manager's live view (what background research may use right now, and why it is throttled). */
import { useEffect, useState } from "react";
import { Badge } from "../unified/ui";
import { getJson } from "../unified/webui";
import { pressure, type ResourceStatus } from "./machineData";
import { WidgetCard } from "../widgets/primitives/WidgetCard";
import "./machine.css";

export function ResourcesCard() {
  const [r, setR] = useState<ResourceStatus | null>(null); const [err, setErr] = useState<string>();
  useEffect(() => { let live = true; const read = () => getJson<ResourceStatus>("/v1/resources").then((x) => live && (setR(x), setErr(undefined)), (e: Error) => live && setErr(e.message));
    void read(); const t = setInterval(() => { if (!document.hidden) void read(); }, 10000); return () => { live = false; clearInterval(t); }; }, []);
  if (err) return <WidgetCard title="Resources" state="error" message={`Resource manager unavailable: ${err}`} />;
  if (!r) return <WidgetCard title="Resources" state="loading" message="Loading resources…" />;
  const s = r.snapshot, c = r.config, hits = pressure(s, c);
  const metrics: [string, string][] = [
    ["Memory free", `${s.mem_free_gb.toFixed(1)} / ${s.mem_total_gb.toFixed(0)} GB`], ["CPU load", `${Math.round(s.cpu_load * 100)}%`],
    ["GPU", s.gpu_util == null ? "–" : `${s.gpu_util}%`], ["Disk free", `${s.disk_free_gb.toFixed(0)} GB`],
    ["Thermal", s.thermal], ["Research cache", `${s.research_gb.toFixed(2)} / ${c.research_disk_budget_gb} GB`],
    ["Loaded models", s.ollama_loaded.length ? s.ollama_loaded.join(", ") : "none"], ["Concurrency", `${c.concurrency.heavy} heavy · ${c.concurrency.light} light`],
  ];
  return (
    <WidgetCard title="Resources" status={<Badge tone={hits.length ? "warn" : "ok"}>{hits.length ? "Throttling background work" : "Background work allowed"}</Badge>}>
      <div className="jg-mc-metrics">{metrics.map(([k, v]) => <div key={k} role="group" aria-label={`${k} ${v}`} className="jg-mc-metric"><span>{k}</span><strong>{v}</strong></div>)}</div>
      {hits.length > 0 && <ul className="jg-mc-why">{hits.map((h) => <li key={h}>{h}</li>)}</ul>}
    </WidgetCard>
  );
}
