'use strict';

/* Jaeger DOM reconciliation using the stable-key row pattern adapted from
 * Kilo Code v7.7.9 transcript-rows.ts (MIT). See THIRD_PARTY_NOTICES.md. */
(function expose(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.JaegerKeyedRenderer = api;
})(typeof window !== 'undefined' ? window : globalThis, () => {
  class KeyedRenderer {
    constructor(host, createRow, updateRow, { bottomThreshold = 90 } = {}) {
      this.host = host; this.createRow = createRow; this.updateRow = updateRow;
      this.bottomThreshold = bottomThreshold; this.reconciliations = 0;
    }
    reconcile(rows) {
      const oldTop = this.host.scrollTop;
      const follow = this.host.scrollHeight - oldTop - this.host.clientHeight <= this.bottomThreshold;
      const existing = new Map([...this.host.children].map(node => [node.dataset.timelineKey, node]));
      const retained = new Set();
      rows.forEach((row, index) => {
        let node = existing.get(row.key);
        if (!node) { node = this.createRow(row); node.dataset.timelineKey = row.key; }
        retained.add(node);
        const signature = JSON.stringify(row);
        if (node.dataset.timelineSignature !== signature) {
          this.updateRow(node, row); node.dataset.timelineSignature = signature;
        }
        const current = this.host.children[index];
        if (current !== node) this.host.insertBefore(node, current || null);
      });
      for (const node of [...this.host.children]) if (!retained.has(node)) this.host.removeChild(node);
      this.host.scrollTop = follow ? this.host.scrollHeight : oldTop;
      this.reconciliations += 1;
    }
  }
  return { KeyedRenderer };
});
