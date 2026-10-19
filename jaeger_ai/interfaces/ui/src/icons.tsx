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
export const WaveIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base} {...p}><path d="M3 6.5v3M5.5 4.5v7M8 3v10M10.5 5v6M13 6.5v3" /></svg>;
/** Neutral app glyphs for the Connect apps pill (D11: no vendor logos yet). */
export const GlyphCode = (p: SVGProps<SVGSVGElement>) => <svg {...base} {...p}><path d="m6 4.5-3.5 3.5L6 11.5M10 4.5l3.5 3.5-3.5 3.5" /></svg>;
export const GlyphBranch = (p: SVGProps<SVGSVGElement>) => <svg {...base} {...p}><circle cx="5" cy="3.5" r="1.5" /><circle cx="5" cy="12.5" r="1.5" /><circle cx="11" cy="6" r="1.5" /><path d="M5 5v6M11 7.5c0 2-2 2.5-6 3.5" /></svg>;
export const GlyphCube = (p: SVGProps<SVGSVGElement>) => <svg {...base} {...p}><path d="M8 2 13.5 5v6L8 14 2.5 11V5zM2.5 5 8 8l5.5-3M8 8v6" /></svg>;
