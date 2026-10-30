/** Character card images, bundled through Vite so they are served from /assets/ by any WebUI build
 * (the old /characters/*.png public paths collided with the /characters page and were never served). */
const CARDS = import.meta.glob("../assets/characters/*.png", { eager: true, query: "?url", import: "default" }) as Record<string, string>;

/** `/characters/jarvis.png` (as stored in CHARACTERS) → the bundled asset URL, or null when there is no card. */
export function cardUrlFor(url: string | null | undefined): string | null {
  if (!url) return null;
  const name = url.split("/").pop();
  return CARDS[`../assets/characters/${name}`] ?? null;
}
