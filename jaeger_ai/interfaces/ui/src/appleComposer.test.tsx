/**
 * Regression test: the AppleApp chat composer must enable the Send button
 * when the user types, and the textarea value must be bound to React state.
 *
 * This guards against the controlled-input bug where typing into the
 * textarea did not update React state (send button stayed disabled).
 */
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

afterEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})

// Mock the gateway client so AppleApp doesn't try to connect.
vi.mock('./lib/gateway-client', () => ({
  GatewayClient: class {
    connect() { return Promise.reject(new Error('no gateway in test')) }
    disconnect() {}
    sendMessage() { return Promise.resolve({}) }
    on() { return () => {} }
  },
}))

async function mountAppleApp() {
  const { AppleApp } = await import('./AppleApp')
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  await act(async () => { root.render(<AppleApp />) })
  return {
    host,
    close: async () => { await act(async () => { root.unmount() }); host.remove() },
  }
}

function findComposer(host: HTMLElement): HTMLTextAreaElement {
  const t = Array.from(host.querySelectorAll('textarea')).find(
    (x) => x.placeholder && x.placeholder.includes('Message')
  )
  if (!t) throw new Error('composer textarea not found')
  return t
}

function findSendButton(host: HTMLElement): HTMLButtonElement {
  const b = host.querySelector('button[aria-label="Send message"]')
  if (!b) throw new Error('send button not found')
  return b as HTMLButtonElement
}

describe('AppleApp composer', () => {
  it('enables Send when the user types into the composer', async () => {
    const page = await mountAppleApp()
    try {
      const textarea = findComposer(page.host)
      const send = findSendButton(page.host)
      expect(send.disabled).toBe(true)

      // Type using the native setter so React's onChange fires.
      await act(async () => {
        const setter = Object.getOwnPropertyDescriptor(
          window.HTMLTextAreaElement.prototype, 'value'
        )!.set!
        setter.call(textarea, 'Hello Jaeger')
        textarea.dispatchEvent(new Event('input', { bubbles: true }))
      })

      expect(textarea.value).toBe('Hello Jaeger')
      expect(send.disabled).toBe(false)
    } finally {
      await page.close()
    }
  })

  it('disables Send again when the composer is cleared', async () => {
    const page = await mountAppleApp()
    try {
      const textarea = findComposer(page.host)
      const send = findSendButton(page.host)

      await act(async () => {
        const setter = Object.getOwnPropertyDescriptor(
          window.HTMLTextAreaElement.prototype, 'value'
        )!.set!
        setter.call(textarea, 'something')
        textarea.dispatchEvent(new Event('input', { bubbles: true }))
      })
      expect(send.disabled).toBe(false)

      await act(async () => {
        const setter = Object.getOwnPropertyDescriptor(
          window.HTMLTextAreaElement.prototype, 'value'
        )!.set!
        setter.call(textarea, '')
        textarea.dispatchEvent(new Event('input', { bubbles: true }))
      })
      expect(send.disabled).toBe(true)
    } finally {
      await page.close()
    }
  })

  it('renders the character card images in the sidebar', async () => {
    const page = await mountAppleApp()
    try {
      // The sidebar should show character avatars (Jarvis, Lilith, Kamina).
      const imgs = Array.from(page.host.querySelectorAll('img')).filter(
        (i) => i.getAttribute('src') && i.getAttribute('src')!.includes('/characters/')
      )
      expect(imgs.length).toBeGreaterThan(0)
      // Every sidebar character image must have a non-empty src.
      for (const img of imgs) {
        expect(img.getAttribute('src')).toBeTruthy()
      }
    } finally {
      await page.close()
    }
  })
})
