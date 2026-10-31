/** MCP & Integrations (unified UI): MCP servers (state, tools, reconnect/disconnect), every tool
 * the gateway exposes, and Connect-apps connectors with their status. Gateway APIs only. */
import { useCallback, useEffect, useMemo, useState } from "react";
import type { ConnectAppsListing, JaegerSource, ToolInventory } from "../api/source";
import { Badge, Empty, Segmented, Sheet, SkeletonRows, useToast, PageHead } from "./ui";

const tone = (s: string) => (/connect|ready|running|ok|active|installed/i.test(s) ? "ok" : /error|fail|disconnect/i.test(s) ? "bad" : "warn") as "ok" | "bad" | "warn";

export function IntegrationsPage({ source }: { source: JaegerSource }) {
  const toast = useToast();
  const [tab, setTab] = useState<"servers" | "tools" | "apps">("servers");
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
      <PageHead title={<>MCP &amp; Integrations</>} subtitle={<>{inv ? `${inv.servers.length} MCP servers · ${inv.count} tools` : "Connected tools and connectors."}{apps ? ` · ${apps.connected_count} apps connected` : ""}</>} actions={<>
          {tab === "tools" && <input className="jg-u-search" type="search" placeholder="Search tools" aria-label="Search tools" value={q} onChange={(e) => setQ(e.target.value)} />}
          <Segmented label="Section" value={tab} onChange={setTab} options={[{ value: "servers", label: "MCP servers" }, { value: "tools", label: "Tools" }, { value: "apps", label: "Apps" }]} />
          <button type="button" className="jg-u-btn" onClick={load}>Refresh</button>
        </>} />
      {err && <p className="jg-u-error" role="alert">{err}</p>}
      {!source.tools && <Empty title="Tool inventory unavailable" />}
      {tab === "servers" && (!inv ? <SkeletonRows n={4} /> : !inv.servers.length ? <Empty title="No MCP servers configured">{inv.mcp_initialized ? "" : "MCP has not initialised yet."}</Empty> : (
        <ul className="jg-studio__grid jg-u-grid--m">{inv.servers.map((s) => (
          <li key={s.id ?? s.name} className="jg-u-card"><h2>{s.name} <Badge tone={tone(s.state)}>{s.state}</Badge></h2>
            <p className="jg-u-note">{s.tool_count} tools{s.active_calls ? ` · ${s.active_calls} running` : ""}{s.resources_advertised ? " · resources" : ""}</p>
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
    </div>
  );
}
