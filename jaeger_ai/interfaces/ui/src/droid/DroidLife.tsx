import { useEffect, useState } from 'react'
import { getJson, sendJson } from '../unified/webui'

/** Droid Life: presence, mood, Matthew's face/voice (stored on this Mac only),
 * "what I noticed" (7 days, deletable) and why it spoke or stayed quiet. */
interface Enrolment { enrolled: boolean; at?: number; samples?: number }
interface LifeState {
  room?: { active_hours: boolean; presence_on: boolean; owner_present: boolean; owner_facing: boolean; guests: boolean; quiet: boolean; halted: boolean; mode?: string }
  blackboard?: { people: number; fps: number; vision_ms: number | null; quiet_until: number; slept_until: number }
  drives?: Record<string, number>
  mood?: string
  enrolled?: { face: Enrolment; voice: Enrolment }
  enrolling?: { kind: string; status: string; samples: unknown[]; target: number } | null
  indicators?: { camera: boolean; microphone: boolean; transcribing: boolean }
  status?: { mode?: string; presence_blocked?: string | null; slept_until?: number }
}
interface Row { id: string; at: number; kind: string; text?: string; action?: string; reason?: string; about?: string }
const base = '/api/jaeger/droid'
const time = (at: number) => new Date(at * 1000).toLocaleString([], { weekday: 'short', hour: 'numeric', minute: '2-digit' })
const DRIVES: [string, string][] = [['social', 'Social'], ['curiosity', 'Curiosity'], ['energy', 'Energy'], ['confidence', 'Confidence']]

