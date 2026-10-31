/**
 * Settings → Providers: subscription CLIs Jaeger can run without API keys (Codex, Claude Code,
 * Cursor agent, Gemini) plus Ollama local/cloud guidance. Detection runs each CLI's own status
 * command; Jaeger never reads their credentials and never signs in for you.
 */
import { useCallback, useEffect, useState } from "react";
import { CLI_STATE, loadCliProviders, loadModels, updateCliProvider, isCloud, type CliProvider, type LocalModel } from "../unified/models";
import { Badge, SkeletonRows } from "../unified/ui";

export function ProvidersPanel() {
  const [ps, setPs] = useState<CliProvider[] | null>(null);
  const [err, setErr] = useState<string>();
  const [ollama, setOllama] = useState<{ models?: LocalModel[]; error?: string }>({});
  const [saving, setSaving] = useState<string>();
  const load = useCallback((refresh = false) => loadCliProviders(refresh).then((r) => { setPs(r.providers); setErr(undefined); }, (e: Error) => setErr(e.message)), []);
  useEffect(() => { void load(); loadModels().then((r) => setOllama({ models: r.models }), (e: Error) => setOllama({ error: e.message })); }, [load]);
  const save = async (p: CliProvider, body: { enabled?: boolean; models?: string[] }) => {
    setSaving(p.id);
    try { const next = await updateCliProvider(p.id, body); setPs((xs) => xs?.map((x) => (x.id === p.id ? next : x)) ?? null); }
    catch (e) { setErr(`${p.label}: ${(e as Error).message}`); }
    finally { setSaving(undefined); }
  };
  const localN = ollama.models?.filter((m) => !isCloud(m)).length ?? 0;
  const cloudN = ollama.models?.filter(isCloud).length ?? 0;
  return (
    <div className="jg-prov">
      <section className="jg-sheet__section">
        <div className="jg-prov__head"><h3 className="jg-sheet__section-title">Subscription CLIs</h3>
          <button type="button" className="jg-u-btn" onClick={() => { setPs(null); void load(true); }}>Re-check</button></div>
        <p className="jg-u-note">Jaeger runs these apps the way you would in Terminal, using the account you're already signed in with. No API keys, and Jaeger never reads or copies their credentials.</p>
        {err && <p className="jg-u-error" role="alert">{err}</p>}
        {!ps ? <SkeletonRows n={4} /> : ps.map((p) => {
          const [tone, text] = CLI_STATE[p.state];
          return (
            <article key={p.id} className="jg-u-card jg-prov__card" aria-label={p.label} data-state={p.state}>
              <header>
                <strong>{p.label}</strong> <Badge tone={tone}>{text}</Badge>
                <label className="jg-u-check jg-prov__toggle"><input type="checkbox" role="switch" aria-label={`Use ${p.label}`} checked={p.enabled} disabled={!p.installed || saving === p.id} onChange={(e) => void save(p, { enabled: e.target.checked })} /> Use</label>
              </header>
              <dl className="jg-ui-kv">
                <dt>Path</dt><dd><code>{p.path ?? "–"}</code></dd>
                <dt>Version</dt><dd>{p.version ?? "–"}</dd>
                <dt>Account</dt><dd>{p.status_note}</dd>
                {p.last_error && <><dt>Last run</dt><dd className="jg-u-error">{p.last_error}</dd></>}
              </dl>
              {p.state === "needs-sign-in" && <p className="jg-u-note">Sign in yourself in Terminal: <code>{p.login_command}</code>, then press Re-check.</p>}
              {p.state === "not-installed" && <p className="jg-u-note">Install the {p.label} CLI, sign in, then press Re-check.</p>}
              {p.models.length > 0 && (
                <fieldset className="jg-prov__models" disabled={!p.enabled || saving === p.id}>
                  <legend>Models to offer in Compare</legend>
                  {p.models.map((m) => (
                    <label key={m.id} className="jg-u-check"><input type="checkbox" checked={p.selected_models.includes(m.id)}
                      onChange={(e) => void save(p, { models: e.target.checked ? [...p.selected_models, m.id] : p.selected_models.filter((x) => x !== m.id) })} /> {m.label}{m.context ? <small> · {Math.round(m.context / 1000)}K</small> : null}</label>))}
                </fieldset>)}
              {p.streams === "messages" && p.installed && <p className="jg-u-note">This CLI sends whole messages rather than tokens, so Compare shows its answer when each message finishes and no tokens-per-second figure.</p>}
            </article>);
        })}
      </section>
      <section className="jg-sheet__section">
        <h3 className="jg-sheet__section-title">Ollama</h3>
        <article className="jg-u-card jg-prov__card" aria-label="Ollama local">
          <header><strong>Ollama on this Mac</strong> {ollama.error ? <Badge tone="bad">Not running</Badge> : ollama.models ? <Badge tone="ok">{localN} local models</Badge> : null}</header>
          <p className="jg-u-note">Runs models on this Mac's GPU, free and offline. Start it with <code>ollama serve</code> (or the Ollama app), then pull models from Models → Pull.</p>
        </article>
        <article className="jg-u-card jg-prov__card" aria-label="Ollama cloud">
          <header><strong>Ollama Cloud</strong> {ollama.models ? <Badge tone={cloudN ? "ok" : undefined}>{cloudN ? `${cloudN} cloud models` : "None added"}</Badge> : null}</header>
          <p className="jg-u-note">Large models hosted by Ollama, run through the same local Ollama with your Ollama account. No key in Jaeger: sign in once in Terminal with <code>ollama signin</code>, then pull a cloud tag such as <code>glm-5.3:cloud</code>.</p>
        </article>
      </section>
    </div>
  );
}
