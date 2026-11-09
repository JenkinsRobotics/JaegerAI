import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { it, expect, vi } from 'vitest'
import { MachineControlPanel } from './MachineControlPanel'
import type { JaegerSource } from '../api/source'
vi.mock('../machine/HostCapabilitiesCard', () => ({ HostCapabilitiesCard: () => null }))
vi.mock('../machine/ResourcesCard', () => ({ ResourcesCard: () => null }))
vi.mock('../machine/LogsPanel', () => ({ LogsPanel: () => null }))
vi.mock('../machine/AgentAppsPanel', () => ({ AgentAppsPanel: () => null }))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
async function mount(source?: JaegerSource) {
  const prior = window.jaegerNative
  delete window.jaegerNative
  const el = document.createElement('div'); document.body.append(el)
  const root = createRoot(el)
  await act(async () => root.render(<MachineControlPanel source={source} />))
  return { el, async render(next?: JaegerSource) { await act(async () => root.render(<MachineControlPanel source={next} />)) }, async close() { await act(async () => root.unmount()); el.remove(); window.jaegerNative = prior } }
}
it('does not claim online Mac hardware when inventory request fails', async () => {
  const source = { computers: vi.fn().mockRejectedValue(new Error('Gateway unavailable')) } as unknown as JaegerSource
  const ui = await mount(source)
  try {
    expect(ui.el.querySelector('[role="alert"]')?.textContent).toContain('Gateway unavailable')
    expect(ui.el.textContent).not.toContain('Online (Local Daemon)')
    expect(ui.el.textContent).not.toContain('Apple Silicon / Darwin')
  } finally { await ui.close() }
})
it('does not claim Online before a pending inventory response', async () => {
  const source = { computers: vi.fn(() => new Promise(() => {})) } as unknown as JaegerSource
  const ui = await mount(source)
  try { expect(ui.el.textContent).not.toContain('Online') } finally { await ui.close() }
})
it('does not invent a local daemon when adapter lacks inventory capability', async () => {
  const ui = await mount({} as JaegerSource)
  try { expect(ui.el.textContent).not.toContain('Online (Local Daemon)') } finally { await ui.close() }
})
it('shows authoritative synthetic Linux host fields without Mac fallback when inventory succeeds', async () => {
  const source = { computers: vi.fn().mockResolvedValue({ scope: 'gateway_process_only', computers: [{ id: 'synthetic-host', state: 'serving', os: 'Linux', architecture: 'x86_64', process_id: 42, screen_view: 'no_shared_ui_viewport', input_authorization: 'per_admitted_turn_and_existing_policy' }], hosted: { state: 'not_observed_by_gateway_inventory', allocation_supported: false }, limits: ['Serving proves transport only.'] }) } as unknown as JaegerSource
  const ui = await mount(source)
  try {
    expect(ui.el.textContent).toContain('synthetic-host'); expect(ui.el.textContent).toContain('Linux (x86_64)')
    expect(ui.el.textContent).not.toContain('Apple Silicon / Darwin')
  } finally { await ui.close() }
})
it('does not invent hardware or daemon for successful empty gateway inventory', async () => {
  const source = { computers: vi.fn().mockResolvedValue({ scope: 'gateway_process_only', computers: [], hosted: { state: 'not_observed_by_gateway_inventory', allocation_supported: false }, requests: {}, approvals: {}, actions: { allocate: false, restart: false, input: false, capture: false }, limits: ['Serving proves this local Gateway transport, not an end-to-end agent/tool result.'] }) } as unknown as JaegerSource
  const ui = await mount(source)
  try { expect(ui.el.textContent).not.toContain('Online (Local Daemon)') } finally { await ui.close() }
})
it('does not describe failed safety reads as no active restrictions', async () => {
  const source = { policySources: vi.fn().mockRejectedValue(new Error('Policy source unavailable')) } as unknown as JaegerSource
  const ui = await mount(source)
  try {
    const button = [...ui.el.querySelectorAll('button')].find(b => b.textContent === 'Safety')!
    await act(async () => button.click())
    expect(source.policySources).toHaveBeenCalledOnce()
    expect(ui.el.textContent).not.toContain('No active policy restrictions detected')
    expect(ui.el.querySelector('[role="alert"]')?.textContent).toContain('Policy source unavailable')
  } finally { await ui.close() }
})

