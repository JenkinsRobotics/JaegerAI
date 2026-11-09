import { useEffect, useRef, useState } from 'react';
import type { JaegerSource } from '../api/source';
import type { Agent, Handoff, SessionRow } from '../api/types';
import { BrowserWorkspace } from '../browser/BrowserWorkspace';
import { Globe, Bot, FileText, FolderOpen, MessageSquare, Plus, Terminal, X } from '../components/Icons';
import { ChatPane } from '../chat/ChatPane';
import { WebHost } from '../chat/webHost';
import { SessionFiles } from '../chat/SessionFiles';
import { TaskArtifacts } from '../library/TaskArtifacts';
import { LibraryPanel } from '../library/LibraryPanel';
import { AutomationsPanel } from '../automations/AutomationsPanel';
import { WorkspaceBrowser } from '../unified/WorkspaceBrowser';
import { sendJson } from '../unified/webui';

export type WorkView = 'browser' | 'tools' | 'changes' | 'files' | 'sources' | 'subagents' | 'outputs' | 'page' | 'automations' | 'sidechat' | 'terminal';
const titles: Record<WorkView, string> = { browser: 'Browser', tools: 'New tab', changes: 'Changes', files: 'Files', sources: 'Sources', subagents: 'Subagents', outputs: 'Outputs', page: 'Pages', automations: 'Scheduled tasks', sidechat: 'Side chat', terminal: 'Terminal' };

export function ConversationWorkPanel({ source, sessionId, agents, recent, open, view, onView, onClose, onConversation, onResize }: {
  source: JaegerSource; sessionId: string; agents: Agent[]; recent: SessionRow[]; open: boolean; view: WorkView; onView(view: WorkView): void; onClose(): void; onConversation(id: string): void; onResize?(width: number): void;
}) {
  const [tabs, setTabs] = useState<WorkView[]>(['tools']);
  useEffect(() => { setTabs(rows => rows.includes(view) ? rows : [...rows, view]); }, [view]);
  const openTab = (next: WorkView) => { setTabs(rows => rows.includes(next) ? rows : [...rows, next]); onView(next); };
  const closeTab = (tab: WorkView) => { const next = tabs.filter(row => row !== tab); setTabs(next); if (view === tab) onView(next.at(-1) || 'tools'); };
  return <aside id="jaeger-work-panel" hidden={!open} className="jg-stable-demo__inspector jg-conversation-work" aria-label="Tools workspace">
    <div className="jg-conversation-work__resize" role="separator" aria-label="Resize tools workspace" aria-orientation="vertical" tabIndex={0}
      onPointerDown={event => {
        if (event.button !== 0 || !onResize) return;
        event.preventDefault(); event.currentTarget.focus(); event.currentTarget.setPointerCapture(event.pointerId);
      }}
      onPointerMove={event => { if (event.currentTarget.hasPointerCapture(event.pointerId)) onResize?.(event.currentTarget.parentElement!.getBoundingClientRect().right - event.clientX); }}
      onPointerUp={event => { if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId); }}
      onKeyDown={event => { if (['ArrowLeft','ArrowRight'].includes(event.key)) { event.preventDefault(); onResize?.(event.currentTarget.parentElement!.clientWidth + (event.key === 'ArrowLeft' ? 24 : -24)); } }} />
    <header hidden={view === "browser"} className="jg-conversation-work__tabbar"><div role="tablist" aria-label="Workspace tabs">{tabs.map(tab => <span key={tab}><button id={`work-tab-${tab}`} type="button" role="tab" aria-controls={`work-view-${tab}`} aria-selected={view === tab} onClick={() => onView(tab)}>{titles[tab]}</button>{tab !== 'tools' && <button type="button" aria-label={`Close ${titles[tab]} tab`} onClick={() => closeTab(tab)}><X size={13} /></button>}</span>)}</div><button type="button" aria-label="New tool tab" onClick={() => openTab('tools')}><Plus size={18} /></button><button type="button" aria-label="Close work panel" onClick={onClose}><X size={18} /></button></header>
    {tabs.map(tab => <section key={tab} id={`work-view-${tab}`} role="tabpanel" aria-labelledby={`work-tab-${tab}`} hidden={view !== tab} className={`jg-conversation-work__content jg-conversation-work__content--${tab}`}>
      {tab === 'tools' && <><h2>Tools</h2><div className="jg-conversation-work__launcher">{([
        ['browser', 'Browser', Globe], ['changes', 'Changes', FileText], ['terminal', 'Terminal', Terminal], ['files', 'Files', FolderOpen], ['sidechat', 'Side chat', MessageSquare], ['page', 'New page', FileText],
      ] as const).map(([id, label, Icon]) => <button type="button" key={id} onClick={() => openTab(id)}><Icon size={19} />{label}</button>)}</div><h2>Suggested</h2><div className="jg-conversation-work__suggested">{recent.filter(row => !row.archived && row.session_id !== sessionId).slice(0, 4).map(row => <button type="button" key={row.session_id} onClick={() => onConversation(row.session_id)}><span><MessageSquare size={22} /></span><strong>{row.title || 'Untitled conversation'}</strong></button>)}{!recent.some(row => row.session_id !== sessionId) && <p>Your other conversations will appear here.</p>}</div></>}
      {(tab === 'files' || tab === 'changes') && (sessionId ? <WorkspaceBrowser source={source} params={new URLSearchParams({ session: sessionId, view: tab })} /> : <p>Start a conversation to browse its workspace and Git changes.</p>)}
      {tab === 'outputs' && (source.taskArtifacts ? <TaskArtifacts controls={source.taskArtifacts} sessionId={sessionId || undefined} /> : <p>Artifacts are unavailable on this Gateway.</p>)}
      {tab === 'sources' && (sessionId ? <ConversationSources key={sessionId} source={source} sessionId={sessionId} /> : <p>Choose a conversation to see its sources.</p>)}
      {tab === 'subagents' && <ConversationWorkers key={sessionId} source={source} sessionId={sessionId} agents={agents} />}
      {tab === 'page' && (source.library ? <LibraryPanel controls={source.library} initialNew /> : <p>Pages are unavailable on this Gateway.</p>)}
      {tab === 'automations' && (source.schedules ? <AutomationsPanel controls={source.schedules} initialNew /> : <p>Scheduled tasks are unavailable on this Gateway.</p>)}
      {tab === 'sidechat' && <SideChat source={source} agents={agents} parentSession={sessionId} />}
      {tab === 'browser' && <BrowserWorkspace key={sessionId} sessionId={sessionId} source={source} onClosePanel={onClose}
        workspaceTabs={tabs.filter(id => id !== 'browser').map(id => <div key={id} className="codex-ui-browser-workspace__tab-shell">
          <button type="button" className="codex-ui-browser-workspace__tab" role="tab" aria-selected={false} onClick={() => onView(id)}>{id === "tools" ? "Tools" : titles[id]}</button>
          {id !== 'tools' && <button type="button" className="codex-ui-browser-workspace__tab-close" aria-label={`Close ${titles[id]} tab`} onClick={() => closeTab(id)}><X size={13}/></button>}
        </div>)} />}
      {tab === 'terminal' && <SessionTerminal key={sessionId} sessionId={sessionId} live={source.kind === 'live'} />}
    </section>)}
  </aside>;
}

