/* Dev-only standalone page: /orchestration-harness.html (not a vite build input).
 * ?fail=1 shows the error state; ?step=<ms> paces the scripted stream. */
import "../platform/bootstrap";
import "@aether/ui/tokens.css";
import "@aether/ui/widgets.css";
import "../shell/tokens.jaeger.css";
import "../shell/shell.css";
import "../agents/agents.css";
import "../unified/design.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { mockAdapter } from "./mockOrchestration";
import { OrchestrationPanes } from "./OrchestrationPanes";

const q = new URLSearchParams(location.search);
const adapter = mockAdapter({ fail: q.has("fail"), stepMs: Number(q.get("step") ?? 0) });
const root = document.getElementById("root")!;
root.style.height = "100dvh";
createRoot(root).render(
  <StrictMode>
    <OrchestrationPanes adapter={adapter} onNavigate={(href) => { document.title = `nav:${href}`; }} />
  </StrictMode>,
);
