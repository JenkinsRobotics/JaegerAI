/**
 * @jaeger/ui-features: 5-destination studio registry with Gateway capability gating.
 */

export type DestinationId = "chat" | "tasks" | "tools" | "memory" | "settings";

export interface DestinationDescriptor {
  readonly id: DestinationId;
  readonly label: string;
  readonly requiredCapabilities: readonly string[];
  readonly authoritativeOwner: "gateway";
}

export const JAEGER_DESTINATIONS: readonly DestinationDescriptor[] = Object.freeze([
  {
    id: "chat",
    label: "Chat",
    requiredCapabilities: ["chat.sessions", "chat.approvals"],
    authoritativeOwner: "gateway",
  },
  {
    id: "tasks",
    label: "Work",
    requiredCapabilities: ["tasks.board"],
    authoritativeOwner: "gateway",
  },
  {
    id: "tools",
    label: "Agents",
    requiredCapabilities: ["tools.inventory"],
    authoritativeOwner: "gateway",
  },
  {
    id: "memory",
    label: "Library",
    requiredCapabilities: ["memory.facts"],
    authoritativeOwner: "gateway",
  },
  {
    id: "settings",
    label: "Settings",
    requiredCapabilities: ["settings.models"],
    authoritativeOwner: "gateway",
  },
]);

export function getDestination(id: DestinationId): DestinationDescriptor {
  const match = JAEGER_DESTINATIONS.find((d) => d.id === id);
  if (!match) throw new Error(`Unknown destination: ${id}`);
  return match;
}
