/**
 * ui-hosts: Host-neutral adapter seam for WebUI, VS Code, and macOS shells.
 *
 * Each host provides transport/window bindings via ChatHost and mounts the
 * same shared UI features through ChatPaneMount. No host owns a separate
 * agent runtime, memory store, or permission authority.
 */
import type { ChatHost, ChatPaneMount, ChatPaneOptions, HostKind } from "../contracts";

export type { ChatHost, ChatPaneMount, ChatPaneOptions, HostKind };

export interface UiHostCapabilities {
  readonly kind: HostKind;
  readonly voice: boolean;
  readonly openFile: boolean;
  readonly themeSync: boolean;
  readonly nativeWindow: boolean;
}

export function describeHostCapabilities(host: ChatHost): UiHostCapabilities {
  return {
    kind: host.kind,
    voice: Boolean(host.capabilities?.voice),
    openFile: typeof host.openFile === "function",
    themeSync: typeof host.onThemeChanged === "function",
    nativeWindow: host.kind === "native",
  };
}
