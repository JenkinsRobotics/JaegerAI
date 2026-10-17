import type { ReactNode } from "react";

export type StatusKind = "ok" | "busy" | "warn" | "error";

export function StatusDot({ kind }: { kind: StatusKind }) {
  const classes = ["aui-status-dot"];
  if (kind === "ok") classes.push("aui-status-dot--ok");
  if (kind === "error") classes.push("aui-status-dot--error");
  if (kind === "busy") classes.push("aui-status-dot--busy");
  return <span className={classes.join(" ")} aria-hidden />;
}

/**
 * Bottom application status strip. Either pass plain children (legacy single
 * row) or the three regions: `leading` (app identity: connection dot, product
 * name, engine), `center` (dynamic notification area, truncates), `trailing`
 * (metrics and ambient controls).
 */
export function StatusBar({ leading, center, trailing, children }: {
  leading?: ReactNode;
  center?: ReactNode;
  trailing?: ReactNode;
  children?: ReactNode;
}) {
  const hasRegions = leading !== undefined || center !== undefined || trailing !== undefined;
  return (
    <div className="aui-status-bar" aria-label="Workspace status">
      {hasRegions ? (
        <>
          <div className="aui-status-bar__leading">{leading}</div>
          <div className="aui-status-bar__center">{center}</div>
          <div className="aui-status-bar__trailing">{trailing}</div>
        </>
      ) : children}
    </div>
  );
}
