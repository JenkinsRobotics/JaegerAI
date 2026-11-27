// Jaeger AI's NexusUI screen, copied from Omni's, in the NexusUI app shell (app-shell/: Aether Studio's sidebar, no header).
// Chat: the avatar (Jaeger Avatar's flat face in Jaeger's own frozen look, speaking with Jaeger Agent's Kokoro voice)
// beside the chat, which runs on the Gateway. The other pages are the Swift app's native surfaces (INVENTORY.md).
// `#pill` is Quick Ask.
import { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './aether-tokens.css';
import './app.css';
import { health, hear, interrupt, listen, loadConfig, newChat, pending, say, type Config, type Health } from './agent.ts';
import { attach } from './attach.ts';
import { recordClip } from './mic.ts';
import { empty, onEvent, sent, type AgentEvent, type Chat as ChatState } from './chat.ts';
import { Chat } from './Chat.tsx';
import { Settings, Shell } from './Shell.tsx';
import { Stage } from './Stage.tsx';
import { moodFor } from './mood.ts';
import { voice } from './voice.ts';
import { AppShell, type ShellSection } from './app-shell/AppShell.tsx';

const speaker = voice();   // her voice: each reply's sound, played here; the face's mouth follows its loudness
type Seen = { at: string; kind: string; text: string };
const PILL = location.hash === '#pill';
const SECTIONS: ShellSection[] = [
  { id: 'workspace', title: 'Workspace', items: [{ id: 'chat', label: 'Chat', icon: 'comment' }, { id: 'activity', label: 'Activity', icon: 'history' }] },
  { id: 'mac', title: 'Mac shell', items: [{ id: 'status', label: 'Status & stack', icon: 'dashboard' }, { id: 'tasks', label: 'Tasks', icon: 'tasks' },
    { id: 'droid', label: 'Droid', icon: 'hardware' }, { id: 'mac', label: 'Mac', icon: 'display' }] },
];

function useAgent() {
  const [chat, setChat] = useState<ChatState>(empty);
  const [seen, setSeen] = useState<Seen[]>([]);
  const [mic, setMic] = useState(false);
  const [mood, setMood] = useState('neutral');
  const stopMic = useRef<(() => Promise<string>) | null>(null);
  useEffect(() => listen((e: AgentEvent & { pcm?: string; rate?: number }) => {
    setChat(c => onEvent(c, e));
    const m = moodFor({ ...e, text: e.text?.toLowerCase() }, 'neutral');
    if (m) setMood(m);
    if (e.event === 'voice' && e.pcm && e.rate) {   // her reply, spoken: the mouth moves while it plays, then she rests
      speaker.play(e.pcm, e.rate);
      void speaker.idle().then(() => setMood('neutral'));
    }
    if (e.event && !['delta', 'assistant', 'user', 'reset', 'voice'].includes(e.event))
      setSeen(s => (s[0]?.kind === e.event && s[0]?.text === (e.text ?? '') ? s   // one line per stretch of thinking, not per token
        : [{ at: new Date().toLocaleTimeString(), kind: e.event!, text: e.text ?? '' }, ...s].slice(0, 80)));
  }), []);
  const note = (text: string) => setChat(c => onEvent(onEvent(c, { event: 'status', text: `error: ${text}` }), { event: 'done' }));
  const send = (text: string) => { setChat(c => sent(c, text)); say(text).catch(e => note(e.message)); };
  const heard = (pcm: string) => {
    setChat(c => ({ ...c, busy: true, status: 'Hearing you' }));
    hear(pcm).then(t => { if (!t) note('nothing was heard'); }, e => note(e.message));
  };
  return {
    chat, seen, mic, mood, send,
    stop: () => { speaker.stop(); interrupt(); },
    fresh: () => newChat().catch(e => note(e.message)),
    file: async (f: File) => {
      const got = await attach(f).catch(() => []);
      const clip = got.find(a => a.kind === 'sound');
      if (clip) heard(clip.data); else note(`${f.name}: the Gateway takes text, text files and sound clips only`);
    },
    toggleMic: async () => {
      if (!stopMic.current && speaker.playing()) return note('she is speaking: the mic opens when she is done (half duplex)');
      if (stopMic.current) { const done = stopMic.current; stopMic.current = null; setMic(false); return heard(await done()); }
      try { stopMic.current = await recordClip(); setMic(true); } catch (err) { note(`no microphone (${(err as Error).message})`); }
    },
  };
}

function App() {
  const [cfg, setCfg] = useState<Config | null>(null);
  const [h, setH] = useState<Health | null>(null);
  const [page, setPage] = useState('chat');
  const a = useAgent();
  useEffect(() => { loadConfig().then(c => { setCfg(c); document.title = PILL ? 'Ask Jaeger' : c.title; }); }, []);
  useEffect(() => {
    const tick = () => { health().then(setH); if (!PILL) pending().then(p => { if (p.destination) setPage(p.destination.target === 'notifications' ? 'tasks' : 'chat'); }); };
    tick(); const t = setInterval(tick, 3000); return () => clearInterval(t);
  }, []);
  if (!cfg) return <div className="loading">Loading…</div>;

  const chat = <Chat name={cfg.name} chat={a.chat} suggestions={cfg.suggestions} mic={a.mic} compact={PILL}
    onSend={a.send} onStop={a.stop} onNew={a.fresh} onMic={a.toggleMic} onFile={a.file} />;
  if (PILL) return <div className="pill-app"><div className="pill-orb"><span className={`dot ${a.chat.busy ? 'busy' : h?.ready ? 'ok' : ''}`} /></div>{chat}</div>;

  const agent = (
    <div className="agentic">
      <h3>Agent</h3>
      <dl>
        <dt>Brain</dt><dd>{h?.brain ?? '—'}</dd>
        <dt>Gateway</dt><dd>{cfg.gateway}</dd>
        <dt>Session</dt><dd>{h?.session ?? '—'}</dd>
        <dt>Hearing</dt><dd>{h?.hearing ?? '—'}</dd>
        <dt>Voice</dt><dd>{h?.voice ?? '—'}</dd>
        {h?.why ? <><dt>Why</dt><dd>{h.why}</dd></> : null}
      </dl>
      <h3>Activity</h3>
      <ol className="activity">{a.seen.length ? a.seen.map((s, i) => <li key={i}><time>{s.at}</time><b>{s.kind}</b> {s.text}</li>) : <li className="dim">Nothing yet.</li>}</ol>
    </div>
  );
  const stage = <section className="pane stage avatar"><Stage look={cfg.face} mood={a.mood} level={speaker.level} />
    <div className="voice-line"><span className={`dot ${h?.voice && !h.voice.startsWith('no voice') ? 'ok' : ''}`} />{h?.voice ?? 'Voice: —'}</div></section>;
  const body = page === 'chat' ? <>{stage}<section className="pane">{chat}</section></>
    : <section className="pane page">{page === 'activity' ? agent : page === 'settings' ? <Settings /> : <Shell webui={cfg.webui} only={page} />}</section>;

  const up = h?.ready ? 'connected' as const : 'offline' as const;
  return (
    <AppShell id="jaeger-ai" brand={{ name: 'Jaeger', suffix: 'AI', mark: 'jaeger-mark.svg' }} sections={SECTIONS} current={page} onSelect={setPage}
      tools={[{ id: 'webui', label: 'Main screen (WebUI)', icon: 'link', href: cfg.webui }]}
      settings={{ id: 'settings', label: 'Settings', icon: 'settings' }}
      profile={{ name: cfg.name, detail: h?.brain ?? 'Connecting…', avatar: 'jaeger-mark.svg', connection: up }}
      status={{ name: cfg.title, connection: up, message: h?.voice ?? '', company: cfg.company }}>
      <div className={`panes ${page === 'chat' ? 'avatar-chat' : 'one'}`}>{body}</div>
    </AppShell>
  );
}

createRoot(document.getElementById('root')!).render(<App />);
