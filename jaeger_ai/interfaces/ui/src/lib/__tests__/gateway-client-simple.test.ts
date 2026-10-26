/**
 * Simplified GatewayClient Tests — No hanging WebSocket mocks
 *
 * These tests focus on the HTTP API surface and basic functionality
 * without complex WebSocket lifecycle mocking.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { GatewayClient } from '../gateway-client'

// Mock fetch
global.fetch = vi.fn() as any

// Mock WebSocket that doesn't hang
class MockWebSocket {
  static CONNECTING = 0
  static OPEN = 1
  static CLOSING = 2
  static CLOSED = 3

  url: string
  readyState = MockWebSocket.CONNECTING
  onopen: (() => void) | null = null
  onclose: ((event: any) => void) | null = null
  onerror: ((event: any) => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  sentMessages: string[] = []
  closed = false

  constructor(url: string) {
    this.url = url
  }

  // Immediately ready - no setTimeout
  connect() {
    this.readyState = MockWebSocket.OPEN
    if (this.onopen) this.onopen()
  }

  send(data: string) {
    this.sentMessages.push(data)
  }

  close() {
    this.readyState = MockWebSocket.CLOSED
    this.closed = true
    if (this.onclose) this.onclose({ code: 1000, reason: 'Normal' })
  }

  simulateMessage(data: any) {
    if (this.onmessage) {
      this.onmessage({ data: JSON.stringify(data) })
    }
  }
}

describe('GatewayClient (Simplified)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // @ts-ignore
    global.WebSocket = MockWebSocket as any
  })

  afterEach(() => {
    vi.clearAllTimers()
  })

  describe('constructor', () => {
    it('creates client with default config', () => {
      const client = new GatewayClient({ baseUrl: 'http://127.0.0.1:33418' })
      expect(client).toBeDefined()
      expect(client.sessions).toBeDefined()
      expect(client.chat).toBeDefined()
      expect(client.tools).toBeDefined()
      expect(client.files).toBeDefined()
      expect(client.memory).toBeDefined()
      expect(client.agents).toBeDefined()
      expect(client.models).toBeDefined()
    })

    it('creates client with custom config', () => {
      const client = new GatewayClient({
        baseUrl: 'http://custom:8080',
        wsUrl: 'ws://custom:8080/ws',
        token: 'test-token',
        autoReconnect: false,
      })
      expect(client).toBeDefined()
    })
  })

  describe('connection state', () => {
    it('starts disconnected', () => {
      const client = new GatewayClient({ baseUrl: 'http://127.0.0.1:33418' })
      expect(client.isConnected()).toBe(false)
    })

    it('can disconnect without being connected', () => {
      const client = new GatewayClient({ baseUrl: 'http://127.0.0.1:33418' })
      expect(() => client.disconnect()).not.toThrow()
    })
  })

  describe('HTTP API methods', () => {
    let client: GatewayClient

    beforeEach(() => {
      client = new GatewayClient({
        baseUrl: 'http://127.0.0.1:33418',
        autoReconnect: false,
      })
    })

    it('sessions.list calls correct endpoint', async () => {
      ;(global.fetch as any).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ sessions: [{ id: '1', title: 'Test' }] }),
      })

      const result = await client.sessions.list()
      expect(result).toEqual([{ id: '1', title: 'Test' }])
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/v1/sessions'),
        expect.objectContaining({ method: 'GET' })
      )
    })

    it('sessions.create sends POST with body', async () => {
      ;(global.fetch as any).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ id: 'new-1', title: 'My Chat' }),
      })

      const result = await client.sessions.create({ title: 'My Chat' })
      expect(result.title).toBe('My Chat')
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/v1/sessions'),
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ title: 'My Chat' }),
        })
      )
    })

    it('chat.send sends message', async () => {
      ;(global.fetch as any).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ turnId: 't-1', response: 'Hello!' }),
      })

      const result = await client.chat.send({
        sessionId: 's-1',
        message: 'Hi there',
      })

      expect(result.content).toBe('Hello!')
      // Check that fetch was called with POST method (URL format may vary)
      expect(global.fetch).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({ method: 'POST' })
      )
    })

    it('tools.list returns tools array', async () => {
      ;(global.fetch as any).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ tools: [{ name: 'read_file' }, { name: 'write_file' }] }),
      })

      const tools = await client.tools.list()
      expect(tools).toHaveLength(2)
      expect(tools[0].name).toBe('read_file')
    })

    it('tools.invoke calls tool with arguments', async () => {
      ;(global.fetch as any).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ result: 'success' }),
      })

      const result = await client.tools.invoke('test_tool', { arg: 'value' })
      expect(result.result).toBe('success')
    })

    it('files.list returns files', async () => {
      ;(global.fetch as any).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ files: [{ name: 'a.txt' }, { name: 'b.ts' }] }),
      })

      const files = await client.files.list('.')
      expect(files).toHaveLength(2)
    })

    it('files.read returns content', async () => {
      ;(global.fetch as any).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ content: 'file contents here' }),
      })

      const content = await client.files.read('test.txt')
      expect(content).toBe('file contents here')
    })

    it('memory.search returns results', async () => {
      ;(global.fetch as any).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ results: [{ id: '1', content: 'fact' }] }),
      })

      const results = await client.memory.search('query')
      expect(results).toHaveLength(1)
    })

    it('memory.remember sends content', async () => {
      ;(global.fetch as any).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ id: 'mem-1' }),
      })

      const result = await client.memory.remember('Important fact')
      expect(result.id).toBe('mem-1')
    })

    it('agents.list returns agents', async () => {
      ;(global.fetch as any).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ agents: [{ id: 'a-1', name: 'Jaeger' }] }),
      })

      const agents = await client.agents.list()
      expect(agents).toHaveLength(1)
      expect(agents[0].name).toBe('Jaeger')
    })

    it('models.list returns models', async () => {
      ;(global.fetch as any).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ models: [{ id: 'gemma4:12b' }, { id: 'gpt-4' }] }),
      })

      const models = await client.models.list()
      expect(models).toHaveLength(2)
    })

    it('models.set sends model preference', async () => {
      ;(global.fetch as any).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ success: true }),
      })

      await client.models.set('gpt-4')
      expect(global.fetch).toHaveBeenCalled()
    })
  })

  describe('error handling', () => {
    let client: GatewayClient

    beforeEach(() => {
      client = new GatewayClient({ baseUrl: 'http://127.0.0.1:33418' })
    })

    it('throws on HTTP error', async () => {
      ;(global.fetch as any).mockResolvedValueOnce({
        ok: false,
        status: 404,
        json: async () => ({ error: 'Not found' }),
      })

      await expect(client.sessions.get('nonexistent')).rejects.toThrow()
    })

    it('throws on network error', async () => {
      ;(global.fetch as any).mockRejectedValueOnce(new Error('Network error'))

      await expect(client.sessions.list()).rejects.toThrow('Network error')
    })

    it('throws on invalid JSON', async () => {
      ;(global.fetch as any).mockResolvedValueOnce({
        ok: true,
        json: async () => { throw new Error('Invalid JSON') },
      })

      await expect(client.sessions.list()).rejects.toThrow()
    })
  })

  describe('request headers', () => {
    it('includes token in Authorization header when provided', async () => {
      const client = new GatewayClient({
        baseUrl: 'http://127.0.0.1:33418',
        token: 'my-secret-token',
      })

      ;(global.fetch as any).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ sessions: [] }),
      })

      await client.sessions.list()

      expect(global.fetch).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          headers: expect.objectContaining({
            Authorization: 'Bearer my-secret-token',
          }),
        })
      )
    })

    it('includes Content-Type for POST requests', async () => {
      const client = new GatewayClient({ baseUrl: 'http://127.0.0.1:33418' })

      ;(global.fetch as any).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ id: 'new' }),
      })

      await client.sessions.create({ title: 'Test' })

      expect(global.fetch).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          headers: expect.objectContaining({
            'Content-Type': 'application/json',
          }),
        })
      )
    })
  })

  describe('default client singleton', () => {
    it('getDefaultClient returns a client', async () => {
      const { getDefaultClient } = await import('../gateway-client')
      const client = getDefaultClient()
      expect(client).toBeDefined()
      expect(client instanceof GatewayClient).toBe(true)
    })

    it('getDefaultClient returns same instance', async () => {
      const { getDefaultClient } = await import('../gateway-client')
      const client1 = getDefaultClient()
      const client2 = getDefaultClient()
      expect(client1).toBe(client2)
    })

    it('setDefaultClient overrides singleton', async () => {
      const { getDefaultClient, setDefaultClient } = await import('../gateway-client')
      const custom = new GatewayClient({ baseUrl: 'http://custom:9999' })
      setDefaultClient(custom)
      expect(getDefaultClient()).toBe(custom)
    })
  })
})
