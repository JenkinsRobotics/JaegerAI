import { useEffect, useRef, useState } from 'react'
import { getJson, sendJson } from '../unified/webui'
import { DroidLife } from './DroidLife'
import './droidView.css'

/** Live Droid view: what the droid sees (camera), what it is doing on the Mac
 * (screen), and what was said, refreshed about once a second while awake. */
interface DroidStatus {
  state: string; awake: boolean; muted?: boolean; heard?: string; said?: string; error?: string | null
  latency_ms?: number | null; camera?: string; faces?: number; present?: boolean; action?: string | null
  pending_approval?: string | null; speaker?: string; microphone?: string; vision_ms?: number; mode?: string
}
interface Line { role: 'user' | 'assistant'; text: string; at: number }

const LABEL: Record<string, string> = {
  off: 'Off', present: 'Present · watching quietly', waking: 'Waking…', listening: 'Listening', hearing: 'Hearing you', thinking: 'Thinking',
  speaking: 'Speaking', sleeping: 'Going to standby', error: 'Needs attention', unavailable: 'Service offline',
}
const base = '/api/jaeger/droid'

function LiveImage({ path, live, alt, empty }: { path: string; live: boolean; alt: string; empty: string }) {
  const [src, setSrc] = useState<string>()
  const [failed, setFailed] = useState(false)
  const timer = useRef<number | undefined>(undefined)
  useEffect(() => {
    if (!live) { setSrc(undefined); return }
    let alive = true
    const next = () => { if (alive) setSrc(`${base}/${path}?t=${Date.now()}`) }
    next()
    return () => { alive = false; window.clearTimeout(timer.current) }
  }, [path, live])
  if (!live || !src) return <div className="jg-droid__empty">{empty}</div>
  return <img className="jg-droid__img" src={src} alt={alt} data-failed={failed || undefined}
    onLoad={() => { setFailed(false); timer.current = window.setTimeout(() => setSrc(`${base}/${path}?t=${Date.now()}`), 900) }}
    onError={() => { setFailed(true); timer.current = window.setTimeout(() => setSrc(`${base}/${path}?t=${Date.now()}`), 2500) }} />
}

export function DroidView() {
  const [status, setStatus] = useState<DroidStatus>({ state: 'off', awake: false })
  const [lines, setLines] = useState<Line[]>([])
  const [busy, setBusy] = useState(false)
  const end = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let alive = true
    const poll = async () => {
      try {
        const data = await getJson<{ lines?: Line[]; status?: DroidStatus; state?: string; error?: string }>(`${base}/transcript`)
        if (!alive) return
        setStatus(data.status || { state: data.state || 'unavailable', awake: false, error: data.error })
        setLines(data.lines || [])
      } catch { if (alive) setStatus({ state: 'unavailable', awake: false, error: 'Droid service is not reachable' }) }
    }
    void poll()
    const id = window.setInterval(() => void poll(), 1000)
    return () => { alive = false; window.clearInterval(id) }
  }, [])
  useEffect(() => { end.current?.scrollIntoView({ block: 'end' }) }, [lines.length, lines.at(-1)?.text])

  const act = async (action: string, body?: unknown) => {
    setBusy(true)
    try { setStatus(await sendJson<DroidStatus>('POST', `${base}/${action}`, body ?? {})) } catch { /* the poll shows the error */ }
    finally { setBusy(false) }
  }
  const awake = status.awake
  return <div className="jg-droid" data-state={status.state}>
    <header className="jg-droid__top">
      <div className="jg-droid__title">
        <span className="jg-droid__orb" data-state={status.state} aria-hidden />
        <div><h1>Droid</h1><p role="status">{LABEL[status.state] || status.state}{status.muted ? ' · mic muted' : ''}{status.action ? ` · ${status.action}` : ''}</p></div>
      </div>
      <div className="jg-droid__actions">
        <button type="button" className="jg-droid__primary" disabled={busy || status.state === 'unavailable'} onClick={() => void act(awake && status.mode !== 'present' ? 'sleep' : 'wake')}>{!awake ? 'Wake droid' : status.mode === 'present' ? 'Talk' : 'Put to sleep'}</button>
        {awake && status.mode === 'present' && <button type="button" disabled={busy} onClick={() => void act('sleep')}>Sleep till morning</button>}
        <button type="button" disabled={!awake || busy} aria-pressed={!!status.muted} onClick={() => void act('mute')}>{status.muted ? 'Unmute' : 'Mute'}</button>
        <button type="button" disabled={!awake || busy} onClick={() => void act('look', { around: true, question: 'Look around the room. What do you see?' })}>Look around</button>
        <button type="button" disabled={!awake || busy} onClick={() => void act('stop')}>Stop</button>
      </div>
    </header>
    {status.error && <p className="jg-droid__alert" role="alert">{status.error}</p>}
    {status.pending_approval && <p className="jg-droid__approval" role="alert">Waiting for your spoken yes or no: {status.pending_approval}</p>}
    <div className="jg-droid__grid">
      <section className="jg-droid__screen" aria-label="Screen">
        <h2>Screen</h2>
        <LiveImage path="screen.jpg" live={awake} alt="The Mac's screen, live" empty={awake ? 'Connecting to the screen…' : 'The droid is in standby. Wake it to watch its screen.'} />
      </section>
      <aside className="jg-droid__side">
        <section className="jg-droid__camera" aria-label="Camera">
          <h2>Camera{status.camera === 'live' ? ` · ${status.present ? `${status.faces || 1} in view` : 'nobody in view'}` : ''}</h2>
          <LiveImage path="camera.jpg" live={awake && status.camera === 'live'} alt="What the droid sees, live"
            empty={!awake ? 'Eyes closed (standby).' : status.camera === 'needs permission' ? 'Camera permission needed for Jaeger Droid.' : 'Opening the camera…'} />
          <p className="jg-droid__note">Camera frames stay on this Mac and are read by the local vision model.</p>
        </section>
        <section className="jg-droid__transcript" aria-label="Conversation" aria-live="polite">
          <h2>Conversation{status.latency_ms ? ` · ${(status.latency_ms / 1000).toFixed(1)} s reply` : ''}</h2>
          <div className="jg-droid__lines">
            {lines.length ? lines.map((l, i) => <p key={i} data-role={l.role}><span>{l.role === 'user' ? 'You' : 'Jaeger'}</span>{l.text}</p>)
              : <p className="jg-droid__hint">Press WAKE DROID on the Stream Deck, or Wake droid above, and talk.</p>}
            {awake && status.state === 'hearing' && status.heard && <p data-role="user" data-partial><span>You</span>{status.heard}</p>}
            <div ref={end} />
          </div>
        </section>
      </aside>
    </div>
    <DroidLife />
  </div>
}
