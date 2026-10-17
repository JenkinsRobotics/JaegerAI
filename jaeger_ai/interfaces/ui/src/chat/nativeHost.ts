/* NativeHost: ChatHost inside the macOS shell (?host=macos). Data still flows
 * through the same-origin gateway proxy (WebHost). OS actions go through
 * window.jaegerNative, with web fallbacks when the bridge is absent. */
import type { JaegerSource } from "../api/source";
import { nativeBridge, onNativeEvent, postNative, probeVoice } from "../platform/native";
import type { HostKind } from "./host";
import { WebHost } from "./webHost";

export class NativeHost extends WebHost {
  override readonly kind: HostKind = "native";

  constructor(source: JaegerSource) { super(source); }

  /** Voice needs the flag AND a mic/tts that is not not_implemented. */
  async probeCapabilities(voiceFlag: boolean) {
    this.capabilities = { voice: voiceFlag && (await probeVoice()) };
    return this.capabilities;
  }

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
