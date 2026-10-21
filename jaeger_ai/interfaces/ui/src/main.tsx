import "./platform/bootstrap";
import "../vendor/jaeger-design-tokens/jaeger.css";
import "../vendor/jaeger-design-tokens/aether.css";
import "@aether/ui/widgets.css";
import "@aether/ui/home.css";
import "./shell/tokens.compat.css";
import "./shell/shell.css";
import "./agents/agents.css";
import "./chat/chat.css";
import "./settings/settings.css";
import "./tasks/tasks.css";
import "./shell/motion.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { createSource } from "./api";

const source = await createSource();
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App source={source} />
  </StrictMode>,
);
