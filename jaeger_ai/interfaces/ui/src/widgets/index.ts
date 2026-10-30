/** Public surface of the widget platform. Hosts import from here only. */
export type {
  WidgetDef,
  WidgetHost,
  WidgetSize,
  WidgetTint,
  WidgetRenderArgs,
  ConfigField,
  GridItem,
  DashboardDoc,
  AnyWidgetDef,
} from "./types";
export {
  registerWidget,
  registerWidgets,
  allWidgets,
  widgetByKind,
  widgetsForHost,
  pickSize,
  isRetired,
} from "./registry";
export { useWidget, type WidgetState } from "./useWidget";
export { WidgetFrame, observedLabel } from "./primitives/WidgetFrame";
export { Sparkline } from "./primitives/Sparkline";
export { Skeleton, SkeletonStat } from "./primitives/Skeleton";
