/**
 * Models (unified UI): a real inventory grouped by provider. Ollama groups come from this Mac's
 * /api/tags (size, parameters, quantisation, context, loaded) and the providers list comes from the
 * WebUI's /api/models, which only includes configured providers. "Make default" calls Jaeger's
 * own default-model setting; pull and remove go through /v1/models and always confirm first.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Badge, Empty, Segmented, Sheet, SkeletonRows, useToast } from "./ui";
import { sendJson } from "./webui";
import { fit, gb, inventory, isCloud, isDefault, isEmbedding, loadCatalog, loadHardware, loadModels, loadProviderKeys, setDefaultModel,
  type Catalog, type Hardware, type LocalModel, type ProviderKey, type Pull, type Row } from "./models";

const FIT_TEXT = { good: ["ok", "Fits well"], tight: ["warn", "Tight fit"], "too-big": ["bad", "Too big"], cloud: [undefined, "Cloud"], unknown: [undefined, "–"] } as const;
type Kind = "all" | "local" | "cloud" | "loaded" | "embedding";
type Ask = { op: "pull" | "remove"; name: string } | { op: "default"; name: string; provider: string };

export function matches(r: Row, q: string, kind: Kind): boolean {
  const text = [r.name, r.local?.family, r.local?.quantization, r.local?.parameters, ...(r.catalog?.capabilities ?? [])].filter(Boolean).join(" ").toLowerCase();
  if (q && !q.toLowerCase().split(/\s+/).every((w) => text.includes(w))) return false;
  const cloud = r.providerId !== "ollama-local" || (r.local ? isCloud(r.local) : false);
  return kind === "all" || (kind === "local" ? !cloud : kind === "cloud" ? cloud : kind === "loaded" ? !!r.local?.loaded : isEmbedding({ name: r.name, family: r.local?.family }));
}

export function ModelsPage() {
  const toast = useToast();
  const [models, setModels] = useState<LocalModel[] | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [keys, setKeys] = useState<ProviderKey[]>([]);
  const [pulls, setPulls] = useState<Pull[]>([]);
  const [hw, setHw] = useState<Hardware>();
  const [err, setErr] = useState<{ ollama?: string; catalog?: string }>({});
  const [q, setQ] = useState("");
  const [kind, setKind] = useState<Kind>("all");
  const [ask, setAsk] = useState<Ask>();
  const [pullName, setPullName] = useState("");
  const [busy, setBusy] = useState(false);
  const loadLocal = useCallback(() => loadModels().then((r) => { setModels(r.models); setPulls(r.pulls); setErr((e) => ({ ...e, ollama: undefined })); }, (e: Error) => { setModels([]); setErr((x) => ({ ...x, ollama: e.message })); }), []);
  const loadCat = useCallback(() => loadCatalog().then((c) => { setCatalog(c); setErr((e) => ({ ...e, catalog: undefined })); }, (e: Error) => setErr((x) => ({ ...x, catalog: e.message }))), []);
  const load = useCallback(() => Promise.all([loadLocal(), loadCat()]), [loadLocal, loadCat]);
  useEffect(() => { void load(); loadHardware().then(setHw, () => {}); loadProviderKeys().then((r) => setKeys(r.providers ?? []), () => {}); }, [load]);
  const running = pulls.some((p) => p.state === "running");
  useEffect(() => { if (!running) return; const t = setInterval(() => void loadLocal(), 1500); return () => clearInterval(t); }, [running, loadLocal]);
  // Refresh the catalog once a pull finishes so the new model is listed.
  useEffect(() => { if (!running && pulls.some((p) => p.state === "done")) void loadCat(); }, [running, pulls, loadCat]);

  const groups = useMemo(() => inventory(catalog, models), [catalog, models]);
  const shown = useMemo(() => groups.map((g) => ({ ...g, rows: g.rows.filter((r) => matches(r, q, kind)).sort((a, b) => (b.local?.size ?? 0) - (a.local?.size ?? 0) || a.name.localeCompare(b.name)) })), [groups, q, kind]);
  const total = groups.reduce((n, g) => n + g.rows.length, 0);
  const visibleCount = shown.reduce((n, g) => n + g.rows.length, 0);
  const totalLocal = (models ?? []).filter((m) => !isCloud(m)).reduce((n, m) => n + m.size, 0);
  const keyed = keys.filter((k) => k.has_key);
  const loading = models === null || (catalog === null && !err.catalog);

  const confirm = async () => {
    if (!ask) return;
    setBusy(true);
    try {
      if (ask.op === "pull") { await sendJson("POST", "/v1/models/pull", { name: ask.name }); toast(`Pulling ${ask.name}…`); setPullName(""); await loadLocal(); }
      else if (ask.op === "remove") { await sendJson("DELETE", `/v1/models/local/${encodeURIComponent(ask.name)}`); toast(`Removed ${ask.name}`); await load(); }
      else if (ask.op === "default") { await setDefaultModel(ask.name, ask.provider); toast(`${ask.name} is now Jaeger's default model`); await loadCat(); }
      setAsk(undefined);
    } catch (e) { toast(`${ask.name}: ${(e as Error).message}`, "error"); }
    finally { setBusy(false); }
  };

  return (
    <div className="jg-u-page jg-models">
      <header className="jg-u-page__head">
        <div><h1>Models</h1><p>{loading ? "Loading models…" : `${total} models across ${groups.length} provider${groups.length === 1 ? "" : "s"} · ${gb(totalLocal)} on this Mac`}</p></div>
        <div className="jg-ui-toolbar">
          <input className="jg-u-search" type="search" placeholder="Search name, family, quant, capability" aria-label="Search models" value={q} onChange={(e) => setQ(e.target.value)} />
          <Segmented label="Show" value={kind} onChange={setKind} options={[{ value: "all", label: "All" }, { value: "local", label: "Local" }, { value: "cloud", label: "Cloud" }, { value: "loaded", label: "Loaded" }, { value: "embedding", label: "Embedding" }]} />
          <button type="button" className="jg-u-btn" onClick={() => void load()}>Refresh</button>
        </div>
      </header>
      {catalog?.default_model && <p className="jg-models__default">Default model <strong>{catalog.default_model}</strong> <span>via {groups.find((g) => g.id === catalog.active_provider)?.title ?? catalog.active_provider}</span></p>}
      {err.ollama && <p className="jg-u-error" role="alert">Ollama: {err.ollama}. Local models can't be listed, pulled or removed until it's running.</p>}
      {err.catalog && <p className="jg-u-error" role="alert">Provider catalog unavailable: {err.catalog}</p>}
      <div className="jg-ui-split">
        <div className="jg-models__groups">
          {loading ? <section className="jg-u-card"><SkeletonRows n={6} /></section>
            : !total ? <section className="jg-u-card"><Empty title="No models yet">Pull an Ollama model on the right, or add a provider key in Settings → Providers.</Empty></section>
            : !visibleCount ? <section className="jg-u-card"><Empty title={q ? `Nothing matches "${q}"` : "No models in this view"} action={<button type="button" className="jg-u-btn" onClick={() => { setQ(""); setKind("all"); }}>Clear filters</button>} /></section>
            : shown.filter((g) => g.rows.length).map((g) => (
              <section key={g.id} className="jg-u-card jg-models__group" aria-label={g.title}>
                <header className="jg-models__ghead">
                  <span className="jg-models__dot" data-status={g.group?.status ?? "unknown"} aria-hidden="true" />
                  <h2>{g.title}</h2>
                  <span className="jg-models__gmeta">{g.rows.length} model{g.rows.length === 1 ? "" : "s"}{g.group?.endpoint ? ` · ${g.group.endpoint.replace(/^https?:\/\//, "")}` : ""}{g.group?.status ? ` · ${g.group.status}` : ""}</span>
                </header>
                <table className="jg-table">
                  <thead><tr><th>Model</th><th>Size</th><th>Context</th><th>Quant</th><th>Status</th><th><span className="jg-sr">Actions</span></th></tr></thead>
                  <tbody>{g.rows.map((r) => {
                    const m = r.local; const def = isDefault(catalog, r.providerId, r.name);
                    const f = m ? fit(m.size, hw?.memory ?? null) : "cloud"; const [tone, text] = FIT_TEXT[f];
                    const canRemove = r.providerId === "ollama-local" && m && !isCloud(m);
                    return (
                      <tr key={r.key} data-default={def || undefined}>
                        <td><strong>{r.name}</strong>{def && <> <Badge tone="ok">Default</Badge></>}
                          <br /><small>{[m?.family, m?.parameters, ...(r.catalog?.capabilities ?? []).filter((c) => c !== "completion")].filter(Boolean).join(" · ") || "–"}</small></td>
                        <td>{m ? gb(m.size) : r.catalog?.size_gb ? `${r.catalog.size_gb} GB` : "–"}</td>
                        <td>{m?.context ? `${Math.round(m.context / 1024)}K` : "–"}</td>
                        <td>{m?.quantization ?? "–"}</td>
                        <td>{m?.loaded ? <Badge tone="ok">Loaded{m.vram ? ` · ${gb(m.vram)}` : ""}</Badge> : <Badge tone={tone}>{text}</Badge>}</td>
                        <td className="jg-models__actions">
                          {!def && r.catalog && <button type="button" className="jg-u-icon-btn" onClick={() => setAsk({ op: "default", name: r.name, provider: r.providerId })} aria-label={`Make ${r.name} the default`}>Make default</button>}
                          {canRemove && <button type="button" className="jg-u-icon-btn jg-models__danger" onClick={() => setAsk({ op: "remove", name: r.name })} aria-label={`Remove ${r.name}`}>Remove</button>}
                        </td>
                      </tr>);
                  })}</tbody>
                </table>
              </section>))}
          {!loading && <p className="jg-u-note">{keyed.length ? `Keys stored for: ${keyed.map((k) => k.id).join(", ")}.` : "No cloud API keys are stored; Ollama Cloud models run through this Mac's Ollama sign-in."} Add providers in Settings → Providers.</p>}
        </div>
        <aside className="jg-ui-inspector" aria-label="This Mac">
          <h3>This Mac</h3>
          {!hw ? <SkeletonRows /> : (
            <dl className="jg-ui-kv">
              <dt>Chip</dt><dd>{hw.chip ?? "–"}</dd>
              <dt>Memory</dt><dd>{hw.memory ? `${Math.round(hw.memory / 2 ** 30)} GB unified` : "–"}</dd>
              <dt>CPU</dt><dd>{hw.cpu_cores ?? "–"} cores{hw.perf_cores ? ` (${hw.perf_cores} performance)` : ""}</dd>
              <dt>GPU</dt><dd>{hw.gpu_cores ? `${hw.gpu_cores} cores` : "–"}</dd>
              <dt>GPU budget</dt><dd>{hw.memory ? `≈ ${Math.round((hw.memory * 0.75) / 2 ** 30)} GB` : "–"}</dd>
              <dt>Loaded now</dt><dd>{(models ?? []).filter((m) => m.loaded).map((m) => m.name).join(", ") || "none"}</dd>
            </dl>)}
          <p className="jg-u-note">{hw?.note}</p>
          <h3>Pull from Ollama</h3>
          <form onSubmit={(e) => { e.preventDefault(); if (pullName.trim()) setAsk({ op: "pull", name: pullName.trim() }); }} style={{ display: "grid", gap: 8 }}>
            <label className="jg-ui-field">Model name<input value={pullName} onChange={(e) => setPullName(e.target.value)} placeholder="qwen3:8b" disabled={!!err.ollama} /></label>
            <div className="jg-ui-actions"><button className="jg-u-btn jg-u-btn--primary" disabled={!pullName.trim() || !!err.ollama}>Pull…</button></div>
          </form>
          {pulls.length > 0 && <ul className="jg-u-list" aria-label="Downloads">{pulls.map((p) => (
            <li key={p.name} className="jg-pull"><strong>{p.name}</strong> <Badge tone={p.state === "done" ? "ok" : p.state === "error" ? "bad" : "warn"}>{p.state === "running" ? "downloading" : p.state}</Badge>
              <span>{p.status}{p.total ? ` · ${gb(p.completed)} of ${gb(p.total)} (${Math.round((100 * p.completed) / p.total)}%)` : ""}</span>
              {p.state === "running" && <progress max={p.total || 1} value={p.total ? p.completed : undefined} aria-label={`${p.name} progress`} />}</li>))}</ul>}
        </aside>
      </div>
      {ask && (
        <Sheet title={ask.op === "pull" ? `Pull ${ask.name}?` : ask.op === "remove" ? `Remove ${ask.name}?` : `Make ${ask.name} the default?`} onClose={() => !busy && setAsk(undefined)}>
          <p>{ask.op === "pull" ? "Ollama will download this model from its registry. Large models can take many gigabytes of disk."
            : ask.op === "remove" ? "This deletes the model's files from this Mac. Agents set to this model will stop working until you pull it again."
            : `Jaeger's main model setting changes to ${ask.name} (${ask.op === "default" ? ask.provider : ""}). Agents that use the default pick it up on their next turn.`}</p>
          <div className="jg-ui-actions"><button type="button" className="jg-u-btn" disabled={busy} onClick={() => setAsk(undefined)}>Cancel</button>
            <button type="button" className={`jg-u-btn ${ask.op === "remove" ? "jg-u-btn--danger" : "jg-u-btn--primary"}`} disabled={busy} onClick={() => void confirm()}>{busy ? "Working…" : ask.op === "pull" ? "Pull" : ask.op === "remove" ? "Remove" : "Make default"}</button></div>
        </Sheet>)}
    </div>
  );
}
