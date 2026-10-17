// Aether UI — one widget per file, importable like a class.
// Product-free by rule: widgets take data and emit events; they never
// name a product concept or call an engine verb.
export { Button, type ButtonProps } from "./Button";
export { IconButton, type IconButtonProps } from "./IconButton";
export { AetherIcon, registerIconPack, aetherIconNames, type AetherIconName, type AetherIconProps } from "./AetherIcon";
export { Ribbon, RibbonGroup, RibbonTool, type RibbonToolProps } from "./Ribbon";
export { Rail, RailButton, type RailProps, type RailButtonProps } from "./Rail";
export { Tabs, type TabDefinition, type TabsProps } from "./Tabs";
export { Tree, type TreeNode, type TreeProps } from "./Tree";
export { DockPanel, type DockPanelProps } from "./DockPanel";
export { PanelHeading } from "./PanelHeading";
export { TextField, type TextFieldProps } from "./TextField";
export {
  SearchField,
  type SearchFieldProps,
  type SearchFieldScope,
} from "./SearchField";
export {
  Breadcrumbs,
  type BreadcrumbItem,
  type BreadcrumbsProps,
} from "./Breadcrumbs";
export { Dialog, type DialogProps } from "./Dialog";
export { StatusBar, StatusDot, type StatusKind } from "./StatusBar";
// Jaeger vendor copy: ViewportCanvas / ViewportNavigationCube (three.js, CAD-only) removed.
export {
  WorkspaceShell,
  FloatingPanel,
  LayoutPresetButton,
  nextLayoutPreset,
  type LayoutPreset,
  type WorkspaceFloatingPosition,
  type WorkspacePanel,
  type WorkspacePanelPresentation,
  type WorkspacePanelState,
  type WorkspaceShellProps,
  type FloatingPanelProps,
} from "./WorkspaceShell";
export { StudioModeButton, WorkspaceWindowMenu, AppearanceToggle, setAetherTheme, activeAetherTheme, installAetherTheme, type AetherThemeManifest, type AppearanceMode } from "./StudioChrome";
export { CollapsibleSidebar, SidebarLabel, SidebarToggle } from "./CollapsibleSidebar";
export { DocumentBar, type DocumentBarProps } from "./DocumentBar";
export { Timeline, type TimelineProps, type TimelineTrack } from "./Timeline";
export {
  Menu,
  MenuButton,
  type MenuItem,
  type MenuItemKind,
  type MenuProps,
  type MenuButtonProps,
} from "./Menu";
export { Popover, type PopoverProps } from "./Popover";
export {
  PanelPlacementMenu,
  type PanelPlacement,
  type PanelPlacementMenuProps,
} from "./PanelPlacementMenu";
export type {
  OverlayAnchor,
  OverlayPlacement,
  OverlayPoint,
} from "./overlay-position";
export { NumberField, type NumberFieldProps } from "./NumberField";
export {
  SelectField,
  type SelectFieldOption,
  type SelectFieldProps,
} from "./SelectField";
export { Checkbox, type CheckboxProps } from "./Checkbox";
export {
  RadioGroup,
  type RadioGroupOption,
  type RadioGroupProps,
} from "./RadioGroup";
export {
  SegmentedControl,
  type SegmentedControlOption,
  type SegmentedControlProps,
} from "./SegmentedControl";
export { Slider, type SliderProps } from "./Slider";
export { ColorField, type ColorFieldProps } from "./ColorField";
export { FileField, type FileFieldProps } from "./FileField";
export {
  CommandPalette,
  type CommandPaletteArgument,
  type CommandPaletteCommand,
  type CommandPaletteProps,
} from "./CommandPalette";
export {
  DocumentTabs,
  type DocumentTab,
  type DocumentSplitDirection,
  type DocumentTabsProps,
} from "./DocumentTabs";
export {
  ToastStack,
  type NotificationItem,
  type NotificationKind,
  type ToastStackProps,
} from "./Toast";
export {
  NotificationCenter,
  type NotificationCenterProps,
} from "./NotificationCenter";
export { FieldRow, type FieldRowProps } from "./FieldRow";
export { parseNumberExpression } from "./number-expression";
export { Tooltip, type TooltipProps } from "./Tooltip";
export { EmptyState, type EmptyStateProps } from "./EmptyState";
export { ErrorState, type ErrorStateProps } from "./ErrorState";
export { ProgressOverlay, type ProgressOverlayProps } from "./ProgressOverlay";
export { ListBox, type ListBoxItem, type ListBoxProps } from "./ListBox";
export {
  DataTable,
  type DataTableColumn,
  type DataTableProps,
  type DataTableRowAction,
  type DataTableSort,
} from "./DataTable";
export {
  PropertyGrid,
  type PropertyGridItem,
  type PropertyGridProps,
  type PropertyGridSection,
} from "./PropertyGrid";
export { SplitPane, type SplitPaneProps } from "./SplitPane";
export {
  BottomPanel,
  type BottomPanelProps,
  type BottomPanelTab,
} from "./BottomPanel";

export { AppIcon } from "./AppIcon";

export { ToolIcon, toolIconNames, type ToolIconName, type ToolIconProps } from "./ToolIcon";
export { openFeatureWindow, type FeatureWindow, type FeatureWindowOptions } from "./FeatureWindow";
export { SettingsWindow, SettingsCard, SettingsRow, type SettingsPane, type SettingsSection, type SettingsWindowProps } from "./SettingsWindow";
