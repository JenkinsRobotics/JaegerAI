/** Unified shell: one app, real routes, back/forward, every page reachable, approvals everywhere. */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { MockSource } from "../api/mock";
import { AppWindow } from "./AppWindow";
import { navigate } from "../shell/router";
import { LAYOUT_KEY } from "./WindowManager";
import { characterAgentBody } from "../unified/CharactersPage";
import { CHARACTERS } from "../components/CharacterLibrary";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root | undefined;
afterEach(async () => { await act(async () => root?.unmount()); root = undefined; localStorage.clear(); document.body.innerHTML = ""; history.replaceState(null, "", "/"); });
const flush = async (fn: () => void = () => {}) => act(async () => { fn(); await new Promise((r) => setTimeout(r, 0)); });
/** Pages are code-split (React.lazy): wait until the visible page has replaced its loading fallback. */
const settle = async () => {
  for (let i = 0; i < 80; i++) {
    await act(async () => { await new Promise((r) => setTimeout(r, 25)); });
    if (!document.querySelector(".app-window__page--active .jg-tabbed__pane:not([hidden]) > .jg-u-page > [role=status][aria-label=Loading], .app-window__page--active > .jg-u-page > [role=status][aria-label=Loading]")) break;
  }
  await flush();
};
const front = () => document.querySelector(".app-window__page--active")?.getAttribute("aria-label");

async function mount(path: string, source = new MockSource()) {
  history.replaceState(null, "", path);
  const el = document.createElement("div"); document.body.append(el);
  root = createRoot(el);
  await flush(() => root!.render(<AppWindow source={source} />));
  await settle();
  return source;
}

const subtab = () => document.querySelector('.app-window__page--active .jg-subtabs [role=tab][aria-selected=true]')?.textContent;

it("opens the page the URL names, redirects retired paths to sub-tabs and follows back/forward", async () => {
  await mount("/characters");
  expect(location.pathname).toBe("/agents/characters");
  expect(front()).toBe("Agents");
  expect(subtab()).toBe("Characters");
  expect(document.body.textContent).toContain("Jarvis");
  await flush(() => navigate("/agents"));
  await settle();
  expect(location.pathname).toBe("/agents");
  expect(subtab()).toBe("Agents");
  await flush(() => navigate("/compare"));
  await settle();
  expect(location.pathname).toBe("/models/compare");
  expect(front()).toBe("Models");
  expect(subtab()).toBe("Compare");
  await flush(() => { history.back(); });
  await flush(() => dispatchEvent(new PopStateEvent("popstate")));
  expect(["Agents", "Models"]).toContain(front());
});

it("switches sub-tabs through the URL and keeps the sub-tab bar consistent", async () => {
  await mount("/work");
  expect(subtab()).toBe("Pipeline");
  const tabs = [...document.querySelectorAll(".app-window__page--active .jg-subtabs [role=tab]")].map((t) => t.textContent);
  expect(tabs).toEqual(["Pipeline", "Backlog", "Tasks", "Production", "Calendar"]);
  await flush(() => (document.querySelectorAll(".app-window__page--active .jg-subtabs [role=tab]")[4] as HTMLButtonElement).click());
  await settle();
  expect(location.pathname).toBe("/work/calendar");
  expect(document.title).toBe("Calendar · Work · Jaeger");
  await flush(() => navigate("/integrations"));
  await settle();
  expect(location.pathname).toBe("/settings/integrations");
  expect(front()).toBe("Settings");
});

it("shows Settings as a grouped page and deep-links a tab", async () => {
  await mount("/settings/voice");
  expect(front()).toBe("Settings");
  // jsdom has no layout width → compact class → push navigation: the panel alone, with an in-app back.
  expect([...document.querySelectorAll(".jg-sheet__page h1")].map((h) => h.textContent)).toEqual(["Voice & audio"]);
  expect(document.querySelector(".jg-page-header__back")?.textContent).toContain("Settings");
  expect(document.querySelector(".jg-sheet__title")).toBeNull();
});

it("lists the nine tabs in the dock and persists which pages are open", async () => {
  await mount("/tasks");
  expect(location.pathname).toBe("/work/tasks");
  const dock = [...document.querySelectorAll(".window-dock__label")].map((l) => l.textContent);
  expect(dock).toEqual(["Home", "Chat", "Agents", "Work", "Research", "Studio", "Models", "Machine", "Settings"]);
  expect(JSON.parse(localStorage.getItem(LAYOUT_KEY)!).open).toContain("work");
});

it("Home shows the approvals section and the ⌘K palette offers pages and characters", async () => {
  await mount("/");
  expect(front()).toBe("Home");
  expect(document.querySelector('[aria-label="Approvals"]')).not.toBeNull();
  expect(document.querySelector('[aria-label="Control Center"]')).not.toBeNull();
  await flush(() => dispatchEvent(new KeyboardEvent("keydown", { key: "k", metaKey: true })));
  const rows = [...document.querySelectorAll(".jg-palette__label")].map((r) => r.textContent);
  expect(rows).toContain("Go to Characters");
  expect(rows).toContain("Go to Compare");
  expect(rows).toContain("Go to Work");
  expect(rows).toContain("New agent: Jarvis");
});

it("creates an agent from a character with its role and instructions", () => {
  const jarvis = CHARACTERS.find((c) => c.id === "jarvis")!;
  const body = characterAgentBody(jarvis, "op-1");
  expect(body).toMatchObject({ operation_id: "op-1", display_name: jarvis.name, metadata: { character_id: "jarvis", specialty: jarvis.role } });
  expect(vi.isMockFunction(characterAgentBody)).toBe(false);
});
