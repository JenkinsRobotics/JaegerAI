import { useSyncExternalStore } from "react";

const defaults = {
  completionAlerts: "Only when unfocused", approvalAlerts: "on", sound: "Default",
  mode: "System", background: "", foreground: "", accent: "Theme default", font: "System",
  sendShortcut: "Enter", contextUsage: "on", voiceEnabled: "on",
  keepAwake: "off", microphone: "", speechVoice: "", speechLanguage: "",
};
type Key = keyof typeof defaults;
const prefix = "jaeger.webui.";
const changed = "jaeger-preference-change";
function subscribe(update: () => void) {
  window.addEventListener(changed, update);
  window.addEventListener("storage", update);
  return () => {
    window.removeEventListener(changed, update);
    window.removeEventListener("storage", update);
  };
}
export function readSetting(key: Key) {
  return window.localStorage.getItem(prefix + key) ?? defaults[key];
}
export function useSetting(key: Key): [string, (value: string) => void] {
  const value = useSyncExternalStore(subscribe, () => readSetting(key), () => defaults[key]);
  return [value, next => {
    window.localStorage.setItem(prefix + key, next);
    window.dispatchEvent(new Event(changed));
  }];
}

export function notifyRunEvent(event: string, tag: string) {
  if (typeof Notification === "undefined" || Notification.permission !== "granted") return;
  let title: string;
  if (event === "approval.requested") {
    if (readSetting("approvalAlerts") !== "on") return;
    title = "Jaeger needs your approval";
  } else if (event === "run.completed") {
    const when = readSetting("completionAlerts");
    if (when === "Never" || (when === "Only when unfocused" && document.hasFocus())) return;
    title = "Jaeger finished your task";
  } else return;
  try {
    new Notification(title, {tag, silent: readSetting("sound") === "Silent"});
  } catch { /* Some hosts expose Notification but require a service worker. */ }
}
