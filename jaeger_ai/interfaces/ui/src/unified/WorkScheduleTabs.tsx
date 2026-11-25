export function WorkScheduleTabs({ active, onNavigate }: { active: "agenda" | "automations"; onNavigate: (path: string) => void }) {
  return <nav className="jg-work-toolbar" aria-label="Schedule views">
    <button type="button" className="jg-u-btn" aria-current={active === "agenda" ? "page" : undefined} onClick={() => onNavigate("/work/calendar")}>Agenda</button>
    <button type="button" className="jg-u-btn" aria-current={active === "automations" ? "page" : undefined} onClick={() => onNavigate("/automations")}>Automations</button>
  </nav>;
}
