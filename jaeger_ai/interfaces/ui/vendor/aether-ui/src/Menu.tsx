import { createPortal } from "react-dom";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { ButtonHTMLAttributes, KeyboardEvent, ReactNode } from "react";
import {
  useOverlayPosition,
  type OverlayAnchor,
  type OverlayPlacement,
} from "./overlay-position";

export type MenuItemKind = "command" | "checkbox" | "radio";

export interface MenuItem {
  id: string;
  label: string;
  icon?: ReactNode;
  shortcut?: string;
  kind?: MenuItemKind;
  checked?: boolean;
  disabled?: boolean;
  disabledReason?: string;
  danger?: boolean;
  separatorBefore?: boolean;
  children?: readonly MenuItem[];
}

export interface MenuProps {
  open: boolean;
  anchor: OverlayAnchor | null;
  items: readonly MenuItem[];
  onSelect: (id: string) => void;
  onClose: () => void;
  ariaLabel: string;
  placement?: OverlayPlacement;
  returnFocus?: boolean;
}

function menuRole(item: MenuItem): "menuitem" | "menuitemcheckbox" | "menuitemradio" {
  if (item.kind === "checkbox") return "menuitemcheckbox";
  if (item.kind === "radio") return "menuitemradio";
  return "menuitem";
}

/** Controlled popup menu. All menu surfaces consume the same item model and
 * report command IDs; product code owns availability and execution. */
