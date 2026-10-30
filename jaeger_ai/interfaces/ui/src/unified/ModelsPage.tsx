/**
 * Models (unified UI, Cookbook): the Mac's Ollama models with size, parameters, quantisation,
 * whether each is loaded, and whether it fits this Mac's unified memory. Pull and remove go
 * through the WebUI's /v1/models API and always ask first.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Badge, Empty, Segmented, Sheet, SkeletonRows, useToast } from "./ui";
import { sendJson } from "./webui";
import { fit, gb, isCloud, isEmbedding, loadHardware, loadModels, type Hardware, type LocalModel, type Pull } from "./models";

const FIT_TEXT = { good: ["ok", "Fits well"], tight: ["warn", "Tight fit"], "too-big": ["bad", "Too big"], cloud: [undefined, "Runs in cloud"], unknown: [undefined, "Unknown"] } as const;

export function ModelsPage() {
  const toast = useToast();
  const [models, setModels] = useState<LocalModel[] | null>(null);
  const [pulls, setPulls] = useState<Pull[]>([]);
  const [hw, setHw] = useState<Hardware>();
  const [err, setErr] = useState<string>();
  const [q, setQ] = useState("");
  const [kind, setKind] = useState<"all" | "local" | "cloud" | "embedding">("all");
  const [ask, setAsk] = useState<{ op: "pull" | "remove"; name: string }>();
  const [pullName, setPullName] = useState("");
  const load = useCallback(() => loadModels().then((r) => { setModels(r.models); setPulls(r.pulls); setErr(undefined); }, (e: Error) => setErr(e.message)), []);
  useEffect(() => { void load(); loadHardware().then(setHw, () => {}); }, [load]);
  const running = pulls.some((p) => p.state === "running");
  useEffect(() => { if (!running) return; const t = setInterval(() => void load(), 2000); return () => clearInterval(t); }, [running, load]);
  const shown = useMemo(() => (models ?? []).filter((m) => (!q || m.name.toLowerCase().includes(q.toLowerCase()))
    && (kind === "all" || (kind === "cloud" ? isCloud(m) : kind === "embedding" ? isEmbedding(m) : !isCloud(m)))).sort((a, b) => b.size - a.size), [models, q, kind]);
  const totalLocal = (models ?? []).filter((m) => !isCloud(m)).reduce((n, m) => n + m.size, 0);
  const confirm = async () => {
    if (!ask) return;
    const { op, name } = ask; setAsk(undefined);
    try {
      if (op === "pull") { await sendJson("POST", "/v1/models/pull", { name }); toast(`Pulling ${name}…`); setPullName(""); }
      else { await sendJson("DELETE", `/v1/models/local/${encodeURIComponent(name)}`); toast(`Removed ${name}`); }
      await load();
    } catch (e) { toast(`${name}: ${(e as Error).message}`, "error"); }
  };
  return (
    <div className="jg-u-page">
      <header className="jg-u-page__head">
        <div><h1>Models</h1><p>{models ? `${models.length} models · ${gb(totalLocal)} on disk` : "Local Ollama models on this Mac."}</p></div>
        <div className="jg-ui-toolbar">
          <input className="jg-u-search" type="search" placeholder="Filter models" aria-label="Filter models" value={q} onChange={(e) => setQ(e.target.value)} />
          <Segmented label="Kind" value={kind} onChange={setKind} options={[{ value: "all", label: "All" }, { value: "local", label: "Local" }, { value: "cloud", label: "Cloud" }, { value: "embedding", label: "Embedding" }]} />
          <button type="button" className="jg-u-btn" onClick={() => void load()}>Refresh</button>
        </div>
      </header>
      {err && <p className="jg-u-error" role="alert">{err}</p>}
      <div className="jg-ui-split">
        <section className="jg-u-card" aria-label="Models" style={{ padding: 0, overflow: "hidden" }}>
          {!models && !err ? <div style={{ padding: 16 }}><SkeletonRows n={5} /></div> : !shown.length ? <Empty title="No models match" /> : (
            <table className="jg-table">
              <thead><tr><th>Model</th><th>Size</th><th>Params</th><th>Quant</th><th>Fit</th><th><span className="jg-sr">Actions</span></th></tr></thead>
              <tbody>{shown.map((m) => {
                const f = fit(m.size, hw?.memory ?? null); const [tone, text] = FIT_TEXT[f];
                return (
                  <tr key={m.name}>
                    <td><strong>{m.name}</strong>{m.loaded && <> <Badge tone="ok">Loaded</Badge></>}<br /><small>{[m.family, m.format, m.context ? `${Math.round(m.context / 1024)}K ctx` : null].filter(Boolean).join(" · ")}</small></td>
                    <td>{gb(m.size)}</td><td>{m.parameters ?? "–"}</td><td>{m.quantization ?? "–"}</td>
                    <td><Badge tone={tone}>{text}</Badge></td>
                    <td><button type="button" className="jg-u-icon-btn" onClick={() => setAsk({ op: "remove", name: m.name })} aria-label={`Remove ${m.name}`}>Remove</button></td>
                  </tr>);
              })}</tbody>
            </table>)}
        </section>
        <aside className="jg-ui-inspector" aria-label="This Mac">
          <h3>This Mac</h3>
          {!hw ? <SkeletonRows /> : (
            <dl className="jg-ui-kv">
              <dt>Chip</dt><dd>{hw.chip ?? "–"}</dd>
              <dt>Memory</dt><dd>{hw.memory ? `${Math.round(hw.memory / 2 ** 30)} GB unified` : "–"}</dd>
              <dt>CPU</dt><dd>{hw.cpu_cores ?? "–"} cores{hw.perf_cores ? ` (${hw.perf_cores} performance)` : ""}</dd>
              <dt>GPU</dt><dd>{hw.gpu_cores ? `${hw.gpu_cores} cores` : "–"}</dd>
              <dt>GPU budget</dt><dd>{hw.memory ? `≈ ${Math.round((hw.memory * 0.75) / 2 ** 30)} GB` : "–"}</dd>
            </dl>)}
          <p className="jg-u-note">{hw?.note}</p>
          <h3>Pull a model</h3>
          <form onSubmit={(e) => { e.preventDefault(); if (pullName.trim()) setAsk({ op: "pull", name: pullName.trim() }); }} style={{ display: "grid", gap: 8 }}>
            <label className="jg-ui-field">Ollama model name<input value={pullName} onChange={(e) => setPullName(e.target.value)} placeholder="qwen3:8b" /></label>
            <div className="jg-ui-actions"><button className="jg-u-btn jg-u-btn--primary" disabled={!pullName.trim()}>Pull…</button></div>
          </form>
          {pulls.length > 0 && <ul className="jg-u-list">{pulls.map((p) => (
            <li key={p.name} className="jg-pull"><strong>{p.name}</strong> <Badge tone={p.state === "done" ? "ok" : p.state === "error" ? "bad" : "warn"}>{p.state}</Badge>
              <span>{p.status}{p.total ? ` · ${Math.round((100 * p.completed) / p.total)}%` : ""}</span>
              {p.state === "running" && p.total > 0 && <progress max={p.total} value={p.completed} />}</li>))}</ul>}
        </aside>
      </div>
      {ask && (
        <Sheet title={ask.op === "pull" ? `Pull ${ask.name}?` : `Remove ${ask.name}?`} onClose={() => setAsk(undefined)}>
          <p>{ask.op === "pull" ? "Ollama will download this model from its registry. Large models can take many gigabytes of disk." : "This deletes the model's files from this Mac. You can pull it again later."}</p>
          <div className="jg-ui-actions"><button type="button" className="jg-u-btn" onClick={() => setAsk(undefined)}>Cancel</button>
            <button type="button" className={`jg-u-btn ${ask.op === "pull" ? "jg-u-btn--primary" : "jg-u-btn--danger"}`} onClick={() => void confirm()}>{ask.op === "pull" ? "Pull" : "Remove"}</button></div>
        </Sheet>)}
    </div>
  );
}
