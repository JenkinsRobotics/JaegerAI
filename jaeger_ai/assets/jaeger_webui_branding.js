/* JaegerAI branding for the stock Hermes WebUI (:8790).
 *
 * SCOPE RULE — this overlay may only do what the stock WebUI cannot:
 * branding (icons, title) and hiding Hermes chrome Jaeger does not back.
 * It must NEVER reimplement a stock feature.
 *
 * It did once, and that is why this rule is written down. An AGENTS roster
 * here listed the four frameworks and switched between them — duplicating the
 * profile switcher the stock composer already has. Two controls for one job:
 * the sidebar said one framework, the composer said another, and the turn
 * label said a third, so you could not tell which agent you were talking to.
 *
 * Framework switching belongs to the stock profile chip. Jaeger reaches its
 * backends through the WebUI's own profile config and the loopback adapter —
 * that is the whole design, and it keeps upstream pulls of hermes-webui
 * mergeable. Every line added here is a future merge conflict, so add none
 * that stock could carry instead.
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
      // The composer placeholder is deliberately NOT touched. Stock derives it
      // from the ACTIVE PROFILE via assistantDisplayName() — the same function
      // that labels the profile chip — so it already reads "Message Hermes
      // Agent…" when Hermes is selected. Overwriting it with a fixed "Message
      // Jaeger…" made the chip and the placeholder name different agents, which
      // is the confusion this overlay is supposed to avoid causing.
      //
      // The window title below IS branding: the app is Jaeger whichever backend
      // a message goes to. Who you are talking to is the composer's job.
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

  const escapeHtml = (s) =>
    String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");



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
      });
    }
    _pendingApproval = payload;
    const body = document.getElementById("jaegerApprovalBody");
    const to = (payload.metadata && payload.metadata.target_display) || payload.to_agent_id || "specialist";
    body.textContent = `Hand off to ${to}?\n${payload.task || ""}`.trim();
    card.hidden = false;
  };

  const polishSessionLibrary = () => {
    try {
      const emptyNotes = document.querySelectorAll(".session-empty-note, #sessionList .empty, #sessionList .session-empty");
      emptyNotes.forEach((el) => {
        const t = (el.textContent || "").trim();
        if (!t) {
          el.textContent = "No conversations yet";
          return;
        }
        if (/no sessions/i.test(t) && !/project/i.test(t) && !/CLI/i.test(t) && !/unassigned/i.test(t)) {
          el.textContent = "No conversations yet";
        }
      });
    } catch (_) {}
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
        // Keep unfinished stages out of the active navigation until their
        // controls have real content and state contracts.
        // ["avatar", "Avatar"],
        // ["work", "Work"],
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



  // ── Transcript chrome: specialist/lead labels on assistant turns ──
  // Gateway turn.finish carries agent_id / role / display_name. Surfaces
  // chrome stamps the same fields onto .assistant-turn rows (no second store).
  let _turnIdentity = null; // { agent_id, role, display_name }

  const ensureTurnChromeStyles = () => {
    if (document.getElementById("jaeger-turn-chrome-style")) return;
    const style = document.createElement("style");
    style.id = "jaeger-turn-chrome-style";
    style.textContent = `
      .msg-role.assistant .jaeger-turn-role-hint {
        font-size: 10px; font-weight: 600; letter-spacing: 0.03em;
        text-transform: uppercase; color: var(--muted, #888);
        margin-left: 6px; opacity: 0.9;
      }
      .msg-role.assistant .msg-role-name[data-jaeger-labeled="1"] {
        font-weight: 600;
      }
    `;
    document.head.appendChild(style);
  };

  const normalizeTurnIdentity = (obj) => {
    if (!obj || typeof obj !== "object") return null;
    const agent_id = obj.agent_id || obj.id || null;
    const role = obj.role || (obj.metadata && obj.metadata.role) || "";
    const display_name = obj.display_name || obj.name || "";
    if (!display_name && !agent_id) return null;
    return {
      agent_id: agent_id ? String(agent_id) : "",
      role: role ? String(role) : "",
      display_name: display_name ? String(display_name) : String(agent_id || ""),
    };
  };

  const setTurnIdentity = (obj) => {
    const next = normalizeTurnIdentity(obj);
    if (!next) return;
    _turnIdentity = next;
    labelAssistantTurns({ stampLatest: true });
  };

  const identityFromDataset = (el) => {
    if (!el || !el.dataset) return null;
    const display_name = el.dataset.jaegerDisplayName || el.dataset.displayName || "";
    const role = el.dataset.jaegerRole || el.dataset.role || "";
    const agent_id = el.dataset.jaegerAgentId || el.dataset.agentId || "";
    if (!display_name && !agent_id) return null;
    return { agent_id, role, display_name: display_name || agent_id };
  };

  const applyIdentityToTurn = (turn, identity) => {
    if (!turn || !identity || !identity.display_name) return;
    ensureTurnChromeStyles();
    // MutationObserver calls this function. Writing the same value still
    // produces attribute/childList mutations, so every write must converge.
    const stamp = (key, value) => {
      if (turn.dataset[key] !== value) turn.dataset[key] = value;
    };
    stamp("jaegerAgentId", identity.agent_id || "");
    stamp("jaegerRole", identity.role || "");
    stamp("jaegerDisplayName", identity.display_name || "");
    const roleEl = turn.querySelector(".msg-role.assistant");
    if (!roleEl) return;
    const nameEl = roleEl.querySelector(".msg-role-name");
    const role = (identity.role || "").trim();
    const label =
      role && role !== "lead"
        ? `${identity.display_name} · ${role}`
        : identity.display_name;
    if (nameEl) {
      if (nameEl.textContent !== label) nameEl.textContent = label;
      if (nameEl.dataset.jaegerLabeled !== "1") nameEl.dataset.jaegerLabeled = "1";
      const title = [identity.display_name, identity.role, identity.agent_id]
        .filter(Boolean)
        .join(" · ");
      if (nameEl.title !== title) nameEl.title = title;
    }
    const icon = roleEl.querySelector(".role-icon.assistant");
    if (icon && identity.display_name) {
      const initial = identity.display_name.charAt(0).toUpperCase();
      if (icon.textContent !== initial) icon.textContent = initial;
    }
    // Mac parity: role rides in the name ("Name · role"); drop separate hint chip.
    const hint = roleEl.querySelector(".jaeger-turn-role-hint");
    if (hint) hint.remove();
  };

  const labelAssistantTurns = (opts) => {
    opts = opts || {};
    ensureTurnChromeStyles();
    const turns = document.querySelectorAll(
      ".assistant-turn, .msg-row[data-role='assistant'], #liveAssistantTurn"
    );
    turns.forEach((turn) => {
      const stamped = identityFromDataset(turn);
      if (stamped) {
        applyIdentityToTurn(turn, stamped);
        return;
      }
      // Payload fields sometimes land on child nodes or message wrappers.
      const nested = turn.querySelector("[data-agent-id],[data-display-name],[data-jaeger-display-name]");
      const fromNested = identityFromDataset(nested);
      if (fromNested) {
        applyIdentityToTurn(turn, fromNested);
        return;
      }
      const isLive =
        turn.id === "liveAssistantTurn" ||
        turn.dataset.latestAssistantResponse === "true" ||
        turn.classList.contains("streaming") ||
        !!turn.querySelector(".streaming, [data-streaming='1']");
      if ((opts.stampLatest || isLive) && _turnIdentity) {
        applyIdentityToTurn(turn, _turnIdentity);
      }
    });
  };

  const ingestTurnPayload = (payload) => {
    if (!payload || typeof payload !== "object") return;
    // Accept turn.finish envelope or flat identity fields.
    const body =
      payload.event === "turn.finish" || payload.type === "turn.finish"
        ? payload.data && typeof payload.data === "object"
          ? { ...payload, ...payload.data }
          : payload
        : payload;
    if (body.display_name || body.agent_id || body.role) {
      setTurnIdentity(body);
    }
  };

  const installTurnChrome = () => {
    ensureTurnChromeStyles();
    labelAssistantTurns({ stampLatest: true });
    if (document.documentElement.dataset.jaegerTurnChrome === "1") return;
    document.documentElement.dataset.jaegerTurnChrome = "1";

    const mo = new MutationObserver(() => {
      labelAssistantTurns({ stampLatest: true });
    });
    mo.observe(document.documentElement, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: [
        "data-role",
        "data-agent-id",
        "data-display-name",
        "data-jaeger-agent-id",
        "data-jaeger-display-name",
        "data-jaeger-role",
        "data-latest-assistant-response",
      ],
    });

    // hermesExt turn lifecycle (when registered) — re-stamp after complete.
    try {
      const handle =
        window.hermesExt && typeof window.hermesExt.register === "function"
          ? window.hermesExt.register("jaeger-dispatcher")
          : null;
      if (handle && handle.events && typeof handle.events.on === "function") {
        handle.events.on("turn:complete", () => labelAssistantTurns({ stampLatest: true }));
        handle.events.on("turn:start", () => labelAssistantTurns({ stampLatest: true }));
      }
    } catch (_) {}

    // Catch turn.finish / identity fields on SSE EventSource messages.
    try {
      const Proto = window.EventSource;
      if (Proto && !Proto.__jaegerTurnChromePatched) {
        const Orig = Proto;
        function PatchedEventSource(url, config) {
          const es = new Orig(url, config);
          const wrap = (type) => {
            es.addEventListener(type, (ev) => {
              try {
                const data = JSON.parse(ev.data);
                ingestTurnPayload(
                  type === "turn.finish" || type === "turn.delta"
                    ? { event: type, ...data }
                    : data
                );
              } catch (_) {}
            });
          };
          wrap("turn.finish");
          wrap("turn.delta");
          wrap("message");
          return es;
        }
        PatchedEventSource.prototype = Orig.prototype;
        PatchedEventSource.CONNECTING = Orig.CONNECTING;
        PatchedEventSource.OPEN = Orig.OPEN;
        PatchedEventSource.CLOSED = Orig.CLOSED;
        PatchedEventSource.__jaegerTurnChromePatched = true;
        window.EventSource = PatchedEventSource;
      }
    } catch (_) {}
  };

  const observeHermesTitleLeak = () => {
    const scrub = () => {
      try {
        // The app is Jaeger whichever backend a message goes to, so the window
        // title is a constant, not the active profile. Matching only /Hermes/
        // made it inconsistent: "Jaeger" on the Hermes profile but "OpenClaw"
        // or "Roundtable" on the others, because stock sets the title from the
        // active agent and the scrub only caught one of the four names.
        if (document.title !== "Jaeger") document.title = "Jaeger";
        const t = document.getElementById("appTitlebarTitle");
        if (t && !/^Jaeger/.test(t.textContent || "")) t.textContent = "Jaeger";
        // The composer placeholder is NOT scrubbed. "Hermes Agent" is a real
        // profile name, so a /Hermes/ rule here rewrote it to "Message Jaeger…"
        // every time that profile was selected — and being a MutationObserver,
        // it did so continuously, fighting stock for the field. The chip said
        // one agent and the placeholder said another.
        //
        // This observer exists to stop UPSTREAM PRODUCT branding leaking into
        // the window title. A profile name is content, not branding.
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
        // Settings /insights path residue (EN i18n + injected copy)
        document.querySelectorAll("label, .settings-desc, .setting-desc, p, span, div").forEach((el) => {
          if (!el || el.children.length > 2) return;
          const raw = el.textContent || "";
          if (/hermes\s*\/insights/i.test(raw) || /Hermes Insights/i.test(raw)) {
            el.textContent = raw
              .replace(/hermes\s*\/insights/gi, "Jaeger /insights")
              .replace(/Hermes Insights/gi, "Jaeger Insights");
          }
        });
      } catch (_) {}
    };
    scrub();
    const mo = new MutationObserver(scrub);
    mo.observe(document.documentElement, { subtree: true, childList: true, characterData: true, attributes: true });
  };

  let booted = false;
  const boot = () => {
    if (booted || !document.body) return;
    booted = true;
    installJaegerIcons();
    installJaegerSurfaceLabels();
    hideTodosSurfaces();
    hideHermesDashboardChrome();
    installStageNav();
    installTurnChrome();
    observeHermesTitleLeak();
    ensureApprovalStyles();
  };

  boot();
  window.addEventListener("pageshow", boot);
  document.addEventListener("DOMContentLoaded", boot);
})();
