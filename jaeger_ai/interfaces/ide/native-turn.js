'use strict';

const { answerIdeRequest } = require('./conversation');
const terminal = new Set(['completed', 'failed', 'cancelled', 'execution_unknown']);
const endEvents = new Set(['turn.finish', 'turn.failed', 'turn.cancelled', 'turn.unknown', 'turn.reconciled']);

// Admission happens once in the caller. Reconnect only observation, from the
// last event cursor; a closed stream never proves that execution completed.
async function observeNativeTurn({ gateway, sessionId, requestId, admitted, signal, stream, ideHandler, onApproval }) {
  let cursor = Math.max(0, Number(admitted.start_event_id || 1) - 1);
  // ChatResponseStream cannot retract markdown, so a segment's text is held
  // until it looks like an answer (see looksLikeAnswer); `text` is what this
  // segment already pushed, `segment` is all of it, pushed or held.
  let text = '', segment = '', live = false, receipt = admitted, interrupted = false;
  // Sources, follow-ups and the search count arrive before turn.finish (the
  // Gateway stores them in the same transaction, with lower event ids).
  const sources = [], seenSources = new Set();
  let followUps = [], searchCount = null;
  const extras = () => ({ sources, followUps, searchCount });
  if (terminal.has(receipt.status)) {
    try { receipt = await gateway.receipt(sessionId, requestId); }
    catch { return { receipt: null, text, held: live ? '' : segment, interrupted: true, ...extras() }; }
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
            if (delta) {
              segment += delta;
              if (live) { stream.markdown(delta); text += delta; }
              else if (looksLikeAnswer(segment)) { live = true; stream.markdown(segment); text = segment; }
            }
          } else if (event.event === 'approval.request') onApproval?.(data);
          else if (event.event === 'approval.resolved') stream.progress('Approval resolved · Jaeger is working...');
          else if (event.event === 'turn.progress') stream.progress(String(data.text || 'Jaeger is working...'));
          else if (event.event === 'tool.started') {
            // Text before a tool call is commentary, not the answer. Held-back
            // commentary becomes a progress line; the next segment starts fresh.
            if (!live && segment.trim()) stream.progress(oneLine(segment));
            segment = ''; live = false; text = '';
            stream.progress(`Jaeger is using ${String(data.tool || 'a tool')}...`);
          }
          else if (event.event === 'sources') {
            for (const item of parseSources(data)) {
              const key = `${item.kind}:${item.location}`;
              if (seenSources.has(key) || sources.length >= 20) continue;
              seenSources.add(key); sources.push(item);
            }
          } else if (event.event === 'follow_ups') followUps = parseFollowUps(data);
          else if (event.event === 'search.count') searchCount = parseSearchCount(data) || searchCount;
          if (endEvents.has(event.event)) break;
        }
      } catch (error) {
        // Even cancellation only stops our observation. Check the Gateway's
        // receipt before describing its execution outcome to the operator.
        interrupted = true;
      }
    }
    try { receipt = await gateway.receipt(sessionId, requestId); }
    catch { return { receipt: null, text, held: live ? '' : segment, interrupted: true, ...extras() }; }
    if (terminal.has(receipt.status) || signal.aborted) break;
    interrupted = true;
    if (attempt < 2) stream.progress('Connection interrupted · Reconnecting to the accepted request...');
  }
  return { receipt, text, held: live ? '' : segment, interrupted, ...extras() };
}

// Short lead-in text ("I'll read the files first") is usually followed by a
// tool call. Stream a segment once it is long or structured enough to be the
// answer; until then hold it, so a preamble never lands in the answer.
const HOLD_CHARS = 200;
function looksLikeAnswer(segment) {
  return segment.length >= HOLD_CHARS || segment.includes('\n\n') || /(^|\n)\s*(#{1,6} |\||```|[-*] |\d+\. )/.test(segment);
}
const oneLine = value => { const line = value.replace(/\s+/g, ' ').trim(); return line.length > 120 ? `${line.slice(0, 117)}...` : line; };

// Same filters as the panel (media/timeline.js and conversation.js) so both
// surfaces show the same Sources and follow-ups.
const {parseSources,parseFollowUps,parseSearchCount} = require('./media/timeline');

// Native chat equivalent of the panel's Sources row. stream.reference takes a
// vscode.Uri; toUri is injected so this module stays free of the vscode API.
function renderNativeSources(stream, { sources, searchCount } = {}, toUri) {
  if (searchCount) {
    const { searches, failed } = searchCount;
    stream.markdown(`\n\n_Searched ${searches} time${searches === 1 ? '' : 's'}${failed ? ` (${failed} failed)` : ''}._`);
  }
  if (!sources?.length) return;
  if (typeof stream.reference === 'function' && typeof toUri === 'function') {
    for (const item of sources) {
      try { stream.reference(toUri(item)); } catch { /* an unparseable location is skipped */ }
    }
    return;
  }
  const label = item => (item.title || item.location).replace(/[\[\]]/g, '');
  stream.markdown(`\n\n**Sources**\n\n${sources.map(item => item.kind === 'url'
    ? `- [${label(item)}](${item.location})` : `- \`${item.location.replace(/`/g, '')}\``).join('\n')}`);
}

// Native follow-ups: VS Code calls provideFollowups with the result returned by
// the participant handler, so the list travels in result.metadata.
function nativeFollowups(result) {
  const list = Array.isArray(result?.metadata?.jaegerFollowUps) ? result.metadata.jaegerFollowUps : [];
  return list.filter(item => typeof item === 'string' && item).slice(0, 5).map(prompt => ({ prompt, label: prompt }));
}

function renderNativeOutcome(stream, { receipt, text, held = '' }, cancelled) {
  if (!receipt || !terminal.has(receipt.status)) {
    stream.markdown(`\n\n**${cancelled ? 'Cancellation requested' : 'Connection interrupted'}:** the Gateway has not confirmed the outcome. Open this conversation in Jaeger to check its status; do not resend the task automatically.`);
    return;
  }
  if (receipt.status !== 'completed') {
    stream.markdown(`\n\n**Jaeger request ${receipt.status}:** ${String(receipt.result?.error || 'No completed answer was returned.')}`);
    return;
  }
  // The confirmed answer replaces the stream and is shown exactly once.
  const answer = String(receipt.result?.output || receipt.result?.text || '');
  if (!text) stream.markdown(answer || held || 'Jaeger completed the request.'); // nothing pushed: write it whole
  else if (answer.startsWith(text)) { if (answer.length > text.length) stream.markdown(answer.slice(text.length)); } // identical or prefix
  else if (answer) stream.markdown(`\n\n---\n\n${answer}`); // pushed text was not the answer
}

module.exports = { looksLikeAnswer, observeNativeTurn, renderNativeOutcome, renderNativeSources, nativeFollowups, parseSources, parseFollowUps, parseSearchCount };
