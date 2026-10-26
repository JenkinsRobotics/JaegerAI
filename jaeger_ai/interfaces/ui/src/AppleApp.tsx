/**
 * AppleApp — Apple-Native UI for JaegerAI (Self-Contained)
 *
 * This is the new production UI, built with:
 * - Apple Human Interface Guidelines
 * - ChatGPT-style message design (no assistant bubbles)
 * - SF Pro typography
 * - System colors
 * - Smooth animations
 *
 * Access with: ?ui=apple or set localStorage jaeger.ui.apple=1
 *
 * Self-contained — only uses react, react-markdown, remark-gfm, and our Icons.
 */

import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { GatewayClient } from './lib/gateway-client'
import { VoiceOrb, VoiceButton, Waveform, useAudioLevel } from './components/VoiceOrb'
import { CreateAgentModal } from './components/CreateAgentModal'
import { PinnedAgents, usePins, type PinnableAgent } from './components/PinnedAgents'
import { AgentContextMenu, useContextMenu, type ContextMenuAgent } from './components/AgentContextMenu'
import { SearchPalette, useSearchPalette } from './components/SearchPalette'
import type { CharacterTemplate } from './components/CharacterGallery'
import './theme/apple-app.css'
import {
  Send,
  Paperclip,
  Mic,
  Square,
  Plus,
  Search,
  Settings,
  Menu,
  X,
  Copy,
  Check,
  RefreshCw,
  ThumbsUp,
  ThumbsDown,
  MoreHorizontal,
  Sun,
  Moon,
  ChevronLeft,
  ChevronRight,
  UserPlus,
  Star,
  Wrench,
} from './components/Icons'

// ─────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────

interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: number
  isStreaming?: boolean
  isGrouped?: boolean
  error?: string
}

interface Agent {
  id: string
  name: string
  displayName?: string
  avatar?: string
  status?: string
  isOnline?: boolean
  isPrimary?: boolean
  isPinned?: boolean
  lastMessage?: string
  unreadCount?: number
  role: 'lead' | 'specialist' | 'character' | 'runtime'
  agentType?: 'lead' | 'specialist' | 'character'
  templateId?: string
  cardUrl?: string | null
  personality?: {
    name: string
    voiceTone: string
    backstory?: string
    quotes?: string[]
  }
  effectiveTools?: string[] | null
  toolCount?: number
}

// ─────────────────────────────────────────────────────────────
// Utils
// ─────────────────────────────────────────────────────────────

function cn(...classes: (string | undefined | null | false)[]): string {
  return classes.filter(Boolean).join(' ')
}

function formatTime(ts: number): string {
  const date = new Date(ts)
  const now = new Date()
  const diff = now.getTime() - date.getTime()
  const minutes = Math.floor(diff / 60000)
  const hours = Math.floor(diff / 3600000)
  const days = Math.floor(diff / 86400000)

  if (minutes < 1) return 'Just now'
  if (minutes < 60) return `${minutes}m ago`
  if (hours < 24) return `${hours}h ago`
  if (days < 7) return `${days}d ago`
  return date.toLocaleDateString()
}

// ─────────────────────────────────────────────────────────────
// Theme Hook
// ─────────────────────────────────────────────────────────────

function useTheme() {
  const [theme, setTheme] = useState<'light' | 'dark' | 'system'>(() => {
    const stored = localStorage.getItem('jaeger.theme')
    return (stored as 'light' | 'dark' | 'system') || 'system'
  })

  useEffect(() => {
    const root = document.documentElement
    const applyTheme = (t: 'light' | 'dark' | 'system') => {
      if (t === 'system') {
        const isDark = window.matchMedia('(prefers-color-scheme: dark)').matches
        root.classList.toggle('dark', isDark)
      } else {
        root.classList.toggle('dark', t === 'dark')
      }
    }
    applyTheme(theme)
    localStorage.setItem('jaeger.theme', theme)
  }, [theme])

  return { theme, setTheme }
}

