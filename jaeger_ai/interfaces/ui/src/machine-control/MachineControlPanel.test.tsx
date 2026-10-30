import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { it, expect, vi } from 'vitest'
import { MachineControlPanel } from './MachineControlPanel'
import type { JaegerSource } from '../api/source'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

it('renders Machine Control panel with host and OS permission telemetry', async () => {
  const source = {
    computers: vi.fn().mockResolvedValue({
      scope: 'gateway_process_only',
      computers: [
        {
          id: 'host-unit-01',
          kind: 'local_gateway',
          state: 'serving',
          process_id: 1337,
          os: 'macOS',
          architecture: 'arm64',
          screen_view: 'standard_window',
          input_authorization: 'authorized',
          os_permissions: 'granted',
          recovery: 'supported',
        },
      ],
      hosted: { state: 'ready', allocation_supported: true },
      limits: [],
    }),
  } as unknown as JaegerSource

  const post = vi.fn(async (type: string) => {
    if (type === 'computer.status') {
      return {
        scope: 'native_shell_process',
        process_id: 999,
        screen_os_permission: 'granted',
        input_os_permission: 'granted',
      }
    }
    return {}
  })

  const prior = window.jaegerNative
  window.jaegerNative = { post }
  const el = document.createElement('div')
  document.body.append(el)
  const root = createRoot(el)

  try {
    await act(async () => root.render(<MachineControlPanel source={source} />))
    expect(el.textContent).toContain('Machine Control & Hardware Telemetry')
    expect(el.textContent).toContain('host-unit-01')
    expect(el.textContent).toContain('1337')
    expect(el.textContent).toContain('Native Shell PID')

    // Switch to OS Settings sub-tab
    const buttons = el.querySelectorAll('button')
    const osSettingsBtn = [...buttons].find((b) => b.textContent?.includes('OS Settings'))
    expect(osSettingsBtn).toBeDefined()
    await act(async () => osSettingsBtn!.click())
    expect(el.textContent).toContain('macOS Privacy & Security Shortcut Panes')
  } finally {
    await act(async () => root.unmount())
    el.remove()
    window.jaegerNative = prior
  }
})

