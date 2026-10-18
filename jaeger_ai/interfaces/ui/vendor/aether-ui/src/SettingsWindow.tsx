import { useEffect } from "react";
import type { ReactNode } from "react";

export interface SettingsPane {
  id: string;
  label: string;
  icon?: ReactNode;
  disabled?: boolean;
}

export interface SettingsSection {
  title: string;
  panes: SettingsPane[];
}

export interface SettingsWindowProps {
  open: boolean;
  title: string;
  sections: SettingsSection[];
  activePaneID: string;
  onSelectPane: (id: string) => void;
  onClose: () => void;
  /** Content of the active pane. */
  children: ReactNode;
}

/** The suite-standard per-app settings window: macOS anatomy — traffic-light
 *  close, grouped sidebar (General / Viewport / Advanced …), card-based
 *  content pane. Products supply sections and pane content; disabled panes
 *  render greyed out as placeholders. */
export function SettingsWindow(props: SettingsWindowProps) {
  const { open, title, sections, activePaneID, onSelectPane, onClose } = props;
  useEffect(() => {
    if (!open) return;
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="aui-settings-scrim" onClick={onClose}>
      <div
        className="aui-settings-window"
        role="dialog"
        aria-label={title}
        onClick={(event) => event.stopPropagation()}
      >
        <aside className="aui-settings-sidebar">
          <button
            type="button"
            className="aui-settings-close"
            aria-label={`Close ${title}`}
            onClick={onClose}
          />
          {sections.map((section) => (
            <div key={section.title} className="aui-settings-section">
              <span className="aui-settings-section-title">{section.title}</span>
              {section.panes.map((pane) => (
                <button
                  key={pane.id}
                  type="button"
                  disabled={pane.disabled}
                  className={
                    "aui-settings-item" + (pane.id === activePaneID ? " active" : "")
                  }
                  onClick={() => onSelectPane(pane.id)}
                >
                  {pane.icon}
                  <span>{pane.label}</span>
                </button>
              ))}
            </div>
          ))}
        </aside>
        <div className="aui-settings-content">
          <header className="aui-settings-title">{title}</header>
          <div className="aui-settings-pane">{props.children}</div>
        </div>
      </div>
    </div>
  );
}

/** Rounded settings card with the Anima Studio section header: accent icon,
 *  bold title, muted caption. `tone="notice"` renders the accent info card. */
export function SettingsCard(props: {
  title?: ReactNode;
  caption?: ReactNode;
  icon?: ReactNode;
  tone?: "notice";
  children?: ReactNode;
}) {
  return (
    <section className={"aui-settings-card" + (props.tone ? ` ${props.tone}` : "")}>
      {props.title ? (
        <span className="aui-settings-card-header">
          {props.icon ? <span className="aui-settings-card-icon">{props.icon}</span> : null}
          <strong className="aui-settings-card-title">{props.title}</strong>
        </span>
      ) : null}
      {props.caption ? <p className="aui-settings-card-caption">{props.caption}</p> : null}
      {props.children}
    </section>
  );
}

/** Settings row. Default: label left, control right. `stacked` puts the
 *  control full-width under the label line with `value` right-aligned —
 *  the Anima Studio slider row. */
export function SettingsRow(props: {
  label: ReactNode;
  icon?: ReactNode;
  value?: ReactNode;
  caption?: ReactNode;
  disabled?: boolean;
  stacked?: boolean;
  children?: ReactNode;
}) {
  return (
    <div className={"aui-settings-row" + (props.disabled ? " disabled" : "") + (props.stacked ? " stacked" : "")}>
      <div className="aui-settings-row-main">
        {props.icon ? <span className="aui-settings-row-icon">{props.icon}</span> : null}
        <span className="aui-settings-row-label">{props.label}</span>
        {props.value !== undefined ? <span className="aui-settings-row-value">{props.value}</span> : null}
        {!props.stacked ? <span className="aui-settings-row-control">{props.children}</span> : null}
      </div>
      {props.stacked ? <div className="aui-settings-row-wide">{props.children}</div> : null}
      {props.caption ? <p className="aui-settings-row-caption">{props.caption}</p> : null}
    </div>
  );
}
