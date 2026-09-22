const healthUrl = "http://127.0.0.1:3001/api/health";
const badge = document.getElementById("statusBadge");
const line = document.getElementById("healthLine");
const pre = document.getElementById("healthJson");

async function probe() {
  try {
    const res = await fetch(healthUrl, { cache: "no-store" });
    const body = await res.json();
    const ok = res.ok && body && body.status === "ok";
    badge.textContent = ok ? "SIDECAR OK" : "SIDECAR ERROR";
    badge.className = "status " + (ok ? "ok" : "bad");
    line.textContent = ok
      ? "Sidecar up at " + healthUrl
      : "Sidecar responded HTTP " + res.status;
    pre.textContent = JSON.stringify(body, null, 2);
  } catch (err) {
    badge.textContent = "SIDECAR DOWN";
    badge.className = "status bad";
    line.textContent = "Cannot reach " + healthUrl + " — run npm run dev:all";
    pre.textContent = String(err);
  }
}

probe();
setInterval(probe, 5000);
