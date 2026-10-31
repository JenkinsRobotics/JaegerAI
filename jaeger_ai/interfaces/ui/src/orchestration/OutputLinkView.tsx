import { useState } from "react";
import type { OutputLink } from "./types";

export type Navigate = (href: string) => void;
const ICON: Record<OutputLink["kind"], string> = { session: "💬", handoff: "⇄", task: "☑", file: "📄", commit: "⌥", url: "↗", approval: "✋" };

/** https → external link; `copy` refs (files, commits, http) → copy chip;
 * anything else is an in-app route or `handoff:<id>`. */
export function OutputLinkView({ link, onNavigate }: { link: OutputLink; onNavigate: Navigate }) {
  const [copied, setCopied] = useState(false);
  const mark = link.verified ? <span className="jg-orch-verified" aria-label="verified" title="Verified by the gateway">✓</span> : null;
  const title = link.sha ? `${link.href}\nsha ${link.sha}` : link.href;
  if (link.copy) {
    const copy = () => { void navigator.clipboard?.writeText(link.href).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); }, () => undefined); };
    return <button type="button" className="jg-orch-out" data-copy title={`Copy ${title}`} aria-label={`Copy ${link.label}`} onClick={copy}><span aria-hidden>{ICON[link.kind]}</span>{copied ? "Copied" : link.label}{mark}</button>;
  }
  if (/^https:\/\//i.test(link.href)) return <a className="jg-orch-out" href={link.href} title={title} target="_blank" rel="noopener noreferrer"><span aria-hidden>{ICON[link.kind]}</span>{link.label}{mark}</a>;
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(link.href)) return null; // never route non-https URLs
  return <button type="button" className="jg-orch-out" onClick={() => onNavigate(link.href)}><span aria-hidden>{ICON[link.kind]}</span>{link.label}{mark}</button>;
}
