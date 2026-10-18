/* Centered hand-off markers between turns, with inline avatars:
 *   "Message from (●) X" · "Messaged (●) X and (●) Y" · "N messages with (●) X"
 *   · 3+ recipients: "Messaged (●●●) [N]", the N chip lists "Agents in this exchange". */
import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";
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
  <span className="jg-handoff__who"><AgentAvatar id={ref.id} name={ref.name} size={18} /> <span className="jg-handoff__name">{ref.name}</span></span>
);

function people(refs: Ref[]): ReactNode {
  return refs.map((ref, i) => (
    <Fragment key={ref.id}>
      {i > 0 && <span>{i === refs.length - 1 ? "and" : ","}</span>}
      {who(ref)}
    </Fragment>
  ));
}

/** Avatar stack + count chip with a small menu of everyone in the exchange. */
export function RecipientStack({ refs, defaultOpen = false }: { refs: Ref[]; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const box = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: Event) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("pointerdown", away); document.removeEventListener("keydown", esc); };
  }, [open]);
  return (
    <span className="jg-handoff__group" ref={box}>
      <span className="jg-handoff__stack">{refs.slice(0, 3).map((r) => <AgentAvatar key={r.id} id={r.id} name={r.name} size={18} />)}</span>
      <button type="button" className="jg-handoff__count" aria-haspopup="true" aria-expanded={open}
        aria-label={`${refs.length} agents in this exchange`} onClick={(e) => { e.stopPropagation(); setOpen((o) => !o); }}>{refs.length}</button>
      {open && (
        <span className="jg-handoff__menu" role="dialog" aria-label="Agents in this exchange">
          <span className="jg-handoff__menu-title">Agents in this exchange</span>
          <ul>{refs.map((r) => <li key={r.id}><AgentAvatar id={r.id} name={r.name} size={18} /><span>{r.name}</span></li>)}</ul>
        </span>
      )}
    </span>
  );
}

export function HandoffMarker({ part, onOpen }: { part: HandoffPart; onOpen?: (handoffId: string) => void }) {
  const text = handoffText(part);
  if (part.direction === "to" && part.agents && part.agents.length >= 3) {
    // The count chip is its own button, so the marker can't be one too; opening the exchange stays on the word.
    return (
      <div className="jg-handoff" role="separator" aria-label={text}>
        <span className="jg-handoff__chip">
          {onOpen ? <button type="button" className="jg-handoff__open" onClick={() => onOpen(part.handoffId)}>Messaged</button> : <span>Messaged</span>}
          <RecipientStack refs={part.agents} />
        </span>
      </div>
    );
  }
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
