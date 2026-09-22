const CANDIDATES = [
  window.ARES_FINANCE_API,
  "/api/extensions/ares-finance/sidecar",
  "http://127.0.0.1:3848",
].filter(Boolean);

let API_BASE = CANDIDATES[CANDIDATES.length - 1];
let apiReady = false;

async function probeApi() {
  for (const base of CANDIDATES) {
    try {
      const res = await fetch(`${base}/health`, { cache: "no-store" });
      if (res.ok) {
        API_BASE = base;
        apiReady = true;
        return true;
      }
    } catch (_err) {
      /* try next */
    }
  }
  apiReady = false;
  return false;
}

async function api(path, opts) {
  if (!apiReady) await probeApi();
  const res = await fetch(`${API_BASE}${path}`, opts);
  if (!res.ok) throw new Error(`${path} failed (${res.status})`);
  return res.json();
}

function money(n) {
  return Number(n || 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function applyProvenance(data) {
  const banner = document.getElementById("provenanceBanner");
  const prov = data && data.data_provenance;
  const isDemo = !prov ? true : !!prov.is_demo;
  banner.hidden = false;
  if (isDemo) {
    banner.className = "provenance-banner demo";
    banner.textContent = (prov && prov.note) || "DEMO DATA — seeded samples, not real accounts.";
  } else {
    banner.className = "provenance-banner live";
    banner.textContent = (prov && prov.note) || "Live Monarch data.";
  }
}

document.querySelectorAll(".nav-tab").forEach((tabBtn) => {
  tabBtn.addEventListener("click", () => {
    document.querySelectorAll(".nav-tab").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach((c) => c.classList.remove("active"));
    tabBtn.classList.add("active");
    const targetId = tabBtn.getAttribute("data-tab");
    document.getElementById(targetId).classList.add("active");
    if (targetId === "walletTab") loadWalletCards();
    if (targetId === "analyticsTab") loadAnalytics();
    if (targetId === "budgetsTab") loadBudgets();
    if (targetId === "billsTab") loadBills();
  });
});

async function fetchSummary() {
  try {
    const data = await api("/api/summary");
    applyProvenance(data);
    document.getElementById("netWorthDisplay").innerText = money(data.net_worth);
    const breakdown = data.breakdown || {};
    document.getElementById("accountsBreakdown").innerHTML = `
      <div class="breakdown-item">
        <div class="breakdown-label">Liquid Assets</div>
        <div class="breakdown-val" style="color: var(--accent-green)">$${money(breakdown.depository || 0)}</div>
      </div>
      <div class="breakdown-item">
        <div class="breakdown-label">Investments</div>
        <div class="breakdown-val" style="color: var(--accent-blue)">$${money(breakdown.investment || 0)}</div>
      </div>
      <div class="breakdown-item">
        <div class="breakdown-label">Credit / Loans</div>
        <div class="breakdown-val" style="color: var(--accent-gold)">$${money(Math.abs(breakdown.credit || 0) + Math.abs(breakdown.loan || 0))}</div>
      </div>
    `;
    setOnlineStatus(true);
  } catch (_err) {
    setOnlineStatus(false);
  }
}

async function fetchTransactions() {
  try {
    const data = await api("/api/transactions?limit=10");
    const tbody = document.getElementById("txTableBody");
    tbody.innerHTML = "";
    (data.transactions || []).forEach((tx) => {
      const tr = document.createElement("tr");
      const isPos = tx.amount > 0;
      tr.innerHTML = `
        <td>${tx.date}</td>
        <td><strong>${tx.merchant_name || ""}</strong></td>
        <td><span class="tx-cat">${tx.category || ""}</span></td>
        <td class="${isPos ? "amount-pos" : "amount-neg"}">${isPos ? "+$" : "-$"}${Math.abs(tx.amount).toFixed(2)}</td>
      `;
      tbody.appendChild(tr);
    });
    document.getElementById("txCountBadge").innerText = `${(data.transactions || []).length} Recorded`;
  } catch (err) {
    console.error("Failed to load transactions", err);
  }
}

async function loadBudgets() {
  const container = document.getElementById("budgetsContainer");
  try {
    const data = await api("/api/budgets");
    applyProvenance(data);
    const budgets = data.budgets || [];
    document.getElementById("budgetCountBadge").innerText = `${budgets.length} categories`;
    if (!budgets.length) {
      container.innerHTML = `<p class="section-desc">No budgets yet. Sync Monarch to pull monthly targets.</p>`;
      return;
    }
    container.innerHTML = "";
    budgets.forEach((b) => {
      const planned = Number(b.amount || 0);
      const spent = Number(b.spent || 0);
      const pct = planned > 0 ? Math.min(100, Math.round((spent / planned) * 100)) : 0;
      const over = spent > planned && planned > 0;
      const row = document.createElement("div");
      row.className = "bar-row";
      row.innerHTML = `
        <div class="bar-label-row">
          <span><strong>${b.category_name}</strong> <span class="tx-cat">${b.period || ""}</span></span>
          <span>$${money(spent)} / $${money(planned)}</span>
        </div>
        <div class="bar-track">
          <div class="bar-fill ${over ? "over" : ""}" style="width: ${pct}%"></div>
        </div>
        <div class="bar-label-row">
          <span class="text-muted">${over ? "Over by" : "Remaining"} $${money(Math.abs(b.remaining || planned - spent))}</span>
        </div>
      `;
      container.appendChild(row);
    });
  } catch (err) {
    container.innerHTML = `<p class="section-desc">Could not load budgets: ${err.message}</p>`;
  }
}

async function loadBills() {
  const tbody = document.getElementById("billsTableBody");
  try {
    const data = await api("/api/recurring-bills");
    applyProvenance(data);
    const bills = data.recurring_bills || [];
    const monthly = bills
      .filter((b) => (b.frequency || "monthly") === "monthly")
      .reduce((sum, b) => sum + Number(b.amount || 0), 0);
    document.getElementById("billsTotalBadge").innerText = `$${money(monthly)} / mo`;
    tbody.innerHTML = "";
    if (!bills.length) {
      tbody.innerHTML = `<tr><td colspan="5">No recurring bills in the local store. Sync Monarch to populate.</td></tr>`;
      return;
    }
    bills.forEach((bill) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><strong>${bill.merchant_name}</strong></td>
        <td><span class="tx-cat">${bill.category_name || ""}</span></td>
        <td>${bill.frequency || ""}</td>
        <td>${bill.next_date || "—"}</td>
        <td class="amount-neg">$${money(bill.amount)}</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="5">Could not load bills: ${err.message}</td></tr>`;
  }
}

async function loadHealth() {
  const list = document.getElementById("healthList");
  const badge = document.getElementById("healthBadge");
  try {
    const data = await api("/api/institutions/health");
    if (data.status !== "success") {
      badge.innerText = data.status || "unavailable";
      list.textContent = data.error || data.message || "Connect Monarch to audit institutions.";
      return;
    }
    const issues = data.issues_detected || 0;
    badge.innerText = issues ? `${issues} issue(s)` : `${data.total_institutions} healthy`;
    if (!issues) {
      list.textContent = `${data.total_institutions} linked institution(s), no reconnect required.`;
      return;
    }
    list.innerHTML = (data.issues || [])
      .map((c) => {
        const name = (c.institution && c.institution.name) || c.id || "Institution";
        return `<div class="health-issue">${name} — reconnect or MFA required</div>`;
      })
      .join("");
  } catch (_err) {
    badge.innerText = "offline";
    list.textContent = "Sidecar unreachable, or Monarch is not connected.";
  }
}

async function loadWalletCards() {
  try {
    const data = await api("/api/cards");
    const container = document.getElementById("cardsGridContainer");
    container.innerHTML = "";
    (data.cards || []).forEach((card) => {
      const div = document.createElement("div");
      div.className = "wallet-card-item";
      const tags = Object.entries(card.rewards || {})
        .map(([cat, mult]) => `<span class="mult-tag">${cat}: ${mult}x</span>`)
        .join("");
      div.innerHTML = `
        <div>
          <div class="wallet-card-title">${card.name}</div>
          <div class="wallet-card-issuer">${card.issuer}</div>
          <div class="wallet-multipliers-tags">${tags}</div>
        </div>
        <div style="font-size: 11px; color: var(--text-secondary); margin-top: 8px;">
          ${card.notes || "Standard card terms."}
        </div>
      `;
      container.appendChild(div);
    });
  } catch (err) {
    console.error("Failed to load cards", err);
  }
}

async function loadAnalytics() {
  try {
    const data = await api("/api/analytics/spending");
    const container = document.getElementById("analyticsBarsContainer");
    container.innerHTML = "";
    const rows = data.spending_by_category || [];
    const maxSpent = Math.max(...rows.map((c) => c.total_spent), 1);
    rows.forEach((cat) => {
      const pct = Math.round((cat.total_spent / maxSpent) * 100);
      const row = document.createElement("div");
      row.className = "bar-row";
      row.innerHTML = `
        <div class="bar-label-row">
          <span><strong>${cat.category}</strong> (${cat.count} tx)</span>
          <span>$${cat.total_spent.toFixed(2)}</span>
        </div>
        <div class="bar-track">
          <div class="bar-fill" style="width: ${pct}%"></div>
        </div>
      `;
      container.appendChild(row);
    });
  } catch (err) {
    console.error("Failed to load analytics", err);
  }
}

async function evaluateCard() {
  const merchant = document.getElementById("merchantInput").value.trim();
  if (!merchant) return;
  try {
    const data = await api("/api/recommend-card", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ merchant }),
    });
    if (data.recommended_card) {
      document.getElementById("recCardName").innerText = data.recommended_card.name;
      document.getElementById("recMultiplier").innerText =
        `${data.multiplier}x Multiplier (${String(data.detected_category || "").toUpperCase()})`;
      document.getElementById("recTip").innerText = data.tip;
    }
  } catch (err) {
    console.error("Optimization failed", err);
  }
}

function setOnlineStatus(online) {
  const badge = document.getElementById("sidecarStatus");
  if (online) {
    badge.innerHTML = `<span class="dot"></span> Sidecar Online`;
    badge.style.color = "var(--accent-green)";
  } else {
    badge.innerHTML = `<span class="dot" style="background: var(--danger)"></span> Offline`;
    badge.style.color = "var(--danger)";
  }
}

const authModal = document.getElementById("authModal");
document.getElementById("authModalBtn").addEventListener("click", () => authModal.classList.remove("hidden"));
document.getElementById("closeAuthModal").addEventListener("click", () => authModal.classList.add("hidden"));

document.getElementById("saveTokenBtn").addEventListener("click", async () => {
  const status = document.getElementById("authStatus");
  const token = document.getElementById("monarchTokenInput").value.trim();
  const email = document.getElementById("monarchEmailInput").value.trim();
  const password = document.getElementById("monarchPasswordInput").value;
  const mfa = document.getElementById("monarchMfaInput").value.trim();
  status.textContent = "Connecting…";
  try {
    let result;
    if (token) {
      result = await api("/api/auth/monarch-token", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
      });
    } else if (email && password) {
      result = await api("/api/auth/connect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password, mfa_secret: mfa || null }),
      });
    } else {
      status.textContent = "Provide a token, or email + password.";
      return;
    }
    status.textContent = result.message || result.status || "Done.";
    if (result.status === "authenticated") {
      authModal.classList.add("hidden");
    }
  } catch (err) {
    status.textContent = `Failed: ${err.message}`;
  }
});

const addCardModal = document.getElementById("addCardModal");
document.getElementById("addCardBtn").addEventListener("click", () => addCardModal.classList.remove("hidden"));
document.getElementById("closeAddCardModal").addEventListener("click", () => addCardModal.classList.add("hidden"));

document.getElementById("saveNewCardBtn").addEventListener("click", async () => {
  const name = document.getElementById("newCardName").value.trim();
  const issuer = document.getElementById("newCardIssuer").value.trim();
  let rewards = {};
  try {
    rewards = JSON.parse(document.getElementById("newCardRewards").value.trim() || '{"default": 1.0}');
  } catch (_e) {
    rewards = { default: 1.0 };
  }
  if (!name) return;
  const id = name.toLowerCase().replace(/[^a-z0-9]/g, "_");
  await api("/api/cards", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id, name, issuer, rewards }),
  });
  addCardModal.classList.add("hidden");
  loadWalletCards();
});

document.getElementById("optimizeBtn").addEventListener("click", evaluateCard);
document.getElementById("merchantInput").addEventListener("keypress", (e) => {
  if (e.key === "Enter") evaluateCard();
});

async function refreshAll() {
  await fetchSummary();
  await fetchTransactions();
  await loadHealth();
}

document.getElementById("syncBtn").addEventListener("click", async () => {
  const btn = document.getElementById("syncBtn");
  btn.innerText = "Syncing...";
  try {
    await api("/api/sync", { method: "POST" });
    await refreshAll();
    await loadBudgets();
    await loadBills();
  } finally {
    btn.innerHTML = `<span class="btn-icon">⚡</span> Sync Monarch`;
  }
});

document.getElementById("refreshBtn").addEventListener("click", async () => {
  const btn = document.getElementById("refreshBtn");
  btn.innerText = "Refreshing…";
  try {
    await api("/api/accounts/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    await refreshAll();
  } finally {
    btn.innerText = "↻ Refresh Banks";
  }
});

(async () => {
  await probeApi();
  await refreshAll();
})();
