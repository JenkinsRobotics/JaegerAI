/**
 * WidgetSlot (Jenkins Robotics, 2026-10-29, original).
 *
 * Binds one grid cell to one widget definition: runs the loader, then hands the data
 * to WidgetFrame + the widget's own view(). This is the only place the state machine
 * and the frame meet, so a host cannot bypass the loading/error contract.
 */
import type { JaegerSource } from "../../api/source";
import { useWidget } from "../useWidget";
import { WidgetFrame } from "../primitives/WidgetFrame";
import type { WidgetDef, WidgetHost, WidgetSize, WidgetTint } from "../types";

export interface WidgetSlotProps {
  def: WidgetDef<unknown, unknown>;
  source?: JaegerSource;
  size: WidgetSize;
  tint: WidgetTint;
  host: WidgetHost;
  params?: unknown;
  /** Host-supplied chrome: the edit-mode remove button. */
  actions?: React.ReactNode;
}

export function WidgetSlot({ def, source, size, tint, host, params, actions }: WidgetSlotProps) {
  const state = useWidget(def, source, params);

  return (
    <WidgetFrame
      title={def.title}
      size={size}
      tint={tint}
      status={state.status}
      error={state.status === "error" ? state.error : undefined}
      observedAt={state.status === "ready" ? state.observedAt : undefined}
      onRetry={state.reload}
      actions={actions}
    >
      {state.status === "ready" &&
        def.view({
          data: state.data,
          size,
          tint,
          host,
          params,
          observedAt: state.observedAt,
          reload: state.reload,
        })}
    </WidgetFrame>
  );
}
