import "@jaeger/ui-kit/tokens.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { JaegerApp } from "@jaeger/ui-features";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <JaegerApp />
  </StrictMode>,
);
