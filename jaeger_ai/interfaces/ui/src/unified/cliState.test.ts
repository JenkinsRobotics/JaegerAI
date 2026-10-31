import { expect, it } from "vitest";
import { CLI_STATE } from "./models";
it("labels the 'checking' placeholder rows the cached CLI probe serves on a cold start", () => {
  expect(CLI_STATE.checking).toEqual([undefined, "Checking…"]);
});
