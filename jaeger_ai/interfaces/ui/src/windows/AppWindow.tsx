/**
 * AppWindow — Main multi-window app container (Grok-style)
 *
 * This is the new main window for Jaeger. It manages multiple app windows
 * (Chat, Settings, Library, etc.) with a macOS-style dock at the bottom.
 *
 * Each window is a self-contained page that can be opened, closed,
 * minimized, and switched between.
 */

import type { JaegerSource } from '../api/source'
import { useWindowManager, type WindowId } from './WindowManager'
import { WindowDock } from './WindowDock'
import { NavPage } from './NavPage'
import { TasksPage } from './TasksPage'
import { ChatPage } from './ChatPage'
import { HomePage } from './HomePage'
import { AboutPage } from './AboutPage'
import { FeaturesPage } from './FeaturesPage'
import { AgentsPage } from './AgentsPage'
import { MachineControlPanel } from '../machine-control/MachineControlPanel'
import { SharePointPanel } from '../sharepoint/SharePointPanel'
import './windows.css'
import './bots-page.css'


// ─────────────────────────────────────────────────────────────
// AppWindow — Main Component
// ─────────────────────────────────────────────────────────────

export function AppWindow({ source }: { source?: JaegerSource }) {
  const {
    windows,
    activeWindowId,
    visibleWindows,
    dockWindows,
    openWindow,
    closeWindow,
    focusWindow,
  } = useWindowManager()

  // Render the content for a specific window
  const renderWindowContent = (windowId: WindowId) => {
    switch (windowId) {
      case 'home':
        return (
          <HomePage
            source={source}
            onOpenWindow={(id) => openWindow(id as WindowId)}
            onStartChat={() => openWindow('chat')}
          />
        )
      case 'nav':
        return <NavPage source={source} onOpenWindow={(id) => openWindow(id as WindowId)} onStartChat={() => openWindow('chat')} />
      case 'chat':
        return <ChatPage source={source} onOpenWindow={(id) => openWindow(id as WindowId)} />
      case 'machine':
        return <MachineControlPanel source={source} />
      case 'sharepoint':
        return <SharePointPanel source={source} />
      case 'tasks':
        return <TasksPage source={source} />
      case 'agents':
        return (
          <AgentsPage
            onStartChat={() => {
              // Switch to chat
              openWindow('chat')
            }}
          />
        )
      case 'about':
        return <AboutPage />
      case 'features':
        return <FeaturesPage onOpenWindow={(id) => openWindow(id as WindowId)} />
      case 'library':
      case 'skills':
      case 'workflows':
      case 'tools':
        // Settings-hub panels: real windows, no dock tab. Each gets a page as
        // its content is built; until then an honest empty state.
        return (
          <div className="panel-page">
            <div className="jg-band wg-band" data-aether-window-drag-region>
              <span className="jg-traffic-lights" aria-hidden="true"><i /><i /><i /></span>
              <h1 className="wg-page__title">{windowId}</h1>
            </div>
            <p className="panel-page__note">
              This panel moved into Settings. Its content surface is being rebuilt —
              nothing is lost, it opens from Settings instead of the dock.
            </p>
          </div>
        )
      default:
        return null
    }
  }

  return (
    <div className="app-window">
      {/* Window Content Area */}
      <div className="app-window__content">
        {visibleWindows.map((window) => (
          <div
            key={window.id}
            className={`app-window__page${window.id === activeWindowId ? ' app-window__page--active' : ''}`}
            style={{ zIndex: window.id === activeWindowId ? 10 : 1 }}
            /* Refocus only when the page is backgrounded: on the active page
               this handler would fire after every inner action (a Settings row
               opening a panel) and steal focus right back. */
            onClick={(e) => {
              if (window.id !== activeWindowId) focusWindow(window.id)
              else e.stopPropagation()
            }}
          >
            {renderWindowContent(window.id)}
          </div>
        ))}
      </div>

      {/* Window Dock — operator tabs only; panels open from Settings */}
      <WindowDock
        windows={windows}
        activeWindowId={activeWindowId}
        onFocusWindow={focusWindow}
        onCloseWindow={closeWindow}
        onOpenWindow={openWindow}
        availableWindows={dockWindows}
      />
    </div>
  )
}

export default AppWindow
