/**
 * Gateway layout transport (Jenkins Robotics, 2026-10-29, original).
 *
 * Dashboard layouts belong to the operator, not the repo: they live at
 * `~/.jaeger/dashboard.json` and are read/written through the gateway. This module is
 * the only place the HTTP shape is known.
 *
 * Paths are same-origin, matching `GatewayClient` (the WebUI proxy forwards /v1/* and
 * attaches the caller token), so no base URL or token is held here.
 *
 * A missing route is not an error: `read()` reports `available: false` and the host
 * says so in plain words. Raw status codes are never surfaced to the UI.
 */
import { emptyDoc } from "./layoutStore";
import type { DashboardDoc } from "./types";

const PATH = "/v1/dashboard";
const jsonHeaders = { "Content-Type": "application/json" };

export interface LayoutRead {
  doc: DashboardDoc;
  /** False when the gateway has no dashboard route yet. Not an error. */
  available: boolean;
}

export interface GatewayLayoutTransport {
  read(): Promise<LayoutRead>;
  /** Resolves when the gateway accepted the write; rejects otherwise. */
  write(doc: DashboardDoc): Promise<void>;
  /** True while no dashboard route exists on the gateway. */
  readonly pendingRoute: boolean;
}

export function gatewayLayoutTransport(): GatewayLayoutTransport {
  let pending = true;
  return {
    get pendingRoute() { return pending; },
    async read(): Promise<LayoutRead> {
      try {
        const response = await fetch(PATH, { headers: jsonHeaders, credentials: "include" });
        if (response.status === 404) {
          pending = true;
          return { doc: emptyDoc(), available: false };
        }
        if (!response.ok) {
          // Auth problems and the like are not the UI's business; report the route
          // as absent and let the caller fall back to its cached copy.
          pending = true;
          return { doc: emptyDoc(), available: false };
        }
        pending = false;
        return { doc: (await response.json()) as DashboardDoc, available: true };
      } catch {
        return { doc: emptyDoc(), available: false };
      }
    },
    async write(doc) {
      const response = await fetch(PATH, {
        method: "PUT",
        headers: jsonHeaders,
        credentials: "include",
        body: JSON.stringify(doc),
      });
      if (response.status === 404) {
        pending = true;
        throw new Error("pending");
      }
      if (!response.ok) throw new Error("write failed");
      pending = false;
    },
  };
}
