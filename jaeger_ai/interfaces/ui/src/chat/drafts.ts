/** Versioned device-local drafts; no execution authority or server credentials. */
import type { PendingFile } from "./composer";
export interface Draft { text: string; files: PendingFile[]; quote?: { turnId: string; text: string } }
const queues = new Map<string, Promise<void>>();
const open = () => new Promise<IDBDatabase>((resolve, reject) => {
  const request = indexedDB.open("jaeger.ui.drafts", 1);
  request.onupgradeneeded = () => request.result.createObjectStore("drafts");
  request.onerror = () => reject(request.error);
  request.onsuccess = () => resolve(request.result);
});
export async function readDraft(sessionId: string): Promise<Draft> {
  await queues.get(sessionId);
  const db = await open();
  try {
    return await new Promise((resolve, reject) => {
      const tx = db.transaction("drafts", "readonly");
      const request = tx.objectStore("drafts").get(sessionId);
      request.onsuccess = () => {
        const value = request.result;
        if (value && (typeof value.text !== "string" || !Array.isArray(value.files))) { reject(new Error("Draft record is invalid; stored bytes preserved")); return; }
        resolve(value ?? { text: "", files: [] });
      };
      request.onerror = () => reject(request.error);
    });
  } finally { db.close(); }
}
export function writeDraft(sessionId: string, draft: Draft): Promise<void> {
  const prior = queues.get(sessionId) ?? Promise.resolve();
  const next = prior.catch(() => {}).then(async () => {
    const db = await open();
    try {
      await new Promise<void>((resolve, reject) => {
        const tx = db.transaction("drafts", "readwrite");
        tx.objectStore("drafts").put(draft, sessionId);
        tx.oncomplete = () => resolve();
        tx.onabort = tx.onerror = () => reject(tx.error ?? new Error("Draft could not be saved"));
      });
    } finally { db.close(); }
  });
  queues.set(sessionId, next);
  // Track pending writes only; no unbounded draft/body retention in memory.
  void next.finally(() => { if (queues.get(sessionId) === next) queues.delete(sessionId); }).catch(() => {});
  return next;
}
