import { useEffect, useState } from 'react'
import { csrfHeader } from '../api/gateway'

/** Quick Mac actions from the phone web app (parity P11): lock, display off, open app, status.
 *  Calls the Gateway's owner-only /v1/mac routes through the WebUI proxy. */
type MacStatus = { host?: string; frontmost_app?: string; screen_locked?: boolean; power?: string[]; memory_free_percent?: number; error?: string }

async function call<T>(path: string, body?: unknown): Promise<T> {
  const method = body === undefined ? 'GET' : 'POST'
  const res = await fetch(path, {
    method, cache: 'no-store', credentials: 'same-origin',
    headers: { Accept: 'application/json', ...(body === undefined ? {} : { 'Content-Type': 'application/json' }), ...csrfHeader(method) },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error((data as { error?: string }).error || `HTTP ${res.status}`)
  return data as T
}

export function MacActionsCard() {
  const [status, setStatus] = useState<MacStatus>()
  const [app, setApp] = useState('')
  const [busy, setBusy] = useState<string>()
  const [note, setNote] = useState<string>()

  const refresh = async () => {
    try { setStatus(await call<MacStatus>('/v1/mac/status')) } catch (e) { setNote(String((e as Error).message || e)) }
  }
  useEffect(() => { void refresh() }, [])

  const run = async (action: string, label: string) => {
    if (action === 'open_app' && !app.trim()) { setNote('Type an app name first.'); return }
    setBusy(action); setNote(undefined)
    try {
      await call('/v1/mac/action', { action, app: action === 'open_app' ? app.trim() : undefined })
      setNote(`${label}: done`)
      await refresh()
    } catch (e) {
      setNote(`${label} failed: ${String((e as Error).message || e)}`)
    } finally { setBusy(undefined) }
  }

  return (
    <div className="machine-control-card mac-actions-card">
      <div className="machine-control-card__header">
        <h3>Mac actions</h3>
        <span className={`badge ${status?.screen_locked ? 'badge-warning' : 'badge-success'}`}>
          {status ? (status.screen_locked ? 'Locked' : 'Unlocked') : '…'}
        </span>
      </div>
      <p className="machine-control-card__desc">
        {status?.host ? `${status.host} · front app ${status.frontmost_app || '—'}${status.power?.[0] ? ` · ${status.power[0].replace(/^Now drawing from /, '').replace(/'/g, '')}` : ''}` : 'Control your Mac from here, including from your phone.'}
      </p>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <button type="button" disabled={!!busy} onClick={() => void run('lock_screen', 'Lock')}>Lock Mac</button>
        <button type="button" disabled={!!busy} onClick={() => void run('display_off', 'Display off')}>Display off</button>
        <button type="button" disabled={!!busy} onClick={() => void refresh()}>Status</button>
      </div>
      <form style={{ display: 'flex', gap: 8, marginTop: 8 }} onSubmit={(e) => { e.preventDefault(); void run('open_app', `Open ${app}`) }}>
        <input value={app} onChange={(e) => setApp(e.target.value)} placeholder="App name, e.g. Safari" aria-label="App to open" style={{ flex: 1 }} />
        <button type="submit" disabled={!!busy}>Open app</button>
      </form>
      {note && <p className="machine-control-card__desc" role="status">{note}</p>}
    </div>
  )
}
