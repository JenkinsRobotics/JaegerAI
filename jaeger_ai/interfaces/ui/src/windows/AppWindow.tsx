/**
 * AppWindow — the one Jaeger shell (unified UI, Jenkins Robotics 2026-10-30).
 *
 * AppChrome (sidebar + app bar, per layout preset) is the frame; every feature is a page at a real route
 * Nine tabs: Home, Chat, Agents, Work, Research, Studio, Models, Machine, Settings. Merged tabs
 * carry sub-tabs at /<tab>/<sub> (e.g. /work/calendar); retired paths (/tasks, /compare …) redirect.
 * Open pages stay mounted (chat streams, drafts and approvals keep running while you look
 * elsewhere); the URL decides which one is in front. ⌘K opens the one command palette,
 * ⌘, opens Settings, and pending approvals are reachable from every page. On a phone or
 * narrow window the chrome becomes a compact top bar plus a bottom tab bar.
 */
import type React from 'react'
import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from 'react'
import type { JaegerSource } from '../api/source'
import { useWindowManager, WINDOW_DEFINITIONS, type WindowId } from './WindowManager'
import { AppChrome } from '../shell/AppChrome'
import { useAgentsStore } from '../agents/agentsStore'
import { visible } from '../agents/agentsLogic'
import { JumpTo, type JumpAction } from '../agents/JumpTo'
import { CHARACTERS } from '../components/CharacterLibrary'
import { usePhone } from '../phone/usePhone'
import { navigate, useRoute, PAGES, SUBTABS, pathOf, type PageId } from '../shell/router'
import { parseSettingsRest, type Tab as SettingsTab } from '../settings/SettingsDialog'
import { HomeDashboard } from '../unified/HomeDashboard'
import { ApprovalTray } from '../unified/ApprovalTray'
import './windows.css'
import '../unified/unified.css'
import '../unified/design.css'
import { ToastProvider, SkeletonRows, TabbedPage } from '../unified/ui'

// Route-level code splitting: every page but Home loads on first open.
const App = lazy(() => import('../App').then((m) => ({ default: m.App })))
const TasksPage = lazy(() => import('./TasksPage').then((m) => ({ default: m.TasksPage })))
const WorkspacePage = lazy(() => import('./WorkspacePage').then((m) => ({ default: m.WorkspacePage })))
const CheckpointsView = lazy(() => import('../unified/CheckpointsView').then((m) => ({ default: m.CheckpointsView })))
const WorkspaceBrowser = lazy(() => import('../unified/WorkspaceBrowser').then((m) => ({ default: m.WorkspaceBrowser })))
const MachineControlPanel = lazy(() => import('../machine-control/MachineControlPanel').then((m) => ({ default: m.MachineControlPanel })))
const SharePointPanel = lazy(() => import('../sharepoint/SharePointPanel').then((m) => ({ default: m.SharePointPanel })))
const EnginePanel = lazy(() => import('../unified/EnginePanel').then((m) => ({ default: m.EnginePanel })))
const AgentsRoster = lazy(() => import('../unified/AgentsRoster').then((m) => ({ default: m.AgentsRoster })))
const AgentsActivityPage = lazy(() => import('../orchestration/AgentsActivityPage').then((m) => ({ default: m.AgentsActivityPage })))
const CharactersPage = lazy(() => import('../unified/CharactersPage').then((m) => ({ default: m.CharactersPage })))
const TasksWorkspace = lazy(() => import('../unified/TasksWorkspace').then((m) => ({ default: m.TasksWorkspace })))
const StudioPage = lazy(() => import('../unified/StudioPage').then((m) => ({ default: m.StudioPage })))
const ModelsPage = lazy(() => import('../unified/ModelsPage').then((m) => ({ default: m.ModelsPage })))
const ComparePage = lazy(() => import('../unified/ComparePage').then((m) => ({ default: m.ComparePage })))
const ResearchPage = lazy(() => import('../unified/ResearchPage').then((m) => ({ default: m.ResearchPage })))
const YouTubePage = lazy(() => import('../research/YouTubePage').then((m) => ({ default: m.YouTubePage })))
const UsagePage = lazy(() => import('../unified/UsagePage').then((m) => ({ default: m.UsagePage })))
const DocumentsPage = lazy(() => import('../unified/DocumentsPage').then((m) => ({ default: m.DocumentsPage })))
const KnowledgePage = lazy(() => import('../unified/KnowledgePage').then((m) => ({ default: m.KnowledgePage })))
const BacklogPage = lazy(() => import('../unified/BacklogPage').then((m) => ({ default: m.BacklogPage })))
const CalendarPage = lazy(() => import('../unified/CalendarPage').then((m) => ({ default: m.CalendarPage })))
const PipelinePage = lazy(() => import('../unified/PipelinePage').then((m) => ({ default: m.PipelinePage })))
const ProductionPage = lazy(() => import('../unified/PipelinePage').then((m) => ({ default: m.ProductionPage })))
const TaskBanner = lazy(() => import('../unified/PipelinePage').then((m) => ({ default: m.TaskBanner })))
const PageFallback = () => <div className="jg-u-page"><SkeletonRows n={6} /></div>

