import { readSetting } from "./userPreferences";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

type Session = {
  stream: MediaStream;
  audio: AudioContext;
  timer: number;
  recorder?: MediaRecorder;
  request: AbortController;
};

export interface DroidVoiceProps {
  baseUrl: string;
  reply: string;
  replyId?: string;
  busy: boolean;
  onCamera: (active: boolean) => void;
  onTranscript: (text: string) => Promise<boolean>;
  aiName?: string;
  sleeping?: boolean;
  onSleep?: () => Promise<boolean | void> | boolean | void;
  onWake?: () => Promise<boolean> | boolean;
}

const DEFAULT_WAKE_WORDS = ["jaeger", "jager", "yeager", "yager"];

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function wakeWordTokens(aiName?: string): string[] {
  const tokens = [...DEFAULT_WAKE_WORDS];
  const custom = (aiName || "").trim().toLowerCase();
  if (custom && !tokens.includes(custom)) {
    tokens.push(custom);
    const firstWord = custom.split(/\s+/)[0];
    if (firstWord && firstWord.length >= 2 && !tokens.includes(firstWord)) {
      tokens.push(firstWord);
    }
  }
  return tokens;
}

function buildWakeWordPattern(aiName?: string): RegExp {
  const alternation = wakeWordTokens(aiName).map(escapeRegExp).join("|");
  return new RegExp(`\\b(?:${alternation})\\b`, "i");
}

