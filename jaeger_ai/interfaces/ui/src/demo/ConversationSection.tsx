import { useEffect, useId, useState, type ReactNode } from "react";
import { ChevronRight } from "../components/Icons";
import "./conversationSection.css";

type SectionId = "pinned" | "projects" | "recents";

/** Device-local navigation preference; conversation data remains Gateway-owned. */
export function ConversationSection({ id, title, children }: { id: SectionId; title: string; children: ReactNode }) {
  const storageKey = `jaeger.sidebar.section.${id}.expanded.v1`;
  const [expanded, setExpanded] = useState(() => {
    try { return localStorage.getItem(storageKey) !== "false"; }
    catch { return true; }
  });
  const contentId = useId();
  useEffect(() => {
    try { localStorage.setItem(storageKey, String(expanded)); }
    catch { /* Navigation still works when browser storage is unavailable. */ }
  }, [expanded, storageKey]);
  return <section className="jg-stable-demo__session-section jg-sidebar-section" data-expanded={expanded}>
    <h2><button type="button" className="jg-sidebar-section__toggle" aria-expanded={expanded} aria-controls={contentId} onClick={() => setExpanded(value => !value)}>
      <span>{title}</span><ChevronRight size={15} className="jg-sidebar-section__chevron" />
    </button></h2>
    <div id={contentId} hidden={!expanded}>{children}</div>
  </section>;
}
