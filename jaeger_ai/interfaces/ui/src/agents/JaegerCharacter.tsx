import { useId } from "react";
import portrait from "../assets/characters/jaeger-sculpted.png";
import "./jaegerCharacter.css";

/** A feathered mouth layer lets the rendered grin move independently of breathing. */
export function JaegerCharacter() {
  const id = useId();
  const mask = `${id}-smile`;
  const feather = `${id}-feather`;
  return <svg className="jg-character" viewBox="0 0 1000 1000" aria-hidden="true" focusable="false">
    <defs>
      <filter id={feather} x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="5" /></filter>
      <mask id={mask} maskUnits="userSpaceOnUse" x="0" y="0" width="1000" height="1000">
        <ellipse cx="495" cy="350" rx="155" ry="86" fill="white" filter={`url(#${feather})`} />
      </mask>
    </defs>
    <g className="jg-character__body">
      <image href={portrait} width="1000" height="1000" />
      <g className="jg-character__smile"><image href={portrait} width="1000" height="1000" mask={`url(#${mask})`} /></g>
    </g>
  </svg>;
}
