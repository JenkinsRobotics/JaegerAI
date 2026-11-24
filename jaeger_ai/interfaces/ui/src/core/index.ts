/**
 * ui-core public barrel: Gateway source adapters, event projection,
 * capability gating, and shared host-neutral primitives.
 */
export { CapabilityGate, type CapabilityGateProps } from "./CapabilityGate";
export { evaluateCapabilities, type CapabilityEvaluation, type UiCapabilityKey } from "../contracts";
export { applyPart, isSessionMissingError } from "../chat/host";
export { createSource } from "../api";
export { GatewayClient } from "../api/gateway";
