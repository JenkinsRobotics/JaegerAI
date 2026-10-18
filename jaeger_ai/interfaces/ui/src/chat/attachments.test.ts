import { describe, expect, it } from "vitest";
import type { JaegerSource } from "../api/source";
import type { ChatPart } from "./host";
import { WebHost } from "./webHost";

/** A source that records attachment registrations and the turn body, then fails the send (no stream needed). */
function recording(failPath?: string) {
  const registered: Array<{ path: string; filename?: string; mime_type?: string }> = [];
  const sent: Array<{ text: string; ids?: string[] }> = [];
  const source = {
    kind: "live",
    addAttachment: async (_s: string, body: { path: string; filename?: string; mime_type?: string }) => {
      if (body.path === failPath) throw new Error("attachment path escapes workspace");
      registered.push(body);
      return { attachment_id: `att_${registered.length}` };
    },
    send: async (_s: string, text: string, _r: string, ids?: string[]) => { sent.push({ text, ids }); throw new Error("stop here"); },
    cancel: async () => {},
  } as unknown as JaegerSource;
  return { source, registered, sent };
}

const turn = (host: WebHost, attachments: Parameters<WebHost["startTurn"]>[0]["attachments"]) => {
  const parts: ChatPart[] = [];
  const handle = host.startTurn({ sessionId: "s1", turnId: "t1", message: "see files", attachments }, (p) => parts.push(p));
  return handle.done.then(() => parts);
};

describe("WebHost attachments (H8 → gateway)", () => {
  it("registers picked files by path and sends exactly their ids", async () => {
    const r = recording();
    const parts = await turn(new WebHost(r.source), [
      { name: "a.pdf", mimeType: "application/pdf", path: "/ws/a.pdf", uri: "file:///ws/a.pdf", size: 3 } as never,
      { name: "b.png", mimeType: "image/png", path: "/ws/b.png", size: 4 } as never,
    ]);
    expect(r.registered).toEqual([
      { path: "/ws/a.pdf", filename: "a.pdf", mime_type: "application/pdf" },
      { path: "/ws/b.png", filename: "b.png", mime_type: "image/png" },
    ]);
    expect(r.sent).toEqual([{ text: "see files", ids: ["att_1", "att_2"] }]);
    expect(parts.some((p) => p.kind === "warning")).toBe(false);
  });

  it("always sends an explicit list, so no turn picks up the chat's older files", async () => {
    const r = recording();
    await turn(new WebHost(r.source), undefined);
    expect(r.sent[0].ids).toEqual([]);
  });

  it("names files it could not send (no path, or refused) and still sends the rest", async () => {
    const r = recording("/outside/c.txt");
    const parts = await turn(new WebHost(r.source), [
      { name: "pasted.png", mimeType: "image/png" },
      { name: "c.txt", mimeType: "text/plain", path: "/outside/c.txt" } as never,
      { name: "d.md", mimeType: "text/markdown", path: "/ws/d.md" } as never,
    ]);
    expect(r.sent[0].ids).toEqual(["att_1"]);
    const warning = parts.find((p) => p.kind === "warning") as { message: string } | undefined;
    expect(warning?.message).toContain("pasted.png (no file path from this window)");
    expect(warning?.message).toContain("c.txt (attachment path escapes workspace)");
    expect(warning?.message).not.toContain("d.md");
  });

  it("reports refused files to the chat view, keyed by turn, so their chips can show why", async () => {
    const r = recording("/outside/c.txt");
    const host = new WebHost(r.source);
    const seen: unknown[] = [];
    host.onAttachmentsRejected = (turnId, rejected) => seen.push({ turnId, rejected });
    await turn(host, [{ name: "c.txt", mimeType: "text/plain", path: "/outside/c.txt" } as never]);
    expect(seen).toEqual([{ turnId: "t1", rejected: [{ name: "c.txt", path: "/outside/c.txt", reason: "attachment path escapes workspace" }] }]);
  });
});
