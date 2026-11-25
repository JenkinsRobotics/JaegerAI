import "./platform/bootstrap";
import "@aether/ui/tokens.css";
import "@aether/ui/widgets.css";
import "@aether/ui/home.css";
import "./shell/tokens.jaeger.css";
import "./shell/feels.css";
import "./shell/shell.css";
import "./agents/agents.css";
import "./chat/chat.css";
import "./settings/settings.css";
import "./tasks/tasks.css";
import "./shell/presets.css";
import "./shell/motion.css";
// One app: the unified shell (dock pages at real routes). The old `?ui=apple|windows|default`
// switch and its localStorage flags are retired; old links land on the matching page.
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createSource } from "./api";
import { StableDemo } from "./demo/StableDemo";
import { UnifiedShell } from "./shell/UnifiedShell";
import { FirstRunGate, firstRunApi } from "./first-run/FirstRun";
import { GatewayClient } from "./api/gateway";
import { clearLegacyFlags, legacyRedirect } from "./shell/router";
import { applyAppearance, storedAppearance } from "./settings/SettingsDialog";
import { applyDensity, applyFeel, applyIcon, storedDensity, storedFeel, storedIcon } from "./settings/appearance";
import { applyPreset, storedPreset, syncPresetFromGateway } from "./shell/layoutPresets";
import { syncLogoFromGateway } from "./brand/logo";
import { registerServiceWorker, startPresence, syncPush } from "./platform/webPush";

const redirect = legacyRedirect(location.pathname, location.search);
if (redirect) history.replaceState(null, "", redirect + location.hash);
clearLegacyFlags();
applyAppearance(storedAppearance());
applyFeel(storedFeel());
applyIcon(storedIcon());
applyDensity(storedDensity());
applyPreset(storedPreset());
void syncPresetFromGateway();
void syncLogoFromGateway();

const source = await createSource();
// Web Push: push-only service worker, keep this device's subscription fresh,
// and tell the Gateway when a window is in use (long replies push only while away).
void registerServiceWorker().then(() => syncPush()).catch(() => undefined);
startPresence();

const useLegacyShell = new URLSearchParams(location.search).get("shell") === "legacy";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <FirstRunGate api={source instanceof GatewayClient ? firstRunApi(source) : null}>
      {useLegacyShell ? <StableDemo source={source} /> : <UnifiedShell source={source} />}
    </FirstRunGate>
  </StrictMode>,
);
