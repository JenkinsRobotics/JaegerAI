// Hermes / OpenClaw's own UIs, embedded through Jaeger's loopback-only embed proxy (J-083 C).
import { useEffect, useState } from 'react'

export type EngineId = 'hermes' | 'openclaw'

export const ENGINE_EMBEDS: Record<EngineId, { title: string; port: number; start: string; blurb: string }> = {
  hermes: { title: 'Hermes', port: 8798, start: '/', blurb: 'Hermes dashboard: its sessions, skills, memory and config.' },
  openclaw: { title: 'OpenClaw', port: 8797, start: '/__jaeger/start', blurb: 'OpenClaw Control UI: its agents, tools, channels and sessions.' },
}

/** The embed proxy only listens on the Mac's loopback, so it is reachable only from a page on the Mac. */
export function embedUrl(engine: EngineId, host: string = typeof location !== 'undefined' ? location.hostname : ''): string | null {
  if (host !== '127.0.0.1' && host !== 'localhost' && host !== '::1' && host !== '[::1]') return null
  const e = ENGINE_EMBEDS[engine]
  return `http://127.0.0.1:${e.port}${e.start}`
}

export function EnginePanel({ engine }: { engine: EngineId }) {
  const e = ENGINE_EMBEDS[engine]
  const url = embedUrl(engine)
  const [up, setUp] = useState<boolean | null>(null)
  useEffect(() => {
    if (!url) return
    let live = true
    fetch(`http://127.0.0.1:${e.port}/__jaeger/health`).then((r) => live && setUp(r.ok)).catch(() => live && setUp(false))
    return () => { live = false }
  }, [url, e.port])
  if (!url) {
    return <div className="jg-u-page"><p className="jg-u-muted">{e.title}&rsquo;s own UI is only reachable on the Mac (it stays on loopback). Open Jaeger on the Mac to use it here.</p></div>
  }
  return (
    <div className="jg-u-page jg-u-page--flush" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <p className="jg-u-muted" style={{ margin: '6px 12px' }}>{e.blurb}{up === false ? ` ${e.title} isn’t running right now.` : ''} <a href={url} target="_blank" rel="noreferrer">Open in a window</a></p>
      <iframe title={`${e.title} UI`} src={url} style={{ flex: 1, minHeight: 560, width: '100%', border: 0 }}
        sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals allow-downloads" />
    </div>
  )
}
