/** Compare (unified UI): one prompt to two Ollama models side by side, with timing and tokens/s. */
import { useEffect, useState } from "react";
import { Markdown } from "../chat/Markdown";
import { Badge, Empty, SkeletonRows } from "./ui";
import { sendJson } from "./webui";
import { isEmbedding, loadModels, type LocalModel } from "./models";

interface Result { model: string; response: string; elapsed_s: number; eval_count?: number; tokens_per_s?: number | null; load_s?: number }
type Slot = { model: string; result?: Result; error?: string; busy?: boolean };

export function ComparePage() {
  const [models, setModels] = useState<LocalModel[] | null>(null);
  const [err, setErr] = useState<string>();
  const [prompt, setPrompt] = useState("");
  const [slots, setSlots] = useState<Slot[]>([{ model: "" }, { model: "" }]);
  useEffect(() => { loadModels().then((r) => { const chat = r.models.filter((m) => !isEmbedding(m)); setModels(chat); setSlots([{ model: chat[0]?.name ?? "" }, { model: chat[1]?.name ?? chat[0]?.name ?? "" }]); }, (e: Error) => setErr(e.message)); }, []);
  const run = () => {
    setSlots((s) => s.map((x) => ({ model: x.model, busy: true })));
    slots.forEach((s, i) => {
      sendJson<Result>("POST", "/v1/compare/run", { model: s.model, prompt })
        .then((r) => setSlots((xs) => xs.map((x, j) => (j === i ? { model: x.model, result: r } : x))), (e: Error) => setSlots((xs) => xs.map((x, j) => (j === i ? { model: x.model, error: e.message } : x))));
    });
  };
  const busy = slots.some((s) => s.busy);
  return (
    <div className="jg-u-page">
      <header className="jg-u-page__head"><div><h1>Compare</h1><p>Send the same prompt to two models and compare answers, speed and length.</p></div></header>
      {err && <p className="jg-u-error" role="alert">{err}</p>}
      <form className="jg-u-card jg-compare__form" onSubmit={(e) => { e.preventDefault(); run(); }}>
        <label className="jg-ui-field">Prompt<textarea rows={4} value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="Explain unified memory on Apple Silicon in three sentences." /></label>
        <div className="jg-ui-actions"><button className="jg-u-btn jg-u-btn--primary" disabled={!models?.length || !prompt.trim() || busy || slots.some((s) => !s.model)}>{busy ? "Running…" : "Run both"}</button></div>
      </form>
      <div className="jg-compare">
        {slots.map((s, i) => (
          <section key={i} className="jg-u-card" aria-label={`Model ${i + 1}`}>
            <div className="jg-ui-toolbar" style={{ justifyContent: "space-between" }}>
              <select className="jg-u-search" aria-label={`Model ${i + 1}`} value={s.model} disabled={!models || busy} onChange={(e) => setSlots((xs) => xs.map((x, j) => (j === i ? { model: e.target.value } : x)))}>
                {(models ?? []).map((m) => <option key={m.name} value={m.name}>{m.name}</option>)}
              </select>
              {s.result && <span style={{ display: "flex", gap: 4 }}><Badge>{s.result.elapsed_s}s</Badge>{s.result.tokens_per_s != null && <Badge tone="ok">{s.result.tokens_per_s} tok/s</Badge>}{s.result.eval_count != null && <Badge>{s.result.eval_count} tokens</Badge>}</span>}
            </div>
            <div className="jg-compare__out">
              {!models && !err ? <SkeletonRows /> : s.busy ? <SkeletonRows n={4} /> : s.error ? <p className="jg-u-error" role="alert">{s.error}</p>
                : s.result ? <Markdown text={s.result.response} /> : <Empty title="No answer yet">Pick a model and run a prompt.</Empty>}
            </div>
          </section>))}
      </div>
    </div>
  );
}
