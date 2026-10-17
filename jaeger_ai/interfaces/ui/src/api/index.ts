import { GatewayClient } from "./gateway";
import { MockSource } from "./mock";
import type { JaegerSource } from "./source";

/** ?mock=1 or VITE_JAEGER_MOCK=1 selects the typed mock adapter. */
export function mockRequested(search = typeof location === "undefined" ? "" : location.search): boolean {
  const flag = new URLSearchParams(search).get("mock");
  if (flag === "1" || flag === "true") return true;
  if (flag === "0" || flag === "false") return false;
  return import.meta.env.VITE_JAEGER_MOCK === "1";
}

export function createSource(): JaegerSource {
  return mockRequested() ? new MockSource() : new GatewayClient("");
}

export type { JaegerSource } from "./source";
export * from "./types";
