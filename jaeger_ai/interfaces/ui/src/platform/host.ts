/* Host detection. ?host=macos (the WKWebView shell's start URL) sets
 * html[data-jaeger-host="macos"] and html[data-aether-native-window], which
 * shell.css uses for traffic-light padding and borderless chrome. */
export type JaegerHost = "web" | "macos";

export function detectHost(search = location.search): JaegerHost {
  return new URLSearchParams(search).get("host") === "macos" ? "macos" : "web";
}

export function applyHostAttributes(host: JaegerHost, root = document.documentElement) {
  root.dataset.jaegerHost = host;
  if (host === "macos") root.setAttribute("data-aether-native-window", "");
  else root.removeAttribute("data-aether-native-window");
}

/** Voice stays off unless explicitly enabled (?voice=1 or VITE_JAEGER_VOICE=1). */
export function voiceFlag(search = location.search): boolean {
  return new URLSearchParams(search).get("voice") === "1" || import.meta.env.VITE_JAEGER_VOICE === "1";
}
