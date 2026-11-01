import { useEffect, useState } from 'react'
import { getJson } from '../unified/webui'
import { WidgetCard } from '../widgets/primitives/WidgetCard'
import './machine.css'

type Runtime = { present: boolean; reachable: boolean | null; loaded_models?: string[] }
export type HostCapabilities = {
  cpu_model: string | null; cpu_cores: number | null; memory_total_gb: number | null
  memory_pressure: number | null; gpu: string | null; neural_engine: boolean | null
  metal: boolean | null; disk_free_gb: number | null; macos_version: string | null
  runtimes: Record<string, Runtime>
}

const value = (x: string | number | boolean | null) => x == null ? 'Unknown' : typeof x === 'boolean' ? (x ? 'Yes' : 'No') : String(x)

export function HostCapabilitiesCard() {
  const [data, setData] = useState<HostCapabilities | null>(null)
  const [error, setError] = useState<string>()
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let live = true
    setError(undefined)
    const timeout = new Promise<never>((_, reject) => setTimeout(() => reject(new Error('The Mac took longer than 15 s to answer')), 15000))
    Promise.race([getJson<{ capabilities?: HostCapabilities }>('/v1/machine/health'), timeout]).then(
      result => { if (!live) return; if (result.capabilities) setData(result.capabilities); else setError('The Gateway returned no host capabilities') },
      reason => { if (live) setError(reason instanceof Error ? reason.message : String(reason)) },
    )
    return () => { live = false }
  }, [attempt])
  return <WidgetCard title="Host capabilities" state={error && !data ? "error" : !data ? "loading" : "ready"}
    message={error ? `Couldn't read host capabilities: ${error}` : "Loading host capabilities…"}
    actions={error ? <button type="button" className="jg-u-btn" onClick={() => setAttempt((n) => n + 1)}>Retry</button> : undefined}>
    {data && <>
      <div className="jg-mc-metrics">
        {([
          ['CPU', data.cpu_model], ['CPU cores', data.cpu_cores], ['Memory total (GB)', data.memory_total_gb],
          ['Memory pressure', data.memory_pressure], ['GPU', data.gpu], ['Neural Engine', data.neural_engine],
          ['Metal', data.metal], ['Disk free (GB)', data.disk_free_gb], ['macOS', data.macos_version],
        ] as [string, string | number | boolean | null][]).map(([label, item]) =>
          <div className="jg-mc-metric" key={label}><span>{label}</span><strong>{value(item)}</strong></div>)}
      </div>
      <h4>Local runtimes</h4>
      <div className="jg-mc-metrics">{Object.entries(data.runtimes).map(([name, runtime]) =>
        <div className="jg-mc-metric" key={name}><span>{name.replace('_', ' ')}</span>
          <strong>{runtime.reachable === true ? 'Reachable' : runtime.reachable === false ? (runtime.present ? 'Present, offline' : 'Unavailable') : runtime.present ? 'Present' : 'Unavailable'}
            {runtime.loaded_models?.length ? ` · ${runtime.loaded_models.join(', ')}` : ''}</strong></div>)}</div>
    </>}
  </WidgetCard>
}
