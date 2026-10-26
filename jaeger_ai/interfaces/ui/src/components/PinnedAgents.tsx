/**
 * PinnedAgents — Grok-style pinned agents strip
 *
 * The supervisor/lead tile is always first, then pinned agents.
 * Drag agents to pin them, drag tiles back to unpin.
 *
 * Features:
 * - Drag-and-drop pinning/unpinning
 * - Per-device persistence (localStorage)
 * - Max 8 pins
 * - Character cards shown as thumbnails
 * - Unread indicators
 */

import { useState, useCallback, useRef, useEffect } from 'react'

// ─────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────

export interface PinnableAgent {
  id: string
  name: string
  role: 'lead' | 'specialist' | 'character' | 'runtime'
  isPrimary?: boolean
  isOnline?: boolean
  unreadCount?: number
  lastMessage?: string
  cardUrl?: string | null  // Character card thumbnail
  personality?: {
    name: string
    voiceTone: string
  }
}

interface PinnedAgentsProps {
  leadAgent: PinnableAgent | null
  pinnedAgents: PinnableAgent[]
  allAgents: PinnableAgent[]
  onPin: (agentId: string) => void
  onUnpin: (agentId: string) => void
  onSelectAgent: (agentId: string) => void
  activeAgentId: string
}

const MAX_PINS = 8
const PINS_KEY = 'jaeger.ui.pinned-agents'

// ─────────────────────────────────────────────────────────────
// Pin Management Hook
// ─────────────────────────────────────────────────────────────

export function usePins() {
  const [pins, setPins] = useState<string[]>(() => {
    try {
      const raw = localStorage.getItem(PINS_KEY)
      if (raw) {
        const parsed = JSON.parse(raw)
        return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === 'string').slice(0, MAX_PINS) : []
      }
    } catch {}
    return []
  })

  const savePins = useCallback((next: string[]) => {
    const limited = next.slice(0, MAX_PINS)
    setPins(limited)
    try {
      localStorage.setItem(PINS_KEY, JSON.stringify(limited))
    } catch {}
  }, [])

  const pin = useCallback((agentId: string) => {
    setPins((cur) => {
      const rest = cur.filter((p) => p !== agentId)
      const next = [...rest, agentId].slice(0, MAX_PINS)
      try { localStorage.setItem(PINS_KEY, JSON.stringify(next)) } catch {}
      return next
    })
  }, [])

  const unpin = useCallback((agentId: string) => {
    setPins((cur) => {
      const next = cur.filter((p) => p !== agentId)
      try { localStorage.setItem(PINS_KEY, JSON.stringify(next)) } catch {}
      return next
    })
  }, [])

  const isPinned = useCallback((agentId: string) => pins.includes(agentId), [pins])

  return { pins, pin, unpin, isPinned, savePins }
}

// ─────────────────────────────────────────────────────────────
// Agent Tile Component
// ─────────────────────────────────────────────────────────────

interface AgentTileProps {
  agent: PinnableAgent
  isActive: boolean
  isDragging: boolean
  onSelect: () => void
  onDragStart: (e: React.DragEvent) => void
  onDragEnd: () => void
  onDrop: (e: React.DragEvent) => void
  onDragOver: (e: React.DragEvent) => void
  isDropTarget: boolean
}

