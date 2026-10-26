/**
 * Jaeger Gateway Client — Unified API client for frontend.
 *
 * Supports both HTTP (REST) and WebSocket transports.
 * Automatically falls back to HTTP if WebSocket fails.
 *
 * Usage:
 *   import { GatewayClient } from './lib/gateway-client'
 *
 *   const client = new GatewayClient('http://127.0.0.1:33418')
 *   await client.connect()
 *
 *   // Sessions
 *   const sessions = await client.sessions.list()
 *   const session = await client.sessions.create({ title: 'New Chat' })
 *
 *   // Chat with streaming
 *   await client.chat.send({
 *     sessionId: session.id,
 *     message: 'Hello!',
 *     onDelta: (text) => console.log(text),
 *     onDone: () => console.log('Done'),
 *   })
 *
 *   // Real-time events
 *   client.on('turn.delta', (event) => console.log(event.payload))
 *   client.on('tool.call', (event) => console.log(event.payload))
 */

// ─────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────

export interface GatewayConfig {
  baseUrl: string
  wsUrl?: string
  token?: string
  autoReconnect?: boolean
  reconnectDelay?: number
}

export interface Session {
  id: string
  title: string
  createdAt: number
  updatedAt: number
  messageCount: number
  agentId?: string
  metadata?: Record<string, any>
}

export interface Message {
  id: string
  sessionId: string
  role: 'user' | 'assistant' | 'system' | 'tool'
  content: string
  timestamp: number
  toolCalls?: ToolCall[]
  toolResults?: ToolResult[]
  metadata?: Record<string, any>
}

export interface ToolCall {
  id: string
  name: string
  arguments: Record<string, any>
  status?: 'pending' | 'running' | 'completed' | 'failed'
}

export interface ToolResult {
  toolCallId: string
  result: any
  error?: string
}

export interface ChatSendOptions {
  sessionId: string
  message: string
  stream?: boolean
  model?: string
  onDelta?: (text: string) => void
  onToolCall?: (call: ToolCall) => void
  onToolResult?: (result: ToolResult) => void
  onDone?: (message: Message) => void
  onError?: (error: Error) => void
}

export interface GatewayEvent {
  type: string
  payload: any
  seq?: number
  timestamp?: number
}

type EventHandler = (event: GatewayEvent) => void

// ─────────────────────────────────────────────────────────────
// WebSocket Message Types
// ─────────────────────────────────────────────────────────────

interface WSRequest {
  type: 'req'
  id: string
  method: string
  params?: Record<string, any>
}

interface WSResponse {
  type: 'res'
  id: string
  ok: boolean
  payload?: any
  error?: { message: string; code: number }
}

interface WSEvent {
  type: 'event'
  event: string
  payload?: any
  seq?: number
}

// ─────────────────────────────────────────────────────────────
// Gateway Client
// ─────────────────────────────────────────────────────────────

export class GatewayClient {
  private config: Required<GatewayConfig>
  private ws: WebSocket | null = null
  private connected = false
  private reconnectAttempts = 0
  private requestId = 0
  private pendingRequests = new Map<string, {
    resolve: (value: any) => void
    reject: (error: Error) => void
    timeout: ReturnType<typeof setTimeout>
  }>()
  private eventHandlers = new Map<string, Set<EventHandler>>()
  private globalHandlers = new Set<EventHandler>()
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null

  // Resource APIs
  public sessions: SessionsAPI
  public chat: ChatAPI
  public tools: ToolsAPI
  public files: FilesAPI
  public memory: MemoryAPI
  public agents: AgentsAPI
  public models: ModelsAPI

  constructor(config: GatewayConfig) {
    this.config = {
      baseUrl: config.baseUrl,
      wsUrl: config.wsUrl || config.baseUrl.replace(/^http/, 'ws') + '/ws',
      token: config.token || '',
      autoReconnect: config.autoReconnect ?? true,
      reconnectDelay: config.reconnectDelay || 3000,
    }

    // Initialize resource APIs
    this.sessions = new SessionsAPI(this)
    this.chat = new ChatAPI(this)
    this.tools = new ToolsAPI(this)
    this.files = new FilesAPI(this)
    this.memory = new MemoryAPI(this)
    this.agents = new AgentsAPI(this)
    this.models = new ModelsAPI(this)
  }

