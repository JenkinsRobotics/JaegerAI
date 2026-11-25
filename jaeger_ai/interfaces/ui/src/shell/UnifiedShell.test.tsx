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
  SettingsView: ({ tab }: { tab?: string }) => <div data-settings-standalone="1" data-tab={tab ?? ""}>Settings</div>,
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
    const avatarBtn = container.querySelector<HTMLButtonElement>('button[aria-label="Toggle live avatar"]');
    expect(avatarBtn).not.toBeNull();
    await flush(() => { avatarBtn!.click(); });
    expect(container.querySelector('[data-avatar-dock="1"]')).not.toBeNull();

    // Navigating to Settings mounts standalone SettingsView (NOT legacy App.tsx) and keeps Chat mounted
    await flush(() => { navigate("/settings/appearance"); });
    expect(container.querySelector('[data-settings-standalone="1"]')).not.toBeNull();
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
