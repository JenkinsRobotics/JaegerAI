import { useCallback, useEffect, useRef, useState } from 'react';
import { BrowserWorkspacePanel, type BrowserWorkspaceAction } from 'codex-ui-kit';
import 'codex-ui-kit/styles.css';
import type { JaegerSource } from '../api/source';
import { sendJson } from '../unified/webui';
import './browser.css';

type BrowserState = { active: string; pages: { id: string; title: string; url: string }[]; image_data?: string };

/** A viewer of the Gateway's browser, never an iframe of the destination website. */
export function BrowserWorkspace({ sessionId, source }: { sessionId: string; source: JaegerSource }) {
  const [state, setState] = useState<BrowserState>();
  const [address, setAddress] = useState('');
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [details, setDetails] = useState(''), [expanded, setExpanded] = useState(false);
  const alive = useRef(true), pending = useRef(0), queue = useRef<Promise<unknown>>(Promise.resolve());
  const frame = useRef<HTMLIFrameElement>(null);
  const base = `/v1/sessions/${encodeURIComponent(sessionId)}/browser`;
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const act = useCallback(async (action: string, extra: Record<string, unknown> = {}, quiet = false) => {
    if (quiet && action === 'status' && pending.current) return;
    pending.current++;
    if (!quiet) { setBusy(true); setError(''); }
    const operation = queue.current.then(async () => {
      if (!alive.current) return;
      try {
        const result = await sendJson<BrowserState>('POST', base + '/action', { action, ...extra });
        if (alive.current && result.pages) setState(result);
        return result;
      } catch (e) { if (alive.current) setError(e instanceof Error ? e.message : String(e)); }
      finally { pending.current--; if (alive.current && !pending.current) setBusy(false); }
    });
    queue.current = operation;
    return operation;
  }, [base]);
  useEffect(() => { if (sessionId && source.kind === 'live') void act('status'); }, [act, sessionId, source.kind]);
  const active = state?.pages.find(p => p.id === state.active);
  useEffect(() => { setAddress(active?.url === 'about:blank' ? '' : active?.url || ''); }, [active?.url]);
  useEffect(() => {
    const element = frame.current;
    if (!element || !state?.active) return;
    let timer: ReturnType<typeof setTimeout>;
    const observer = new ResizeObserver(() => {
      clearTimeout(timer);
      timer = setTimeout(() => { const { width, height } = element.getBoundingClientRect(); if (width > 0 && height > 0) void act('viewport', { width, height }, true); }, 150);
    });
    observer.observe(element);
    return () => { clearTimeout(timer); observer.disconnect(); };
  }, [state?.active, act]);
  useEffect(() => {
    if (!state) return;
    const timer = window.setInterval(() => { if (document.visibilityState === 'visible') void act('status', {}, true); }, 2000);
    return () => clearInterval(timer);
  }, [!!state, act]);
  const onAction = async (action: BrowserWorkspaceAction) => {
    if (['back', 'forward', 'reload', 'new-tab'].includes(action)) { await act(action); return; }
    if (action === 'expand') { setExpanded(v => !v); return; }
    if (action === 'external') { if (active && /^https?:\/\//.test(active.url)) window.open(active.url, '_blank', 'noopener,noreferrer'); return; }
    if (action === 'site-info') { setDetails(active ? `${active.title}\n${active.url}` : 'No page open'); return; }
    if (action === 'site-tools') { const result = await act('errors'); if (result) setDetails(JSON.stringify(result, null, 2)); return; }
    if (action === 'options') { setDetails(details ? '' : 'Browser workspaces belong to this conversation. Use “Stop browser” to close its tabs and release memory.'); return; }
    if (action === 'annotate' && source.uploadAttachment) {
      const result = await act('screenshot');
      if (result?.image_data) {
        try { await source.uploadAttachment(sessionId, { name: 'browser-page.png', mime: 'image/png', data_base64: result.image_data }, crypto.randomUUID()); setDetails('Screenshot saved in this conversation’s Sources. You can discuss it with Jaeger.'); }
        catch (e) { setError(String(e)); }
      }
    }
  };
  if (!state) return <div className="jg-browser-start"><h2>Browser</h2><p>Open a browser that you and Jaeger can use together in this conversation.</p>{error && <p role="alert">{error}</p>}<button disabled={!sessionId || source.kind !== 'live' || busy} onClick={() => void act('status')}>{busy ? 'Starting browser…' : 'Open browser'}</button></div>;
  return <div className="jg-browser" data-expanded={expanded}>
    <BrowserWorkspacePanel tabs={state.pages.map(p => ({ id: p.id, title: p.title || 'New tab', active: p.id === state.active }))} disabled={busy}
      onAction={action => void onAction(action)} onSelectTab={p => void act('select', { page_id: p.id })} onCloseTab={p => void act('close', { page_id: p.id })}>
      <form className="jg-browser-address" onSubmit={event => { event.preventDefault(); const url = /^[a-z][a-z\d+.-]*:/i.test(address) ? address : `https://${address}`; void act('navigate', { url }); }}>
        <input aria-label="Browser address" placeholder="Enter a website address" value={address} onChange={event => setAddress(event.target.value)} spellCheck={false} /><button disabled={busy || !address.trim()}>Go</button>
      </form>
      {error && <p className="jg-browser-notice" role="alert">{error}<button onClick={() => void act('status')}>Reconnect</button></p>}
      {details && <div className="jg-browser-notice"><button onClick={() => setDetails('')}>Close details</button><pre>{details}</pre></div>}
      {active && <iframe ref={frame} className="jg-browser-viewer" title="Shared browser page" src={`${base}/viewer?pageId=${encodeURIComponent(active.id)}`} />}
      <footer><span>{busy ? 'Working…' : 'Shared with Jaeger'}</span><button disabled={busy} onClick={async () => { const result = await act('stop'); if (result) setState(undefined); }}>Stop browser</button></footer>
    </BrowserWorkspacePanel>
  </div>;
}
