// The Swift shell's native surfaces as screen tabs, so they work in the window and in a browser tab alike.
// Shell: StatusItemController (status lines, tasks, pause, stack, login, reload, browser), DroidMenuController,
// MacControlMenuController. Settings: hotkey, pause, launch at login, permissions, history consent, deep links, notify.
// The window's menu-bar item (native.py) calls the same actions by the same names.
import { useEffect, useState } from 'react';
import { act, openLink, shellStatus, type ShellStatus } from './agent.ts';

function useStatus() {
  const [s, setS] = useState<ShellStatus | null>(null);
  const reload = () => shellStatus().then(setS);
  useEffect(() => { void reload(); const t = setInterval(reload, 3000); return () => clearInterval(t); }, []);
  return [s, reload] as const;
}

function Button({ name, arg, label, confirm, disabled, after, onResult }: {
  name: string; arg?: unknown; label: string; confirm?: string; disabled?: boolean; after?: () => void; onResult?: (r: unknown) => void;
}) {
  const [busy, setBusy] = useState(false), [ask, setAsk] = useState(false), [msg, setMsg] = useState('');
  const go = async () => {
    setAsk(false); setBusy(true); setMsg('');
    try { const r = await act(name, arg); onResult?.(r); setMsg(typeof r === 'object' && r && 'ok' in r ? ((r as { ok: boolean }).ok ? 'Done' : 'Failed') : 'Done'); }
    catch (e) { setMsg((e as Error).message); }
    finally { setBusy(false); after?.(); setTimeout(() => setMsg(''), 4000); }
  };
  if (ask) return <span className="confirm">{confirm} <button className="ghost" onClick={go}>{label.replace('…', '')}</button><button className="ghost" onClick={() => setAsk(false)}>Cancel</button></span>;
  return <span className="act"><button className="ghost" disabled={disabled || busy} onClick={() => (confirm ? setAsk(true) : go())}>{busy ? '…' : label}</button>{msg ? <small className="dim"> {msg}</small> : null}</span>;
}

export function Shell({ webui, only }: { webui: string; only?: string }) {
  const [s, reload] = useStatus();
  const [mac, setMac] = useState<Record<string, string> | null>(null);
  if (!s) return <div className="settings dim">Loading…</div>;
  const d = s.droid_raw, up = s.gateway_up, estop = !!d.estop_latched, awake = !!d.awake;
  const t = s.tasks, show = (k: string) => !only || only === k || (only === 'status' && k === 'stack');
  return (
    <div className="settings shell">
      {show('status') ? <section>
        <h3>Status</h3>
        <ul className="lines"><li>{s.webui}</li><li>{s.gateway}</li><li>{s.shell}</li></ul>
        <div className="acts">
          <Button name="shell.pause" label={s.paused ? 'Resume Jaeger Shell' : 'Pause Jaeger Shell'} after={reload} />
          <Button name="window.show" label="Show Jaeger" />
          <a className="ghost link" href={webui} target="_blank" rel="noreferrer">Open in Browser</a>
          <button className="ghost" onClick={() => location.reload()}>Reload</button>
        </div>
      </section> : null}
      {show('tasks') ? <section>
        <h3>Tasks</h3>
        {t.state === 'unsupported' ? <p className="dim">The Gateway has no /v1/live/tasks route, so live tasks and their notifications are off (the Swift app stops polling the same way).</p>
          : <ul className="lines">
            <li>{t.running.length ? `Tasks running (${t.running.length})` : 'Tasks: none running'}</li>
            {t.running.map(x => <li key={x.request_id}>⟳ {x.title} — {x.step} ({Math.round(x.elapsed_s ?? 0)} s)</li>)}
            {t.recent.map(x => <li key={x.request_id}>{x.status === 'failed' ? '✕' : '✓'} {x.title}</li>)}
          </ul>}
      </section> : null}
      {show('stack') ? <section>
        <h3>Jaeger stack</h3>
        <div className="acts">
          <Button name="stack.start" label="Start…" confirm="Start the Jaeger stack?" after={reload} />
          <Button name="stack.restart" label="Restart…" confirm="Restart the Jaeger stack?" after={reload} />
          <Button name="stack.stop" label="Stop…" confirm="Stop the Jaeger stack?" after={reload} />
        </div>
      </section> : null}
      {show('droid') ? <section>
        <h3>Droid</h3>
        <ul className="lines">{s.droid.map(l => <li key={l}>{l}</li>)}</ul>
        <div className="acts">
          {awake ? <Button name="droid.sleep" label="Turn Off Droid Mode (Sleep & Park)" disabled={!up} after={reload} />
            : <Button name="droid.wake" label="Turn On Droid Mode (Wake)" disabled={!up || estop} after={reload} />}
          <Button name="droid.park" label="Park Camera Now (Privacy)" disabled={!up} after={reload} />
          <Button name="droid.center" label="Center Camera" disabled={!up || !awake || estop} />
          <Button name="open.droid" label="Open Droid View" />
          <Button name="droid.refresh" label="Refresh Droid Peripherals" disabled={!up} after={reload} />
        </div>
      </section> : null}
      {show('mac') ? <section>
        <h3>Mac</h3>
        <div className="acts">
          <Button name="mac.lock" label="Lock Mac" confirm="Lock this Mac now?" />
          <Button name="mac.display_off" label="Turn Display Off" />
          <Button name="mac.status" label="Mac Status…" onResult={r => setMac(r as Record<string, string>)} />
        </div>
        {mac ? <dl className="kv"><dt>Uptime</dt><dd>{mac.uptime}</dd><dt>Disk free</dt><dd>{mac.disk_free}</dd><dt>Battery</dt><dd>{mac.battery}</dd></dl> : null}
      </section> : null}
    </div>
  );
}

