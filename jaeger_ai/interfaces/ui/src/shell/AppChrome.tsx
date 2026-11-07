/**
 * AppChrome (Jenkins Robotics, 2026-10-31, original). The app bar and navigation for every preset;
 * replaces the old bottom dock. Mac/tablet: sidebar (Settings pinned at the bottom) plus, except for
 * Arc, a 52px top bar with traffic-light space, sidebar toggle, breadcrumb and the ⌘K command field.
 * Phone: a compact top bar (title, search) and a bottom tab bar (Home, Chat, Agents, Work + More).
 */
import type React from 'react'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { WINDOW_DEFINITIONS, type WindowId } from '../windows/WindowManager'
import { Check, Users, Globe, Menu, MessageSquare, Search, Sparkles } from '../components/Icons'
import { SUBTABS, navigate } from './router'
import { usePreset, type Preset } from './layoutPresets'
import { JaegerMark } from '../brand/JaegerMark'
import './appchrome.css'


export interface ChromeProps {
  active: WindowId
  sub?: string
  pages: WindowId[]
  phone: boolean
  onPick: (id: WindowId) => void
  onSearch: () => void
  /** Top-bar status slot (approvals badge, J-087). */
  trail?: React.ReactNode
}

const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent)
const KEY = isMac ? '⌘K' : 'Ctrl K'

function CommandField({ preset, onSearch, compact }: { preset: Preset; onSearch: () => void; compact?: boolean }) {
  const ask = preset.layout.command === 'ask'
  const label = ask ? 'Search or ask Jaeger…' : 'Search, jump or ask Jaeger…'
  return (
    <button type="button" className={`jg-cmd jg-cmd--${preset.layout.command}${compact ? ' jg-cmd--compact' : ''}`} onClick={onSearch} aria-label={`${label} (${KEY})`} aria-keyshortcuts="Meta+K">
      {ask ? <Sparkles size={15} /> : <Search size={15} />}
      <span className="jg-cmd__label">{label}</span>
      <kbd className="jg-cmd__kbd">{KEY}</kbd>
    </button>
  )
}

function NavItem({ id, active, collapsed, onPick }: { id: WindowId; active: boolean; collapsed: boolean; onPick: (id: WindowId) => void }) {
  const def = WINDOW_DEFINITIONS[id]
  const Icon = def.icon
  return (
    <button type="button" className={`jg-nav__item${active ? ' is-active' : ''}`} aria-current={active ? 'page' : undefined}
      aria-label={id === 'settings' ? 'Settings' : undefined} title={collapsed ? def.title : def.description} onClick={() => onPick(id)}>
      <Icon size={18} /><span className="jg-nav__label">{def.title}</span>
    </button>
  )
}

const PHONE_BAR: readonly { id: string; label: string; page: WindowId; to: string; Icon: typeof MessageSquare }[] = [
  { id: 'chat', label: 'Chat', page: 'chat', to: '/', Icon: MessageSquare },
  { id: 'feed', label: 'Feed', page: 'chat', to: '/?feed=1', Icon: Globe },
  { id: 'ideas', label: 'Ideas', page: 'research', to: '/research', Icon: Sparkles },
  { id: 'tasks', label: 'Work', page: 'work', to: '/work/tasks', Icon: Check },
  { id: 'agents', label: 'Agents', page: 'agents', to: '/agents', Icon: Users },
]

function PhoneTabs({ active }: Pick<ChromeProps, 'active'>) {
  return (
    <nav className="phone-tabs" aria-label="Pages">
      {PHONE_BAR.map((t) => {
        const feed = new URLSearchParams(location.search).has('feed')
        const on = t.page === active && (t.id === 'feed' ? feed : t.id === 'chat' ? !feed : true)
        return (
          <button key={t.id} type="button" className={`phone-tabs__tab${on ? ' is-active' : ''}`} aria-current={on ? 'page' : undefined} onClick={() => navigate(t.to)}>
            <t.Icon size={22} /><span>{t.label}</span>
          </button>
        )
      })}
    </nav>
  )
}

