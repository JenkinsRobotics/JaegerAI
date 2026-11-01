/** The Jaeger mark (J-085): renders the chosen logo as a crisp inline vector (or the sanitized custom image). */
import { SHIELD_J_PATH, SHIELD_J_VIEWBOX, useLogo, type LogoId } from "./logo";

const SHIELD = "M32 5.5 53 12.6v16.6c0 13.6-8.6 24-21 29.3C19.6 53.2 11 42.8 11 29.2V12.6z";
const J = "M41 13v24.5C41 45 36.6 50 29.6 50 24.4 50 20.6 47.4 19 43";

export function LogoArt({ id, custom }: { id: LogoId; custom?: string }) {
  switch (id) {
    case "custom":
      return custom ? <img src={custom} alt="" draggable={false} /> : <LogoArt id="shield-j" />;
    case "shield-j-tile":
      return (
        <svg viewBox="0 0 64 64" aria-hidden="true">
          <rect width="64" height="64" rx="14.5" fill="var(--jg-color-accent, #1f6fe5)" />
          <svg x="9" y="8.5" width="46" height="47" viewBox={SHIELD_J_VIEWBOX}><path fill="#fff" fillRule="evenodd" d={SHIELD_J_PATH} /></svg>
        </svg>
      );
    case "shield":
      return <svg viewBox="0 0 64 64" aria-hidden="true"><path d={SHIELD} fill="none" stroke="currentColor" strokeWidth="4.5" strokeLinejoin="round" /></svg>;
    case "j":
      return <svg viewBox="0 0 64 64" aria-hidden="true"><path d={`M31 13h16M${J.slice(1)}`} fill="none" stroke="currentColor" strokeWidth="7" strokeLinecap="round" strokeLinejoin="round" /></svg>;
    case "wordmark":
      return (
        <svg viewBox="0 0 232 64" aria-hidden="true">
          <svg x="0" y="4" width="54" height="56" viewBox={SHIELD_J_VIEWBOX}><path fill="currentColor" fillRule="evenodd" d={SHIELD_J_PATH} /></svg>
          <text x="66" y="44" fill="currentColor" fontFamily="var(--jg-font-family, -apple-system, BlinkMacSystemFont, 'SF Pro Display', system-ui, sans-serif)" fontSize="33" fontWeight="700" letterSpacing="5">JAEGER</text>
        </svg>
      );
    case "classic":
      return (
        <svg viewBox="0 0 64 64" aria-hidden="true">
          <rect width="64" height="64" rx="14" fill="#121212" />
          <path d="M32 8.5 52 15v15.4c0 12.6-8 22.2-20 27.1-12-4.9-20-14.5-20-27.1V15z" fill="#d63a3a" />
          <path d="M37.5 20v15.6c0 6-3.6 9.4-9 9.4-3.2 0-5.8-1.2-7.5-3.4" fill="none" stroke="#fff" strokeWidth="5.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    default:
      return <svg viewBox={SHIELD_J_VIEWBOX} aria-hidden="true"><path fill="currentColor" fillRule="evenodd" d={SHIELD_J_PATH} /></svg>;
  }
}

/** The app's current mark. `label` makes it announced; otherwise decorative. */
export function JaegerMark({ className, label }: { className?: string; label?: string }) {
  const s = useLogo();
  return (
    <span className={`jg-mark${className ? ` ${className}` : ""}`} data-logo={s.id} role={label ? "img" : undefined} aria-label={label} aria-hidden={label ? undefined : true}>
      <LogoArt id={s.id} custom={s.custom} />
    </span>
  );
}

