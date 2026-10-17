/* Runs before @aether/ui loads (import order in main.tsx): sets the host
 * attributes, and defaults the appearance to Light like Studio when this
 * device has no stored choice. */
import { applyHostAttributes, detectHost } from "./host";

applyHostAttributes(detectHost());
try {
  if (!localStorage.getItem("aether-appearance")) localStorage.setItem("aether-appearance", "light");
} catch { /* storage unavailable: Aether falls back to System */ }
