/**
 * AgentContextMenu — Role-aware right-click context menu
 *
 * Different menus for different agent types:
 * - Lead: Pin, Mark Read, Rename, Change Personality, View Details
 * - Specialist: Pin, Move to Section, Mark Read, Rename, Add Personality, Details
 * - Character: Pin, Toggle Tools, Edit Personality, Convert to Specialist, Delete
 *
 * Apple-native styling with smooth animations.
 */

import { useState, useEffect, useRef, useCallback } from 'react'
import {
  Pin,
  PinOff,
  Check,
  Pencil,
  User,
  Wrench,
  Star,
  Eye,
  Copy,
  EyeOff,
  Trash2,
  MoreHorizontal,
  FolderInput,
  Volume2,
  MessageSquare,
} from './Icons'

// ─────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────

export interface ContextMenuAgent {
  id: string
  name: string
  displayName: string
  role: 'lead' | 'specialist' | 'character' | 'runtime'
  isPrimary: boolean
  isPinned: boolean
  unreadCount: number
  hasPersonality: boolean
  toolCount: number
  templateId?: string
}

interface MenuAction {
  id: string
  label: string
  icon?: React.ComponentType<{ size?: number }>
  shortcut?: string
  danger?: boolean
  disabled?: boolean
  separator?: boolean
  submenu?: MenuAction[]
}

interface AgentContextMenuProps {
  agent: ContextMenuAgent
  isOpen: boolean
  position: { x: number; y: number }
  onClose: () => void
  onAction: (action: string, agent: ContextMenuAgent) => void
}

// ─────────────────────────────────────────────────────────────
// Menu Builders (Role-Aware)
// ─────────────────────────────────────────────────────────────

function buildMenuItems(agent: ContextMenuAgent): MenuAction[] {
  const items: MenuAction[] = []

  // ── Common items ──
  
  // Pin/Unpin
  items.push({
    id: agent.isPinned ? 'unpin' : 'pin',
    label: agent.isPinned ? 'Unpin' : 'Pin to Top',
    icon: agent.isPinned ? PinOff : Pin,
  })

  // Move to Section (not for lead/primary)
  if (!agent.isPrimary) {
    items.push({
      id: 'move-to-section',
      label: 'Move to Section',
      icon: FolderInput,
      submenu: [
        { id: 'section-new', label: 'New Section…' },
        { id: 'section-unassigned', label: 'Unassigned', separator: true },
      ],
    })
  }

  items.push({ id: 'sep-1', label: '', separator: true })

  // Mark as Read / Unread
  if (agent.unreadCount > 0) {
    items.push({
      id: 'mark-read',
      label: 'Mark as Read',
      icon: Check,
    })
  } else {
    items.push({
      id: 'mark-unread',
      label: 'Mark as Unread',
      icon: Eye,
    })
  }

  // ── Role-specific items ──
  
  if (agent.role === 'lead') {
    // Lead-specific
    items.push({ id: 'sep-2', label: '', separator: true })
    items.push({
      id: 'rename',
      label: 'Rename',
      icon: Pencil,
    })
    items.push({
      id: 'change-personality',
      label: agent.hasPersonality ? 'Change Personality' : 'Add Personality',
      icon: User,
    })
    items.push({ id: 'sep-3', label: '', separator: true })
    items.push({
      id: 'view-details',
      label: 'View Details',
      icon: Eye,
    })
    items.push({
      id: 'replace-primary',
      label: 'Replace as Primary…',
      icon: Star,
      danger: true,
    })
  } 
  else if (agent.role === 'specialist') {
    // Specialist-specific
    items.push({ id: 'sep-2', label: '', separator: true })
    items.push({
      id: 'rename',
      label: 'Rename',
      icon: Pencil,
    })
    items.push({
      id: 'add-personality',
      label: agent.hasPersonality ? 'Edit Personality' : 'Add Personality',
      icon: User,
    })
    items.push({
      id: 'view-tools',
      label: `Tools (${agent.toolCount})`,
      icon: Wrench,
    })
    items.push({ id: 'sep-3', label: '', separator: true })
    items.push({
      id: 'view-details',
      label: 'View Details',
      icon: Eye,
    })
    items.push({
      id: 'make-primary',
      label: 'Make Primary',
      icon: Star,
    })
  } 
  else if (agent.role === 'character') {
    // Character-specific
    items.push({ id: 'sep-2', label: '', separator: true })
    items.push({
      id: 'rename',
      label: 'Rename',
      icon: Pencil,
    })
    items.push({
      id: 'edit-personality',
      label: 'Edit Personality',
      icon: User,
    })
    items.push({
      id: 'toggle-tools',
      label: agent.toolCount === 0 ? 'Enable Tools…' : `Tools (${agent.toolCount})`,
      icon: Wrench,
    })
    items.push({ id: 'sep-3', label: '', separator: true })
    items.push({
      id: 'view-details',
      label: 'View Character Card',
      icon: Eye,
    })
    items.push({
      id: 'read-aloud',
      label: 'Read Aloud',
      icon: Volume2,
    })
    items.push({ id: 'sep-4', label: '', separator: true })
    items.push({
      id: 'convert-to-specialist',
      label: 'Convert to Specialist',
      icon: Wrench,
    })
    items.push({
      id: 'make-primary',
      label: 'Make Primary',
      icon: Star,
    })
  }

  // ── Common bottom items ──
  
  items.push({ id: 'sep-5', label: '', separator: true })
  items.push({
    id: 'copy-id',
    label: 'Copy Agent ID',
    icon: Copy,
  })
  
  if (!agent.isPrimary) {
    items.push({ id: 'sep-6', label: '', separator: true })
    items.push({
      id: 'hide',
      label: 'Hide from Sidebar',
      icon: EyeOff,
    })
    items.push({
      id: 'delete',
      label: 'Delete',
      icon: Trash2,
      danger: true,
    })
  }

  return items
}

