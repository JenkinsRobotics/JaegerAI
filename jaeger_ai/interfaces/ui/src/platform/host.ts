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