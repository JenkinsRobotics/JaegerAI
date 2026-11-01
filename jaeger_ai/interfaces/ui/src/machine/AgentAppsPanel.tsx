/** Machine › Agent Apps: status of Matthew's agent apps and Jaeger services, with proposals that
 * only run after he approves them here. Configs are shown redacted; edits create backups. */
import { useCallback, useEffect, useState } from "react";
import { Badge } from "../unified/ui";
import { WidgetCard } from "../widgets/primitives/WidgetCard";
import { getJson, sendJson } from "../unified/webui";
import { actionLabel, groupApps, isLifecycle, statusTone, type AgentApp, type Proposal } from "./agentApps";
import "./machine.css";

const show = (v: unknown) => (typeof v === "string" ? v : JSON.stringify(v));

export function AgentAppsPanel() {
  const [apps, setApps] = useState<AgentApp[] | null>(null);
  const [props, setProps] = useState<Proposal[]>([]);
  const [err, setErr] = useState<string>();
  const [cfg, setCfg] = useState<{ app: string; text: string } | null>(null);
  const [busy, setBusy] = useState<string>();
  const load = useCallback(async () => {
    try {
      const [a, p] = await Promise.all([getJson<{ apps: AgentApp[] }>("/v1/apps"), getJson<{ proposals: Proposal[] }>("/v1/apps/proposals")]);
      setApps(a.apps); setProps(p.proposals); setErr(undefined);
    } catch (e) { setErr((e as Error).message); }
  }, []);
  useEffect(() => { void load(); const t = setInterval(() => { if (!document.hidden) void load(); }, 5000); return () => clearInterval(t); }, [load]);
  const act = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key);
    try { await fn(); await load(); } catch (e) { setErr((e as Error).message); } finally { setBusy(undefined); }
  };
  const propose = (app: string, action: string) => act(`${app}:${action}`, () => sendJson("POST", `/v1/apps/${app}/proposals`, { action }));
  const decide = (id: string, approve: boolean) => act(id, () => sendJson("POST", `/v1/apps/proposals/${id}/decision`, { approve }));
  const rollback = (id: string) => act(id, () => sendJson("POST", `/v1/apps/proposals/${id}/rollback`, {}));
  const viewConfig = (app: string) => act(`${app}:cfg`, async () => {
    const r = await getJson<{ path: string; config: unknown; editable_keys: string[] }>(`/v1/apps/${app}/config`);
    setCfg({ app, text: `# ${r.path}\n# editable: ${r.editable_keys.join(", ") || "none (read-only)"}\n${JSON.stringify(r.config, null, 2)}` });
  });
  const pending = props.filter((p) => p.status === "pending");
  const recent = props.filter((p) => p.status !== "pending").slice(0, 8);
  return (
    <div className="jg-mc-apps">
      {err && <WidgetCard title="Agent apps error" state="error" message={err} />}
      <WidgetCard title="Waiting for your approval" status={<Badge tone={pending.length ? "warn" : "ok"}>{pending.length}</Badge>}
        state={pending.length === 0 ? "empty" : "ready"} message="Nothing waiting (0). Agents can only propose app changes; they run after you approve them here.">
        {pending.map((p) => (
          <article key={p.id} className="jg-mc-proposal">
            <div className="jg-mc-inline-head"><strong>{p.summary}</strong><span className="jg-mc-muted">from {p.proposed_by}</span></div>
            {p.reason && <p className="jg-mc-muted">{p.reason}</p>}
            {p.prompt_preview && <pre className="jg-mc-pre">{p.prompt_preview}</pre>}
            {p.diff && <ul className="jg-mc-diff">{p.diff.map((d) => <li key={d.path} data-change={d.change}><code>{d.path}</code> {d.change}{d.after !== undefined && <> → <code>{show(d.after)}</code></>}</li>)}</ul>}
            <div className="jg-mc-row">
              <button className="jg-u-btn" data-variant="primary" disabled={busy === p.id} onClick={() => void decide(p.id, true)}>Approve</button>
              <button className="jg-u-btn" disabled={busy === p.id} onClick={() => void decide(p.id, false)}>Reject</button>
            </div>
          </article>
        ))}
      </WidgetCard>
      {apps === null ? <WidgetCard title="Agent apps" state="loading" message="Loading agent apps…" /> : groupApps(apps).map((g) => (
        <WidgetCard key={g.title} title={g.title}>
          <div className="jg-mc-appgrid">
            {g.apps.map((a) => (
              <article key={a.id} className="jg-mc-app">
                <div className="jg-mc-inline-head">
                  <strong>{a.name}</strong>
                  {a.kind !== "cli" ? <Badge tone={a.running ? "ok" : undefined}>{a.running ? "Running" : "Stopped"}</Badge> : <Badge>CLI</Badge>}
                </div>
                {a.surfaces.length > 0 && <span className="jg-mc-muted">{a.surfaces.join(" · ")}</span>}
                {a.notes && <span className="jg-mc-muted">{a.notes}</span>}
                <div className="jg-mc-row">
                  {a.actions.filter(isLifecycle).filter((x) => !(x === "start" && a.running) && !(x === "stop" && !a.running)).map((x) => (
                    <button key={x} className="jg-u-btn" disabled={busy === `${a.id}:${x}`} onClick={() => void propose(a.id, x)} title="Creates a proposal you approve above">{actionLabel(x)}</button>
                  ))}
                  {a.configs.length > 0 && <button className="jg-u-btn" disabled={busy === `${a.id}:cfg`} onClick={() => void viewConfig(a.id)}>Config</button>}
                </div>
              </article>
            ))}
          </div>
        </WidgetCard>
      ))}
      {cfg && (
        <WidgetCard title={`${cfg.app} config (secrets hidden)`} actions={<button className="jg-u-btn" onClick={() => setCfg(null)}>Close</button>}>
          <pre className="jg-mc-pre">{cfg.text}</pre>
        </WidgetCard>
      )}
      {recent.length > 0 && (
        <WidgetCard title="Recent">
          {recent.map((p) => (
            <div key={p.id} className="jg-mc-inline-head jg-mc-recent">
              <span>{p.summary}</span>
              <span className="jg-mc-row"><Badge tone={statusTone(p.status)}>{p.status.replace("_", " ")}</Badge>
                {p.action === "config" && p.status === "done" && <button className="jg-u-btn" disabled={busy === p.id} onClick={() => void rollback(p.id)}>Roll back</button>}</span>
              {p.error && <span className="jg-mc-muted">{p.error}</span>}
            </div>
          ))}
        </WidgetCard>
      )}
    </div>
  );
}
