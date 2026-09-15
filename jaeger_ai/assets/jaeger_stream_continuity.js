/* Give the active chat response first claim on the WebUI's HTTP/1.1 sockets.
 *
 * Hermes exposes turn lifecycle events to extensions. Jaeger's WebUI uses that
 * public seam to pause the two replaceable sidebar streams while a turn owns a
 * token stream. This matters for PWA/multi-tab clients: EventSource connections
 * share the browser's small per-origin HTTP/1.1 pool, and a queued chat stream
 * produces exactly the observed failure mode -- the POST succeeds and the
 * response is persisted, but it is invisible until a page reload.
 */
(() => {
  "use strict";

  const extension = window.hermesExt?.register?.("jaeger-stream-continuity");
  if (!extension?.events?.on) return;

  const activeTurns = new Set();
  let backgroundStreamsPaused = false;

  const turnKey = (event) =>
    `${String(event?.sessionId || "")}\u0000${String(event?.streamId || "")}`;

  const callIfPresent = (name) => {
    const fn = window[name];
    if (typeof fn !== "function") return;
    try {
      fn();
    } catch (error) {
      try {
        console.warn(`[jaeger] ${name} failed during stream handoff`, error);
      } catch (_) {}
    }
  };

  const pauseBackgroundStreams = () => {
    if (backgroundStreamsPaused) return;
    backgroundStreamsPaused = true;
    // Release both optional EventSource connections synchronously, before the
    // lifecycle dispatcher returns and Hermes constructs /api/chat/stream.
    callIfPresent("stopGatewaySSE");
    callIfPresent("_closeSessionEventsSSE");
  };

  const resumeBackgroundStreams = () => {
    if (!backgroundStreamsPaused || activeTurns.size) return;
    backgroundStreamsPaused = false;
    // Defer restoration until the terminal chat handler has closed its source.
    window.setTimeout(() => {
      if (activeTurns.size || document.hidden) return;
      callIfPresent("ensureSessionEventsSSE");
      callIfPresent("startGatewaySSE");
    }, 0);
  };

  extension.events.on("turn:start", (event) => {
    const key = turnKey(event);
    if (!key || key === "\u0000") return;
    activeTurns.add(key);
    pauseBackgroundStreams();
  });

  const finishTurn = (event) => {
    activeTurns.delete(turnKey(event));
    resumeBackgroundStreams();
  };
  extension.events.on("turn:complete", finishTurn);
  extension.events.on("turn:error", finishTurn);
  extension.events.on("turn:cancel", finishTurn);

  window.addEventListener("pagehide", () => {
    activeTurns.clear();
    backgroundStreamsPaused = false;
  });
})();