/** The leading/top chrome. Rendered by AppWindow around its page stack. */
export function AppChrome({ active, sub, pages, phone, onPick, onSearch, trail, children }: ChromeProps & { children: React.ReactNode }) {
  const preset = usePreset()
  const phoneChrome = useRef<HTMLDivElement>(null)
  useLayoutEffect(() => {
    const root = phoneChrome.current, tabs = root?.querySelector<HTMLElement>('.phone-tabs')
    if (!root || !tabs) return
    const measure = () => root.style.setProperty('--jg-phone-tabs-h', `${Math.ceil(tabs.getBoundingClientRect().height)}px`)
    measure()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(measure)
    observer.observe(tabs)
    return () => observer.disconnect()
  }, [phone])
  const [collapsed, setCollapsed] = useState(false)
  const title = WINDOW_DEFINITIONS[active].title
  const subTitle = SUBTABS[active]?.find((t) => t.id === sub && t.id !== SUBTABS[active]![0].id)?.title
  const topbar = preset.layout.nav !== 'sidebar'
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.metaKey && e.ctrlKey && e.key.toLowerCase() === 's') { e.preventDefault(); setCollapsed((v) => !v) } }
    addEventListener('keydown', onKey)
    return () => removeEventListener('keydown', onKey)
  }, [])

  if (phone) {
    return (
      <div ref={phoneChrome} className="jg-chrome jg-chrome--phone" data-preset={preset.id}>
        {active !== 'chat' && (
          <header className="jg-topbar jg-topbar--compact">
            <JaegerMark className="jg-topbar__logo" />
            <h1 className="jg-topbar__title">{title}</h1>
            {trail}
            <button type="button" className="jg-iconbtn" onClick={onSearch} aria-label={`Search or ask (${KEY})`}><Search size={18} /></button>
          </header>
        )}
        <main className="jg-chrome__main">{children}</main>
        <PhoneTabs active={active} />
      </div>
    )
  }

  const main = pages.filter((id) => id !== 'settings')
  return (
    <div className={`jg-chrome${collapsed ? ' is-collapsed' : ''}`} data-preset={preset.id}>
      <nav className="jg-sidebar" aria-label="Pages">
        <div className="jg-sidebar__head">
          <span className="jg-traffic" aria-hidden="true" />
          {!topbar && trail}
          {!topbar && <button type="button" className="jg-iconbtn" onClick={() => setCollapsed((v) => !v)} aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'} aria-keyshortcuts="Control+Meta+S"><Menu size={16} /></button>}
        </div>
        {preset.layout.command === 'sidebar' && <CommandField preset={preset} onSearch={onSearch} compact={collapsed} />}
        <div className="jg-nav">
          {main.map((id) => <NavItem key={id} id={id} active={id === active} collapsed={collapsed} onPick={onPick} />)}
        </div>
        {pages.includes('settings') && <div className="jg-nav jg-nav--foot"><NavItem id="settings" active={active === 'settings'} collapsed={collapsed} onPick={onPick} /></div>}
      </nav>
      <div className="jg-chrome__body">
        {topbar && (
          <header className="jg-topbar" role="toolbar" aria-label="App bar">
            <div className="jg-topbar__lead jg-capsule">
              <button type="button" className="jg-iconbtn" onClick={() => setCollapsed((v) => !v)} aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'} aria-keyshortcuts="Control+Meta+S"><Menu size={16} /></button>
              <span className="jg-crumb"><b>{title}</b>{subTitle && <span className="jg-crumb__sub"> / {subTitle}</span>}</span>
            </div>
            <div className="jg-topbar__center"><CommandField preset={preset} onSearch={onSearch} /></div>
            <div className="jg-topbar__trail">{trail}</div>
          </header>
        )}
        <main className="jg-chrome__main">{children}</main>
      </div>
    </div>
  )
}
