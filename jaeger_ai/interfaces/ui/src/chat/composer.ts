/* Composer helpers (Jenkins Robotics, 2026-10-17, original): the primary button's morph, the attachment
 * caps and the auto-grow fallback for WebKit builds that ignore `field-sizing: content`. */
import type { HostAttachment } from "./hostH8";

export type Primary = "stop" | "send" | "voice" | "dictate";
/** Stop while a turn runs, Send once there is text or a file; on an empty composer, Start voice chat
 * when the host has it, else Dictate when it can only take speech-to-text, else a (disabled) Send.
 * The ghost mic beside it is dictation, shown only while voice chat holds the primary. */
export function primaryAction(o: { running: boolean; hasContent: boolean; voiceChat: boolean; dictation: boolean }): Primary {
  if (o.running) return "stop";
  if (o.hasContent) return "send";
  if (o.voiceChat) return "voice";
  if (o.dictation) return "dictate";
  return "send";
}

export const MAX_ATTACHMENTS = 8;
export const MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024;
/** `path`/`uri` when the host picker supplied a real file (H8); paste/drag files have neither. */
export interface PendingFile { id: string; name: string; size: number; type: string; path?: string; uri?: string; error?: string }

/** One file the host could not send with a turn, and the raw reason. */
export interface RejectedAttachment { name: string; path?: string; reason: string }

/** Chip wording for a refused attachment: plain language first, the raw reason only as a fallback. */
export function attachmentError(reason: string): string {
  if (/escapes workspace/i.test(reason)) return "Not sent: outside Jaeger's workspace";
  if (/no file path/i.test(reason)) return "Not sent: use + to attach it from disk";
  return `Not sent: ${reason}`;
}

/** Put refused files back in the composer as error chips (the turn itself still went). */
export function restoreRejected(current: PendingFile[], sent: PendingFile[], rejected: RejectedAttachment[]): PendingFile[] {
  const back = rejected.flatMap((r) => {
    const file = sent.find((f) => f.name === r.name && f.path === r.path);
    return file ? [{ ...file, error: attachmentError(r.reason) }] : [];
  });
  return [...current.filter((f) => !back.some((b) => b.id === f.id)), ...back];
}

/** Add picked or pasted files under the caps; says what was left out. */
export function addFiles(current: PendingFile[], incoming: Array<{ name: string; size: number; type: string; path?: string; uri?: string }>, makeId: () => string):
  { files: PendingFile[]; note?: string } {
  const files = [...current];
  let tooBig = 0, overCount = 0;
  for (const f of incoming) {
    if (f.size > MAX_ATTACHMENT_BYTES) { tooBig += 1; continue; }
    if (files.length >= MAX_ATTACHMENTS) { overCount += 1; continue; }
    files.push({ id: makeId(), name: f.name || "pasted file", size: f.size, type: f.type, ...(f.path ? { path: f.path, uri: f.uri } : {}) });
  }
  const notes = [
    tooBig ? `${tooBig} over ${MAX_ATTACHMENT_BYTES / 1024 / 1024} MB left out` : "",
    overCount ? `only ${MAX_ATTACHMENTS} files per message` : "",
  ].filter(Boolean);
  return { files, note: notes.length ? notes.join(" · ") : undefined };
}

export const toAttachments = (files: PendingFile[]): HostAttachment[] =>
  files.filter((f) => !f.error).map((f) => ({ name: f.name, mimeType: f.type || "application/octet-stream", size: f.size, ...(f.path ? { path: f.path, uri: f.uri } : {}) }));

/** A host-picked attachment as composer input (size 0 when the host left it out). */
export const fromHost = (a: HostAttachment) => ({ name: a.name, size: a.size ?? 0, type: a.mimeType, path: a.path, uri: a.uri });

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
