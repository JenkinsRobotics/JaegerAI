import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { AgentAppsPanel } from './AgentAppsPanel'
import { getJson } from '../unified/webui'

vi.mock('../unified/webui', () => ({ getJson: vi.fn(), sendJson: vi.fn() }))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const read = vi.mocked(getJson)
afterEach(() => read.mockReset())

it('maps app loading, empty approvals, and fetch errors to card states', async () => {
  read.mockImplementation(() => new Promise(() => {}))
  const el = document.createElement('div'); const root = createRoot(el)
  await act(async () => root.render(<AgentAppsPanel />))
  expect(el.querySelector('[aria-label="Agent apps"]')?.getAttribute('data-state')).toBe('loading')
  await act(async () => root.unmount())
  read.mockImplementation((url) => Promise.resolve(String(url).includes('proposals') ? { proposals: [] } : { apps: [] }))
  const empty = createRoot(el)
  await act(async () => { empty.render(<AgentAppsPanel />); await Promise.resolve() })
  expect(el.querySelector('[aria-label="Waiting for your approval"]')?.getAttribute('data-state')).toBe('empty')
  expect(el.textContent).toContain('Nothing waiting')
  await act(async () => empty.unmount())
  read.mockRejectedValue(new Error('offline'))
  const error = createRoot(el)
  await act(async () => { error.render(<AgentAppsPanel />); await Promise.resolve() })
  expect(el.querySelector('[aria-label="Agent apps error"]')?.getAttribute('data-state')).toBe('error')
  expect(el.textContent).toContain('offline')
  await act(async () => error.unmount())
})
