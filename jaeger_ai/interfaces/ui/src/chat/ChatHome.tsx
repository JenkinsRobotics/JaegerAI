/* Empty-chat greeting: a short hello and a few things you can type, not a product map. */
import type { ReactNode } from "react";

export interface HomeChip { id: string; label: string; icon?: ReactNode; run: () => void }

const SUGGESTIONS = [
  { id: "plan", label: "Help me plan my day", prompt: "Help me plan my day." },
  { id: "files", label: "What's in this workspace?", prompt: "What files are in the current workspace?" },
  { id: "write", label: "Draft a short email", prompt: "Draft a short, clear email I can edit." },
  { id: "explain", label: "Explain a concept simply", prompt: "Explain a concept I choose in simple language." },
];

export const HOME_CHIPS = SUGGESTIONS;

export function ChatHome({ onSuggest, chips }: { onSuggest?: (prompt: string) => void; chips?: readonly HomeChip[]; portrait?: string }) {
  const items = chips?.length
    ? chips
    : SUGGESTIONS.map((item) => ({ id: item.id, label: item.label, run: () => onSuggest?.(item.prompt) }));
  return (
    <div className="jg-chat-home" data-testid="chat-home">
      <p className="jg-chat-home__hello">Hello</p>
      <p className="jg-chat-home__title">What should we work on?</p>
      <div className="jg-chat-home__chips" role="list" aria-label="Suggestions">
        {items.map((c) => (
          <button key={c.id} type="button" role="listitem" className="jg-chat-home__chip" onClick={c.run}>
            {c.label}
          </button>
        ))}
      </div>
    </div>
  );
}
