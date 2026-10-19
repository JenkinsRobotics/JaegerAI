/* Native host bridge (macOS WKWebView shell, interfaces/macos-shell).
 * window.jaegerNative.post(type, payload) => Promise. The shell pushes
 * `jaeger:native` CustomEvents (window.visibility, hotkey). Every call is
 * guarded: in a plain browser jaegerNative is absent and nothing breaks. */

export interface JaegerNativeBridge {
  post(type: string, payload?: unknown): Promise<unknown>;
}

declare global {
  interface Window {
    jaegerNative?: JaegerNativeBridge;
  }
}

export interface NativeEventDetail {
  type: "window.visibility" | "hotkey" | string;
  payload?: unknown;
}

export const nativeBridge = (): JaegerNativeBridge | undefined =>
  typeof window !== "undefined" && typeof window.jaegerNative?.post === "function" ? window.jaegerNative : undefined;

export async function postNative<T = unknown>(type: string, payload?: unknown): Promise<T | undefined> {
  const bridge = nativeBridge();
  if (!bridge) return undefined;
  try {
    return (await bridge.post(type, payload)) as T;
  } catch (error) {
    // Optional host feature: report it, then let the caller fall back.
    console.warn(`jaegerNative.post(${type}) failed`, error);
    return undefined;
  }
}

const notImplemented = (reply: unknown) =>
  reply == null || (typeof reply === "object" && ((reply as { error?: string }).error === "not_implemented" || (reply as { status?: string }).status === "not_implemented"));

/** mic and tts count as available only when the shell answers with something
 * other than not_implemented. */
export async function probeVoice(): Promise<boolean> {
  const { dictation, voiceChat } = await probeSpeech();
  return dictation || voiceChat;
}

type MicStatus = { available?: boolean; permission?: string; speech_permission?: string };
type TtsStatus = { available?: boolean };

/** Dictation needs a mic (input present, mic + speech permission not denied); voice chat also needs a
 * voice to speak with. A shell that predates these fields counts as having both once it answers. */
export async function probeSpeech(): Promise<{ dictation: boolean; voiceChat: boolean }> {
  if (!nativeBridge()) return { dictation: false, voiceChat: false };
  const [mic, tts] = await Promise.all([postNative<MicStatus>("mic.status"), postNative<TtsStatus>("tts.status")]);
  const micOk = !notImplemented(mic) && mic?.available !== false && mic?.permission !== "denied" && mic?.speech_permission !== "denied";
  const ttsOk = !notImplemented(tts) && tts?.available !== false;
  return { dictation: micOk, voiceChat: micOk && ttsOk };
}

export function onNativeEvent(cb: (detail: NativeEventDetail) => void): () => void {
  if (typeof window === "undefined") return () => {};
  const listener = (event: Event) => cb((event as CustomEvent<NativeEventDetail>).detail);
  window.addEventListener("jaeger:native", listener);
  return () => window.removeEventListener("jaeger:native", listener);
}
