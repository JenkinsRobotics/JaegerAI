/**
 * WindowManager — Multi-window app system (Grok-style App windows)
 *
 * Manages multiple app windows that can be opened, closed, and switched between.
 * Each window is a self-contained page/app within the main Jaeger window.
 *
 * Features:
 * - Window dock at the bottom (macOS-style)
 * - Open/close windows
 * - Switch between active windows
 * - Minimize windows
 * - Window titles and icons
 */

import React, { useState, useCallback, useMemo } from 'react'
import {
  MessageSquare,
  Cpu,
  Cloud,
  Home,
  Zap,
  Users,
  Compass,
  Info,
  Rocket,
  FolderOpen,
  BookOpen,
  Wrench,
  Sparkles,
} from '../components/Icons'

// ─────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────

export type WindowId =
  | 'home'
  | 'chat'
  | 'machine'
  | 'sharepoint'
  | 'tasks'
  | 'agents'
  | 'nav'
  | 'about'
  | 'features'
  | 'library'
  | 'skills'
  | 'workflows'
  | 'tools'

export interface WindowDefinition {
  id: WindowId
  title: string
  icon: React.ComponentType<{ size?: number; className?: string }>
  /** Short description for tooltips/dock */
  description: string
  /** Whether this window can be closed (chat is always present) */
  closable?: boolean
  /** Minimum width/height constraints */
  minWidth?: number
  minHeight?: number
  /**
   * True for panels folded into the Settings hub (About, Features, …).
   * They are real windows with content, but the dock lists only the
   * operator-facing tabs — panels open from Settings rows.
   */
  panel?: boolean
}

export interface WindowInstance {
  id: WindowId
  definition: WindowDefinition
  /** Whether the window is minimized to the dock */
  minimized: boolean
  /** Z-index for stacking (managed by WindowManager) */
  zIndex: number
}

// ─────────────────────────────────────────────────────────────
// Window Definitions
// ─────────────────────────────────────────────────────────────

export const WINDOW_DEFINITIONS: Record<WindowId, WindowDefinition> = {
  home: {
    id: 'home',
    title: 'Home',
    icon: Home,
    description: 'Welcome to JaegerAI — your AI companion',
    closable: true,
  },
  chat: {
    id: 'chat',
    title: 'Chat',
    icon: MessageSquare,
    description: 'Chat with Jaeger and your AI agents',
    closable: false,
  },
  machine: {
    id: 'machine',
    title: 'Machine Control',
    icon: Cpu,
    description: 'Local computer control, screen and permissions',
    closable: true,
  },
  sharepoint: {
    id: 'sharepoint',
    title: 'SharePoint',
    icon: Cloud,
    description: 'SharePoint document libraries and files',
    closable: true,
  },
  tasks: {
    id: 'tasks',
    title: 'Tasks',
    icon: Zap,
    description: 'View and manage tasks',
    closable: true,
  },
  agents: {
    id: 'agents',
    title: 'Agents',
    icon: Users,
    description: 'Manage your AI agents',
    closable: true,
  },
  nav: {
    id: 'nav',
    title: 'Settings',
    icon: Compass,
    description: 'Settings, agents, chats and everything else Jaeger has',
    closable: true,
  },
  about: {
    id: 'about',
    title: 'About',
    icon: Info,
    description: 'About JaegerAI',
    closable: true,
    panel: true,
  },
  features: {
    id: 'features',
    title: 'Features',
    icon: Rocket,
    description: 'Features of JaegerAI',
    closable: true,
    panel: true,
  },
  library: {
    id: 'library',
    title: 'Library',
    icon: FolderOpen,
    description: 'Library of JaegerAI',
    closable: true,
    panel: true,
  },
  skills: {
    id: 'skills',
    title: 'Skills',
    icon: BookOpen,
    description: 'Skills of JaegerAI',
    closable: true,
    panel: true,
  },
  workflows: {
    id: 'workflows',
    title: 'Workflows',
    icon: Wrench,
    description: 'Workflows of JaegerAI',
    closable: true,
    panel: true,
  },
  tools: {
    id: 'tools',
    title: 'Tools',
    icon: Sparkles,
    description: 'Tools of JaegerAI',
    closable: true,
    panel: true,
  },
}

