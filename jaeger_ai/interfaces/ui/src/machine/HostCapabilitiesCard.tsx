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
  useEffect(() => {
    let live = true
    getJson<{ capabilities: HostCapabilities }>('/v1/machine/health').then(
      result => { if (live) setData(result.capabilities) },
      reason => { if (live) setError(String(reason)) },
    )
    return () => { live = false }
  }, [])
  return <WidgetCard title="Host capabilities" state={error ? "error" : !data ? "loading" : "ready"}
    message={error ?? "Loading host capabilities…"}>
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
