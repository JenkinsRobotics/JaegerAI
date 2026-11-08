import { describe, expect, it } from "vitest";
import { LEGACY_PATHS, PAGES, SUBTABS, canonicalPath, legacyRedirect, parseRoute, pathOf } from "./router";

describe("router", () => {
  it("keeps existing routes and exposes companion destinations", () => {
    expect(PAGES).toEqual(["chat", "agents", "work", "research", "studio", "machine", "library", "automations", "feed", "settings"]);
  });
  it("opens / to Chat, keeps /home, and falls back to Chat", () => {
    expect(parseRoute("/").page).toBe("chat");
    expect(parseRoute("/home").page).toBe("work");
    expect(parseRoute("/chat").page).toBe("chat");
    expect(parseRoute("/settings/voice/").rest).toBe("voice");
    expect(parseRoute("/nope").page).toBe("chat");
    expect(parseRoute("/chat", "?agent=native:jaeger").params.get("agent")).toBe("native:jaeger");
  });
  it("resolves sub-tabs, defaulting to the first", () => {
    expect(parseRoute("/work")).toMatchObject({ page: "work", sub: "pipeline", rest: "" });
    expect(parseRoute("/work/tasks/gallery")).toMatchObject({ page: "work", sub: "tasks", rest: "gallery" });
    expect(parseRoute("/research/knowledge").sub).toBe("knowledge");
    expect(parseRoute("/home").sub).toBe("pipeline");
    expect(parseRoute("/home/widgets")).toMatchObject({ page: "settings", rest: "widgets" });
  });
  it("maps every page and sub-tab to a path", () => {
    expect(pathOf("chat")).toBe("/");
    expect(pathOf("home")).toBe("/home");
    expect(pathOf("home", "widgets")).toBe("/home/widgets");
    expect(pathOf("agents", "characters")).toBe("/agents/characters");
    expect(canonicalPath(pathOf("models", "library"))).toBe("/settings/models/library");
    for (const p of PAGES) for (const t of SUBTABS[p] ?? []) expect(parseRoute(pathOf(p, t.id))).toMatchObject({ page: p, sub: t.id });
  });
  it.each([
    ["/characters", "agents", "characters"], ["/tasks", "work", "tasks"], ["/calendar", "work", "calendar"],
    ["/documents", "research", "documents"], ["/knowledge", "agents", "knowledge"],

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
    expect(legacyRedirect("/", "?ui=apple")).toBe("/chat");
    expect(legacyRedirect("/", "?ui=windows")).toBe("/work");
    expect(legacyRedirect("/", "?ui=default&home=fallback")).toBe("/chat?home=fallback");
    expect(legacyRedirect("/", "")).toBeNull();
  });
  it("opens bookmarked Apple chat links in Chat and preserves explicit destinations", () => {
    const redirect = legacyRedirect("/", "?ui=apple&session=owned&agent=native%3Ajaeger")!;
    const url = new URL(redirect, "https://jaeger.test");
    expect(parseRoute(url.pathname, url.search)).toMatchObject({page:"chat"});
    expect(url.searchParams.get("session")).toBe("owned");
    expect(url.searchParams.get("agent")).toBe("native:jaeger");
    expect(legacyRedirect("/agents/characters", "?ui=apple")).toBe("/agents/characters");
  });
});

describe("Rev 3 complete destination migration", () => {
  it.each([
    ["/home", "/work"], ["/home/overview", "/work"], ["/home/widgets", "/settings/widgets"],
    ["/agents/hermes", "/settings/integrations/hermes"], ["/agents/openclaw", "/settings/integrations/openclaw"],
    ["/work/workspace", "/research/workspace"], ["/work/checkpoints", "/settings/checkpoints"],
    ["/research/youtube", "/work/youtube"], ["/research/knowledge", "/agents/knowledge"], ["/research/sharepoint", "/settings/integrations/sharepoint"],
    ["/models", "/settings/models/library"], ["/models/library", "/settings/models/library"], ["/models/compare", "/settings/models/compare"], ["/models/usage", "/settings/models/usage"],
    ["/knowledge", "/agents/knowledge"], ["/sharepoint", "/settings/integrations/sharepoint"], ["/compare", "/settings/models/compare"], ["/workspace", "/settings/widgets"],
  ])("moves %s to %s without losing queries or tails", (old, target) => {
    expect(canonicalPath(old, "?task=real-id")).toBe(`${target}?task=real-id`);
    expect(canonicalPath(`${old}/detail`, "?x=1")).toBe(`${target}/detail?x=1`);
    expect(canonicalPath(target)).toBeNull();
    expect(parseRoute(old)).toMatchObject(parseRoute(target));
  });
});

it("navigates home without a separate workspace mode", async () => {
  const { navigate } = await import("./router");
  history.replaceState(null, "", "/work/tasks");
  navigate("chat");
  expect(location.pathname + location.search).toBe("/");
});

it("keeps the development mock source across internal navigation", async () => {
  const { navigate } = await import("./router");
  history.replaceState(null, "", "/?mock=1");
  navigate("agents");
  expect(location.pathname + location.search).toBe("/agents?mock=1");
  navigate("chat");
  expect(location.pathname + location.search).toBe("/?mock=1");
});
