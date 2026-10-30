import "./platform/bootstrap";
import "@aether/ui/tokens.css";
import "@aether/ui/widgets.css";
import "@aether/ui/home.css";
import "./shell/tokens.jaeger.css";
import "./shell/shell.css";
import "./agents/agents.css";
import "./chat/chat.css";
import "./settings/settings.css";
import "./tasks/tasks.css";
import "./shell/motion.css";
// One app: the unified shell (dock pages at real routes). The old `?ui=apple|windows|default`
// switch and its localStorage flags are retired; old links land on the matching page.
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createSource } from "./api";
import { AppWindow } from "./windows/AppWindow";
import { clearLegacyFlags, legacyRedirect } from "./shell/router";
import { applyAppearance, storedAppearance } from "./settings/SettingsDialog";

const redirect = legacyRedirect(location.pathname, location.search);
if (redirect) history.replaceState(null, "", redirect + location.hash);
clearLegacyFlags();
applyAppearance(storedAppearance());

const source = await createSource();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AppWindow source={source} />
  </StrictMode>,
);
