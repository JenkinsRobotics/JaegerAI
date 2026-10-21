/* NativeHost: ChatHost inside the macOS shell (?host=macos). Data still flows
 * through the same-origin gateway proxy (WebHost). OS actions go through
 * window.jaegerNative, with web fallbacks when the bridge is absent. */
import type { JaegerSource } from "../api/source";
import { nativeBridge, onNativeEvent, postNative, probeSpeech } from "../platform/native";
import type { HostAttachment, HostCapabilities, PickFilesHost, PickFilesOptions } from "./hostH8";
import type { HostKind } from "./host";
import { WebHost } from "./webHost";

/** Shell voice: dictation in, speech out. Only the macOS shell provides it. */
export interface VoiceHost {
  probeCapabilities(): Promise<HostCapabilities>;
  micStart(): Promise<void>;
  micStop(): Promise<string>;
  speak(text: string): void;
  stopSpeaking(): void;
}

export class NativeHost extends WebHost implements VoiceHost, PickFilesHost {
  override readonly kind: HostKind = "native";
  override capabilities: HostCapabilities = { voice: false, pickFiles: Boolean(nativeBridge()) };

  constructor(source: JaegerSource) { super(source); }

  /** Dictation and voice chat are separate: a Mac with a mic but no voices can still dictate. */
  async probeCapabilities() {
    const { dictation, voiceChat } = await probeSpeech();
    this.capabilities = { voice: dictation || voiceChat, dictation, voiceChat, pickFiles: Boolean(nativeBridge()) };
    return this.capabilities;
  }

  /** H8 pickFiles: the shell's NSOpenPanel (files.pick). [] on cancel; rejects when the shell can't. */
  async pickFiles(options: PickFilesOptions): Promise<HostAttachment[]> {
    const bridge = nativeBridge();
    if (!bridge) throw new Error("no native bridge");
    const reply = (await bridge.post("files.pick", options)) as { files?: HostAttachment[] } | undefined;
    return (reply?.files ?? []).map((f) => ({ name: f.name, mimeType: f.mimeType, path: f.path, uri: f.uri, size: f.size }));
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
    const bridge=nativeBridge();
    if(bridge){const receipt=await bridge.post("clipboard.write",{text}) as {copied?:boolean};if(receipt?.copied!==true)throw Error("Native clipboard write unconfirmed; no automatic retry");}
    else await super.copy(text);
  }
  onThemeChanged(cb: () => void) {
    return onNativeEvent((detail) => { if (detail.type === "appearance.changed") cb(); });
  }
}
