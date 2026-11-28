/**
 * Modern 2D Expressive Companion Character Stage (zero-GPU WebGL overhead).
 *
 * Renders either an uploaded 2D character portrait with live reactive halo +
 * expression/mode cues OR a sleek, Grok-companion-style animated 2D character rig
 * with smooth auto-blinking, cursor eye-tracking, breathing motion, emotion eyebrows,
 * and Kokoro viseme / live-amplitude mouth shapes.
 */

import { useEffect, useRef, useState } from "react";
import type { VisemeFrame } from "./vrmEngine";

export interface Character2DStageProps {
  name?: string;
  emotion?: string;
  mode?: string;
  amplitude?: number;
  visemes?: VisemeFrame[];
  imageUrl?: string | null;
  videoUrl?: string | null;
  paused?: boolean;
  compact?: boolean;
}

export function Character2DStage({
  name = "Jaeger",
  emotion = "warm",
  mode = "observing",
  amplitude = 0,
  visemes = [],
  imageUrl = null,
  videoUrl = null,
  paused = false,
  compact = false,
}: Character2DStageProps) {
  const [failedVideo, setFailedVideo] = useState<string>();
  const [reduceMotion, setReduceMotion] = useState(
    () => typeof window !== "undefined" && (window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches ?? false),
  );
  useEffect(() => {
    const preference = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    const onChange = (event: MediaQueryListEvent) => setReduceMotion(event.matches);
    preference?.addEventListener("change", onChange);
    return () => preference?.removeEventListener("change", onChange);
  }, []);

  const [blink, setBlink] = useState(false);
  const [gaze, setGaze] = useState({ x: 0, y: 0 });
  const [activeViseme, setActiveViseme] = useState<string>("closed");
  const rootRef = useRef<HTMLDivElement | null>(null);

  // Natural randomized blink loop
  useEffect(() => {
    if (paused) return;
    let alive = true;
    let timer = 0;
    const schedule = () => {
      const wait = 2400 + Math.random() * 3400;
      timer = window.setTimeout(() => {
        if (!alive) return;
        setBlink(true);
        window.setTimeout(() => {
          if (!alive) return;
          setBlink(false);
          schedule();
        }, 135);
      }, wait);
    };
    schedule();
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [paused]);

  // Play Kokoro lip_marks viseme timeline when provided
  useEffect(() => {
    if (!visemes.length || paused) {
      setActiveViseme("closed");
      return;
    }
    const started = performance.now();
    const last = visemes[visemes.length - 1];
    const id = window.setInterval(() => {
      const elapsed = performance.now() - started;
      if (elapsed > last.t_ms + last.duration_ms + 80) {
        setActiveViseme("closed");
        window.clearInterval(id);
        return;
      }
      const hit = visemes.find((f) => elapsed >= f.t_ms && elapsed <= f.t_ms + f.duration_ms);
      setActiveViseme(hit ? hit.viseme : "closed");
    }, 32);
    return () => window.clearInterval(id);
  }, [visemes, paused]);

  const handleMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (paused || !rootRef.current) return;
    const rect = rootRef.current.getBoundingClientRect();
    const nx = ((e.clientX - rect.left) / Math.max(1, rect.width) - 0.5) * 2;
    const ny = ((e.clientY - rect.top) / Math.max(1, rect.height) - 0.5) * 2;
    setGaze({ x: Math.max(-1, Math.min(1, nx)), y: Math.max(-1, Math.min(1, ny)) });
  };

  const mouthOpen =
    activeViseme === "aa"
      ? 14
      : activeViseme === "oh" || activeViseme === "ou"
        ? 11
        : activeViseme === "ee" || activeViseme === "ih"
          ? 7
          : Math.round(amplitude * 12);

  const eyeScaleY = blink ? 0.08 : emotion === "happy" ? 0.82 : emotion === "focused" ? 0.88 : 1;
  const browTilt =
    emotion === "focused" ? 5 : emotion === "concerned" || emotion === "sad" ? -6 : emotion === "curious" ? -3 : 0;

  return (
    <div
      ref={rootRef}
      className={`jg-avatar-2d ${compact ? "is-compact" : ""} is-${mode}`}
      onMouseMove={handleMove}
      onMouseLeave={() => setGaze({ x: 0, y: 0 })}
      aria-label={`${name} avatar (${emotion})`}
    >
      <div
        className="jg-avatar-halo"
        style={{ transform: `scale(${(1 + Math.max(amplitude, mouthOpen / 24) * 0.14).toFixed(3)})` }}
      />
      {videoUrl && videoUrl !== failedVideo && !paused && !reduceMotion ? (
        <video
          key={videoUrl}
          src={videoUrl}
          poster={imageUrl ?? undefined}
          className="jg-avatar-portrait"
          role="img"
          aria-label={name}
          autoPlay
          muted
          loop
          playsInline
          onError={() => setFailedVideo(videoUrl)}
        />
      ) : imageUrl ? (
        <img
          src={imageUrl}
          alt={name}
          className="jg-avatar-portrait"
          style={{
            transform: `translate(${(gaze.x * 3).toFixed(1)}px, ${(gaze.y * 2).toFixed(1)}px)`,
          }}
        />
      ) : (
        <svg viewBox="0 0 220 240" className="jg-avatar-svg" role="img" aria-label={name}>
          <defs>
            <linearGradient id="jgSkinGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--jg-surface-elevated)" />
              <stop offset="100%" stopColor="var(--jg-surface-subtle)" />
            </linearGradient>
            <linearGradient id="jgAccentGrad" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="var(--jg-accent)" />
              <stop offset="100%" stopColor="var(--jg-accent-hover)" />
            </linearGradient>
          </defs>

          {/* Shoulders / collar silhouette */}
          <path
            d="M42 232 C48 186 76 172 110 172 C144 172 172 186 178 232 Z"
            fill="url(#jgAccentGrad)"
            opacity="0.18"
          />
          <path
            d="M54 232 C60 194 82 182 110 182 C138 182 160 194 166 232"
            fill="none"
            stroke="var(--jg-accent)"
            strokeWidth="2.5"
            opacity="0.65"
          />

          {/* Head + subtle gaze parallax */}
          <g transform={`translate(${(gaze.x * 4).toFixed(1)}, ${(gaze.y * 3).toFixed(1)})`}>
            {/* Stylized futuristic hair / visor crest */}
            <path
              d="M52 106 C50 56 76 32 110 32 C144 32 170 56 168 106 C168 148 142 170 110 170 C78 170 52 148 52 106 Z"
              fill="url(#jgSkinGrad)"
              stroke="var(--jg-border-strong)"
              strokeWidth="2"
            />
            <path
              d="M54 92 C58 50 82 34 110 34 C138 34 162 50 166 92 C148 76 130 68 110 72 C90 68 72 76 54 92 Z"
              fill="url(#jgAccentGrad)"
              opacity="0.82"
            />

            {/* Expressive eyebrows */}
            <path
              d="M72 90 Q86 84 98 89"
              fill="none"
              stroke="var(--jg-text)"
              strokeWidth="2.6"
              strokeLinecap="round"
              transform={`rotate(${browTilt} 85 88)`}
            />
            <path
              d="M122 89 Q134 84 148 90"
              fill="none"
              stroke="var(--jg-text)"
              strokeWidth="2.6"
              strokeLinecap="round"
              transform={`rotate(${-browTilt} 135 88)`}
            />

            {/* Left & Right Eyes with smooth blink & pupil tracking */}
            <g transform={`translate(85, 108) scale(1, ${eyeScaleY})`}>
              <ellipse cx="0" cy="0" rx="11" ry="12" fill="var(--jg-bg)" stroke="var(--jg-border-strong)" strokeWidth="1.5" />
              <circle cx={gaze.x * 3.5} cy={gaze.y * 2.5} r="6.2" fill="var(--jg-accent)" />
              <circle cx={gaze.x * 3.5 - 2} cy={gaze.y * 2.5 - 2.2} r="2.1" fill="var(--jg-surface)" />
            </g>
            <g transform={`translate(135, 108) scale(1, ${eyeScaleY})`}>
              <ellipse cx="0" cy="0" rx="11" ry="12" fill="var(--jg-bg)" stroke="var(--jg-border-strong)" strokeWidth="1.5" />
              <circle cx={gaze.x * 3.5} cy={gaze.y * 2.5} r="6.2" fill="var(--jg-accent)" />
              <circle cx={gaze.x * 3.5 - 2} cy={gaze.y * 2.5 - 2.2} r="2.1" fill="var(--jg-surface)" />
            </g>

            {/* Lip-synced expressive mouth */}
            {mouthOpen > 2 ? (
              <ellipse
                cx="110"
                cy="141"
                rx={activeViseme === "ou" || activeViseme === "oh" ? 7 : 11}
                ry={Math.max(3, mouthOpen * 0.65)}
                fill="var(--jg-accent)"
                opacity="0.85"
              />
            ) : (
              <path
                d={
                  emotion === "happy" || emotion === "warm"
                    ? "M96 138 Q110 149 124 138"
                    : emotion === "concerned" || emotion === "sad"
                      ? "M98 144 Q110 137 122 144"
                      : "M99 140 Q110 144 121 140"
                }
                fill="none"
                stroke="var(--jg-text)"
                strokeWidth="2.8"
                strokeLinecap="round"
              />
            )}
          </g>
        </svg>
      )}
    </div>
  );
}
