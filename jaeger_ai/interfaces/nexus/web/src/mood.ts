// What the face shows for an agent event: its feeling while it lasts, else what the agent is doing.
export function moodFor(e: { event?: string; text?: string }, feeling: string): string | null {
  if (e.event === 'feeling' && e.text) return e.text;
  if (e.event !== 'state') return null;
  return e.text === 'thinking' ? 'thinking' : e.text === 'hearing you' ? 'listening' : e.text === 'speaking' ? feeling : 'neutral';
}
