/**
 * ui-core: Declarative Gateway capability gate for feature modules.
 *
 * Ensures unsupported features render an explicit unavailable state instead
 * of silently inventing fallback or mock data.
 */
import type { ReactNode } from "react";
import type { JaegerSource, UiCapabilityKey } from "../contracts";
import { evaluateCapabilities } from "../contracts";

export interface CapabilityGateProps {
  source: JaegerSource | null | undefined;
  requires: readonly UiCapabilityKey[];
  featureName: string;
  unavailable?: (missing: readonly UiCapabilityKey[]) => ReactNode;
  children: ReactNode;
}

export function CapabilityGate({
  source,
  requires,
  featureName,
  unavailable,
  children,
}: CapabilityGateProps) {
  const { supported, missing } = evaluateCapabilities(source, requires);
  if (supported) {
    return <>{children}</>;
  }
  if (unavailable) {
    return <>{unavailable(missing)}</>;
  }
  return (
    <section
      role="status"
      aria-label={`${featureName} unavailable`}
      data-testid="capability-unavailable"
      data-feature={featureName}
      data-missing={missing.join(",")}
      className="jaeger-capability-unavailable"
    >
      <h3>{featureName} unavailable</h3>
      <p>
        This Gateway connection does not advertise the required capabilities (
        <code>{missing.join(", ")}</code>).
      </p>
    </section>
  );
}
