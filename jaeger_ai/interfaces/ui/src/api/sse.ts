/**
 * Single source of truth for SSE decoding: backed by standalone @jaeger/ui-protocol.
 */
export {
  decodeSSE,
  parseSSEChunk,
  type SSEFrame,
  type SSEIssue,
  type SSEIssueObserver,
} from "@jaeger/ui-protocol";