// ─────────────────────────────────────────────────────────────
// Sparkles Icon (for logo)
// ─────────────────────────────────────────────────────────────

function SparklesIcon({ size = 24, className = '' }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <path d="M12 3l1.9 5.8a2 2 0 0 0 1.3 1.3L21 12l-5.8 1.9a2 2 0 0 0-1.3 1.3L12 21l-1.9-5.8a2 2 0 0 0-1.3-1.3L3 12l5.8-1.9a2 2 0 0 0 1.3-1.3L12 3z" />
    </svg>
  )
}

// ─────────────────────────────────────────────────────────────
// Mock Data Hook
// ─────────────────────────────────────────────────────────────

function useMockData() {
  const [agents, setAgents] = useState<Agent[]>([
    {
      id: 'jaeger-main',
      name: 'Jaeger',
      status: 'AI Companion',
      isOnline: true,
      isPrimary: true,
      agentType: 'lead',
      lastMessage: 'Ready to help!',
    },
    {
      id: 'jarvis',
      name: 'Jarvis',
      status: 'AI Butler',
      isOnline: false,
      agentType: 'specialist',
      templateId: 'jarvis',
    },
    {
      id: 'lilith',
      name: 'Lilith',
      status: 'Self-aware AI',
      isOnline: false,
      agentType: 'specialist',
      templateId: 'lilith',
    },
  ])

  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [isGenerating, setIsGenerating] = useState(false)

  return { agents, setAgents, messages, setMessages, isGenerating, setIsGenerating }
}

// ─────────────────────────────────────────────────────────────
// Components
// ─────────────────────────────────────────────────────────────

/** Theme Toggle Button */
function ThemeToggle() {
  const { theme, setTheme } = useTheme()

  const cycleTheme = () => {
    setTheme(theme === 'light' ? 'dark' : theme === 'dark' ? 'system' : 'light')
  }

  return (
    <button
      className="icon-button"
      onClick={cycleTheme}
      aria-label={`Current theme: ${theme}. Click to change.`}
      title={`Theme: ${theme}`}
    >
      {theme === 'light' && <Sun size={20} />}
      {theme === 'dark' && <Moon size={20} />}
      {theme === 'system' && <SparklesIcon size={20} />}
    </button>
  )
}

