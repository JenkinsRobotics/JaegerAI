import { afterEach, describe, expect, it, vi } from "vitest";
import type { JaegerSource } from "../api/source";
import { addFiles, BYTES_UPLOAD_FLAG, bytesUploadEnabled, readBase64, toAttachments, withBytes } from "./composer";
import type { ChatPart } from "./host";
import { WebHost } from "./webHost";

afterEach(() => localStorage.clear());

describe("bytes upload prep (flag, off by default)", () => {
  const pasted = () => new File(["hello"], "note.txt", { type: "text/plain" });
  it("is off unless the flag is set", () => {
    expect(bytesUploadEnabled()).toBe(false);
    localStorage.setItem(BYTES_UPLOAD_FLAG, "1");
    expect(bytesUploadEnabled()).toBe(true);
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
    await host.startTurn({ sessionId: "s1", turnId: "t1", message: "m", attachments: [{ name: "note.txt", mimeType: "text/plain", data: btoa("hello") }] }, (p) => parts.push(p)).done;
    return parts;
  };
  it("WebHost uploads the bytes only with the flag on", async () => {
    const off = source();
    const parts = await turn(new WebHost(off.s));
    expect(off.uploads).toEqual([]);
    expect(parts.find((p) => p.kind === "warning")).toMatchObject({ message: expect.stringContaining("no file path from this window") });

    localStorage.setItem(BYTES_UPLOAD_FLAG, "1");
    const on = source();
    await turn(new WebHost(on.s));
    expect(on.uploads).toEqual([{ filename: "note.txt", mime_type: "text/plain", data_base64: btoa("hello") }]);
    expect((on.s.send as ReturnType<typeof vi.fn>).mock.calls[0][3]).toEqual(["att_b1"]);
  });
});
