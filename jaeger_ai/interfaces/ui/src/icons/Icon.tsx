// Icons: VS Code codicons (MIT, microsoft/vscode d956e8a6, vendored font + LICENSE beside this file; copied from
// jaeger-chat's vendor/codicons). Glyph code points from codicon.css. Never Grok's or Antigravity's icons.
import "./codicons.css";

export const CODICON = {
  "search": 0xea6d,
  "settings-gear": 0xeb51,
  "copy": 0xebcc,
  "reply": 0xea7d,
  "link": 0xeb15,
  "eye-closed": 0xeae7,
  "pin": 0xeb2b,
  "pinned": 0xeba0,
  "check": 0xeab2,
  "close": 0xea76,
  "edit": 0xea73,
  "trash": 0xea81,
  "mail-read": 0xeb1b,
  "info": 0xea74,
  "history": 0xea82,
  "add": 0xea60,
  "attach": 0xec34,
  "mic": 0xec12,
  "account": 0xeb99,
  "color-mode": 0xeac6,
  "server": 0xeb50,
  "unmute": 0xeb75,
  "terminal": 0xea85,
  "question": 0xeb32,
  "chevron-right": 0xeab6,
  "person-add": 0xebcd,
  "file": 0xea7b,
  "globe": 0xeb01,
  "comment-discussion": 0xeac7,
  "symbol-color": 0xeb5c,
  "go-to-file": 0xea94,
  "arrow-up": 0xeaa1,
  "debug-stop": 0xead7,
  "smiley": 0xeb54,
  "thumbsup": 0xeb6c,
  "thumbsdown": 0xeb6b,
  "heart": 0xeb05,
  "rocket": 0xeb44,
  "eye": 0xea70,
  "pass": 0xeba4,
  "error": 0xea87,
  "warning": 0xea6c,
  "comment": 0xea6b,
  "ellipsis": 0xea7c,
  "arrow-right": 0xea9c,
  "checklist": 0xeab3,
  "chevron-down": 0xeab4,
  "chevron-left": 0xeab5,
  "star-full": 0xeb59,
} as const;
export type IconName = keyof typeof CODICON;

export function Icon({ name, size = 16, className = "", label }: { name: IconName; size?: number; className?: string; label?: string }) {
  return (
    <span className={`jg-icon ${className}`.trim()} style={{ fontSize: size }} role={label ? "img" : undefined}
      aria-label={label} aria-hidden={label ? undefined : true}>{String.fromCodePoint(CODICON[name])}</span>
  );
}