function AgentTile({
  agent,
  isActive,
  isDragging,
  onSelect,
  onDragStart,
  onDragEnd,
  onDrop,
  onDragOver,
  isDropTarget,
}: AgentTileProps) {
  const gradients: Record<string, string> = {
    jarvis: 'linear-gradient(135deg, #1e3a5f 0%, #2d5a87 100%)',
    lilith: 'linear-gradient(135deg, #4a148c 0%, #7b1fa2 100%)',
    kamina: 'linear-gradient(135deg, #d32f2f 0%, #f57c00 100%)',
    bender: 'linear-gradient(135deg, #616161 0%, #9e9e9e 100%)',
    glados: 'linear-gradient(135deg, #0277bd 0%, #00acc1 100%)',
    hal_9000: 'linear-gradient(135deg, #b71c1c 0%, #e53935 100%)',
    mochi: 'linear-gradient(135deg, #f06292 0%, #f8bbd0 100%)',
    tars: 'linear-gradient(135deg, #37474f 0%, #546e7a 100%)',
  }

  const isCharacter = agent.role === 'character'
  const defaultGradient = 'linear-gradient(135deg, #616161 0%, #9e9e9e 100%)'
  const gradient = gradients[agent.id] || defaultGradient

  return (
    <button
      className={`pinned-tile ${isActive ? 'active' : ''} ${isDragging ? 'dragging' : ''} ${isDropTarget ? 'drop-target' : ''}`}
      onClick={onSelect}
      draggable
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onDrop={onDrop}
      onDragOver={onDragOver}
      title={agent.personality?.name || agent.name}
    >
      {/* Avatar or Character Card */}
      <div className="pinned-tile-avatar">
        {agent.cardUrl ? (
          <img
            src={agent.cardUrl}
            alt={agent.name}
            className="pinned-tile-card"
            loading="lazy"
          />
        ) : (
          <div
            className="pinned-tile-gradient"
            style={{ background: gradient }}
          >
            {agent.name[0].toUpperCase()}
          </div>
        )}
        
        {/* Badges */}
        {agent.isPrimary && <span className="tile-badge tile-star">⭐</span>}
        {isCharacter && <span className="tile-badge tile-character">🎭</span>}
        
        {/* Unread indicator */}
        {agent.unreadCount && agent.unreadCount > 0 && (
          <span className="tile-unread">{agent.unreadCount > 9 ? '9+' : agent.unreadCount}</span>
        )}
        
        {/* Online dot */}
        {agent.isOnline && <span className="tile-online" />}
      </div>
      
      {/* Name */}
      <span className="pinned-tile-name">{agent.name}</span>

      <style>{`
        .pinned-tile {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 6px;
          padding: 8px;
          background: none;
          border: none;
          border-radius: 12px;
          cursor: grab;
          transition: all 0.2s ease;
          width: 72px;
        }

        .pinned-tile:hover {
          background: var(--secondary-background);
        }

        .pinned-tile.active {
          background: var(--tertiary-fill);
        }

        .pinned-tile.dragging {
          opacity: 0.5;
          cursor: grabbing;
        }

        .pinned-tile.drop-target {
          background: rgba(0, 122, 255, 0.1);
          outline: 2px dashed var(--system-blue);
          outline-offset: 2px;
        }

        .pinned-tile-avatar {
          position: relative;
          width: 48px;
          height: 48px;
        }

        .pinned-tile-card {
          width: 100%;
          height: 100%;
          object-fit: cover;
          border-radius: 10px;
          border: 1px solid var(--separator);
        }

        .pinned-tile-gradient {
          width: 100%;
          height: 100%;
          border-radius: 10px;
          display: flex;
          align-items: center;
          justify-content: center;
          color: white;
          font-size: 20px;
          font-weight: 600;
        }

        .tile-badge {
          position: absolute;
          bottom: -4px;
          right: -4px;
          width: 18px;
          height: 18px;
          border-radius: 50%;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 10px;
          background: white;
          border: 1px solid var(--separator);
        }

        .tile-star {
          background: #FFCC00;
        }

        .tile-character {
          background: #AF52DE;
          color: white;
        }

        .tile-unread {
          position: absolute;
          top: -4px;
          right: -4px;
          min-width: 18px;
          height: 18px;
          padding: 0 4px;
          border-radius: 9px;
          background: var(--system-blue);
          color: white;
          font-size: 11px;
          font-weight: 600;
          display: flex;
          align-items: center;
          justify-content: center;
        }

        .tile-online {
          position: absolute;
          bottom: 2px;
          right: 2px;
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background: var(--system-green);
          border: 2px solid var(--background);
        }

        .pinned-tile-name {
          font-size: 11px;
          font-weight: 500;
          color: var(--secondary-label);
          max-width: 100%;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .pinned-tile.active .pinned-tile-name {
          color: var(--label);
        }
      `}</style>
    </button>
  )
}

// ─────────────────────────────────────────────────────────────
// Pinned Strip Component
// ─────────────────────────────────────────────────────────────

