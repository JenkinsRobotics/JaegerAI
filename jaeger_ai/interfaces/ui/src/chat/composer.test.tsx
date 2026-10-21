import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MAX_ATTACHMENTS, MAX_ATTACHMENT_BYTES, addFiles, attachmentError, fileSize, primaryAction, restoreRejected, toAttachments } from "./composer";
import { WebHost } from "./webHost";
import type { ChatHost, StartTurnRequest } from "./host";
import { MinimalChat } from "./MinimalChat";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe("composer helpers", () => {
  it("morphs the primary button Stop → Send → Voice chat", () => {
    const both = { voiceChat: true, dictation: true };
    expect(primaryAction({ running: true, hasContent: true, ...both })).toBe("stop");
    expect(primaryAction({ running: false, hasContent: true, ...both })).toBe("send");
    expect(primaryAction({ running: false, hasContent: false, ...both })).toBe("voice");
    // Dictation only (no voices to speak with): Dictate takes the primary.
    expect(primaryAction({ running: false, hasContent: false, voiceChat: false, dictation: true })).toBe("dictate");
    expect(primaryAction({ running: false, hasContent: true, voiceChat: false, dictation: true })).toBe("send");
    expect(primaryAction({ running: false, hasContent: false, voiceChat: false, dictation: false })).toBe("send");
  });

  it("caps attachments by count and size and says what it left out", () => {
    let n = 0;
    const id = () => `f${(n += 1)}`;
    const many = Array.from({ length: MAX_ATTACHMENTS + 2 }, (_, i) => ({ name: `a${i}.txt`, size: 10, type: "text/plain" }));
    const r = addFiles([], [...many, { name: "big.mov", size: MAX_ATTACHMENT_BYTES + 1, type: "video/quicktime" }], id);
    expect(r.files).toHaveLength(MAX_ATTACHMENTS);
    expect(r.note).toBe("1 over 20 MB left out · only 8 files per message");
    expect(addFiles([], [{ name: "", size: 1, type: "image/png" }], id).files[0].name).toBe("pasted file");
    expect(toAttachments([{ id: "x", name: "a.bin", size: 1, type: "" }])).toEqual([{ name: "a.bin", mimeType: "application/octet-stream", size: 1 }]);
    // Host-picked files keep their H8 path + uri so the gateway can register them.
    expect(toAttachments([{ id: "y", name: "b.pdf", size: 9, type: "application/pdf", path: "/w/b.pdf", uri: "file:///w/b.pdf" }]))
      .toEqual([{ name: "b.pdf", mimeType: "application/pdf", size: 9, path: "/w/b.pdf", uri: "file:///w/b.pdf" }]);
    expect(fileSize(2048)).toBe("2 KB");
  });
});

describe("composer (DOM)", () => {
  let el: HTMLDivElement;
  let root: Root;
  const started: StartTurnRequest[] = [];
  const host = {
    capabilities: { voice: false },
    startTurn: vi.fn((req: StartTurnRequest) => { started.push(req); req.onAccepted?.(); return { cancel() {}, done: new Promise(() => {}) }; }),
    respondToConfirmation: vi.fn(),
    sessions: { list: vi.fn(), load: vi.fn(async (id: string) => ({ id, title: "t", turns: [] })) },
    copy: vi.fn(), openExternal: vi.fn(),
  } as unknown as ChatHost;
  beforeEach(async () => {
    el = document.createElement("div");
    document.body.append(el);
    root = createRoot(el);
    await act(async () => { root.render(<MinimalChat host={host} sessionId="s1" />); });
  });
  afterEach(() => { act(() => root.unmount()); el.remove(); started.length = 0; });

  it("shows picked files as chips, sends them with the turn and clears them", async () => {
    const input = el.querySelector<HTMLInputElement>('input[type="file"]')!;
    expect(input).toBeTruthy();
    const file = new File(["hello"], "notes.md", { type: "text/markdown" });
    Object.defineProperty(input, "files", { configurable: true, value: [file] });
    await act(async () => { input.dispatchEvent(new Event("change", { bubbles: true })); });
    expect(el.querySelector(".jg-chip__name")?.textContent).toBe("notes.md");
    const send = el.querySelector<HTMLButtonElement>('button[aria-label="Send"]')!;
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
    expect(send.disabled).toBe(false); // file bytes must be ready before Send enables
    await act(async () => { send.click(); });
    expect(started[0].attachments).toEqual([{ name: "notes.md", mimeType: "text/markdown", size: 5, data: btoa("hello") }]);
    expect(el.querySelector(".jg-chip")).toBeNull();
  });

  it("removes a chip and keeps Send disabled with nothing to send", async () => {
    const input = el.querySelector<HTMLInputElement>('input[type="file"]')!;
    Object.defineProperty(input, "files", { configurable: true, value: [new File(["x"], "a.txt", { type: "text/plain" })] });
    await act(async () => { input.dispatchEvent(new Event("change", { bubbles: true })); });
    await act(async () => { el.querySelector<HTMLButtonElement>('button[aria-label="Remove a.txt"]')!.click(); });
    expect(el.querySelector(".jg-chip")).toBeNull();
    expect(el.querySelector<HTMLButtonElement>('button[aria-label="Send"]')!.disabled).toBe(true);
  });

  it("auto-grows the message field up to 200 px", async () => {
    const ta = el.querySelector<HTMLTextAreaElement>("textarea")!;
    Object.defineProperty(ta, "scrollHeight", { configurable: true, get: () => 340 });
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!;
    await act(async () => { setter.call(ta, "line\n".repeat(20)); ta.dispatchEvent(new Event("input", { bubbles: true })); });
    expect(ta.style.height).toBe("200px");
    expect(ta.style.overflowY).toBe("auto");
  });
});

