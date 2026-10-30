/**
 * AppWindow — the one Jaeger shell (unified UI, Jenkins Robotics 2026-10-30).
 *
 * The Windows UI's dock is the frame; every feature is a dock page at a real route
 * (/, /chat, /agents, /characters, /tasks, /machine, /sharepoint, /workspace, /settings).
 * Open pages stay mounted (chat streams, drafts and approvals keep running while you look
 * elsewhere); the URL decides which one is in front. ⌘K opens the one command palette,
 * ⌘, opens Settings, and pending approvals are reachable from every page. On a phone or
 * narrow window the dock becomes a bottom tab bar.
 */
import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from 'react'
import type { JaegerSource } from '../api/source'
import { useWindowManager, WINDOW_DEFINITIONS, type WindowId } from './WindowManager'
import { WindowDock } from './WindowDock'
import { useAgentsStore } from '../agents/agentsStore'
import { visible } from '../agents/agentsLogic'
import { JumpTo, type JumpAction } from '../agents/JumpTo'
import { CHARACTERS } from '../components/CharacterLibrary'
import { usePhone } from '../phone/usePhone'
import { navigate, useRoute, PAGES } from '../shell/router'
import { isSettingsTab, type Tab as SettingsTab } from '../settings/SettingsDialog'
import { HomeDashboard } from '../unified/HomeDashboard'
import { ApprovalTray } from '../unified/ApprovalTray'
import './windows.css'
import '../unified/unified.css'
import '../unified/design.css'
import { ToastProvider, SkeletonRows } from '../unified/ui'

// Route-level code splitting: every page but Home loads on first open.
const App = lazy(() => import('../App').then((m) => ({ default: m.App })))
const TasksPage = lazy(() => import('./TasksPage').then((m) => ({ default: m.TasksPage })))
const WorkspacePage = lazy(() => import('./WorkspacePage').then((m) => ({ default: m.WorkspacePage })))
const MachineControlPanel = lazy(() => import('../machine-control/MachineControlPanel').then((m) => ({ default: m.MachineControlPanel })))
const SharePointPanel = lazy(() => import('../sharepoint/SharePointPanel').then((m) => ({ default: m.SharePointPanel })))
const AgentsRoster = lazy(() => import('../unified/AgentsRoster').then((m) => ({ default: m.AgentsRoster })))
const CharactersPage = lazy(() => import('../unified/CharactersPage').then((m) => ({ default: m.CharactersPage })))
const TasksWorkspace = lazy(() => import('../unified/TasksWorkspace').then((m) => ({ default: m.TasksWorkspace })))
const StudioPage = lazy(() => import('../unified/StudioPage').then((m) => ({ default: m.StudioPage })))
const ModelsPage = lazy(() => import('../unified/ModelsPage').then((m) => ({ default: m.ModelsPage })))
const ComparePage = lazy(() => import('../unified/ComparePage').then((m) => ({ default: m.ComparePage })))
const ResearchPage = lazy(() => import('../unified/ResearchPage').then((m) => ({ default: m.ResearchPage })))
const DocumentsPage = lazy(() => import('../unified/DocumentsPage').then((m) => ({ default: m.DocumentsPage })))
const KnowledgePage = lazy(() => import('../unified/KnowledgePage').then((m) => ({ default: m.KnowledgePage })))
const IntegrationsPage = lazy(() => import('../unified/IntegrationsPage').then((m) => ({ default: m.IntegrationsPage })))
const CalendarPage = lazy(() => import('../unified/CalendarPage').then((m) => ({ default: m.CalendarPage })))
const PageFallback = () => <div className="jg-u-page"><SkeletonRows n={6} /></div>

