/**
 * Compare (unified UI): one prompt to 2–4 models, streamed side by side from Ollama through the
 * WebUI's /v1/compare/stream. Metrics are Ollama's own counters (tokens, eval time, load time);
 * cost is $0 for local models and unknown for cloud ones. Finished runs are saved to
 * /v1/compare/history with an optional winner vote.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { Markdown } from "../chat/Markdown";
import { Badge, Empty, SkeletonRows, useToast } from "./ui";
import { deleteRun, fmtCost, isCloud, isEmbedding, loadModels, loadRuns, saveRun, streamCompare, voteRun,
  type CompareRun, type LocalModel, type Metrics, type RunResult } from "./models";

export interface Slot { model: string; text: string; thinking: string; state: "idle" | "running" | "done" | "error" | "stopped"; metrics?: Metrics; error?: string }
const blank = (model: string): Slot => ({ model, text: "", thinking: "", state: "idle" });
export const pickDefaults = (ms: LocalModel[], n = 2) => {
  const local = ms.filter((m) => !isCloud(m)).sort((a, b) => a.size - b.size);
  return [...local, ...ms.filter(isCloud)].slice(0, n).map((m) => m.name);
};
export const toResult = (s: Slot): RunResult => ({ model: s.model, response: s.text, ...(s.metrics ?? {}), ...(s.error ? { error: s.error } : {}) });

export function ComparePage() {
  const toast = useToast();
  const [models, setModels] = useState<LocalModel[] | null>(null);
  const [err, setErr] = useState<string>();
  const [prompt, setPrompt] = useState("");
  const [slots, setSlots] = useState<Slot[]>([blank(""), blank("")]);
  const [runs, setRuns] = useState<CompareRun[]>([]);
  const [current, setCurrent] = useState<CompareRun>();
  const ctl = useRef<AbortController[]>([]);
  const slotsRef = useRef(slots); slotsRef.current = slots;

  useEffect(() => {
    loadModels().then((r) => { const chat = r.models.filter((m) => !isEmbedding(m)); setModels(chat); const d = pickDefaults(chat); setSlots([blank(d[0] ?? ""), blank(d[1] ?? d[0] ?? "")]); }, (e: Error) => { setModels([]); setErr(e.message); });
    loadRuns().then((r) => setRuns(r.runs), () => {});
  }, []);
  const patch = (i: number, f: (s: Slot) => Slot) => setSlots((xs) => xs.map((x, j) => (j === i ? f(x) : x)));

  /** Streams one slot; keeps a local copy so the caller gets the final state without waiting for a render. */
  const runSlot = useCallback(async (i: number, model: string, text: string): Promise<Slot> => {
    const ac = new AbortController(); ctl.current[i]?.abort(); ctl.current[i] = ac;
    let cur: Slot = { ...blank(model), state: "running" };
    const set = (f: (s: Slot) => Slot) => { cur = f(cur); const snap = cur; patch(i, () => snap); };
    set(() => cur);
    try {
      await streamCompare(model, text, (e) => {
        if (e.type === "delta") set((s) => ({ ...s, text: s.text + e.text }));
        else if (e.type === "thinking") set((s) => ({ ...s, thinking: s.thinking + e.text }));
        else if (e.type === "done") { const { type: _t, model: _m, ...m } = e; set((s) => ({ ...s, state: "done", metrics: m })); }
        else if (e.type === "error") set((s) => ({ ...s, state: "error", error: e.error }));
      }, ac.signal);
      if (cur.state === "running") set((s) => ({ ...s, state: "error", error: "The stream ended before the model finished." }));
    } catch (e) {
      set((s) => (ac.signal.aborted ? { ...s, state: "stopped" } : { ...s, state: "error", error: (e as Error).message }));
    }
    return cur;
  }, []);

  const runAll = async () => {
    const text = prompt; setCurrent(undefined);
    const done = await Promise.all(slotsRef.current.map((s, i) => runSlot(i, s.model, text)));
    if (done.some((s) => s.state === "done")) {
      try { const run = await saveRun(text, done.map(toResult)); setCurrent(run); setRuns((r) => [run, ...r.filter((x) => x.id !== run.id)]); }
      catch (e) { toast(`Couldn't save this run: ${(e as Error).message}`, "error"); }
    }
  };
  const stop = () => ctl.current.forEach((c) => c?.abort());
  const vote = async (winner: string | null) => {
    if (!current) return;
    try { const r = await voteRun(current.id, current.winner === winner ? null : winner); setCurrent(r); setRuns((xs) => xs.map((x) => (x.id === r.id ? r : x))); }
    catch (e) { toast(`Vote not saved: ${(e as Error).message}`, "error"); }
  };
  const open = (r: CompareRun) => { stop(); setCurrent(r); setPrompt(r.prompt); setSlots(r.results.map((x) => ({ model: x.model, text: x.response, thinking: "", state: x.error ? "error" : "done", error: x.error, metrics: x.elapsed_s != null ? (x as Metrics) : undefined }))); };
  const remove = async (r: CompareRun) => { try { await deleteRun(r.id); setRuns((xs) => xs.filter((x) => x.id !== r.id)); if (current?.id === r.id) setCurrent(undefined); } catch (e) { toast((e as Error).message, "error"); } };
  const copy = async (s: Slot) => { try { await navigator.clipboard.writeText(s.text); toast(`Copied ${s.model}'s answer`); } catch { toast("Clipboard unavailable", "error"); } };

  const busy = slots.some((s) => s.state === "running");
  const fastest = slots.filter((s) => s.metrics?.tokens_per_s).sort((a, b) => (b.metrics!.tokens_per_s ?? 0) - (a.metrics!.tokens_per_s ?? 0))[0]?.model;
  const local = (models ?? []).filter((m) => !isCloud(m)); const cloud = (models ?? []).filter(isCloud);
  const canRun = !!models?.length && !!prompt.trim() && !busy && slots.every((s) => s.model);

  return (
    <div className="jg-u-page jg-cmp">
      <header className="jg-u-page__head"><div><h1>Compare</h1><p>One prompt, up to four models, streamed side by side with Ollama's real timings.</p></div></header>
      {err && <p className="jg-u-error" role="alert">Ollama: {err}. Start Ollama to compare local models.</p>}
      <div className="jg-cmp__layout">
        <div className="jg-cmp__main">
          <form className="jg-u-card jg-compare__form" onSubmit={(e) => { e.preventDefault(); if (canRun) void runAll(); }}>
            <label className="jg-ui-field">Prompt<textarea rows={3} value={prompt} onChange={(e) => setPrompt(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && canRun) { e.preventDefault(); void runAll(); } }} placeholder="Explain unified memory on Apple Silicon in three sentences." /></label>
            <div className="jg-ui-actions jg-cmp__bar">
              <span className="jg-u-note">{slots.length} models · ⌘↩ to run</span>
              <button type="button" className="jg-u-btn" disabled={busy || slots.length >= 4 || !models?.length} onClick={() => setSlots((s) => [...s, blank(pickDefaults(models ?? [], s.length + 1)[s.length] ?? models?.[0]?.name ?? "")])}>Add model</button>
              {busy ? <button type="button" className="jg-u-btn jg-u-btn--danger" onClick={stop}>Stop</button>
                : <button className="jg-u-btn jg-u-btn--primary" disabled={!canRun}>Run {slots.length}</button>}
            </div>
          </form>
          {current && slots.some((s) => s.state === "done") && (
            <div className="jg-cmp__vote" role="group" aria-label="Pick a winner">
              <span>Which answer was best?</span>
              {slots.map((s) => <button key={s.model} type="button" className="jg-u-btn" aria-pressed={current.winner === s.model} onClick={() => void vote(s.model)}>{s.model}</button>)}
              <button type="button" className="jg-u-btn" aria-pressed={current.winner === "tie"} onClick={() => void vote("tie")}>Tie</button>
            </div>)}
          <div className="jg-compare" data-count={slots.length}>
            {slots.map((s, i) => (
              <section key={i} className="jg-u-card jg-cmp__slot" aria-label={`Model ${i + 1}`} data-state={s.state} data-winner={current?.winner === s.model || undefined}>
                <div className="jg-cmp__slothead">
                  <select className="jg-u-search" aria-label={`Model ${i + 1}`} value={s.model} disabled={!models?.length || busy} onChange={(e) => patch(i, () => blank(e.target.value))}>
                    {!models?.length && <option value="">No models</option>}
                    {local.length > 0 && <optgroup label="On this Mac">{local.map((m) => <option key={m.name} value={m.name}>{m.name}{m.parameters ? ` · ${m.parameters}` : ""}</option>)}</optgroup>}
                    {cloud.length > 0 && <optgroup label="Ollama Cloud">{cloud.map((m) => <option key={m.name} value={m.name}>{m.name}</option>)}</optgroup>}
                  </select>
                  <div className="jg-cmp__tools">
                    <button type="button" className="jg-u-icon-btn" disabled={!s.text} onClick={() => void copy(s)} aria-label={`Copy ${s.model}'s answer`}>Copy</button>
                    <button type="button" className="jg-u-icon-btn" disabled={s.state === "running" || !prompt.trim() || !s.model} onClick={() => void runSlot(i, s.model, prompt)} aria-label={`Rerun ${s.model}`}>Rerun</button>
                    {slots.length > 2 && <button type="button" className="jg-u-icon-btn" disabled={busy} onClick={() => setSlots((xs) => xs.filter((_, j) => j !== i))} aria-label={`Remove model ${i + 1}`}>✕</button>}
                  </div>
                </div>
                <dl className="jg-cmp__metrics" aria-label="Metrics">
                  <div><dt>Total</dt><dd>{s.metrics ? `${s.metrics.elapsed_s}s` : s.state === "running" ? "…" : "–"}</dd></div>
                  <div><dt>First token</dt><dd>{s.metrics?.ttft_s != null ? `${s.metrics.ttft_s}s` : "–"}</dd></div>
                  <div><dt>Tokens</dt><dd>{s.metrics?.eval_count ?? "–"}{s.metrics?.prompt_eval_count != null ? <small> / {s.metrics.prompt_eval_count} in</small> : null}</dd></div>
                  <div><dt>Speed</dt><dd>{s.metrics?.tokens_per_s != null ? <>{s.metrics.tokens_per_s} tok/s{fastest === s.model && slots.length > 1 && <> <Badge tone="ok">Fastest</Badge></>}</> : "–"}</dd></div>
                  <div><dt>Load</dt><dd>{s.metrics?.load_s != null ? `${s.metrics.load_s}s` : "–"}</dd></div>
                  <div><dt>Cost</dt><dd>{s.metrics ? fmtCost(s.metrics.cost_usd) : "–"}</dd></div>
                </dl>
                <div className="jg-cmp__out" aria-live="polite" aria-busy={s.state === "running"}>
                  {models === null ? <SkeletonRows /> : s.state === "error" ? <p className="jg-u-error" role="alert">{s.error}</p>
                    : s.text ? <><Markdown text={s.text} />{s.state === "stopped" && <p className="jg-u-note">Stopped.</p>}</>
                    : s.state === "running" ? <>{s.thinking ? <p className="jg-cmp__thinking">Thinking… {s.thinking.slice(-240)}</p> : <SkeletonRows n={3} />}</>
                    : <Empty title="No answer yet">Write a prompt and run it.</Empty>}
                </div>
              </section>))}
          </div>
        </div>
        <aside className="jg-ui-inspector jg-cmp__history" aria-label="History">
          <h3>History</h3>
          {!runs.length ? <p className="jg-u-note">Finished runs are saved here with your vote.</p> : (
            <ul className="jg-u-list">{runs.map((r) => (
              <li key={r.id} className="jg-cmp__run" aria-current={current?.id === r.id || undefined}>
                <button type="button" onClick={() => open(r)}>
                  <strong>{r.prompt.slice(0, 80)}</strong>
                  <span>{r.results.map((x) => x.model).join(" vs ")}</span>
                  <small>{new Date(r.created_at * 1000).toLocaleString()}{r.winner ? ` · ${r.winner === "tie" ? "Tie" : `🏆 ${r.winner}`}` : ""}</small>
                </button>
                <button type="button" className="jg-u-icon-btn" aria-label="Delete run" onClick={() => void remove(r)}>✕</button>
              </li>))}</ul>)}
        </aside>
      </div>
    </div>
  );
}
