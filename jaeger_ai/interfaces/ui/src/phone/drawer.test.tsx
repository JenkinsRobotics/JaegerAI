import { afterEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { DRAWER_NAV, PhoneDrawer } from "./PhoneShell";

describe("PhoneDrawer", () => {
  afterEach(() => { history.replaceState(null, "", "/"); document.body.innerHTML = ""; });
  it("pushes the chat aside, lists real pages + recents, and closes from the card", async () => {
    const el = document.createElement("div"); document.body.appendChild(el);
    const onClose = vi.fn(), onSearch = vi.fn(), onSettings = vi.fn(), onChat = vi.fn();
    const root = createRoot(el);
    await act(async () => root.render(<PhoneDrawer open onClose={onClose} onSearch={onSearch} onSettings={onSettings} onChat={onChat} recents={<p>recent-list</p>}><p>chat</p></PhoneDrawer>));
    expect(el.querySelector(".jg-pdrawer.is-open")).not.toBeNull();
    expect([...el.querySelectorAll(".jg-pdrawer__item > span:last-child")].map((b) => b.textContent)).toEqual(DRAWER_NAV.map((n) => n.label));
    expect(el.textContent).toContain("recent-list");
    await act(async () => el.querySelector<HTMLButtonElement>('[aria-label="Close menu"]')!.click());
    await act(async () => el.querySelector<HTMLButtonElement>('.jg-pdrawer__chat')!.click());
    await act(async () => el.querySelector<HTMLButtonElement>('.jg-pdrawer__top [aria-label="Search"]')!.click());
    expect(onChat).toHaveBeenCalled(); expect(onSearch).toHaveBeenCalled();
    await act(async () => [...el.querySelectorAll<HTMLButtonElement>(".jg-pdrawer__item")].find((b) => b.textContent?.endsWith("Backlog"))!.click());
    expect(location.pathname).toBe("/work/backlog");
    await act(async () => root.render(<PhoneDrawer open={false} onClose={onClose} onSearch={onSearch} onSettings={onSettings} onChat={onChat} recents={null}><p>chat</p></PhoneDrawer>));
    expect(el.querySelector('[aria-label="Close menu"]')).toBeNull();
  });
});
