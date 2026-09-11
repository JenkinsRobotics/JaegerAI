/* JaegerAI branding + Surfaces chrome for Hermes WebUI (:8790).
 *
 * Loaded through Hermes WebUI's extension mechanism. Keeps upstream HTML
 * unmodified while giving Mac-parity AGENTS list (Gateway /api/agents proxy)
 * and Jaeger-facing chrome (not Hermes-first).
 */
(() => {
  "use strict";

  const iconVersion = "jaeger-app-icon-v1";
  const extensionAsset = (name) => `/extensions/${name}?v=${iconVersion}`;

  const installJaegerIcons = () => {
    if (!document.head) return;
    document.head
      .querySelectorAll(
        'link[rel="icon"], link[rel="shortcut icon"], link[rel="apple-touch-icon"]'
      )
      .forEach((node) => node.remove());
    const icons = [
      { rel: "icon", sizes: "16x16", href: extensionAsset("jaeger_app_icon_16.png") },
      { rel: "icon", sizes: "32x32", href: extensionAsset("jaeger_app_icon_32.png") },
      { rel: "shortcut icon", sizes: "256x256", href: extensionAsset("jaeger_app_icon_256.png") },
      { rel: "apple-touch-icon", sizes: "256x256", href: extensionAsset("jaeger_app_icon_256.png") },
    ];
    for (const icon of icons) {
      const link = document.createElement("link");
      link.rel = icon.rel;
      link.type = "image/png";
      link.sizes = icon.sizes;
      link.href = icon.href;
      link.dataset.jaegerBranding = "true";
      document.head.appendChild(link);
    }
  };

  const installJaegerSurfaceLabels = () => {
    try {
      document.title = "Jaeger";
      const apple = document.querySelector('meta[name="apple-mobile-web-app-title"]');
      if (apple) apple.setAttribute("content", "Jaeger");
      const titlebar = document.getElementById("appTitlebarTitle");
      if (titlebar) titlebar.textContent = "Jaeger";
      const msg = document.getElementById("msg");
      if (msg && /Message Hermes/i.test(msg.getAttribute("placeholder") || "")) {
        msg.setAttribute("placeholder", "Message Jaeger…");
      }
    } catch (_) {}
  };

  const hideTodosSurfaces = () => {
    // S1 / product: no /api/todos route — hide rail + mobile + workspace todos.
    try {
      document.querySelectorAll('[data-panel="todos"]').forEach((el) => {
        el.hidden = true;
        el.setAttribute("aria-hidden", "true");
        el.style.display = "none";
      });
      const panel = document.getElementById("panelTodos");
      if (panel) {
        panel.hidden = true;
        panel.style.display = "none";
      }
      const wsTab = document.getElementById("workspaceTodosTab");
      if (wsTab) {
        wsTab.hidden = true;
        wsTab.style.display = "none";
      }
      const wsPanel = document.getElementById("workspaceTodosPanel");
      if (wsPanel) wsPanel.hidden = true;
    } catch (_) {}
  };

  const hideHermesDashboardChrome = () => {
    try {
      document.querySelectorAll("[data-dashboard-link], .dashboard-link").forEach((el) => {
        el.style.display = "none";
        el.hidden = true;
      });
    } catch (_) {}
  };

  const ensureAgentsStyles = () => {
    if (document.getElementById("jaeger-agents-style")) return;
    const style = document.createElement("style");
    style.id = "jaeger-agents-style";
    style.textContent = `
      #jaegerAgentsSection { padding: 8px 8px 4px; border-bottom: 1px solid var(--border, rgba(255,255,255,0.06)); }
      #jaegerAgentsSection .jaeger-agents-head {
        font-size: 10px; font-weight: 700; letter-spacing: 0.04em;
        color: var(--muted, #888); padding: 4px 8px 6px; text-transform: uppercase;
      }
      #jaegerAgentsList { display: flex; flex-direction: column; gap: 2px; }
      #jaegerAgentsList button.jaeger-agent-row {
        display: flex; align-items: center; gap: 8px; width: 100%;
        border: 0; background: transparent; color: var(--text, inherit);
        padding: 6px 10px; border-radius: 8px; cursor: pointer; text-align: left;
        font: inherit; font-size: 12px; font-weight: 500;
      }
      #jaegerAgentsList button.jaeger-agent-row:hover { background: rgba(127,127,127,0.12); }
      #jaegerAgentsList button.jaeger-agent-row.active { background: rgba(96,165,250,0.16); }
      #jaegerAgentsList .jaeger-agent-dot {
        width: 8px; height: 8px; border-radius: 50%; flex: 0 0 auto;
      }
      #jaegerAgentsList .jaeger-agent-dot.native { background: #f59e0b; }
      #jaegerAgentsList .jaeger-agent-dot.third { background: #34d399; }
      #jaegerAgentsList .jaeger-agent-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      #jaegerAgentsList .jaeger-agent-active-mark {
        width: 6px; height: 6px; border-radius: 50%; background: var(--accent, #60a5fa);
      }
      #jaegerAgentsEmpty { font-size: 11px; color: var(--muted,#888); padding: 4px 10px 8px; }
    `;
    document.head.appendChild(style);
  };

  const escapeHtml = (s) =>
    String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");

  let _agentsBusy = false;

  const renderAgents = (catalog) => {
    const list = document.getElementById("jaegerAgentsList");
    const empty = document.getElementById("jaegerAgentsEmpty");
    if (!list) return;
    const agents = Array.isArray(catalog && catalog.agents) ? catalog.agents : [];
    const activeId = (catalog && catalog.active && catalog.active.id) || null;
    if (!agents.length) {
      list.innerHTML = "";
      if (empty) {
        empty.hidden = false;
        empty.textContent = "Gateway agents unavailable";
      }
      return;
    }
    if (empty) empty.hidden = true;
    list.innerHTML = agents
      .map((a) => {
        const id = a.id || "";
        const name = a.display_name || a.name || id;
        const kind = a.kind === "jaeger_native" ? "native" : "third";
        const isActive = !!a.active || id === activeId;
        return (
          `<button type="button" class="jaeger-agent-row${isActive ? " active" : ""}" data-agent-id="${escapeHtml(id)}" title="${escapeHtml(id)}">` +
          `<span class="jaeger-agent-dot ${kind}"></span>` +
          `<span class="jaeger-agent-name">${escapeHtml(name)}</span>` +
          (isActive ? `<span class="jaeger-agent-active-mark" aria-hidden="true"></span>` : "") +
          `</button>`
        );
      })
      .join("");

    // Titlebar chip: show active agent display name when present.
    const label = document.getElementById("titlebarProfileLabel");
    const active = agents.find((a) => a.id === activeId) || agents.find((a) => a.active);
    if (label && active) {
      const dn = active.display_name || active.name;
      if (dn) label.textContent = dn;
    }
  };

  const activateAgent = async (id) => {
    if (!id || _agentsBusy) return;
    _agentsBusy = true;
    try {
      const res = await fetch(`/api/agents/${encodeURIComponent(id)}/activate`, {
        method: "POST",
        headers: { Accept: "application/json" },
      });
      if (!res.ok) {
        console.warn("[jaeger] activate failed", res.status);
      }
      await loadAgentsCatalog();
      // Keep chat panel focused (Mac parity: switch agent → Chat).
      if (typeof switchPanel === "function") {
        try {
          switchPanel("chat", { fromRailClick: true });
        } catch (_) {}
      }
    } catch (err) {
      console.warn("[jaeger] activate error", err);
    } finally {
      _agentsBusy = false;
    }
  };

  const loadAgentsCatalog = async () => {
    try {
      const res = await fetch("/api/agents", { headers: { Accept: "application/json" } });
      if (!res.ok) {
        renderAgents({ agents: [] });
        return null;
      }
      const catalog = await res.json();
      renderAgents(catalog);
      return catalog;
    } catch (_) {
      renderAgents({ agents: [] });
      return null;
    }
  };

  const installAgentsSection = () => {
    ensureAgentsStyles();
    const sessionList = document.getElementById("sessionList");
    const panelChat = document.getElementById("panelChat");
    if (!panelChat || !sessionList) return;
    if (document.getElementById("jaegerAgentsSection")) {
      loadAgentsCatalog();
      return;
    }
    const section = document.createElement("div");
    section.id = "jaegerAgentsSection";
    section.innerHTML =
      `<div class="jaeger-agents-head">Agents</div>` +
      `<div id="jaegerAgentsList" role="list"></div>` +
      `<div id="jaegerAgentsEmpty" hidden></div>`;
    panelChat.insertBefore(section, sessionList);
    section.addEventListener("click", (ev) => {
      const btn = ev.target.closest("button.jaeger-agent-row");
      if (!btn) return;
      activateAgent(btn.getAttribute("data-agent-id"));
    });
    loadAgentsCatalog();
    // Refresh periodically so Mac/WebUI stay aligned when either face switches.
    setInterval(loadAgentsCatalog, 15000);
  };

  const boot = () => {
    installJaegerIcons();
    installJaegerSurfaceLabels();
    hideTodosSurfaces();
    hideHermesDashboardChrome();
    installAgentsSection();
  };

  boot();
  window.addEventListener("pageshow", boot);
  document.addEventListener("DOMContentLoaded", boot);
})();
