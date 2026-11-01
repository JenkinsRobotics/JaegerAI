import { describe, expect, it } from "vitest";
import { LEGACY_PATHS, PAGES, SUBTABS, canonicalPath, legacyRedirect, parseRoute, pathOf } from "./router";

describe("router", () => {
  it("has the nine consolidated tabs", () => {
    expect(PAGES).toEqual(["home", "chat", "agents", "work", "research", "studio", "models", "machine", "settings"]);
  });
  it("opens / to Chat, keeps /home, and falls back to Chat", () => {
    expect(parseRoute("/").page).toBe("chat");
    expect(parseRoute("/home").page).toBe("home");
    expect(parseRoute("/chat").page).toBe("chat");
    expect(parseRoute("/settings/voice/").rest).toBe("voice");
    expect(parseRoute("/nope").page).toBe("chat");
    expect(parseRoute("/chat", "?agent=native:jaeger").params.get("agent")).toBe("native:jaeger");
  });
  it("resolves sub-tabs, defaulting to the first", () => {
    expect(parseRoute("/work")).toMatchObject({ page: "work", sub: "pipeline", rest: "" });
    expect(parseRoute("/work/tasks/gallery")).toMatchObject({ page: "work", sub: "tasks", rest: "gallery" });
    expect(parseRoute("/research/knowledge").sub).toBe("knowledge");
    expect(parseRoute("/home").sub).toBe("overview");
    expect(parseRoute("/home/widgets").sub).toBe("widgets");
  });
  it("maps every page and sub-tab to a path", () => {
    expect(pathOf("chat")).toBe("/");
    expect(pathOf("home")).toBe("/home");
    expect(pathOf("home", "widgets")).toBe("/home/widgets");
    expect(pathOf("agents", "characters")).toBe("/agents/characters");
    expect(pathOf("models", "library")).toBe("/models");
    for (const p of PAGES) for (const t of SUBTABS[p] ?? []) expect(parseRoute(pathOf(p, t.id))).toMatchObject({ page: p, sub: t.id });
  });
  it.each([
    ["/characters", "agents", "characters"], ["/tasks", "work", "tasks"], ["/calendar", "work", "calendar"],
    ["/documents", "research", "documents"], ["/knowledge", "research", "knowledge"], ["/sharepoint", "research", "sharepoint"],
    ["/compare", "models", "compare"], ["/workspace", "home", "widgets"],
  ])("redirects retired %s to %s › %s", (old, page, sub) => {
    expect(parseRoute(old)).toMatchObject({ page, sub });
  });
  it("redirects /integrations into Settings and keeps deep-link tails and queries", () => {
    expect(parseRoute("/integrations")).toMatchObject({ page: "settings", rest: "integrations" });
    expect(canonicalPath("/tasks/gallery", "?x=1")).toBe("/work/tasks/gallery?x=1");
    expect(canonicalPath("/characters", "?character=jarvis")).toBe("/agents/characters?character=jarvis");
    expect(canonicalPath("/work/tasks")).toBeNull();
    expect(Object.keys(LEGACY_PATHS).sort()).toEqual(["calendar", "characters", "compare", "documents", "integrations", "knowledge", "sharepoint", "tasks", "workspace"]);
  });
  it("rewrites the old ?ui= links to the matching page", () => {
    expect(legacyRedirect("/", "?ui=apple")).toBe("/agents/characters");
    expect(legacyRedirect("/", "?ui=windows")).toBe("/home");
    expect(legacyRedirect("/", "?ui=default&home=fallback")).toBe("/chat?home=fallback");
    expect(legacyRedirect("/", "")).toBeNull();
  });
});
