import { useEffect, useId, useRef, useState } from "react";
import type { SessionFiles } from "../api/source";
import type { ChatPart } from "./host";

const RASTER = new Set(["image/png", "image/jpeg", "image/webp", "image/gif"]);

export type AttachmentPart = Extract<ChatPart, { kind: "attachment" }>;

function decodeVerified(data: string, expected: { size: number; sha256?: string }) {
  const bytes = Uint8Array.from(atob(data), (c) => c.charCodeAt(0));
  if (expected.size && bytes.byteLength !== expected.size) throw Error("File size mismatch");
  return bytes;
}

/** First-class session image in a chat bubble. Bytes come from the session
 *  attachment store (never a markdown <img> or a remote URL). */
/** Non-image file the agent shared (parity P14): a chip whose Download button
 *  fetches verified bytes from the session attachment store on click. */
function AttachmentFile({ part, sessionId, files }: { part: AttachmentPart; sessionId?: string; files?: SessionFiles }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const download = async () => {
    if (!sessionId || !files) { setError("File is not available in this conversation."); return; }
    setBusy(true); setError(undefined);
    try {
      const result = await files.read(sessionId, part.attachmentId);
      if (result.session_id !== sessionId || result.attachment_id !== part.attachmentId) throw Error("File identity mismatch");
      if (part.sha256 && result.sha256 !== part.sha256) throw Error("File digest mismatch");
      const bytes = decodeVerified(result.data_base64, { size: result.size, sha256: part.sha256 });
      const url = URL.createObjectURL(new Blob([bytes], { type: "application/octet-stream" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = (part.name || "file").replace(/[\\/\x00-\x1f]/g, "_");
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 30_000);
    } catch (err) { setError(String((err as Error).message || err)); }
    finally { setBusy(false); }
  };
  const size = typeof part.size === "number" ? (part.size < 1024 ? `${part.size} B` : `${(part.size / 1024).toFixed(1)} KB`) : "";
  return (
    <div className="jg-card jg-file-card" role="group" aria-label={`File ${part.name}`} style={{ display: "flex", alignItems: "center", gap: 12 }}>
      <span aria-hidden="true">📄</span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="jg-card__title" style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{part.name || "file"}</div>
        <div className="jg-card__message">{[part.mime, size].filter(Boolean).join(" · ")}</div>
        {error && <div className="jg-card__message" role="alert">{error}</div>}
      </div>
      <button type="button" className="jg-action" disabled={busy} onClick={() => void download()}>{busy ? "Downloading…" : "Download"}</button>
    </div>
  );
}

export function AttachmentImage({ part, sessionId, files }: { part: AttachmentPart; sessionId?: string; files?: SessionFiles }) {
  const kind = (part.mime || "").split(";")[0].trim().toLowerCase();
  if (!RASTER.has(kind)) return <AttachmentFile part={part} sessionId={sessionId} files={files} />;
  return <AttachmentRaster part={part} sessionId={sessionId} files={files} />;
}

function AttachmentRaster({ part, sessionId, files }: { part: AttachmentPart; sessionId?: string; files?: SessionFiles }) {
  const [url, setUrl] = useState<string>();
  const [error, setError] = useState<string>();
  const [open, setOpen] = useState(false);
  const objectUrl = useRef<string | undefined>(undefined);
  const dialog = useRef<HTMLDialogElement>(null);
  const labelId = useId();
  const mime = (part.mime || "").split(";")[0].trim().toLowerCase();
  const raster = RASTER.has(mime);

  useEffect(() => {
    let cancelled = false;
    const release = () => { if (objectUrl.current) { URL.revokeObjectURL(objectUrl.current); objectUrl.current = undefined; } };
    release();
    setUrl(undefined);
    setError(undefined);
    if (!sessionId || !files || !part.attachmentId) {
      setError("Image is not available in this conversation.");
      return () => { cancelled = true; release(); };
    }
    if (!raster) {
      setError("This attachment has no inline preview.");
      return () => { cancelled = true; release(); };
    }
    void files.read(sessionId, part.attachmentId).then(async (result) => {
      if (cancelled) return;
      if (result.session_id !== sessionId || result.attachment_id !== part.attachmentId) throw Error("File identity mismatch");
      if (part.sha256 && result.sha256 !== part.sha256) throw Error("File digest mismatch");
      if (part.size && result.size !== part.size) throw Error("File size mismatch");
      if (result.name !== part.name && part.name) { /* name may be sanitized; identity is the id + digest */ }
      const bytes = decodeVerified(result.data_base64, { size: result.size, sha256: part.sha256 });
      if (part.sha256) {
        const hash = [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))].map((x) => x.toString(16).padStart(2, "0")).join("");
        if (hash !== part.sha256) throw Error("File digest mismatch");
      }
      if (cancelled) return;
      const created = URL.createObjectURL(new Blob([bytes], { type: mime }));
      objectUrl.current = created;
      setUrl(created);
    }).catch((err) => { if (!cancelled) setError(String(err)); });
    return () => { cancelled = true; release(); };
  }, [files, sessionId, part.attachmentId, part.sha256, part.size, part.name, mime, raster]);

  useEffect(() => {
    const node = dialog.current;
    if (!node) return;
    if (open && !node.open) node.showModal();
    if (!open && node.open) node.close();
  }, [open]);

  const download = () => {
    if (!url) return;
    const link = document.createElement("a");
    link.href = url;
    link.download = (part.name || "image").replace(/[\\/\x00-\x1f]/g, "_");
    link.click();
  };

  return (
    <figure className="jg-generated-image" aria-labelledby={labelId}>
      <figcaption id={labelId} className="jg-generated-image__caption">{part.name || "Generated image"}</figcaption>
      {url ? (
        <button type="button" className="jg-generated-image__frame" onClick={() => setOpen(true)} aria-label={`Enlarge ${part.name || "generated image"}`}>
          <img src={url} alt={part.name || "Generated image"} />
        </button>
      ) : error ? <p className="jg-generated-image__error">{error}</p> : <p className="jg-generated-image__status" role="status">Loading image…</p>}
      <div className="jg-generated-image__actions">
        <button type="button" className="jg-action" disabled={!url} onClick={download}>Download</button>
        <button type="button" className="jg-action" disabled={!url} onClick={() => setOpen(true)}>Enlarge</button>
      </div>
      <dialog ref={dialog} className="jg-generated-image__lightbox" aria-label={part.name || "Generated image"} onClose={() => setOpen(false)} onClick={(event) => { if (event.target === event.currentTarget) setOpen(false); }}>
        {url && <img src={url} alt={part.name || "Generated image"} />}
        <form method="dialog">
          <button type="submit" className="jg-action">Close</button>
          <button type="button" className="jg-action" disabled={!url} onClick={download}>Download</button>
        </form>
      </dialog>
    </figure>
  );
}