const inventory = (id = 'host-current') => ({ scope: 'gateway_process_only', computers: [{ id, state: 'serving', os: 'Linux', architecture: 'x86_64', process_id: 42, screen_view: 'no_shared_ui_viewport', input_authorization: 'per_admitted_turn_and_existing_policy' }], limits: ['Transport only; no execution verified.'] })
const safety = (state = 'observed') => ({ scope: 'bound_instance_policy_sources', state, action_authorized: false, mutation_supported: false, hook_execution_performed: false, sources: [], limits: ['No authority conferred.'] })
const adapter = (computers: unknown, policySources?: unknown) => ({ computers, policySources }) as JaegerSource
function deferred<T>() { let resolve!: (v: T) => void; let reject!: (e: Error) => void; const promise = new Promise<T>((a, b) => { resolve = a; reject = b }); return { promise, resolve, reject } }
async function click(el: HTMLElement, title: string) { await act(async () => [...el.querySelectorAll('button')].find(b => b.textContent === title)!.click()) }

it('renders loading, unavailable and observed Safety without inferring grants', async () => {
  const pending = deferred<ReturnType<typeof safety>>()
  const ui = await mount(adapter(undefined, () => pending.promise))
  try {
    await click(ui.el, 'Safety')
    expect(ui.el.textContent).toContain('Loading safety policy')
    await act(async () => pending.resolve(safety()))
    expect(ui.el.textContent).toContain('observed')
    expect(ui.el.textContent).toContain('No authority conferred.')
    expect(ui.el.textContent).toContain('No policy sources reported. This does not establish authorization.')
    expect(ui.el.textContent).toContain('unknown count')
    expect(ui.el.textContent).not.toContain('Enforced')
    await ui.render({} as JaegerSource)
    expect(ui.el.textContent).toContain('Safety policy unavailable')
    expect(ui.el.textContent).not.toContain('No authority conferred.')
  } finally { await ui.close() }
})

it('keeps Safety failures independent of valid inventory and refreshes both', async () => {
  const computers = vi.fn().mockResolvedValue(inventory())
  const policies = vi.fn().mockRejectedValueOnce(Error('Safety denied')).mockResolvedValue(safety('runtime_not_bound'))
  const ui = await mount(adapter(computers, policies))
  try {
    expect(ui.el.textContent).toContain('host-current')
    expect(ui.el.textContent).toContain('Safety denied')
    expect(ui.el.textContent).toContain('Transport only; no execution verified.')
    await click(ui.el, 'Refresh')
    await click(ui.el, 'Safety')
    expect(ui.el.textContent).toContain('runtime_not_bound')
    expect(ui.el.textContent).not.toContain('Safety denied')
    expect(computers).toHaveBeenCalledTimes(2)
    expect(policies).toHaveBeenCalledTimes(2)
  } finally { await ui.close() }
})

it('keeps valid Safety independent of inventory failure', async () => {
  const ui = await mount(adapter(() => Promise.reject(Error('Inventory denied')), () => Promise.resolve(safety())))
  try { await click(ui.el, 'Safety'); expect(ui.el.textContent).toContain('observed'); expect(ui.el.textContent).toContain('Inventory denied') } finally { await ui.close() }
})

