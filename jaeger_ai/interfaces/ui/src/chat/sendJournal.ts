/** Device-scoped immutable intent. Gateway remains the sole execution owner.
 * Versioned keys do not migrate or overwrite old transcript storage. A bad or
 * full store fails before dispatch; unknown entries are never deleted/replayed.
 */
export interface SendIntent {
  version: 1; deviceDraft?: boolean; sessionId: string; requestId: string; text: string;
  draftBody?: string; quoteKey?: string;
  attachmentIds: string[]; draftFileIds?: string[]; phase: "preparing" | "submitting" | "accepted" | "unknown";
}
const key = (session: string) => `jaeger.ui.send.v1.${encodeURIComponent(session)}`;
export function readIntent(session: string): SendIntent | undefined {
  const raw = localStorage.getItem(key(session));
  if (!raw) return;
  const value = JSON.parse(raw) as SendIntent;
  if (value.version !== 1 || value.sessionId !== session || typeof value.requestId !== "string" || typeof value.text !== "string" || !Array.isArray(value.attachmentIds)) throw new Error("Saved request needs reconciliation; its journal was preserved");
  return value;
}
export function saveIntent(intent: SendIntent) { localStorage.setItem(key(intent.sessionId), JSON.stringify(intent)); }
export function settleIntent(session: string, requestId: string) {
  if (readIntent(session)?.requestId === requestId) localStorage.removeItem(key(session));
}
