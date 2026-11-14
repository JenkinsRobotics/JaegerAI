import { describe, expect, it } from 'vitest'
import { embedUrl } from './EnginePanel'

describe('embedUrl', () => {
  it('points at the loopback embed proxy on the Mac', () => {
    expect(embedUrl('openclaw', '127.0.0.1')).toBe('http://127.0.0.1:8797/__jaeger/start')
    expect(embedUrl('openclaw', 'localhost')).toBe('http://127.0.0.1:8797/__jaeger/start')
  })
  it('never offers the embed off the Mac', () => {
    expect(embedUrl('openclaw', 'matthews-mac-studio.tail80f206.ts.net')).toBeNull()
  })
})