export function AppWindow({ source }: { source: JaegerSource }) {
  const route = useRoute()
  const active = route.page as WindowId
  const { windows, visibleWindows, dockWindows } = useWindowManager(active)
  const store = useAgentsStore(source)
  const phone = usePhone()
  const [paletteOpen, setPaletteOpen] = useState(false)
  const go = useCallback((to: string) => navigate(to), [])

  useEffect(() => {
    const sub = SUBTABS[active]?.find((t) => t.id === route.sub)
    document.title = `${sub && sub.id !== SUBTABS[active]![0].id ? `${sub.title} · ` : ''}${WINDOW_DEFINITIONS[active].title} · Jaeger`
  }, [active, route.sub])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setPaletteOpen((v) => !v) }
      else if ((e.metaKey || e.ctrlKey) && e.key === ',' && active !== 'chat') { e.preventDefault(); go('/settings') }
    }
    const onPalette = () => setPaletteOpen(true)
    addEventListener('keydown', onKey)
    addEventListener('jaeger:palette', onPalette)
    return () => { removeEventListener('keydown', onKey); removeEventListener('jaeger:palette', onPalette) }
  }, [go, active])

  // Each merged tab remembers the sub-tab you were last on (nav click returns there).
  const [lastSub, setLastSub] = useState<Partial<Record<PageId, string>>>({})
  useEffect(() => { if (SUBTABS[active]) setLastSub((m) => (m[active] === route.sub ? m : { ...m, [active]: route.sub })) }, [active, route.sub])

  const { tab: settingsTab, segment: settingsSegment } = parseSettingsRest(route.rest) as { tab?: SettingsTab; segment?: string }
  const paletteActions = useMemo<JumpAction[]>(() => [
    { id: 'new', label: 'New chat', shortcut: '⌘N', run: () => go('/chat') },
    ...PAGES.map((p) => ({ id: `page:${p}`, label: `Go to ${WINDOW_DEFINITIONS[p].title}`, hint: WINDOW_DEFINITIONS[p].description, shortcut: p === 'settings' ? '⌘,' : undefined, run: () => go(pathOf(p)) })),
    ...PAGES.flatMap((p) => (SUBTABS[p] ?? []).slice(1).map((t) => ({ id: `sub:${p}:${t.id}`, label: `Go to ${t.title}`, hint: `${WINDOW_DEFINITIONS[p].title} › ${t.title}`, run: () => go(pathOf(p, t.id)) }))),
    { id: 'backlog:needs-ok', label: 'Backlog: needs my OK', hint: 'Work › Backlog', run: () => go('/work/backlog?status=needs_ok') },
    { id: 'settings:integrations', label: 'Integrations', hint: 'Settings → Integrations', run: () => go('/settings/integrations') },
    { id: 'settings:agents', label: 'Manage agents', hint: 'Settings → Agents', run: () => go('/settings/agents') },
    { id: 'settings:general', label: 'Appearance and text size', hint: 'Settings → General', run: () => go('/settings/general') },
    ...CHARACTERS.map((c) => ({ id: `character:${c.id}`, label: `New agent: ${c.name}`, hint: c.role, run: () => go(`/agents/characters?character=${encodeURIComponent(c.id)}`) })),
  ], [go])

  // Sub-tab of a merged page: the route's sub when that page is in front, else its default.
  const subOf = (p: PageId) => (active === p ? route.sub : SUBTABS[p]![0].id)
  const paramsOf = (p: PageId) => (active === p ? route.params : new URLSearchParams())
  const tabbed = (p: PageId, body: (sub: string) => React.ReactNode, banner?: React.ReactNode) => (
    <TabbedPage label={`${WINDOW_DEFINITIONS[p].title} sections`} tabs={SUBTABS[p]!} active={subOf(p)}
      onPick={(t) => go(pathOf(p, t))} render={(t) => <Suspense fallback={<PageFallback />}>{body(t)}</Suspense>} banner={banner} />
  )
  const taskFor = (p: PageId, sub?: string) => (active === p && (!sub || route.sub === sub) ? route.params.get('task') : null)
  const banner = (p: PageId, stage: 'research' | 'studio' | 'production', sub?: string) => {
    const t = taskFor(p, sub)
    return t ? <Suspense fallback={null}><TaskBanner source={source} taskId={t} stage={stage} onNavigate={go} clearTo={pathOf(p, sub)} /></Suspense> : undefined
  }

  const render = (id: WindowId) => {
    switch (id) {
      case 'home': return tabbed('home', (t) => t === 'widgets' ? <WorkspacePage source={source} /> : <HomeDashboard source={source} store={store} onNavigate={go} />)
      case 'agents': return tabbed('agents', (t) => t === 'hermes' || t === 'openclaw' ? <EnginePanel engine={t} />
        : t === 'characters'
        ? <CharactersPage characterId={active === 'agents' && route.sub === 'characters' ? route.params.get('character') : null} source={source} refresh={store.refresh} onNavigate={go} />
        : active === 'agents' && route.rest === 'activity' ? <AgentsActivityPage source={source} onNavigate={go} />
        : <AgentsRoster source={source} store={store} refresh={store.refresh} onNavigate={go} avatarFor={active === 'agents' ? (/^(.+)\/avatar$/.exec(route.rest)?.[1] ?? null) : null} />)
      case 'work': return tabbed('work', (t) => {
        switch (t) {
          case 'tasks': return active === 'work' && route.sub === 'tasks' && route.rest === 'gallery'
            ? <div className="jg-u-page jg-u-page--flush">
                <nav className="jg-u-subnav" aria-label="Tasks views"><button type="button" onClick={() => go('/work/tasks')}>Board</button><button type="button" aria-current="page">Gallery</button></nav>
                <TasksPage source={source} />
              </div>
            : <TasksWorkspace source={source} agents={store.agents} params={paramsOf('work')} onNavigate={go} />
          case 'production': return <ProductionPage source={source} params={active === 'work' && route.sub === 'production' ? route.params : new URLSearchParams()} onNavigate={go} />
          case 'calendar': return <CalendarPage source={source} onNavigate={go} />
          case 'backlog': return <BacklogPage params={paramsOf('work')} />
          case 'checkpoints': return <CheckpointsView source={source} params={paramsOf('work')} />
          case 'workspace': return <WorkspaceBrowser source={source} params={paramsOf('work')} />
          default: return <PipelinePage source={source} params={active === 'work' && route.sub === 'pipeline' ? route.params : new URLSearchParams()} onNavigate={go} />
        }
      }, banner('work', 'production', 'production'))
      case 'research': return tabbed('research', (t) => {
        switch (t) {
          case 'documents': return <DocumentsPage params={active === 'research' && route.sub === 'documents' ? route.params : new URLSearchParams()} />
          case 'youtube': return <YouTubePage params={active === 'research' && route.sub === 'youtube' ? route.params : new URLSearchParams()} onNavigate={go} />
          case 'knowledge': return <KnowledgePage source={source} agents={store.agents} />
          case 'sharepoint': return <SharePointPanel source={source} />
          default: return <ResearchPage source={source} agents={store.agents} onNavigate={go} />
        }
      }, (() => { const t = taskFor('research'); return t ? <Suspense fallback={null}><TaskBanner source={source} taskId={t} stage="research" onNavigate={go} clearTo={pathOf('research', route.sub)} /></Suspense> : undefined })())
      case 'models': return tabbed('models', (t) => t === 'compare' ? <ComparePage /> : t === 'usage' ? <UsagePage /> : <ModelsPage />)
      case 'machine': return <MachineControlPanel source={source} />
      case 'studio': return <div className="jg-tabbed">{banner('studio', 'studio')}<div className="jg-tabbed__body"><StudioPage source={source} agents={store.agents} onNavigate={go} /></div></div>
      default: return null
    }
  }

  // Chat and Settings share one App instance (its stores, streams, dialogs and settings panels).
  const appView = active === 'settings' ? 'settings' : 'chat'
  const chatOpen = windows.some((w) => w.id === 'chat')

  return (
    <ToastProvider>
    <div className={`app-window${phone ? ' app-window--phone' : ''}`} data-page={active}>
      <AppChrome active={active} sub={route.sub} pages={dockWindows} phone={phone} onSearch={() => setPaletteOpen(true)}
        trail={<ApprovalTray source={source} onOpenChat={(agentId) => go(agentId ? `/chat?agent=${encodeURIComponent(agentId)}` : '/chat')} />}
        onPick={(id) => go(id === 'settings' && settingsTab ? `/settings/${settingsTab}` : id === active ? pathOf(id) : pathOf(id, lastSub[id]))}>
      <div className="app-window__content">
        {chatOpen && (
          <div className={`app-window__page app-window__page--chat${active === 'chat' || active === 'settings' ? ' app-window__page--active' : ''}`}
            hidden={active !== 'chat' && active !== 'settings'} aria-label={active === 'settings' ? 'Settings' : 'Chat'}>
            <Suspense fallback={<PageFallback />}><App source={source} view={appView} settingsTab={settingsTab} settingsSegment={settingsSegment} onSettingsTab={(t) => navigate(t ? `/settings/${t}` : '/settings', { replace: !!t && !!settingsTab })}
              onNavigate={go} requestedAgent={active === 'chat' ? route.params.get('agent') : null} onOpenPalette={() => setPaletteOpen(true)} /></Suspense>
          </div>
        )}
        {visibleWindows.filter((w) => w.id !== 'chat' && w.id !== 'settings').map((w) => (
          <div key={w.id} className={`app-window__page${w.id === active ? ' app-window__page--active' : ''}`} hidden={w.id !== active} aria-label={w.definition.title}>
            <Suspense fallback={<PageFallback />}>{render(w.id)}</Suspense>
          </div>
        ))}
      </div>
      </AppChrome>

      <JumpTo open={paletteOpen} agents={store.agents.filter(visible)} summaries={store.summaries} seen={store.seen}
        onClose={() => setPaletteOpen(false)} onAgent={(id) => go(`/chat?agent=${encodeURIComponent(id)}`)} actions={paletteActions} />
    </div>
    </ToastProvider>
  )
}

export default AppWindow
