import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { ResourcesCard } from './ResourcesCard'
import { getJson } from '../unified/webui'

vi.mock('../unified/webui', () => ({ getJson: vi.fn() }))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const read = vi.mocked(getJson)
afterEach(() => read.mockReset())

it('maps loading and error to WidgetCard states', async () => {
  read.mockImplementation(() => new Promise(() => {}))
  const el = document.createElement('div'); const root = createRoot(el)
  await act(async () => root.render(<ResourcesCard />))
  expect(el.querySelector('[aria-label="Resources"]')?.getAttribute('data-state')).toBe('loading')
  await act(async () => root.unmount())
  read.mockRejectedValueOnce(new Error('offline'))
  const second = createRoot(el)
  await act(async () => { second.render(<ResourcesCard />); await Promise.resolve() })
  expect(el.querySelector('[aria-label="Resources"]')?.getAttribute('data-state')).toBe('error')
  expect(el.textContent).toContain('offline')
  await act(async () => second.unmount())
})
