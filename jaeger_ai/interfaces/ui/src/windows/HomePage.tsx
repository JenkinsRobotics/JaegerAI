/**
 * HomePage (Jenkins Robotics, 2026-10-29).
 *
 * The Home tab is a thin wrapper: it supplies the real `JaegerSource` and the
 * gateway-backed layout transport to the widget platform's page host. No data, no
 * layout and no widget knowledge lives here — that is the whole point of the split.
 */
import { useMemo } from "react";
import type { JaegerSource } from "../api/source";
import { PageHost } from "../widgets/host/PageHost";
import { gatewayLayoutTransport } from "../widgets/gatewayLayout";
import "../widgets/definitions"; // registers the widget kinds
import "../widgets/host/host.css";

export interface HomePageProps {
  source?: JaegerSource;
  onOpenWindow?: (id: string) => void;
  onStartChat?: (agentId?: string) => void;
}

export function HomePage({ source }: HomePageProps) {
  // One transport per mount; identity is stable so PageHost loads the layout once.
  const transport = useMemo(() => gatewayLayoutTransport(), []);
  return <PageHost source={source} transport={transport} />;
}

export default HomePage;
