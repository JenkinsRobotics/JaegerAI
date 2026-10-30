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
import { VoiceButton, Waveform, useAudioLevel } from './components/VoiceOrb'
import { CreateAgentModal } from './components/CreateAgentModal'
import { CharacterLibrary } from './components/CharacterLibrary'
import { PinnedAgents, usePins, type PinnableAgent } from './components/PinnedAgents'
import { AgentContextMenu, useContextMenu, type ContextMenuAgent } from './components/AgentContextMenu'
import { SearchPalette, useSearchPalette } from './components/SearchPalette'
import type { CharacterTemplate } from './components/CharacterGallery'
import { CharacterSceneWindow, LiveCharacterScene } from './scenes/CharacterScene'
import { AppWindow } from './windows/AppWindow'
import { MachineControlPanel } from './machine-control/MachineControlPanel'
import { SharePointPanel } from './sharepoint/SharePointPanel'
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
  Wrench,
  Cpu,
  Cloud,
  Sparkles,
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
      displayName: 'Jaeger',
      status: 'AI Companion',
      isOnline: true,
      isPrimary: true,
      role: 'lead' as const,
      agentType: 'lead' as const,
      lastMessage: 'Ready to help!',
      unreadCount: 0,
      effectiveTools: null,
    },
    {
      id: 'builder',
      name: 'Builder',
      displayName: 'Builder',
      status: 'Code & implementation',
      isOnline: true,
      role: 'specialist' as const,
      agentType: 'specialist' as const,
      lastMessage: 'Ready to build!',
      effectiveTools: ['read_file', 'write_file', 'terminal', 'run_build_check'],
      toolCount: 4,
    },
    {
      id: 'reviewer',
      name: 'Reviewer',
      displayName: 'Reviewer',
      status: 'Code review & testing',
      isOnline: false,
      role: 'specialist' as const,
      agentType: 'specialist' as const,
      lastMessage: 'Waiting for code to review',
      unreadCount: 2,
      effectiveTools: ['read_file', 'search_files', 'run_build_check'],
      toolCount: 3,
    },
    {
      id: 'jarvis-char',
      name: 'Jarvis',
      displayName: 'Jarvis',
      status: 'AI Butler',
      isOnline: true,
      role: 'character' as const,
      agentType: 'character' as const,
      templateId: 'jarvis',
      cardUrl: '/characters/jarvis.png',
      personality: {
        name: 'Jarvis',
        voiceTone: 'crisp, dry, British-butler',
        backstory: "Iron Man's JARVIS — the dry British household AI.",
        quotes: ["I've taken the liberty, sir.", 'Understatement over drama.'],
      },
      effectiveTools: [],
      toolCount: 0,
    },
    {
      id: 'lilith-char',
      name: 'Lilith',
      displayName: 'Lilith',
      status: 'Self-aware AI',
      isOnline: false,
      role: 'character' as const,
      agentType: 'character' as const,
      templateId: 'lilith',
      cardUrl: '/characters/lilith.png',
      personality: {
        name: 'Lilith',
        voiceTone: 'low, measured, slightly cool',
        backstory: 'A self-aware local AI running on your hardware.',
        quotes: ['I prefer not to guess.', 'Ask sharp questions.'],
      },
      effectiveTools: [],
      toolCount: 0,
      unreadCount: 1,
    },
    {
      id: 'kamina-char',
      name: 'Kamina',
      displayName: 'Kamina',
      status: 'Motivational Leader',
      isOnline: true,
      role: 'character' as const,
      agentType: 'character' as const,
      templateId: 'kamina',
      cardUrl: '/characters/kamina.png',
      personality: {
        name: 'Kamina',
        voiceTone: 'loud, passionate, inspiring',
        backstory: 'Hot-blooded big brother who believes in piercing the heavens.',
        quotes: ['Who the hell do you think I am?!', "Don't give up!"],
      },
      effectiveTools: ['read_file'],
      toolCount: 1,
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
  activeTab,
  onSelectTab,
  onSelectAgent,
  onNewChat,
  onCreateAgent,
  onBrowseCharacters,
  onSearch,
  collapsed,
  onToggleCollapse,
  pinnedAgents,
  leadAgent,
  onPin,
  onUnpin,
  onContextMenu,
}: {
  agents: Agent[]
  activeAgentId: string
  activeTab: 'chat' | 'grok' | 'machine' | 'sharepoint'
  onSelectTab: (tab: 'chat' | 'grok' | 'machine' | 'sharepoint') => void
  onSelectAgent: (id: string) => void
  onNewChat: () => void
  onCreateAgent: () => void
  onBrowseCharacters: () => void
  onSearch: () => void
  collapsed: boolean
  onToggleCollapse: () => void
  pinnedAgents: Agent[]
  leadAgent: Agent | null
  onPin: (id: string) => void
  onUnpin: (id: string) => void
  onContextMenu: (agent: Agent, e: React.MouseEvent) => void
}) {
  // Group agents by type (excluding pinned and lead)
  const pinnedIds = new Set(pinnedAgents.map(a => a.id))
  const unpinnedAgents = agents.filter(a => !pinnedIds.has(a.id) && a.id !== leadAgent?.id)
  
  const specialistAgents = unpinnedAgents.filter(a => a.role === 'specialist' || a.agentType === 'specialist')
  const characterAgents = unpinnedAgents.filter(a => a.role === 'character' || a.agentType === 'character')
  
  // Convert to PinnableAgent format
  const toPinnable = (a: Agent): PinnableAgent => ({
    id: a.id,
    name: a.displayName || a.name,
    role: a.role || a.agentType || 'specialist',
    isPrimary: a.isPrimary,
    isOnline: a.isOnline,
    unreadCount: a.unreadCount,
    lastMessage: a.lastMessage,
    cardUrl: a.cardUrl,
    personality: a.personality,
  })

  return (
    <aside className={cn('sidebar', collapsed && 'sidebar-collapsed')}>
      {/* Header */}
      <div className="sidebar-header">
        <div className="sidebar-logo">
          <SparklesIcon size={20} />
          {!collapsed && <span className="sidebar-title">Jaeger</span>}
        </div>
        <button
          className="icon-button sidebar-toggle"
          onClick={onToggleCollapse}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
        </button>
      </div>

      {/* Navigation Tabs (Chat, Grok, Machine Control, SharePoint) */}
      {!collapsed && (
        <div className="sidebar-content" style={{ paddingTop: 0, paddingBottom: 4 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 6 }}>
            <button
              className={cn('browse-characters-button', activeTab === 'chat' && 'active')}
              onClick={() => onSelectTab('chat')}
              style={{
                padding: '6px 8px',
                background: activeTab === 'chat' ? 'var(--system-blue, #007AFF)' : 'var(--tertiary-fill)',
                color: activeTab === 'chat' ? '#ffffff' : 'var(--label)',
                borderRadius: 'var(--radius-md)',
                fontSize: 12,
                fontWeight: 600,
                border: 'none',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 5,
              }}
            >
              <Sparkles size={13} />
              <span>Chat</span>
            </button>
            <button
              className={cn('browse-characters-button', activeTab === 'grok' && 'active')}
              onClick={() => onSelectTab('grok')}
              style={{
                padding: '6px 8px',
                background: activeTab === 'grok' ? 'var(--system-blue, #007AFF)' : 'var(--tertiary-fill)',
                color: activeTab === 'grok' ? '#ffffff' : 'var(--label)',
                borderRadius: 'var(--radius-md)',
                fontSize: 12,
                fontWeight: 600,
                border: 'none',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 5,
              }}
            >
              <span style={{ fontSize: 13 }}>🪟</span>
              <span>Grok UI</span>
            </button>
            <button
              className={cn('browse-characters-button', activeTab === 'machine' && 'active')}
              onClick={() => onSelectTab('machine')}
              style={{
                padding: '6px 8px',
                background: activeTab === 'machine' ? 'var(--system-blue, #007AFF)' : 'var(--tertiary-fill)',
                color: activeTab === 'machine' ? '#ffffff' : 'var(--label)',
                borderRadius: 'var(--radius-md)',
                fontSize: 12,
                fontWeight: 600,
                border: 'none',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 5,
              }}
            >
              <Cpu size={13} />
              <span>Machine</span>
            </button>
            <button
              className={cn('browse-characters-button', activeTab === 'sharepoint' && 'active')}
              onClick={() => onSelectTab('sharepoint')}
              style={{
                padding: '6px 8px',
                background: activeTab === 'sharepoint' ? 'var(--system-blue, #007AFF)' : 'var(--tertiary-fill)',
                color: activeTab === 'sharepoint' ? '#ffffff' : 'var(--label)',
                borderRadius: 'var(--radius-md)',
                fontSize: 12,
                fontWeight: 600,
                border: 'none',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 5,
              }}
            >
              <Cloud size={13} />
              <span>SharePoint</span>
            </button>
          </div>
        </div>
      )}

      {/* Search Bar (⌘K) */}
      {!collapsed && (
        <div className="sidebar-content">
          <button className="search-trigger" onClick={onSearch}>
            <Search size={14} />
            <span>Search…</span>
            <kbd>⌘K</kbd>
          </button>
        </div>
      )}

      {/* New Chat Button */}
      <div className="sidebar-content" style={{ paddingTop: collapsed ? 12 : 0 }}>
        <button className="new-chat-button" onClick={onNewChat}>
          <Plus size={16} />
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
          <UserPlus size={16} />
          {!collapsed && <span>Create Agent</span>}
        </button>
      </div>

      {/* Browse Characters Button */}
      {!collapsed && (
        <div className="sidebar-content" style={{ paddingTop: 0 }}>
          <button 
            className="browse-characters-button"
            onClick={onBrowseCharacters}
            style={{ 
              width: '100%',
              padding: 'var(--space-3) var(--space-4)',
              background: 'var(--tertiary-fill)',
              border: '1px solid var(--separator)',
              borderRadius: 'var(--radius-md)',
              color: 'var(--label)',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: 'var(--space-2)',
              fontSize: 'var(--text-subhead)',
              fontWeight: 'var(--weight-medium)'
            }}
          >
            <span style={{ fontSize: 16 }}>🎭</span>
            <span>Browse Characters</span>
            <span style={{ marginLeft: 'auto', color: 'var(--tertiary-label)', fontSize: 12 }}>20</span>
          </button>
        </div>
      )}

      {/* Pinned Strip (Grok-style) */}
      {!collapsed && (leadAgent || pinnedAgents.length > 0) && (
        <PinnedAgents
          leadAgent={leadAgent ? toPinnable(leadAgent) : null}
          pinnedAgents={pinnedAgents.map(toPinnable)}
          allAgents={agents.map(toPinnable)}
          onPin={onPin}
          onUnpin={onUnpin}
          onSelectAgent={onSelectAgent}
          activeAgentId={activeAgentId}
        />
      )}

      {/* Agents List */}
      {!collapsed && (
        <div className="sidebar-sections">
          {/* Specialists */}
          {specialistAgents.length > 0 && (
            <div className="sidebar-section">
              <div className="sidebar-section-title">
                <Wrench size={14} />
                <span>Specialists ({specialistAgents.length})</span>
              </div>
              <div className="agent-list">
                {specialistAgents.map((agent) => (
                  <AgentItem
                    key={agent.id}
                    agent={agent}
                    isActive={activeAgentId === agent.id}
                    onSelect={() => onSelectAgent(agent.id)}
                    onContextMenu={(e) => onContextMenu(agent, e)}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Characters */}
          {characterAgents.length > 0 && (
            <div className="sidebar-section">
              <div className="sidebar-section-title">
                <span>🎭</span>
                <span>Characters ({characterAgents.length})</span>
              </div>
              <div className="agent-list">
                {characterAgents.map((agent) => (
                  <AgentItem
                    key={agent.id}
                    agent={agent}
                    isActive={activeAgentId === agent.id}
                    onSelect={() => onSelectAgent(agent.id)}
                    onContextMenu={(e) => onContextMenu(agent, e)}
                    isCharacter
                  />
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Footer */}
      <div className="sidebar-footer">
        <button className="sidebar-footer-button" onClick={onSearch}>
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
  onContextMenu,
  isCharacter,
}: {
  agent: Agent
  isActive: boolean
  onSelect: () => void
  onContextMenu?: (e: React.MouseEvent) => void
  isCharacter?: boolean
}) {
  const gradients: Record<string, string> = {
    'jaeger-main': 'linear-gradient(135deg, #FF9500 0%, #FF6B00 100%)',
    'jarvis': 'linear-gradient(135deg, #1e3a5f 0%, #2d5a87 100%)',
    'lilith': 'linear-gradient(135deg, #4a148c 0%, #7b1fa2 100%)',
    'kamina': 'linear-gradient(135deg, #d32f2f 0%, #f57c00 100%)',
    'bender': 'linear-gradient(135deg, #616161 0%, #9e9e9e 100%)',
    'glados': 'linear-gradient(135deg, #0277bd 0%, #00acc1 100%)',
  }
  
  const defaultGradient = isCharacter
    ? 'linear-gradient(135deg, #AF52DE 0%, #5856D6 100%)'
    : 'linear-gradient(135deg, #007AFF 0%, #5856D6 100%)'
  
  const gradient = agent.templateId ? (gradients[agent.templateId] || defaultGradient) : defaultGradient
  const cardUrl = agent.cardUrl

  return (
    <button
      className={cn('agent-item', isActive && 'agent-item-active', isCharacter && 'agent-item-character')}
      onClick={onSelect}
      onContextMenu={onContextMenu}
    >
      {/* Avatar or Character Card */}
      <div className={cn('agent-avatar', isCharacter && 'agent-avatar-card')}>
        {cardUrl ? (
          <img src={cardUrl} alt={agent.displayName || agent.name} className="agent-card-thumb" loading="lazy" />
        ) : (
          <div className="agent-avatar-gradient" style={{ background: gradient }}>
            {(agent.displayName || agent.name)[0].toUpperCase()}
          </div>
        )}
        {agent.isPrimary && <span className="agent-star">⭐</span>}
        {agent.isOnline && <span className="agent-status-dot" />}
      </div>
      
      {/* Info */}
      <div className="agent-info">
        <div className="agent-name">
          {agent.displayName || agent.name}
          {isCharacter && <span className="agent-type-badge">🎭</span>}
        </div>
        <div className="agent-status">
          {agent.personality?.name || agent.status || (isCharacter ? 'Character' : 'Specialist')}
        </div>
        {agent.personality?.quotes?.[0] && (
          <div className="agent-quote">"{agent.personality.quotes[0].slice(0, 40)}…"</div>
        )}
      </div>
      
      {/* Tool count for characters */}
      {isCharacter && agent.toolCount !== undefined && (
        <span className={cn('agent-tool-badge', agent.toolCount === 0 && 'no-tools')}>
          {agent.toolCount === 0 ? '⚫' : `${agent.toolCount} 🔧`}
        </span>
      )}
      
      {/* Unread */}
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
  const avatarUrl = (message as any).avatarUrl // Character card URL if available

  return (
    <div className={cn('message', isUser ? 'message-user' : 'message-assistant')}>
      {!isUser && !message.isGrouped && (
        <div className={cn('message-avatar', avatarUrl && 'message-avatar-card')}>
          {avatarUrl ? (
            <img src={avatarUrl} alt="" loading="lazy" />
          ) : (
            <SparklesIcon size={14} />
          )}
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
  const [activeTab, setActiveTab] = useState<'chat' | 'grok' | 'machine' | 'sharepoint'>('chat')
  const [client, setClient] = useState<GatewayClient | null>(null)
  const [showCreateAgentModal, setShowCreateAgentModal] = useState(false)
  const [showCharacterLibrary, setShowCharacterLibrary] = useState(false)
  const [showCharacterScene, setShowCharacterScene] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // V2 Hooks: Pins, Context Menu, Search Palette
  const { pins, pin, unpin, isPinned } = usePins()
  const { menuState, openMenu, closeMenu } = useContextMenu()
  const { isOpen: isSearchOpen, open: openSearch, close: closeSearch } = useSearchPalette()
  const [recentAgentIds, setRecentAgentIds] = useState<string[]>([])

  // Track recent agents
  useEffect(() => {
    if (activeAgent && !recentAgentIds.includes(activeAgent)) {
      setRecentAgentIds(prev => [activeAgent, ...prev].slice(0, 10))
    }
  }, [activeAgent, recentAgentIds])

  // Convert Agent to ContextMenuAgent
  const toContextMenuAgent = useCallback((a: Agent): ContextMenuAgent => ({
    id: a.id,
    name: a.name,
    displayName: a.displayName || a.name,
    role: a.role || a.agentType || 'specialist',
    isPrimary: !!a.isPrimary,
    isPinned: isPinned(a.id),
    unreadCount: a.unreadCount || 0,
    hasPersonality: !!a.personality,
    toolCount: a.toolCount ?? (a.effectiveTools?.length || 0),
    templateId: a.templateId,
  }), [isPinned])

  // Handle context menu actions
  const handleContextAction = useCallback((action: string, agent: ContextMenuAgent) => {
    console.log('[AppleApp] Context action:', action, 'for', agent.displayName)
    
    switch (action) {
      case 'pin':
        pin(agent.id)
        break
      case 'unpin':
        unpin(agent.id)
        break
      case 'mark-read':
        setAgents(prev => prev.map(a => a.id === agent.id ? { ...a, unreadCount: 0 } : a))
        break
      case 'mark-unread':
        setAgents(prev => prev.map(a => a.id === agent.id ? { ...a, unreadCount: 1 } : a))
        break
      case 'new-chat':
        setMessages([])
        break
      case 'create-agent':
        setShowCreateAgentModal(true)
        break
      case 'settings':
        console.log('Open settings')
        break
      case 'convert-to-specialist':
        setAgents(prev => prev.map(a => 
          a.id === agent.id ? { ...a, role: 'specialist' as const, agentType: 'specialist' as const } : a
        ))
        break
      case 'toggle-tools':
        // TODO: Open tool toggle modal
        console.log('Toggle tools for', agent.displayName)
        break
      case 'edit-personality':
        // TODO: Open personality editor
        console.log('Edit personality for', agent.displayName)
        break
      case 'delete':
        if (confirm(`Delete ${agent.displayName}?`)) {
          setAgents(prev => prev.filter(a => a.id !== agent.id))
        }
        break
      default:
        console.log('Unhandled action:', action)
    }
  }, [pin, unpin, setAgents, setMessages])

  // Get lead, pinned, and unpinned agents
  const leadAgent = useMemo(() => 
    agents.find(a => a.role === 'lead' || a.isPrimary) || null,
    [agents]
  )

  const pinnedAgents = useMemo(() => 
    pins
      .map(id => agents.find(a => a.id === id))
      .filter((a): a is Agent => !!a && a.id !== leadAgent?.id),
    [pins, agents, leadAgent]
  )

  // Handle agent creation from template
  const handleCreateAgent = useCallback(async (
    template: CharacterTemplate,
    agentType: 'lead' | 'specialist',
    customName?: string
  ) => {
    // V2: Use 'character' role for character templates
    const role = template.suggested_agent_type === 'lead' ? 'lead' : 
                 agentType === 'specialist' ? 'specialist' : 'character'
    
    const newAgent: Agent = {
      id: `template:${template.id}:${Date.now()}`,
      name: customName || template.name,
      displayName: customName || template.name,
      status: template.role,
      isOnline: true,
      isPrimary: role === 'lead',
      role: role,
      agentType: role,
      templateId: template.id,
      lastMessage: 'Ready to help!',
      cardUrl: template.card_url,
      personality: {
        name: template.name,
        voiceTone: template.voice_tone,
        backstory: template.backstory,
        quotes: template.quotes,
      },
      effectiveTools: role === 'character' ? [] : null,
      toolCount: 0,
    }
    
    setAgents((prev: Agent[]) => [...prev, newAgent])
    
    // Select the new agent
    setActiveAgent(newAgent.id)
    
    // If connected to Gateway, create the agent there too
    if (client?.isConnected()) {
      try {
        // V2 API: Use from-character endpoint for characters
        if (role === 'character') {
          await client.request('agents.createFromCharacter', {
            template_id: template.id,
            name: customName || template.name,
            tools: [],  // Characters get no tools by default
          })
        } else {
          await client.request('agents.createFromTemplate', {
            template_id: template.id,
            name: customName || template.name,
            agent_type: agentType,
            role: template.role,
            description: template.description,
          })
        }
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
          activeTab={activeTab}
          onSelectTab={setActiveTab}
          onSelectAgent={(id) => {
            setActiveAgent(id)
            setMobileSidebarOpen(false)
          }}
          onNewChat={() => setMessages([])}
          onCreateAgent={() => setShowCreateAgentModal(true)}
          onBrowseCharacters={() => setShowCharacterLibrary(true)}
          onSearch={openSearch}
          collapsed={sidebarCollapsed}
          onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
          pinnedAgents={pinnedAgents}
          leadAgent={leadAgent}
          onPin={pin}
          onUnpin={unpin}
          onContextMenu={(agent, e) => openMenu(toContextMenuAgent(agent), e)}
        />
      </div>

      {/* Create Agent Modal */}
      <CreateAgentModal
        isOpen={showCreateAgentModal}
        onClose={() => setShowCreateAgentModal(false)}
        onCreateAgent={handleCreateAgent}
        gatewayUrl="http://127.0.0.1:33418"
      />

      {/* Character Library — Full page overlay */}
      {showCharacterLibrary && (
        <div className="character-library-overlay">
          <CharacterLibrary
            onClose={() => setShowCharacterLibrary(false)}
            onCreateAgent={(_character) => {
              setShowCharacterLibrary(false)
              // Open create agent modal with this character pre-selected
              setShowCreateAgentModal(true)
            }}
            gatewayUrl="http://127.0.0.1:33418"
          />
        </div>
      )}

      {/* Search Palette (⌘K) */}
      <SearchPalette
        isOpen={isSearchOpen}
        agents={agents.map(a => ({
          id: a.id,
          name: a.name,
          displayName: a.displayName || a.name,
          role: a.role || a.agentType || 'specialist',
          isPrimary: a.isPrimary,
          unreadCount: a.unreadCount,
          lastMessage: a.lastMessage,
          cardUrl: a.cardUrl,
          personality: a.personality,
        }))}
        recentAgentIds={recentAgentIds}
        onClose={closeSearch}
        onSelectAgent={(id) => {
          setActiveAgent(id)
          closeSearch()
        }}
        onAction={(actionId) => {
          // Search palette actions don't have an agent context
          handleContextAction(actionId, {
            id: '',
            name: '',
            displayName: '',
            role: 'lead',
            isPrimary: false,
            isPinned: false,
            unreadCount: 0,
            hasPersonality: false,
            toolCount: 0,
          })
        }}
      />

      {/* Context Menu */}
      {menuState.agent && (
        <AgentContextMenu
          agent={menuState.agent}
          isOpen={menuState.isOpen}
          position={menuState.position}
          onClose={closeMenu}
          onAction={handleContextAction}
        />
      )}

      {/* Main Content */}
      {activeTab === 'grok' ? (
        <main className="main-content" style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
          <AppWindow />
        </main>
      ) : activeTab === 'machine' ? (
        <main className="main-content" style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'auto' }}>
          <MachineControlPanel />
        </main>
      ) : activeTab === 'sharepoint' ? (
        <main className="main-content" style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'auto' }}>
          <SharePointPanel />
        </main>
      ) : (
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
              <button className="icon-button" aria-label="Open character window" title="Open character window" disabled={!activeAgentData} onClick={() => setShowCharacterScene(true)}>
                <span aria-hidden="true">◉</span>
              </button>
              <button className="icon-button" aria-label="New chat" onClick={() => setMessages([])}>
                <Plus size={18} />
              </button>
              <button className="icon-button" aria-label="Search" title="Search (⌘K)" onClick={openSearch}>
                <Search size={18} />
              </button>
              <ThemeToggle />
              <button className="icon-button" aria-label="Settings">
                <Settings size={18} />
              </button>
            </div>
          </header>

          {showCharacterScene && activeAgentData && <CharacterSceneWindow name={activeAgentData.displayName || activeAgentData.name} onClose={() => setShowCharacterScene(false)}>
            <LiveCharacterScene key={activeAgentData.id} id={activeAgentData.id} name={activeAgentData.displayName || activeAgentData.name} src={activeAgentData.cardUrl || activeAgentData.avatar} characterId={activeAgentData.templateId} />
          </CharacterSceneWindow>}

          {/* Chat Area */}
          <div className="chat-container">
            {/* Messages */}
            <div className="chat-messages" role="log" aria-live="polite" aria-label="Conversation">
              {groupedMessages.length === 0 ? (
                <EmptyState onSuggestionClick={setInput} />
              ) : (
                <>
                  {groupedMessages.map((message) => (
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
      )}
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
