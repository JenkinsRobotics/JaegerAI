/* Blueprint acceptance oracles GB-008 (rich transcript) and GB-009 (composer), as isolated fixture tests against
 * the real components. Fixture host only (no gateway): these prove client behaviour, not live acceptance. */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Markdown } from "./Markdown";
import { MinimalChat } from "./MinimalChat";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let el: HTMLDivElement; let root: Root;
beforeEach(() => { localStorage.clear(); el = document.createElement("div"); document.body.append(el); root = createRoot(el); });
afterEach(() => { act(() => root.unmount()); el.remove(); });

const fixture = "# Report\n\n```ts\nconst a = 1;\n```\n\n| k | v |\n|---|---|\n| x | 1 |\n\n$$\\frac{1}{\\x$$\n\n```mermaid\ngraph TD; A-->\n```\n\n[bad](javascript:alert(1)) and [ok](https://example.com)";

describe("GB-008 rich transcript", () => {
  it("A1/A4: code, table, math and a malformed diagram render with readable literal fallbacks; unsafe links never become hrefs", () => {
    const html = renderToStaticMarkup(<Markdown text={fixture} onCopy={() => {}} onOpen={() => {}} />);
    expect(html).toContain("const a = 1;");
    expect(html).toContain("<table");
    expect(html).toContain("\\frac{1}{\\x");          // invalid math stays readable literal text
    expect(html).toContain("graph TD; A--&gt;");       // malformed diagram stays a literal code block
    expect(html).not.toContain("javascript:");
    expect(html).toContain('href="https://example.com"');
  });
  it("A3: Copy on a code block yields its exact source once, and re-rendering the same revision keeps one block", () => {
    const onCopy = vi.fn();
    act(() => root.render(<Markdown text={"```sh\necho hi\n\nls\n```"} onCopy={onCopy} onOpen={() => {}} />));
    act(() => root.render(<Markdown text={"```sh\necho hi\n\nls\n```"} onCopy={onCopy} onOpen={() => {}} />));
    expect(el.querySelectorAll("pre").length).toBe(1);
    act(() => el.querySelector<HTMLButtonElement>('button[aria-label="Copy code"]')!.click());
    expect(onCopy).toHaveBeenCalledTimes(1);
    expect(onCopy).toHaveBeenCalledWith("echo hi\n\nls");
  });
});

function host() {
  const startTurn = vi.fn(() => ({ cancel: vi.fn(), done: new Promise(() => {}) }));
  return { startTurn, h: { capabilities: { voice: false }, startTurn, respondToConfirmation: vi.fn(), copy: vi.fn(), openExternal: vi.fn(),
    sessions: { list: vi.fn(), load: vi.fn(async (id: string) => ({ id, title: "t", turns: [] })) } } };
}
async function mountChat() {
  const { h, startTurn } = host();
  await act(async () => root.render(<MinimalChat host={h as never} sessionId="s1" />));
  await act(async () => { await new Promise((r) => setTimeout(r, 30)); });
  const input = el.querySelector<HTMLTextAreaElement>(".jg-composer__input")!;
  const type = (v: string) => act(() => { const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!; set.call(input, v); input.dispatchEvent(new Event("input", { bubbles: true })); });
  const enter = (init: KeyboardEventInit) => act(() => { input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true, ...init })); });
  return { input, type, enter, startTurn };
}

describe("GB-009 composer", () => {
  it("A1/A2: multiline text survives; Enter during IME composition (isComposing or WebKit keyCode 229) never sends", async () => {
    const c = await mountChat();
    c.type("line one\nline two");
    c.enter({ isComposing: true });
    c.enter({ keyCode: 229 } as KeyboardEventInit);
    expect(c.startTurn).not.toHaveBeenCalled();
    act(() => c.input.blur());
    expect(c.input.value).toBe("line one\nline two");
    c.enter({});
    expect(c.startTurn).toHaveBeenCalledTimes(1);
    expect((c.startTurn.mock.calls[0] as unknown as [{ message: string }])[0].message).toBe("line one\nline two");
  });
  it("A3: a double Send emits exactly one intent with the exact text", async () => {
    const c = await mountChat();
    c.type("ship it");
    const sendBtn = () => el.querySelector<HTMLButtonElement>('button[aria-label="Send"]');
    act(() => { sendBtn()?.click(); sendBtn()?.click(); });
    c.enter({});
    expect(c.startTurn).toHaveBeenCalledTimes(1);
    expect((c.startTurn.mock.calls[0] as unknown as [{ message: string }])[0].message).toBe("ship it");
  });
  it("A4: whitespace only keeps Send disabled and admits no request", async () => {
    const c = await mountChat();
    c.type("   \n  ");
    expect(el.querySelector<HTMLButtonElement>('button[aria-label="Send"]')?.disabled).toBe(true);
    c.enter({});
    expect(c.startTurn).not.toHaveBeenCalled();
  });
});
