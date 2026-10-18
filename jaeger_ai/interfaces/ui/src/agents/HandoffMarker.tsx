/* Centered hand-off markers between turns, with inline avatars:
 *   "Message from (●) X" · "Messaged (●) X and (●) Y" · "N messages with (●) X" */
import { Fragment, type ReactNode } from "react";
import type { ChatPart } from "../chat/host";
import { AgentAvatar } from "./AgentAvatar";

type HandoffPart = Extract<ChatPart, { kind: "handoff" }>;
type Ref = { id: string; name: string };

const joinNames = (names: string[]) => (names.length <= 1 ? names[0] ?? "" : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`);

/** Plain-text form (aria-label, tests). */
export function handoffText(part: HandoffPart): string {
  if (part.direction === "from") return `Message from ${part.agentName}`;
  if (part.agents && part.agents.length > 1) return `Messaged ${joinNames(part.agents.map((a) => a.name))}`;
  if (part.count > 1) return `${part.count} messages with ${part.agentName}`;
  return `Messaged ${part.agentName}`;
}

const who = (ref: Ref) => (
  <span className="jg-handoff__who"><AgentAvatar id={ref.id} name={ref.name} size={14} /> <span className="jg-handoff__name">{ref.name}</span></span>
);

function people(refs: Ref[]): ReactNode {
  return refs.map((ref, i) => (
    <Fragment key={ref.id}>
      {i > 0 && <span>{i === refs.length - 1 ? "and" : ","}</span>}
      {who(ref)}
    </Fragment>
  ));
}

export function HandoffMarker({ part, onOpen }: { part: HandoffPart; onOpen?: (handoffId: string) => void }) {
  const text = handoffText(part);
  const self = { id: part.agentId, name: part.agentName };
  const content =
    part.direction === "from" ? <><span>Message from</span>{who(self)}</>
    : part.agents && part.agents.length > 1 ? <><span>Messaged</span>{people(part.agents)}</>
    : part.count > 1 ? <><span>{part.count} messages with</span>{who(self)}</>
    : <><span>Messaged</span>{who(self)}</>;
  return (
    <div className="jg-handoff" role="separator" aria-label={text}>
      {onOpen
        ? <button type="button" className="jg-handoff__chip" aria-label={text} onClick={() => onOpen(part.handoffId)}>{content}</button>
        : <span className="jg-handoff__chip">{content}</span>}
    </div>
  );
}
