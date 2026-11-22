import { useEffect, useState } from 'react';
import { CHARACTERS } from '../components/CharacterLibrary';
import type { ModelInventory } from '../api/source';
import { GatewayClient } from '../api/gateway';
import { navigate } from '../shell/router';
import './first-run.css';

export interface FirstRunSetupBody {
  character_id: string;
  awake_provider: string;
  awake_model: string;
  display_name?: string;
  voice_profile?: 'female' | 'male';
  audio_input?: string;
  audio_output?: string;
  camera_device?: string;
  vision_enabled?: boolean;
  local_fallback_model?: string;
  autonomy?: 'ask' | 'scoped' | 'auto' | 'full';
  heartbeat_interval_minutes?: number;
  quiet_start_hour?: number;
  quiet_end_hour?: number;
  initial_goals?: Array<{ title: string; dimension: string; priority?: number }>;
}
export interface FirstRunStatus {
  status: string;
  completed: boolean;
  skipped: boolean;
  character_id: string | null;
  model_selection: unknown;
}
export interface FirstRunApi {
  status(): Promise<FirstRunStatus>;
  setup(body: FirstRunSetupBody): Promise<FirstRunStatus>;
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

type InventoryModel = ModelInventory['providers'][number]['models'][number];
function isSelectableFirstRunModel(item: InventoryModel): boolean {
  return item.available !== false && (!item.capabilities?.length || item.capabilities.includes('completion'));
}

export function FirstRunPage({ api, onDone }: { api: FirstRunApi; onDone: () => void }) {
  const [step, setStep] = useState(0);
  const [character, setCharacter] = useState('truth');
  const [provider, setProvider] = useState('');
  const [model, setModel] = useState('');
  const [inventory, setInventory] = useState<ModelInventory | null>(null);
  const [customized, setCustomized] = useState(false);
  const [displayName, setDisplayName] = useState('Truth');
  const [voiceProfile, setVoiceProfile] = useState<'female' | 'male'>('female');
  const [audioInput, setAudioInput] = useState('Insta360 Link 2');
  const [audioOutput, setAudioOutput] = useState('Mac Studio Speakers');
  const [cameraDevice, setCameraDevice] = useState('Insta360 Link 2');
  const [visionEnabled, setVisionEnabled] = useState(true);
  const [autonomy, setAutonomy] = useState<'ask' | 'scoped' | 'auto' | 'full'>('auto');
  const [heartbeatMinutes, setHeartbeatMinutes] = useState(30);
  const [quietStart, setQuietStart] = useState(22);
  const [quietEnd, setQuietEnd] = useState(7);
  const [goalTitle, setGoalTitle] = useState('');
  const [goalDimension, setGoalDimension] = useState('self_actualization');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (step !== 2 || inventory) return; let live = true; api.models().then((value) => { if (live) setInventory(value); }, (reason: unknown) => { if (live) setError(String((reason as Error)?.message ?? reason)); }); return () => { live = false; }; }, [api, step, inventory]);
  const providers = inventory?.providers
    .map((item) => ({ ...item, selectableModels: item.models.filter(isSelectableFirstRunModel) }))
    .filter((item) => item.reachable && item.configured && item.selectableModels.length > 0) ?? [];
  const selectedProvider = providers.find((item) => item.id === provider);
  async function complete() {
    setBusy(true); setError('');
    try {
      const payload: FirstRunSetupBody = { character_id: character, awake_provider: provider, awake_model: model };
      if (customized || goalTitle.trim()) {
        if (displayName.trim()) payload.display_name = displayName.trim();
        payload.voice_profile = voiceProfile;
        if (audioInput.trim()) payload.audio_input = audioInput.trim();
        if (audioOutput.trim()) payload.audio_output = audioOutput.trim();
        if (cameraDevice.trim()) payload.camera_device = cameraDevice.trim();
        payload.vision_enabled = visionEnabled;
        payload.autonomy = autonomy;
        payload.heartbeat_interval_minutes = heartbeatMinutes;
        payload.quiet_start_hour = quietStart;
        payload.quiet_end_hour = quietEnd;
        if (goalTitle.trim()) {
          payload.initial_goals = [{ title: goalTitle.trim(), dimension: goalDimension, priority: 2 }];
        }
      }
      const result = await api.setup(payload);
      if (!result.completed) throw Error('Setup did not complete. Please try again.');
      onDone();
    }
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
    {step === 0 && <><h1>Welcome to Jaeger</h1><p>Meet Truth — your persistent, truth-seeking personal intelligence. Its app and saved history live on your Mac. Your selected model may run locally or in the cloud.</p><button className="jg-first-run__primary" type="button" onClick={() => setStep(1)}>Get started</button></>}
    {step === 1 && <><h1>Pick your companion</h1><p>Truth is your default companion. You can keep Truth or pick another character and customize anytime.</p><div className="jg-first-run__characters" role="group" aria-label="Character">{CHARACTERS.map((item) => <button key={item.id} type="button" aria-pressed={character === item.id} onClick={() => { setCharacter(item.id); setDisplayName(item.name); }}><strong>{item.name}</strong><span>{item.role}</span></button>)}</div><div className="jg-first-run__actions"><button type="button" onClick={() => setStep(0)}>Back</button><button className="jg-first-run__primary" type="button" disabled={!character} onClick={() => { setError(''); setStep(2); }}>Choose character</button></div></>}
    {step === 2 && <><h1>Connect your models &amp; preferences</h1><p>Choose your primary model, and optionally configure Truth's identity, voice, camera, permissions, heartbeat, and personal goals.</p><label>Awake provider<select value={provider} onChange={(event) => { setProvider(event.target.value); setModel(''); }}><option value="">Choose a provider</option>{providers.map((item) => <option key={item.id} value={item.id}>{item.display_name}</option>)}</select></label><label>Awake model<select value={model} disabled={!selectedProvider} onChange={(event) => setModel(event.target.value)}><option value="">Choose a model</option>{selectedProvider?.selectableModels.map((item) => <option key={item.id} value={item.id}>{item.id}</option>)}</select></label>{inventory && providers.length === 0 && <p>No reachable models are configured. Connect a model in Settings or skip setup for now.</p>}<details className="jg-first-run__prefs"><summary>Personalize Truth (identity, voice, camera, permissions, heartbeat &amp; goals)</summary><label>Companion display name<input type="text" aria-label="Companion display name" value={displayName} onChange={(e) => { setCustomized(true); setDisplayName(e.target.value); }} /></label><label>Voice profile<select aria-label="Voice profile" value={voiceProfile} onChange={(e) => { setCustomized(true); setVoiceProfile(e.target.value as 'female' | 'male'); }}><option value="female">Female (af_heart)</option><option value="male">Male (am_michael)</option></select></label><label>Microphone<input type="text" aria-label="Microphone" value={audioInput} onChange={(e) => { setCustomized(true); setAudioInput(e.target.value); }} /></label><label>Speakers<input type="text" aria-label="Speakers" value={audioOutput} onChange={(e) => { setCustomized(true); setAudioOutput(e.target.value); }} /></label><label>Camera<input type="text" aria-label="Camera" value={cameraDevice} onChange={(e) => { setCustomized(true); setCameraDevice(e.target.value); }} /></label><label><input type="checkbox" aria-label="Enable local vision" checked={visionEnabled} onChange={(e) => { setCustomized(true); setVisionEnabled(e.target.checked); }} /> Enable local vision (qwen3.5:9b)</label><label>Operating mode<select aria-label="Operating mode" value={autonomy} onChange={(e) => { setCustomized(true); setAutonomy(e.target.value as 'ask' | 'scoped' | 'auto' | 'full'); }}><option value="ask">Ask for approval</option><option value="scoped">Approve for me</option><option value="auto">Automatic</option><option value="full">Full access</option></select></label><label>Heartbeat interval (minutes)<input type="number" aria-label="Heartbeat interval (minutes)" min={5} max={240} value={heartbeatMinutes} onChange={(e) => { setCustomized(true); setHeartbeatMinutes(Number(e.target.value) || 30); }} /></label><label>Quiet hours start (0-23)<input type="number" aria-label="Quiet hours start" min={0} max={23} value={quietStart} onChange={(e) => { setCustomized(true); setQuietStart(Number(e.target.value)); }} /></label><label>Quiet hours end (0-23)<input type="number" aria-label="Quiet hours end" min={0} max={23} value={quietEnd} onChange={(e) => { setCustomized(true); setQuietEnd(Number(e.target.value)); }} /></label><label>First personal goal (optional)<input type="text" aria-label="First personal goal" placeholder="e.g. Maintain daily focus and exercise routine" value={goalTitle} onChange={(e) => { setCustomized(true); setGoalTitle(e.target.value); }} /></label><label>Goal focus area<select aria-label="Goal focus area" value={goalDimension} onChange={(e) => { setCustomized(true); setGoalDimension(e.target.value); }}><option value="physiological">Health &amp; Energy</option><option value="safety_stability">Safety &amp; Stability</option><option value="belonging_relationships">Relationships &amp; Belonging</option><option value="competence_esteem">Competence &amp; Mastery</option><option value="self_actualization">Growth &amp; Purpose</option><option value="meaning_contribution">Contribution &amp; Impact</option></select></label></details><div className="jg-first-run__actions"><button type="button" disabled={busy} onClick={() => setStep(1)}>Back</button><button className="jg-first-run__primary" type="button" disabled={busy || !provider || !model} onClick={() => void complete()}>{busy ? 'Saving…' : 'Connect models'}</button></div></>}
    {error && <p role="alert" className="jg-first-run__error">{error}</p>}
  </section></main>;
}
