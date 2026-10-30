/**
 * PageHost (Jenkins Robotics, 2026-10-29, original).
 *
 * The in-app dashboard surface. Fixed frame — the window band above and the dock
 * below are owned by AppWindow and are untouched here. This file owns exactly three
 * things: the layout, the edit mode, and the gallery.
 *
 * `react-grid-layout` is imported here and nowhere else in the widget platform, so
 * swapping the grid engine later touches only this file.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Responsive, useContainerWidth, type LayoutItem } from "react-grid-layout";
import type { JaegerSource } from "../../api/source";
import { generateWidgetSpec } from "../../api/widgets";
import { Icon } from "../../icons/Icon";
import { WidgetSlot } from "./WidgetSlot";
import { allWidgets, pickSize, widgetByKind, isRetired } from "../registry";
import { customAiWidget, specKey, specToUnit, type AiWidgetSpec } from "../definitions/customAi";
import {
  addItem,
  loadLayout,
  removeItem,
  saveLayout,
  withHost,
  type LayoutTransport,
} from "../layoutStore";
import type { DashboardDoc, WidgetSize } from "../types";
import "react-grid-layout/css/styles.css";
import "react-resizable/css/styles.css";
import "./host.css";

const COLS = 12;
const ROW_HEIGHT = 40;

/** Grid units per widget size on the page host. */
const UNIT: Record<WidgetSize, { w: number; h: number }> = {
  sm: { w: 3, h: 3 },
  md: { w: 4, h: 4 },
  lg: { w: 6, h: 6 },
  xl: { w: 12, h: 8 },
  inline: { w: 3, h: 2 },
  circle: { w: 2, h: 3 },
  rect: { w: 4, h: 3 },
};

export interface PageHostProps {
  source?: JaegerSource;
  /** Gateway-backed layout transport. Omit to run read-only from the cache. */
  transport?: LayoutTransport;
}

