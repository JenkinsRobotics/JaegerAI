/* NativeHost: ChatHost inside the macOS shell (?host=macos). Data still flows
 * through the same-origin gateway proxy (WebHost). OS actions go through
 * window.jaegerNative, with web fallbacks when the bridge is absent. */
import type { JaegerSource } from "../api/source";
import { nativeBridge, onNativeEvent, postNative, probeVoice } from "../platform/native";
import type { HostKind } from "./host";
import { WebHost } from "./webHost";

/** Shell voice: dictation in, speech out. Only the macOS shell provides it. */
export interface VoiceHost {
  micStart(): Promise<void>;
  micStop(): Promise<string>;
  speak(text: string): void;
  stopSpeaking(): void;
}

export class NativeHost extends WebHost implements VoiceHost {
  override readonly kind: HostKind = "native";

  constructor(source: JaegerSource) { super(source); }

  /** Voice needs a shell mic and tts that are not not_implemented. */
  async probeCapabilities() {
    this.capabilities = { voice: await probeVoice() };
    return this.capabilities;
  }

  /** Dictation: start recording, or stop and resolve with the transcript. */
  async micStart() { await postNative("mic.start", { mode: "dictation" }); }
  micStop(): Promise<string> {
    return new Promise((resolve) => {
      const off = onNativeEvent((detail) => {
        const d = detail as { type: string; text?: string; final?: boolean };
        if (d.type === "voice.transcript" && d.final !== false) { off(); resolve(d.text ?? ""); }
        else if (d.type === "voice.error") { off(); resolve(""); }
      });
      void postNative("mic.stop").then((reply) => { if (reply === undefined) { off(); resolve(""); } });
    });
  }
  speak(text: string) { if (text.trim()) void postNative("tts.speak", { text }); }
  stopSpeaking() { void postNative("tts.stop"); }

  override openExternal(url: string) {
    if (nativeBridge()) void postNative("open.external", { url });
    else super.openExternal(url);
  }
  openFile(path: string) { void postNative("open.file", { path }); }
  override async copy(text: string) {
    if (nativeBridge()) await postNative("clipboard.write", { text });
    else await super.copy(text);
  }
  onThemeChanged(cb: () => void) {
    return onNativeEvent((detail) => { if (detail.type === "appearance.changed") cb(); });
  }
}
