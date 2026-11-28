/**
 * Multi-Track YouTube & Media Studio Timeline (OpenReel-inspired NLE track model, MIT).
 */

import { useState } from "react";

export interface StudioClip {
  id: string;
  track: "video" | "voice" | "captions" | "broll";
  label: string;
  startSec: number;
  durationSec: number;
  status: "ready" | "generating" | "needs_review";
}

export interface StudioTimelineProps {
  projectTitle: string;
  clips: StudioClip[];
  totalSec?: number;
  onDryRun?: () => void;
  dryRunBusy?: boolean;
}

const TRACKS: Array<{ id: StudioClip["track"]; label: string }> = [
  { id: "video", label: "V1 · Main Camera / Render" },
  { id: "broll", label: "V2 · B-Roll & Thumbnails" },
  { id: "voice", label: "A1 · Kokoro MLX Voiceover" },
  { id: "captions", label: "T1 · Auto Captions" },
];

export function StudioTimeline({
  projectTitle,
  clips,
  totalSec = 180,
  onDryRun,
  dryRunBusy = false,
}: StudioTimelineProps) {
  const [playheadSec, setPlayheadSec] = useState(18);
  const [selectedClipId, setSelectedClipId] = useState<string>(clips[0]?.id ?? "");
  const selected = clips.find((c) => c.id === selectedClipId) ?? null;

  const fmtTime = (sec: number) => {
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  };

  return (
    <section className="jg-studio-timeline" aria-label="YouTube Studio Multi-Track Timeline">
      <div className="jg-studio-head">
        <div>
          <strong>{projectTitle}</strong>
          <span className="jg-pill">Playhead {fmtTime(playheadSec)} / {fmtTime(totalSec)}</span>
        </div>
        <div className="jg-studio-actions">
          <input
            type="range"
            min={0}
            max={totalSec}
            value={playheadSec}
            aria-label="Scrub timeline playhead"
            onChange={(e) => setPlayheadSec(Number(e.target.value))}
          />
          {onDryRun && (
            <button type="button" className="jg-btn" disabled={dryRunBusy} onClick={onDryRun}>
              {dryRunBusy ? "Simulating..." : "Safe Dry-Run"}
            </button>
          )}
        </div>
      </div>

      <div className="jg-timeline-tracks">
        {TRACKS.map((track) => {
          const trackClips = clips.filter((c) => c.track === track.id);
          return (
            <div key={track.id} className="jg-track-row">
              <div className="jg-track-label">{track.label}</div>
              <div className="jg-track-lane">
                <div
                  className="jg-playhead-line"
                  style={{ left: `${(playheadSec / Math.max(1, totalSec)) * 100}%` }}
                />
                {trackClips.map((clip) => (
                  <button
                    key={clip.id}
                    type="button"
                    className={`jg-clip is-${clip.status} ${selectedClipId === clip.id ? "is-selected" : ""}`}
                    style={{
                      left: `${(clip.startSec / Math.max(1, totalSec)) * 100}%`,
                      width: `${Math.max(8, (clip.durationSec / Math.max(1, totalSec)) * 100)}%`,
                    }}
                    onClick={() => setSelectedClipId(clip.id)}
                  >
                    <span className="jg-clip-title">{clip.label}</span>
                  </button>
                ))}
              </div>
            </div>
          );
        })}
      </div>

      {selected && (
        <div className="jg-clip-inspector">
          <span>
            <strong>{selected.label}</strong> · Track: <code>{selected.track}</code> · Start {fmtTime(selected.startSec)} ({selected.durationSec}s)
          </span>
          <span className={`jg-pill is-${selected.status}`}>{selected.status.replace("_", " ")}</span>
        </div>
      )}
    </section>
  );
}
