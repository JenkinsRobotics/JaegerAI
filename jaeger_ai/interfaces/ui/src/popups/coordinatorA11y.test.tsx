/* GB-064 accessibility oracles for the shared popup coordinator (isolated DOM fixture). */
import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";
import { useExclusivePopup } from "./coordinator";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let el: HTMLDivElement; let root: Root;
beforeEach(() => { el = document.createElement("div"); document.body.append(el); root = createRoot(el); });
afterEach(() => { act(() => root.unmount()); el.remove(); });

function Fixture() {
  const [open, setOpen] = useState(false);
  return <><button id="invoker" onClick={() => setOpen(true)}>Open</button>{open && <Menu close={() => setOpen(false)} />}</>;
}
function Menu({ close }: { close: () => void }) {
  useExclusivePopup(true, close);
  return <div role="menu"><input id="picker" aria-label="Pick" /></div>;
}
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });
const key = (init: KeyboardEventInit) => act(() => { document.activeElement!.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, ...init })); });

it("A1/A2: Escape closes the popup and focus returns to its invoking control", async () => {
  act(() => root.render(<Fixture />));
  const invoker = el.querySelector<HTMLButtonElement>("#invoker")!;
  invoker.focus(); act(() => invoker.click());
  el.querySelector<HTMLInputElement>("#picker")!.focus();
  key({}); await flush();
  expect(el.querySelector('[role="menu"]')).toBeNull();
  expect(document.activeElement).toBe(invoker);
});
it("A2: Escape that cancels an IME composition does not dismiss the popup", async () => {
  act(() => root.render(<Fixture />));
  act(() => el.querySelector<HTMLButtonElement>("#invoker")!.click());
  el.querySelector<HTMLInputElement>("#picker")!.focus();
  key({ isComposing: true }); key({ keyCode: 229 } as KeyboardEventInit); await flush();
  expect(el.querySelector('[role="menu"]')).not.toBeNull();
  expect(document.activeElement?.id).toBe("picker");
});
it("does not steal focus the user already moved elsewhere", async () => {
  act(() => root.render(<><Fixture /><input id="elsewhere" /></>));
  const invoker = el.querySelector<HTMLButtonElement>("#invoker")!;
  invoker.focus(); act(() => invoker.click());
  const other = el.querySelector<HTMLInputElement>("#elsewhere")!;
  act(() => { other.focus(); other.dispatchEvent(new MouseEvent("mousedown", { bubbles: true })); }); await flush();
  expect(el.querySelector('[role="menu"]')).toBeNull();
  expect(document.activeElement).toBe(other);
});
