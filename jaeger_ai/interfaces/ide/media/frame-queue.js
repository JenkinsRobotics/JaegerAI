'use strict';

/*
 * Adapted from Kilo Code v7.7.9:
 * packages/kilo-vscode/webview-ui/src/context/frame-queue.ts
 * commit d52877ea1c0a02284a4a87d2da0082d2f6dbefb7
 *
 * Copyright (c) 2026 Kilo Code
 * Copyright (c) 2025 opencode
 * SPDX-License-Identifier: MIT
 *
 * Modified for Jaeger: build-free browser/CommonJS export, injectable clock,
 * and full-state snapshot coalescing at the Gateway client boundary.
 */

(function expose(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.JaegerFrameQueue = api;
})(typeof window !== 'undefined' ? window : globalThis, () => {
  function browserClock() {
    return {
      requestFrame: typeof requestAnimationFrame === 'function'
        ? callback => requestAnimationFrame(callback) : undefined,
      cancelFrame: typeof cancelAnimationFrame === 'function'
        ? handle => cancelAnimationFrame(handle) : undefined,
      setTimer: (callback, delay) => setTimeout(callback, delay),
      clearTimer: handle => clearTimeout(handle),
      hidden: () => typeof document !== 'undefined' && document.visibilityState === 'hidden',
    };
  }

  function createFrameQueue(apply, isStream = () => true, suppliedClock) {
    const clock = { ...browserClock(), ...(suppliedClock || {}) };
    const queue = [];
    let frame;
    let timer;

    const stop = () => {
      if (frame !== undefined && clock.cancelFrame) clock.cancelFrame(frame);
      if (timer !== undefined) clock.clearTimer(timer);
      frame = undefined;
      timer = undefined;
    };
    const drain = () => {
      stop();
      if (queue.length) apply(queue.splice(0));
    };
    const schedule = () => {
      if (frame !== undefined || timer !== undefined) return;
      const hidden = Boolean(clock.hidden?.());
      if (clock.requestFrame && !hidden) frame = clock.requestFrame(drain);
      // Hidden webviews and throttled animation frames still make progress.
      timer = clock.setTimer(drain, hidden ? 0 : 100);
    };

    return {
      push(item) {
        if (!isStream(item)) {
          drain();
          apply([item]);
          return;
        }
        queue.push(item);
        schedule();
      },
      flush: drain,
      cancel() { stop(); queue.length = 0; },
      get size() { return queue.length; },
    };
  }

  return { createFrameQueue };
});