export function DroidLife() {
  const [life, setLife] = useState<LifeState>({})
  const [noticed, setNoticed] = useState<Row[]>([])
  const [decisions, setDecisions] = useState<Row[]>([])
  const [showWhy, setShowWhy] = useState(false)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string>()

  const loadLogs = async () => {
    try {
      const [n, d] = await Promise.all([getJson<{ items?: Row[] }>(`${base}/noticed`), getJson<{ items?: Row[] }>(`${base}/decisions`)])
      setNoticed(n.items || []); setDecisions(d.items || [])
    } catch { /* service offline: the header shows it */ }
  }
  useEffect(() => {
    let alive = true
    const poll = async () => { try { const data = await getJson<LifeState>(`${base}/life`); if (alive) setLife(data) } catch { /* offline */ } }
    void poll(); void loadLogs()
    const a = window.setInterval(() => void poll(), 2000)
    const b = window.setInterval(() => void loadLogs(), 6000)
    return () => { alive = false; window.clearInterval(a); window.clearInterval(b) }
  }, [])

  const post = async (action: string, body: unknown = {}) => {
    setBusy(true); setNote(undefined)
    try {
      const r = await sendJson<{ ok?: boolean; error?: string }>('POST', `${base}/${action}`, body)
      if (r && r.ok === false && r.error) setNote(r.error)
    } catch { setNote('The droid service did not answer.') }
    finally { setBusy(false); void loadLogs() }
  }
  const ind = life.indicators || { camera: false, microphone: false, transcribing: false }
  const room = life.room
  const mode = life.status?.mode || 'off'
  const quiet = !!room?.quiet
  const blocked = life.status?.presence_blocked
  const slept = life.status?.slept_until || 0
  const enrolling = life.enrolling && life.enrolling.status === 'collecting' ? life.enrolling : null

  const presenceLine = mode === 'conversation' ? 'In a conversation'
    : mode === 'present' ? (room?.owner_present ? (room.owner_facing ? 'You are here, facing me' : 'You are here') : 'Nobody here right now')
    : slept > Date.now() / 1000 ? `Asleep until ${time(slept)}`
    : blocked ? `Presence is waiting for ${blocked.replace('microphone', 'microphone permission:')}`
    : room && !room.active_hours ? 'Night: camera and microphone are off' : 'Off'

  return <div className="jg-dlife">
    <section className="jg-dlife__presence" aria-label="Presence">
      <h2>Presence</h2>
      <div className="jg-dlife__ind">
        <span data-on={ind.camera || undefined}><i aria-hidden />Camera {ind.camera ? 'on' : 'off'}</span>
        <span data-on={ind.microphone || undefined} data-rec={ind.transcribing || undefined}><i aria-hidden />
          Microphone {ind.transcribing ? 'on · transcribing' : ind.microphone ? 'on · voice detection only' : 'off'}</span>
      </div>
      <p className="jg-dlife__line">{presenceLine}{room?.guests ? ' · someone else is here (private things stay off the speaker)' : ''}{quiet ? ' · quiet mode' : ''}</p>
      <div className="jg-dlife__drives" aria-label={`Mood: ${life.mood || 'calm'}`}>
        <p>Mood · <b>{life.mood || 'calm'}</b></p>
        {DRIVES.map(([key, label]) => <div key={key} className="jg-dlife__drive">
          <span>{label}</span><meter min={0} max={1} value={life.drives?.[key] ?? 0} aria-label={label} />
        </div>)}
      </div>
      <div className="jg-dlife__row">
        {quiet ? <button type="button" disabled={busy} onClick={() => void post('unquiet')}>You can talk again</button>
          : <button type="button" disabled={busy} onClick={() => void post('quiet', { minutes: 60 })}>Quiet for 1 hour</button>}
        {mode === 'conversation' && <button type="button" disabled={busy} onClick={() => void post('standby')}>End conversation</button>}
      </div>
      <p className="jg-droid__note">Awake 9 AM–11 PM. Without a conversation, nothing is recorded or transcribed: the camera spots people and the microphone only detects that someone is talking.</p>
    </section>

    <section className="jg-dlife__who" aria-label="Recognise Matthew">
      <h2>Recognise you</h2>
      {(['face', 'voice'] as const).map(kind => {
        const e = life.enrolled?.[kind]
        const active = enrolling?.kind === kind
        return <div key={kind} className="jg-dlife__enrol">
          <div>
            <b>{kind === 'face' ? 'Your face' : 'Your voice'}</b>
            <p>{active ? `Learning… ${enrolling!.samples.length}/${enrolling!.target}${kind === 'face' ? ' (look at the camera)' : ' (keep talking)'}`
              : e?.enrolled ? `Learned ${e.at ? time(e.at) : ''} · ${e.samples || 0} samples` : 'Not learned yet'}</p>
          </div>
          <div className="jg-dlife__row">
            {active ? <button type="button" disabled={busy} onClick={() => void post('enrol', { cancel: true })}>Cancel</button>
              : <button type="button" disabled={busy || mode === 'off'} onClick={() => void post('enrol', { kind })}>{e?.enrolled ? 'Re-learn' : 'Learn'}</button>}
            {e?.enrolled && <button type="button" className="jg-dlife__danger" disabled={busy} onClick={() => void post('forget', { kind })}>Delete</button>}
          </div>
        </div>
      })}
      {note && <p className="jg-droid__alert" role="alert">{note}</p>}
      <p className="jg-droid__note">Stored as numbers on this Mac only (~/.jaeger/droid/identity), never uploaded. Used to tell you from guests.</p>
    </section>

    <section className="jg-dlife__noticed" aria-label="What I noticed">
      <h2>What I noticed · last 7 days</h2>
      <div className="jg-dlife__list">
        {noticed.length ? noticed.slice(0, 80).map(r => <p key={r.id}>
          <time>{time(r.at)}</time><span>{r.text || r.kind}</span>
          <button type="button" aria-label="Delete this entry" title="Delete" onClick={() => void post('noticed-delete', { id: r.id })}>×</button>
        </p>) : <p className="jg-droid__hint">Nothing yet.</p>}
      </div>
      <div className="jg-dlife__row">
        <button type="button" className="jg-dlife__danger" disabled={busy || (!noticed.length && !decisions.length)} onClick={() => void post('noticed-delete', {})}>Delete all</button>
        <button type="button" aria-expanded={showWhy} onClick={() => setShowWhy(v => !v)}>{showWhy ? 'Hide' : 'Why I spoke or stayed quiet'}</button>
      </div>
      {showWhy && <div className="jg-dlife__list jg-dlife__why">
        {decisions.length ? decisions.slice(0, 40).map(r => <p key={r.id}>
          <time>{time(r.at)}</time><span><b data-action={r.action}>{r.action === 'speak' ? 'Spoke' : r.action === 'push' ? 'Sent to phone' : 'Stayed quiet'}</b> · {r.about?.replace('_', ' ')} · {r.reason}</span>
        </p>) : <p className="jg-droid__hint">No decisions yet.</p>}
      </div>}
    </section>
  </div>
}
