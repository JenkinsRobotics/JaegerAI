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
  } catch {
    return undefined;
  }
}

const notImplemented = (reply: unknown) =>
  reply == null || (typeof reply === "object" && ((reply as { error?: string }).error === "not_implemented" || (reply as { status?: string }).status === "not_implemented"));

/** mic and tts count as available only when the shell answers with something
 * other than not_implemented. */
export async function probeVoice(): Promise<boolean> {
  if (!nativeBridge()) return false;
  const [mic, tts] = await Promise.all([postNative("mic.status"), postNative("tts.status")]);
  return !notImplemented(mic) && !notImplemented(tts);
}

export function onNativeEvent(cb: (detail: NativeEventDetail) => void): () => void {
  if (typeof window === "undefined") return () => {};
  const listener = (event: Event) => cb((event as CustomEvent<NativeEventDetail>).detail);
  window.addEventListener("jaeger:native", listener);
  return () => window.removeEventListener("jaeger:native", listener);
}
