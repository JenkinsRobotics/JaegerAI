import { createRoot } from "react-dom/client";
import type { ChatPaneMount } from "./host";
import { MinimalChat } from "./MinimalChat";

/** ChatPaneMount for the stand-in renderer. Uses its own React root, exactly
 * like a framework-free widget would own `el`. */
export const mountMinimalChat: ChatPaneMount = (el, host, opts) => {
  const root = createRoot(el);
  const render = (agents = opts.agents) => root.render(<MinimalChat host={host} sessionId={opts.sessionId} agents={agents} />);
  render();
  return Object.assign(() => root.unmount(), { updateAgents: render });
};