it('clears previous observations on refresh and ignores superseded responses', async () => {
  const old = deferred<ReturnType<typeof inventory>>()
  const newer = deferred<ReturnType<typeof inventory>>()
  const computers = vi.fn().mockResolvedValueOnce(inventory('initial')).mockReturnValueOnce(old.promise).mockReturnValueOnce(newer.promise)
  const ui = await mount(adapter(computers))
  try {
    expect(ui.el.textContent).toContain('initial')
    await click(ui.el, 'Refresh')
    expect(ui.el.textContent).not.toContain('initial')
    expect(ui.el.textContent).toContain('Loading inventory')
    await click(ui.el, 'Refresh')
    await act(async () => newer.resolve(inventory('newest')))
    await act(async () => old.resolve(inventory('obsolete')))
    expect(ui.el.textContent).toContain('newest')
    expect(ui.el.textContent).not.toContain('obsolete')
  } finally { await ui.close() }
})

it('ignores late old-source failures and resolutions after switching source or unmounting', async () => {
  const oldInventory = deferred<ReturnType<typeof inventory>>()
  const oldPolicy = deferred<ReturnType<typeof safety>>()
  const ui = await mount(adapter(() => oldInventory.promise, () => oldPolicy.promise))
  await ui.render(adapter(() => Promise.resolve(inventory('replacement')), () => Promise.resolve(safety())))
  await act(async () => { oldInventory.reject(Error('obsolete failure')); oldPolicy.resolve(safety('runtime_not_bound')) })
  expect(ui.el.textContent).toContain('replacement')
  expect(ui.el.textContent).not.toContain('obsolete failure')
  await click(ui.el, 'Safety')
  expect(ui.el.textContent).not.toContain('runtime_not_bound')
  const late = deferred<ReturnType<typeof inventory>>()
  await ui.render(adapter(() => late.promise))
  await ui.close()
  await act(async () => late.resolve(inventory('unmounted')))
  expect(ui.el.textContent).toBe('')
})

it.each([
  [{ ...inventory(), scope: 'execution_verified' }, safety()],
  [{ ...inventory(), computers: [{}] }, safety()],
  [inventory(), { ...safety(), action_authorized: true }],
  [inventory(), { ...safety(), sources: null }],
])('rejects malformed or overclaiming read responses', async (hosts, policy) => {
  const ui = await mount(adapter(() => Promise.resolve(hosts), () => Promise.resolve(policy)))
  try { expect(ui.el.querySelector('[role="alert"]')?.textContent).toContain('Unqualified') } finally { await ui.close() }
})

it('drops stale hardware and policy when refreshed reads fail', async () => {
  const computers = vi.fn().mockResolvedValueOnce(inventory('previous-host')).mockRejectedValue(Error('Inventory refresh failed'))
  const policies = vi.fn().mockResolvedValueOnce(safety()).mockRejectedValue(Error('Safety refresh failed'))
  const ui = await mount(adapter(computers, policies))
  try {
    expect(ui.el.textContent).toContain('serving (transport observation only)')
    await click(ui.el, 'Refresh')
    expect(ui.el.textContent).not.toContain('previous-host')
    expect(ui.el.textContent).toContain('Hardware and runtime status are unknown')
    await click(ui.el, 'Safety')
    expect(ui.el.textContent).toContain('Restrictions and authorization are unknown')
    expect(ui.el.textContent).not.toContain('No authority conferred.')
    expect(ui.el.textContent).toContain('Safety refresh failed')
  } finally { await ui.close() }
})

it('ignores superseded Safety refresh results and late unmounted rejection', async () => {
  const old = deferred<ReturnType<typeof safety>>()
  const latest = deferred<ReturnType<typeof safety>>()
  const policies = vi.fn().mockReturnValueOnce(old.promise).mockReturnValueOnce(latest.promise)
  const ui = await mount(adapter(undefined, policies))
  await click(ui.el, 'Refresh')
  await act(async () => latest.resolve(safety()))
  await act(async () => old.reject(Error('obsolete policy failure')))
  await click(ui.el, 'Safety')
  expect(ui.el.textContent).toContain('observed')
  expect(ui.el.textContent).not.toContain('obsolete policy failure')
  const late = deferred<ReturnType<typeof safety>>()
  await ui.render(adapter(undefined, () => late.promise))
  await ui.close()
  await act(async () => late.reject(Error('unmounted failure')))
  expect(ui.el.textContent).toBe('')
})
