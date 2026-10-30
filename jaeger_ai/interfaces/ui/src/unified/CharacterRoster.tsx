/**
 * The character roster on the Agents page. In the old Windows UI the Agents tab *was* the
 * "Browse Bots" gallery of all 20 characters; the unified Agents page shows live gateway agents,
 * so the full character roster stays visible here too (cards → /characters detail → create agent).
 */
import { CHARACTERS, type CharacterBio } from "../components/CharacterLibrary";
import { cardUrlFor } from "../characters/cards";

export function characterRoster(): CharacterBio[] { return CHARACTERS; }

export function CharacterRoster({ onNavigate }: { onNavigate: (to: string) => void }) {
  const all = characterRoster();
  return (
    <section className="jg-u-chars" aria-label="Characters">
      <div className="jg-u-chars__head">
        <h2>Characters <span>{all.length}</span></h2>
        <button type="button" className="jg-u-btn" onClick={() => onNavigate("/characters")}>Browse all</button>
      </div>
      <ul className="jg-u-chars__list">
        {all.map((c) => {
          const src = cardUrlFor(c.cardUrl);
          return (
            <li key={c.id}>
              <button type="button" className="jg-u-chars__card" title={`${c.name} — ${c.role}`} onClick={() => onNavigate(`/characters?character=${encodeURIComponent(c.id)}`)}>
                {src ? <img src={src} alt="" loading="lazy" /> : <span className="jg-u-chars__ph" aria-hidden="true">{c.name.slice(0, 1)}</span>}
                <strong>{c.name}</strong>
                <span>{c.role}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
