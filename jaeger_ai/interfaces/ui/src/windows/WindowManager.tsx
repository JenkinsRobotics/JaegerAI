/**
 * WindowManager — the unified shell's pages (Jenkins Robotics, 2026-10-30).
 *
 * Every feature is a dock page with a real route (see shell/router.ts). The
 * route decides which page is in front; the manager tracks which pages are
 * open (kept mounted so streams and drafts survive switching), their dock
 * order and minimized state, and persists that layout in localStorage.
 */
import type React from 'react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { MessageSquare, Cpu, Cloud, Home, Zap, Users, Settings, Sparkles, BarChart, Image, Database, Workflow, Compass, FileText } from '../components/Icons'
import { PAGES, type PageId } from '../shell/router'

export type WindowId = PageId

export interface WindowDefinition {
  id: WindowId
  title: string
  icon: React.ComponentType<{ size?: number; className?: string }>
  description: string
  /** Pages that can't be closed (Home, Chat). */
  closable?: boolean
  /** Shown in the phone bottom tab bar (the rest go under "More"). */
  phoneTab?: boolean
}

export interface WindowInstance {
  id: WindowId
  definition: WindowDefinition
  minimized: boolean
  zIndex: number
}

export const WINDOW_DEFINITIONS: Record<WindowId, WindowDefinition> = {
  home: { id: 'home', title: 'Home', icon: Home, description: 'Active agents, approvals, recent chats and tasks', closable: false, phoneTab: true },
  chat: { id: 'chat', title: 'Chat', icon: MessageSquare, description: 'Chat with Jaeger and your specialists', closable: false, phoneTab: true },
  agents: { id: 'agents', title: 'Agents', icon: Users, description: 'Your agents and specialists', closable: true, phoneTab: true },
  characters: { id: 'characters', title: 'Characters', icon: Sparkles, description: 'Create a new agent from a character', closable: true },
  tasks: { id: 'tasks', title: 'Tasks', icon: Zap, description: 'Tasks, runs and artifacts', closable: true, phoneTab: true },
  machine: { id: 'machine', title: 'Machine Control', icon: Cpu, description: 'Local computer control, screen and permissions', closable: true },
  sharepoint: { id: 'sharepoint', title: 'SharePoint', icon: Cloud, description: 'Document libraries and artifacts', closable: true },
  workspace: { id: 'workspace', title: 'Workspace', icon: BarChart, description: 'Your own widget dashboard', closable: true },
  studio: { id: 'studio', title: 'Studio', icon: Image, description: 'Generate images, asset library and board', closable: true },
  models: { id: 'models', title: 'Models', icon: Database, description: 'Local Ollama models, sizes and fit for this Mac', closable: true },
  compare: { id: 'compare', title: 'Compare', icon: Workflow, description: 'One prompt, two models, side by side', closable: true },
  research: { id: 'research', title: 'Research', icon: Compass, description: 'Deep research runs as an approved task with a report', closable: true },
  documents: { id: 'documents', title: 'Documents', icon: FileText, description: 'Markdown documents with AI edit actions', closable: true },
  settings: { id: 'settings', title: 'Settings', icon: Settings, description: 'Settings, grouped by category (⌘,)', closable: true },
}

export const LAYOUT_KEY = 'jaeger.shell.layout.v1'

export interface StoredLayout { open: WindowId[]; minimized: WindowId[]; order: WindowId[] }

const DEFAULT_LAYOUT: StoredLayout = { open: ['home', 'chat'], minimized: [], order: [...PAGES] }

const isPage = (v: unknown): v is WindowId => typeof v === 'string' && (PAGES as readonly string[]).includes(v)

export function loadLayout(storage: Pick<Storage, 'getItem'> | undefined = globalThis.localStorage): StoredLayout {
  try {
    const raw = storage?.getItem(LAYOUT_KEY)
    if (!raw) return DEFAULT_LAYOUT
    const parsed = JSON.parse(raw) as Partial<StoredLayout>
    const open = (parsed.open ?? []).filter(isPage)
    const order = (parsed.order ?? []).filter(isPage)
    for (const id of ['home', 'chat'] as WindowId[]) if (!open.includes(id)) open.unshift(id)
    for (const id of PAGES) if (!order.includes(id)) order.push(id)
    return { open: [...new Set(open)], minimized: (parsed.minimized ?? []).filter(isPage), order: [...new Set(order)] }
  } catch { return DEFAULT_LAYOUT }
}

export function saveLayout(layout: StoredLayout, storage: Pick<Storage, 'setItem'> | undefined = globalThis.localStorage): void {
  try { storage?.setItem(LAYOUT_KEY, JSON.stringify(layout)) } catch { /* storage unavailable */ }
}

/** Route-driven: `activeWindowId` is the page the URL names; opening it adds it to the open set. */
export function useWindowManager(activeWindowId: WindowId) {
  const [layout, setLayout] = useState<StoredLayout>(loadLayout)
  useEffect(() => {
    setLayout((cur) => cur.open.includes(activeWindowId) && !cur.minimized.includes(activeWindowId)
      ? cur : { ...cur, open: cur.open.includes(activeWindowId) ? cur.open : [...cur.open, activeWindowId], minimized: cur.minimized.filter((id) => id !== activeWindowId) })
  }, [activeWindowId])
  useEffect(() => saveLayout(layout), [layout])

  const closeWindow = useCallback((id: WindowId) => {
    if (!WINDOW_DEFINITIONS[id].closable) return
    setLayout((cur) => ({ ...cur, open: cur.open.filter((w) => w !== id), minimized: cur.minimized.filter((w) => w !== id) }))
  }, [])
  const minimizeWindow = useCallback((id: WindowId) => setLayout((cur) => ({ ...cur, minimized: [...new Set([...cur.minimized, id])] })), [])
  const moveWindow = useCallback((id: WindowId, toIndex: number) => setLayout((cur) => {
    const order = cur.order.filter((w) => w !== id); order.splice(Math.max(0, Math.min(toIndex, order.length)), 0, id)
    return { ...cur, order }
  }), [])

  const windows = useMemo<WindowInstance[]>(() => layout.order.filter((id) => layout.open.includes(id)).map((id, i) => ({
    id, definition: WINDOW_DEFINITIONS[id], minimized: layout.minimized.includes(id), zIndex: id === activeWindowId ? 10 : i + 1,
  })), [layout, activeWindowId])

  return {
    layout,
    windows,
    activeWindowId,
    visibleWindows: windows.filter((w) => !w.minimized),
    dockWindows: layout.order,
    closeWindow,
    minimizeWindow,
    moveWindow,
  }
}
