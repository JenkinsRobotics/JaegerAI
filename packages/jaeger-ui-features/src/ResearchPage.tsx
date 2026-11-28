import { useState, type FormEvent } from "react";

interface ResearchPlan {
  phases: Array<{
    phase: number;
    name: string;
    steps: string[];
    heavy_model: string | null;
    estimated_ram_gb: number;
  }>;
}

export function ResearchPage({ baseUrl }: { baseUrl: string }) {
  const [source, setSource] = useState("");
  const [plan, setPlan] = useState<ResearchPlan>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!source.trim() || busy) return;
    setBusy(true);
    setError("");
    setPlan(undefined);
    try {
      const response = await fetch(`${baseUrl}/v1/youtube/research/plan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source: source.trim() }),
      });
      if (!response.ok) throw new Error(`Gateway returned HTTP ${response.status}`);
      const data = await response.json() as { plan?: ResearchPlan };
      if (!Array.isArray(data.plan?.phases)) throw new Error("Gateway returned no research phases");
      setPlan(data.plan);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Unable to build a research plan");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="jg-content jg-workspace-page">
      <form className="jg-card jg-workspace-page" onSubmit={(event) => void submit(event)}>
        <h2 style={{ margin: 0 }}>YouTube Research Planner</h2>
        <label htmlFor="research-source">YouTube video or playlist URL</label>
        <input id="research-source" className="jg-input" type="url" value={source} required
          onChange={(event) => setSource(event.target.value)} />
        <button type="submit" className="jg-btn jg-btn-primary" disabled={busy || !source.trim()}>
          {busy ? "Planning…" : "Build Research Plan"}
        </button>
      </form>
      {error && <p role="alert">{error}</p>}
      {plan?.phases.map((phase) => (
        <section className="jg-card" key={phase.phase}>
          <h3>{phase.name}</h3>
          <p>{phase.heavy_model ?? "CPU"} · {phase.estimated_ram_gb} GB estimated</p>
          <ul>{phase.steps.map((step) => <li key={step}>{step}</li>)}</ul>
        </section>
      ))}
    </div>
  );
}
