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
import { AppWindow } from "./windows/AppWindow";
import { FirstRunGate, firstRunApi } from "./first-run/FirstRun";
import { GatewayClient } from "./api/gateway";
import { clearLegacyFlags, legacyRedirect } from "./shell/router";
import { applyAppearance, storedAppearance } from "./settings/SettingsDialog";
import { applyDensity, applyFeel, applyIcon, storedDensity, storedFeel, storedIcon } from "./settings/appearance";
import { applyPreset, storedPreset, syncPresetFromGateway } from "./shell/layoutPresets";
import { syncLogoFromGateway } from "./brand/logo";

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

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <FirstRunGate api={source instanceof GatewayClient ? firstRunApi(source) : null}><AppWindow source={source} /></FirstRunGate>
  </StrictMode>,
);