/** Sidebar */
function Sidebar({
  agents,
  activeAgentId,
  onSelectAgent,
  onNewChat,
  onCreateAgent,
  collapsed,
  onToggleCollapse,
}: {
  agents: Agent[]
  activeAgentId: string
  onSelectAgent: (id: string) => void
  onNewChat: () => void
  onCreateAgent: () => void
  collapsed: boolean
  onToggleCollapse: () => void
}) {
  // Group agents by type
  const leadAgents = agents.filter(a => a.agentType === 'lead' || a.isPrimary)
  const specialistAgents = agents.filter(a => a.agentType === 'specialist' && !a.isPrimary)
  
  return (
    <aside className={cn('sidebar', collapsed && 'sidebar-collapsed')}>
      {/* Header */}
      <div className="sidebar-header">
        <div className="sidebar-logo">
          <SparklesIcon size={24} />
          {!collapsed && <span className="sidebar-title">Jaeger</span>}
        </div>
        <button
          className="icon-button sidebar-toggle"
          onClick={onToggleCollapse}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}
        </button>
      </div>

      {/* New Chat Button */}
      <div className="sidebar-content">
        <button className="new-chat-button" onClick={onNewChat}>
          <Plus size={18} />
          {!collapsed && <span>New Chat</span>}
        </button>
      </div>

      {/* Create Agent Button */}
      <div className="sidebar-content" style={{ paddingTop: 0 }}>
        <button 
          className="new-chat-button create-agent-button"
          onClick={onCreateAgent}
          style={{ 
            background: 'linear-gradient(135deg, #007AFF 0%, #5856D6 100%)',
            color: 'white'
          }}
        >
          <UserPlus size={18} />
          {!collapsed && <span>Create Agent</span>}
        </button>
      </div>

      {/* Agents List */}
      {!collapsed && (
        <>
          {/* Lead Agents */}
          {leadAgents.length > 0 && (
            <div className="sidebar-section">
              <div className="sidebar-section-title">⭐ Lead Agents</div>
              <div className="agent-list">
                {leadAgents.map((agent) => (
                  <AgentItem
                    key={agent.id}
                    agent={agent}
                    isActive={activeAgentId === agent.id}
                    onSelect={() => onSelectAgent(agent.id)}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Specialist Agents */}
          {specialistAgents.length > 0 && (
            <div className="sidebar-section">
              <div className="sidebar-section-title">🔧 Specialists</div>
              <div className="agent-list">
                {specialistAgents.map((agent) => (
                  <AgentItem
                    key={agent.id}
                    agent={agent}
                    isActive={activeAgentId === agent.id}
                    onSelect={() => onSelectAgent(agent.id)}
                  />
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {/* Footer */}
      <div className="sidebar-footer">
        <button className="sidebar-footer-button">
          <Search size={18} />
          {!collapsed && <span>Search</span>}
        </button>
        <button className="sidebar-footer-button">
          <Settings size={18} />
          {!collapsed && <span>Settings</span>}
        </button>
      </div>
    </aside>
  )
}

/** Individual Agent Item in Sidebar */
function AgentItem({
  agent,
  isActive,
  onSelect,
}: {
  agent: Agent
  isActive: boolean
  onSelect: () => void
}) {
  const gradients: Record<string, string> = {
    'jaeger-main': 'linear-gradient(135deg, #007AFF 0%, #5856D6 100%)',
    'jarvis': 'linear-gradient(135deg, #1e3a5f 0%, #2d5a87 100%)',
    'lilith': 'linear-gradient(135deg, #4a148c 0%, #7b1fa2 100%)',
    'kamina': 'linear-gradient(135deg, #d32f2f 0%, #f57c00 100%)',
    'bender': 'linear-gradient(135deg, #616161 0%, #9e9e9e 100%)',
    'glados': 'linear-gradient(135deg, #0277bd 0%, #00acc1 100%)',
  }
  
  const defaultGradient = 'linear-gradient(135deg, #616161 0%, #9e9e9e 100%)'
  const gradient = agent.templateId ? (gradients[agent.templateId] || defaultGradient) : defaultGradient

  return (
    <button
      className={cn('agent-item', isActive && 'agent-item-active')}
      onClick={onSelect}
    >
      <div
        className="agent-avatar"
        style={{ background: gradient }}
      >
        {agent.name[0].toUpperCase()}
        {agent.isOnline && <span className="agent-status-dot" />}
      </div>
      <div className="agent-info">
        <div className="agent-name">{agent.name}</div>
        {agent.status && <div className="agent-status">{agent.status}</div>}
      </div>
      {agent.unreadCount && agent.unreadCount > 0 && (
        <span className="agent-badge">{agent.unreadCount}</span>
      )}
    </button>
  )
}

/** Message Actions */
function MessageActions({ message, onRegenerate }: { message: ChatMessage; onRegenerate: () => void }) {
  const [copied, setCopied] = useState(false)
  const [feedback, setFeedback] = useState<'up' | 'down' | null>(null)

  const handleCopy = useCallback(async () => {
    await navigator.clipboard.writeText(message.content)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }, [message.content])

  if (message.role === 'user') return null

  return (
    <div className="message-actions">
      <button
        className="message-action-button"
        onClick={handleCopy}
        aria-label="Copy message"
        title="Copy"
      >
        {copied ? <Check size={16} /> : <Copy size={16} />}
      </button>
      <button
        className="message-action-button"
        onClick={onRegenerate}
        aria-label="Regenerate response"
        title="Regenerate"
      >
        <RefreshCw size={16} />
      </button>
      <button
        className={cn('message-action-button', feedback === 'up' && 'active')}
        onClick={() => setFeedback(feedback === 'up' ? null : 'up')}
        aria-label="Good response"
        title="Good response"
      >
        <ThumbsUp size={16} />
      </button>
      <button
        className={cn('message-action-button', feedback === 'down' && 'active')}
        onClick={() => setFeedback(feedback === 'down' ? null : 'down')}
        aria-label="Bad response"
        title="Bad response"
      >
        <ThumbsDown size={16} />
      </button>
      <button
        className="message-action-button"
        aria-label="More options"
        title="More"
      >
        <MoreHorizontal size={16} />
      </button>
    </div>
  )
}

/** Single Message */
function Message({ message, onRegenerate }: { message: ChatMessage; onRegenerate: () => void }) {
  const isUser = message.role === 'user'
  const isStreaming = message.isStreaming

  return (
    <div className={cn('message', isUser ? 'message-user' : 'message-assistant')}>
      {!isUser && !message.isGrouped && (
        <div className="message-avatar">
          <SparklesIcon size={18} />
        </div>
      )}
      <div className="message-content-wrapper">
        <div className={cn('message-bubble', isUser ? 'message-bubble-user' : 'message-bubble-assistant')}>
          {isUser ? (
            <div className="message-text">{message.content}</div>
          ) : (
            <div className="message-markdown">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.content}
              </ReactMarkdown>
              {isStreaming && <span className="streaming-cursor" />}
            </div>
          )}
        </div>
        {!isUser && !isStreaming && (
          <MessageActions message={message} onRegenerate={onRegenerate} />
        )}
        <div className="message-timestamp">{formatTime(message.timestamp)}</div>
      </div>
    </div>
  )
}

/** Empty State */
function EmptyState({ onSuggestionClick }: { onSuggestionClick: (text: string) => void }) {
  const suggestions = [
    {
      icon: '✨',
      title: 'Explain something complex',
      description: 'Quantum computing, blockchain, etc.',
      prompt: 'Explain quantum computing in simple terms',
    },
    {
      icon: '💻',
      title: 'Write some code',
      description: 'Python, JavaScript, Swift, and more',
      prompt: 'Write a Python function to sort a list',
    },
    {
      icon: '💡',
      title: 'Brainstorm ideas',
      description: 'Creative projects, business ideas',
      prompt: 'Give me 5 creative project ideas',
    },
    {
      icon: '🔍',
      title: 'Research a topic',
      description: 'Find information on any subject',
      prompt: 'Research the latest AI developments',
    },
  ]

  return (
    <div className="empty-state">
      <div className="empty-state-icon">
        <SparklesIcon size={48} />
      </div>
      <h2 className="empty-state-title">How can I help you today?</h2>
      <p className="empty-state-subtitle">
        I'm Jaeger — your AI companion. Ask me anything, upload files, or let me help with your projects.
      </p>
      <div className="suggestion-grid">
        {suggestions.map((s, i) => (
          <button
            key={i}
            className="suggestion-card"
            onClick={() => onSuggestionClick(s.prompt)}
          >
            <div className="suggestion-icon">
              <span style={{ fontSize: '20px' }}>{s.icon}</span>
            </div>
            <div>
              <div className="suggestion-title">{s.title}</div>
              <div className="suggestion-description">{s.description}</div>
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}

/** Chat Input */
function ChatInput({
  value,
  onChange,
  onSend,
  onStop,
  isGenerating,
}: {
  value: string
  onChange: (v: string) => void
  onSend: () => void
  onStop: () => void
  isGenerating: boolean
}) {
  const [isRecording, setIsRecording] = useState(false)
  const [isVoiceMode, setIsVoiceMode] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const audioLevel = useAudioLevel(isRecording)

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`
    }
  }, [value])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      onSend()
    }
  }

  const toggleVoiceMode = () => {
    setIsVoiceMode(!isVoiceMode)
    if (isRecording) {
      setIsRecording(false)
    }
  }

  // Voice mode: show orb instead of text input
  if (isVoiceMode) {
    return (
      <div className="chat-input-container">
        <div className="voice-mode-container">
          <VoiceButton
            isRecording={isRecording}
            isProcessing={isGenerating}
            audioLevel={audioLevel}
            onToggle={() => setIsRecording(!isRecording)}
            size={120}
          />
          {isRecording && (
            <div className="voice-waveform-container">
              <Waveform audioLevel={audioLevel} height={40} />
              <p className="voice-hint">Speak now...</p>
            </div>
          )}
          {!isRecording && !isGenerating && (
            <p className="voice-hint">Tap the orb to start, tap again to stop</p>
          )}
          <button
            className="voice-exit-button"
            onClick={toggleVoiceMode}
            aria-label="Exit voice mode"
          >
            <X size={20} />
            <span>Back to typing</span>
          </button>
        </div>
        <p className="chat-input-disclaimer">
          Jaeger can make mistakes. Consider verifying important information.
        </p>
      </div>
    )
  }

  return (
    <div className="chat-input-container">
      <div className="chat-input-wrapper">
        <div className="chat-input-actions">
          <button
            className="input-action-button"
            aria-label="Attach file"
            title="Attach file"
          >
            <Paperclip size={20} />
          </button>
          <button
            className={cn('input-action-button', isRecording && 'recording')}
            onClick={toggleVoiceMode}
            aria-label="Voice input"
            title="Voice input"
          >
            <Mic size={20} />
          </button>
        </div>

        <textarea
          ref={textareaRef}
          className="chat-input"
          placeholder="Message Jaeger..."
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={1}
          aria-label="Message input"
        />

        <div className="chat-input-actions">
          {isGenerating ? (
            <button
              className="send-button stop-button"
              onClick={onStop}
              aria-label="Stop generation"
              title="Stop generation"
            >
              <Square size={16} />
            </button>
          ) : (
            <button
              className="send-button"
              onClick={onSend}
              disabled={!value.trim()}
              aria-label="Send message"
              title="Send message (Enter)"
            >
              <Send size={18} />
            </button>
          )}
        </div>
      </div>
      <p className="chat-input-disclaimer">
        Jaeger can make mistakes. Consider verifying important information.
      </p>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────
// Main App Component
// ─────────────────────────────────────────────────────────────

function AppleAppContent() {
  const { agents, messages, setMessages, isGenerating, setIsGenerating, setAgents } = useMockData()
  const [input, setInput] = useState('')
  const [activeAgent, setActiveAgent] = useState(agents[0]?.id || '')
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)
  const [client, setClient] = useState<GatewayClient | null>(null)
  const [showCreateAgentModal, setShowCreateAgentModal] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // Handle agent creation from template
  const handleCreateAgent = useCallback(async (
    template: CharacterTemplate,
    agentType: 'lead' | 'specialist',
    customName?: string
  ) => {
    const newAgent: Agent = {
      id: `template:${template.id}:${Date.now()}`,
      name: customName || template.name,
      status: template.role,
      isOnline: true,
      isPrimary: agentType === 'lead',
      agentType: agentType,
      templateId: template.id,
      lastMessage: 'Ready to help!',
    }
    
    setAgents((prev: Agent[]) => [...prev, newAgent])
    
    // Select the new agent
    setActiveAgent(newAgent.id)
    
    // If connected to Gateway, create the agent there too
    if (client?.isConnected()) {
      try {
        await client.request('agents.createFromTemplate', {
          template_id: template.id,
          name: customName || template.name,
          agent_type: agentType,
          role: template.role,
          description: template.description,
        })
      } catch (err) {
        console.warn('[AppleApp] Failed to create agent on Gateway:', err)
      }
    }
    
    console.log('[AppleApp] Created agent:', newAgent)
  }, [client, setAgents])

  // Initialize Gateway client
  useEffect(() => {
    const gatewayClient = new GatewayClient({
      baseUrl: 'http://127.0.0.1:33418',
    })

    gatewayClient.connect().then(() => {
      console.log('[AppleApp] Connected to Gateway')
      setClient(gatewayClient)
    }).catch(err => {
      console.warn('[AppleApp] Gateway connection failed, using mock mode:', err)
    })

    return () => {
      gatewayClient.disconnect()
    }
  }, [])

  // Scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Group messages for display
  const groupedMessages = useMemo(() => {
    return messages.map((msg, i) => {
      const prev = messages[i - 1]
      const isGrouped = prev && prev.role === msg.role && msg.role === 'assistant'
      return { ...msg, isGrouped }
    })
  }, [messages])

  // Send message
  const handleSend = useCallback(async () => {
    const text = input.trim()
    if (!text || isGenerating) return

    // Add user message
    const userMessage: ChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: text,
      timestamp: Date.now(),
    }
    setMessages(prev => [...prev, userMessage])
    setInput('')
    setIsGenerating(true)

    // Add placeholder assistant message
    const assistantId = `assistant-${Date.now()}`
    const assistantMessage: ChatMessage = {
      id: assistantId,
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
      isStreaming: true,
    }
    setMessages(prev => [...prev, assistantMessage])

    try {
      if (client?.isConnected()) {
        // Real streaming via Gateway
        let fullContent = ''
        for await (const event of client.chat.sendStream({
          sessionId: 'default',
          message: text,
        })) {
          if (event.type === 'chat.delta') {
            fullContent += event.payload?.delta?.content || ''
            setMessages(prev => prev.map(m =>
              m.id === assistantId
                ? { ...m, content: fullContent }
                : m
            ))
          } else if (event.type === 'chat.done') {
            setMessages(prev => prev.map(m =>
              m.id === assistantId
                ? { ...m, isStreaming: false }
                : m
            ))
          } else if (event.type === 'chat.error') {
            throw new Error(event.payload?.error || 'Chat error')
          }
        }
        setIsGenerating(false)
      } else {
        // Mock response for development
        await new Promise(resolve => setTimeout(resolve, 500))
        const mockResponses = [
          "I'm Jaeger, your AI companion. How can I help you today? ✨",
          "That's an interesting question! Let me think about it... 🤔",
          "I can help you with coding, writing, research, and much more. What would you like to work on?",
          "Great idea! Let's explore that together. 🚀",
          "Here's what I know about that:\n\n1. First point\n2. Second point\n3. Third point\n\nWould you like me to elaborate on any of these?",
        ]
        const response = mockResponses[Math.floor(Math.random() * mockResponses.length)]

        // Simulate streaming
        for (let i = 0; i < response.length; i++) {
          await new Promise(resolve => setTimeout(resolve, 15))
          setMessages(prev => prev.map(m =>
            m.id === assistantId
              ? { ...m, content: response.slice(0, i + 1) }
              : m
          ))
        }

        setMessages(prev => prev.map(m =>
          m.id === assistantId
            ? { ...m, isStreaming: false }
            : m
        ))
        setIsGenerating(false)
      }
    } catch (err) {
      console.error('[AppleApp] Send error:', err)
      setMessages(prev => prev.map(m =>
        m.id === assistantId
          ? { ...m, isStreaming: false, error: String(err) }
          : m
      ))
      setIsGenerating(false)
    }
  }, [client, input, isGenerating, setMessages, setIsGenerating])

  const handleStop = useCallback(() => {
    setIsGenerating(false)
    setMessages(prev => prev.map(m =>
      m.isStreaming ? { ...m, isStreaming: false } : m
    ))
  }, [setMessages, setIsGenerating])

  const handleRegenerate = useCallback(() => {
    // Find the last user message
    const userMsg = [...messages].reverse().find(m => m.role === 'user')
    if (userMsg) {
      setInput(userMsg.content)
    }
  }, [messages, setInput])

  const activeAgentData = agents.find(a => a.id === activeAgent)

  return (
    <div className="app-shell">
      {/* Mobile Sidebar Overlay */}
      {mobileSidebarOpen && (
        <div
          className="mobile-sidebar-overlay"
          onClick={() => setMobileSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <div className={cn('sidebar-wrapper', mobileSidebarOpen && 'mobile-open')}>
        <Sidebar
          agents={agents}
          activeAgentId={activeAgent}
          onSelectAgent={(id) => {
            setActiveAgent(id)
            setMobileSidebarOpen(false)
          }}
          onNewChat={() => setMessages([])}
          onCreateAgent={() => setShowCreateAgentModal(true)}
          collapsed={sidebarCollapsed}
          onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
        />
      </div>

      {/* Create Agent Modal */}
      <CreateAgentModal
        isOpen={showCreateAgentModal}
        onClose={() => setShowCreateAgentModal(false)}
        onCreateAgent={handleCreateAgent}
        gatewayUrl="http://127.0.0.1:33418"
      />

      {/* Main Content */}
      <main className="main-content">
        {/* Header */}
        <header className="main-header">
          <div className="header-left">
            <button
              className="icon-button mobile-menu-button"
              onClick={() => setMobileSidebarOpen(true)}
              aria-label="Open menu"
            >
              <Menu size={20} />
            </button>
            <h1 className="header-title">
              {activeAgentData?.name || 'Jaeger'}
            </h1>
            {activeAgentData?.isOnline && (
              <span className="header-status">● Online</span>
            )}
          </div>
          <div className="header-actions">
            <button className="icon-button" aria-label="New chat" onClick={() => setMessages([])}>
              <Plus size={20} />
            </button>
            <button className="icon-button" aria-label="Search" title="Search (⌘K)">
              <Search size={20} />
            </button>
            <ThemeToggle />
            <button className="icon-button" aria-label="Settings">
              <Settings size={20} />
            </button>
          </div>
        </header>

        {/* Chat Area */}
        <div className="chat-container">
          {/* Messages */}
          <div className="chat-messages" role="log" aria-live="polite" aria-label="Conversation">
            {groupedMessages.length === 0 ? (
              <EmptyState onSuggestionClick={setInput} />
            ) : (
              <>
                {groupedMessages.map((message, i) => (
                  <Message
                    key={message.id}
                    message={message}
                    onRegenerate={handleRegenerate}
                  />
                ))}
                <div ref={messagesEndRef} />
              </>
            )}
          </div>

          {/* Input */}
          <ChatInput
            value={input}
            onChange={setInput}
            onSend={handleSend}
            onStop={handleStop}
            isGenerating={isGenerating}
          />
        </div>
      </main>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────
// Error Boundary
// ─────────────────────────────────────────────────────────────

function ErrorFallback({ error, reset }: { error: Error; reset: () => void }) {
  return (
    <div className="error-fallback">
      <div className="error-icon">⚠️</div>
      <h2>Something went wrong</h2>
      <p>{error.message}</p>
      <button className="error-button" onClick={reset}>
        Try again
      </button>
    </div>
  )
}

class SimpleErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { hasError: boolean; error: Error | null }
> {
  constructor(props: { children: React.ReactNode }) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error('[AppleApp] Error:', error, errorInfo)
  }

  render() {
    if (this.state.hasError && this.state.error) {
      return (
        <ErrorFallback
          error={this.state.error}
          reset={() => this.setState({ hasError: false, error: null })}
        />
      )
    }
    return this.props.children
  }
}

// ─────────────────────────────────────────────────────────────
// Export
// ─────────────────────────────────────────────────────────────

export function AppleApp() {
  return (
    <SimpleErrorBoundary>
      <AppleAppContent />
    </SimpleErrorBoundary>
  )
}

export default AppleApp