function ConversationSources({ source, sessionId }: { source: JaegerSource; sessionId: string }) {
  const [revision, setRevision] = useState(0), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const upload = async (file: File) => {
    if (!source.uploadAttachment || busy) return;
    if (file.size > 25 * 1024 * 1024) { setError('Choose a file smaller than 25 MB.'); return; }
    setBusy(true); setError('');
    try {
      const data = await new Promise<string>((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(',')[1]); reader.onerror = () => reject(Error('File could not be read')); reader.readAsDataURL(file); });
      await source.uploadAttachment(sessionId, { name: file.name, mime: file.type || 'application/octet-stream', data_base64: data }, crypto.randomUUID()); setRevision(n => n + 1);
    } catch (e) { setError(String((e as Error).message || e)); }
    finally { setBusy(false); }
  };
  return <><h2>Sources</h2>{source.uploadAttachment && <label className="jg-conversation-work__upload"><Plus size={18} />{busy ? 'Adding source…' : 'Add source'}<input aria-label="Add source file" type="file" disabled={busy} onChange={event => { const file = event.target.files?.[0]; if (file) void upload(file); event.target.value = ''; }} /></label>}{error && <p role="alert">{error}</p>}{source.sessionFiles ? <SessionFiles key={revision} files={source.sessionFiles} sessionId={sessionId} onClose={() => {}} /> : <p>Sources are unavailable on this Gateway.</p>}</>;
}
function ConversationWorkers({ source, sessionId, agents }: { source: JaegerSource; sessionId: string; agents: Agent[] }) {
  const [rows, setRows] = useState<Handoff[]>(), [error, setError] = useState('');
  useEffect(() => { let live = true; if (!sessionId) return; void source.handoffs({ session_id: sessionId }).then(result => { if (live) setRows(result.filter(row => row.session_id === sessionId)); }, e => { if (live) setError(String(e)); }); return () => { live = false; }; }, [source, sessionId]);
  return <><h2>Subagents</h2>{error && <p role="alert">{error}</p>}{!sessionId ? <p>Choose a conversation.</p> : !rows ? <p>Loading…</p> : !rows.length ? <p>No subagents in this conversation.</p> : rows.map(row => <article key={row.id}><h3><Bot size={18} />{agents.find(agent => agent.id === row.to_agent_id)?.display_name || row.to_agent_id}</h3><p>{row.status || 'Status unknown'}</p><p>{row.task}</p>{row.result?.summary && <p>{row.result.summary}</p>}</article>)}</>;
}
function SideChat({ source, agents, parentSession }: { source: JaegerSource; agents: Agent[]; parentSession: string }) {
  const [session, setSession] = useState(''), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const host = useRef<WebHost | null>(null);
  if (!host.current) host.current = new WebHost(source);
  const start = async () => { if (busy) return; setBusy(true); setError(''); try { const row = await source.createSession({ agent_id: 'native:jaeger', title: 'Side chat' }); setSession(row.session_id); } catch (e) { setError(String(e)); } finally { setBusy(false); } };
  return session ? <ChatPane host={host.current} sessionId={session} agents={agents} /> : <div className="jg-conversation-work__side-empty"><MessageSquare size={28} /><h2>Side chat</h2><p>Start a separate conversation alongside your current chat. It has its own saved history.</p>{parentSession && <small>Your main conversation stays open.</small>}{error && <p role="alert">{error}</p>}<button type="button" disabled={busy} onClick={() => void start()}>{busy ? 'Opening…' : 'Start side chat'}</button></div>;
}
/** Uses the existing authenticated WebUI PTY; no shell is started until the operator connects. */
function SessionTerminal({ sessionId, live }: { sessionId: string; live: boolean }) {
  const [connected, setConnected] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState(''), [output, setOutput] = useState(''), [input, setInput] = useState('');
  useEffect(() => {
    if (!connected) return;
    const stream = new EventSource(`/api/terminal/output?session_id=${encodeURIComponent(sessionId)}`, { withCredentials: true });
    stream.addEventListener('output', event => { try { const row = JSON.parse((event as MessageEvent).data); if (typeof row.text === 'string') setOutput(text => (text + row.text).slice(-100000)); } catch { setError('Invalid terminal output'); } });
    stream.addEventListener('terminal_closed', () => { setConnected(false); stream.close(); });
    stream.addEventListener('terminal_error', () => { setError('Terminal reported an error.'); stream.close(); setConnected(false); });
    stream.onerror = () => { setError('Terminal connection interrupted. Reconnect to the existing shell.'); stream.close(); setConnected(false); };
    return () => stream.close();
  }, [connected, sessionId]);
  const connect = async () => { if (busy) return; setBusy(true); setError(''); try { const row = await sendJson<{session_id: string; running: boolean}>('POST', '/api/terminal/start', { session_id: sessionId, rows: 24, cols: 80 }); if (row.session_id !== sessionId || !row.running) throw Error('Terminal was not started for this conversation'); setConnected(true); } catch (e) { setError(String((e as Error).message || e)); } finally { setBusy(false); } };
  const send = async (data: string) => { if (busy) return; setBusy(true); setError(''); try { await sendJson('POST', '/api/terminal/input', { session_id: sessionId, data }); setInput(''); } catch (e) { setError(String(e)); } finally { setBusy(false); } };
  return <><h2>Terminal</h2><p>Operator shell in this conversation’s workspace.</p>{error && <p role="alert">{error}</p>}{!connected && <button type="button" disabled={!sessionId || !live || busy} onClick={() => void connect()}>{busy ? 'Connecting…' : 'Connect terminal'}</button>}{output && <pre className="jg-conversation-work__terminal" aria-label="Terminal output">{output.replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, '')}</pre>}{connected && <form onSubmit={event => { event.preventDefault(); void send(input + '\n'); }}><label>Command<input aria-label="Terminal command" value={input} maxLength={8000} onChange={event => setInput(event.target.value)} /></label><button disabled={busy || !input}>Run</button><button type="button" disabled={busy} onClick={() => void send('\x03')}>Interrupt</button></form>}</>;
}
