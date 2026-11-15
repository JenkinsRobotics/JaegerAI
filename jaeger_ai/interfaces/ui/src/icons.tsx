/* Glyphs the Aether icon set lacks (send, stop, mic, attach, star). The
 * stroke uses currentColor, so color comes from the CSS tokens. */
import type { SVGProps } from "react";

const base = { width: 16, height: 16, viewBox: "0 0 16 16", fill: "none", stroke: "currentColor", strokeWidth: 1.6, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": true } as const;

export const SendIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base} {...p}><path d="M8 13V3M3.5 7.5 8 3l4.5 4.5" /></svg>;
export const StopIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base} {...p}><rect x="4.5" y="4.5" width="7" height="7" rx="1.2" fill="currentColor" stroke="none" /></svg>;
export const MicIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base} {...p}><rect x="6" y="2" width="4" height="8" rx="2" /><path d="M3.5 7.5a4.5 4.5 0 0 0 9 0M8 12v2" /></svg>;
export const PlusIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base} {...p}><path d="M8 3v10M3 8h10" /></svg>;
/** Sidebar toggle: a window outline with the sidebar's divider (drawn for Jaeger). */
export const SidebarIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base} {...p}><rect x="1.8" y="3.4" width="12.4" height="9.2" rx="2" /><path d="M5.9 3.6v8.8" /></svg>;
export const SearchIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base} {...p}><circle cx="7" cy="7" r="4.2" /><path d="m10.2 10.2 3.3 3.3" /></svg>;
export const StarIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base} viewBox="0 0 16 16" {...p}><path d="m8 1.8 1.9 3.9 4.3.6-3.1 3 .7 4.3L8 11.6l-3.8 2 .7-4.3-3.1-3 4.3-.6z" fill="currentColor" stroke="none" /></svg>;
export const TasksIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base} {...p}><rect x="2.5" y="2.5" width="11" height="11" rx="2.2" /><path d="m5.2 8 1.9 1.9 3.7-3.8" /></svg>;
export const AppsIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base} {...p}><rect x="2.5" y="2.5" width="4.5" height="4.5" rx="1.2" /><rect x="9" y="2.5" width="4.5" height="4.5" rx="1.2" /><rect x="2.5" y="9" width="4.5" height="4.5" rx="1.2" /><path d="M11.25 9.2v4.1M9.2 11.25h4.1" /></svg>;
export const ArrowDownIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base} {...p}><path d="M8 3v10M3.5 8.5 8 13l4.5-4.5" /></svg>;
export const ChevronIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base} {...p}><path d="m6 4 4 4-4 4" /></svg>;
export const CloseIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base} {...p}><path d="m4.5 4.5 7 7M11.5 4.5l-7 7" /></svg>;
export const CameraIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base} {...p}><rect x="1.8" y="4.2" width="9" height="7.6" rx="1.6" /><path d="m10.8 7 3.4-2v6l-3.4-2" /></svg>;
export const ScreenIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base} {...p}><rect x="1.8" y="2.6" width="12.4" height="8.6" rx="1.4" /><path d="M5.5 13.6h5M8 11.2v2.4" /></svg>;
export const UndoIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base} {...p}><path d="M4.5 3 2 5.5 4.5 8" /><path d="M2.2 5.5h7.3a4 4 0 0 1 0 8H6" /></svg>;
export const WaveIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base} {...p}><path d="M3 6.5v3M5.5 4.5v7M8 3v10M10.5 5v6M13 6.5v3" /></svg>;
export const GearIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base} {...p}><circle cx="8" cy="8" r="2.2" /><path d="M8 1.8v1.6M8 12.6v1.6M1.8 8h1.6M12.6 8h1.6M3.6 3.6l1.1 1.1M11.3 11.3l1.1 1.1M3.6 12.4l1.1-1.1M11.3 4.7l1.1-1.1" /></svg>;
export const ExpandIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base} {...p}><path d="M9.5 2.5h4v4M6.5 13.5h-4v-4M13.5 2.5 9 7M2.5 13.5 7 9" /></svg>;
export const CollapseIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base} {...p}><path d="M13 7H9V3M3 9h4v4M9 7l4.5-4.5M7 9l-4.5 4.5" /></svg>;
export const HangUpIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base} {...p}><path d="M1.8 9.6c3.6-3.3 8.8-3.3 12.4 0l-1.6 2-2.6-1.1V8.6a8 8 0 0 0-3.9 0v1.9l-2.6 1.1z" fill="currentColor" stroke="none" /></svg>;
/** Neutral app glyphs for the Connect apps pill (D11: no vendor logos yet). */
export const GlyphCode = (p: SVGProps<SVGSVGElement>) => <svg {...base} {...p}><path d="m6 4.5-3.5 3.5L6 11.5M10 4.5l3.5 3.5-3.5 3.5" /></svg>;
export const GlyphBranch = (p: SVGProps<SVGSVGElement>) => <svg {...base} {...p}><circle cx="5" cy="3.5" r="1.5" /><circle cx="5" cy="12.5" r="1.5" /><circle cx="11" cy="6" r="1.5" /><path d="M5 5v6M11 7.5c0 2-2 2.5-6 3.5" /></svg>;
export const GlyphCube = (p: SVGProps<SVGSVGElement>) => <svg {...base} {...p}><path d="M8 2 13.5 5v6L8 14 2.5 11V5zM2.5 5 8 8l5.5-3M8 8v6" /></svg>;
export const GrokIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base} {...p}><rect x="2" y="2" width="12" height="12" rx="2" /><path d="M2 6h12M6 6v8" /></svg>;
export const CpuIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base} {...p}><rect x="3.5" y="3.5" width="9" height="9" rx="1.5" /><path d="M6 6h4v4H6zM6 1.5v2M10 1.5v2M6 12.5v2M10 12.5v2M1.5 6h2M1.5 10h2M12.5 6h2M12.5 10h2" /></svg>;
export const SharePointIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base} {...p}><path d="M12 7.5a3.5 3.5 0 0 0-6.8-1.1A2.5 2.5 0 0 0 3 8.8a2.5 2.5 0 0 0 2.5 2.7h6.7a2.8 2.8 0 0 0 0-5.5z" /></svg>;
