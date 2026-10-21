import { afterEach, expect, test } from "vitest";
import { installModeSync } from "./appearanceSync";

let stop = () => {};
afterEach(() => { stop(); document.documentElement.classList.remove("aether-light-theme"); delete document.documentElement.dataset.mode; });

test("data-mode follows the Aether light class", async () => {
  stop = installModeSync();
  expect(document.documentElement.dataset.mode).toBe("dark");
  document.documentElement.classList.add("aether-light-theme");
  await Promise.resolve();
  expect(document.documentElement.dataset.mode).toBe("light");
  document.documentElement.classList.remove("aether-light-theme");
  await Promise.resolve();
  expect(document.documentElement.dataset.mode).toBe("dark");
});
