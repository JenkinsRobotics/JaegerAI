import { describe, expect, it } from "vitest";
import { legacyRedirect, parseRoute, pathOf } from "./router";

describe("router", () => {
  it("parses real page paths and falls back to home", () => {
    expect(parseRoute("/").page).toBe("home");
    expect(parseRoute("/chat").page).toBe("chat");
    expect(parseRoute("/settings/voice/").rest).toBe("voice");
    expect(parseRoute("/nope").page).toBe("home");
    expect(parseRoute("/chat", "?agent=native:jaeger").params.get("agent")).toBe("native:jaeger");
  });
  it("maps every page to a path", () => {
    expect(pathOf("home")).toBe("/");
    expect(pathOf("characters")).toBe("/characters");
  });
  it("rewrites the old ?ui= links to the matching page", () => {
    expect(legacyRedirect("/", "?ui=apple")).toBe("/characters");
    expect(legacyRedirect("/", "?ui=windows")).toBe("/");
    expect(legacyRedirect("/", "?ui=default&home=fallback")).toBe("/chat?home=fallback");
    expect(legacyRedirect("/tasks", "?ui=apple")).toBe("/tasks");
    expect(legacyRedirect("/", "")).toBeNull();
  });
});
