/**
 * Deep Research (unified UI): a research question becomes a gateway task (proposal → your
 * approval → the agent's task runner) whose goal asks for a multi-step plan and a Markdown
 * report with sources. The report is the task's result; artifacts are listed and the report can
 * be saved to Documents. Which tools (e.g. web search) the agent may use is up to the gateway.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import type { JaegerSource } from "../api/source";
import type { Agent, Task } from "../api/types";
import { label, visible } from "../agents/agentsLogic";
import { TaskArtifacts } from "../library/TaskArtifacts";
import { Markdown } from "../chat/Markdown";
import { Badge, Empty, Segmented, SkeletonRows, useToast, PageHead } from "./ui";
import { sendJson } from "./webui";

export const RESEARCH_PREFIX = "Deep research: ";
export function researchGoal(question: string, depth: "quick" | "standard" | "deep") {
  const steps = depth === "quick" ? 3 : depth === "deep" ? 8 : 5;
  return `${RESEARCH_PREFIX}${question.trim()}\n\nWork in steps: (1) break the question into up to ${steps} sub-questions; (2) investigate each with the tools you are allowed to use, noting every source; (3) reconcile conflicts; (4) write the final answer as a Markdown report with a summary, findings per sub-question, open questions, and a numbered list of sources. Say clearly when something could not be verified.`;
}
export const isResearch = (t: Task) => (t.goal ?? "").startsWith(RESEARCH_PREFIX);
const question = (t: Task) => (t.goal ?? "").slice(RESEARCH_PREFIX.length).split("\n")[0];
const resultText = (r: unknown) => (typeof r === "string" ? r : r && typeof r === "object" && typeof (r as { text?: unknown }).text === "string" ? (r as { text: string }).text : r == null ? "" : "```json\n" + JSON.stringify(r, null, 2) + "\n```");
const isProposal = (t: Task) => t.state === "paused" && t.provenance?.authorized === false && !t.run_history?.length;

export function ResearchPage({ source, agents, onNavigate }: { source: JaegerSource; agents: Agent[]; onNavigate: (to: string) => void }) {
  const toast = useToast();
  const live = agents.filter(visible);
  const [q, setQ] = useState("");
  const [depth, setDepth] = useState<"quick" | "standard" | "deep">("standard");
  const [agentId, setAgentId] = useState("");
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [err, setErr] = useState<string>();
  const [sel, setSel] = useState<string>();
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (!agentId && live[0]) setAgentId((live.find((a) => a.primary) ?? live[0]).id); }, [live, agentId]);
  const load = useCallback(() => source.tasks().then((t) => { setTasks(t.filter(isResearch)); setErr(undefined); }, (e: Error) => setErr(e.message)), [source]);
  useEffect(() => { void load(); const t = setInterval(() => void load(), 10000); return () => clearInterval(t); }, [load]);
  const runs = useMemo(() => [...(tasks ?? [])].sort((a, b) => Number(b.updated_at ?? 0) - Number(a.updated_at ?? 0)), [tasks]);
  const task = runs.find((t) => t.task_id === sel) ?? runs[0];
  const can = Boolean(source.taskActions && source.agentHome);
  const start = async () => {
    if (!source.taskActions || !source.agentHome) return;
    setBusy(true);
    try {
      const home = await source.agentHome(agentId);
      const r = await source.taskActions.create({ session_id: home.session_id, goal: researchGoal(q, depth), request_id: crypto.randomUUID(), proposal: true });
      toast("Research proposed — approve it to start");
      setQ(""); await load(); setSel(r.task_id);
    } catch (e) { toast(`Couldn't start research: ${(e as Error).message}`, "error"); } finally { setBusy(false); }
  };
  const act = async (fn: () => Promise<void>, ok: string) => { setBusy(true); try { await fn(); toast(ok); await load(); } catch (e) { toast((e as Error).message, "error"); } finally { setBusy(false); } };
  const saveDoc = async (t: Task) => {
    try { const d = await sendJson<{ id: string }>("POST", "/v1/documents", { title: `Research: ${question(t)}`.slice(0, 200), body: resultText(t.result) }); toast("Saved to Documents"); onNavigate(`/research/documents?doc=${d.id}`); }
    catch (e) { toast((e as Error).message, "error"); }
  };
  return (
    <div className="jg-u-page">
      <PageHead title="Deep Research" subtitle="Multi-step research runs as a task you approve; the agent returns a sourced report." />
      <form className="jg-u-card jg-compare__form" onSubmit={(e) => { e.preventDefault(); void start(); }}>
        <label className="jg-ui-field">Research question<textarea rows={3} maxLength={4000} value={q} onChange={(e) => setQ(e.target.value)} placeholder="What are the trade-offs of MLX vs GGUF for running 30B models on an M1 Max?" /></label>
        <div className="jg-ui-toolbar jg-spread">
          <div className="jg-ui-toolbar">
            <select className="jg-u-search" aria-label="Research agent" value={agentId} onChange={(e) => setAgentId(e.target.value)}>{live.map((a) => <option key={a.id} value={a.id}>{label(a)}</option>)}</select>
            <Segmented label="Depth" value={depth} onChange={setDepth} options={[{ value: "quick", label: "Quick" }, { value: "standard", label: "Standard" }, { value: "deep", label: "Deep" }]} />
          </div>
          <button className="jg-u-btn jg-u-btn--primary" disabled={!can || !q.trim() || !agentId || busy}>Propose research</button>
        </div>
        {!can && <p className="jg-u-note">This gateway doesn't accept task proposals.</p>}
      </form>
      {err && <p className="jg-u-error" role="alert">{err}</p>}
      <div className="jg-ui-split jg-mt-4">
        <section className="jg-u-card" aria-label="Research runs">
          <h2>Runs</h2>
          {!tasks && !err ? <SkeletonRows /> : !runs.length ? <Empty title="No research yet">Ask a question above to start one.</Empty> : (
            <ul className="jg-u-list">{runs.map((t) => (
              <li key={t.task_id}><button type="button" className="jg-u-row" aria-current={t.task_id === task?.task_id || undefined} onClick={() => setSel(t.task_id)}>
                <span className="jg-u-row__text"><strong>{question(t)}</strong><span>{String(t.state)} · {t.updated_at ? new Date(t.updated_at * 1000).toLocaleString() : ""}</span></span>
              </button></li>))}</ul>)}
        </section>
        <aside className="jg-ui-inspector" aria-label="Report">
          {!task ? <Empty title="No run selected" /> : (<>
            <h3>Report</h3>
            <strong>{question(task)}</strong>
            <span className="jg-row"><Badge tone={task.state === "done" ? "ok" : task.state === "failed" ? "bad" : "warn"}>{String(task.state).replace(/_/g, " ")}</Badge></span>
            <div className="jg-ui-toolbar">
              {isProposal(task) && source.taskActions && typeof task.updated_at === "number" && <button type="button" className="jg-u-btn jg-u-btn--primary" disabled={busy} onClick={() => void act(() => source.taskActions!.approve(task.task_id, task.updated_at!), "Approved — research started")}>Approve &amp; start</button>}
              {!["done", "failed", "cancelled"].includes(String(task.state)) && source.taskActions && <button type="button" className="jg-u-btn jg-u-btn--danger" disabled={busy} onClick={() => void act(() => source.taskActions!.cancel(task.task_id), "Cancellation requested")}>Cancel</button>}
              {task.result != null && <button type="button" className="jg-u-btn" onClick={() => void saveDoc(task)}>Save to Documents</button>}
              <button type="button" className="jg-u-btn" onClick={() => onNavigate(`/work/tasks?task=${encodeURIComponent(task.task_id)}`)}>Open task</button>
            </div>
            {task.error && <p className="jg-u-error">{task.error}</p>}
            {task.result != null ? <div className="jg-research__report"><Markdown text={resultText(task.result)} /></div>
              : <p className="jg-u-note">{isProposal(task) ? "Waiting for your approval." : "The report appears here when the task finishes."}</p>}
            {source.taskArtifacts && <><h3>Artifacts</h3><TaskArtifacts controls={source.taskArtifacts} taskId={task.task_id} /></>}
          </>)}
        </aside>
      </div>
    </div>
  );
}
