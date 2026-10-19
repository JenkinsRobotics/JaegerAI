import { applyTextSize } from "../settings/textSize";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { AppShell } from "./AppShell";
import { SIDEBAR } from "./sidebarSizing";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;
const setWindowWidth = (w: number) => {
  Object.defineProperty(window, "innerWidth", { configurable: true, value: w });
  act(() => { window.dispatchEvent(new Event("resize")); });
};
const render = () => act(() => {
  root.render(<AppShell top={<div />} primary={<div />} footer={<div />}><p>chat</p></AppShell>);
});
const shell = () => host.querySelector<HTMLDivElement>(".jg-shell")!;
const handle = () => host.querySelector<HTMLDivElement>('[role="separator"]')!;
const key = (k: string) => act(() => { handle().dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true })); });

beforeEach(() => {
  localStorage.clear();
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 1040 });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(() => { act(() => root.unmount()); host.remove(); });

describe("AppShell sidebar", () => {
  it("hands the header a toggle that collapses to the rail and back", () => {
    const top = ({ collapsed, toggle }: { collapsed: boolean; toggle: () => void }) => (
      <button type="button" aria-expanded={!collapsed} onClick={toggle}>sidebar</button>
    );
    act(() => { root.render(<AppShell top={top} primary={<div />} footer={<div />}><p>chat</p></AppShell>); });
    const button = host.querySelector("button")!;
    expect(button.getAttribute("aria-expanded")).toBe("true");
    act(() => { button.click(); });
    expect(shell().dataset.sidebar).toBe("rail");
    expect(button.getAttribute("aria-expanded")).toBe("false");
    act(() => { button.click(); });
    expect(shell().dataset.sidebar).toBe("expanded");
  });

  it("starts at 280 with an accessible separator", () => {
    render();
    expect(shell().dataset.sidebar).toBe("expanded");
    expect(shell().style.getPropertyValue("--jg-sidebar-column")).toBe("280px");
    expect(handle().getAttribute("aria-orientation")).toBe("vertical");
    expect(handle().getAttribute("aria-valuenow")).toBe("280");
    expect(handle().tabIndex).toBe(0);
  });

  it("steps with the arrow keys and remembers the width", () => {
    render();
    key("ArrowRight");
    key("ArrowRight");
    expect(handle().getAttribute("aria-valuenow")).toBe("296");
    expect(JSON.parse(localStorage.getItem(SIDEBAR.storageKey)!)).toEqual({ expandedWidth: 296, isCollapsed: false });
  });

  it("restores the stored state and toggles the rail with an animation", () => {
    localStorage.setItem(SIDEBAR.storageKey, JSON.stringify({ expandedWidth: 330, isCollapsed: false }));
    render();
    expect(shell().style.getPropertyValue("--jg-sidebar-column")).toBe("330px");
    key("Enter");
    expect(shell().dataset.sidebar).toBe("rail");
    expect(shell().style.getPropertyValue("--jg-sidebar-column")).toBe("88px");
    expect(shell().classList.contains("is-animating")).toBe(true);
    expect(JSON.parse(localStorage.getItem(SIDEBAR.storageKey)!)).toEqual({ expandedWidth: 330, isCollapsed: true });
  });

  it("auto-collapses below width + 424 without storing it, and comes back", () => {
    render();
    setWindowWidth(650);
    expect(shell().dataset.sidebar).toBe("rail");
    expect(shell().classList.contains("is-auto-rail")).toBe(true);
    expect(shell().classList.contains("is-animating")).toBe(false);
    expect(JSON.parse(localStorage.getItem(SIDEBAR.storageKey)!).isCollapsed).toBe(false);
    setWindowWidth(1040);
    expect(shell().dataset.sidebar).toBe("expanded");
  });
});


it("auto-collapses for larger text and restores the sidebar when the window grows", () => {
  setWindowWidth(900); render();
  expect(shell().classList.contains("is-rail")).toBe(false);
  act(() => { applyTextSize(20); });
  expect(shell().classList.contains("is-rail")).toBe(true);
  setWindowWidth(1400);
  expect(shell().classList.contains("is-rail")).toBe(false);
  expect(JSON.parse(localStorage.getItem(SIDEBAR.storageKey)!).isCollapsed).toBe(false);
  act(() => { applyTextSize(14); });
});
