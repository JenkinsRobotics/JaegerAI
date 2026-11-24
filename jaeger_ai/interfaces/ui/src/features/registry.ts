/**
 * ui-features: Capability-declared feature module registry.
 *
 * Every UI feature declares the exact Gateway capabilities it requires so
 * WebUI, VS Code, and macOS hosts share one consistent availability contract
 * without duplicating business logic or inventing fallback data.
 */
import type { JaegerSource, UiCapabilityKey } from "../contracts";
import { evaluateCapabilities } from "../contracts";

export type UiFeatureId =
  | "chat"
  | "tasks"
  | "tools"
  | "browser"
  | "memory"
  | "skills"
  | "settings"
  | "diagnostics";

export interface UiFeatureDescriptor {
  readonly id: UiFeatureId;
  readonly label: string;
  readonly requiredCapabilities: readonly UiCapabilityKey[];
  readonly optionalCapabilities?: readonly UiCapabilityKey[];
  readonly authoritativeOwner: "gateway";
}

export const UI_FEATURE_MODULES: readonly UiFeatureDescriptor[] = Object.freeze([
  {
    id: "chat",
    label: "Chat",
    requiredCapabilities: ["chat.sessions", "chat.approvals"],
    optionalCapabilities: ["chat.queue", "files.attachments", "agents.catalog"],
    authoritativeOwner: "gateway",
  },
  {
    id: "tasks",
    label: "Tasks",
    requiredCapabilities: ["tasks.board"],
    optionalCapabilities: ["tasks.workflows", "files.attachments"],
    authoritativeOwner: "gateway",
  },
  {
    id: "tools",
    label: "Tools",
    requiredCapabilities: ["tools.inventory"],
    optionalCapabilities: ["tools.mcp", "tools.plugins"],
    authoritativeOwner: "gateway",
  },
  {
    id: "browser",
    label: "Browser",
    requiredCapabilities: ["tools.inventory", "chat.sessions"],
    optionalCapabilities: ["diagnostics.process"],
    authoritativeOwner: "gateway",
  },
  {
    id: "memory",
    label: "Memory",
    requiredCapabilities: ["memory.facts"],
    optionalCapabilities: ["memory.library", "memory.episodes"],
    authoritativeOwner: "gateway",
  },
  {
    id: "skills",
    label: "Skills",
    requiredCapabilities: ["skills.catalog"],
    optionalCapabilities: ["tools.inventory"],
    authoritativeOwner: "gateway",
  },
  {
    id: "settings",
    label: "Settings",
    requiredCapabilities: ["settings.models"],
    optionalCapabilities: ["settings.runtime", "settings.channels"],
    authoritativeOwner: "gateway",
  },
  {
    id: "diagnostics",
    label: "Diagnostics",
    requiredCapabilities: ["diagnostics.gateway"],
    optionalCapabilities: ["diagnostics.process"],
    authoritativeOwner: "gateway",
  },
]);

export function getFeatureModule(id: UiFeatureId): UiFeatureDescriptor {
  const found = UI_FEATURE_MODULES.find((f) => f.id === id);
  if (!found) {
    throw new Error(`Unknown UI feature module: ${id}`);
  }
  return found;
}

export function availableFeaturesFor(source: JaegerSource | null | undefined): {
  available: UiFeatureDescriptor[];
  unavailable: Array<{ feature: UiFeatureDescriptor; missing: UiCapabilityKey[] }>;
} {
  const available: UiFeatureDescriptor[] = [];
  const unavailable: Array<{ feature: UiFeatureDescriptor; missing: UiCapabilityKey[] }> = [];
  for (const feature of UI_FEATURE_MODULES) {
    const check = evaluateCapabilities(source, feature.requiredCapabilities);
    if (check.supported) {
      available.push(feature);
    } else {
      unavailable.push({ feature, missing: check.missing });
    }
  }
  return { available, unavailable };
}
