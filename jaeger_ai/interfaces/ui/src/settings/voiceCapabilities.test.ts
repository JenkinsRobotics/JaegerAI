import { expect, it } from "vitest";
import { speechAvailability } from "../platform/native";
it("reports unknown/denied native status honestly and distinguishes dictation from spoken turns", () => {
  expect(speechAvailability(undefined, undefined)).toEqual({ dictation: false, voiceChat: false });
  expect(speechAvailability({}, {})).toEqual({ dictation: false, voiceChat: false });
  expect(speechAvailability({ available: true, permission: "denied" }, { available: true })).toEqual({ dictation: false, voiceChat: false });
  expect(speechAvailability({ available: true }, { available: false })).toEqual({ dictation: true, voiceChat: false });
  expect(speechAvailability({ available: true }, { available: true })).toEqual({ dictation: true, voiceChat: true });
});
