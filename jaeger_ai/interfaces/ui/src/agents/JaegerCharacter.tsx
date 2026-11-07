import { useId } from "react";
import "./jaegerCharacter.css";

/** SVG joints keep body movement independent of the profile's hit target. */
export function JaegerCharacter() {
  const halo = useId();
  return <svg className="jg-character" viewBox="0 0 160 180" aria-hidden="true" focusable="false">
    <defs><radialGradient id={halo}><stop offset=".35" stopColor="var(--jg-character-ink)" stopOpacity=".85"/><stop offset="1" stopColor="var(--jg-character-ink)" stopOpacity="0"/></radialGradient></defs>
    <ellipse cx="80" cy="91" rx="77" ry="88" fill={`url(#${halo})`}/>
    <g fill="var(--jg-character-ink)">{Array.from({length: 96}, (_, i) => {
      const a = i * 2.399963, r = .66 + ((i * 17) % 31) / 100;
      return <circle key={i} cx={80 + Math.cos(a)*72*r} cy={88 + Math.sin(a)*80*r} r={.4+(i%4)*.3} opacity={.12+(i%5)*.09}/>;
    })}</g>
    <ellipse cx="82" cy="161" rx="65" ry="12" fill="var(--jg-character-ink)"/>
    <g className="jg-character__body">
      <path className="jg-character__skin" d="M76 117C91 111 105 120 120 133L140 147Q149 159 132 161L100 161Q89 172 78 165L70 147Z"/>
      <path className="jg-character__skin" d="M61 101Q44 97 41 115L39 148Q26 157 30 167Q35 175 47 168L64 153L74 127Z"/>
      <path className="jg-character__skin" d="M64 66Q79 60 96 70Q108 83 101 103L99 128Q85 142 63 128L56 99Q50 79 64 66Z"/>
      <path className="jg-character__limb" d="M98 79Q111 98 111 119L105 140"/>
      <ellipse className="jg-character__skin" cx="104" cy="142" rx="8" ry="11" transform="rotate(18 104 142)"/>
      <g className="jg-character__head">
        <path className="jg-character__skin" d="M53 36Q52 12 77 12Q104 11 105 36L103 52Q111 53 105 63L98 67Q93 81 78 81Q62 80 57 67Q46 64 49 54L53 52Z"/>
        <path className="jg-character__mouth" d="M57 57Q78 68 100 57L96 71Q78 84 61 71Z"/>
        <path className="jg-character__teeth" d="M59 64Q78 75 98 64M64 61L66 74M71 64L72 77M79 65V78M87 64L86 77M94 61L92 74"/>
      </g>
      <g className="jg-character__arm"><path className="jg-character__limb" d="M60 78Q41 83 35 98"/>
        <g className="jg-character__forearm"><path className="jg-character__limb" d="M35 98L57 108"/>
          <path className="jg-character__skin" d="M53 102Q61 99 66 106L71 116Q71 120 67 118L60 112L64 122Q63 126 59 121L54 114Q47 110 53 102Z"/>
        </g>
      </g>
    </g>
  </svg>;
}
