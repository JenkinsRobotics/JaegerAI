'use strict';

const { answerIdeRequest } = require('./conversation');
const terminal = new Set(['completed', 'failed', 'cancelled', 'execution_unknown']);
const endEvents = new Set(['turn.finish', 'turn.failed', 'turn.cancelled', 'turn.unknown', 'turn.reconciled']);

// Admission happens once in the caller. Reconnect only observation, from the
// last event cursor; a closed stream never proves that execution completed.
async function observeNativeTurn({ gateway, sessionId, requestId, admitted, signal, stream, ideHandler, onApproval }) {
  let cursor = Math.max(0, Number(admitted.start_event_id || 1) - 1);
  let text = '', receipt = admitted, interrupted = false;
  if (terminal.has(receipt.status)) {
    try { receipt = await gateway.receipt(sessionId, requestId); }
    catch { return { receipt: null, text, interrupted: true }; }
  }
  for (let attempt = 0; attempt < 3 && !terminal.has(receipt.status); attempt++) {
    if (!signal.aborted) {
      try {
        for await (const event of gateway.events(sessionId, cursor, signal)) {
          if (signal.aborted) break;
          if (event.event_id && Number(event.event_id) <= cursor) continue;
          if (event.event_id) cursor = Math.max(cursor, Number(event.event_id));
          const data = event.data || {};
          if (event.session_id && event.session_id !== sessionId && event.session_id !== '*') continue;
          if (data.request_id !== requestId) continue;
          if (event.event === 'ide.request') await answerIdeRequest(gateway, ideHandler, sessionId, data);
          else if (event.event === 'turn.delta') {
            const delta = String(data.delta || '');
            if (delta) { stream.markdown(delta); text += delta; }
          } else if (event.event === 'approval.request') onApproval?.(data);
          else if (event.event === 'approval.resolved') stream.progress('Approval resolved · Jaeger is working...');
          else if (event.event === 'turn.progress') stream.progress(String(data.text || 'Jaeger is working...'));
          else if (event.event === 'tool.started') stream.progress(`Jaeger is using ${String(data.tool || 'a tool')}...`);
          if (endEvents.has(event.event)) break;
        }
      } catch (error) {
        // Even cancellation only stops our observation. Check the Gateway's
        // receipt before describing its execution outcome to the operator.
        interrupted = true;
      }
    }
    try { receipt = await gateway.receipt(sessionId, requestId); }
    catch { return { receipt: null, text, interrupted: true }; }
    if (terminal.has(receipt.status) || signal.aborted) break;
    interrupted = true;
    if (attempt < 2) stream.progress('Connection interrupted · Reconnecting to the accepted request...');
  }
  return { receipt, text, interrupted };
}

function renderNativeOutcome(stream, { receipt, text }, cancelled) {
  if (!receipt || !terminal.has(receipt.status)) {
    stream.markdown(`\n\n**${cancelled ? 'Cancellation requested' : 'Connection interrupted'}:** the Gateway has not confirmed the outcome. Open this conversation in Jaeger to check its status; do not resend the task automatically.`);
    return;
  }
  if (receipt.status !== 'completed') {
    stream.markdown(`\n\n**Jaeger request ${receipt.status}:** ${String(receipt.result?.error || 'No completed answer was returned.')}`);
    return;
  }
  const answer = String(receipt.result?.output || receipt.result?.text || '');
  if (!text) stream.markdown(answer || 'Jaeger completed the request.');
  else if (answer.startsWith(text)) {
    if (answer.length > text.length) stream.markdown(answer.slice(text.length));
  } else if (answer) {
    // Native chat is append-only. Label a server correction rather than silently
    // concatenating a different final answer onto the provisional stream.
    stream.markdown(`\n\n**Final confirmed answer**\n\n${answer}`);
  }
}

module.exports = { observeNativeTurn, renderNativeOutcome };
