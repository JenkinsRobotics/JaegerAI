/* Chat home (2026-11-01): the new-chat state Jaeger opens to. A large faint Jaeger mark, a row of
 * quick-action chips (each one a real page or the ⌘K palette — nothing staged), then the shared
 * composer below. Styled entirely from tokens so Glass, Arc, Linear and Dia each restyle it. */
import type { ReactNode } from "react";
import { navigate } from "../shell/router";
import { JaegerAvatar } from "../avatar/JaegerAvatar";
import { JaegerMark } from "../brand/JaegerMark";
import { AppsIcon, SearchIcon, StarIcon, TasksIcon } from "../icons";

export interface HomeChip { id: string; label: string; icon: ReactNode; run: () => void }

/** Only actions that exist in Jaeger today: Backlog, the Hermes / OpenClaw agent pages, Research, Agents, ⌘K. */
export const HOME_CHIPS: readonly HomeChip[] = [
  { id: "work", label: "Put an Agent to Work", icon: <TasksIcon />, run: () => navigate("/work/backlog") },
  { id: "hermes", label: "Open Hermes", icon: <StarIcon />, run: () => navigate("/agents/hermes") },
  { id: "openclaw", label: "Open OpenClaw", icon: <StarIcon />, run: () => navigate("/agents/openclaw") },
  { id: "research", label: "Research", icon: <SearchIcon />, run: () => navigate("/research") },
  { id: "agents", label: "Browse Agents", icon: <AppsIcon />, run: () => navigate("/agents") },
  { id: "search", label: "Search or Jump", icon: <SearchIcon />, run: () => dispatchEvent(new Event("jaeger:palette")) },
];

export function ChatHome({ chips = HOME_CHIPS, portrait }: { chips?: readonly HomeChip[]; portrait?: string }) {
  return (
    <div className="jg-chat-home" data-testid="chat-home">
      <div className="jg-chat-home__avatar"><JaegerAvatar portraitOverride={portrait} state="idle" /></div>
      <JaegerMark className="jg-chat-home__mark" />
      <p className="jg-chat-home__title">What should we work on?</p>
      <div className="jg-chat-home__chips" role="list" aria-label="Quick actions">
        {chips.map((c) => (
          <button key={c.id} type="button" role="listitem" className="jg-chat-home__chip" onClick={c.run}>
            <span className="jg-chat-home__chip-icon" aria-hidden="true">{c.icon}</span>{c.label}
          </button>
        ))}
      </div>
    </div>
  );
}
