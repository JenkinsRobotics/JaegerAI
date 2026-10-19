/** Device-local, nonsecurity typography preference. Never writes Gateway settings. */
export const TEXT_SIZE_KEY = "jaeger.ui.text-size";
export const TEXT_SIZE_EVENT = "jaeger-text-size";
export function clampTextSize(value: unknown): number {
  const n = Number(value);
  return Number.isFinite(n) && n >= 12 && n <= 22 ? Math.round(n) : 14;
}
export function storedTextSize(): number {
  try { return clampTextSize(localStorage.getItem(TEXT_SIZE_KEY)); } catch { return 14; }
}
export function currentTextSize(): number {
  return clampTextSize(parseFloat(document.documentElement.style.getPropertyValue("--jg-font-size-base")) || storedTextSize());
}
export function applyTextSize(value: number, persist = true): number {
  const size = clampTextSize(value);
  if (persist) try { localStorage.setItem(TEXT_SIZE_KEY, String(size)); } catch { /* Device storage unavailable. */ }
  const style = document.documentElement.style;
  style.setProperty("--jg-font-size-base", `${size}px`);
  style.setProperty("--jg-font-small", `${Math.max(11, size - 1)}px`);
  style.setProperty("--jg-font-tiny", `${Math.max(10, size - 2)}px`);
  style.setProperty("--jg-line-height-base", `${Math.round(size * 1.57)}px`);
  window.dispatchEvent(new Event(TEXT_SIZE_EVENT));
  return size;
}
