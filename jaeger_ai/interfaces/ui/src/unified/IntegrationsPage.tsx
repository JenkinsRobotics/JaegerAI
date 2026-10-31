/** MCP & Integrations (unified UI): MCP servers (state, tools, reconnect/disconnect), every tool
 * the gateway exposes, and Connect-apps connectors with their status. Gateway APIs only. */
import { useCallback, useEffect, useMemo, useState } from "react";
import type { ConnectAppsListing, JaegerSource, ToolInventory } from "../api/source";
import { Badge, Empty, Segmented, Sheet, SkeletonRows, useToast } from "./ui";
import { PageHeader } from "../components/PageHeader";

/** Status pill (TAB-01 §3): Running / Needs sign-in / Error, plus the raw state for anything else. */
export function pill(s: string): { tone: "ok" | "warn" | "bad"; text: string } {
  if (/auth|sign.?in|oauth|login|consent/i.test(s)) return { tone: "warn", text: "Needs sign-in" };
  if (/error|fail/i.test(s)) return { tone: "bad", text: "Error" };
  if (/connect(ed)?$|ready|running|ok|active/i.test(s) && !/disconnect/i.test(s)) return { tone: "ok", text: "Running" };
  return { tone: /disconnect|stopped/i.test(s) ? "bad" : "warn", text: s.replace(/_/g, " ") };
}
const tone = (s: string) => (/connect|ready|running|ok|active|installed/i.test(s) ? "ok" : /error|fail|disconnect/i.test(s) ? "bad" : "warn") as "ok" | "bad" | "warn";

export function IntegrationsPage({ source, embedded, initialTab, back }: { source: JaegerSource; embedded?: boolean; initialTab?: "servers" | "tools" | "apps"; back?: { label: string; onBack: () => void } }) {
  const toast = useToast();
  const [tab, setTab] = useState<"servers" | "tools" | "apps">(initialTab ?? "servers");
  useEffect(() => { if (initialTab) setTab(initialTab); }, [initialTab]);
  const [adding, setAdding] = useState(false);
  const [inv, setInv] = useState<ToolInventory | null>(null);
  const [apps, setApps] = useState<ConnectAppsListing | null>(null);
  const [err, setErr] = useState<string>();
  const [q, setQ] = useState("");
  const [ask, setAsk] = useState<{ id: string; name: string; action: "disconnect" | "reconnect"; state: string } | { install: string; name: string }>();
  const load = useCallback(() => {
    source.tools?.().then(setInv, (e: Error) => setErr(e.message));
    source.connectApps?.list().then(setApps, () => setApps({ apps: [], categories: [], connected_count: 0 }));
  }, [source]);
  useEffect(() => { load(); }, [load]);
  const tools = useMemo(() => (inv?.tools ?? []).filter((t) => !q || `${t.name} ${t.description} ${t.toolset} ${t.server ?? ""}`.toLowerCase().includes(q.toLowerCase())), [inv, q]);
  const confirm = async () => {
    if (!ask) return; setAsk(undefined);
    try {
      if ("install" in ask) { await source.connectApps!.install(ask.install); toast(`Connecting ${ask.name}…`); }
      else { const r = await source.mcpControls!.mutate(ask.id, ask.action, { operation_id: crypto.randomUUID(), expected_state: ask.state }); if (!r.ok) throw new Error(r.error ?? "rejected"); toast(`${ask.name}: ${ask.action} requested`); }
      load();
    } catch (e) { toast((e as Error).message, "error"); }
  };
  return (
    <div className="jg-u-page">
      <PageHeader title="Integrations & MCP" embedded={embedded} back={back} subtitle={<>{inv ? `${inv.servers.length} MCP servers · ${inv.count} tools` : "Connected tools and connectors."}{apps ? ` · ${apps.connected_count} apps connected` : ""}</>} actions={<>
          {tab === "tools" && <input className="jg-u-search" type="search" placeholder="Search tools" aria-label="Search tools" value={q} onChange={(e) => setQ(e.target.value)} />}
          <Segmented label="Section" value={tab} onChange={setTab} options={[{ value: "servers", label: "MCP servers" }, { value: "tools", label: "Tools" }, { value: "apps", label: "Apps" }]} />
          <button type="button" className="jg-u-btn" onClick={load}>Refresh</button>
          {source.mcpConfiguration && <button type="button" className="jg-u-btn jg-u-btn--primary" onClick={() => setAdding(true)}>Add server</button>}
        </>} />
      {err && <p className="jg-u-error" role="alert">{err}</p>}
      {!source.tools && <Empty title="Tool inventory unavailable" />}
      {tab === "servers" && (!inv ? <SkeletonRows n={4} /> : !inv.servers.length ? <Empty title="No MCP servers configured">{inv.mcp_initialized ? "" : "MCP has not initialised yet."}</Empty> : (
        <ul className="jg-studio__grid jg-u-grid--m">{inv.servers.map((s) => (
          <li key={s.id ?? s.name} className="jg-u-card"><h2>{s.name} <Badge tone={pill(s.state).tone}>{pill(s.state).text}</Badge></h2>
            <p className="jg-u-note">{s.tool_count} tools{s.active_calls ? ` · ${s.active_calls} running` : ""}{s.resources_advertised ? " · resources" : ""}</p>
            {pill(s.state).tone === "bad" && <p className="jg-u-note">State: {s.state}. <a href="/settings/about#set-diagnostics">View log</a></p>}
            {source.mcpControls && s.id && <div className="jg-ui-toolbar">{(s.actions ?? []).filter((a): a is "disconnect" | "reconnect" => a === "disconnect" || a === "reconnect").map((a) => (
              <button key={a} type="button" className="jg-u-btn" onClick={() => setAsk({ id: s.id!, name: s.name, action: a, state: s.state })}>{a === "reconnect" ? "Reconnect" : "Disconnect"}</button>))}</div>}
          </li>))}</ul>))}
      {tab === "tools" && (!inv ? <SkeletonRows n={6} /> : (
        <section className="jg-u-card jg-u-card--flush">
          <table className="jg-table"><thead><tr><th>Tool</th><th>Toolset</th><th>Source</th><th>Tier</th></tr></thead>
            <tbody>{tools.slice(0, 400).map((t) => (
              <tr key={`${t.server ?? t.source}/${t.name}`}><td><strong>{t.name}</strong>{t.dangerous && <> <Badge tone="bad">dangerous</Badge></>}{t.beta && <> <Badge>beta</Badge></>}<br /><small>{t.description}</small></td>
                <td>{t.toolset}</td><td>{t.server ?? t.source}</td><td><Badge tone={t.availability === "available" ? "ok" : undefined}>{t.permission_tier}</Badge></td></tr>))}</tbody></table>
          {!tools.length && <Empty title="No tools match" />}
        </section>))}
      {tab === "apps" && (!apps ? <SkeletonRows n={4} /> : !apps.apps.length ? <Empty title="No connectors available">{source.connectApps ? "" : "This gateway doesn't expose Connect apps."}</Empty> : (
        <ul className="jg-studio__grid jg-u-grid--s">{apps.apps.map((a) => (
          <li key={a.id} className="jg-u-card"><h2>{a.name} <Badge tone={tone(a.state.value)}>{a.state.value}</Badge></h2>
            <p className="jg-u-note">{a.description ?? a.category}</p>{a.state.detail && <p className="jg-u-note">{a.state.detail}</p>}
            {a.actions.includes("install") && <button type="button" className="jg-u-btn" onClick={() => setAsk({ install: a.id, name: a.name })}>Connect…</button>}
          </li>))}</ul>))}
      {ask && (
        <Sheet title={"install" in ask ? `Connect ${ask.name}?` : `${ask.action === "reconnect" ? "Reconnect" : "Disconnect"} ${ask.name}?`} onClose={() => setAsk(undefined)}>
          <p>{"install" in ask ? "Jaeger will install and start this connector on this Mac." : ask.action === "disconnect" ? "Its tools stop being available to agents until you reconnect." : "Jaeger restarts the connection to this server."}</p>
          <div className="jg-ui-actions"><button type="button" className="jg-u-btn" onClick={() => setAsk(undefined)}>Cancel</button><button type="button" className="jg-u-btn jg-u-btn--primary" onClick={() => void confirm()}>Confirm</button></div>
        </Sheet>)}
      {adding && source.mcpConfiguration && <AddServerSheet controls={source.mcpConfiguration} onClose={() => setAdding(false)} onSaved={(n) => { setAdding(false); toast(`${n} saved. It connects when the gateway next starts its MCP servers.`); load(); }} />}
    </div>
  );
}