  // ─────────────────────────────────────────────────────────────
  // Connection Management
  // ─────────────────────────────────────────────────────────────

  async connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      try {
        this.ws = new WebSocket(this.config.wsUrl)
        this.ws.onopen = () => {
          this.connected = true
          this.reconnectAttempts = 0
          console.log('[Gateway] WebSocket connected')
          resolve()
        }
        this.ws.onclose = (event) => {
          this.connected = false
          console.log('[Gateway] WebSocket closed:', event.code, event.reason)
          this._handleDisconnect()
        }
        this.ws.onerror = (error) => {
          console.error('[Gateway] WebSocket error:', error)
          if (!this.connected) {
            reject(new Error('WebSocket connection failed'))
          }
        }
        this.ws.onmessage = (event) => {
          this._handleMessage(event.data)
        }
      } catch (error) {
        reject(error)
      }
    })
  }

  disconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    if (this.ws) {
      this.ws.close()
      this.ws = null
    }
    this.connected = false
  }

  isConnected(): boolean {
    return this.connected
  }

  private _handleDisconnect(): void {
    // Reject pending requests
    for (const [id, pending] of this.pendingRequests) {
      clearTimeout(pending.timeout)
      pending.reject(new Error('Connection lost'))
    }
    this.pendingRequests.clear()

    // Reconnect
    if (this.config.autoReconnect) {
      this.reconnectAttempts++
      const delay = this.config.reconnectDelay * Math.min(this.reconnectAttempts, 5)
      console.log(`[Gateway] Reconnecting in ${delay}ms... (attempt ${this.reconnectAttempts})`)
      this.reconnectTimer = setTimeout(() => {
        this.connect().catch(console.error)
      }, delay)
    }
  }

  private _handleMessage(data: string): void {
    try {
      const message = JSON.parse(data)

      switch (message.type) {
        case 'res': {
          // Response to a request
          const pending = this.pendingRequests.get(message.id)
          if (pending) {
            clearTimeout(pending.timeout)
            this.pendingRequests.delete(message.id)
            if (message.ok) {
              pending.resolve(message.payload)
            } else {
              pending.reject(new Error(message.error?.message || 'Request failed'))
            }
          }
          break
        }

        case 'event': {
          // Server-pushed event
          const event: GatewayEvent = {
            type: message.event,
            payload: message.payload,
            seq: message.seq,
            timestamp: Date.now(),
          }

          // Dispatch to specific handlers
          const handlers = this.eventHandlers.get(message.event)
          if (handlers) {
            handlers.forEach(h => h(event))
          }

          // Dispatch to global handlers
          this.globalHandlers.forEach(h => h(event))
          break
        }

        case 'pong':
          // Keep-alive response
          break

        default:
          console.warn('[Gateway] Unknown message type:', message.type)
      }
    } catch (error) {
      console.error('[Gateway] Failed to parse message:', error)
    }
  }

  // ─────────────────────────────────────────────────────────────
  // RPC Methods
  // ─────────────────────────────────────────────────────────────

  /**
   * Make a WebSocket RPC request.
   * Falls back to HTTP if WebSocket is not connected.
   */
  async request<T = any>(method: string, params?: Record<string, any>): Promise<T> {
    // Try WebSocket first
    if (this.connected && this.ws) {
      return this._wsRequest<T>(method, params)
    }

    // Fall back to HTTP
    return this._httpRequest<T>(method, params)
  }

  private _wsRequest<T>(method: string, params?: Record<string, any>): Promise<T> {
    return new Promise((resolve, reject) => {
      const id = `req-${++this.requestId}-${Date.now()}`
      const request: WSRequest = {
        type: 'req',
        id,
        method,
        params,
      }

      // Set timeout
      const timeout = setTimeout(() => {
        this.pendingRequests.delete(id)
        reject(new Error(`Request timeout: ${method}`))
      }, 30000)

      this.pendingRequests.set(id, { resolve, reject, timeout })

      this.ws!.send(JSON.stringify(request))
    })
  }

  private async _httpRequest<T>(method: string, params?: Record<string, any>): Promise<T> {
    // Convert RPC method to HTTP endpoint
    // e.g., "sessions.list" → GET /v1/sessions
    const [resource, action] = method.split('.')
    const endpoint = this._methodToEndpoint(method)

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    }
    if (this.config.token) {
      headers['Authorization'] = `Bearer ${this.config.token}`
    }

    let url = `${this.config.baseUrl}${endpoint}`
    let options: RequestInit = { headers }

    if (action === 'list' || action === 'get' || !params) {
      options.method = 'GET'
      if (params) {
        url += '?' + new URLSearchParams(params).toString()
      }
    } else {
      options.method = 'POST'
      options.body = JSON.stringify(params)
    }

    const response = await fetch(url, options)
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`)
    }

    return response.json()
  }

  private _methodToEndpoint(method: string): string {
    const map: Record<string, string> = {
      'sessions.list': '/v1/sessions',
      'sessions.get': '/v1/sessions/:id',
      'sessions.create': '/v1/sessions',
      'sessions.delete': '/v1/sessions/:id',
      'agents.list': '/v1/agents',
      'agents.get': '/v1/agents/:id',
      'tools.list': '/v1/tools',
      'files.list': '/v1/files',
      'models.list': '/v1/models',
      'health': '/health',
    }
    return map[method] || `/v1/${method.replace('.', '/')}`
  }

  // ─────────────────────────────────────────────────────────────
  // Event Subscriptions
  // ─────────────────────────────────────────────────────────────

  on(eventType: string, handler: EventHandler): () => void {
    if (!this.eventHandlers.has(eventType)) {
      this.eventHandlers.set(eventType, new Set())
    }
    this.eventHandlers.get(eventType)!.add(handler)

    // Return unsubscribe function
    return () => {
      this.eventHandlers.get(eventType)?.delete(handler)
    }
  }

  onAny(handler: EventHandler): () => void {
    this.globalHandlers.add(handler)
    return () => {
      this.globalHandlers.delete(handler)
    }
  }

  off(eventType: string, handler: EventHandler): void {
    this.eventHandlers.get(eventType)?.delete(handler)
  }

  // ─────────────────────────────────────────────────────────────
  // Streaming Chat
  // ─────────────────────────────────────────────────────────────

  /**
   * Send a chat message with streaming response.
   * Uses WebSocket for streaming, falls back to SSE if needed.
   */
  async *streamChat(options: ChatSendOptions): AsyncGenerator<GatewayEvent, void, unknown> {
    const requestId = `chat-${Date.now()}`
    let done = false
    let error: Error | null = null
    const events: GatewayEvent[] = []

    const handler = (event: GatewayEvent) => {
      if (event.payload?.requestId === requestId) {
        events.push(event)
        if (event.type === 'chat.delta' && options.onDelta) {
          options.onDelta(event.payload.delta?.content || '')
        } else if (event.type === 'chat.done') {
          done = true
          if (options.onDone) {
            options.onDone({
              id: event.payload.messageId,
              sessionId: options.sessionId,
              role: 'assistant',
              content: '', // Accumulated in onDelta
              timestamp: Date.now(),
            })
          }
        } else if (event.type === 'chat.error') {
          error = new Error(event.payload?.error || 'Chat error')
          done = true
        }
      }
    }

    this.onAny(handler)

    try {
      // Send the message
      await this.request('chat.sendStream', {
        requestId,
        sessionId: options.sessionId,
        messages: [{ role: 'user', content: options.message }],
        stream: true,
      })

      // Yield events until done
      while (!done && !error) {
        while (events.length > 0) {
          const event = events.shift()!
          yield event
        }
        await new Promise(r => setTimeout(r, 50))
      }

      // Yield remaining events
      while (events.length > 0) {
        const event = events.shift()!
        yield event
      }

      if (error) {
        if (options.onError) options.onError(error)
        throw error
      }
    } finally {
      this.globalHandlers.delete(handler)
    }
  }
}

// ─────────────────────────────────────────────────────────────
// Resource APIs
// ─────────────────────────────────────────────────────────────

class BaseAPI {
  constructor(protected client: GatewayClient) {}
}

class SessionsAPI extends BaseAPI {
  async list(limit = 50): Promise<Session[]> {
    const result = await this.client.request('sessions.list', { limit })
    return result.sessions || []
  }

  async get(sessionId: string): Promise<Session> {
    return this.client.request('sessions.get', { sessionId })
  }

  async create(options: { title?: string; agentId?: string } = {}): Promise<Session> {
    return this.client.request('sessions.create', options)
  }

  async delete(sessionId: string): Promise<void> {
    await this.client.request('sessions.delete', { sessionId })
  }

  async *send(options: ChatSendOptions): AsyncGenerator<GatewayEvent> {
    yield* this.client.streamChat(options)
  }
}

class ChatAPI extends BaseAPI {
  async send(options: ChatSendOptions): Promise<Message> {
    // Non-streaming version
    const result = await this.client.request('sessions.send', {
      sessionId: options.sessionId,
      message: options.message,
    })
    return {
      id: result.turnId,
      sessionId: options.sessionId,
      role: 'assistant',
      content: result.response,
      timestamp: Date.now(),
    }
  }

  async *sendStream(options: ChatSendOptions): AsyncGenerator<GatewayEvent> {
    yield* this.client.streamChat(options)
  }
}

class ToolsAPI extends BaseAPI {
  async list(): Promise<any[]> {
    const result = await this.client.request('tools.list')
    return result.tools || []
  }

  async invoke(name: string, args: Record<string, any>): Promise<any> {
    return this.client.request('tools.invoke', { name, arguments: args })
  }
}

class FilesAPI extends BaseAPI {
  async list(path = '.'): Promise<any[]> {
    const result = await this.client.request('files.list', { path })
    return result.files || []
  }

  async read(path: string): Promise<string> {
    const result = await this.client.request('files.read', { path })
    return result.content
  }

  async upload(filename: string, content: string | Blob): Promise<any> {
    if (content instanceof Blob) {
      const buffer = await content.arrayBuffer()
      const base64 = btoa(String.fromCharCode(...new Uint8Array(buffer)))
      return this.client.request('files.upload', { filename, content: base64 })
    }
    return this.client.request('files.upload', { filename, content })
  }
}

class MemoryAPI extends BaseAPI {
  async search(query: string, limit = 10): Promise<any[]> {
    const result = await this.client.request('memory.search', { query, limit })
    return result.results || []
  }

  async remember(content: string, metadata?: Record<string, any>): Promise<any> {
    return this.client.request('memory.remember', { content, metadata })
  }
}

class AgentsAPI extends BaseAPI {
  async list(): Promise<any[]> {
    const result = await this.client.request('agents.list')
    return result.agents || []
  }

  async get(agentId: string): Promise<any> {
    return this.client.request('agents.get', { agentId })
  }
}

class ModelsAPI extends BaseAPI {
  async list(): Promise<any[]> {
    const result = await this.client.request('models.list')
    return result.models || []
  }

  async set(model: string): Promise<void> {
    await this.client.request('models.set', { model })
  }
}

// ─────────────────────────────────────────────────────────────
// Singleton instance (optional)
// ─────────────────────────────────────────────────────────────

let defaultClient: GatewayClient | null = null

export function getDefaultClient(): GatewayClient {
  if (!defaultClient) {
    defaultClient = new GatewayClient({
      baseUrl: 'http://127.0.0.1:33418',
    })
  }
  return defaultClient
}

export function setDefaultClient(client: GatewayClient): void {
  defaultClient = client
}
