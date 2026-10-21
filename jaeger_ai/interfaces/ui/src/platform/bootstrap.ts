/* Runs before @aether/ui loads (import order in main.tsx): sets the host
 * attributes, and defaults the appearance to Light like Studio when this
 * device has no stored choice. */
import { applyHostAttributes, detectHost } from "./host";

applyHostAttributes(detectHost());
try {
  if (!localStorage.getItem("aether-appearance")) localStorage.setItem("aether-appearance", "light");
} catch { /* storage unavailable: Aether falls back to System */ }

import { applyTextSize, storedTextSize } from "../settings/textSize";
applyTextSize(storedTextSize(), false);
window.addEventListener("storage", (event) => { if (event.key === "jaeger.ui.text-size" || event.key === null) applyTextSize(storedTextSize(), false); });

import {applyDevicePreferences, devicePreferenceSnapshot, DEVICE_PREF_KEY} from "../settings/devicePreferences";
applyDevicePreferences(devicePreferenceSnapshot().preferences);
window.addEventListener("storage", event => {if(event.key === DEVICE_PREF_KEY || event.key === null) applyDevicePreferences(devicePreferenceSnapshot().preferences);});
