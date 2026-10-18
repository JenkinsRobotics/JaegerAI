import { GatewayClient } from "./gateway";
import type { JaegerSource } from "./source";

export interface MockEnv {
  DEV: boolean;
  VITE_JAEGER_MOCK?: string;
}

/** Mock data exists only in dev builds, or in builds made with
 * VITE_JAEGER_MOCK=1 (screenshots). A production build ignores ?mock=1. */
export function mockAllowed(env: MockEnv = import.meta.env): boolean {
  return env.DEV || env.VITE_JAEGER_MOCK === "1";
}

export function mockRequested(search: string, env: MockEnv = import.meta.env): boolean {
  if (!mockAllowed(env)) return false;
  const flag = new URLSearchParams(search).get("mock");
  if (flag === "1" || flag === "true") return true;
  if (flag === "0" || flag === "false") return false;
  return env.VITE_JAEGER_MOCK === "1";
}

export async function createSource(search = typeof location === "undefined" ? "" : location.search): Promise<JaegerSource> {
  // The condition is a build-time constant, so production bundles drop the
  // mock chunk entirely (verified by `npm run check:no-mock`).
  if ((import.meta.env.DEV || import.meta.env.VITE_JAEGER_MOCK === "1") && mockRequested(search)) {
    const { MockSource } = await import("./mock");
    return new MockSource();
  }
  return new GatewayClient("");
}

export type { JaegerSource } from "./source";
export * from "./types";
