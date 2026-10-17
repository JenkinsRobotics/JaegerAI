/* Centered hand-off markers between turns:
 *   "Messaged X" · "Messaged X and Y" (grouped) · "N messages with X" · "Message from X" */
import type { ChatPart } from "../chat/host";

type HandoffPart = Extract<ChatPart, { kind: "handoff" }>;

const joinNames = (names: string[]) => (names.length <= 1 ? names[0] ?? "" : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`);

export function handoffText(part: HandoffPart): string {
  if (part.direction === "from") return `Message from ${part.agentName}`;
  if (part.agents && part.agents.length > 1) return `Messaged ${joinNames(part.agents.map((a) => a.name))}`;
  if (part.count > 1) return `${part.count} messages with ${part.agentName}`;
  return `Messaged ${part.agentName}`;
}

export function HandoffMarker({ part, onOpen }: { part: HandoffPart; onOpen?: (handoffId: string) => void }) {
  const text = handoffText(part);
  return (
    <div className="jg-handoff" role="separator" aria-label={text}>
      <span className="jg-handoff__rule" />
      {onOpen ? (
        <button type="button" className="jg-handoff__chip" onClick={() => onOpen(part.handoffId)}>{text}</button>
      ) : (
        <span className="jg-handoff__chip">{text}</span>
      )}
      <span className="jg-handoff__rule" />
    </div>
  );
}
