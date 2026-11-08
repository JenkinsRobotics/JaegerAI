import { useRef, type PointerEvent as ReactPointerEvent } from "react";
import jaegerArtwork from "../assets/characters/jaeger-sculpted.png";
import { ClipAvatar } from "./ClipAvatar";
import { useReducedMotion } from "./AvatarStage";
import { STATUS_TEXT, type ClipState } from "./avatar";
import "./jaegerAvatar.css";

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
    data-motion={calm ? "still" : "rigged"}
    style={{ width: size, height: size }}
    onPointerMove={point}
    onPointerLeave={center}
  >
    <span className="jg-jaeger-cutout" role="img" aria-label={`${name} avatar`}>
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
    </span>
    {showStatus && <span className="jg-clip-status" role="status">{STATUS_TEXT[state]}</span>}
  </span>;
}
