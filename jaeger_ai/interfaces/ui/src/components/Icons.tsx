/**
 * Icons — Lightweight SVG icon system
 *
 * Self-contained SVG icons matching Apple SF Symbols aesthetic.
 * No external dependencies required.
 *
 * Usage:
 *   import { Send, Mic, Paperclip } from './components/Icons'
 *
 *   <Send size={20} />
 *   <Mic size={24} className="text-blue-500" />
 */

import type { SVGProps } from 'react'

interface IconProps extends SVGProps<SVGSVGElement> {
  size?: number | string
  strokeWidth?: number
}

const baseProps = {
  fill: 'none',
  stroke: 'currentColor',
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
  viewBox: '0 0 24 24',
}

function createIcon(path: React.ReactNode, displayName: string) {
  const Icon = ({ size = 24, strokeWidth = 2, className = '', style, ...props }: IconProps) => (
    <svg
      {...baseProps}
      width={size}
      height={size}
      strokeWidth={strokeWidth}
      className={className}
      style={style}
      aria-hidden="true"
      {...props}
    >
      {path}
    </svg>
  )
  Icon.displayName = displayName
  return Icon
}

// ─────────────────────────────────────────────────────────────
// Chat Icons
// ─────────────────────────────────────────────────────────────

export const Send = createIcon(
  <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z" />,
  'Send'
)

export const Stop = createIcon(
  <rect x="6" y="6" width="12" height="12" rx="2" />,
  'Stop'
)

export const Square = Stop // Alias

export const Mic = createIcon(
  <>
    <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z" />
    <path d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v3M8 22h8" />
  </>,
  'Mic'
)

export const MicOff = createIcon(
  <>
    <line x1="1" y1="1" x2="23" y2="23" />
    <path d="M9 9v3a3 3 0 0 0 5.12 2.12M15 9.34V5a3 3 0 0 0-5.94-.6" />
    <path d="M17 16.95A7 7 0 0 1 5 12v-2m14 0v2a7 7 0 0 1-.11 1.23M12 19v3M8 22h8" />
  </>,
  'MicOff'
)

export const Paperclip = createIcon(
  <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />,
  'Paperclip'
)

// ─────────────────────────────────────────────────────────────
// Navigation Icons
// ─────────────────────────────────────────────────────────────

export const Search = createIcon(
  <>
    <circle cx="11" cy="11" r="8" />
    <path d="M21 21l-4.35-4.35" />
  </>,
  'Search'
)

export const Plus = createIcon(
  <>
    <line x1="12" y1="5" x2="12" y2="19" />
    <line x1="5" y1="12" x2="19" y2="12" />
  </>,
  'Plus'
)

export const Settings = createIcon(
  <>
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
  </>,
  'Settings'
)

export const Menu = createIcon(
  <>
    <line x1="3" y1="6" x2="21" y2="6" />
    <line x1="3" y1="12" x2="21" y2="12" />
    <line x1="3" y1="18" x2="21" y2="18" />
  </>,
  'Menu'
)

export const X = createIcon(
  <>
    <line x1="18" y1="6" x2="6" y2="18" />
    <line x1="6" y1="6" x2="18" y2="18" />
  </>,
  'X'
)

export const ChevronLeft = createIcon(
  <path d="M15 18l-6-6 6-6" />,
  'ChevronLeft'
)

export const ChevronRight = createIcon(
  <path d="M9 18l6-6-6-6" />,
  'ChevronRight'
)

// ─────────────────────────────────────────────────────────────
// Action Icons
// ─────────────────────────────────────────────────────────────

export const Copy = createIcon(
  <>
    <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
  </>,
  'Copy'
)

export const Check = createIcon(
  <path d="M20 6L9 17l-5-5" />,
  'Check'
)

export const RefreshCw = createIcon(
  <>
    <polyline points="23 4 23 10 17 10" />
    <polyline points="1 20 1 14 7 14" />
    <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
  </>,
  'RefreshCw'
)

export const Trash2 = createIcon(
  <>
    <polyline points="3 6 5 6 21 6" />
    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
    <line x1="10" y1="11" x2="10" y2="17" />
    <line x1="14" y1="11" x2="14" y2="17" />
  </>,
  'Trash2'
)

