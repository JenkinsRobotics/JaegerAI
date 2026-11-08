/**
 * VoiceDictation (unified UI, 2026-10-30): the Apple UI's voice button, made real.
 *
 * Click the microphone to dictate into the chat composer with the browser's
 * speech recognition. Text is only inserted into the composer — nothing
 * is sent until the operator presses Send. Unsupported browsers keep a
 * disabled microphone with a reason; native Mac hosts have their own controls.
 */
import { useEffect, useRef, useState } from "react";
import { MicIcon } from "../icons";

type Recognition = { lang: string; interimResults: boolean; continuous: boolean; start(): void; stop(): void;
  onresult: ((e: { resultIndex: number; results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null;
  onend: (() => void) | null; onerror: ((e: { error: string }) => void) | null };
type RecognitionCtor = new () => Recognition;

export function recognitionCtor(w: unknown = typeof window === "undefined" ? undefined : window): RecognitionCtor | undefined {
  const g = w as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor } | undefined;
  return g?.SpeechRecognition ?? g?.webkitSpeechRecognition;
}

/** Append text to the composer through React's value setter so its state sees the change. */
export function insertIntoComposer(text: string, root: ParentNode = document): boolean {
  const field = root.querySelector<HTMLTextAreaElement>(".jg-composer__input");
  if (!field || field.disabled || !text.trim()) return false;
  const next = field.value ? `${field.value.replace(/\s+$/, "")} ${text.trim()}` : text.trim();
  const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
  setter?.call(field, next);
  field.dispatchEvent(new Event("input", { bubbles: true }));
  field.focus();
  return true;
}

export function VoiceDictation() {
  const Ctor = recognitionCtor();
  const [listening, setListening] = useState(false);
  const [error, setError] = useState<string>();
  const rec = useRef<Recognition | null>(null);
  useEffect(() => () => rec.current?.stop(), []);
  if (!Ctor) return <div className="jg-voice"><button type="button" className="jg-composer__icon" disabled aria-label="Dictation unavailable in this browser" title="This browser does not support speech recognition. You can use keyboard dictation."><MicIcon /></button></div>;
  const start = () => {
    if (listening) return;
    const r = new Ctor();
    r.lang = navigator.language || "en-US"; r.interimResults = false; r.continuous = true;
    r.onresult = (e) => {
      for (let i = e.resultIndex; i < e.results.length; i++) if (e.results[i].isFinal) insertIntoComposer(e.results[i][0].transcript);
    };
    r.onerror = (e) => setError(e.error === "not-allowed" ? "Microphone permission denied" : `Dictation stopped: ${e.error}`);
    r.onend = () => setListening(false);
    rec.current = r; setError(undefined); setListening(true);
    try { r.start(); } catch (e) { setListening(false); setError(String((e as Error).message ?? e)); }
  };
  const stop = () => { rec.current?.stop(); setListening(false); };
  return (
    <div className="jg-voice" data-listening={listening || undefined}>
      <button type="button" className={`jg-composer__icon${listening ? " is-listening" : ""}`} aria-label={listening ? "Stop dictation" : "Dictate message"} title={listening ? "Stop dictation" : "Dictate message"} aria-pressed={listening} onClick={() => (listening ? stop() : start())}><MicIcon /></button>
      {(error || listening) && <span className="jg-voice__label" role="status">{error ?? "Listening… tap to stop"}</span>}
    </div>
  );
}
