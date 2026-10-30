/**
 * keyedLocalStorage — enumerate localStorage keys by prefix.
 *
 * `Object.keys(localStorage)` does NOT work in jsdom (it returns []), so every
 * `Object.keys(localStorage).filter(...)` in the app silently matched nothing
 * under test. This helper walks the real Storage interface (`length` + `key(i)`)
 * and works in both the browser and jsdom.
 */

/** Return all localStorage keys that start with `prefix`. */
export function keysWithPrefix(prefix: string): string[] {
  const out: string[] = []
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i)
      if (k && k.startsWith(prefix)) out.push(k)
    }
  } catch {
    // storage unavailable — return what we have
  }
  return out
}
