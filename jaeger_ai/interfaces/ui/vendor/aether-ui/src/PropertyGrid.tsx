import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { FieldRow } from "./FieldRow";

export interface PropertyGridItem {
  id: string;
  label: string;
  editor: ReactNode;
  help?: ReactNode;
  error?: ReactNode;
  modified?: boolean;
  mixed?: boolean;
  readOnly?: boolean;
  onReset?: () => void;
}

export interface PropertyGridSection {
  id: string;
  label: string;
  badge?: string;
  properties: readonly PropertyGridItem[];
}

export interface PropertyGridProps {
  sections: readonly PropertyGridSection[];
  ariaLabel: string;
  filter?: string;
  modifiedOnly?: boolean;
  collapsedIDs?: ReadonlySet<string>;
  defaultCollapsedIDs?: readonly string[];
  onToggleSection?: (id: string, expanded: boolean) => void;
  emptyState?: ReactNode;
  className?: string;
}

/** Shared inspector composition; applications supply editors and transactions. */
export function PropertyGrid({
  sections,
  ariaLabel,
  filter,
  modifiedOnly = false,
  collapsedIDs,
  defaultCollapsedIDs,
  onToggleSection,
  emptyState,
  className,
}: PropertyGridProps) {
  const [internalCollapsed, setInternalCollapsed] = useState<ReadonlySet<string>>(
    () => new Set(defaultCollapsedIDs ?? [])
  );
  const query = (filter ?? "").trim().toLocaleLowerCase();
  const visible = useMemo(
    () =>
      sections
        .map((section) => ({
          ...section,
          properties: section.properties.filter((property) => {
            if (modifiedOnly && !property.modified) return false;
            if (!query) return true;
            return `${section.label} ${property.label}`
              .toLocaleLowerCase()
              .includes(query);
          }),
        }))
        .filter((section) => section.properties.length > 0),
    [modifiedOnly, query, sections]
  );

  const toggle = (id: string) => {
    const collapsed = collapsedIDs
      ? collapsedIDs.has(id)
      : internalCollapsed.has(id);
    onToggleSection?.(id, collapsed);
    if (!collapsedIDs) {
      setInternalCollapsed((current) => {
        const next = new Set(current);
        if (collapsed) next.delete(id);
        else next.add(id);
        return next;
      });
    }
  };

  return (
    <div
      className={["aui-property-grid", className].filter(Boolean).join(" ")}
      role="region"
      aria-label={ariaLabel}
    >
      {visible.length === 0 ? (
        <div className="aui-property-grid-empty">{emptyState ?? "No properties"}</div>
      ) : (
        visible.map((section) => {
          const collapsed = collapsedIDs
            ? collapsedIDs.has(section.id)
            : internalCollapsed.has(section.id);
          return (
            <section key={section.id} className="aui-property-section">
              <button
                type="button"
                className="aui-property-section-heading"
                aria-expanded={!collapsed}
                onClick={() => toggle(section.id)}
              >
                <span aria-hidden="true">{collapsed ? "▸" : "▾"}</span>
                <strong>{section.label}</strong>
                {section.badge ? <small>{section.badge}</small> : null}
              </button>
              {!collapsed ? (
                <div className="aui-property-section-body">
                  {section.properties.map((property) => (
                    <div
                      key={property.id}
                      className={`aui-property-item${property.readOnly ? " aui-property-item--readonly" : ""}`}
                    >
                      <FieldRow
                        label={property.label}
                        help={property.help}
                        error={property.error}
                        modified={property.modified}
                        onReset={property.readOnly ? undefined : property.onReset}
                      >
                        <div className="aui-property-editor" aria-readonly={property.readOnly || undefined}>
                          {property.editor}
                          {property.mixed ? <span className="aui-property-mixed">Mixed</span> : null}
                        </div>
                      </FieldRow>
                    </div>
                  ))}
                </div>
              ) : null}
            </section>
          );
        })
      )}
    </div>
  );
}
