import { useCallback, useEffect, useRef, useState } from "react";
import { avatarApi, type AvatarRecord } from "./avatarModel";

/** The agent's saved avatar + live emotion. Emotion is re-read every 15 s while visible (nothing pushes it yet). */
export function useAvatar(agentId: string | undefined) {
  const [record, setRecord] = useState<AvatarRecord | null>(null);
  const [error, setError] = useState<string>();
  const reload = useCallback(async () => {
    if (!agentId) return;
    try { setRecord(await avatarApi.get(agentId)); setError(undefined); } catch (e) { setError((e as Error).message); setRecord(null); }
  }, [agentId]);
  useEffect(() => {
    setRecord(null); void reload();
    const t = window.setInterval(() => { if (document.visibilityState === "visible") void reload(); }, 15000);
    return () => window.clearInterval(t);
  }, [reload]);
  return { record, setRecord, error, reload };
}

/** Speaking + mouth from the native TTS event. Lip-sync timing is a STUB (server text heuristic) until TTS reports visemes. */
export function useSpeech(agentId: string | undefined) {
  const [speaking, setSpeaking] = useState(false);
  const [mouth, setMouth] = useState<string | null>(null);
  const timers = useRef<number[]>([]);
  useEffect(() => {
    const clear = () => { timers.current.forEach((t) => window.clearTimeout(t)); timers.current = []; };
    const on = (e: Event) => {
      const d = (e as CustomEvent<{ speaking: boolean; text?: string }>).detail;
      clear();
      if (!d?.speaking || !agentId) { setSpeaking(false); setMouth(null); return; }
      setSpeaking(true);
      fetch(`/v1/agents/${encodeURIComponent(agentId)}/avatar/visemes?text=${encodeURIComponent((d.text ?? "").slice(0, 2000))}`, { credentials: "include" })
        .then((r) => r.json() as Promise<{ duration: number; timeline: { t: number; viseme: string }[] }>)
        .then((v) => {
          for (const k of v.timeline) timers.current.push(window.setTimeout(() => setMouth(k.viseme === "sil" ? null : k.viseme), k.t * 1000));
          timers.current.push(window.setTimeout(() => { setSpeaking(false); setMouth(null); }, v.duration * 1000 + 200));
        }, () => timers.current.push(window.setTimeout(() => setSpeaking(false), 4000)));
    };
    window.addEventListener("jaeger:tts", on);
    return () => { window.removeEventListener("jaeger:tts", on); clear(); };
  }, [agentId]);
  return { speaking, mouth };
}
