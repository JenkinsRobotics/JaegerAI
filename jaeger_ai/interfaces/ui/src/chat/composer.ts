/* Composer helpers (Jenkins Robotics, 2026-10-17, original): the primary button's morph, the attachment
 * caps and the auto-grow fallback for WebKit builds that ignore `field-sizing: content`. */
import type { ChatAttachment } from "./host";

export type Primary = "stop" | "send" | "voice";
/** Stop while a turn runs, Send once there is text or a file, else Start voice chat when the shell has voice.
 * Without voice the primary stays a (disabled) Send. Dictation is the ghost mic beside it. */
export function primaryAction(o: { running: boolean; hasContent: boolean; voice: boolean }): Primary {
  if (o.running) return "stop";
  if (o.hasContent || !o.voice) return "send";
  return "voice";
}

export const MAX_ATTACHMENTS = 8;
export const MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024;
export interface PendingFile { id: string; name: string; size: number; type: string }

/** Add picked or pasted files under the caps; says what was left out. */
export function addFiles(current: PendingFile[], incoming: Array<{ name: string; size: number; type: string }>, makeId: () => string):
  { files: PendingFile[]; note?: string } {
  const files = [...current];
  let tooBig = 0, overCount = 0;
  for (const f of incoming) {
    if (f.size > MAX_ATTACHMENT_BYTES) { tooBig += 1; continue; }
    if (files.length >= MAX_ATTACHMENTS) { overCount += 1; continue; }
    files.push({ id: makeId(), name: f.name || "pasted file", size: f.size, type: f.type });
  }
  const notes = [
    tooBig ? `${tooBig} over ${MAX_ATTACHMENT_BYTES / 1024 / 1024} MB left out` : "",
    overCount ? `only ${MAX_ATTACHMENTS} files per message` : "",
  ].filter(Boolean);
  return { files, note: notes.length ? notes.join(" · ") : undefined };
}

export const toAttachments = (files: PendingFile[]): ChatAttachment[] =>
  files.map((f) => ({ name: f.name, mimeType: f.type || "application/octet-stream" }));

export function fileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export const COMPOSER_MAX_PX = 200;
/** height = auto, then min(scrollHeight, 200): grows with the text, scrolls past 200 px. */
export function autoGrow(el: HTMLTextAreaElement | null) {
  if (!el) return;
  el.style.height = "auto";
  el.style.height = `${Math.min(el.scrollHeight, COMPOSER_MAX_PX)}px`;
  el.style.overflowY = el.scrollHeight > COMPOSER_MAX_PX ? "auto" : "hidden";
}
