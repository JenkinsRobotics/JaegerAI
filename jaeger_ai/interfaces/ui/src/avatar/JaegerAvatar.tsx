import { useEffect, useState } from "react";
import artwork from "../assets/characters/jaeger-emotes.png";
import { ClipAvatar } from "./ClipAvatar";
import { useReducedMotion } from "./AvatarStage";
import { STATUS_TEXT, type ClipState } from "./avatar";
import "./jaegerAvatar.css";

export const EXPRESSIONS = ["Idle", "Listening", "Thinking", "Determined", "Your move", "Eureka", "Resting", "Facepalm", "Laughing", "Playful curiosity", "Playful invitation", "Peekaboo"] as const;
export const STATE_EXPRESSION: Record<ClipState, number> = {
  idle: 0, working: 2, making_something: 3, waiting: 4, connecting: 6, milestone_level_up: 5,
};

type JaegerAvatarProps = {
  state?: ClipState;
  size?: number;
  name?: string;
  still?: boolean;
  showStatus?: boolean;
  portraitOverride?: string;
};

export function JaegerAvatar({ state = "idle", size = 94, name = "Jaeger", still = false, showStatus = false, portraitOverride }: JaegerAvatarProps) {
  const reduced = useReducedMotion();
  const [choice, setChoice] = useState(-1);
  useEffect(() => { setChoice(-1); }, [state]);
  useEffect(() => {
    if (choice < 0) return;
    const timer = setTimeout(() => setChoice(-1), 8000);
    return () => clearTimeout(timer);
  }, [choice]);
  if (portraitOverride) return <ClipAvatar state={state} size={size} name={name} still={still || reduced} showStatus={showStatus} portraitOverride={portraitOverride} />;
  const expression = choice < 0 ? STATE_EXPRESSION[state] : choice;
  return <span className="jg-jaeger-avatar" data-avatar-state={state} data-expression={EXPRESSIONS[expression]} data-motion={still || reduced ? "still" : "animated"} style={{ width: size, height: size }}>
    <span key={expression} className="jg-jaeger-emote" role="img" aria-label={`${name}: ${EXPRESSIONS[expression]}`} style={{ backgroundImage: `url(${artwork})`, backgroundPosition: `${expression % 4 * 100 / 3}% ${Math.floor(expression / 4) * 50}%` }} />
    <select className="jg-jaeger-expression-picker" aria-label="Avatar expression" title="Preview an expression for 8 seconds" value={choice} onChange={event => setChoice(Number(event.target.value))}>
      <option value={-1}>Automatic</option>
      {EXPRESSIONS.map((label, index) => <option key={label} value={index}>{label}</option>)}
    </select>
    {showStatus && <span className="jg-clip-status" role="status">{STATUS_TEXT[state]}</span>}
  </span>;
}
