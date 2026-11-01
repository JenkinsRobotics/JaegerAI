import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { LogsPanel } from './LogsPanel'
import { getJson } from '../unified/webui'

vi.mock('../unified/webui', () => ({ getJson: vi.fn() }))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const read = vi.mocked(getJson)
afterEach(() => read.mockReset())

it('maps loading, empty, and error log reads to card states while retaining controls', async () => {
  read.mockImplementation((url) => String(url).includes('/sources') ? Promise.resolve({ sources: [] }) : new Promise(() => {}))
  const el = document.createElement('div'); const root = createRoot(el)
  await act(async () => { root.render(<LogsPanel />); await Promise.resolve() })
  expect(el.querySelector('[aria-label="Logs"]')?.getAttribute('data-state')).toBe('loading')
  expect(el.querySelector('[aria-label="Search log"]')).not.toBeNull()
  await act(async () => root.unmount())
  read.mockImplementation((url) => String(url).includes('/sources') ? Promise.resolve({ sources: [] }) : Promise.resolve({ exists: true, lines: [] }))
  const empty = createRoot(el)
  await act(async () => { empty.render(<LogsPanel />); await Promise.resolve() })
  expect(el.querySelector('[aria-label="Logs"]')?.getAttribute('data-state')).toBe('empty')
  expect(el.textContent).toContain('No matching lines')
  await act(async () => empty.unmount())
  read.mockImplementation((url) => String(url).includes('/sources') ? Promise.resolve({ sources: [] }) : Promise.reject(new Error('offline')))
  const error = createRoot(el)
  await act(async () => { error.render(<LogsPanel />); await Promise.resolve() })
  expect(el.querySelector('[aria-label="Logs"]')?.getAttribute('data-state')).toBe('error')
  expect(el.textContent).toContain('offline')
  await act(async () => error.unmount())
})
