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
    label: "Command",
    requiredCapabilities: ["chat.sessions", "chat.approvals"],
    authoritativeOwner: "gateway",
  },
  {
    id: "tasks",
    label: "Work & Studio",
    requiredCapabilities: ["tasks.board"],
    authoritativeOwner: "gateway",
  },
  {
    id: "tools",
    label: "Team & Tools",
    requiredCapabilities: ["tools.inventory"],
    authoritativeOwner: "gateway",
  },
  {
    id: "memory",
    label: "Memory & Life",
    requiredCapabilities: ["memory.facts"],
    authoritativeOwner: "gateway",
  },
  {
    id: "settings",
    label: "Control & Body",
    requiredCapabilities: ["settings.models"],
    authoritativeOwner: "gateway",
  },
]);

export function getDestination(id: DestinationId): DestinationDescriptor {
  const match = JAEGER_DESTINATIONS.find((d) => d.id === id);
  if (!match) throw new Error(`Unknown destination: ${id}`);
  return match;
}
