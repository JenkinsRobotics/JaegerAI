import type { ReactNode } from "react";

export interface DocumentBarProps {
  /** Left cluster: home button, project name, save state, commands. */
  leading?: ReactNode;
  /** Centered on the window (usually workspace <Tabs>). */
  center?: ReactNode;
  /** Right cluster: engine status, layout preset button, window menus. */
  trailing?: ReactNode;
  className?: string;
  /** Disable for embedded component previews. */
  windowChrome?: boolean;
}

/** The shared top app-window row (Swift `StudioDocumentBar`): leading and
 *  trailing clusters with the center slot truly window-centered. */
export function DocumentBar({ leading, center, trailing, className, windowChrome = true }: DocumentBarProps) {
  const classes = ["aui-document-bar"];
  if (className) classes.push(className);
  return (
    <header className={classes.join(" ")} data-aether-window-drag-region={windowChrome ? "true" : undefined}>
      <div className="aui-document-bar-cluster">
        {windowChrome && <span className="aui-native-titlebar-space" aria-hidden="true" />}
        {leading}
      </div>
      {center ? <div className="aui-document-bar-center">{center}</div> : null}
      <div className="aui-document-bar-cluster aui-document-bar-cluster--trailing">
        {trailing}
      </div>
    </header>
  );
}