export function AppWindow({ source }: { source: JaegerSource }) {
  const route = useRoute()
  const active = route.page as WindowId
  const { windows, visibleWindows, dockWindows, closeWindow } = useWindowManager(active)
  const store = useAgentsStore(source)
  const phone = usePhone()
  const [paletteOpen, setPaletteOpen] = useState(false)
  const go = useCallback((to: string) => navigate(to), [])

  useEffect(() => {
    document.title = `${WINDOW_DEFINITIONS[active].title} · Jaeger`
  }, [active])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setPaletteOpen((v) => !v) }
      else if ((e.metaKey || e.ctrlKey) && e.key === ',' && active !== 'chat') { e.preventDefault(); go('/settings') }
    }
    addEventListener('keydown', onKey)
    return () => removeEventListener('keydown', onKey)
  }, [go, active])

  const close = (id: WindowId) => {
    closeWindow(id)
    if (id === active) go('/')
  }

  const settingsTab: SettingsTab | undefined = isSettingsTab(route.rest) ? route.rest : undefined
  const paletteActions = useMemo<JumpAction[]>(() => [
    { id: 'new', label: 'New chat', shortcut: '⌘N', run: () => go('/chat') },
    ...PAGES.map((p) => ({ id: `page:${p}`, label: `Go to ${WINDOW_DEFINITIONS[p].title}`, hint: WINDOW_DEFINITIONS[p].description, shortcut: p === 'settings' ? '⌘,' : undefined, run: () => go(p === 'home' ? '/' : `/${p}`) })),
    { id: 'settings:agents', label: 'Manage agents', hint: 'Settings → Agents', run: () => go('/settings/agents') },
    { id: 'settings:general', label: 'Appearance and text size', hint: 'Settings → General', run: () => go('/settings/general') },
    ...CHARACTERS.map((c) => ({ id: `character:${c.id}`, label: `New agent: ${c.name}`, hint: c.role, run: () => go(`/characters?character=${encodeURIComponent(c.id)}`) })),
  ], [go])

  const render = (id: WindowId) => {
    switch (id) {
      case 'home': return <HomeDashboard source={source} store={store} onNavigate={go} />
      case 'agents': return <AgentsRoster source={source} store={store} refresh={store.refresh} onNavigate={go} />
      case 'characters': return <CharactersPage characterId={active === 'characters' ? route.params.get('character') : null} source={source} refresh={store.refresh} onNavigate={go} />
      case 'tasks': return route.rest === 'gallery'
        ? <div className="jg-u-page jg-u-page--flush">
            <nav className="jg-u-subnav" aria-label="Tasks views"><button type="button" onClick={() => go('/tasks')}>Board</button><button type="button" aria-current="page">Gallery</button></nav>
            <TasksPage source={source} />
          </div>
        : <TasksWorkspace source={source} agents={store.agents} params={route.params} onNavigate={go} />
      case 'machine': return <MachineControlPanel source={source} />
      case 'sharepoint': return <SharePointPanel source={source} />
      case 'workspace': return <WorkspacePage source={source} />
      case 'models': return <ModelsPage />
      case 'compare': return <ComparePage />
      case 'research': return <ResearchPage source={source} agents={store.agents} onNavigate={go} />
      case 'documents': return <DocumentsPage params={route.params} />
      case 'knowledge': return <KnowledgePage source={source} agents={store.agents} />
      case 'integrations': return <IntegrationsPage source={source} />
      case 'calendar': return <CalendarPage source={source} onNavigate={go} />
      case 'studio': return <StudioPage source={source} agents={store.agents} onNavigate={go} />
      default: return null
    }
  }

  // Chat and Settings share one App instance (its stores, streams, dialogs and settings panels).
  const appView = active === 'settings' ? 'settings' : 'chat'
  const chatOpen = windows.some((w) => w.id === 'chat')

  return (
    <ToastProvider>
    <div className={`app-window${phone ? ' app-window--phone' : ''}`} data-page={active}>
      <div className="app-window__content">
        {chatOpen && (
          <div className={`app-window__page app-window__page--chat${active === 'chat' || active === 'settings' ? ' app-window__page--active' : ''}`}
            hidden={active !== 'chat' && active !== 'settings'} aria-label={active === 'settings' ? 'Settings' : 'Chat'}>
            <Suspense fallback={<PageFallback />}><App source={source} view={appView} settingsTab={settingsTab} onSettingsTab={(t) => navigate(`/settings/${t}`, { replace: true })}
              onNavigate={go} requestedAgent={active === 'chat' ? route.params.get('agent') : null} onOpenPalette={() => setPaletteOpen(true)} /></Suspense>
          </div>
        )}
        {visibleWindows.filter((w) => w.id !== 'chat' && w.id !== 'settings').map((w) => (
          <div key={w.id} className={`app-window__page${w.id === active ? ' app-window__page--active' : ''}`} hidden={w.id !== active} aria-label={w.definition.title}>
            <Suspense fallback={<PageFallback />}>{render(w.id)}</Suspense>
          </div>
        ))}
      </div>

      <ApprovalTray source={source} onOpenChat={(agentId) => go(agentId ? `/chat?agent=${encodeURIComponent(agentId)}` : '/chat')} />

      <WindowDock
        windows={windows}
        activeWindowId={active}
        onFocusWindow={(id) => go(id === 'home' ? '/' : id === 'settings' && settingsTab ? `/settings/${settingsTab}` : `/${id}`)}
        onCloseWindow={close}
        availableWindows={dockWindows}
        phone={phone}
        onSearch={() => setPaletteOpen(true)}
      />

      <JumpTo open={paletteOpen} agents={store.agents.filter(visible)} summaries={store.summaries} seen={store.seen}
        onClose={() => setPaletteOpen(false)} onAgent={(id) => go(`/chat?agent=${encodeURIComponent(id)}`)} actions={paletteActions} />
    </div>
    </ToastProvider>
  )
}

export default AppWindow
