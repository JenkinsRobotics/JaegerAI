import type { ReactNode } from "react";
import { MenuButton, type MenuItem } from "./Menu";

export type PanelPlacement = "docked" | "floating" | "hidden";

export interface PanelPlacementMenuProps {
  label: string;
  placement: PanelPlacement;
  onChange: (placement: PanelPlacement) => void;
  className?: string;
  children?: ReactNode;
}

const placementItems = (placement: PanelPlacement): readonly MenuItem[] => [
  {
    id: "docked",
    label: "Dock",
    icon: "▦",
    kind: "radio",
    checked: placement === "docked",
  },
  {
    id: "floating",
    label: "Float",
    icon: "□",
    kind: "radio",
    checked: placement === "floating",
  },
  {
    id: "hidden",
    label: "Hide",
    icon: "−",
    kind: "radio",
    checked: placement === "hidden",
  },
];

/** Product-free panel placement control. Applications own persistence and
 * decide what each stable panel ID means. */
export function PanelPlacementMenu({
  label,
  placement,
  onChange,
  className,
  children = "•••",
}: PanelPlacementMenuProps) {
  return (
    <MenuButton
      className={className}
      label={`${label} placement`}
      items={placementItems(placement)}
      onSelect={(id) => onChange(id as PanelPlacement)}
    >
      {children}
    </MenuButton>
  );
}