export function PinnedAgents({
  leadAgent,
  pinnedAgents,
  allAgents,
  onPin,
  onUnpin,
  onSelectAgent,
  activeAgentId,
}: PinnedAgentsProps) {
  const [draggedAgent, setDraggedAgent] = useState<PinnableAgent | null>(null)
  const [dropTarget, setDropTarget] = useState<string | null>(null)

  const handleDragStart = useCallback((agent: PinnableAgent) => (e: React.DragEvent) => {
    setDraggedAgent(agent)
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('agent-id', agent.id)
  }, [])

  const handleDragEnd = useCallback(() => {
    setDraggedAgent(null)
    setDropTarget(null)
  }, [])

  const handleDrop = useCallback((targetAgent: PinnableAgent) => (e: React.DragEvent) => {
    e.preventDefault()
    const draggedId = e.dataTransfer.getData('agent-id')
    if (draggedId && draggedId !== targetAgent.id) {
      // If dropped on a pinned tile, the dragged agent swaps or inserts
      // For now, just pin the dragged agent
      if (!pinnedAgents.find(a => a.id === draggedId) && draggedId !== leadAgent?.id) {
        onPin(draggedId)
      }
    }
    setDropTarget(null)
  }, [pinnedAgents, leadAgent, onPin])

  const handleDragOver = useCallback((targetAgent: PinnableAgent) => (e: React.DragEvent) => {
    e.preventDefault()
    setDropTarget(targetAgent.id)
  }, [])

  // Find unpinned agents that could be pinned here
  const unpinnedAgents = allAgents.filter(
    a => a.id !== leadAgent?.id && !pinnedAgents.find(p => p.id === a.id)
  )

  const handleStripDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    const draggedId = e.dataTransfer.getData('agent-id')
    if (draggedId && draggedId !== leadAgent?.id) {
      onPin(draggedId)
    }
    setDropTarget(null)
  }, [leadAgent, onPin])

  const handleStripDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
  }, [])

  return (
    <div
      className="pinned-strip"
      onDrop={handleStripDrop}
      onDragOver={handleStripDragOver}
    >
      {/* Lead/Supervisor tile — always first, never removable */}
      {leadAgent && (
        <AgentTile
          agent={leadAgent}
          isActive={activeAgentId === leadAgent.id}
          isDragging={draggedAgent?.id === leadAgent.id}
          onSelect={() => onSelectAgent(leadAgent.id)}
          onDragStart={handleDragStart(leadAgent)}
          onDragEnd={handleDragEnd}
          onDrop={handleDrop(leadAgent)}
          onDragOver={handleDragOver(leadAgent)}
          isDropTarget={dropTarget === leadAgent.id}
        />
      )}

      {/* Pinned agents */}
      {pinnedAgents.map((agent) => (
        <AgentTile
          key={agent.id}
          agent={agent}
          isActive={activeAgentId === agent.id}
          isDragging={draggedAgent?.id === agent.id}
          onSelect={() => onSelectAgent(agent.id)}
          onDragStart={handleDragStart(agent)}
          onDragEnd={handleDragEnd}
          onDrop={handleDrop(agent)}
          onDragOver={handleDragOver(agent)}
          isDropTarget={dropTarget === agent.id}
        />
      ))}

      {/* Empty slots hint */}
      {pinnedAgents.length < 7 && (
        <div className="pinned-slot-empty" title={`Drag agents here to pin (${pinnedAgents.length + 1}/8)`}>
          <span>+</span>
        </div>
      )}

      <style>{`
        .pinned-strip {
          display: flex;
          align-items: flex-start;
          gap: 4px;
          padding: 12px;
          background: var(--secondary-background);
          border-bottom: 1px solid var(--separator);
          min-height: 96px;
          overflow-x: auto;
          scrollbar-width: none;
        }

        .pinned-strip::-webkit-scrollbar {
          display: none;
        }

        .pinned-slot-empty {
          display: flex;
          align-items: center;
          justify-content: center;
          width: 48px;
          height: 48px;
          border: 2px dashed var(--quaternary-fill);
          border-radius: 10px;
          color: var(--tertiary-label);
          font-size: 20px;
          margin-top: 2px;
          opacity: 0.5;
          transition: all 0.2s;
        }

        .pinned-strip:hover .pinned-slot-empty {
          opacity: 1;
          border-color: var(--system-blue);
          color: var(--system-blue);
        }

        @media (max-width: 768px) {
          .pinned-strip {
            padding: 8px;
          }
        }
      `}</style>
    </div>
  )
}

export default PinnedAgents