describe("refused attachments", () => {
  it("words the gateway's refusals plainly", () => {
    expect(attachmentError("attachment path escapes workspace")).toBe("Not sent: outside Jaeger's workspace");
    expect(attachmentError("no file path from this window")).toBe("Not sent: use + to attach it from disk");
    expect(attachmentError("413 Payload Too Large")).toBe("Too large (25 MB max)");
  });
  it("puts exactly the refused files back as error chips, and never re-sends them", () => {
    const sent = [{ id: "1", name: "a.txt", size: 1, type: "text/plain", path: "/out/a.txt" }, { id: "2", name: "b.txt", size: 1, type: "text/plain", path: "/ws/b.txt" }];
    const back = restoreRejected([], sent, [{ name: "a.txt", path: "/out/a.txt", reason: "attachment path escapes workspace" }]);
    expect(back).toEqual([{ ...sent[0], error: "Not sent: outside Jaeger's workspace" }]);
    expect(toAttachments(back)).toEqual([]);
  });
  it("shows the 'escapes workspace' 400 on that file's chip (DOM)", async () => {
    const host = Object.assign(Object.create(WebHost.prototype) as WebHost, {
      capabilities: { voice: false },
      startTurn: (req: StartTurnRequest) => {
        host.onAttachmentsRejected?.(req.turnId, [{ name: "secret.txt", reason: "attachment path escapes workspace" }]);
        return { cancel() {}, done: new Promise(() => {}) };
      },
      respondToConfirmation: vi.fn(),
      sessions: { list: vi.fn(), load: vi.fn(async (id: string) => ({ id, title: "t", turns: [] })) },
      copy: vi.fn(), openExternal: vi.fn(),
    });
    const el = document.createElement("div");
    document.body.append(el);
    const root = createRoot(el);
    await act(async () => { root.render(<MinimalChat host={host as unknown as ChatHost} sessionId="s1" />); });
    const input = el.querySelector<HTMLInputElement>('input[type="file"]')!;
    Object.defineProperty(input, "files", { configurable: true, value: [new File(["x"], "secret.txt", { type: "text/plain" })] });
    await act(async () => { input.dispatchEvent(new Event("change", { bubbles: true })); });
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
    await act(async () => { el.querySelector<HTMLButtonElement>('button[aria-label="Send"]')!.click(); });
    const chip = el.querySelector(".jg-chip.is-error");
    expect(chip?.querySelector(".jg-chip__name")?.textContent).toBe("secret.txt");
    expect(chip?.querySelector('[role="alert"]')?.textContent).toBe("Not sent: outside Jaeger's workspace");
    act(() => root.unmount());
    el.remove();
  });
});

describe("jump button (DOM)", () => {
  it("is always mounted, hidden at the bottom, and the chat root carries --jg-composer-h", async () => {
    const el = document.createElement("div");
    document.body.append(el);
    const root = createRoot(el);
    const host = {
      capabilities: { voice: false }, startTurn: vi.fn(), respondToConfirmation: vi.fn(), copy: vi.fn(), openExternal: vi.fn(),
      sessions: { list: vi.fn(), load: vi.fn(async (id: string) => ({ id, title: "t", turns: [] })) },
    } as unknown as ChatHost;
    await act(async () => { root.render(<MinimalChat host={host} sessionId="s1" />); });
    const jump = el.querySelector<HTMLButtonElement>(".jg-jump")!;
    expect(jump.classList.contains("is-visible")).toBe(false);
    expect(jump.getAttribute("aria-hidden")).toBe("true");
    expect(jump.tabIndex).toBe(-1);
    expect(el.querySelector<HTMLDivElement>(".jg-chat")!.style.getPropertyValue("--jg-composer-h")).toMatch(/^\d+px$/);
    act(() => root.unmount());
    el.remove();
  });
});
