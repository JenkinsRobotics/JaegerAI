/**
 * PlatformAdapter contract isolating browser, macOS native, and VS Code host capabilities.
 */

export type PlatformKind = "web" | "macos" | "vscode";

export interface PlatformAdapter {
  readonly kind: PlatformKind;
  readonly supportsVoice: boolean;
  readonly supportsNativeWindow: boolean;
  openFile?: (path: string, line?: number) => void;
  copyText?: (text: string) => Promise<void>;
  onThemeChanged?: (cb: (theme: "light" | "dark") => void) => () => void;
}
