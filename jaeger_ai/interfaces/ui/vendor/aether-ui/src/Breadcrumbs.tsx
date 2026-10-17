import { MenuButton, type MenuItem } from "./Menu";

export interface BreadcrumbItem {
  id: string;
  label: string;
  disabled?: boolean;
}

export interface BreadcrumbsProps {
  items: readonly BreadcrumbItem[];
  onNavigate: (id: string) => void;
  ariaLabel?: string;
  maxVisible?: number;
  className?: string;
}

/** Stable-path navigation. The last item is the current page; long paths use
 * the shared Menu for intermediate locations rather than a second popup. */
export function Breadcrumbs({
  items,
  onNavigate,
  ariaLabel = "Breadcrumbs",
  maxVisible = 5,
  className,
}: BreadcrumbsProps) {
  if (items.length === 0) return null;
  const visibleLimit = Math.max(3, maxVisible);
  const overflowCount = Math.max(0, items.length - visibleLimit);
  const first = items[0];
  const hidden = overflowCount > 0 ? items.slice(1, overflowCount + 1) : [];
  const visible = overflowCount > 0 ? [first, ...items.slice(overflowCount + 1)] : items;
  const overflowItems: MenuItem[] = hidden.map((item) => ({
    id: item.id,
    label: item.label,
    disabled: item.disabled,
    disabledReason: item.disabled ? "This location is unavailable." : undefined,
  }));
  const classes = ["aui-breadcrumbs", className].filter(Boolean).join(" ");
  return <nav className={classes} aria-label={ariaLabel}>
    <ol>
      {visible.map((item, visibleIndex) => {
        const originalIndex = items.findIndex((candidate) => candidate.id === item.id);
        const current = originalIndex === items.length - 1;
        const insertOverflow = visibleIndex === 1 && hidden.length > 0;
        return <li key={item.id}>
          {insertOverflow ? <>
            <span className="aui-breadcrumbs-separator" aria-hidden>/</span>
            <MenuButton label="More locations" items={overflowItems} onSelect={onNavigate} placement="bottom-start">…</MenuButton>
          </> : null}
          {visibleIndex > 0 ? <span className="aui-breadcrumbs-separator" aria-hidden>/</span> : null}
          {current ? <span className="aui-breadcrumb-current" aria-current="page">{item.label}</span> : <button type="button" disabled={item.disabled} onClick={() => onNavigate(item.id)}>{item.label}</button>}
        </li>;
      })}
    </ol>
  </nav>;
}
