/**
 * WindowDock — macOS-style dock for window navigation
 *
 * Shows all open windows as icons in a dock at the bottom of the screen.
 * Features horizontal scrolling with arrow buttons when many windows are open.
 * Responsive sizing - icons shrink on smaller screens.
 */

import { useRef, useEffect, useState, useCallback } from 'react'
import { WINDOW_DEFINITIONS as windowDefinitions, type WindowInstance, type WindowId } from './WindowManager'
import { X, ChevronLeft, ChevronRight } from '../components/Icons'

interface WindowDockProps {
  windows: WindowInstance[]
  activeWindowId: WindowId
  onFocusWindow: (id: WindowId) => void
  onCloseWindow: (id: WindowId) => void
  /** Kept for API compatibility; every tab is listed inline now. */
  onOpenWindow?: (id: WindowId) => void
  /** Every tab the app ships. All of them are shown; unopened ones open on click. */
  availableWindows?: WindowId[]
}

export function WindowDock({
  windows,
  activeWindowId,
  onFocusWindow,
  onCloseWindow,
  availableWindows = [],
}: WindowDockProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [hasOverflow, setHasOverflow] = useState(false)
  const [canScrollLeft, setCanScrollLeft] = useState(false)
  const [canScrollRight, setCanScrollRight] = useState(false)

  // Check for overflow and scroll state.
  const checkOverflow = useCallback(() => {
    const el = scrollRef.current
    if (!el) return

    let contentWidth = 0
    for (const child of Array.from(el.children)) {
      const style = getComputedStyle(child as HTMLElement)
      if (style.position === 'absolute' || style.position === 'fixed') continue
      contentWidth = Math.max(contentWidth, (child as HTMLElement).offsetLeft + (child as HTMLElement).offsetWidth)
    }

    const hasOv = contentWidth > el.clientWidth + 10
    setHasOverflow(hasOv)
    setCanScrollLeft(el.scrollLeft > 5)
    setCanScrollRight(el.scrollLeft + el.clientWidth < contentWidth - 5)
  }, [])

  // Check overflow on mount and when windows change
  useEffect(() => {
    checkOverflow()
    // Also check after layout settles
    const timer = setTimeout(checkOverflow, 100)
    const timer2 = setTimeout(checkOverflow, 500)
    return () => {
      clearTimeout(timer)
      clearTimeout(timer2)
    }
  }, [windows, checkOverflow])

  // Scroll to keep active item visible
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return

    const activeItem = el.querySelector('.window-dock__item--active') as HTMLElement
    if (activeItem) {
      const itemLeft = activeItem.offsetLeft
      const itemRight = itemLeft + activeItem.offsetWidth
      const scrollLeft = el.scrollLeft
      const clientWidth = el.clientWidth

      // Scroll if active item is not fully visible
      if (itemLeft < scrollLeft) {
        el.scrollTo({ left: itemLeft - 20, behavior: 'smooth' })
      } else if (itemRight > scrollLeft + clientWidth) {
        el.scrollTo({ left: itemRight - clientWidth + 20, behavior: 'smooth' })
      }
    }
  }, [activeWindowId, windows])

  // Scroll handlers
  const scrollLeft = () => {
    const el = scrollRef.current
    if (el) {
      el.scrollBy({ left: -150, behavior: 'smooth' })
      setTimeout(checkOverflow, 350)
    }
  }

  const scrollRight = () => {
    const el = scrollRef.current
    if (el) {
      el.scrollBy({ left: 150, behavior: 'smooth' })
      setTimeout(checkOverflow, 350)
    }
  }

  // Update scroll buttons on scroll
  const handleScroll = () => {
    checkOverflow()
  }

  // Window resize handler
  useEffect(() => {
    const handleResize = () => checkOverflow()
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [checkOverflow])

  return (
    <div className={`window-dock${hasOverflow ? ' has-overflow' : ''}`} role="toolbar" aria-label="App windows">
      {/* Left scroll button */}
      {canScrollLeft && (
        <button
          className="window-dock__scroll-left"
          onClick={scrollLeft}
          aria-label="Scroll dock left"
          type="button"
        >
          <ChevronLeft />
        </button>
      )}

      {/* Scrollable items container */}
      <div
        className="window-dock__items"
        ref={scrollRef}
        onScroll={handleScroll}
      >
        {availableWindows.map((id) => {
          const def = windowDefinitions[id]
          const open = windows.find((w) => w.id === id)
          const Icon = def.icon
          const isActive = id === activeWindowId && !!open && !open.minimized
          const isMinimized = !!open?.minimized

          return (
            <div
              key={id}
              className={`window-dock__item${isActive ? ' window-dock__item--active' : ''}${isMinimized ? ' window-dock__item--minimized' : ''}${!open ? ' window-dock__item--closed' : ''}`}
              onClick={() => onFocusWindow(id)}
              title={def.description}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  onFocusWindow(id)
                }
              }}
            >
              <div className="window-dock__icon">
                <Icon size={20} />
              </div>
              <span className="window-dock__label">{def.title}</span>
              {isMinimized && <span className="window-dock__minimized-dot" />}
              {open && def.closable && (
                <button
                  className="window-dock__close"
                  onClick={(e) => {
                    e.stopPropagation()
                    onCloseWindow(id)
                  }}
                  aria-label={`Close ${def.title}`}
                  title={`Close ${def.title}`}
                  type="button"
                >
                  <X size={10} />
                </button>
              )}
            </div>
          )
        })}
      </div>

      {/* Right scroll button */}
      {canScrollRight && (
        <button
          className="window-dock__scroll-right"
          onClick={scrollRight}
          aria-label="Scroll dock right"
          type="button"
        >
          <ChevronRight />
        </button>
      )}
    </div>
  )
}

export default WindowDock
