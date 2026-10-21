import type {ChatSession} from './host';
/** Snapshot content cannot settle a live/unknown request or erase loaded history. */
export function mergeSessionSnapshot(current: ChatSession | null, next: ChatSession): ChatSession {
  if (!current || current.id !== next.id) return next;
  const turns = new Map(current.turns.map(turn => [turn.turnId, turn]));
  for (const turn of next.turns) {
    const existing = turns.get(turn.turnId);
    if (!existing || !['pending','unknown'].includes(existing.state)) turns.set(turn.turnId, turn);
  }
  return {...next, turns:[...turns.values()].sort((a,b)=> (a.createdAt ?? 0)-(b.createdAt ?? 0))};
}
