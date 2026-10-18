import type { ImgHTMLAttributes } from "react";
import studio from "../../assets/branding/apps/studio.svg";
import cad from "../../assets/branding/apps/cad.svg";
import animation from "../../assets/branding/apps/animation.svg";
import ui from "../../assets/branding/apps/ui.svg";
const sources = { studio, cad, animation, ui };
/** Product identity artwork, separate from monochrome toolbar symbols. */
export function AppIcon({ app = "studio", size = 32, alt = "", style, ...props }: Omit<ImgHTMLAttributes<HTMLImageElement>, "src"> & { app?: string; size?: number }) {
  return <img src={sources[app as keyof typeof sources] ?? sources.studio} alt={alt} width={size} height={size} style={{ objectFit: "contain", flexShrink: 0, ...style }} {...props} />;
}
