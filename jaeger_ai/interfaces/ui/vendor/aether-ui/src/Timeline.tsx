import { useRef } from "react";
import type { PointerEvent as ReactPointerEvent, ReactNode } from "react";

/**
 * Dope-sheet timeline: labeled tracks, keyframe diamonds, adaptive time
 * ruler, draggable playhead. Purely presentational — the app owns time,
 * playback, and (later) keyframe mutation via its engine.
 * Behavior reference: Swift `UIDevTimelineDesignB` + demo `Timeline`.
 */
export interface TimelineTrack {
  id: string;
  label: string;
  keyframes: readonly { timeS: number }[];
}

export interface TimelineProps {
  tracks: readonly TimelineTrack[];
  durationS: number;
  timeS: number;
  onSeek: (timeS: number) => void;
  playing?: boolean;
  onTogglePlay?: () => void;
  selected?: { trackID: string; index: number } | null;
  onSelectKeyframe?: (trackID: string, index: number) => void;
  emptyState?: ReactNode;
}

const TICK_STEPS = [0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60];

function tickStep(durationS: number): number {
  const target = durationS / 8;
  return TICK_STEPS.find((step) => step >= target) ?? 60;
}

export function Timeline(props: TimelineProps) {
  const { tracks, durationS, timeS, onSeek } = props;
  const lanesRef = useRef<HTMLDivElement>(null);
  const scrubbing = useRef(false);

  if (tracks.length === 0) {
    return (
      <div className="aui-timeline">
        <div className="aui-timeline-empty">
          {props.emptyState ?? "no tracks"}
        </div>
      </div>
    );
  }

  const duration = Math.max(durationS, 1e-6);
  const toPercent = (time: number) => `${(time / duration) * 100}%`;

  const seekFromEvent = (event: ReactPointerEvent) => {
    const lanes = lanesRef.current;
    if (!lanes) return;
    const rect = lanes.getBoundingClientRect();
    if (rect.width <= 0) return;
    const fraction = (event.clientX - rect.left) / rect.width;
    onSeek(Math.min(Math.max(fraction, 0), 1) * duration);
  };

  const onPointerDown = (event: ReactPointerEvent) => {
    scrubbing.current = true;
    (event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId);
    seekFromEvent(event);
  };
  const onPointerMove = (event: ReactPointerEvent) => {
    if (scrubbing.current) seekFromEvent(event);
  };
  const onPointerUp = () => {
    scrubbing.current = false;
  };

  const step = tickStep(duration);
  const ticks: number[] = [];
  for (let time = 0; time <= duration + 1e-9; time += step) ticks.push(time);

  return (
    <div className="aui-timeline">
      <div className="aui-timeline-side">
        <div className="aui-timeline-transport">
          {props.onTogglePlay ? (
            <button
              type="button"
              className="aui-icon-button"
              aria-label={props.playing ? "Pause" : "Play"}
              onClick={props.onTogglePlay}
            >
              {props.playing ? "❚❚" : "▶"}
            </button>
          ) : null}
          <span className="aui-timeline-clock">
            {timeS.toFixed(2)}s
          </span>
        </div>
        {tracks.map((track) => (
          <div key={track.id} className="aui-timeline-label" title={track.label}>
            {track.label}
          </div>
        ))}
      </div>
      <div
        className="aui-timeline-lanes"
        ref={lanesRef}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
      >
        <div className="aui-timeline-ruler">
          {ticks.map((tick) => (
            <span
              key={tick.toFixed(3)}
              className="aui-timeline-tick"
              style={{ left: toPercent(tick) }}
            >
              {step >= 1 ? tick.toFixed(0) : tick.toFixed(2)}
            </span>
          ))}
        </div>
        {tracks.map((track) => (
          <div key={track.id} className="aui-timeline-row">
            {track.keyframes.map((keyframe, index) => {
              const isSelected =
                props.selected?.trackID === track.id &&
                props.selected.index === index;
              return (
                <span
                  key={index}
                  role="button"
                  aria-label={`${track.label} keyframe at ${keyframe.timeS.toFixed(2)}s`}
                  className={
                    isSelected
                      ? "aui-timeline-key aui-timeline-key--selected"
                      : "aui-timeline-key"
                  }
                  style={{ left: toPercent(keyframe.timeS) }}
                  onPointerDown={(event) => {
                    event.stopPropagation();
                    props.onSelectKeyframe?.(track.id, index);
                  }}
                />
              );
            })}
          </div>
        ))}
        <div className="aui-timeline-playhead" style={{ left: toPercent(timeS) }} />
      </div>
    </div>
  );
}
