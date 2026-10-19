/* Local mirror of the frozen IDE Chat H8 host additions (pickFiles + richer attachments). host.ts is
 * IDE Chat's file and stays untouched; when their commit is vendored, delete this file and import the
 * same names from ./host. `dictation` / `voiceChat` are PROPOSED (this lane), not in H8 yet. */
import type { ChatAttachment, ChatHost } from "./host";

/** H8 ChatAttachment: picked files carry an absolute `path` (+ `uri` file://) and `size` in bytes;
 * `data` (base64) is for paste/drag only. */
export interface HostAttachment extends ChatAttachment { path?: string; size?: number }

export interface PickFilesOptions { multiple?: boolean; maxFiles?: number; maxBytes?: number; accept?: string[] }

export interface HostCapabilities {
  voice: boolean;
  /** H8: the host can show a native file picker (host.pickFiles). */
  pickFiles?: boolean;
  /** PROPOSED: speech-to-text into the composer (the mic). */
  dictation?: boolean;
  /** PROPOSED: hands-free voice chat (the primary voice button). */
  voiceChat?: boolean;
}

export interface PickFilesHost {
  /** [] on cancel; rejects only on real errors. */
  pickFiles?(options: PickFilesOptions): Promise<HostAttachment[]>;
}

export const capabilitiesOf = (host: ChatHost): HostCapabilities => host.capabilities as HostCapabilities;

export function filePicker(host: ChatHost): ((options: PickFilesOptions) => Promise<HostAttachment[]>) | undefined {
  const pick = (host as ChatHost & PickFilesHost).pickFiles;
  return capabilitiesOf(host).pickFiles && pick ? pick.bind(host) : undefined;
}
