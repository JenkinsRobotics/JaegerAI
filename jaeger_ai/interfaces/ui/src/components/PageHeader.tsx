/** One header per view (TAB-01 §3): h1 + subtitle + actions. `embedded` drops the h1 (a dialog already titles it); `back` adds an in-app back bar (standalone PWA has no Safari back). */
import type { ReactNode } from "react";

export function PageHeader({ title, subtitle, actions, embedded, back, children, id }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; embedded?: boolean; back?: { label: string; onBack: () => void }; children?: ReactNode; id?: string }) {
  return (
    <header className="jg-u-page__head jg-page-header" data-embedded={embedded || undefined}>
      {back && <button type="button" className="jg-page-header__back" onClick={back.onBack}>‹ {back.label}</button>}
      <div className="jg-u-page__title">{embedded ? null : <h1 id={id}>{title}</h1>}{subtitle != null && subtitle !== false && <p>{subtitle}</p>}</div>
      {actions && <div className="jg-ui-toolbar">{actions}</div>}
      {children}
    </header>
  );
}
