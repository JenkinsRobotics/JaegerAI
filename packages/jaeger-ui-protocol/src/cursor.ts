/**
 * Monotonic Last-Event-ID cursor tracker preventing duplicate or out-of-order replay.
 */

export interface CursorAdvanceResult {
  accepted: boolean;
  gapDetected: boolean;
  expectedSeq: number;
  receivedSeq: number;
}

export class SeqCursor {
  private _lastSeq: number;

  constructor(initialSeq = 0) {
    this._lastSeq = Math.max(0, Math.floor(initialSeq));
  }

  get lastSeq(): number {
    return this._lastSeq;
  }

  get lastEventIdHeader(): string | undefined {
    return this._lastSeq > 0 ? String(this._lastSeq) : undefined;
  }

  advance(seq: number): CursorAdvanceResult {
    const received = Math.floor(seq);
    const expected = this._lastSeq + 1;
    if (!Number.isFinite(received) || received <= this._lastSeq) {
      return {
        accepted: false,
        gapDetected: false,
        expectedSeq: expected,
        receivedSeq: received,
      };
    }
    const gapDetected = this._lastSeq > 0 && received > expected;
    this._lastSeq = received;
    return {
      accepted: true,
      gapDetected,
      expectedSeq: expected,
      receivedSeq: received,
    };
  }

  reset(floorSeq = 0): void {
    this._lastSeq = Math.max(0, Math.floor(floorSeq));
  }
}
