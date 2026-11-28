/**
 * Unified Grok-style On-Screen 2D/3D VR Avatar Stage.
 *
 * Lazily imports Three.js + @pixiv/three-vrm ONLY when a 3D VRM/GLB asset is
 * active so 2D / PiP mode keeps bundle and 32 GB GPU usage featherweight.
 */

import { useEffect, useRef, useState } from "react";
import { Character2DStage } from "./Character2DStage";
import { LiveAvatarApp, useAvatarApp } from "./LiveAvatarApp";
import type { AvatarStageHandle, VisemeFrame } from "./vrmEngine";

export interface AvatarStageProps {
  name?: string;
  mode?: "3d_vrm" | "2d_character" | "rive";
  modelUrl?: string | null;
  imageUrl?: string | null;
  videoUrl?: string | null;
  emotion?: string;
  cognitiveMode?: string;
  focusText?: string;
  amplitude?: number;
  visemes?: VisemeFrame[];
  compact?: boolean;
  liveFace?: string;
  onToggleExpand?: () => void;
}

export function AvatarStage({
  name = "Jaeger",
  mode = "2d_character",
  modelUrl = null,
  imageUrl = null,
  videoUrl = null,
  emotion = "warm",
  cognitiveMode = "observing",
  focusText = "Aware & standing by",
  amplitude = 0,
  visemes = [],
  compact = false,
  liveFace = "vita",
  onToggleExpand,
}: AvatarStageProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const handleRef = useRef<AvatarStageHandle | null>(null);
  const [paused, setPaused] = useState(false);
  const [vrmError, setVrmError] = useState<string>("");
  const [vrmStats, setVrmStats] = useState<{ triangles: number; vrmVersion: string } | null>(null);
  const dragRef = useRef<{ active: boolean; x: number; y: number; yaw: number; pitch: number; zoom: number }>({
    active: false,
    x: 0,
    y: 0,
    yaw: 0,
    pitch: 4,
    zoom: 1,
  });

  const use3D = mode === "3d_vrm" && Boolean(modelUrl);
  const liveAvatarUp = useAvatarApp();

  useEffect(() => {
    if (!use3D || !modelUrl || !canvasRef.current) return;
    let cancelled = false;
    setVrmError("");
    void import("./vrmEngine")
      .then((mod) => mod.mountStudioVrmStage(canvasRef.current!, modelUrl, { fps: compact ? 30 : 45 }))
      .then((handle) => {
        if (cancelled) {
          handle.dispose();
          return;
        }
        handleRef.current = handle;
        handle.setEmotion(emotion);
        const s = handle.stats();
        setVrmStats({ triangles: s.triangles, vrmVersion: s.vrmVersion });
      })
      .catch((err: unknown) => {
        if (!cancelled) setVrmError(err instanceof Error ? err.message : "Failed to load VRM model");
      });
    return () => {
      cancelled = true;
      handleRef.current?.dispose();
      handleRef.current = null;
    };
  }, [use3D, modelUrl, compact]);

  useEffect(() => {
    handleRef.current?.setEmotion(emotion);
  }, [emotion]);

  useEffect(() => {
    handleRef.current?.setAmplitude(amplitude);
  }, [amplitude]);

  useEffect(() => {
    if (visemes.length > 0) handleRef.current?.playVisemes(visemes);
  }, [visemes]);

  useEffect(() => {
    handleRef.current?.setPaused(paused);
  }, [paused]);

  const modeLabel =
    cognitiveMode === "serving_owner"
      ? "Working for You"
      : cognitiveMode === "idle_life"
        ? "Playing Minecraft"
        : cognitiveMode === "proactive_work"
          ? "Running Business Ops"
          : cognitiveMode === "estop"
            ? "E-Stop Latched"
            : "Aware · Observing";

  return (
    <div className={`jg-avatar-stage ${compact ? "is-compact" : ""}`}>
      <div className="jg-avatar-stage-head">
        <div className="jg-avatar-stage-title">
          <span className={`jg-dot is-${cognitiveMode}`} />
          <strong>{name}</strong>
          <span className="jg-pill">{modeLabel}</span>
          {liveAvatarUp && !paused && (
            <span className="jg-pill jg-pill-live">live · {liveFace}</span>
          )}
        </div>
        <div className="jg-avatar-stage-actions">
          <button
            type="button"
            className="jg-btn-ghost"
            onClick={() => setPaused((p) => !p)}
            title={paused ? "Resume avatar rendering" : "Pause rendering (0% GPU)"}
          >
            {paused ? "Resume" : "0% GPU"}
          </button>
          {onToggleExpand && (
            <button type="button" className="jg-btn-ghost" onClick={onToggleExpand}>
              {compact ? "Expand" : "Minimize"}
            </button>
          )}
        </div>
      </div>

      <div
        className="jg-avatar-viewport"
        onPointerMove={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          const nx = ((e.clientX - rect.left) / Math.max(1, rect.width) - 0.5) * 2;
          const ny = ((e.clientY - rect.top) / Math.max(1, rect.height) - 0.5) * 2;
          handleRef.current?.setPointer(nx, ny);
          if (dragRef.current.active) {
            dragRef.current.yaw += (e.clientX - dragRef.current.x) * 0.45;
            dragRef.current.pitch = Math.max(-25, Math.min(35, dragRef.current.pitch + (e.clientY - dragRef.current.y) * 0.35));
            dragRef.current.x = e.clientX;
            dragRef.current.y = e.clientY;
            handleRef.current?.setOrbit(dragRef.current.yaw, dragRef.current.pitch, dragRef.current.zoom);
          }
        }}
        onPointerDown={(e) => {
          dragRef.current.active = true;
          dragRef.current.x = e.clientX;
          dragRef.current.y = e.clientY;
        }}
        onPointerUp={() => {
          dragRef.current.active = false;
        }}
        onWheel={(e) => {
          if (!use3D) return;
          dragRef.current.zoom = Math.max(0.6, Math.min(2.2, dragRef.current.zoom - e.deltaY * 0.001));
          handleRef.current?.setOrbit(dragRef.current.yaw, dragRef.current.pitch, dragRef.current.zoom);
        }}
      >
        {liveAvatarUp && !paused ? (
          <LiveAvatarApp face={liveFace} compact={compact} />
        ) : use3D ? (
          <>
            <canvas ref={canvasRef} className="jg-avatar-canvas" />
            {vrmError && <div className="jg-avatar-error">{vrmError}</div>}
          </>
        ) : (
          <Character2DStage
            name={name}
            emotion={emotion}
            mode={cognitiveMode}
            amplitude={amplitude}
            visemes={visemes}
            imageUrl={imageUrl}
            videoUrl={videoUrl}
            paused={paused}
            compact={compact}
          />
        )}
      </div>

      <div className="jg-avatar-stage-foot">
        <span className="jg-muted">{focusText}</span>
        {vrmStats && <span className="jg-muted">VRM {vrmStats.vrmVersion} · {vrmStats.triangles.toLocaleString()} tris</span>}
      </div>
    </div>
  );
}