// ─────────────────────────────────────────────────────────────
// Context Menu Component
// ─────────────────────────────────────────────────────────────

export function AgentContextMenu({
  agent,
  isOpen,
  position,
  onClose,
  onAction,
}: AgentContextMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null)
  const [activeSubmenu, setActiveSubmenu] = useState<string | null>(null)

  // Close on click outside
  useEffect(() => {
    if (!isOpen) return

    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose()
      }
    }

    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose()
      }
    }

    document.addEventListener('mousedown', handleClickOutside)
    document.addEventListener('keydown', handleEscape)

    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
      document.removeEventListener('keydown', handleEscape)
    }
  }, [isOpen, onClose])

  if (!isOpen) return null

  const items = buildMenuItems(agent)

  // Adjust position to stay on screen
  const menuStyle: React.CSSProperties = {
    position: 'fixed',
    left: Math.min(position.x, window.innerWidth - 220),
    top: Math.min(position.y, window.innerHeight - 400),
    zIndex: 1000,
  }

  const handleItemClick = (actionId: string) => {
    onAction(actionId, agent)
    onClose()
  }

  return (
    <>
      {/* Backdrop */}
      <div className="context-menu-backdrop" />
      
      {/* Menu */}
      <div
        ref={menuRef}
        className="context-menu"
        style={menuStyle}
        role="menu"
        aria-label={`Actions for ${agent.displayName}`}
      >
        {/* Preview header (character card for characters) */}
        {agent.role === 'character' && (
          <div className="context-menu-preview">
            <div className="preview-avatar">
              {agent.displayName[0]}
            </div>
            <div className="preview-info">
              <div className="preview-name">{agent.displayName}</div>
              <div className="preview-role">🎭 Character</div>
            </div>
          </div>
        )}
        
        {/* Menu items */}
        {items.map((item) => {
          if (item.separator) {
            return <div key={item.id} className="context-menu-separator" />
          }

          const Icon = item.icon
          const hasSubmenu = item.submenu && item.submenu.length > 0

          return (
            <button
              key={item.id}
              className={`context-menu-item ${item.danger ? 'danger' : ''} ${item.disabled ? 'disabled' : ''}`}
              onClick={() => !item.disabled && !hasSubmenu && handleItemClick(item.id)}
              onMouseEnter={() => hasSubmenu && setActiveSubmenu(item.id)}
              onMouseLeave={() => hasSubmenu && setActiveSubmenu(null)}
              disabled={item.disabled}
              role="menuitem"
            >
              {Icon && <Icon size={16} />}
              <span className="context-menu-label">{item.label}</span>
              {item.shortcut && <span className="context-menu-shortcut">{item.shortcut}</span>}
              {hasSubmenu && <span className="context-menu-arrow">›</span>}
              
              {/* Submenu */}
              {hasSubmenu && activeSubmenu === item.id && (
                <div className="context-menu-submenu" role="menu">
                  {item.submenu!.map((subitem) => (
                    <button
                      key={subitem.id}
                      className="context-menu-item"
                      onClick={() => handleItemClick(subitem.id)}
                      role="menuitem"
                    >
                      <span className="context-menu-label">{subitem.label}</span>
                    </button>
                  ))}
                </div>
              )}
            </button>
          )
        })}
      </div>

      <style>{`
        .context-menu-backdrop {
          position: fixed;
          inset: 0;
          z-index: 999;
        }

        .context-menu {
          min-width: 200px;
          max-width: 280px;
          background: var(--background);
          border: 1px solid var(--separator);
          border-radius: 12px;
          box-shadow: 0 8px 32px rgba(0, 0, 0, 0.12), 0 2px 8px rgba(0, 0, 0, 0.08);
          padding: 4px;
          animation: contextMenuIn 0.15s ease;
          overflow: hidden;
        }

        @keyframes contextMenuIn {
          from {
            opacity: 0;
            transform: scale(0.95) translateY(-4px);
          }
          to {
            opacity: 1;
            transform: scale(1) translateY(0);
          }
        }

        .context-menu-preview {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 12px;
          margin-bottom: 4px;
          background: var(--secondary-background);
          border-radius: 8px;
        }

        .preview-avatar {
          width: 40px;
          height: 40px;
          border-radius: 10px;
          background: linear-gradient(135deg, #AF52DE 0%, #5856D6 100%);
          color: white;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 18px;
          font-weight: 600;
        }

        .preview-name {
          font-size: 14px;
          font-weight: 600;
          color: var(--label);
        }

        .preview-role {
          font-size: 12px;
          color: var(--secondary-label);
        }

        .context-menu-item {
          display: flex;
          align-items: center;
          gap: 10px;
          width: 100%;
          padding: 8px 10px;
          background: none;
          border: none;
          border-radius: 6px;
          font-size: 13px;
          color: var(--label);
          cursor: pointer;
          text-align: left;
          position: relative;
          transition: background 0.1s;
        }

        .context-menu-item:hover:not(.disabled) {
          background: var(--tertiary-fill);
        }

        .context-menu-item.danger {
          color: var(--system-red);
        }

        .context-menu-item.danger:hover:not(.disabled) {
          background: rgba(255, 59, 48, 0.1);
        }

        .context-menu-item.disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }

        .context-menu-label {
          flex: 1;
        }

        .context-menu-shortcut {
          font-size: 11px;
          color: var(--tertiary-label);
        }

        .context-menu-arrow {
          font-size: 16px;
          color: var(--tertiary-label);
        }

        .context-menu-separator {
          height: 1px;
          background: var(--separator);
          margin: 4px 8px;
        }

        .context-menu-submenu {
          position: absolute;
          left: 100%;
          top: -4px;
          min-width: 160px;
          background: var(--background);
          border: 1px solid var(--separator);
          border-radius: 8px;
          box-shadow: 0 4px 16px rgba(0, 0, 0, 0.1);
          padding: 4px;
          animation: contextMenuIn 0.1s ease;
        }

        /* Dark mode adjustments */
        .dark .context-menu {
          box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4), 0 2px 8px rgba(0, 0, 0, 0.3);
        }
      `}</style>
    </>
  )
}

// ─────────────────────────────────────────────────────────────
// Hook for managing context menu state
// ─────────────────────────────────────────────────────────────

export function useContextMenu() {
  const [menuState, setMenuState] = useState<{
    isOpen: boolean
    agent: ContextMenuAgent | null
    position: { x: number; y: number }
  }>({ isOpen: false, agent: null, position: { x: 0, y: 0 } })

  const openMenu = useCallback((agent: ContextMenuAgent, e: React.MouseEvent) => {
    e.preventDefault()
    setMenuState({
      isOpen: true,
      agent,
      position: { x: e.clientX, y: e.clientY },
    })
  }, [])

  const closeMenu = useCallback(() => {
    setMenuState((prev) => ({ ...prev, isOpen: false }))
  }, [])

  return { menuState, openMenu, closeMenu }
}

export default AgentContextMenu