export function isSleepVoiceCommand(text: string, aiName?: string): boolean {
  const trimmed = text.trim();
  if (!trimmed || /\?$/.test(trimmed)) return false;
  const normalized = trimmed
    .toLowerCase()
    .replace(/[.,!;:"'“”‘’]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (!normalized) return false;

  const addressWords = [...wakeWordTokens(aiName), "truth", "droid"];
  const uniqueAddress = Array.from(new Set(addressWords)).map(escapeRegExp).join("|");
  const greeting = "(?:(?:hey|hi|ok|okay|yo)\\s+)?";
  const optionalAddress = `(?:(?:${uniqueAddress})\\s+)?`;
  const requiredAddress = `(?:${uniqueAddress})\\s+`;
  const polite = "(?:please\\s+)?";
  const suffix = `(?:\\s+(?:now|please|${uniqueAddress}))*$`;

  const questionPrefix = new RegExp(`^${greeting}${optionalAddress}(?:how|why|what)\\b`, "i");
  if (questionPrefix.test(normalized)) return false;

  const directCommands = [
    "go to sleep",
    "turn off (?:the )?(?:droid(?: mode)?|camera|yourself)",
    "turn (?:the )?(?:droid(?: mode)?|camera) off",
    "shut off (?:the )?(?:droid(?: mode)?|camera|yourself)",
    "shut (?:the )?(?:droid(?: mode)?|camera) off",
    "shut down (?:the )?(?:droid(?: mode)?|camera|yourself)",
    "shutdown (?:the )?(?:droid(?: mode)?|camera|yourself)",
    "shut (?:the )?(?:droid(?: mode)?|camera) down",
    "power down (?:the )?(?:droid(?: mode)?|camera|yourself)",
    "power (?:the )?(?:droid(?: mode)?|camera) down",
    "(?:exit|leave|disable|stop) (?:the )?droid mode",
    "droid mode off",
    "park (?:the )?(?:camera|gimbal|lens|droid)",
    "put (?:the )?(?:droid|camera) to sleep",
    "(?:enter )?sleep mode",
  ];

  const directRegex = new RegExp(`^${greeting}${optionalAddress}${polite}(?:${directCommands.join("|")})${suffix}`, "i");
  if (directRegex.test(normalized)) return true;

  const addressedSleepRegex = new RegExp(`^${greeting}${requiredAddress}${polite}sleep${suffix}`, "i");
  return addressedSleepRegex.test(normalized);
}

function pickSpeechVoice(synth: SpeechSynthesis): SpeechSynthesisVoice | undefined {
  const voices = typeof synth.getVoices === "function" ? synth.getVoices() : [];
  const selected=voices.find(v=>v.voiceURI===readSetting("speechVoice"));
  const language=(readSetting("speechLanguage") || navigator.language).split("-")[0].toLowerCase();
  return selected ?? voices.find(v=>v.localService && v.lang.toLowerCase().startsWith(language))
    ?? voices.find(v=>v.lang.toLowerCase().startsWith(language));
}

export function DroidVoice({
  baseUrl,
  reply,
  replyId,
  busy,
  onCamera,
  onTranscript,
  aiName,
  sleeping = false,
  onSleep,
  onWake,
}: DroidVoiceProps) {
  const wakeLabel = (aiName || "").trim() || "Jaeger";
  const session = useRef<Session | null>(null);
  const generation = useRef(0);
  const enrollNext = useRef(false);
  const queuedSpeech = useRef("");
  const spoken = useRef({ id: replyId, offset: reply.length });
  const voicePanel = useRef<HTMLDivElement>(null);
  const prevSleeping = useRef(Boolean(sleeping));
  const [phase, setPhase] = useState<"off" | "starting" | "listening" | "recording" | "transcribing">("off");
  const [notice, setNotice] = useState("");
  const [noticeIsError, setNoticeIsError] = useState(false);
  const [micName, setMicName] = useState("");
  const [muted, setMuted] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [compact, setCompact] = useState(false);
  const [voicesVersion, setVoicesVersion] = useState(0);

  const latest = useRef({ baseUrl, busy, onTranscript, onCamera, onSleep, onWake, aiName, sleeping });
  latest.current = { baseUrl, busy, onTranscript, onCamera, onSleep, onWake, aiName, sleeping };

  function updateNotice(message: string, isError = false) {
    setNotice(message);
    setNoticeIsError(isError && Boolean(message));
  }

  function closeSession() {
    generation.current++;
    enrollNext.current = false;
    queuedSpeech.current = "";
    const current = session.current;
    session.current = null;
    if (current) {
      window.clearInterval(current.timer);
      current.request.abort();
      if (current.recorder?.state === "recording") {
        current.recorder.onstop = null;
        current.recorder.stop();
      }
      current.stream.getTracks().forEach((track) => track.stop());
      void current.audio.close();
    }
    window.speechSynthesis?.cancel();
    voicePanel.current?.style.setProperty("--jg-droid-level", "0");
  }

  const stop = () => {
    closeSession();
    latest.current.onCamera(false);
    updateNotice("");
    setMuted(false);
    setSpeaking(false);
    setCompact(false);
    setPhase("off");
  };

  const stopRef = useRef(stop);
  stopRef.current = stop;

  async function triggerSleep(reason: "voice" | "button") {
    window.speechSynthesis?.cancel();
    closeSession();
    latest.current.onCamera(false);
    setMuted(false);
    setSpeaking(false);
    setCompact(false);
    setPhase("off");
    updateNotice("Droid asleep — camera parked.", false);
    try {
      if (latest.current.onSleep) {
        await latest.current.onSleep();
      } else {
        await fetch(`${latest.current.baseUrl}/v1/droid/sleep`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ reason }),
        });
      }
    } catch {
      // Mic, TTS, and camera preview are already closed locally.
    }
  }

  useEffect(() => () => closeSession(), []);

  useEffect(() => {
    const synth = typeof window !== "undefined" ? window.speechSynthesis : undefined;
    if (!synth) return;
    const handleVoicesChanged = () => setVoicesVersion((version) => version + 1);
    synth.getVoices?.();
    if (typeof synth.addEventListener === "function") {
      synth.addEventListener("voiceschanged", handleVoicesChanged);
      return () => synth.removeEventListener("voiceschanged", handleVoicesChanged);
    }
    const previous = synth.onvoiceschanged;
    synth.onvoiceschanged = handleVoicesChanged;
    return () => {
      if (synth.onvoiceschanged === handleVoicesChanged) synth.onvoiceschanged = previous ?? null;
    };
  }, []);

  useEffect(() => {
    const wasSleeping = prevSleeping.current;
    prevSleeping.current = Boolean(sleeping);
    if (sleeping && !wasSleeping && (phase !== "off" || session.current)) {
      closeSession();
      latest.current.onCamera(false);
      setMuted(false);
      setSpeaking(false);
      setCompact(false);
      setPhase("off");
      updateNotice("Droid asleep — camera parked.", false);
    }
  }, [sleeping, phase]);

  useEffect(() => {
    if (phase === "off") return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.key !== "Escape") return;
      if (event.shiftKey) {
        event.preventDefault();
        stopRef.current();
      } else if (!compact) {
        event.preventDefault();
        setCompact(true);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [phase, compact]);

  useEffect(() => {
    const current = session.current;
    if (!current || busy || phase !== "listening" || !queuedSpeech.current) return;
    const text = queuedSpeech.current;
    queuedSpeech.current = "";
    void latest.current.onTranscript(text).then((sent) => {
      if (session.current === current) updateNotice(sent ? "" : "Voice turn is in the message box.", false);
    });
  }, [busy, phase]);

  useEffect(() => {
    if (!session.current || !replyId || phase !== "listening" || !window.speechSynthesis) return;
    if (typeof SpeechSynthesisUtterance === "undefined") return;
    if (spoken.current.id !== replyId) spoken.current = { id: replyId, offset: 0 };
    const remaining = reply.slice(spoken.current.offset);
    const complete = busy ? remaining.match(/^[\s\S]*[.!?](?:\s|$)/)?.[0] ?? "" : remaining;
    if (!complete.trim()) return;
    const voice = pickSpeechVoice(window.speechSynthesis);
    spoken.current.offset += complete.length;
    const utterance = new SpeechSynthesisUtterance(complete);
    utterance.lang = voice?.lang || readSetting("speechLanguage") || navigator.language;
    if (voice) utterance.voice = voice;
    utterance.onstart = () => { if (session.current) setSpeaking(true); };
    utterance.onend = utterance.onerror = () => {
      if (session.current && !window.speechSynthesis.pending) setSpeaking(false);
    };
    window.speechSynthesis.speak(utterance);
  }, [reply, replyId, busy, phase, voicesVersion]);

  async function start() {
    const attempt = ++generation.current;
    updateNotice("");
    setMuted(false);
    setSpeaking(false);
    setCompact(false);
    setPhase("starting");

    if (latest.current.sleeping && latest.current.onWake) {
      updateNotice("Waking Droid…", false);
      let woke = false;
      try {
        woke = Boolean(await latest.current.onWake());
      } catch {
        woke = false;
      }
      if (generation.current !== attempt) return;
      if (!woke) {
        setPhase("off");
        updateNotice("Could not wake Droid. Check E-Stop or Droid status.", true);
        return;
      }
      updateNotice("");
    }

    let stream: MediaStream | undefined;
    let audio: AudioContext | undefined;
    try {
      audio = new AudioContext();
      await audio.resume();
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { ...(readSetting("microphone") ? {deviceId: {exact: readSetting("microphone")}} : {}), echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      if (generation.current !== attempt) {
        stream.getTracks().forEach((track) => track.stop());
        void audio.close();
        return;
      }
      const analyser = audio.createAnalyser();
      analyser.fftSize = 1024;
      const source = audio.createMediaStreamSource(stream);
      source.connect(analyser);
      const delay = audio.createDelay(1);
      delay.delayTime.value = 0.35;
      const bufferedMic = audio.createMediaStreamDestination();
      source.connect(delay).connect(bufferedMic);
      setMicName(stream.getAudioTracks()[0]?.label || "Default microphone");
      latest.current.onCamera(true);
      const samples = new Float32Array(analyser.fftSize);
      const microphone = stream;
      const current: Session = { stream, audio, timer: 0, request: new AbortController() };
      session.current = current;
      spoken.current = { id: replyId, offset: reply.length };
      let loud = 0;
      let lastSpeech = 0;
      let started = 0;
      let processing = false;

      current.timer = window.setInterval(() => {
        if (processing || microphone.getAudioTracks().every((track) => !track.enabled)) return;
        analyser.getFloatTimeDomainData(samples);
        const level = Math.sqrt(samples.reduce((sum, sample) => sum + sample * sample, 0) / samples.length);
        voicePanel.current?.style.setProperty("--jg-droid-level", Math.min(1, level * 18).toFixed(3));
        const now = performance.now();
        const talking = level > 0.022;
        if (talking) lastSpeech = now;
        if (current.recorder?.state === "recording") {
          if (now - lastSpeech > 1050 || now - started > 19_500) current.recorder.stop();
          return;
        }
        loud = talking ? loud + 1 : 0;
        if (loud < 2) return;
        loud = 0;
        window.speechSynthesis?.cancel();
        setSpeaking(false);
        spoken.current.offset = Number.MAX_SAFE_INTEGER;
        const enroll = enrollNext.current;
        enrollNext.current = false;
        const recorder = new MediaRecorder(bufferedMic.stream);
        const chunks: BlobPart[] = [];
        recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
        recorder.onstop = async () => {
          if (session.current !== current) return;
          processing = true;
          setPhase("transcribing");
          try {
            const response = await fetch(`${latest.current.baseUrl}/v1/droid/transcribe${enroll ? "?enroll=1" : ""}`, {
              method: "POST",
              body: new Blob(chunks, { type: recorder.mimeType }),
              signal: current.request.signal,
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || "Transcription unavailable.");
            if (session.current !== current) return;
            const text = String(data.transcript || "").replace(/\[BLANK_AUDIO\]/gi, "").trim();
            if (data.intent === "sleep" || (text && isSleepVoiceCommand(text, latest.current.aiName))) {
              await triggerSleep("voice");
              return;
            }
            if (!text) {
              updateNotice(data.notice || "No clear speech detected.", false);
              return;
            }
            const wakePattern = buildWakeWordPattern(latest.current.aiName);
            const currentLabel = (latest.current.aiName || "").trim() || "Jaeger";
            if (!wakePattern.test(text)) {
              updateNotice(`Matched your voice. Say ${currentLabel} to send a question to chat.`, false);
              return;
            }
            if (latest.current.busy) {
              queuedSpeech.current = [queuedSpeech.current, text].filter(Boolean).join(" ");
              updateNotice("Heard your interruption. Sending when the current turn settles.", false);
            } else {
              const sent = await latest.current.onTranscript(text);
              if (session.current === current) updateNotice(sent ? "" : "Voice turn is in the message box.", false);
            }
          } catch (error) {
            if (session.current === current) {
              updateNotice(error instanceof Error ? error.message : "Voice turn failed.", true);
            }
          } finally {
            processing = false;
            if (session.current === current) setPhase("listening");
          }
        };
        recorder.start();
        current.recorder = recorder;
        started = now;
        setPhase("recording");
      }, 40);
      setPhase("listening");
    } catch {
      stream?.getTracks().forEach((track) => track.stop());
      if (audio && audio.state !== "closed") void audio.close();
      if (generation.current === attempt) {
        setPhase("off");
        updateNotice("Microphone unavailable. Check browser microphone permission.", true);
      }
    }
  }

  const status = notice || ({
    off: "",
    starting: "Opening microphone…",
    listening: muted
      ? "Microphone muted"
      : speaking
        ? `${wakeLabel} is speaking`
        : busy
          ? `${wakeLabel} is working`
          : `Listening for “${wakeLabel}”`,
    recording: "Hearing you…",
    transcribing: "Transcribing…",
  })[phase];

  const toggleMute = () => {
    const current = session.current;
    if (!current) return;
    if (!muted && current.recorder?.state === "recording") {
      current.recorder.onstop = null;
      current.recorder.stop();
      setPhase("listening");
    }
    current.stream.getAudioTracks().forEach((track) => { track.enabled = muted; });
    setMuted(!muted);
  };

  const orbPhase = speaking ? "speaking" : phase;

  const voicePopup = phase !== "off" ? (
    <div
      ref={voicePanel}
      className="jg-droid-voice-popover"
      role={compact ? undefined : "dialog"}
      aria-label={compact ? undefined : "Droid voice conversation"}
      data-compact={compact ? "true" : undefined}
      data-phase={orbPhase}
      data-muted={muted ? "true" : undefined}
    >
      {compact ? (
        <button
          type="button"
          className="jg-droid-voice-orb jg-droid-voice-orb-compact"
          aria-label="Expand Droid voice orb"
          aria-expanded={false}
          title={status || "Expand Droid voice orb"}
          onClick={() => setCompact(false)}
        >
          <span aria-hidden="true" />
          <i className="jg-droid-voice-dot" aria-hidden="true" />
        </button>
      ) : (
        <>
          <button
            type="button"
            className="jg-droid-voice-orb"
            aria-label={muted ? "Unmute Droid microphone" : "Mute Droid microphone"}
            disabled={phase === "starting" || phase === "transcribing"}
            onClick={toggleMute}
          >
            <span aria-hidden="true" />
          </button>
          <div className="jg-droid-voice-copy">
            <strong>Droid voice</strong>
            <span role="status">{status}</span>
            {micName && <small title={micName}>{micName}</small>}
          </div>
          <span className="jg-droid-voice-meter" aria-hidden="true"><i /><i /><i /><i /></span>
          {(phase === "listening" || phase === "recording") && (
            <button
              type="button"
              className="jg-droid-voice-control jg-droid-voice-mute"
              aria-pressed={muted}
              onClick={toggleMute}
            >
              {muted ? "Unmute" : "Mute"}
            </button>
          )}
          {phase === "listening" && !muted && (
            <button
              type="button"
              className="jg-droid-voice-control jg-droid-voice-enroll"
              onClick={() => {
                enrollNext.current = true;
                updateNotice(
                  "Speak alone for five seconds with the TV muted. Your next phrase becomes your local voice profile.",
                  false,
                );
              }}
            >
              Learn voice
            </button>
          )}
          <button
            type="button"
            className="jg-droid-voice-control jg-droid-voice-sleep"
            onClick={() => void triggerSleep("button")}
          >
            Sleep
          </button>
          <button
            type="button"
            className="jg-droid-voice-control jg-droid-voice-minimize"
            aria-label="Minimize Droid voice orb"
            title="Minimize (Esc)"
            onClick={() => setCompact(true)}
          >
            Minimize
          </button>
          <button type="button" className="jg-droid-voice-control jg-droid-voice-end" onClick={stop}>
            End
          </button>
        </>
      )}
    </div>
  ) : null;

  const voicePortal = voicePopup && typeof document !== "undefined"
    ? createPortal(voicePopup, document.body)
    : voicePopup;

  return (
    <>
      <div className="jg-live-details jg-droid-voice-launcher" role="group" aria-label="Droid voice">
        <button
          type="button"
          className="jg-btn"
          aria-expanded={phase !== "off"}
          onClick={() => {
            if (phase === "off") void start();
            else stop();
          }}
        >
          {phase === "off" ? "Start Droid Conversation" : "End Droid Conversation"}
        </button>
        {phase === "off" && (
          <span role={notice ? (noticeIsError ? "alert" : "status") : undefined}>
            {notice || (sleeping
              ? "Droid is asleep — starting voice will wake Droid and open the floating orb."
              : "Open the camera and floating voice orb.")}
          </span>
        )}
      </div>
      {voicePortal}
    </>
  );
}
