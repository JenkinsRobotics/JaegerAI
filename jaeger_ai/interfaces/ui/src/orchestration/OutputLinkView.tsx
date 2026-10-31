import type { OutputLink } from "./types";

export type Navigate = (href: string) => void;
const ICON: Record<OutputLink["kind"], string> = { session: "💬", handoff: "⇄", task: "☑", file: "📄", commit: "⌥", url: "↗", approval: "✋" };

export function OutputLinkView({ link, onNavigate }: { link: OutputLink; onNavigate: Navigate }) {
  if (/^https:\/\//.test(link.href)) return <a className="jg-orch-out" href={link.href} target="_blank" rel="noopener noreferrer"><span aria-hidden>{ICON[link.kind]}</span>{link.label}</a>;
  return <button type="button" className="jg-orch-out" onClick={() => onNavigate(link.href)}><span aria-hidden>{ICON[link.kind]}</span>{link.label}</button>;
}
