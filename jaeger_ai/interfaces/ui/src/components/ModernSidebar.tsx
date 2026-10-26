/**
 * Modern Sidebar — Premium navigation component
 *
 * Features:
 * - Collapsible design
 * - Agent list with avatars
 * - Search/filter
 * - Section navigation
 * - Smooth animations
 */

import { useState, useMemo } from 'react'
import {
  MessageSquare,
  Users,
  Settings,
  Search,
  Plus,
  ChevronLeft,
  ChevronRight,
  Sparkles,
  Zap,
  Clock,
  Star,
  Archive,
  Trash2,
  MoreHorizontal,
} from 'lucide-react'
import { cn } from '../lib/utils'

export interface Agent {
  id: string
  name: string
  avatar?: string
  status?: string
  isOnline?: boolean
  isPrimary?: boolean
  lastMessage?: string
  unreadCount?: number
}

export interface NavSection {
  id: string
  title: string
  items: NavItem[]
}

export interface NavItem {
  id: string
  label: string
  icon: React.ComponentType<{ className?: string }>
  badge?: number
  onClick?: () => void
}

interface ModernSidebarProps {
  agents: Agent[]
  activeAgentId?: string
  onSelectAgent: (agentId: string) => void
  onNewChat: () => void
  onOpenSettings: () => void
  className?: string
}

const defaultNavSections: NavSection[] = [
  {
    id: 'main',
    title: 'Chat',
    items: [
      { id: 'new-chat', label: 'New Chat', icon: Plus },
      { id: 'search', label: 'Search', icon: Search },
    ],
  },
  {
    id: 'library',
    title: 'Library',
    items: [
      { id: 'recent', label: 'Recent', icon: Clock },
      { id: 'starred', label: 'Starred', icon: Star },
      { id: 'archived', label: 'Archived', icon: Archive },
    ],
  },
]

export function ModernSidebar({
  agents,
  activeAgentId,
  onSelectAgent,
  onNewChat,
  onOpenSettings,
  className,
}: ModernSidebarProps) {
  const [collapsed, setCollapsed] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [activeNavItem, setActiveNavItem] = useState('new-chat')

  const filteredAgents = useMemo(() => {
    if (!searchQuery) return agents
    const query = searchQuery.toLowerCase()
    return agents.filter(
      a => a.name.toLowerCase().includes(query) ||
           a.status?.toLowerCase().includes(query)
    )
  }, [agents, searchQuery])

  const getInitials = (name: string) => {
    return name
      .split(' ')
      .map(n => n[0])
      .join('')
      .toUpperCase()
      .slice(0, 2)
  }

  return (
    <aside className={cn('sidebar', collapsed && 'collapsed', className)}>
      {/* Header */}
      <div className="sidebar-header">
        <div className="sidebar-logo">
          <Sparkles size={18} />
        </div>
        {!collapsed && (
          <span className="sidebar-title gradient-text">JaegerAI</span>
        )}
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="icon-button ml-auto"
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}
        </button>
      </div>

      {/* Search */}
      {!collapsed && (
        <input
          type="text"
          className="sidebar-search"
          placeholder="Search agents..."
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
        />
      )}

      {/* Navigation */}
      <nav className="sidebar-nav">
        {defaultNavSections.map(section => (
          <div key={section.id} className="nav-section">
            {!collapsed && (
              <div className="nav-section-title">{section.title}</div>
            )}
            {section.items.map(item => (
              <button
                key={item.id}
                className={cn('nav-item', activeNavItem === item.id && 'active')}
                onClick={() => {
                  setActiveNavItem(item.id)
                  if (item.id === 'new-chat') onNewChat()
                  item.onClick?.()
                }}
                title={collapsed ? item.label : undefined}
              >
                <item.icon className="nav-item-icon" />
                {!collapsed && <span>{item.label}</span>}
                {item.badge && !collapsed && (
                  <span className="nav-item-badge">{item.badge}</span>
                )}
              </button>
            ))}
          </div>
        ))}

        {/* Agents Section */}
        <div className="nav-section">
          {!collapsed && (
            <div className="nav-section-title">Agents</div>
          )}
          {filteredAgents.map(agent => (
            <div
              key={agent.id}
              className={cn(
                'agent-list-item',
                activeAgentId === agent.id && 'active'
              )}
              onClick={() => onSelectAgent(agent.id)}
            >
              <div className={cn(
                'agent-avatar',
                agent.isOnline && 'online'
              )}>
                {agent.avatar ? (
                  <img src={agent.avatar} alt={agent.name} />
                ) : (
                  getInitials(agent.name)
                )}
              </div>
              {!collapsed && (
                <div className="agent-info">
                  <div className="agent-name">
                    {agent.name}
                    {agent.isPrimary && (
                      <Star size={12} className="inline ml-1 text-yellow-500 fill-current" />
                    )}
                  </div>
                  {agent.lastMessage && (
                    <div className="agent-status">{agent.lastMessage}</div>
                  )}
                </div>
              )}
              {!collapsed && agent.unreadCount && agent.unreadCount > 0 && (
                <span className="nav-item-badge">{agent.unreadCount}</span>
              )}
            </div>
          ))}
        </div>
      </nav>

      {/* Footer */}
      <div className="sidebar-footer" style={{ padding: 'var(--space-4)', borderTop: '1px solid var(--border-primary)' }}>
        <button
          className="nav-item w-full"
          onClick={onOpenSettings}
          title={collapsed ? 'Settings' : undefined}
        >
          <Settings className="nav-item-icon" />
          {!collapsed && <span>Settings</span>}
        </button>
      </div>
    </aside>
  )
}

/**
 * Mobile Sidebar Toggle — Hamburger menu
 */
export function MobileSidebarToggle({ onClick, className }: { onClick: () => void; className?: string }) {
  return (
    <button onClick={onClick} className={cn('icon-button md:hidden', className)} aria-label="Open menu">
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <line x1="3" y1="12" x2="21" y2="12" />
        <line x1="3" y1="6" x2="21" y2="6" />
        <line x1="3" y1="18" x2="21" y2="18" />
      </svg>
    </button>
  )
}
