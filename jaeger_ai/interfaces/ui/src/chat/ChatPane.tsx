import type { Agent } from "../api/types";
/* Mount point for the chat pane. Swap `mount` for the shared widget's
 * mount(el, host, opts) => dispose when packages/jaeger-chat-ui lands. */
import { useEffect, useLayoutEffect, useRef } from "react";
import type { ChatHost, ChatPaneMount } from "./host";
import { mountMinimalChat } from "./mountMinimal";

export function ChatPane({ host, sessionId, topicId, agents, onAvatarState, onSessionMissing, mount = mountMinimalChat }: { host: ChatHost; sessionId?: string; topicId?: string | null; agents?: Agent[]; onAvatarState?: (state: import("../avatar/avatar").ClipState) => void; onSessionMissing?: (sessionId: string) => void; mount?: ChatPaneMount }) {
  const el = useRef<HTMLDivElement>(null);
  const mounted = useRef<ReturnType<ChatPaneMount> | null>(null);
  const callbacks = useRef({ onAvatarState, onSessionMissing });
  const reportsAvatar = Boolean(onAvatarState);
  const recoversMissingSession = Boolean(onSessionMissing);
  useLayoutEffect(() => {
    callbacks.current = { onAvatarState, onSessionMissing };
  }, [onAvatarState, onSessionMissing]);

  useEffect(() => {
    if (!el.current) return;
    // A fresh child per mount, so a widget never shares a node with the one it replaces.
    const child = document.createElement("div");
    child.className = "jg-chat-mount__inner";
    el.current.appendChild(child);
    // Shell refreshes may replace handlers without changing the active chat.
    // Replacing the widget would also replace the focused composer and stream listener.
    const dispose = mount(child, host, {
      sessionId,
      agents,
      onAvatarState: reportsAvatar ? (state) => callbacks.current.onAvatarState?.(state) : undefined,
      onSessionMissing: recoversMissingSession ? (id) => callbacks.current.onSessionMissing?.(id) : undefined,
    });
    mounted.current = dispose;
    return () => { mounted.current = null; queueMicrotask(() => { dispose(); child.remove(); }); };
  }, [host, sessionId, topicId, mount, reportsAvatar, recoversMissingSession]);
  useEffect(() => { if (agents) mounted.current?.updateAgents?.(agents); }, [agents]);
  return <div className="jg-chat-mount" ref={el} />;
}
