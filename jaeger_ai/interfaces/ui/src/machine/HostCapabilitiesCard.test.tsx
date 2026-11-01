import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { HostCapabilitiesCard } from './HostCapabilitiesCard'
vi.mock('../unified/webui', () => ({ getJson: vi.fn().mockResolvedValue({ capabilities: {
  cpu_model: 'Apple M4', cpu_cores: 10, memory_total_gb: 32, memory_pressure: 1,
  gpu: 'Apple M4', neural_engine: true, metal: true, disk_free_gb: 100,
  macos_version: '15.0', runtimes: { ollama: { present: true, reachable: true, loaded_models: ['gemma:latest'] } },
} }) }))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
it('renders hardware and local runtime capability facts', async () => {
  const el = document.createElement('div'); document.body.append(el); const root = createRoot(el)
  await act(async () => { root.render(<HostCapabilitiesCard />); await Promise.resolve() })
  expect(el.textContent).toContain('Apple M4')
  expect(el.textContent).toContain('gemma:latest')
  expect(el.textContent).toContain('Reachable')
  await act(async () => root.unmount()); el.remove()
})
