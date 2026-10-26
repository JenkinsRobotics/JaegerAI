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
// Apple-Native Design System (v0.13.0) — Self-contained
// Loaded only when ?ui=apple or jaeger.ui.apple=1
// The AppleApp component imports its own styles via apple-app.css
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { createSource } from "./api";

// Feature flag: Set to true to use the new Apple-native UI
const USE_APPLE_UI = new URLSearchParams(window.location.search).get("ui") === "apple" ||
                     localStorage.getItem("jaeger.ui.apple") === "1";

const source = await createSource();

// Render Apple UI or Classic UI based on flag
if (USE_APPLE_UI) {
  const { AppleApp } = await import("./AppleApp");
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <AppleApp />
    </StrictMode>,
  );
} else {
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App source={source} />
    </StrictMode>,
  );
}
