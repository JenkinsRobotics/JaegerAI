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
      #jaegerAgentsSection .jaeger-agents-subhead {
        font-size: 10px; font-weight: 700; letter-spacing: 0.04em;
        color: var(--muted, #888); padding: 8px 8px 4px; text-transform: uppercase;
      }
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
      #jaegerAgentsList .jaeger-agent-role {
        font-size: 10px; color: var(--muted,#888); text-transform: uppercase;
        letter-spacing: 0.03em; opacity: 0.85;
      }
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

  const agentRowHtml = (a, activeId, leadId) => {
    const id = a.id || "";
    const name = a.display_name || a.name || id;
    const role = a.role || (a.metadata && a.metadata.role) || "";
    const kind = role === "lead" || id === leadId ? "native" : "third";
    const isActive = !!a.active || id === activeId;
    const roleTag = role ? `<span class="jaeger-agent-role">${escapeHtml(role)}</span>` : "";
    return (
      `<button type="button" class="jaeger-agent-row${isActive ? " active" : ""}" data-agent-id="${escapeHtml(id)}" data-role="${escapeHtml(role)}" title="${escapeHtml(id)}">` +
      `<span class="jaeger-agent-dot ${kind}"></span>` +
      `<span class="jaeger-agent-name">${escapeHtml(name)}</span>` +
      roleTag +
      (isActive ? `<span class="jaeger-agent-active-mark" aria-hidden="true"></span>` : "") +
      `</button>`
    );
  };

  const renderAgents = (catalog) => {
    const list = document.getElementById("jaegerAgentsList");
    const empty = document.getElementById("jaegerAgentsEmpty");
    if (!list) return;
    const lead = catalog && catalog.lead ? catalog.lead : null;
    const specialists = Array.isArray(catalog && catalog.specialists) ? catalog.specialists : [];
    const agents = Array.isArray(catalog && catalog.agents) ? catalog.agents : [];
    const activeId = (catalog && catalog.active && catalog.active.id) || null;
    const leadId = (lead && lead.id) || null;
    const rows = [];
    if (lead) rows.push(lead);
    if (specialists.length) {
      for (const s of specialists) if (!leadId || s.id !== leadId) rows.push(s);
    } else {
      for (const a of agents) if (!leadId || a.id !== leadId) rows.push(a);
    }
    if (!rows.length) {
      list.innerHTML = "";
      if (empty) {
        empty.hidden = false;
        empty.textContent = "Gateway agents unavailable";
      }
      return;
    }
    if (empty) empty.hidden = true;
    let html = "";
    if (lead) {
      html += `<div class="jaeger-agents-subhead">Lead</div>` + agentRowHtml(lead, activeId, leadId);
    }
    const specs = rows.filter((a) => a !== lead);
    if (specs.length) {
      html += `<div class="jaeger-agents-subhead">Specialists</div>`;
      html += specs.map((a) => agentRowHtml(a, activeId, leadId)).join("");
    }
    list.innerHTML = html;

    const label = document.getElementById("titlebarProfileLabel");
    const active =
      (catalog && catalog.active) ||
      rows.find((a) => a.id === activeId) ||
      rows.find((a) => a.active) ||
      lead;
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


  const ensureApprovalStyles = () => {
    if (document.getElementById("jaeger-approval-style")) return;
    const style = document.createElement("style");
    style.id = "jaeger-approval-style";
    style.textContent = `
      #jaegerApprovalCard {
        position: fixed; right: 16px; bottom: 88px; z-index: 9999;
        max-width: 360px; background: var(--panel, #1c1c1e); color: var(--text, #fff);
        border: 1px solid rgba(127,127,127,0.35); border-radius: 12px; padding: 12px 14px;
        box-shadow: 0 8px 28px rgba(0,0,0,0.35); font-size: 13px;
      }
      #jaegerApprovalCard[hidden] { display: none !important; }
      #jaegerApprovalCard .jaeger-approval-title { font-weight: 700; margin-bottom: 6px; }
      #jaegerApprovalCard .jaeger-approval-body { color: var(--muted, #bbb); margin-bottom: 10px; white-space: pre-wrap; }
      #jaegerApprovalCard .jaeger-approval-actions { display: flex; gap: 8px; justify-content: flex-end; }
      #jaegerApprovalCard button {
        border: 0; border-radius: 8px; padding: 6px 12px; font: inherit; font-weight: 600; cursor: pointer;
      }
      #jaegerApprovalCard .allow { background: #34d399; color: #062; }
      #jaegerApprovalCard .deny { background: rgba(127,127,127,0.25); color: inherit; }
    `;
    document.head.appendChild(style);
  };

  let _pendingApproval = null;

  const hideApprovalCard = () => {
    const card = document.getElementById("jaegerApprovalCard");
    if (card) card.hidden = true;
    _pendingApproval = null;
  };

  const showApprovalCard = (payload) => {
    ensureApprovalStyles();
    let card = document.getElementById("jaegerApprovalCard");
    if (!card) {
      card = document.createElement("div");
      card.id = "jaegerApprovalCard";
      card.innerHTML =
        `<div class="jaeger-approval-title">Approval needed</div>` +
        `<div class="jaeger-approval-body" id="jaegerApprovalBody"></div>` +
        `<div class="jaeger-approval-actions">` +
        `<button type="button" class="deny" data-decision="deny">Deny</button>` +
        `<button type="button" class="allow" data-decision="allow">Allow</button>` +
        `</div>`;
      document.body.appendChild(card);
      card.addEventListener("click", async (ev) => {
        const btn = ev.target.closest("button[data-decision]");
        if (!btn || !_pendingApproval) return;
        const approved = btn.dataset.decision === "allow";
        const id = _pendingApproval.approval_id;
        try {
          await fetch(`/api/approvals/${encodeURIComponent(id)}`, {
            method: "POST",
            headers: { "Content-Type": "application/json", Accept: "application/json" },
            body: JSON.stringify({ approved, decision: approved ? "allow" : "deny" }),
          });
        } catch (err) {
          console.warn("[jaeger] approval resolve failed", err);
        }
        hideApprovalCard();
        loadAgentsCatalog();
      });
    }
    _pendingApproval = payload;
    const body = document.getElementById("jaegerApprovalBody");
    const to = (payload.metadata && payload.metadata.target_display) || payload.to_agent_id || "specialist";
    body.textContent = `Hand off to ${to}?\n${payload.task || ""}`.trim();
    card.hidden = false;
  };

  const requestSpecialistHandoff = async (id, displayName) => {
    const task = `Help with current chat as ${displayName || id}`;
    try {
      const res = await fetch(`/api/agents/${encodeURIComponent(id)}/handoff`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ task, reason: "surfaces-ui", require_approval: true }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        console.warn("[jaeger] handoff failed", res.status, data);
        return activateAgent(id);
      }
      if (data.status === "pending_approval" && data.approval_id) {
        showApprovalCard(data);
        return;
      }
      await activateAgent(id);
    } catch (err) {
      console.warn("[jaeger] handoff error", err);
      await activateAgent(id);
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
      const id = btn.getAttribute("data-agent-id");
      const role = btn.getAttribute("data-role") || "";
      const name = (btn.querySelector(".jaeger-agent-name") || {}).textContent || id;
      if (role === "specialist") {
        requestSpecialistHandoff(id, name);
      } else {
        activateAgent(id);
      }
    });
    loadAgentsCatalog();
    // Refresh periodically so Mac/WebUI stay aligned when either face switches.
    setInterval(loadAgentsCatalog, 15000);
  };


  const ensureStageNavStyles = () => {
    if (document.getElementById("jaeger-stage-nav-style")) return;
    const style = document.createElement("style");
    style.id = "jaeger-stage-nav-style";
    style.textContent = `
      #jaegerStageNav {
        display: flex; gap: 6px; align-items: center; justify-content: center;
        padding: 6px 10px; margin: 0 auto;
      }
      #jaegerStageNav button.jaeger-stage-pill {
        border: 1px solid rgba(127,127,127,0.25); background: transparent;
        color: var(--text, inherit); border-radius: 999px; padding: 5px 12px;
        font: inherit; font-size: 12px; font-weight: 600; cursor: pointer;
      }
      #jaegerStageNav button.jaeger-stage-pill.active {
        background: rgba(96,165,250,0.18); border-color: rgba(96,165,250,0.45);
      }
      #jaegerStageNav button.jaeger-stage-pill:hover { background: rgba(127,127,127,0.12); }
      .rail .rail-btn.nav-tab[data-panel="kanban"],
      .rail .rail-btn.nav-tab[data-panel="insights"],
      .rail .rail-btn.nav-tab[data-panel="logs"],
      .sidebar-nav .nav-tab[data-panel="kanban"],
      .sidebar-nav .nav-tab[data-panel="insights"],
      .sidebar-nav .nav-tab[data-panel="logs"] {
        opacity: 0.45;
      }
    `;
    document.head.appendChild(style);
  };

  let _stage = "chat";

  const setStage = (stage) => {
    _stage = stage;
    document.querySelectorAll("#jaegerStageNav button.jaeger-stage-pill").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.stage === stage);
    });
    if (typeof switchPanel === "function") {
      try { switchPanel("chat", { fromRailClick: true }); } catch (_) {}
    }
    const titlebar = document.getElementById("appTitlebarTitle");
    if (titlebar) {
      titlebar.textContent = stage === "chat" ? "Jaeger" : `Jaeger · ${stage[0].toUpperCase()}${stage.slice(1)}`;
    }
    const notice = document.getElementById("jaegerStageNotice");
    if (notice) {
      if (stage === "chat") {
        notice.hidden = true;
        notice.textContent = "";
      } else {
        notice.hidden = false;
        notice.textContent =
          stage === "avatar"
            ? "Avatar stage (Mac parity) — voice/orb UI comes next; chat composer stays active."
            : "Work stage (Mac parity) — projects/tasks surface comes next; chat composer stays active.";
      }
    }
  };

  const installStageNav = () => {
    ensureStageNavStyles();
    const titlebar = document.querySelector(".app-titlebar, #appTitlebar, header.app-header, #titlebar");
    const host =
      document.getElementById("appTitlebarCenter") ||
      document.querySelector(".titlebar-center") ||
      document.getElementById("appTitlebarTitle")?.parentElement ||
      titlebar;
    if (!host) return;
    if (!document.getElementById("jaegerStageNav")) {
      const nav = document.createElement("div");
      nav.id = "jaegerStageNav";
      nav.setAttribute("role", "tablist");
      nav.setAttribute("aria-label", "Stage");
      nav.innerHTML = [
        ["chat", "Chat"],
        ["avatar", "Avatar"],
        ["work", "Work"],
      ]
        .map(
          ([id, label]) =>
            `<button type="button" class="jaeger-stage-pill${id === "chat" ? " active" : ""}" data-stage="${id}" role="tab">${label}</button>`
        )
        .join("");
      const title = document.getElementById("appTitlebarTitle");
      if (title && title.parentElement) {
        title.insertAdjacentElement("afterend", nav);
      } else {
        host.appendChild(nav);
      }
      nav.addEventListener("click", (ev) => {
        const btn = ev.target.closest("button.jaeger-stage-pill");
        if (!btn) return;
        setStage(btn.dataset.stage);
      });
    }
    if (!document.getElementById("jaegerStageNotice")) {
      const main = document.querySelector("main") || document.getElementById("chat") || document.body;
      const notice = document.createElement("div");
      notice.id = "jaegerStageNotice";
      notice.hidden = true;
      notice.style.cssText =
        "font-size:12px;color:var(--muted,#888);padding:6px 14px;text-align:center;";
      const composer = document.getElementById("composerWrap") || document.getElementById("composerBox");
      if (composer && composer.parentElement) {
        composer.parentElement.insertBefore(notice, composer);
      } else {
        main.appendChild(notice);
      }
    }
  };


  const observeHermesTitleLeak = () => {
    const scrub = () => {
      try {
        if (/Hermes/i.test(document.title)) document.title = "Jaeger";
        const t = document.getElementById("appTitlebarTitle");
        if (t && /Hermes/i.test(t.textContent || "")) t.textContent = "Jaeger";
        const msg = document.getElementById("msg");
        if (msg && /Hermes/i.test(msg.getAttribute("placeholder") || "")) {
          msg.setAttribute("placeholder", "Message Jaeger…");
        }
        const health = document.getElementById("agentHealthTitle");
        if (health && /Hermes/i.test(health.textContent || "")) {
          health.textContent = "Jaeger agent is not responding";
        }
        const offline = document.getElementById("offlineAutorefresh");
        if (offline && /Hermes/i.test(offline.textContent || "")) {
          offline.textContent = "I will refresh this page automatically when Jaeger is reachable again.";
        }
        const onboarding = document.getElementById("onboardingTitle");
        if (onboarding && /Hermes/i.test(onboarding.textContent || "")) {
          onboarding.textContent = "Welcome to Jaeger";
        }
        document.querySelectorAll('[data-tooltip*="Hermes"], [aria-label*="Hermes"]').forEach((el) => {
          if (el.dataset.tooltip) el.dataset.tooltip = el.dataset.tooltip.replace(/Hermes\s*/gi, "").trim() || "Dashboard";
          if (el.getAttribute("aria-label")) {
            el.setAttribute(
              "aria-label",
              (el.getAttribute("aria-label") || "").replace(/Hermes\s*/gi, "").trim() || "Dashboard"
            );
          }
        });
      } catch (_) {}
    };
    scrub();
    const mo = new MutationObserver(scrub);
    mo.observe(document.documentElement, { subtree: true, childList: true, characterData: true, attributes: true });
  };

  const boot = () => {
    installJaegerIcons();
    installJaegerSurfaceLabels();
    hideTodosSurfaces();
    hideHermesDashboardChrome();
    installAgentsSection();
    installStageNav();
    observeHermesTitleLeak();
    ensureApprovalStyles();
  };

  boot();
  window.addEventListener("pageshow", boot);
  document.addEventListener("DOMContentLoaded", boot);
})();
