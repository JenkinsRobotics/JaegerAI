/**
 * SearchPalette — ⌘K command palette (Grok-style)
 *
 * Centered overlay with:
 * - Fuzzy search across agents
 * - Quick actions (New Chat, Settings, etc.)
 * - Recent agents
 * - Keyboard navigation
 */

import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import {
  Search,
  Plus,
  Settings,
  MessageSquare,
  Clock,
  Star,
  Wrench,
  User,
  Command,
} from './Icons'

// ─────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────

interface SearchableAgent {
  id: string
  name: string
  displayName: string
  role: 'lead' | 'specialist' | 'character' | 'runtime'
  isPrimary?: boolean
  unreadCount?: number
  lastMessage?: string
  cardUrl?: string | null
  personality?: { name: string }
}

interface QuickAction {
  id: string
  label: string
  shortcut?: string
  icon: React.ComponentType<{ size?: number }>
  action: () => void
}

interface SearchPaletteProps {
  isOpen: boolean
  agents: SearchableAgent[]
  recentAgentIds: string[]
  onClose: () => void
  onSelectAgent: (agentId: string) => void
  onAction: (actionId: string) => void
}

// ─────────────────────────────────────────────────────────────
// Fuzzy Search
// ─────────────────────────────────────────────────────────────

function fuzzyMatch(query: string, text: string): number {
  const q = query.toLowerCase()
  const t = text.toLowerCase()
  
  if (t.includes(q)) {
    // Exact substring match — score by position
    return 100 - t.indexOf(q)
  }
  
  // Fuzzy: all characters in order
  let score = 0
  let qi = 0
  for (let ti = 0; ti < t.length && qi < q.length; ti++) {
    if (t[ti] === q[qi]) {
      score += 10
      qi++
    }
  }
  return qi === q.length ? score : 0
}

// ─────────────────────────────────────────────────────────────
// Search Palette Component
// ─────────────────────────────────────────────────────────────

