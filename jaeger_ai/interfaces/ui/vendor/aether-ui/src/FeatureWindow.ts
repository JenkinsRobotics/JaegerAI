/** The suite-standard floating feature window (Onshape-anatomy):
 * header = title + green ✓ accept + red ✕ discard, draggable; body takes an
 * entities box, inline parameter rows, and a status line. Every feature
 * editor (plane, extrude, mirror, mates…) mounts through this one module. */

export interface FeatureWindowOptions {
  viewport: HTMLElement;
  className: string;
  title: string;
  acceptLabel: string;
  discardLabel: string;
  onAccept: () => void | Promise<void>;
  onDiscard: () => void | Promise<void>;
}

export interface FeatureWindow {
  panel: HTMLElement;
  body: HTMLElement;
  status: HTMLElement;
  close: () => void;
  /** Put the window in the error state (red title + message) or clear it.
   *  Accept is disabled while an error is showing. */
  setError: (message: string | null) => void;
  /** Captioned bordered selection list; render() replaces its rows. */
  entitiesBox: (caption?: string) => {
    element: HTMLElement;
    render: (rows: { label: string; onRemove: () => void }[]) => void;
  };
  /** Inline row: label left, controls right (Onshape parameter row). */
  row: (label: string, ...controls: HTMLElement[]) => HTMLElement;
  /** Segmented tab row (e.g. Solid/Surface/Thin, New/Add/Remove/Intersect). */
  tabs: (labels: string[], activeIndex?: number) => HTMLElement;
  /** A dropdown anchored to its field: the popup opens directly beneath,
   *  matching the field width. Native <select> popups overlay the control
   *  (macOS centres the current value on the cursor), which reads as
   *  misaligned inside a feature window. */
  picker: (
    options: readonly string[],
    config?: { value?: string; ariaLabel?: string; onChange?: (value: string) => void },
  ) => FeaturePicker;
  /** A sub-setting block: its children indent beneath a toggle, the way
   *  Onshape nests options that only apply when the parent is on. */
  subsection: (
    label: string,
    options?: { kind?: "checkbox" | "disclosure"; open?: boolean; onToggle?: (open: boolean) => void },
  ) => FeatureSubsection;
}

export interface FeaturePicker {
  /** Place this in a row or the body; it carries the popup with it. */
  element: HTMLElement;
  value: () => string;
  setValue: (value: string) => void;
}

export interface FeatureSubsection {
  element: HTMLElement;
  /** Container for the nested rows. */
  body: HTMLElement;
  setOpen: (open: boolean) => void;
  isOpen: () => boolean;
}

