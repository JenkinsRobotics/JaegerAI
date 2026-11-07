/** Settings search registry (TAB-01 §3): every searchable row → panel + anchor id. */
export type PanelId = "checkpoints" | "widgets" | "appearance" | "general" | "voice" | "notifications" | "agents" | "memory" | "integrations" | "models" | "automations" | "machine" | "privacy" | "limits" | "about";
export interface Entry { id: string; panel: PanelId; anchor: string; label: string; keywords: string[] }
export const PANEL_LABEL: Record<PanelId, string> = {
  checkpoints: "Checkpoints", widgets: "My widgets", appearance: "Appearance", general: "General", voice: "Voice & audio", notifications: "Notifications", agents: "Agents", memory: "Memory & skills",
  integrations: "Integrations & MCP", models: "Models & Providers", automations: "Automations", machine: "Machine & devices", privacy: "Privacy & data", limits: "Spending limits", about: "About & diagnostics",
};
export const GROUPS: { id: string; label: string; panels: PanelId[] }[] = [
  { id: "you", label: "You", panels: ["appearance", "general", "voice", "notifications"] },
  { id: "agents", label: "Agents", panels: ["agents", "memory"] },
  { id: "connections", label: "Connections", panels: ["integrations", "models", "automations"] },
  { id: "machine", label: "Machine", panels: ["machine"] },
  { id: "privacy", label: "Privacy", panels: ["privacy", "limits"] },
  { id: "system", label: "System", panels: ["checkpoints", "widgets", "about"] },
];
/** Old /settings/<id> → new panel (+ optional segment). */
export const LEGACY_SETTINGS: Record<string, string> = {
  providers: "models", connection: "models", tools: "integrations/tools", workflows: "automations", channels: "automations",
  skills: "memory", library: "memory", diagnostics: "about", reset: "about", finance: "limits",
};
const e = (panel: PanelId, anchor: string, label: string, ...keywords: string[]): Entry => ({ id: `${panel}.${anchor}`, panel, anchor, label, keywords });
export const REGISTRY: Entry[] = [
  e("checkpoints", "checkpoints", "Checkpoints", "workspace", "versions", "restore"),
  e("widgets", "widgets", "My widgets", "personalisation", "layout"),
  e("models", "library", "Model library", "models", "inventory"),
  e("models", "compare", "Compare models", "compare"),
  e("models", "usage", "Model usage", "usage"),
  e("integrations", "hermes", "Hermes", "engine"),
  e("integrations", "openclaw", "OpenClaw", "engine"),
  e("integrations", "sharepoint", "SharePoint", "documents"),
  e("appearance", "theme", "Theme (Light, Dark, System)", "theme", "dark", "light", "mode", "appearance"),
  e("appearance", "feel", "Feel", "feel", "style", "colors", "accent", "jaeger blue", "skin"),
  e("appearance", "icon", "App icon", "icon", "logo", "favicon", "dock", "custom icon", "upload"),
  e("appearance", "text-size", "Text size", "font", "text size", "zoom"),
  e("appearance", "density", "Density", "density", "compact", "comfortable", "rows"),
  e("general", "stream-style", "Stream style", "stream", "typing", "animation"),
  e("general", "device", "Device preferences", "device", "preferences"),
  e("voice", "dictation", "Dictation", "voice", "microphone", "mic", "dictation", "speech"),
  e("voice", "spoken", "Spoken turns", "voice", "tts", "speak", "audio"),
  e("notifications", "notifications", "Notifications", "notifications", "alerts"),
  e("agents", "agents", "Manage agents", "agents", "bots", "specialists", "primary"),
  e("memory", "memory", "Memory", "memory", "facts", "claims"),
  e("memory", "skills", "Skills", "skills"),
  e("memory", "library", "Library", "library", "artifacts"),
  e("integrations", "servers", "MCP servers", "mcp", "servers", "integrations", "add server"),
  e("integrations", "tools", "Tools", "tools", "mcp tools"),
  e("integrations", "apps", "Apps", "apps", "connectors", "microsoft", "sharepoint"),
  e("models", "cli", "Subscription apps (Codex, Claude, Gemini, Copilot)", "sign in", "codex", "claude", "gemini", "copilot", "cli", "providers", "login"),
  e("models", "ollama", "Ollama", "ollama", "local models", "offline"),
  e("automations", "automations", "Schedules & webhooks", "automations", "schedules", "webhooks", "cron"),
  e("automations", "workflows", "Workflows", "workflows"),
  e("automations", "channels", "Channels", "channels", "telegram", "discord", "slack"),
  e("machine", "computer", "Local computer control", "computer", "control", "screen", "machine"),
  e("machine", "clipboard", "Clipboard", "clipboard", "paste"),
  e("machine", "gateway", "Gateway address", "gateway", "api", "address", "loopback"),
  e("privacy", "uploads", "Send file contents with messages", "files", "upload", "privacy", "attachments"),
  e("privacy", "storage", "Where your data lives", "data", "storage", "on device", "local", "export", "telemetry"),
  e("limits", "limits", "Spending limits", "spending", "limits", "finance", "money", "budget"),
  e("about", "version", "Version & updates", "version", "updates", "about"),
  e("about", "diagnostics", "Diagnostics", "diagnostics", "logs", "debug"),
  e("about", "reset", "Reset", "reset", "danger", "erase"),
];
export function search(q: string, available: (p: PanelId) => boolean = () => true): Entry[] {
  const s = q.trim().toLowerCase();
  if (!s) return [];
  return REGISTRY.filter((x) => available(x.panel) && (x.label.toLowerCase().includes(s) || PANEL_LABEL[x.panel].toLowerCase().includes(s) || x.keywords.some((k) => k.includes(s))));
}