const HOTKEYS = { 'ctrl-opt-j': '⌃⌥J', 'ctrl-opt-k': '⌃⌥K', 'ctrl-opt-space': '⌃⌥Space (same as the Swift app)', 'opt-space': '⌥Space' };

export function Settings() {
  const [s, reload] = useStatus();
  const [link, setLink] = useState(''), [linkMsg, setLinkMsg] = useState('');
  if (!s) return <div className="settings dim">Loading…</div>;
  return (
    <div className="settings">
      <section>
        <h3>Window</h3>
        <label>Global hotkey (shows and hides the window; needs Accessibility for other apps' keys)
          <select value={s.hotkey} onChange={e => act('hotkey.set', e.target.value).then(reload)}>
            {Object.entries(HOTKEYS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <label className="row"><input type="checkbox" checked={s.paused} onChange={() => act('shell.pause').then(reload)} />Pause the shell (hotkey off)</label>
        <label className="row"><input type="checkbox" checked={s.login} onChange={() => act('login.toggle').then(reload)} />Launch at Login (this NexusUI app)</label>
        <label className="row"><input type="checkbox" onChange={e => act('window.pin', e.target.checked)} />Keep the window on top</label>
      </section>
      <section>
        <h3>Permissions</h3>
        <ul className="list">{Object.entries(s.permissions).map(([k, v]) => <li key={k}><b>{k.replace('_', ' ')}</b><code>{v}</code><button className="ghost" onClick={() => act('settings.open', k)}>Open Settings</button></li>)}
        </ul>
        <label className="row"><input type="checkbox" checked={s.history_app_names} onChange={e => act('history.consent', e.target.checked).then(reload)} />Allow Jaeger to record foreground app names</label>
      </section>
      <section>
        <h3>Notifications and links</h3>
        <div className="acts"><Button name="notify.test" label="Send a test notification" /></div>
        <label>Open a jaeger:// link (jaeger://conversation/&lt;id&gt; or jaeger://notifications)
          <input value={link} placeholder="jaeger://notifications" onChange={e => setLink(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') openLink(link).then(r => setLinkMsg(`Opens ${JSON.stringify(r.destination)}`), err => setLinkMsg(err.message)); }} />
        </label>
        {linkMsg ? <p className="dim">{linkMsg}</p> : null}
      </section>
    </div>
  );
}