function AddServerSheet({ controls, onClose, onSaved }: { controls: NonNullable<JaegerSource["mcpConfiguration"]>; onClose: () => void; onSaved: (name: string) => void }) {
  const [name, setName] = useState("");
  const [transport, setTransport] = useState<"stdio" | "http">("stdio");
  const [target, setTarget] = useState("");
  const [err, setErr] = useState<string>();
  const [busy, setBusy] = useState(false);
  const save = async () => {
    const n = name.trim(), t = target.trim();
    if (!/^[A-Za-z0-9_-]{1,64}$/.test(n)) return setErr("Name: letters, numbers, - and _ only");
    if (!t) return setErr(transport === "http" ? "Enter the server URL" : "Enter the command");
    if (transport === "http" && !/^https?:\/\//.test(t)) return setErr("URL must start with http:// or https://");
    setBusy(true); setErr(undefined);
    try {
      const { config_revision } = await controls.read();
      const parts = t.match(/(?:[^\s"']+|"[^"]*"|'[^']*')+/g)?.map((p) => p.replace(/^["']|["']$/g, "")) ?? [];
      const definition = transport === "http" ? { name: n, url: t } : { name: n, command: parts[0], args: parts.slice(1) };
      const r = await controls.change({ operation_id: crypto.randomUUID(), expected_revision: config_revision, action: "stage", definition });
      if (r.outcome !== "saved") throw new Error(r.error ?? `Gateway ${r.outcome} the change`);
      onSaved(n);
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <Sheet title="Add MCP server" onClose={onClose}>
      <label className="jg-ui-field">Name<input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. github" autoFocus /></label>
      <Segmented label="Transport" value={transport} onChange={setTransport} options={[{ value: "stdio", label: "stdio (command)" }, { value: "http", label: "HTTP (URL)" }]} />
      <label className="jg-ui-field">{transport === "http" ? "URL" : "Command"}<input value={target} onChange={(e) => setTarget(e.target.value)} placeholder={transport === "http" ? "http://127.0.0.1:3000/mcp" : "npx -y @modelcontextprotocol/server-filesystem ~/Documents"} /></label>
      <p className="jg-u-note">Saved to the gateway's MCP config; no secrets are stored here. Servers that need a token sign in through their own flow.</p>
      {err && <p className="jg-u-error" role="alert">{err}</p>}
      <div className="jg-ui-actions"><button type="button" className="jg-u-btn" onClick={onClose}>Cancel</button><button type="button" className="jg-u-btn jg-u-btn--primary" disabled={busy} onClick={() => void save()}>Add server</button></div>
    </Sheet>
  );
}
