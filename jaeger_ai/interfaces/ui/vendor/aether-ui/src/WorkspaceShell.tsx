import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type {
  CSSProperties,
  PointerEvent as ReactPointerEvent,
  ReactNode,
} from "react";
import { Rail, RailButton } from "./Rail";
import type { PanelPlacement } from "./PanelPlacementMenu";

/**
 * The app-window chrome, ported from the Swift `StudioWorkspaceScaffold`:
 * three layout presets — DOCKED (sidebars in flow), FLOATING (chrome
 * floats over the canvas), CANVAS (chrome hidden; edge hot-zones reveal
 * it on hover) — with per-side panel stacks toggled from icon rails and
 * tear-off floating panels that drag anywhere and restack near their
 * home edge. Spec lives in WIDGETS.md ("WorkspaceShell").
 */
export type LayoutPreset = "docked" | "floating" | "canvas";

export interface WorkspacePanel {
  id: string;
  title: string;
  icon: ReactNode;
  content: ReactNode;
  /** Docked presentation renders no title/float/close header; the panel content owns its heading. Rail toggle still closes it. */
  chromeless?: boolean;
}

const PRESET_ORDER: readonly LayoutPreset[] = ["floating", "docked", "canvas"];
const PRESET_GLYPH: Record<LayoutPreset, string> = {
  floating: "❏",
  docked: "▥",
  canvas: "⛶",
};
const LEFT_PANEL_WIDTH = 232;
const RIGHT_PANEL_WIDTH = 248;
const RESTACK_DISTANCE = 110;

export function nextLayoutPreset(preset: LayoutPreset): LayoutPreset {
  return PRESET_ORDER[(PRESET_ORDER.indexOf(preset) + 1) % PRESET_ORDER.length];
}

/** The studio layout button: cycles Floating → Docked → Canvas. */
export function LayoutPresetButton({
  preset,
  onChange,
}: {
  preset: LayoutPreset;
  onChange: (preset: LayoutPreset) => void;
}) {
  const next = nextLayoutPreset(preset);
  return (
    <button
      type="button"
      className="aui-icon-button"
      title={`Layout: ${preset} — click for ${next}`}
      aria-label={`Layout ${preset}, switch to ${next}`}
      onClick={() => onChange(next)}
    >
      {PRESET_GLYPH[preset]}
    </button>
  );
}

export interface FloatingPanelProps {
  title: string;
  x: number;
  y: number;
  width?: number;
  onMove: (x: number, y: number) => void;
  onDragEnd?: (x: number, y: number) => void;
  onDock?: () => void;
  onClose?: () => void;
  children: ReactNode;
}

/** A draggable floating panel (drag by header). Also used standalone for
 *  short-lived tools that must stay visible above the workspace. */