export function Menu({
  open,
  anchor,
  items,
  onSelect,
  onClose,
  ariaLabel,
  placement = "bottom-start",
  returnFocus = true,
}: MenuProps) {
  const rootRef = useRef<HTMLUListElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const [expandedIDs, setExpandedIDs] = useState<ReadonlySet<string>>(new Set());
  const position = useOverlayPosition({
    open,
    overlayRef: rootRef,
    anchor,
    placement,
  });

  useLayoutEffect(() => {
    if (!open) return;
    returnFocusRef.current =
      anchor instanceof HTMLElement
        ? anchor
        : (document.activeElement as HTMLElement | null);
    setExpandedIDs(new Set());
    rootRef.current
      ?.querySelector<HTMLButtonElement>('.aui-menu-item:not(:disabled)')
      ?.focus();
  }, [anchor, open]);

  useEffect(() => {
    if (!open) return;
    const onDocumentKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      onClose();
    };
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (rootRef.current?.contains(target)) return;
      if (anchor instanceof HTMLElement && anchor.contains(target)) return;
      onClose();
    };
    document.addEventListener("keydown", onDocumentKeyDown, true);
    document.addEventListener("pointerdown", onPointerDown, true);
    return () => {
      document.removeEventListener("keydown", onDocumentKeyDown, true);
      document.removeEventListener("pointerdown", onPointerDown, true);
      if (returnFocus) returnFocusRef.current?.focus?.();
      returnFocusRef.current = null;
    };
  }, [anchor, onClose, open, returnFocus]);

  const buttonsIn = (list: HTMLElement): HTMLButtonElement[] =>
    Array.from(list.children)
      .map((child) => child.querySelector<HTMLButtonElement>(":scope > .aui-menu-item"))
      .filter((button): button is HTMLButtonElement => Boolean(button && !button.disabled));

  const onKeyDown = (event: KeyboardEvent<HTMLUListElement>) => {
    const target = (event.target as HTMLElement).closest<HTMLButtonElement>(
      ".aui-menu-item",
    );
    if (!target) return;
    const list = target.closest<HTMLElement>('[role="menu"]');
    if (!list) return;
    const buttons = buttonsIn(list);
    const index = buttons.indexOf(target);
    const focusAt = (next: number) => buttons[next]?.focus();

    switch (event.key) {
      case "ArrowDown":
        focusAt((index + 1) % buttons.length);
        break;
      case "ArrowUp":
        focusAt((index - 1 + buttons.length) % buttons.length);
        break;
      case "Home":
        focusAt(0);
        break;
      case "End":
        focusAt(buttons.length - 1);
        break;
      case "ArrowRight": {
        const id = target.dataset.menuItemId;
        if (!id || target.getAttribute("aria-haspopup") !== "menu") return;
        setExpandedIDs((current) => new Set([...current, id]));
        queueMicrotask(() => {
          const submenu = Array.from(
            rootRef.current?.querySelectorAll<HTMLElement>("[data-menu-parent]") ?? [],
          ).find((candidate) => candidate.dataset.menuParent === id);
          submenu?.querySelector<HTMLButtonElement>(".aui-menu-item:not(:disabled)")?.focus();
        });
        break;
      }
      case "ArrowLeft": {
        const parentID = list.dataset.menuParent;
        if (!parentID) return;
        setExpandedIDs((current) => {
          const next = new Set(current);
          next.delete(parentID);
          return next;
        });
        Array.from(
          rootRef.current?.querySelectorAll<HTMLButtonElement>("[data-menu-item-id]") ?? [],
        )
          .find((candidate) => candidate.dataset.menuItemId === parentID)
          ?.focus();
        break;
      }
      case "Enter":
      case " ":
        target.click();
        break;
      case "Escape":
        onClose();
        break;
      default:
        return;
    }
    event.preventDefault();
    event.stopPropagation();
  };

  const renderItems = (menuItems: readonly MenuItem[], parentID?: string): ReactNode => (
    <ul
      className={parentID ? "aui-menu aui-menu-submenu" : "aui-menu"}
      role="menu"
      aria-label={parentID ? undefined : ariaLabel}
      data-menu-parent={parentID}
      onKeyDown={onKeyDown}
      ref={parentID ? undefined : rootRef}
      style={parentID ? undefined : position}
    >
      {menuItems.map((item) => {
        const hasChildren = Boolean(item.children?.length);
        const expanded = hasChildren && expandedIDs.has(item.id);
        const classes = ["aui-menu-item"];
        if (item.danger) classes.push("aui-menu-item--danger");
        return (
          <li key={item.id} className="aui-menu-entry" role="none">
            {item.separatorBefore ? <div className="aui-menu-separator" role="separator" /> : null}
            <button
              type="button"
              className={classes.join(" ")}
              role={menuRole(item)}
              aria-checked={item.kind && item.kind !== "command" ? Boolean(item.checked) : undefined}
              aria-haspopup={hasChildren ? "menu" : undefined}
              aria-expanded={hasChildren ? expanded : undefined}
              disabled={item.disabled}
              title={item.disabled ? item.disabledReason : undefined}
              data-menu-item-id={item.id}
              onMouseEnter={() => {
                if (!hasChildren) return;
                setExpandedIDs((current) => new Set([...current, item.id]));
              }}
              onClick={() => {
                if (hasChildren) {
                  setExpandedIDs((current) => {
                    const next = new Set(current);
                    if (next.has(item.id)) next.delete(item.id);
                    else next.add(item.id);
                    return next;
                  });
                  return;
                }
                onSelect(item.id);
                onClose();
              }}
            >
              <span className="aui-menu-check" aria-hidden>
                {item.kind === "radio" && item.checked
                  ? "●"
                  : item.kind === "checkbox" && item.checked
                    ? "✓"
                    : ""}
              </span>
              <span className="aui-menu-icon" aria-hidden>{item.icon ?? ""}</span>
              <span className="aui-menu-label">{item.label}</span>
              <span className="aui-menu-shortcut">{item.shortcut ?? ""}</span>
              <span className="aui-menu-arrow" aria-hidden>{hasChildren ? "›" : ""}</span>
            </button>
            {expanded && item.children ? renderItems(item.children, item.id) : null}
          </li>
        );
      })}
    </ul>
  );

  if (!open || !anchor || typeof document === "undefined") return null;
  return createPortal(renderItems(items), document.body);
}

export interface MenuButtonProps
  extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "onSelect"> {
  label: string;
  items: readonly MenuItem[];
  onSelect: (id: string) => void;
  children: ReactNode;
  placement?: OverlayPlacement;
}

/** Standard anchor button for a Menu. Context menus use Menu directly with a
 * pointer position anchor. */
export function MenuButton({
  label,
  items,
  onSelect,
  children,
  placement = "bottom-end",
  className,
  ...buttonProps
}: MenuButtonProps) {
  const anchorRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const classes = ["aui-menu-trigger"];
  if (className) classes.push(className);
  return (
    <>
      <button
        {...buttonProps}
        ref={anchorRef}
        type="button"
        className={classes.join(" ")}
        aria-label={label}
        title={label}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        {children}
      </button>
      <Menu
        open={open}
        anchor={anchorRef.current}
        items={items}
        onSelect={onSelect}
        onClose={() => setOpen(false)}
        ariaLabel={label}
        placement={placement}
      />
    </>
  );
}
