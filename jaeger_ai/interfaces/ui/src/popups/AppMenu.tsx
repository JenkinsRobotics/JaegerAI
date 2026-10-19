import type { ComponentProps } from "react";
import { Menu } from "@aether/ui";
import { useExclusivePopup } from "./coordinator";

/** Aether Menu + the app popup coordinator (Escape, mousedown-outside, one open at a time). */
export function AppMenu(props: ComponentProps<typeof Menu>) {
  useExclusivePopup(props.open, props.onClose, props.anchor as Element | { x: number; y: number } | null);
  return <Menu {...props} />;
}