export function PageHost({ source, transport }: PageHostProps) {
  const { width, containerRef } = useContainerWidth();
  const [doc, setDoc] = useState<DashboardDoc | null>(null);
  const [editing, setEditing] = useState(false);
  const [galleryOpen, setGalleryOpen] = useState(false);
  /** True once the gateway confirmed the dashboard route exists. */
  const [available, setAvailable] = useState(true);
  // Ask-AI state
  const [askPrompt, setAskPrompt] = useState("");
  const [askBusy, setAskBusy] = useState(false);
  const [askError, setAskError] = useState<string | null>(null);

  // Load the layout once (and when the transport identity changes).
  useEffect(() => {
    if (!transport) {
      setDoc({ v: 1, hosts: { page: [], float: [], overlay: [], menubar: [] } });
      setAvailable(false);
      return;
    }
    let live = true;
    void loadLayout(transport).then(({ doc: loaded, available: hasRoute }) => {
      if (!live) return;
      setDoc(loaded);
      setAvailable(hasRoute);
    });
    return () => {
      live = false;
    };
  }, [transport]);

  const items = doc?.hosts.page ?? [];
  const layouts = useMemo<Record<string, LayoutItem[]>>(
    () => ({ lg: items.map((g) => ({ i: g.i, x: g.x, y: g.y, w: g.w, h: g.h })) }),
    [items],
  );

  const persist = useCallback(
    async (next: DashboardDoc) => {
      setDoc(next);
      if (!transport) return;
      try {
        await saveLayout(transport, next);
        setAvailable(true);
      } catch {
        // Route not deployed yet: the local copy still applies for this session.
      }
    },
    [transport],
  );

  const onLayoutChange = useCallback(
    (layout: readonly LayoutItem[]) => {
      if (!editing || !doc) return;
      const next = withHost(
        doc,
        "page",
        layout.map((g) => ({ i: g.i, x: g.x, y: g.y, w: g.w, h: g.h })),
      );
      // Dragging updates local state only; Save commits.
      setDoc(next);
    },
    [doc, editing],
  );

  const add = useCallback(
    (kind: string) => {
      if (!doc) return;
      const def = widgetByKind(kind);
      if (!def) return;
      const size = pickSize(def.sizes, "lg");
      const unit = UNIT[size];
      void persist(addItem(doc, "page", { i: kind, x: 0, w: unit.w, h: unit.h }));
      setGalleryOpen(false);
    },
    [doc, persist],
  );

  /** Ask the gateway's model to design a widget, then place the returned spec on the grid. */
  const askAi = useCallback(async () => {
    const prompt = askPrompt.trim();
    if (!prompt || !doc || askBusy) return;
    setAskBusy(true);
    setAskError(null);
    try {
      const { spec } = await generateWidgetSpec(prompt);
      const key = specKey(spec as AiWidgetSpec);
      if (doc.hosts.page.some((g) => g.i === key)) {
        setAskError("That widget is already on your dashboard.");
        return;
      }
      const unit = specToUnit(spec as AiWidgetSpec);
      await persist(
        addItem(doc, "page", {
          i: key,
          x: 0,
          w: unit.w,
          h: unit.h,
          params: { spec },
        }),
      );
      setAskPrompt("");
      setGalleryOpen(false);
    } catch (err) {
      setAskError(err instanceof Error ? err.message : "Could not create the widget.");
    } finally {
      setAskBusy(false);
    }
  }, [askPrompt, doc, askBusy, persist]);

  const remove = useCallback(
    (kind: string) => {
      if (!doc) return;
      void persist(removeItem(doc, "page", kind));
    },
    [doc, persist],
  );

  if (!doc) {
    return (
      <div className="wg-page">
        <div className="wg-page__grid" aria-busy="true" />
      </div>
    );
  }

  const widgets = allWidgets().filter((d) => d.hosts.includes("page"));

  return (
    <div className="wg-page">
      {/* Window band: identical chrome to every other window (traffic-light reserve + drag). */}
      <div className="jg-band wg-band" data-aether-window-drag-region>
        <span className="jg-traffic-lights" aria-hidden="true"><i /><i /><i /></span>
        <h1 className="wg-page__title">Dashboard</h1>
        <div className="wg-page__tools">
          {editing && (
            <button type="button" className="wg-btn" onClick={() => setGalleryOpen((v) => !v)}>
              <Icon name="add" /> Add widget
            </button>
          )}
          <button
            type="button"
            className={`wg-btn${editing ? " wg-btn--primary" : ""}`}
            onClick={() => {
              if (editing && doc && transport) void persist(doc);
              setEditing((v) => !v);
              setGalleryOpen(false);
            }}
          >
            {editing ? "Done" : "Edit"}
          </button>
        </div>
      </div>

      {!available && (
        <p className="wg-page__note">
          Layout saving isn’t wired to this gateway yet — changes stay in this browser.
        </p>
      )}

      {galleryOpen && (
        <div className="wg-gallery" role="dialog" aria-label="Widget gallery">
          <div className="wg-ask">
            <label className="wg-ask__label" htmlFor="wg-ask-input">Ask Jaeger to design a widget</label>
            <div className="wg-ask__row">
              <input
                id="wg-ask-input"
                className="wg-ask__input"
                type="text"
                placeholder="e.g. show pending approvals and failed requests"
                value={askPrompt}
                maxLength={1000}
                disabled={askBusy}
                onChange={(e) => setAskPrompt(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void askAi();
                }}
              />
              <button
                type="button"
                className="wg-btn wg-btn--primary"
                disabled={askBusy || !askPrompt.trim()}
                onClick={() => void askAi()}
              >
                {askBusy ? "Asking…" : "Ask AI"}
              </button>
            </div>
            {askError && <p className="wg-ask__status wg-ask__status--error">{askError}</p>}
            {askBusy && <p className="wg-ask__status">Designing from live gateway data…</p>}
          </div>
          {widgets.length === 0 && <p className="wg-gallery__empty">No widgets registered.</p>}
          <ul className="wg-gallery__list">
            {widgets.map((def) => {
              const used = items.some((g) => g.i === def.kind);
              return (
                <li key={def.kind} className="wg-gallery__item">
                  <div>
                    <span className="wg-gallery__name">{def.title}</span>
                    <span className="wg-gallery__about">{def.about}</span>
                  </div>
                  <button
                    type="button"
                    className="wg-btn"
                    disabled={used}
                    onClick={() => add(def.kind)}
                  >
                    {used ? "Added" : "Add"}
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {items.length === 0 ? (
        <div className="wg-page__empty">
          <p>No widgets yet.</p>
          <button type="button" className="wg-btn wg-btn--primary" onClick={() => { setEditing(true); setGalleryOpen(true); }}>
            Add your first widget
          </button>
        </div>
      ) : (
        <div ref={containerRef} className="wg-page__grid">
          <Responsive
            className={`wg-grid${editing ? " wg-grid--editing" : ""}`}
            width={width}
            layouts={layouts}
            breakpoints={{ lg: 1000, md: 780, sm: 560, xs: 0 }}
            cols={{ lg: COLS, md: 8, sm: 6, xs: 4 }}
            rowHeight={ROW_HEIGHT}
            margin={[12, 12]}
            containerPadding={[0, 0]}
            dragConfig={{ enabled: editing, handle: ".wg-frame__head", threshold: 3 }}
            resizeConfig={{ enabled: editing }}
            onLayoutChange={onLayoutChange}
          >
            {items.map((item) => {
              const def = item.i.startsWith("custom.ai:") ? customAiWidget : widgetByKind(item.i);
              if (!def) {
                return (
                  <div key={item.i} className="wg-frame wg-frame--md wg-frame--full">
                    <div className="wg-frame__body">
                      {isRetired(item.i) ? (
                        <p className="wg-frame__retired">This widget was removed. Delete it.</p>
                      ) : (
                        <p className="wg-frame__retired">Unknown widget “{item.i}”. Delete it.</p>
                      )}
                    </div>
                  </div>
                );
              }
              const size = pickSize(def.sizes, "lg");
              // AI-generated widgets carry their own title in the persisted spec.
              const viewDef =
                item.i.startsWith("custom.ai:") && item.params?.spec
                  ? { ...def, title: (item.params.spec as AiWidgetSpec).title }
                  : def;
              return (
                <div key={item.i} className="wg-cell">
                  <WidgetSlot
                    def={viewDef as never}
                    source={source}
                    size={size}
                    tint="full"
                    host="page"
                    params={item.params}
                    actions={
                      editing ? (
                        <button
                          type="button"
                          className="wg-btn wg-btn--icon"
                          aria-label={`Remove ${def.title}`}
                          onClick={() => remove(item.i)}
                        >
                          <Icon name="close" />
                        </button>
                      ) : undefined
                    }
                  />
                </div>
              );
            })}
          </Responsive>
        </div>
      )}
    </div>
  );
}
