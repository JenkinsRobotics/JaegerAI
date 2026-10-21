import { afterEach, describe, expect, it, vi } from "vitest";
import type { JaegerSource } from "../api/source";
import { addFiles, BYTES_UPLOAD_FLAG, bytesUploadEnabled, readBase64, toAttachments, withBytes } from "./composer";
import type { ChatPart } from "./host";
import { WebHost } from "./webHost";

afterEach(() => localStorage.clear());

describe("bytes upload (on by default since 417d8a0c; flag \"0\" opts out)", () => {
  const pasted = () => new File(["hello"], "note.txt", { type: "text/plain" });
  it("is on unless the flag is \"0\"", () => {
    expect(bytesUploadEnabled()).toBe(true);
    localStorage.setItem(BYTES_UPLOAD_FLAG, "0");
    expect(bytesUploadEnabled()).toBe(false);
  });
  it("reads a file as base64", async () => {
    expect(await readBase64(pasted())).toBe(btoa("hello"));
  });
  it("keeps the pasted File on its chip, and sends no bytes while the flag is off", async () => {
    const { files } = addFiles([], [pasted()], () => "1");
    expect(files[0].blob).toBeInstanceOf(Blob);
    expect(toAttachments(files)[0]).toEqual({ name: "note.txt", mimeType: "text/plain", size: 5 });
    expect((await withBytes(files, false))[0].data).toBeUndefined();
  });
  it("adds base64 data for path-less files when on; picked files keep their path and get no data", async () => {
    const { files } = addFiles([], [pasted(), { name: "a.pdf", size: 3, type: "application/pdf", path: "/ws/a.pdf", uri: "file:///ws/a.pdf" }], (() => { let n = 0; return () => String(++n); })());
    const out = await withBytes(files, true);
    expect(out[0]).toMatchObject({ name: "note.txt", data: btoa("hello") });
    expect(out[1]).toEqual({ name: "a.pdf", mimeType: "application/pdf", size: 3, path: "/ws/a.pdf", uri: "file:///ws/a.pdf" });
  });

  const source = () => {
    const uploads: unknown[] = [];
    const s = {
      kind: "live",
      uploadAttachment: vi.fn(async (_s: string, body: unknown) => { uploads.push(body); return { attachment_id: "att_b1" }; }),
      addAttachment: vi.fn(),
      send: vi.fn(async () => { throw new Error("stop"); }),
      cancel: async () => {},
    } as unknown as JaegerSource;
    return { s, uploads };
  };
  const turn = async (host: WebHost) => {
    const parts: ChatPart[] = [];
    await host.startTurn({ sessionId: crypto.randomUUID(), turnId: crypto.randomUUID(), message: "m", attachments: [{ name: "note.txt", mimeType: "text/plain", data: btoa("hello") }] }, (p) => parts.push(p)).done;
    return parts;
  };
  it("WebHost uploads the bytes unless opted out", async () => {
    localStorage.setItem(BYTES_UPLOAD_FLAG, "0");
    const off = source();
    const parts = await turn(new WebHost(off.s));
    expect(off.uploads).toEqual([]);
    expect(parts.find((p) => p.kind === "warning")).toMatchObject({ message: expect.stringContaining("no file path from this window") });

    localStorage.setItem(BYTES_UPLOAD_FLAG, "1");
    const on = source();
    await turn(new WebHost(on.s));
    expect(on.uploads).toEqual([{ name: "note.txt", mime: "text/plain", data_base64: btoa("hello") }]);
    expect((on.s.send as ReturnType<typeof vi.fn>).mock.calls[0][3]).toEqual(["att_b1"]);
  });

  const failing = (status: number) => ({
    kind: "live",
    uploadAttachment: vi.fn(async () => { throw Object.assign(new Error(`status ${status}`), { status }); }),
    addAttachment: vi.fn(),
    send: vi.fn(async () => { throw new Error("stop"); }),
    cancel: async () => {},
  } as unknown as JaegerSource);
  it("413 becomes 'Too large (25 MB max)'; attachment_ids is still sent ([] for none)", async () => {
    localStorage.setItem(BYTES_UPLOAD_FLAG, "1");
    const s = failing(413);
    const host = new WebHost(s);
    const rejected: unknown[] = [];
    host.onAttachmentsRejected = (_t, r) => rejected.push(...r);
    await turn(host);
    expect(rejected).toEqual([{ name: "note.txt", reason: "Too large (25 MB max)" }]);
    expect((s.send as ReturnType<typeof vi.fn>).mock.calls[0][3]).toEqual([]);
  });
  it("feature-detects a gateway without the bytes route (404/405) and stops trying", async () => {
    localStorage.setItem(BYTES_UPLOAD_FLAG, "1");
    const s = failing(405);
    const host = new WebHost(s);
    const parts = await turn(host);
    expect(parts.find((p) => p.kind === "warning")).toMatchObject({ message: expect.stringContaining("no file path from this window") });
    await turn(host);
    expect((s.uploadAttachment as ReturnType<typeof vi.fn>).mock.calls.length).toBe(1);
  });
  it("refuses files over 25 MB before uploading", async () => {
    localStorage.setItem(BYTES_UPLOAD_FLAG, "1");
    const s = failing(500);
    const host = new WebHost(s);
    const rejected: unknown[] = [];
    host.onAttachmentsRejected = (_t, r) => rejected.push(...r);
    await host.startTurn({ sessionId: "s1", turnId: "t2", message: "m", attachments: [{ name: "big.bin", mimeType: "application/octet-stream", data: "A".repeat(36 * 1024 * 1024) }] }, () => {}).done;
    expect(rejected).toEqual([{ name: "big.bin", reason: "Too large (25 MB max)" }]);
    expect(s.uploadAttachment).not.toHaveBeenCalled();
  });
});
