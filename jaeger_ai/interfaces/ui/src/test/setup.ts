/**
 * Vitest Setup File
 *
 * Global test configuration and mocks.
 * Runs before each test file.
 */

import '@testing-library/jest-dom'
import { cleanup } from '@testing-library/react'
import { afterEach, beforeAll, vi } from 'vitest'

// Cleanup after each test
afterEach(() => {
  cleanup()
})

// ─────────────────────────────────────────────────────────────
// Global Mocks
// ─────────────────────────────────────────────────────────────

beforeAll(() => {
  // Mock window.matchMedia (not implemented in jsdom). Must be a real
  // function on BOTH window and globalThis — code checks
  // `typeof matchMedia === 'function'` against the bare global.
  const matchMediaMock = (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    configurable: true,
    value: matchMediaMock,
  })
  ;(globalThis as { matchMedia?: unknown }).matchMedia = matchMediaMock

  // Mock localStorage — implements the full Storage interface (key/length) so
  // tests that assert on localStorage.length work. Methods are defined ON
  // Storage.prototype (not as own properties) so vi.spyOn(Storage.prototype,
  // 'setItem') intercepts calls from the SUT.
  const localStorageStore: Record<string, string> = {}
  const localStorageMock = {
    get length() {
      return Object.keys(localStorageStore).length
    },
    key(index: number) {
      return Object.keys(localStorageStore)[index] ?? null
    },
    getItem(key: string) {
      return key in localStorageStore ? localStorageStore[key] : null
    },
    setItem(key: string, value: string) {
      localStorageStore[key] = value.toString()
    },
    removeItem(key: string) {
      delete localStorageStore[key]
    },
    clear() {
      for (const k of Object.keys(localStorageStore)) delete localStorageStore[k]
    },
  }
  // Expose localStorage as a real Storage-prototype object so
  // vi.spyOn(Storage.prototype, 'setItem') intercepts calls from the SUT.
  // jsdom's Storage has an illegal constructor, so we build the instance via
  // Object.create(Storage.prototype) and override the methods. The methods
  // live on the PROTOTYPE (not as own props) so spies on the prototype work.
  const storageProto = Storage.prototype as Storage
  storageProto.getItem = localStorageMock.getItem
  storageProto.setItem = localStorageMock.setItem
  storageProto.removeItem = localStorageMock.removeItem
  storageProto.clear = localStorageMock.clear
  storageProto.key = localStorageMock.key
  Object.defineProperty(storageProto, 'length', {
    configurable: true,
    get: () => Object.keys(localStorageStore).length,
  })
  const storageInstance = Object.create(Storage.prototype) as Storage
  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    value: storageInstance,
  })
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: storageInstance,
  })

  // Mock IntersectionObserver
  global.IntersectionObserver = class IntersectionObserver {
    constructor() {}
    disconnect() {}
    observe() {}
    takeRecords() {
      return []
    }
    unobserve() {}
  }

  // Mock ResizeObserver
  global.ResizeObserver = class ResizeObserver {
    constructor() {}
    disconnect() {}
    observe() {}
    unobserve() {}
  }

  // Mock scrollTo
  window.scrollTo = vi.fn()

  // Mock clipboard
  Object.assign(navigator, {
    clipboard: {
      writeText: vi.fn().mockResolvedValue(undefined),
      readText: vi.fn().mockResolvedValue(''),
    },
  })

  // Mock AudioContext for VoiceOrb tests
  global.AudioContext = class AudioContext {
    createAnalyser() {
      return {
        fftSize: 256,
        frequencyBinCount: 128,
        getByteFrequencyData: vi.fn(),
      }
    }
    createMediaStreamSource() {
      return { connect: vi.fn() }
    }
    close() {
      return Promise.resolve()
    }
  } as any

  // Mock getUserMedia
  Object.defineProperty(navigator, 'mediaDevices', {
    value: {
      getUserMedia: vi.fn().mockResolvedValue({
        getTracks: () => [{ stop: vi.fn() }],
      }),
    },
    writable: true,
  })
})

// ─────────────────────────────────────────────────────────────
// Custom Matchers
// ─────────────────────────────────────────────────────────────

// Add custom matchers if needed