// ─────────────────────────────────────────────────────────────
// Window Manager Hook
// ─────────────────────────────────────────────────────────────

export function useWindowManager() {
  const [windows, setWindows] = useState<WindowInstance[]>([
    {
      id: 'home',
      definition: WINDOW_DEFINITIONS.home,
      minimized: false,
      zIndex: 1,
    },
    {
      id: 'chat',
      definition: WINDOW_DEFINITIONS.chat,
      minimized: false,
      zIndex: 2,
    },
  ])
  const [activeWindowId, setActiveWindowId] = useState<WindowId>('home')
  const [nextZIndex, setNextZIndex] = useState(3)

  const openWindow = useCallback((id: WindowId) => {
    setWindows((prev) => {
      const existing = prev.find((w) => w.id === id)
      if (existing) {
        // Un-minimize and bring to front
        return prev.map((w) =>
          w.id === id ? { ...w, minimized: false, zIndex: nextZIndex } : w
        )
      }
      // Create new window
      const definition = WINDOW_DEFINITIONS[id]
      return [
        ...prev,
        {
          id,
          definition,
          minimized: false,
          zIndex: nextZIndex,
        },
      ]
    })
    setActiveWindowId(id)
    setNextZIndex((z) => z + 1)
  }, [nextZIndex])

  const closeWindow = useCallback((id: WindowId) => {
    setWindows((prev) => {
      const filtered = prev.filter((w) => w.id !== id)
      // If we closed the active window, activate the most recent one
      if (id === activeWindowId && filtered.length > 0) {
        const nextActive = filtered[filtered.length - 1]
        setActiveWindowId(nextActive.id)
      }
      return filtered
    })
  }, [activeWindowId])

  const minimizeWindow = useCallback((id: WindowId) => {
    setWindows((prev) => {
      const updated = prev.map((w) =>
        w.id === id ? { ...w, minimized: true } : w
      )
      // Activate the next non-minimized window
      const nextActive = updated.find((w) => !w.minimized && w.id !== id)
      if (nextActive) {
        setActiveWindowId(nextActive.id)
      } else if (updated.length > 0) {
        setActiveWindowId(updated[0].id)
      }
      return updated
    })
  }, [])

  const focusWindow = useCallback((id: WindowId) => {
    setActiveWindowId(id)
    setWindows((prev) => {
      // Every tab is listed in the dock, so focusing a closed one opens it.
      if (!prev.find((w) => w.id === id)) {
        return [
          ...prev,
          { id, definition: WINDOW_DEFINITIONS[id], minimized: false, zIndex: nextZIndex },
        ]
      }
      return prev.map((w) => (w.id === id ? { ...w, minimized: false } : w))
    })
    setNextZIndex((z) => z + 1)
  }, [nextZIndex])

  const activeWindow = useMemo(
    () => windows.find((w) => w.id === activeWindowId && !w.minimized),
    [windows, activeWindowId]
  )

  const visibleWindows = useMemo(
    () => windows.filter((w) => !w.minimized),
    [windows]
  )

  const minimizedWindows = useMemo(
    () => windows.filter((w) => w.minimized),
    [windows]
  )

  return {
    windows,
    activeWindowId,
    activeWindow,
    visibleWindows,
    minimizedWindows,
    /** WindowIds the dock lists — everything except Settings-hub panels. */
    dockWindows: (Object.keys(WINDOW_DEFINITIONS) as WindowId[]).filter(
      (id) => !WINDOW_DEFINITIONS[id].panel,
    ),
    openWindow,
    closeWindow,
    minimizeWindow,
    focusWindow,
  }
}
