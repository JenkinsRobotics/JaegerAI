// Native-shell popup bug: WKWebView fires mousedown but no pointerdown after a right-click, so Aether's
// pointerdown-only dismissal never ran and menus piled up. AppMenu closes on mousedown/Escape, one at a time.
import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { AppMenu } from "./AppMenu";
import { announcePopup, anyPopupOpen, whenNoPopup } from "./coordinator";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let el: HTMLDivElement; let root: Root;
beforeEach(() => { el = document.createElement("div"); document.body.append(el); root = createRoot(el); });
afterEach(() => { act(() => root.unmount()); el.remove(); document.body.innerHTML = ""; });

let openA: () => void = () => {}; let openB: () => void = () => {};
function Two() {
  const [a, setA] = useState(false); const [b, setB] = useState(false);
  openA = () => setA(true); openB = () => setB(true);
  return <>
    <button id="outside">outside</button>
    <AppMenu open={a} anchor={{ x: 10, y: 10 }} ariaLabel="A" items={[{ id: "a1", label: "A one" }]} onSelect={() => {}} onClose={() => setA(false)} />
    <AppMenu open={b} anchor={{ x: 40, y: 40 }} ariaLabel="B" items={[{ id: "b1", label: "B one" }]} onSelect={() => {}} onClose={() => setB(false)} />
  </>;
}
const menus = () => [...document.querySelectorAll('[role="menu"]')].map((m) => m.getAttribute("aria-label"));
const press = (t: Element, type = "mousedown") => act(() => { t.dispatchEvent(new MouseEvent(type, { bubbles: true })); });

describe("popup coordinator", () => {
  beforeEach(async () => { await act(async () => { root.render(<Two />); }); });
  it("opening one menu closes the other", async () => {
    await act(async () => openA()); expect(menus()).toEqual(["A"]);
    await act(async () => openB()); expect(menus()).toEqual(["B"]);
  });
  it("a mousedown outside closes it even with no pointerdown (WKWebView after a right-click)", async () => {
    await act(async () => openA());
    press(document.getElementById("outside")!);
    expect(menus()).toEqual([]);
  });
  it("a press inside the menu keeps it open", async () => {
    await act(async () => openA());
    press(document.querySelector('[role="menuitem"]')!);
    expect(menus()).toEqual(["A"]);
  });
  it("Escape closes it from anywhere (document keydown)", async () => {
    await act(async () => openB());
    act(() => { document.body.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })); });
    expect(menus()).toEqual([]);
  });
  it("an external popup (⌘K palette) closes open menus", async () => {
    await act(async () => openA());
    act(() => announcePopup("palette"));
    expect(menus()).toEqual([]);
  });
});

describe("auto-follow pause", () => {
  beforeEach(async () => { await act(async () => { root.render(<Two />); }); });
  it("runs at once with no popup; while one is open it waits and runs (latest only) on close", async () => {
    const ran: string[] = [];
    whenNoPopup(() => ran.push("now")); expect(ran).toEqual(["now"]);
    await act(async () => openA()); expect(anyPopupOpen()).toBe(true);
    whenNoPopup(() => ran.push("first")); whenNoPopup(() => ran.push("latest"));
    expect(ran).toEqual(["now"]);
    await act(async () => openB()); expect(ran).toEqual(["now"]);
    act(() => { document.body.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })); });
    expect(anyPopupOpen()).toBe(false);
    expect(ran).toEqual(["now", "latest"]);
  });
});
