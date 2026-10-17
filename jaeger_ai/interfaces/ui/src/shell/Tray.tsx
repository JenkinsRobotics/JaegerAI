/* Modified from AetherStudio studio/src/main.tsx StudioTray() (Apache-2.0,
 * ece0209): StatusBar + StatusDot + AppearanceToggle. Shows which data source
 * is live. */
import { AppearanceToggle, StatusBar, StatusDot, type StatusKind } from "@aether/ui";

export function Tray({ status, label }: { status: StatusKind; label: string }) {
  return (
    <div className="jg-tray">
      <StatusBar leading={<span className="jg-tray__item"><StatusDot kind={status} /> {label}</span>} trailing={<AppearanceToggle />} />
    </div>
  );
}
