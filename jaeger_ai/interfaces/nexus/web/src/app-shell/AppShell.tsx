// NexusUI app shell for React apps: the standard container and navigation bar (app-shell.css says where it comes from).
// Copy this folder into the app (AppShell.tsx, app-shell.css, icons.js); the app owns its copy. app-shell.js is the
// same shell for apps without React.
//
//   <AppShell id="jaeger-ai" brand={{ name: 'Jaeger', suffix: 'AI', mark: '/mark.svg' }}
//     sections={[{ id: 'workspace', title: 'Workspace', items: [{ id: 'chat', label: 'Chat', icon: 'comment' }] }]}
//     current={page} onSelect={setPage} settings={{ id: 'settings', label: 'Settings', icon: 'settings' }}
//     profile={{ name: 'Jaeger', detail: 'Gateway · qwen3', connection: 'connected' }}
//     status={{ name: 'Jaeger AI', connection: 'connected', message: '', company: 'Jenkins Robotics' }}>
//     {the app's page, unchanged}
//   </AppShell>
import { useState, type ReactNode } from 'react';
import { ICONS } from './icons.js';
import './app-shell.css';

export type Connection = 'connected' | 'offline' | 'local' | 'waiting';
export type ShellItem = { id: string; label: string; icon: string | ReactNode; badge?: number | string; href?: string; disabled?: boolean; pressed?: boolean; onSelect?: () => void };
export type ShellSection = { id: string; title?: string; items: ShellItem[] };
export type Brand = { name: string; suffix?: string; mark?: string | ReactNode };
export type Profile = { name: string; detail?: string; avatar?: string | ReactNode; connection?: Connection };
export type Status = { name: string; connection?: Connection; message?: string; company?: string };

const remembered = (key: string, fallback: boolean) => { try { const v = localStorage.getItem(key); return v ? v === '1' : fallback; } catch { return fallback; } };
const remember = (key: string, on: boolean) => { try { localStorage.setItem(key, on ? '1' : '0'); } catch { /* a device preference only */ } };

export function Icon({ name }: { name: string | ReactNode }) {
  if (typeof name !== 'string') return <span className="nx-icon" aria-hidden="true">{name}</span>;
  return <span className="nx-icon" aria-hidden="true" dangerouslySetInnerHTML={{ __html: (ICONS as Record<string, string>)[name] ?? '' }} />;   // repository-owned SVG, never user data
}

export function Row({ item, current, onSelect }: { item: ShellItem; current?: boolean; onSelect?: (id: string) => void }) {
  const go = () => { item.onSelect ? item.onSelect() : onSelect?.(item.id); };
  const body = <><Icon name={item.icon} /><span className="nx-label">{item.label}</span>{item.badge !== undefined ? <span className="nx-badge">{item.badge}</span> : null}</>;
  const shared = { className: 'nx-row', title: item.label, 'aria-label': item.label, 'aria-current': current ? 'page' as const : undefined };
  return item.href && !item.disabled
    ? <a {...shared} href={item.href} target="_blank" rel="noreferrer">{body}</a>
    : <button {...shared} type="button" disabled={item.disabled} aria-pressed={item.pressed} onClick={go}>{body}</button>;
}

function Section({ id, section, current, onSelect }: { id: string; section: ShellSection; current?: string; onSelect?: (id: string) => void }) {
  const key = `nx-shell-${id}-${section.id}`;
  const [open, setOpen] = useState(() => remembered(key, true));
  const toggle = () => { setOpen(!open); remember(key, !open); };
  return (
    <nav className="nx-section" aria-label={section.title ?? 'Navigation'}>
      {section.title ? <button type="button" className="nx-caption" aria-expanded={open} aria-label={`${open ? 'Hide' : 'Show'} ${section.title}`} onClick={toggle}>
        <span>{section.title}</span><Icon name={open ? 'chevron-down' : 'chevron-right'} /></button> : null}
      <div className="nx-section-items" hidden={!open}>{section.items.map(it => <Row key={it.id} item={it} current={it.id === current} onSelect={onSelect} />)}</div>
    </nav>
  );
}

export function AppShell({ id, brand, sections, current, onSelect, tools, settings, apps, profile, status, children }: {
  /** Stable key: the rail and each section's open state are remembered per app on this device. */
  id: string;
  brand: Brand;
  sections: ShellSection[];
  current?: string;
  onSelect?: (id: string) => void;
  /** Rows above Settings (Aether Studio: Administration, Sign out). */
  tools?: ShellItem[];
  settings?: ShellItem;
  apps?: ShellItem;
  profile?: Profile;
  status?: Status;
  children: ReactNode;
}) {
  const [rail, setRail] = useState(() => remembered(`nx-shell-${id}-rail`, false));
  const toggle = () => { setRail(!rail); remember(`nx-shell-${id}-rail`, !rail); };
  const mark = typeof brand.mark === 'string' ? <img src={brand.mark} alt="" /> : brand.mark;
  const avatar = typeof profile?.avatar === 'string' ? <img src={profile.avatar} alt="" /> : profile?.avatar ?? profile?.name.slice(0, 1);
  return (
    <div className="nx-app">
      <aside className={`nx-sidebar${rail ? ' nx-collapsed' : ''}`} aria-label={`${brand.name}${brand.suffix ? ` ${brand.suffix}` : ''} sidebar`}>
        <button type="button" className="nx-brand" aria-expanded={!rail} title={rail ? 'Expand sidebar' : 'Collapse sidebar'} onClick={toggle}>
          {mark ? <span className="nx-mark" aria-hidden="true">{mark}</span> : null}
          <span className="nx-wordmark"><b>{brand.name}</b>{brand.suffix ? <i>{brand.suffix}</i> : null}</span>
        </button>
        <div className="nx-sidebar-body">
          <div className="nx-sections">{sections.map(s => <Section key={s.id} id={id} section={s} current={current} onSelect={onSelect} />)}</div>
        </div>
        <div className="nx-sidebar-footer">
          {tools?.length ? <div className="nx-tools">{tools.map(t => <Row key={t.id} item={t} current={t.id === current} onSelect={onSelect} />)}</div> : null}
          {settings || apps ? <div className="nx-settings">
            {settings ? <Row item={settings} current={settings.id === current} onSelect={onSelect} /> : null}
            {apps ? <Row item={apps} current={apps.id === current} onSelect={onSelect} /> : null}
          </div> : null}
          {profile ? <div className="nx-profile" title={`${profile.name}${profile.detail ? ` · ${profile.detail}` : ''}`}>
            <span className="nx-avatar" aria-hidden="true">{avatar}</span>
            <span className="nx-profile-text"><b>{profile.name}</b>{profile.detail ? <span>{profile.connection ? <i className="nx-dot" data-connection={profile.connection} /> : null}{profile.detail}</span> : null}</span>
          </div> : null}
        </div>
      </aside>
      <main className="nx-main">{children}</main>
      {status ? <footer className="nx-status" role="status">
        <i className="nx-dot" data-connection={status.connection ?? 'local'} /><span className="nx-status-name">{status.name}</span>
        <span className="nx-status-message">{status.message ?? ''}</span>
        {status.company ? <span className="nx-status-company">{status.company}</span> : null}
      </footer> : null}
    </div>
  );
}
