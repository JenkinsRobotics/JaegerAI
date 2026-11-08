import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import jaegerArtwork from "../assets/characters/jaeger-signature-grin.png";
import poseArtwork from "../assets/characters/jaeger-approved-poses.png";
import { ClipAvatar } from "./ClipAvatar";
import { useReducedMotion } from "./AvatarStage";
import { STATUS_TEXT, type ClipState } from "./avatar";
import "./jaegerAvatar.css";

export const APPROVED_POSES = [
  { number: 1, label: "Composed" },
  { number: 2, label: "Listening" },
  { number: 3, label: "Calculating" },
  { number: 5, label: "Your move" },
  { number: 6, label: "Eureka" },
  { number: 7, label: "Resting" },
  { number: 8, label: "Facepalm" },
  { number: 10, label: "Curious grin" },
  { number: 11, label: "Inviting grin" },
  { number: 12, label: "Peekaboo" },
] as const;
export const ACTIVITY_POSE: Record<ClipState, number> = {
  idle: -1, working: 2, making_something: 2, waiting: 3, connecting: 5, milestone_level_up: 4,
};

type JaegerAvatarProps = {
  state?: ClipState;
  size?: number;
  name?: string;
  still?: boolean;
  showStatus?: boolean;
  portraitOverride?: string;
};

/**
 * A 2D cutout rig made from the canonical sculpted Jaeger artwork. Every
 * layer uses the same source image, so the character is pixel-identical when
 * resting; only the clipped smile and arms move.
 */
export function JaegerAvatar({
  state = "idle",
  size = 94,
  name = "Jaeger",
  still = false,
  showStatus = false,
  portraitOverride,
}: JaegerAvatarProps) {
  const rig = useRef<HTMLSpanElement>(null);
  const reduced = useReducedMotion();
  const calm = still || reduced;
  const [preview, setPreview] = useState(-1);
  useEffect(() => { setPreview(-1); }, [state]);
  useEffect(() => {
    if (preview < 0) return;
    const timer = setTimeout(() => setPreview(-1), 8000);
    return () => clearTimeout(timer);
  }, [preview]);
  const poseIndex = preview < 0 ? ACTIVITY_POSE[state] : preview;
  const pose = APPROVED_POSES[poseIndex];

  if (portraitOverride) {
    return <ClipAvatar state={state} size={size} name={name} still={calm} showStatus={showStatus} portraitOverride={portraitOverride} />;
  }

  const point = (event: ReactPointerEvent<HTMLSpanElement>) => {
    if (calm) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const x = Math.max(-1, Math.min(1, ((event.clientX - rect.left) / rect.width) * 2 - 1));
    const y = Math.max(-1, Math.min(1, ((event.clientY - rect.top) / rect.height) * 2 - 1));
    rig.current?.style.setProperty("--jg-look-x", `${(x * 1.2).toFixed(2)}px`);
    rig.current?.style.setProperty("--jg-look-y", `${(y * 0.7).toFixed(2)}px`);
  };
  const center = () => {
    rig.current?.style.setProperty("--jg-look-x", "0px");
    rig.current?.style.setProperty("--jg-look-y", "0px");
  };

  return <span
    ref={rig}
    className="jg-jaeger-avatar"
    data-avatar-state={state}
    data-pose={pose?.number ?? "signature"}
    data-motion={calm ? "still" : "rigged"}
    style={{ width: size, height: size }}
    onPointerMove={point}
    onPointerLeave={center}
  >
    {pose ? <span key={pose.number} className="jg-jaeger-pose" role="img" aria-label={`${name} avatar`} title={pose.label} style={{ backgroundImage: `url(${poseArtwork})`, backgroundPosition: `${poseIndex % 5 * 25}% ${Math.floor(poseIndex / 5) * 100}%` }} /> : <span className="jg-jaeger-cutout" role="img" aria-label={`${name} avatar`}>
      <img className="jg-jaeger-cutout__base" src={jaegerArtwork} alt="" draggable={false} />
      <span className="jg-jaeger-cutout__part jg-jaeger-cutout__smile" aria-hidden="true">
        <img src={jaegerArtwork} alt="" draggable={false} />
      </span>
      <span className="jg-jaeger-cutout__part jg-jaeger-cutout__arm--raised" aria-hidden="true">
        <img src={jaegerArtwork} alt="" draggable={false} />
      </span>
      <span className="jg-jaeger-cutout__part jg-jaeger-cutout__arm--grounded" aria-hidden="true">
        <img src={jaegerArtwork} alt="" draggable={false} />
      </span>
    </span>}
    <select className="jg-jaeger-pose-picker" aria-label="Avatar pose" title="Preview a pose for 8 seconds" value={preview} onChange={event => setPreview(Number(event.target.value))}>
      <option value={-1}>Automatic</option>
      {APPROVED_POSES.map((item, index) => <option key={item.number} value={index}>{item.number}. {item.label}</option>)}
    </select>
    {showStatus && <span className="jg-clip-status" role="status">{STATUS_TEXT[state]}</span>}
  </span>;
}