export function FloatingPanel(props: FloatingPanelProps) {
  const { title, x, y, width = LEFT_PANEL_WIDTH } = props;
  const drag = useRef<{ startX: number; startY: number; baseX: number; baseY: number } | null>(null);
  const pos = useRef({ x, y });
  pos.current = { x, y };

  const onPointerDown = (event: ReactPointerEvent) => {
    if ((event.target as HTMLElement).closest("button")) return;
    drag.current = { startX: event.clientX, startY: event.clientY, baseX: x, baseY: y };
    (event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId);
  };
  const onPointerMove = (event: ReactPointerEvent) => {
    if (!drag.current) return;
    props.onMove(
      drag.current.baseX + event.clientX - drag.current.startX,
      drag.current.baseY + event.clientY - drag.current.startY
    );
  };
  const onPointerUp = () => {
    if (!drag.current) return;
    drag.current = null;
    props.onDragEnd?.(pos.current.x, pos.current.y);
  };

  return (
    <div className="aui-float-panel" style={{ left: x, top: y, width }}>
      <div
        className="aui-float-panel-header"
        tabIndex={0}
        role="group"
        aria-label={`Move ${title}`}
        onKeyDown={(event) => {
          const step = event.shiftKey ? 40 : 10;
          const delta = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[event.key];
          if (!delta || event.target !== event.currentTarget) return;
          event.preventDefault();
          props.onMove(x + delta[0], y + delta[1]);
        }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
      >
        <span className="aui-float-panel-title">{title}</span>
        <span className="aui-float-panel-actions">
          {props.onDock ? (
            <button
              type="button"
              className="aui-float-panel-action"
              title="Dock panel"
              aria-label={`Dock ${title}`}
              onClick={props.onDock}
            >
              ⇤
            </button>
          ) : null}
          {props.onClose ? (
            <button
              type="button"
              className="aui-float-panel-action"
              title="Close panel"
              aria-label={`Close ${title}`}
              onClick={props.onClose}
            >
              ✕
            </button>
          ) : null}
        </span>
      </div>
      <div className="aui-float-panel-body">{props.children}</div>
    </div>
  );
}

export interface WorkspaceShellProps {
  preset: LayoutPreset;
  /** Preserve panel DOM, drafts and external editor bindings across layout/visibility changes. */
  preservePanelContent?: boolean;
  /** Versioned device-local layouts, remembered independently per preset. */
  storageKey?: string;
  /** Usually a <Ribbon>; docked above the canvas or floating top-center. */
  toolbar?: ReactNode;
  leftPanels?: readonly WorkspacePanel[];
  rightPanels?: readonly WorkspacePanel[];
  defaultOpenLeft?: readonly string[];
  defaultOpenRight?: readonly string[];
  /** Controlled stable-ID panel presentation. Omit for shell-owned state. */
  panelState?: WorkspacePanelState;
  /** Additional initial state used only when `panelState` is uncontrolled. */
  defaultPanelState?: WorkspacePanelState;
  /** Emits a complete state snapshot after any visibility or position change. */
  onPanelStateChange?: (state: WorkspacePanelState) => void;
  /** Bottom editor strip under the canvas (dope sheet, curves, log). */
  bottom?: ReactNode;
  statusBar?: ReactNode;
  style?: CSSProperties;
  /** The center canvas/viewport. */
  children: ReactNode;
}

export interface WorkspaceFloatingPosition {
  x: number;
  y: number;
}

export interface WorkspacePanelPresentation {
  placement: PanelPlacement;
  position?: Readonly<WorkspaceFloatingPosition>;
}

export type WorkspacePanelState = Readonly<
  Record<string, Readonly<WorkspacePanelPresentation>>
>;

function readPanelLayout(key: string, preset: LayoutPreset, fallback: WorkspacePanelState): WorkspacePanelState {
  try {
    const saved = JSON.parse(localStorage.getItem(key) ?? "null");
    if (saved?.version !== 1 || !saved.layouts?.[preset]) return fallback;
    const result: Record<string, WorkspacePanelPresentation> = { ...fallback };
    for (const [id, value] of Object.entries(saved.layouts[preset])) {
      const entry = value as WorkspacePanelPresentation;
      if (!entry || !["docked", "floating", "hidden"].includes(entry.placement)) return fallback;
      if (entry.position && (!Number.isFinite(entry.position.x) || !Number.isFinite(entry.position.y))) return fallback;
      result[id] = entry;
    }
    return result;
  } catch { return fallback; }
}

type Edge = "top" | "left" | "right";

export function WorkspaceShell(props: WorkspaceShellProps) {
  const {
    preset, toolbar, bottom, statusBar, style, children,
    leftPanels = [], rightPanels = [],
  } = props;
  const bodyRef = useRef<HTMLDivElement>(null);
  const panelHosts = useRef(new Map<string, HTMLDivElement>());
  const allPanels = [...leftPanels, ...rightPanels];
  // Stable portal destinations preserve editor state while chrome is rearranged.
  // SSR renders inline; browser slots relocate the same host element.
  if (props.preservePanelContent && typeof document !== "undefined") {
    for (const panel of allPanels) {
      if (!panelHosts.current.has(panel.id)) {
        const host = document.createElement("div");
        // Named so the docked height chain reaches the app's own panel: an
        // unclassed div here left every panel content-height.
        host.className = "aui-shell-panel-host";
        panelHosts.current.set(panel.id, host);
      }
    }
  }
  const panelContent = (panel: WorkspacePanel) => {
    const host = props.preservePanelContent ? panelHosts.current.get(panel.id) : undefined;
    return host ? <div className="aui-shell-panel-slot" ref={(slot) => {
      if (slot && host.parentElement !== slot) slot.appendChild(host);
    }} /> : panel.content;
  };
  const [uncontrolledPanelState, setUncontrolledPanelState] =
    useState<WorkspacePanelState>(() => {
      const initial: Record<string, WorkspacePanelPresentation> = {
        ...(props.defaultPanelState ?? {}),
      };
      for (const id of props.defaultOpenLeft ?? []) {
        initial[id] ??= { placement: "docked" };
      }
      for (const id of props.defaultOpenRight ?? []) {
        initial[id] ??= { placement: "docked" };
      }
      return props.storageKey ? readPanelLayout(props.storageKey, preset, initial) : initial;
    });
  const previousPreset = useRef(preset);
  const initialPanelState = useRef<WorkspacePanelState>({
    ...Object.fromEntries([...(props.defaultOpenLeft ?? []), ...(props.defaultOpenRight ?? [])].map((id) => [id, { placement: "docked" as const }])),
    ...(props.defaultPanelState ?? {}),
  });
  useEffect(() => {
    if (!props.storageKey || props.panelState !== undefined) return;
    if (previousPreset.current !== preset) {
      previousPreset.current = preset;
      setUncontrolledPanelState(readPanelLayout(props.storageKey, preset, initialPanelState.current));
      return;
    }
    try {
      let saved;
      try { saved = JSON.parse(localStorage.getItem(props.storageKey) ?? "null"); } catch { saved = null; }
      const layouts = saved?.version === 1 ? saved.layouts ?? {} : {};
      localStorage.setItem(props.storageKey, JSON.stringify({ version: 1, layouts: { ...layouts, [preset]: uncontrolledPanelState } }));
    } catch { /* Preferences never block editing. */ }
  }, [preset, uncontrolledPanelState, props.storageKey, props.panelState]);
  const panelState = props.panelState ?? uncontrolledPanelState;
  useEffect(() => {
    const body = bodyRef.current;
    if (!body || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      const next = { ...panelState };
      let changed = false;
      for (const panel of allPanels) {
        const entry = next[panel.id];
        if (entry?.placement !== "floating" || !entry.position) continue;
        const width = leftPanels.includes(panel) ? LEFT_PANEL_WIDTH : RIGHT_PANEL_WIDTH;
        const position = {
          x: Math.max(8, Math.min(entry.position.x, body.clientWidth - width - 8)),
          y: Math.max(8, Math.min(entry.position.y, body.clientHeight - 48)),
        };
        if (position.x !== entry.position.x || position.y !== entry.position.y) {
          next[panel.id] = { ...entry, position };
          changed = true;
        }
      }
      if (changed) {
        if (props.panelState === undefined) setUncontrolledPanelState(next);
        props.onPanelStateChange?.(next);
      }
    });
    observer.observe(body);
    return () => observer.disconnect();
  }, [panelState, props.onPanelStateChange]);
  const [revealed, setRevealed] = useState<ReadonlySet<Edge>>(new Set());
  const hideTimers = useRef(new Map<Edge, ReturnType<typeof setTimeout>>());

  const reveal = useCallback((edge: Edge) => {
    const timer = hideTimers.current.get(edge);
    if (timer) clearTimeout(timer);
    setRevealed((current) => {
      if (current.has(edge)) return current;
      return new Set(current).add(edge);
    });
  }, []);
  const scheduleHide = useCallback((edge: Edge) => {
    const timer = hideTimers.current.get(edge);
    if (timer) clearTimeout(timer);
    hideTimers.current.set(
      edge,
      setTimeout(() => {
        setRevealed((current) => {
          const next = new Set(current);
          next.delete(edge);
          return next;
        });
      }, 160)
    );
  }, []);

  const panelsFor = (side: "left" | "right") =>
    side === "left" ? leftPanels : rightPanels;
  const widthFor = (side: "left" | "right") =>
    side === "left" ? LEFT_PANEL_WIDTH : RIGHT_PANEL_WIDTH;

  const presentationFor = (id: string): WorkspacePanelPresentation =>
    panelState[id] ?? { placement: "hidden" };

  const updatePanel = (id: string, next: WorkspacePanelPresentation) => {
    const updated: WorkspacePanelState = { ...panelState, [id]: next };
    if (props.panelState === undefined) setUncontrolledPanelState(updated);
    props.onPanelStateChange?.(updated);
  };

  const togglePanel = (_side: "left" | "right", id: string) => {
    const current = presentationFor(id);
    updatePanel(
      id,
      current.placement === "hidden"
        ? { placement: "docked" }
        : { placement: "hidden" },
    );
  };

  const detachPanel = (side: "left" | "right", id: string) => {
    const body = bodyRef.current;
    const count = panelsFor(side).filter(
      (panel) => presentationFor(panel.id).placement === "floating",
    ).length;
    const width = widthFor(side);
    const x =
      side === "left"
        ? 64 + count * 18
        : Math.max(64, (body?.clientWidth ?? 900) - 64 - width - count * 18);
    updatePanel(id, {
      placement: "floating",
      position: { x, y: 56 + count * 28 },
    });
  };

  const restackPanel = (_side: "left" | "right", id: string) => {
    updatePanel(id, { placement: "docked" });
  };

  const movePanel = (side: "left" | "right", id: string, x: number, y: number) => {
    const body = bodyRef.current;
    const width = widthFor(side);
    const maxX = (body?.clientWidth ?? 1200) - width - 8;
    const maxY = (body?.clientHeight ?? 700) - 48;
    const clamped = {
      x: Math.min(Math.max(x, 8), Math.max(8, maxX)),
      y: Math.min(Math.max(y, 8), Math.max(8, maxY)),
    };
    updatePanel(id, { placement: "floating", position: clamped });
  };

  const maybeRestack = (side: "left" | "right", id: string, x: number) => {
    const bodyWidth = bodyRef.current?.clientWidth ?? 1200;
    const nearHome =
      side === "left"
        ? x < RESTACK_DISTANCE
        : bodyWidth - (x + widthFor(side)) < RESTACK_DISTANCE;
    if (nearHome) restackPanel(side, id);
  };

  const rail = (side: "left" | "right") => {
    return (
      <Rail>
        {panelsFor(side).map((panel) => (
          <RailButton
            key={panel.id}
            label={panel.title}
            active={presentationFor(panel.id).placement !== "hidden"}
            onClick={() => togglePanel(side, panel.id)}
          >
            {panel.icon}
          </RailButton>
        ))}
      </Rail>
    );
  };

  const stackedCard = (side: "left" | "right", panel: WorkspacePanel) => (
    <div key={panel.id} className="aui-shell-panel" style={{ width: widthFor(side) }}>
      {panel.chromeless ? null : <div className="aui-shell-panel-header">
        <span>{panel.title}</span>
        <span className="aui-float-panel-actions">
          <button
            type="button"
            className="aui-float-panel-action"
            title="Float panel"
            aria-label={`Float ${panel.title}`}
            onClick={() => detachPanel(side, panel.id)}
          >
            ⇱
          </button>
          <button
            type="button"
            className="aui-float-panel-action"
            title="Close panel"
            aria-label={`Close ${panel.title}`}
            onClick={() => togglePanel(side, panel.id)}
          >
            ✕
          </button>
        </span>
      </div>}
      <div className="aui-shell-panel-body">{panelContent(panel)}</div>
    </div>
  );

  const stackedIDs = (side: "left" | "right") => {
    return panelsFor(side)
      .filter((panel) => presentationFor(panel.id).placement === "docked")
      .map((panel) => panel.id);
  };

  const tornLayer = (side: "left" | "right") => {
    return panelsFor(side)
      .filter((panel) => presentationFor(panel.id).placement === "floating")
      .map((panel) => {
        const position = presentationFor(panel.id).position ?? { x: 64, y: 56 };
        return (
          <FloatingPanel
            key={panel.id}
            title={panel.title}
            x={position.x}
            y={position.y}
            width={widthFor(side)}
            onMove={(x, y) => movePanel(side, panel.id, x, y)}
            onDragEnd={(x) => maybeRestack(side, panel.id, x)}
            onDock={() => restackPanel(side, panel.id)}
            onClose={() => togglePanel(side, panel.id)}
          >
            {panelContent(panel)}
          </FloatingPanel>
        );
      });
  };

  const floatingStack = (side: "left" | "right") => {
    const ids = stackedIDs(side);
    return (
      <div className={`aui-shell-fledge aui-shell-fledge--${side}`}>
        {side === "right" && ids.length > 0 ? floatingCards(side, ids) : null}
        <div className="aui-float">{rail(side)}</div>
        {side === "left" && ids.length > 0 ? floatingCards(side, ids) : null}
      </div>
    );
  };

  const floatingCards = (side: "left" | "right", ids: readonly string[]) => (
    <div className="aui-shell-flstack">
      {panelsFor(side)
        .filter((panel) => ids.includes(panel.id))
        .map((panel) => (
          <div key={panel.id} className="aui-float">
            {stackedCard(side, panel)}
          </div>
        ))}
    </div>
  );

  const canvasEdge = (edge: Edge, content: ReactNode) => (
    <div
      className={`aui-shell-edge aui-shell-edge--${edge}`}
      onMouseEnter={() => reveal(edge)}
      onMouseLeave={() => scheduleHide(edge)}
    >
      {revealed.has(edge) ? (
        content
      ) : (
        <div className={`aui-shell-handle aui-shell-handle--${edge}`} />
      )}
    </div>
  );

  const overlayChrome = (canvasMode: boolean) => {
    const top = toolbar ? (
      <div className="aui-shell-fltoolbar">
        <div className="aui-float">{toolbar}</div>
      </div>
    ) : null;
    const leftChrome = leftPanels.length ? floatingStack("left") : null;
    const rightChrome = rightPanels.length ? floatingStack("right") : null;
    if (!canvasMode) {
      return (
        <>
          {top}
          {leftChrome}
          {rightChrome}
        </>
      );
    }
    return (
      <>
        {top ? canvasEdge("top", top) : null}
        {leftChrome ? canvasEdge("left", leftChrome) : null}
        {rightChrome ? canvasEdge("right", rightChrome) : null}
      </>
    );
  };

  const dockedSide = (side: "left" | "right") => {
    const panels = panelsFor(side);
    const ids = stackedIDs(side);
    const isRight = side === "right";
    const visible = preset === "docked" && panels.length > 0;
    return (
      <div
        className={`aui-shell-side${isRight ? " aui-shell-side--right" : ""}`}
        hidden={!visible}
      >
        {visible && isRight && ids.length > 0 ? (
          <div className="aui-shell-stack">
            {panels
              .filter((panel) => ids.includes(panel.id))
              .map((panel) => stackedCard(side, panel))}
          </div>
        ) : null}
        {visible ? rail(side) : null}
        {visible && !isRight && ids.length > 0 ? (
          <div className="aui-shell-stack">
            {panels
              .filter((panel) => ids.includes(panel.id))
              .map((panel) => stackedCard(side, panel))}
          </div>
        ) : null}
      </div>
    );
  };

  return (
    <div className="aui-shell" style={style}>
      <div className="aui-shell-body">
        <div className="aui-shell-area" ref={bodyRef}>
          {dockedSide("left")}
          <div className="aui-shell-main">
            <div
              className="aui-shell-toolbar"
              hidden={preset !== "docked" || !toolbar}
            >
              {preset === "docked" ? toolbar : null}
            </div>
            <div className="aui-shell-center">{children}</div>
          </div>
          {dockedSide("right")}
          {preset !== "docked" ? overlayChrome(preset === "canvas") : null}
          {tornLayer("left")}
          {tornLayer("right")}
          {props.preservePanelContent ? <div hidden>
            {allPanels.filter((panel) => presentationFor(panel.id).placement === "hidden" || (preset === "canvas" && presentationFor(panel.id).placement === "docked" && !revealed.has(leftPanels.includes(panel) ? "left" : "right")))
              .map((panel) => <div key={panel.id}>{panelContent(panel)}</div>)}
          </div> : null}
          {props.preservePanelContent ? allPanels.map((panel) => {
            const host = panelHosts.current.get(panel.id);
            return host ? createPortal(panel.content, host, panel.id) : null;
          }) : null}
        </div>
        {bottom}
      </div>
      {statusBar}
    </div>
  );
}
