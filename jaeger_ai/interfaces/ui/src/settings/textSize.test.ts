import { afterEach, expect, it } from "vitest";
import { applyTextSize, clampTextSize, currentTextSize, storedTextSize, TEXT_SIZE_KEY } from "./textSize";
afterEach(() => { localStorage.clear(); document.documentElement.removeAttribute("style"); });
it("restores a bounded preference and applies chat/composer typography without a backend mutation", () => {
  for (const value of [null, "oops", 0, 1000, -1]) expect(clampTextSize(value)).toBe(14);
  applyTextSize(20);
  expect(localStorage.getItem(TEXT_SIZE_KEY)).toBe("20");
  expect(storedTextSize()).toBe(20);
  expect(currentTextSize()).toBe(20);
  expect(document.documentElement.style.getPropertyValue("--jg-line-height-base")).toBe("31px");
  applyTextSize(14);
  expect(currentTextSize()).toBe(14);
});
