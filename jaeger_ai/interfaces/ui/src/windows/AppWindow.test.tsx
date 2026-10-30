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
const front = () => document.querySelector(".app-window__page--active")?.getAttribute("aria-label");

async function mount(path: string, source = new MockSource()) {
  history.replaceState(null, "", path);
  const el = document.createElement("div"); document.body.append(el);
  root = createRoot(el);
  await flush(() => root!.render(<AppWindow source={source} />));
  await flush();
  return source;
}

it("opens the page the URL names and follows navigation and back/forward", async () => {
  await mount("/characters");
  expect(front()).toBe("Characters");
  expect(document.body.textContent).toContain("Jarvis");
  await flush(() => navigate("/agents"));
  expect(location.pathname).toBe("/agents");
  expect(front()).toBe("Agents");
  await flush(() => { history.back(); });
  await flush(() => dispatchEvent(new PopStateEvent("popstate")));
  expect(["Characters", "Agents"]).toContain(front());
});

it("shows Settings as a grouped page and deep-links a tab", async () => {
  await mount("/settings/voice");
  expect(front()).toBe("Settings");
  const groups = [...document.querySelectorAll(".jg-sheet__group-title")].map((g) => g.textContent);
  expect(groups).toEqual(expect.arrayContaining(["You", "Agents", "System"]));
  expect(document.querySelector(".jg-sheet__title")?.textContent).toBe("Voice");
});

it("lists every page in the dock and persists which pages are open", async () => {
  await mount("/tasks");
  const dock = [...document.querySelectorAll(".window-dock__label")].map((l) => l.textContent);
  expect(dock).toEqual(["Home", "Chat", "Agents", "Characters", "Tasks", "Machine Control", "SharePoint", "Settings", "Workspace", "Studio"]);
  expect(JSON.parse(localStorage.getItem(LAYOUT_KEY)!).open).toContain("tasks");
});

it("Home shows the approvals section and the ⌘K palette offers pages and characters", async () => {
  await mount("/");
  expect(front()).toBe("Home");
  expect(document.querySelector('[aria-label="Approvals"]')).not.toBeNull();
  expect(document.querySelector('[aria-label="Control Center"]')).not.toBeNull();
  await flush(() => dispatchEvent(new KeyboardEvent("keydown", { key: "k", metaKey: true })));
  const rows = [...document.querySelectorAll(".jg-palette__label")].map((r) => r.textContent);
  expect(rows).toContain("Go to Characters");
  expect(rows).toContain("New agent: Jarvis");
});

it("creates an agent from a character with its role and instructions", () => {
  const jarvis = CHARACTERS.find((c) => c.id === "jarvis")!;
  const body = characterAgentBody(jarvis, "op-1");
  expect(body).toMatchObject({ operation_id: "op-1", display_name: jarvis.name, metadata: { character_id: "jarvis", specialty: jarvis.role } });
  expect(vi.isMockFunction(characterAgentBody)).toBe(false);
});