export const Edit2 = createIcon(
  <path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z" />,
  'Edit2'
)

export const Share = createIcon(
  <>
    <path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8" />
    <polyline points="16 6 12 2 8 6" />
    <line x1="12" y1="2" x2="12" y2="15" />
  </>,
  'Share'
)

export const ThumbsUp = createIcon(
  <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3" />,
  'ThumbsUp'
)

export const ThumbsDown = createIcon(
  <path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h2.67A2.31 2.31 0 0 1 22 4v7a2.31 2.31 0 0 1-2.33 2H17" />,
  'ThumbsDown'
)

export const Volume2 = createIcon(
  <>
    <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
    <path d="M15.54 8.46a5 5 0 0 1 0 7.07M19.07 4.93a10 10 0 0 1 0 14.14" />
  </>,
  'Volume2'
)

// ─────────────────────────────────────────────────────────────
// Theme Icons
// ─────────────────────────────────────────────────────────────

export const Sun = createIcon(
  <>
    <circle cx="12" cy="12" r="5" />
    <line x1="12" y1="1" x2="12" y2="3" />
    <line x1="12" y1="21" x2="12" y2="23" />
    <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
    <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
    <line x1="1" y1="12" x2="3" y2="12" />
    <line x1="21" y1="12" x2="23" y2="12" />
    <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
    <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
  </>,
  'Sun'
)

export const Moon = createIcon(
  <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />,
  'Moon'
)

// ─────────────────────────────────────────────────────────────
// Status Icons
// ─────────────────────────────────────────────────────────────

export const Circle = createIcon(
  <circle cx="12" cy="12" r="10" />,
  'Circle'
)

export const Loader = createIcon(
  <>
    <line x1="12" y1="2" x2="12" y2="6" />
    <line x1="12" y1="18" x2="12" y2="22" />
    <line x1="4.93" y1="4.93" x2="7.76" y2="7.76" />
    <line x1="16.24" y1="16.24" x2="19.07" y2="19.07" />
    <line x1="2" y1="12" x2="6" y2="12" />
    <line x1="18" y1="12" x2="22" y2="12" />
    <line x1="4.93" y1="19.07" x2="7.76" y2="16.24" />
    <line x1="16.24" y1="7.76" x2="19.07" y2="4.93" />
  </>,
  'Loader'
)

// ─────────────────────────────────────────────────────────────
// Misc Icons
// ─────────────────────────────────────────────────────────────

export const Zap = createIcon(
  <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />,
  'Zap'
)

export const Clock = createIcon(
  <>
    <circle cx="12" cy="12" r="10" />
    <polyline points="12 6 12 12 16 14" />
  </>,
  'Clock'
)

export const Star = createIcon(
  <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />,
  'Star'
)

export const MessageSquare = createIcon(
  <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />,
  'MessageSquare'
)

export const MoreHorizontal = createIcon(
  <>
    <circle cx="12" cy="12" r="1" />
    <circle cx="19" cy="12" r="1" />
    <circle cx="5" cy="12" r="1" />
  </>,
  'MoreHorizontal'
)

// ─────────────────────────────────────────────────────────────
// Export all icons as a map for easy access
// ─────────────────────────────────────────────────────────────

export const Icons = {
  Send,
  Stop,
  Square,
  Mic,
  MicOff,
  Paperclip,
  Search,
  Plus,
  Settings,
  Menu,
  X,
  ChevronLeft,
  ChevronRight,
  Copy,
  Check,
  RefreshCw,
  Trash2,
  Edit2,
  Share,
  ThumbsUp,
  ThumbsDown,
  Volume2,
  Sun,
  Moon,
  Circle,
  Loader,
  Zap,
  Clock,
  Star,
  MessageSquare,
  MoreHorizontal,
}

// ─────────────────────────────────────────────────────────────
// Spinning loader animation
// ─────────────────────────────────────────────────────────────

export function Spinner({ size = 24, className = '' }: { size?: number; className?: string }) {
  return (
    <svg
      className={`spinner ${className}`}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{
        animation: 'spin 1s linear infinite',
      }}
    >
      <path d="M21 12a9 9 0 1 1-6.219-8.56" />
    </svg>
  )
}

export default Icons