export function openFeatureWindow(options: FeatureWindowOptions): FeatureWindow {
  const panel = document.createElement("aside");
  panel.className = `aui-float-panel aui-feature-window ${options.className}`;
  const header = document.createElement("div");
  header.className = "aui-float-panel-header";
  const title = document.createElement("span");
  title.className = "aui-float-panel-title";
  title.textContent = options.title;
  header.append(title);
  const actions = document.createElement("span");
  actions.className = "aui-float-panel-actions";
  const accept = document.createElement("button");
  accept.type = "button";
  accept.className = "aui-feature-accept";
  accept.textContent = "✓";
  accept.setAttribute("aria-label", options.acceptLabel);
  const discard = document.createElement("button");
  discard.type = "button";
  discard.className = "aui-feature-discard";
  discard.textContent = "✕";
  discard.setAttribute("aria-label", options.discardLabel);
  actions.append(accept, discard);
  header.append(actions);
  panel.append(header);
  const body = document.createElement("div");
  body.className = "aui-float-panel-body";
  panel.append(body);
  const status = document.createElement("p");
  status.setAttribute("role", "status");

  let panelX = 0,
    panelY = 0;
  header.addEventListener("pointerdown", (e) => {
    if ((e.target as HTMLElement).closest("button")) return;
    const startX = e.clientX - panelX,
      startY = e.clientY - panelY;
    header.setPointerCapture(e.pointerId);
    const move = (ev: PointerEvent) => {
      panelX = ev.clientX - startX;
      panelY = ev.clientY - startY;
      panel.style.transform = `translate(${panelX}px, ${panelY}px)`;
    };
    const up = () => {
      header.removeEventListener("pointermove", move);
      header.removeEventListener("pointerup", up);
    };
    header.addEventListener("pointermove", move);
    header.addEventListener("pointerup", up);
  });

  accept.onclick = () => void options.onAccept();
  discard.onclick = () => void options.onDiscard();
  // Enter anywhere in the window commits, mirroring the ✓.
  panel.addEventListener("keydown", (e) => {
    const target = e.target as HTMLElement | null;
    if (e.key !== "Enter" || target?.tagName === "TEXTAREA") return;
    // Inside a form, native implicit submission already handles Enter.
    if (target?.closest?.("form")) return;
    e.preventDefault();
    void options.onAccept();
  });
  const close = () => panel.remove();
  const error = document.createElement("p");
  error.className = "aui-feature-error";
  error.hidden = true;
  error.setAttribute("role", "alert");
  const setError = (message: string | null) => {
    error.textContent = message ?? "";
    error.hidden = !message;
    panel.classList.toggle("invalid", Boolean(message));
    accept.disabled = Boolean(message);
    if (message) body.prepend(error);
  };

  const entitiesBox: FeatureWindow["entitiesBox"] = (caption = "Entities") => {
    const element = document.createElement("div");
    element.className = "aui-feature-entities";
    element.setAttribute("aria-label", caption);
    const label = document.createElement("span");
    label.className = "aui-feature-entities-caption";
    label.textContent = caption;
    element.append(label);
    const list = document.createElement("div");
    element.append(list);
    body.append(element);
    body.append(status);
    return {
      element,
      render(rows) {
        list.replaceChildren();
        for (const { label: text, onRemove } of rows) {
          const row = document.createElement("div");
          row.className = "aui-feature-entity";
          const name = document.createElement("span");
          name.textContent = text;
          const remove = document.createElement("button");
          remove.type = "button";
          remove.textContent = "×";
          remove.setAttribute("aria-label", `Remove ${text}`);
          remove.onclick = onRemove;
          row.append(name, remove);
          list.append(row);
        }
      },
    };
  };

  const row: FeatureWindow["row"] = (label, ...controls) => {
    const element = document.createElement("div");
    element.className = "aui-feature-row";
    const caption = document.createElement("span");
    caption.textContent = label;
    element.append(caption, ...controls);
    body.append(element);
    body.append(status);
    return element;
  };

  const tabs: FeatureWindow["tabs"] = (labels, activeIndex = 0) => {
    const element = document.createElement("div");
    element.className = "aui-feature-tabs";
    labels.forEach((text, index) => {
      const tab = document.createElement("button");
      tab.type = "button";
      tab.textContent = text;
      tab.className = index === activeIndex ? "active" : "";
      tab.onclick = () => {
        for (const sibling of element.children) sibling.classList.remove("active");
        tab.classList.add("active");
      };
      element.append(tab);
    });
    body.append(element);
    body.append(status);
    return element;
  };

  const picker: FeatureWindow["picker"] = (options, config = {}) => {
    let current = config.value ?? options[0] ?? "";
    const element = document.createElement("span");
    element.className = "aui-feature-picker";
    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "aui-feature-picker-trigger";
    trigger.setAttribute("aria-haspopup", "listbox");
    trigger.setAttribute("aria-expanded", "false");
    if (config.ariaLabel) trigger.setAttribute("aria-label", config.ariaLabel);
    const label = document.createElement("span");
    const chevron = document.createElement("span");
    chevron.className = "aui-feature-picker-chevron";
    chevron.textContent = "▾";
    trigger.append(label, chevron);
    const menu = document.createElement("div");
    menu.className = "aui-feature-picker-menu";
    menu.setAttribute("role", "listbox");
    menu.hidden = true;
    const paint = () => {
      label.textContent = current;
      for (const child of menu.children) {
        const option = child as HTMLElement;
        option.setAttribute("aria-selected", String(option.dataset.value === current));
      }
    };
    const close = () => {
      menu.hidden = true;
      trigger.setAttribute("aria-expanded", "false");
    };
    for (const option of options) {
      const item = document.createElement("button");
      item.type = "button";
      item.setAttribute("role", "option");
      item.dataset.value = option;
      item.textContent = option;
      item.onclick = () => {
        current = option;
        paint();
        close();
        config.onChange?.(option);
      };
      menu.append(item);
    }
    trigger.onclick = () => {
      const opening = menu.hidden;
      menu.hidden = !opening;
      trigger.setAttribute("aria-expanded", String(opening));
    };
    document.addEventListener("pointerdown", (event) => {
      if (!element.contains(event.target as Node)) close();
    });
    element.addEventListener("keydown", (event) => {
      if (event.key === "Escape") close();
    });
    element.append(trigger, menu);
    paint();
    return {
      element,
      value: () => current,
      setValue: (value) => {
        current = value;
        paint();
      },
    };
  };

  const subsection: FeatureWindow["subsection"] = (label, config = {}) => {
    const kind = config.kind ?? "checkbox";
    const element = document.createElement("div");
    element.className = "aui-feature-subsection";
    const header = document.createElement("div");
    header.className = "aui-feature-subsection-header";
    const nested = document.createElement("div");
    nested.className = "aui-feature-subsection-body";
    // Disclosure groups start expanded so their settings are visible;
    // checkbox groups stay closed until their box is ticked.
    let open = config.open ?? kind === "disclosure";
    const apply = () => {
      nested.hidden = !open;
      element.classList.toggle("open", open);
    };
    if (kind === "checkbox") {
      const box = document.createElement("input");
      box.type = "checkbox";
      box.checked = open;
      box.setAttribute("aria-label", label);
      const caption = document.createElement("span");
      caption.textContent = label;
      box.onchange = () => {
        open = box.checked;
        apply();
        config.onToggle?.(open);
      };
      header.append(caption, box);
    } else {
      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "aui-feature-disclosure";
      const caption = document.createElement("span");
      caption.textContent = label;
      const chevron = document.createElement("span");
      chevron.className = "aui-feature-chevron";
      chevron.textContent = open ? "▾" : "▸";
      toggle.append(chevron, caption);
      toggle.onclick = () => {
        open = !open;
        chevron.textContent = open ? "▾" : "▸";
        apply();
        config.onToggle?.(open);
      };
      header.append(toggle);
    }
    apply();
    element.append(header, nested);
    body.append(element);
    body.append(status);
    return {
      element,
      body: nested,
      setOpen: (next) => {
        open = next;
        apply();
      },
      isOpen: () => open,
    };
  };

  options.viewport.append(panel);
  body.append(status);
  return { panel, body, status, close, setError, entitiesBox, row, tabs, picker, subsection };
}
