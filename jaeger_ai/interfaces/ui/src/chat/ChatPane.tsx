/* Mount point for the chat pane. Swap `mount` for the shared widget's
 * mount(el, host, opts) => dispose when packages/jaeger-chat-ui lands. */
import { useEffect, useRef } from "react";
import type { ChatHost, ChatPaneMount } from "./host";
import { mountMinimalChat } from "./mountMinimal";

export function ChatPane({ host, sessionId, mount = mountMinimalChat }: { host: ChatHost; sessionId?: string; mount?: ChatPaneMount }) {
  const el = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!el.current) return;
    // A fresh child per mount, so a widget never shares a node with the one it replaces.
    const child = document.createElement("div");
    child.className = "jg-chat-mount__inner";
    el.current.appendChild(child);
    const dispose = mount(child, host, { sessionId });
    return () => queueMicrotask(() => { dispose(); child.remove(); });
  }, [host, sessionId, mount]);
  return <div className="jg-chat-mount" ref={el} />;
}
