/**
 * 60fps requestAnimationFrame token delta batcher (VS Code / OpenCode streaming pattern).
 * Coalesces rapid LLM token chunks into one state flush per animation frame.
 */

export class StreamingDeltaBatcher<T = string> {
  private buffer: T[] = [];
  private rafId: number | ReturnType<typeof setTimeout> | null = null;
  private readonly onFlush: (items: T[]) => void;

  constructor(onFlush: (items: T[]) => void) {
    this.onFlush = onFlush;
  }

  push(item: T): void {
    this.buffer.push(item);
    if (this.rafId !== null) return;
    if (typeof requestAnimationFrame === "function") {
      this.rafId = requestAnimationFrame(() => this.flushNow());
    } else {
      this.rafId = setTimeout(() => this.flushNow(), 16);
    }
  }

  flushNow(): void {
    if (this.rafId !== null) {
      if (typeof cancelAnimationFrame === "function" && typeof this.rafId === "number") {
        cancelAnimationFrame(this.rafId);
      } else {
        clearTimeout(this.rafId as ReturnType<typeof setTimeout>);
      }
      this.rafId = null;
    }
    if (this.buffer.length === 0) return;
    const batch = this.buffer;
    this.buffer = [];
    this.onFlush(batch);
  }

  dispose(): void {
    this.buffer = [];
    if (this.rafId !== null) {
      if (typeof cancelAnimationFrame === "function" && typeof this.rafId === "number") {
        cancelAnimationFrame(this.rafId);
      } else {
        clearTimeout(this.rafId as ReturnType<typeof setTimeout>);
      }
      this.rafId = null;
    }
  }
}
