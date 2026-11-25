import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MockSource } from "../api/mock";
import { canonicalDestinationOf, navigate, parseRoute } from "./router";
import { UnifiedShell } from "./UnifiedShell";

vi.mock("../chat/ChatPane", () => ({
  ChatPane: ({ sessionId }: { sessionId: string }) => <div data-chat-session={sessionId}>Chat pane</div>,
}));
vi.mock("../avatar/AvatarPanel", () => ({
  AvatarPanel: ({ agent }: { agent: { id: string } }) => <aside data-avatar-panel={agent.id}>Live Avatar</aside>,
}));
vi.mock("../settings/SettingsView", () => ({
  SettingsView: ({ tab, navigationOpen }: { tab?: string; navigationOpen: boolean }) => <div data-settings-standalone="1" data-tab={tab ?? ""}>{navigationOpen && <nav aria-label="Settings sections">Settings</nav>}</div>,
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
let container: HTMLDivElement | null = null;

async function flush(fn: () => void | Promise<void> = () => {}) {
  await act(async () => {
    await fn();
    await new Promise((r) => setTimeout(r, 0));
  });
}

afterEach(async () => {
  if (root) {
    await act(async () => { root?.unmount(); });
    root = null;
  }
  container?.remove();
  container = null;
  history.replaceState(null, "", "/");
  localStorage.clear();
});

describe("UnifiedShell (Phase 3 single-shell 5-destination consolidation)", () => {
  it("maps all legacy and canonical routes to the 5 Revision 2 destinations", () => {
    expect(canonicalDestinationOf(parseRoute("/"))).toBe("chat");
    expect(canonicalDestinationOf(parseRoute("/agents/characters"))).toBe("agents");
    expect(canonicalDestinationOf(parseRoute("/work/youtube"))).toBe("work");
    expect(canonicalDestinationOf(parseRoute("/automations"))).toBe("work");
    expect(canonicalDestinationOf(parseRoute("/studio"))).toBe("work");
    expect(canonicalDestinationOf(parseRoute("/library"))).toBe("library");
    expect(canonicalDestinationOf(parseRoute("/research/documents"))).toBe("library");
    expect(canonicalDestinationOf(parseRoute("/research/workspace"))).toBe("library");
    expect(canonicalDestinationOf(parseRoute("/settings/models"))).toBe("settings");
    expect(canonicalDestinationOf(parseRoute("/machine"))).toBe("settings");
  });

  it("fits the visible iPhone viewport during keyboard pan and resets on dismissal", async () => {
    const original = Object.getOwnPropertyDescriptor(window, "visualViewport");
    const viewport = Object.assign(new EventTarget(), { height: window.innerHeight, offsetTop: 0, scale: 1 });
    Object.defineProperty(window, "visualViewport", { configurable: true, value: viewport });
    try {
      container = document.createElement("div");
      document.body.appendChild(container);
      root = createRoot(container);
      await flush(() => { root!.render(<UnifiedShell source={new MockSource()} />); });
      const shell = container.querySelector<HTMLElement>(".jg-ushell")!;
      viewport.height = window.innerHeight - 280;
      viewport.dispatchEvent(new Event("resize"));
      viewport.offsetTop = 96;
      viewport.dispatchEvent(new Event("scroll"));
      expect(shell.style.getPropertyValue("--jg-viewport-height")).toBe(`${viewport.height}px`);
      expect(shell.style.getPropertyValue("--jg-viewport-top")).toBe("96px");
      expect(shell.dataset.keyboard).toBe("true");
      viewport.height = window.innerHeight;
      viewport.dispatchEvent(new Event("resize"));
      expect(shell.style.getPropertyValue("--jg-viewport-top")).toBe("0px");
      expect(shell.dataset.keyboard).toBe("false");
      viewport.scale = 1.25;
      viewport.dispatchEvent(new Event("resize"));
      expect(shell.style.getPropertyValue("--jg-viewport-height")).toBe("");
      expect(shell.style.getPropertyValue("--jg-viewport-top")).toBe("");
    } finally {
      if (original) Object.defineProperty(window, "visualViewport", original);
      else delete (window as unknown as { visualViewport?: unknown }).visualViewport;
    }
  });

  it("renders one unified shell, preserves Chat across navigation, toggles live AvatarPanel, and mounts standalone Settings", async () => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    const source = new MockSource();

    await flush(() => { root!.render(<UnifiedShell source={source} />); });

    // Exactly 1 unified shell, no nested AppWindow or legacy StableDemo
    expect(container.querySelector('[data-unified-shell="1"]')).not.toBeNull();
    expect(container.querySelector('[data-stable-demo="1"]')).toBeNull();
    expect(container.querySelector(".app-window")).toBeNull();

    // All 5 canonical destinations present in mobile bottom bar
    const mobileBtns = [...container.querySelectorAll(".jg-ushell__bottom-btn")].map((b) => b.textContent?.trim());
    expect(mobileBtns).toEqual(["Chat", "Agents", "Work", "Library", "Settings"]);

    // Live AvatarPanel is off by default (no idle rendering) and mounts on toggle
    expect(container.querySelector('[data-avatar-dock="1"]')).toBeNull();
    const agentMenu = container.querySelector<HTMLButtonElement>('button[aria-label$="chat options"]');
    expect(agentMenu).not.toBeNull();
    await flush(() => { agentMenu!.click(); });
    const avatarOption = [...document.querySelectorAll<HTMLElement>('[role="menuitem"]')].find(item => item.textContent?.includes("Show live avatar"));
    expect(avatarOption).toBeTruthy();
    await flush(() => { avatarOption!.click(); });
    expect(container.querySelector('[data-avatar-dock="1"]')).not.toBeNull();

    // Navigating to Settings mounts standalone SettingsView (NOT legacy App.tsx) and keeps Chat mounted
    await flush(() => { navigate("/settings/appearance"); });
    expect(container.querySelector('[data-settings-standalone="1"]')).not.toBeNull();
    expect(container.querySelector('[aria-label="Settings sidebar"]')).toBeNull();
    expect(container.querySelectorAll('nav[aria-label="Settings sections"]')).toHaveLength(1);
    await flush(() => { container!.querySelector<HTMLButtonElement>('[aria-label="Toggle navigation"]')!.click(); });
    expect(container.querySelector('nav[aria-label="Settings sections"]')).toBeNull();
    await flush(() => { container!.querySelector<HTMLButtonElement>('[aria-label="Toggle navigation"]')!.click(); });
    expect(container.querySelectorAll('nav[aria-label="Settings sections"]')).toHaveLength(1);
    const chatSection = container.querySelector<HTMLElement>('section[aria-label="Chat"]');
    expect(chatSection).not.toBeNull();
    expect(chatSection!.hidden).toBe(true);
    // Live Avatar unmounts while Chat is hidden (saves GPU!)
    expect(container.querySelector('[data-avatar-dock="1"]')).toBeNull();

    // Returning to Chat restores the mounted Chat section & Avatar dock
    await flush(() => { navigate("/"); });
    expect(chatSection!.hidden).toBe(false);
    expect(container.querySelector('[data-avatar-dock="1"]')).not.toBeNull();
  });
});
