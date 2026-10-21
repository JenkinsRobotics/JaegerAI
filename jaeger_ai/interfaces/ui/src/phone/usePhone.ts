import {displayDate, displayDayDistance} from "../settings/devicePreferences";
/* Phone layout switch: width ≤ 700px OR a coarse (touch) pointer, on any host. The Mac app at its normal width
 * (fine pointer, ≥ 700px) never matches, so the desktop layout is untouched. Also keeps --jg-vvh = the visual
 * viewport height, so the phone shell (and its composer) shrinks above the on-screen keyboard. */
import { useEffect, useState } from "react";

export const PHONE_QUERY = "(max-width: 700px), (pointer: coarse)";
const matches = () => typeof matchMedia === "function" && matchMedia(PHONE_QUERY).matches;

export function usePhone(): boolean {
  const [phone, setPhone] = useState(matches);
  useEffect(() => {
    if (typeof matchMedia !== "function") return;
    const mq = matchMedia(PHONE_QUERY);
    const on = () => setPhone(mq.matches);
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  }, []);
  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle("jg-phone", phone);
    if (!phone) { root.style.removeProperty("--jg-vvh"); return; }
    const vv = window.visualViewport;
    const sync = () => root.style.setProperty("--jg-vvh", `${Math.round(vv?.height ?? innerHeight)}px`);
    sync();
    vv?.addEventListener("resize", sync); vv?.addEventListener("scroll", sync); addEventListener("resize", sync);
    return () => { vv?.removeEventListener("resize", sync); vv?.removeEventListener("scroll", sync); removeEventListener("resize", sync); root.classList.remove("jg-phone"); };
  }, [phone]);
  return phone;
}

/** Row time like the iOS list: "7:15 AM" today, "Yesterday", a weekday within a week, else "Oct 3". */
export function rowTime(epochSeconds: number, now = new Date()): string {
  if (!epochSeconds) return "";
  const d = new Date(epochSeconds * 1000);
  const days = displayDayDistance(d.getTime(), now.getTime());
  if (days <= 0) return displayDate(d, {hour: "numeric", minute: "2-digit"});
  if (days === 1) return "Yesterday";
  if (days < 7) return displayDate(d, {weekday: "long"});
  return displayDate(d, {month: "short", day: "numeric"});
}
