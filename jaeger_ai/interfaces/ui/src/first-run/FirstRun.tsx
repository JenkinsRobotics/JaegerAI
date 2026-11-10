import { useEffect, useState } from 'react';
import { CHARACTERS } from '../components/CharacterLibrary';
import type { ModelInventory } from '../api/source';
import { GatewayClient } from '../api/gateway';
import { navigate } from '../shell/router';
import './first-run.css';

export interface FirstRunStatus {
  status: string;
  completed: boolean;
  skipped: boolean;
  character_id: string | null;
  model_selection: unknown;
}
export interface FirstRunApi {
  status(): Promise<FirstRunStatus>;
  setup(body: { character_id: string; awake_provider: string; awake_model: string }): Promise<FirstRunStatus>;
  skip(): Promise<FirstRunStatus>;
  models(): Promise<ModelInventory>;
}
export function firstRunApi(client: GatewayClient): FirstRunApi {
  return {
    status: () => client.json('/v1/first-run'),
    setup: (body) => client.json('/v1/first-run/setup', body),
    skip: () => client.json('/v1/first-run/skip', {}),
    models: () => client.modelSettings.inventory(),
  };
}

export function FirstRunGate({ api, children }: { api: FirstRunApi | null; children: React.ReactNode }) {
  const [status, setStatus] = useState<FirstRunStatus | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    if (!api) return;
    let live = true;
    api.status().then((value) => {
      if (!live) return;
      setStatus(value);
      if (!value.completed && (location.pathname === '/' || location.pathname === '/home')) navigate('/first-run', { replace: true });
      if (value.completed && location.pathname === '/first-run') navigate('/', { replace: true });
    }, (reason: unknown) => { if (live) setError(String((reason as Error)?.message ?? reason)); });
    return () => { live = false; };
  }, [api]);
  if (!api) return <>{children}</>;
  // Fail open: an older Gateway (no /v1/first-run) or a transient error must never lock the whole app.
  if (error && !status) { if (location.pathname !== '/first-run') return <>{children}</>; return <main className="jg-first-run"><div className="jg-first-run__panel" role="alert"><h1>Welcome to Jaeger</h1><p>First-run status could not be loaded: {error}</p><button onClick={() => location.reload()}>Try again</button></div></main>; }
  if (!status) return <main className="jg-first-run" aria-busy="true"><p>Loading Jaeger…</p></main>;
  if (location.pathname === '/first-run' && !status.completed) return <FirstRunPage api={api} onDone={() => { setStatus({ ...status, completed: true }); navigate('/', { replace: true }); }} />;
  return <>{children}</>;
}

export function FirstRunPage({ api, onDone }: { api: FirstRunApi; onDone: () => void }) {
  const [step, setStep] = useState(0);
  const [character, setCharacter] = useState('');
  const [provider, setProvider] = useState('');
  const [model, setModel] = useState('');
  const [inventory, setInventory] = useState<ModelInventory | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (step !== 2 || inventory) return; let live = true; api.models().then((value) => { if (live) setInventory(value); }, (reason: unknown) => { if (live) setError(String((reason as Error)?.message ?? reason)); }); return () => { live = false; }; }, [api, step, inventory]);
  const providers = inventory?.providers.filter((item) => item.reachable && item.configured && item.models.length) ?? [];
  const selectedProvider = providers.find((item) => item.id === provider);
  async function complete() {
    setBusy(true); setError('');
    try { const result = await api.setup({ character_id: character, awake_provider: provider, awake_model: model }); if (!result.completed) throw Error('Setup did not complete. Please try again.'); onDone(); }
    catch (reason) { setError(String((reason as Error)?.message ?? reason)); }
    finally { setBusy(false); }
  }
  async function skip() {
    setBusy(true); setError('');
    try { const result = await api.skip(); if (!result.completed) throw Error('Skip did not complete. Please try again.'); onDone(); }
    catch (reason) { setError(String((reason as Error)?.message ?? reason)); }
    finally { setBusy(false); }
  }
  return <main className="jg-first-run"><section className="jg-first-run__panel" aria-label="First-run setup">
    <header><span className="jg-first-run__eyebrow">JAEGER · SETUP {step + 1} / 3</span><button className="jg-first-run__skip" type="button" disabled={busy} onClick={() => void skip()}>Skip setup</button></header>
    {step === 0 && <><h1>Welcome to Jaeger</h1><p>Jaeger is your own agent. Its app and saved history live on your Mac. Your selected model may run locally or in the cloud.</p><button className="jg-first-run__primary" type="button" onClick={() => setStep(1)}>Get started</button></>}
    {step === 1 && <><h1>Pick your companion</h1><p>Choose the character Jaeger will speak and act as. This changes how it talks, not what it can do. You can change it later.</p><div className="jg-first-run__characters" role="group" aria-label="Character">{CHARACTERS.map((item) => <button key={item.id} type="button" aria-pressed={character === item.id} onClick={() => setCharacter(item.id)}><strong>{item.name}</strong><span>{item.role}</span></button>)}</div><div className="jg-first-run__actions"><button type="button" onClick={() => setStep(0)}>Back</button><button className="jg-first-run__primary" type="button" disabled={!character} onClick={() => { setError(''); setStep(2); }}>Choose character</button></div></>}
    {step === 2 && <><h1>Connect your models</h1><p>Choose a configured cloud provider or an optional local model. Local model weights are only needed when you choose on-device inference.</p><label>Awake provider<select value={provider} onChange={(event) => { setProvider(event.target.value); setModel(''); }}><option value="">Choose a provider</option>{providers.map((item) => <option key={item.id} value={item.id}>{item.display_name}</option>)}</select></label><label>Awake model<select value={model} disabled={!selectedProvider} onChange={(event) => setModel(event.target.value)}><option value="">Choose a model</option>{selectedProvider?.models.filter((item) => item.available !== false && item.usable_for_react !== false).map((item) => <option key={item.id} value={item.id}>{item.id}</option>)}</select></label>{inventory && providers.length === 0 && <p>No reachable models are configured. Connect a model in Settings or skip setup for now.</p>}<div className="jg-first-run__actions"><button type="button" disabled={busy} onClick={() => setStep(1)}>Back</button><button className="jg-first-run__primary" type="button" disabled={busy || !provider || !model} onClick={() => void complete()}>{busy ? 'Saving…' : 'Connect models'}</button></div></>}
    {error && <p role="alert" className="jg-first-run__error">{error}</p>}
  </section></main>;
}