export function SearchPalette({
  isOpen,
  agents,
  recentAgentIds,
  onClose,
  onSelectAgent,
  onAction,
}: SearchPaletteProps) {
  const [query, setQuery] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  // Focus input on open
  useEffect(() => {
    if (isOpen) {
      setQuery('')
      setSelectedIndex(0)
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }, [isOpen])

  // Quick actions
  const quickActions: QuickAction[] = useMemo(() => [
    {
      id: 'new-chat',
      label: 'New Chat',
      shortcut: '⌘N',
      icon: Plus,
      action: () => onAction('new-chat'),
    },
    {
      id: 'create-agent',
      label: 'Create Agent',
      shortcut: '⌘⇧N',
      icon: User,
      action: () => onAction('create-agent'),
    },
    {
      id: 'settings',
      label: 'Settings',
      shortcut: '⌘,',
      icon: Settings,
      action: () => onAction('settings'),
    },
  ], [onAction])

  // Filter and score agents
  const scoredAgents = useMemo(() => {
    if (!query) {
      // No query: show recents first, then all
      const recents = recentAgentIds
        .map(id => agents.find(a => a.id === id))
        .filter((a): a is SearchableAgent => !!a)
      const others = agents.filter(a => !recentAgentIds.includes(a.id))
      return [...recents, ...others]
    }
    
    return agents
      .map(agent => ({
        agent,
        score: Math.max(
          fuzzyMatch(query, agent.name),
          fuzzyMatch(query, agent.displayName),
          fuzzyMatch(query, agent.role),
          agent.personality ? fuzzyMatch(query, agent.personality.name) : 0
        ),
      }))
      .filter(({ score }) => score > 0)
      .sort((a, b) => b.score - a.score)
      .map(({ agent }) => agent)
  }, [query, agents, recentAgentIds])

  // Filter quick actions
  const filteredActions = useMemo(() => {
    if (!query) return []
    return quickActions.filter(a => 
      fuzzyMatch(query, a.label) > 0
    )
  }, [query, quickActions])

  // Combined results for keyboard navigation
  const results = useMemo(() => [
    ...filteredActions.map(a => ({ type: 'action' as const, data: a })),
    ...scoredAgents.map(a => ({ type: 'agent' as const, data: a })),
  ], [filteredActions, scoredAgents])

  // Keyboard navigation
  useEffect(() => {
    if (!isOpen) return

    const handleKeyDown = (e: KeyboardEvent) => {
      switch (e.key) {
        case 'ArrowDown':
          e.preventDefault()
          setSelectedIndex(i => Math.min(i + 1, results.length - 1))
          break
        case 'ArrowUp':
          e.preventDefault()
          setSelectedIndex(i => Math.max(i - 1, 0))
          break
        case 'Enter':
          e.preventDefault()
          const selected = results[selectedIndex]
          if (selected) {
            if (selected.type === 'agent') {
              onSelectAgent(selected.data.id)
            } else {
              selected.data.action()
            }
            onClose()
          }
          break
        case 'Escape':
          e.preventDefault()
          onClose()
          break
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, results, selectedIndex, onSelectAgent, onClose])

  // Scroll selected into view
  useEffect(() => {
    const el = listRef.current?.querySelector(`[data-index="${selectedIndex}"]`)
    el?.scrollIntoView({ block: 'nearest' })
  }, [selectedIndex])

  if (!isOpen) return null

  const getRoleIcon = (role: string) => {
    switch (role) {
      case 'lead': return <Star size={14} />
      case 'specialist': return <Wrench size={14} />
      case 'character': return '🎭'
      default: return <MessageSquare size={14} />
    }
  }

  const getRoleBadge = (role: string) => {
    switch (role) {
      case 'lead': return { label: 'Lead', color: '#FF9500' }
      case 'specialist': return { label: 'Specialist', color: '#007AFF' }
      case 'character': return { label: 'Character', color: '#AF52DE' }
      default: return { label: 'Runtime', color: '#8E8E93' }
    }
  }

  return (
    <>
      {/* Backdrop */}
      <div className="palette-backdrop" onClick={onClose} />
      
      {/* Palette */}
      <div className="search-palette" role="dialog" aria-label="Search">
        {/* Search Input */}
        <div className="palette-input-wrapper">
          <Search size={18} />
          <input
            ref={inputRef}
            type="text"
            placeholder="Search agents and actions…"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value)
              setSelectedIndex(0)
            }}
            aria-label="Search"
            autoComplete="off"
            spellCheck={false}
          />
          <kbd>ESC</kbd>
        </div>

        {/* Results */}
        <div ref={listRef} className="palette-results">
          {/* Quick Actions */}
          {filteredActions.length > 0 && (
            <div className="palette-section">
              <div className="palette-section-title">Actions</div>
              {filteredActions.map((action, i) => {
                const Icon = action.icon
                const isSelected = selectedIndex === i
                return (
                  <button
                    key={action.id}
                    data-index={i}
                    className={`palette-item ${isSelected ? 'selected' : ''}`}
                    onClick={() => {
                      action.action()
                      onClose()
                    }}
                    onMouseEnter={() => setSelectedIndex(i)}
                  >
                    <div className="palette-item-icon action">
                      <Icon size={18} />
                    </div>
                    <div className="palette-item-content">
                      <div className="palette-item-label">{action.label}</div>
                    </div>
                    {action.shortcut && (
                      <kbd className="palette-item-shortcut">{action.shortcut}</kbd>
                    )}
                  </button>
                )
              })}
            </div>
          )}

          {/* Agents */}
          {scoredAgents.length > 0 && (
            <div className="palette-section">
              <div className="palette-section-title">
                {query ? 'Agents' : 'Recent'}
              </div>
              {scoredAgents.map((agent, i) => {
                const resultIndex = filteredActions.length + i
                const isSelected = selectedIndex === resultIndex
                const badge = getRoleBadge(agent.role)
                
                return (
                  <button
                    key={agent.id}
                    data-index={resultIndex}
                    className={`palette-item ${isSelected ? 'selected' : ''}`}
                    onClick={() => {
                      onSelectAgent(agent.id)
                      onClose()
                    }}
                    onMouseEnter={() => setSelectedIndex(resultIndex)}
                  >
                    {/* Avatar or character card */}
                    <div className="palette-item-icon">
                      {agent.cardUrl ? (
                        <img src={agent.cardUrl} alt={agent.displayName} />
                      ) : (
                        <div className={`avatar-gradient role-${agent.role}`}>
                          {agent.displayName[0]}
                        </div>
                      )}
                    </div>
                    
                    {/* Info */}
                    <div className="palette-item-content">
                      <div className="palette-item-label">
                        {agent.displayName}
                        {agent.isPrimary && <Star size={12} className="inline-star" />}
                      </div>
                      <div className="palette-item-description">
                        {badge.label} · {agent.lastMessage?.slice(0, 50) || agent.personality?.name || ''}
                      </div>
                    </div>
                    
                    {/* Role badge */}
                    <span
                      className="palette-item-badge"
                      style={{ backgroundColor: badge.color }}
                    >
                      {badge.label[0]}
                    </span>
                    
                    {/* Unread */}
                    {agent.unreadCount && agent.unreadCount > 0 && (
                      <span className="palette-item-unread">{agent.unreadCount}</span>
                    )}
                  </button>
                )
              })}
            </div>
          )}

          {/* Empty state */}
          {results.length === 0 && query && (
            <div className="palette-empty">
              <p>No results for "{query}"</p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="palette-footer">
          <span><kbd>↑↓</kbd> Navigate</span>
          <span><kbd>↵</kbd> Select</span>
          <span><kbd>ESC</kbd> Close</span>
        </div>

        <style>{`
          .palette-backdrop {
            position: fixed;
            inset: 0;
            background: rgba(0, 0, 0, 0.4);
            backdrop-filter: blur(4px);
            z-index: 1000;
            animation: fadeIn 0.15s ease;
          }

          .search-palette {
            position: fixed;
            top: 15vh;
            left: 50%;
            transform: translateX(-50%);
            width: 90%;
            max-width: 560px;
            background: var(--background);
            border: 1px solid var(--separator);
            border-radius: 16px;
            box-shadow: 0 24px 48px rgba(0, 0, 0, 0.2);
            z-index: 1001;
            overflow: hidden;
            animation: paletteIn 0.2s cubic-bezier(0.16, 1, 0.3, 1);
          }

          @keyframes paletteIn {
            from {
              opacity: 0;
              transform: translateX(-50%) translateY(-20px) scale(0.95);
            }
            to {
              opacity: 1;
              transform: translateX(-50%) translateY(0) scale(1);
            }
          }

          @keyframes fadeIn {
            from { opacity: 0; }
            to { opacity: 1; }
          }

          .palette-input-wrapper {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 16px 20px;
            border-bottom: 1px solid var(--separator);
            color: var(--secondary-label);
          }

          .palette-input-wrapper input {
            flex: 1;
            border: none;
            outline: none;
            background: none;
            font-size: 16px;
            color: var(--label);
          }

          .palette-input-wrapper input::placeholder {
            color: var(--tertiary-label);
          }

          .palette-input-wrapper kbd {
            padding: 4px 8px;
            background: var(--tertiary-fill);
            border-radius: 6px;
            font-size: 11px;
            color: var(--secondary-label);
            font-family: inherit;
          }

          .palette-results {
            max-height: 400px;
            overflow-y: auto;
            padding: 8px;
          }

          .palette-section {
            margin-bottom: 8px;
          }

          .palette-section-title {
            padding: 8px 12px 4px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--tertiary-label);
          }

          .palette-item {
            display: flex;
            align-items: center;
            gap: 12px;
            width: 100%;
            padding: 10px 12px;
            background: none;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            text-align: left;
            transition: background 0.1s;
          }

          .palette-item:hover,
          .palette-item.selected {
            background: var(--tertiary-fill);
          }

          .palette-item-icon {
            width: 40px;
            height: 40px;
            border-radius: 8px;
            overflow: hidden;
            flex-shrink: 0;
          }

          .palette-item-icon img {
            width: 100%;
            height: 100%;
            object-fit: cover;
          }

          .palette-item-icon.action {
            display: flex;
            align-items: center;
            justify-content: center;
            background: var(--secondary-background);
            color: var(--system-blue);
          }

          .avatar-gradient {
            width: 100%;
            height: 100%;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-size: 16px;
            font-weight: 600;
          }

          .avatar-gradient.role-lead { background: linear-gradient(135deg, #FF9500 0%, #FF6B00 100%); }
          .avatar-gradient.role-specialist { background: linear-gradient(135deg, #007AFF 0%, #5856D6 100%); }
          .avatar-gradient.role-character { background: linear-gradient(135deg, #AF52DE 0%, #5856D6 100%); }
          .avatar-gradient.role-runtime { background: linear-gradient(135deg, #8E8E93 0%, #636366 100%); }

          .palette-item-content {
            flex: 1;
            min-width: 0;
          }

          .palette-item-label {
            font-size: 14px;
            font-weight: 500;
            color: var(--label);
            display: flex;
            align-items: center;
            gap: 6px;
          }

          .inline-star {
            color: #FF9500;
          }

          .palette-item-description {
            font-size: 12px;
            color: var(--secondary-label);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
          }

          .palette-item-badge {
            width: 20px;
            height: 20px;
            border-radius: 6px;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-size: 10px;
            font-weight: 700;
            flex-shrink: 0;
          }

          .palette-item-unread {
            min-width: 20px;
            height: 20px;
            padding: 0 6px;
            border-radius: 10px;
            background: var(--system-blue);
            color: white;
            font-size: 11px;
            font-weight: 600;
            display: flex;
            align-items: center;
            justify-content: center;
          }

          .palette-item-shortcut {
            padding: 2px 6px;
            background: var(--tertiary-fill);
            border-radius: 4px;
            font-size: 11px;
            color: var(--secondary-label);
            font-family: inherit;
          }

          .palette-empty {
            padding: 32px;
            text-align: center;
            color: var(--tertiary-label);
          }

          .palette-footer {
            display: flex;
            align-items: center;
            gap: 16px;
            padding: 10px 20px;
            border-top: 1px solid var(--separator);
            font-size: 11px;
            color: var(--tertiary-label);
          }

          .palette-footer span {
            display: flex;
            align-items: center;
            gap: 4px;
          }

          .palette-footer kbd {
            padding: 2px 5px;
            background: var(--tertiary-fill);
            border-radius: 4px;
            font-family: inherit;
          }

          /* Dark mode */
          .dark .search-palette {
            box-shadow: 0 24px 48px rgba(0, 0, 0, 0.5);
          }
        `}</style>
      </div>
    </>
  )
}

// ─────────────────────────────────────────────────────────────
// Hook for ⌘K shortcut
// ─────────────────────────────────────────────────────────────

export function useSearchPalette(): {
  isOpen: boolean
  open: () => void
  close: () => void
  toggle: () => void
} {
  const [isOpen, setIsOpen] = useState(false)

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // ⌘K or Ctrl+K
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        setIsOpen((prev) => !prev)
      }
      // Also open on ⌘P (like VS Code/Grok)
      if ((e.metaKey || e.ctrlKey) && e.key === 'p' && e.shiftKey === false) {
        // Only if not typing in an input
        if (!(e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement)) {
          e.preventDefault()
          setIsOpen((prev) => !prev)
        }
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [])

  const open = useCallback(() => setIsOpen(true), [])
  const close = useCallback(() => setIsOpen(false), [])
  const toggle = useCallback(() => setIsOpen((prev) => !prev), [])

  return { isOpen, open, close, toggle }
}

export default SearchPalette
