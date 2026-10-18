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
export interface PendingFile { id: string; name: string; size: number; type: string; path?: string; uri?: string; error?: string;
  /** The pasted or dropped file itself, kept for a bytes upload (no path to hand the gateway). */
  blob?: Blob;
  /** Its bytes as base64, read when the chip is added (bytes-upload flag only). */
  data?: string }

/** Bytes upload (gateway-side staging) is prepared but OFF until the gateway contract lands:
 * localStorage `jaeger.ui.bytes-upload` = "1" turns it on for testing. */
export const BYTES_UPLOAD_FLAG = "jaeger.ui.bytes-upload";
export function bytesUploadEnabled(): boolean {
  try { return localStorage.getItem(BYTES_UPLOAD_FLAG) === "1"; } catch { return false; }
}

/** A file's bytes as base64 (no data: prefix). */
export async function readBase64(blob: Blob): Promise<string> {
  const buffer = typeof blob.arrayBuffer === "function" ? await blob.arrayBuffer() : await new Promise<ArrayBuffer>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as ArrayBuffer);
    reader.onerror = () => reject(reader.error);
    reader.readAsArrayBuffer(blob);
  });
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}

/** toAttachments, plus `data` (base64) for path-less files when the bytes-upload flag is on. */
export async function withBytes(files: PendingFile[], enabled = bytesUploadEnabled()): Promise<HostAttachment[]> {
  const base = toAttachments(files);
  if (!enabled) return base;
  const sendable = files.filter((f) => !f.error);
  return Promise.all(base.map(async (a, i) => {
    const blob = sendable[i].blob;
    return a.path || a.data || !blob ? a : { ...a, data: await readBase64(blob) };
  }));
}

/** One file the host could not send with a turn, and the raw reason. */
export interface RejectedAttachment { name: string; path?: string; reason: string }

/** Chip wording for a refused attachment: plain language first, the raw reason only as a fallback. */
/** Bytes upload limit (gateway: 413 above it). */
export const UPLOAD_MAX_BYTES = 25 * 1024 * 1024;
export const UPLOAD_TOO_LARGE = "Too large (25 MB max)";

export function attachmentError(reason: string): string {
  if (/escapes workspace/i.test(reason)) return "Not sent: outside Jaeger's workspace";
  if (/no file path/i.test(reason)) return "Not sent: use + to attach it from disk";
  if (/too large|413/i.test(reason)) return UPLOAD_TOO_LARGE;
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
    files.push({ id: makeId(), name: f.name || "pasted file", size: f.size, type: f.type, ...(f.path ? { path: f.path, uri: f.uri } : {}),
      ...(!f.path && typeof Blob !== "undefined" && f instanceof Blob ? { blob: f } : {}) });
  }
  const notes = [
    tooBig ? `${tooBig} over ${MAX_ATTACHMENT_BYTES / 1024 / 1024} MB left out` : "",
    overCount ? `only ${MAX_ATTACHMENTS} files per message` : "",
  ].filter(Boolean);
  return { files, note: notes.length ? notes.join(" · ") : undefined };
}

export const toAttachments = (files: PendingFile[]): HostAttachment[] =>
  files.filter((f) => !f.error).map((f) => ({ name: f.name, mimeType: f.type || "application/octet-stream", size: f.size,
    ...(f.path ? { path: f.path, uri: f.uri } : f.data ? { data: f.data } : {}) }));

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
