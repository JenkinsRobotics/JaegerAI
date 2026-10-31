/**
 * The roster on the Agents page, in two rows:
 * - Characters: persona characters with portrait art (category "fun" in CHARACTERS).
 * - Bots: plain working specialists (category "professional"). Their card PNGs are a shared
 *   placeholder, so they get a robot card in the RobotIcon style instead of art.
 * Both open the same detail (/agents/characters?character=<id>) where "Create agent" works.
 */
import { CHARACTERS, type CharacterBio } from "../components/CharacterLibrary";
import { cardUrlFor } from "../characters/cards";
import { RobotIcon } from "../agents/RobotIcon";

export function characterRoster(): CharacterBio[] { return CHARACTERS; }
/** Split by the data's own `category` field — no names are hard-coded. */
export function rosterGroups(all: CharacterBio[] = CHARACTERS): { characters: CharacterBio[]; bots: CharacterBio[] } {
  return { characters: all.filter((c) => c.category !== "professional"), bots: all.filter((c) => c.category === "professional") };
}

export function CharacterRoster({ onNavigate }: { onNavigate: (to: string) => void }) {
  const { characters, bots } = rosterGroups();
  const open = (c: CharacterBio) => onNavigate(`/agents/characters?character=${encodeURIComponent(c.id)}`);
  return (
    <>
      <section className="jg-u-chars" aria-label="Characters">
        <div className="jg-u-chars__head">
          <h2>Characters <span>{characters.length}</span></h2>
          <button type="button" className="jg-u-btn" onClick={() => onNavigate("/agents/characters")}>Browse all</button>
        </div>
        <ul className="jg-u-chars__list">
          {characters.map((c) => {
            const src = cardUrlFor(c.cardUrl);
            return (
              <li key={c.id}>
                <button type="button" className="jg-u-chars__card" title={`${c.name} — ${c.role}`} onClick={() => open(c)}>
                  {src ? <img src={src} alt="" loading="lazy" /> : <span className="jg-u-chars__ph" aria-hidden="true">{c.name.slice(0, 1)}</span>}
                  <strong>{c.name}</strong>
                  <span>{c.role}</span>
                </button>
              </li>
            );
          })}
        </ul>
      </section>
      <section className="jg-u-chars jg-u-bots" aria-label="Bots">
        <div className="jg-u-chars__head">
          <h2>Bots <span>{bots.length}</span></h2>
        </div>
        <ul className="jg-u-chars__list jg-u-bots__list">
          {bots.map((c) => (
            <li key={c.id}>
              <button type="button" className="jg-u-bots__card" title={`${c.name} — ${c.role}`} onClick={() => open(c)}>
                <span className="jg-u-bots__face" aria-hidden="true"><RobotIcon id={`character:${c.id}`} name={c.name} size={44} /></span>
                <strong>{c.name}</strong>
                <span>{c.role}</span>
              </button>
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}
