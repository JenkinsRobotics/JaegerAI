'use strict';
const { randomUUID } = require('node:crypto');
const { applyEvents, createTimelineState, isStreamEvent } = require('./media/timeline');
const terminal = new Set(['completed', 'failed', 'cancelled', 'execution_unknown']);
const taskTerminal = new Set(['completed', 'failed', 'cancelled', 'execution_unknown', 'blocked', 'quota', 'auth', 'unknown']);
const endEvents = new Set(['turn.finish', 'turn.failed', 'turn.cancelled', 'turn.unknown', 'turn.reconciled']);
const COMPLETED_TIMELINE_SESSION_LIMIT = 20;
const COMPLETED_TIMELINE_ROW_LIMIT = 100;
const COMPLETED_TIMELINE_TEXT_LIMIT = 16000;

function boundedText(value, limit = COMPLETED_TIMELINE_TEXT_LIMIT) {
  const text = String(value || '');
  return text.length > limit ? text.slice(-limit) : text;
}

function boundedTimelineRows(value) {
  if (!Array.isArray(value)) return [];
  return value.filter(row => row && ['tool', 'reasoning', 'progress', 'checkpoint'].includes(row.kind))
    .slice(-COMPLETED_TIMELINE_ROW_LIMIT)
    .map(row => ({
      key: boundedText(row.key, 256), kind: row.kind,
      requestId: boundedText(row.requestId, 128),
      ...(['reasoning', 'progress', 'checkpoint'].includes(row.kind) ? { text: boundedText(row.text) } : {
        name: boundedText(row.name, 256), detail: boundedText(row.detail),
        phase: boundedText(row.phase, 32), ok: row.ok,
      }),
      live: false,
    }));
}

function boundedCompletedTimelines(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  const bounded = {};
  for (const [sid, timeline] of Object.entries(value).slice(-COMPLETED_TIMELINE_SESSION_LIMIT)) {
    const rows = boundedTimelineRows(timeline?.rows);
    if (rows.length) bounded[sid] = { cursor: Math.max(0, Number(timeline?.cursor) || 0), rows };
  }
  return bounded;
}

class Conversation {
  constructor(gateway, publish, save, restored = {}) {
    this.gateway = gateway; this.publish = publish; this.save = save;
    this.pending = restored.pending || {};
    this.pendingTask = restored.pendingTask || null;
    this.openSessionIds = Array.isArray(restored.openSessionIds) ? [...new Set(restored.openSessionIds)] : [];
    this.completedTimelines = boundedCompletedTimelines(restored.completedTimelines);
    this.workBySession = Object.fromEntries(Object.entries(restored.workBySession || {}).slice(-20)
      .map(([sid, turns]) => [sid, Array.isArray(turns) ? turns.slice(-50) : []]));
    // `staged` are attachments already uploaded to the Gateway but not yet
    // attached to a sent turn — kept out of persisted state; an unsent
    // attachment does not survive a panel reload, matching the composer text.
    this.staged = [];
    this.modelsLoaded = false;
    this.workersLoaded = false;
    this.timelineState = createTimelineState();
    this.state = { session: null, sessions: [], text: '', reasoning: '', activity: [], timeline: [],
      approvals: [], models: null, modelsError: null, workers: [], workersError: null,
      activeTask: null, backgroundTasks: [], busy: false, queue: [], openSessionIds: this.openSessionIds,
      connected: false, status: 'Not connected', error: '', endpoint: gateway.url };
    this.observer = null; this.epoch = 0; this.stagedGen = 0; this.sending = false;
    this.disposed = false;
  }
  emit(updateKind = 'control') {
    if (this.disposed) return;
    this.publish({ ...this.state, openSessionIds: this.openSessionIds, staged: this.staged,
      workTurns: this.workBySession[this.state.session?.session_id] || [],
      updateKind,
      canCancel: Boolean(this.pending[this.state.session?.session_id] || this.pendingTask) });
    delete this.state.changes; // one-shot change event; authoritative refresh may follow
  }
  resetTimeline() {
    this.timelineState = createTimelineState();
    this.state.timeline = [];
    this.syncTimelineProjection();
  }
  syncTimelineProjection() {
    this.state.timeline = this.timelineState.rows;
    this.state.text = this.state.timeline.filter(row => row.kind === 'answer').map(row => row.text).join('');
    this.state.reasoning = this.state.timeline.filter(row => row.kind === 'reasoning').map(row => row.text).join('');
    this.state.activity = this.state.timeline
      .filter(row => row.kind === 'tool' || row.kind === 'control')
      .map(row => row.kind === 'tool'
        ? { name: row.name, ok: row.ok, detail: row.detail }
        : { detail: row.detail });
  }
  restoreCompletedTimeline(sid) {
    const saved = sid && this.completedTimelines[sid];
    const rows = boundedTimelineRows(saved?.rows);
    this.timelineState = {
      ...createTimelineState(),
      cursor: Math.max(0, Number(saved?.cursor) || 0),
      rows,
    };
    this.syncTimelineProjection();
  }
  settleCompletedTimeline(sid) {
    if (!sid) return;
    const rows = boundedTimelineRows(this.timelineState.rows);
    // Reinsert the current session so object insertion order is recency order.
    delete this.completedTimelines[sid];
    if (rows.length) {
      this.completedTimelines[sid] = { cursor: this.timelineState.cursor, rows };
    }
    for (const old of Object.keys(this.completedTimelines)
      .slice(0, -COMPLETED_TIMELINE_SESSION_LIMIT)) delete this.completedTimelines[old];
    this.timelineState = { ...this.timelineState, rows: this.timelineState.rows.filter(row => row.kind !== 'answer' && row.kind !== 'terminal') };
    this.syncTimelineProjection();
  }
  applyTimelineEvent(event) {
    this.timelineState = applyEvents(this.timelineState, [event]);
    this.syncTimelineProjection();
  }
  async persist() {
    if (this.disposed) return;
    await this.save({ selected: this.state.session?.session_id, pending: this.pending,
      pendingTask: this.pendingTask, completedTimelines: this.completedTimelines,
      workBySession: this.workBySession, openSessionIds: this.openSessionIds });
  }
  async refresh(selected = this.state.session?.session_id, explicit = false) {
    if (this.disposed) return;
    if (this.sending) throw new Error('Wait for request admission before reconnecting.');
    const epoch = ++this.epoch;
    clearTimeout(this.reconnectTimer);
    this.observer?.abort(); this.observer = null;
    this.state.connected = false; this.state.status = 'Connecting…'; this.state.error = ''; this.emit();
    try {
      const [version, listed] = await Promise.all([this.gateway.json('/version'), this.gateway.sessions()]);
      if (version.component !== 'jaeger-gateway' && version.service !== 'jaeger-gateway') {
        throw new Error('This endpoint is not a Jaeger Gateway.');
      }
      const session = selected ? await this.gateway.session(selected) : null;
      if (epoch !== this.epoch) return;
      this.state.sessions = listed.sessions || []; this.state.session = session;
      if (session && !this.openSessionIds.includes(session.session_id)) {
        this.openSessionIds = [...this.openSessionIds, session.session_id];
      }
      // A conversation switch drops this client's staged (unsent) attachments —
      // they were picked for the previous conversation, not this one.
      this.stagedGen++; this.staged = [];
      this.state.connected = true;
      this.restoreCompletedTimeline(session?.session_id);
      if (session && this.gateway.activity) await this.loadHistory(selected, epoch);
      if (session) await this.loadQueue(selected, epoch);
      if (epoch !== this.epoch) return;
      this.state.busy = Boolean(session && (this.pending[selected] || ['running', 'cancelling', 'busy'].includes(session.status)));
      this.state.status = this.state.busy ? 'Work in progress · reconnecting' : 'Connected';
      if (this.state.busy && !this.pending[selected]) this.state.status = 'Work in another client · Refresh for latest history';
      if (explicit) { this.modelsLoaded = false; this.workersLoaded = false; }
      await this.loadApprovals(epoch); await this.loadTasks(epoch); await this.loadModels(epoch); await this.loadWorkers(epoch); await this.persist(); this.emit();
      const pending = this.pending[selected];
      if (pending) this.observe(selected, pending.requestId, pending.startCursor || 0, epoch);
      else if (session && this.gateway.activity) this.watchSession(selected, epoch);
    } catch (error) {
      if (epoch !== this.epoch) return;
      this.state.connected = false; this.state.error = error.message;
      this.state.status = 'Unavailable · reconnecting'; this.emit();
      this.reconnectTimer = setTimeout(() => {
        if (!this.disposed && epoch === this.epoch) this.refresh(selected);
      }, 1000);
    }
  }
  async loadHistory(sid, epoch) {
    let cursor = 0, timeline = createTimelineState();
    const works = [];
    let userIndex = -1, active = null;
    do {
      const page = await this.gateway.activity(sid, cursor);
      if (epoch !== this.epoch) return;
      timeline = applyEvents(timeline, page.events);
      for (const event of page.events) {
        const rid = event.data?.request_id;
        if (event.event === 'turn.start') {
          userIndex++;
          active = { requestId: rid, startedAt: event.timestamp * 1000, finishedAt: null, status: 'running', userIndex };
          works.push(active);
        } else if (endEvents.has(event.event)) {
          const work = works.find(w => w.requestId === rid);
          if (work) { work.finishedAt = event.timestamp * 1000; work.status = event.data.status || event.event.slice(5); }
          if (active?.requestId === rid) active = null;
        }
      }
      cursor = page.next_cursor;
      if (!page.has_more) break;
      this.state.status = `Loading work history… ${timeline.rows.length} activities`; this.emit();
    } while (epoch === this.epoch);
    // Final text is rendered from the authoritative message, once. All other
    // streamed text (including checkpoints) retains its original position.
    const completed = new Set(works.filter(w => w.finishedAt).map(w => w.requestId));
    timeline.rows = timeline.rows.filter(row => !(row.kind === 'answer' && completed.has(row.requestId)));
    this.timelineState = timeline;
    this.workBySession[sid] = works;
    if (active) this.pending[sid] = { requestId: active.requestId, startCursor: cursor };
    this.syncTimelineProjection();
  }
  async watchSession(sid, epoch) {
    if (this.disposed || epoch !== this.epoch) return;
    const observer = new AbortController(); this.observer?.abort(); this.observer = observer;
    try {
      for await (const event of this.gateway.events(sid, this.timelineState.cursor, observer.signal)) {
        if (epoch !== this.epoch || observer.signal.aborted) return;
        if (event.event === 'turn.start' || endEvents.has(event.event) || ['message.created', 'task.created', 'task.updated', 'approval.request', 'approval.resolved'].includes(event.event)) {
          await this.refresh(sid); return;
        }
      }
      throw new Error('Session stream closed');
    } catch (error) {
      if (epoch !== this.epoch || observer.signal.aborted) return;
      this.state.status = 'Connection interrupted · reconnecting'; this.state.error = error.message; this.emit();
      this.reconnectTimer = setTimeout(() => { if (epoch === this.epoch) this.refresh(sid); }, 1000);
    }
  }
  async loadTasks(epoch = this.epoch) {
    if (typeof this.gateway.tasks !== 'function') return;
    const result = await this.gateway.tasks();
    if (epoch === this.epoch) this.state.backgroundTasks = (result.tasks || [])
      .filter(task => task.notification_policy?.recipient_session_id === this.state.session?.session_id
        && !['completed', 'cancelled'].includes(task.state));
  }
  async cancelBackgroundTask(id) {
    await this.gateway.cancelTask(id); await this.loadTasks(); this.emit();
  }
  async loadApprovals(epoch = this.epoch) {
    const result = await this.gateway.approvals();
    if (epoch === this.epoch) this.state.approvals = (result.approvals || [])
      .filter(a => a.session_id === this.state.session?.session_id);
  }
  async loadWorkers(epoch = this.epoch) {
    if (this.workersLoaded || typeof this.gateway.orchestrationWorkers !== 'function') return;
    try {
      const result = await this.gateway.orchestrationWorkers();
      if (epoch !== this.epoch) return;
      this.workersLoaded = true;
      this.state.workers = result.workers || [];
      this.state.workersError = null;
    } catch (error) {
      if (epoch !== this.epoch) return;
      this.state.workersError = error.message;
    }
  }

  // The Gateway's authoritative provider/model catalog (/v1/runtime/models) —
  // never a hardcoded list. Fetched once per connection, refreshed when the
  // operator explicitly reconnects (explicit=true), and best-effort: a failure
  // disables the picker with a real reason rather than blocking the conversation.
  async loadModels(epoch = this.epoch) {
    if (this.modelsLoaded || typeof this.gateway.models !== 'function') return;
    try {
      const result = await this.gateway.models();
      if (epoch !== this.epoch) return;
      this.modelsLoaded = true;
      this.state.models = result;
      this.state.modelsError = null;
    } catch (error) {
      if (epoch !== this.epoch) return;
      this.state.modelsError = error.message;
    }
  }
  async closeSession(sessionId) {
    sessionId = String(sessionId || '');
    if (!sessionId || !this.openSessionIds.includes(sessionId)) return;
    this.openSessionIds = this.openSessionIds.filter(id => id !== sessionId);
    if (this.state.session?.session_id === sessionId) {
      const next = this.openSessionIds.at(-1) || null;
      await this.refresh(next, true);
      return;
    }
    await this.persist();
    this.emit();
  }
  async newSession(title, workspace = '') {
    if (this.sending) throw new Error('Wait for request admission before switching.');
    const epoch = this.epoch;
    const session = await this.gateway.create({ session_id: randomUUID(), title: title || 'New conversation', workspace, source: 'ide' });
    if (this.disposed || epoch !== this.epoch) return;
    await this.refresh(session.session_id);
  }
  async send(text, model = '', provider = '', workspace = '', ide = null, allowedTools = null) {
    text = String(text).trim();
    if (!text || !this.state.connected || this.state.busy || this.sending) return;
    clearTimeout(this.reconnectTimer);
    this.observer?.abort();
    this.sending = true;
    const epoch = this.epoch;
    // A blank composer is a new chat, not a blocked state.  Codex lets the
    // first message establish the conversation; do the same while keeping
    // the Gateway as the sole session owner.
    if (!this.state.session) {
      try {
        const title = text.replace(/\s+/g, ' ').slice(0, 72) || 'New conversation';
        const created = await this.gateway.create({
          session_id: randomUUID(), title, workspace, source: 'ide',
        });
        if (this.disposed || epoch !== this.epoch) { this.sending = false; return; }
        this.state.session = created;
        this.state.sessions = [created, ...this.state.sessions.filter(item => item.session_id !== created.session_id)];
        this.openSessionIds = [...new Set([...this.openSessionIds, created.session_id])];
        this.restoreCompletedTimeline(created.session_id);
      } catch (error) {
        this.sending = false;
        this.state.error = error.message;
        this.state.status = 'Could not create chat';
        this.emit();
        return;
      }
    }
    const sid = this.state.session.session_id, requestId = randomUUID();
    // Explicit every turn, including the empty list: the Gateway attaches
    // whatever attachment_ids a turn sends, but reuses the SESSION's whole
    // uploaded set when a turn omits the field — an earlier turn's file would
    // silently ride along on every later one otherwise.
    const attachmentIds = this.staged.map(a => a.attachment_id);
    const work = { requestId, startedAt: Date.now(), finishedAt: null, status: 'running',
      userIndex: (this.state.session.messages || []).filter(m => m.role === 'user').length };
    this.workBySession[sid] = [...(this.workBySession[sid] || []), work];
    for (const old of Object.keys(this.workBySession).filter(key => key !== sid).slice(0, -19)) delete this.workBySession[old];
    this.state.busy = true; this.state.error = ''; this.state.status = 'Submitting…'; this.emit();
    this.pending[sid] = { requestId, startCursor: 0 };
    let admittedSuccessfully = false;
    try {
      await this.persist(); // Persist identity before admission; never automatically re-send text.
      const admitted = await this.gateway.send(sid, {
        text, request_id: requestId, attachment_ids: attachmentIds,
        ...(Array.isArray(allowedTools) ? { allowed_tools: allowedTools } : {}),
        ...(model ? { model, ...(provider ? { provider } : {}) } : {}),
        // The open project and what is open in it, so the agent works in the
        // operator's workspace and can resolve "this file" / "the selection".
        ...(workspace ? { workspace } : {}),
        ...(ide ? { options: { ide } } : {}),
      });
      admittedSuccessfully = true;
      this.pending[sid].startCursor = Math.max(0, Number(admitted.start_event_id || 1) - 1);
      await this.persist();
      if (epoch !== this.epoch) return;
      this.publish({ accepted: true, submittedText: text });
      this.stagedGen++; this.staged = [];
      this.state.session = await this.gateway.session(sid);
      this.state.status = 'Working'; this.emit();
      if (terminal.has(admitted.status)) await this.finish(sid, requestId, epoch);
      else this.observe(sid, requestId, this.pending[sid].startCursor, epoch);
    } catch (error) {
      // A definitive rejected request is not an ambiguous transport failure.
      if (!admittedSuccessfully && error.status >= 400 && error.status < 500) {
        work.finishedAt = Date.now(); work.status = 'failed';
        delete this.pending[sid]; await this.persist(); this.state.busy = false;
      }
      this.state.error = `${error.message}${this.pending[sid] ? ' Delivery is uncertain. Retry connection to check the same request; it will not be resent.' : ''}`;
      this.state.status = 'Request not confirmed'; this.emit();
    } finally { this.sending = false; }
  }
  async finish(sid, rid, epoch) {
    const receipt = await this.gateway.receipt(sid, rid);
    if (!terminal.has(receipt.status)) throw new Error('No durable terminal result yet.');
    const work = (this.workBySession[sid] || []).find(turn => turn.requestId === rid);
    if (work && !work.finishedAt) { work.finishedAt = Date.now(); work.status = receipt.status; }
    delete this.pending[sid]; await this.persist();
    if (epoch !== this.epoch) return;
    const session = await this.gateway.session(sid);
    if (epoch !== this.epoch) return;
    this.state.session = session;
    // History is authoritative for user/assistant text after a terminal
    // receipt. Keep only observed reasoning/tool rows: otherwise the final
    // assistant answer is rendered twice, while fast tool calls disappear.
    if (this.gateway.activity) await this.loadHistory(sid, epoch);
    if (epoch !== this.epoch) return;
    this.settleCompletedTimeline(sid);
    await this.persist();
    const stillBusy = Boolean(this.pending[sid] || ['running', 'cancelling', 'busy'].includes(session.status));
    this.state.status = stillBusy ? 'Working' : receipt.status;
    this.state.busy = stillBusy;
    this.state.error = !stillBusy && (receipt.status === 'failed' || receipt.status === 'execution_unknown')
      ? String(receipt.result?.error || receipt.status) : '';
    await this.loadApprovals(epoch); await this.loadTasks(epoch);
    await this.loadQueue(sid, epoch);
    this.emit();
    const active = this.pending[sid];
    if (active) this.observe(sid, active.requestId, active.startCursor || 0, epoch);
    else if (this.gateway.activity) this.watchSession(sid, epoch);
  }
  async observe(sid, rid, cursor, epoch) {
    const observer = new AbortController(); this.observer?.abort(); this.observer = observer;
    try {
      const receipt = await this.gateway.receipt(sid, rid);
      if (terminal.has(receipt.status)) { await this.finish(sid, rid, epoch); return; }
      for await (const event of this.gateway.events(sid, cursor, observer.signal)) {
        if (epoch !== this.epoch || observer.signal.aborted) return;
        if (event.event_id && event.event_id <= cursor) continue;
        if (event.event_id) cursor = event.event_id;
        const data = event.data || {};
        if (event.session_id && event.session_id !== sid && event.session_id !== '*') continue;
        // Child task notifications belong to the session, not the currently
        // streaming foreground request. Keep them visible during that turn.
        if (event.event.startsWith('task.')) { await this.loadTasks(epoch); this.emit(); }
        // The agent asking the editor to do something (open a file, list Problems).
        if (event.event === 'ide.request') { void this.answerIde(sid, data); continue; }
        if (event.event === 'queue.updated') {
          await this.loadQueue(sid, epoch); this.emit(); continue;
        }
        if (event.event === 'message.created') {
          const session = await this.gateway.session(sid);
          if (epoch !== this.epoch) return;
          this.state.session = session; this.emit();
        }
        if (data.request_id !== rid) continue;
        this.applyTimelineEvent(event);
        if (event.event === 'files.changed') this.state.changes = data;
        if (event.event === 'approval.request' || event.event === 'approval.resolved') await this.loadApprovals(epoch);
        this.state.status = 'Working'; this.emit(isStreamEvent(event) ? 'stream' : 'control');
        if (endEvents.has(event.event)) { await this.finish(sid, rid, epoch); return; }
      }
      // EOF is never success. The receipt is the authority, not the connection.
      await this.finish(sid, rid, epoch);
    } catch (error) {
      if (observer.signal.aborted || epoch !== this.epoch) return;
      this.state.status = 'Connection interrupted · Retry'; this.state.error = error.message;
      this.state.busy = true; this.emit();
      if (this.gateway.activity) this.reconnectTimer = setTimeout(() => { if (epoch === this.epoch) this.refresh(sid); }, 1000);
    } finally { observer.abort(); }
  }
  // ``ideHandler`` is supplied by the extension host (it owns the VS Code API).
  async answerIde(sid, request) {
    if (!this.ideHandler || !request?.ide_request_id) return;
    let body;
    try { body = { ok: true, result: await this.ideHandler(request.kind, request.args || {}) }; }
    catch (error) { body = { ok: false, error: String(error?.message || error) }; }
    try { await this.gateway.ideResult(sid, request.ide_request_id, body); }
    catch { /* another window answered first, or the request expired */ }
  }
  async cancel() {
    if (this.pendingTask) {
      const tid = this.pendingTask.taskId;
      await this.gateway.orchestrationCancel(tid);
      this.state.status = 'Cancellation requested'; this.emit();
      return;
    }
    const sid = this.state.session?.session_id, rid = this.pending[sid]?.requestId;
    if (!rid) throw new Error('This client has no request ID to cancel. Use the originating client.');
    await this.gateway.cancel(sid, rid);
    this.state.status = 'Cancellation requested · waiting for owner'; this.emit();
    if (!this.observer || this.observer.signal.aborted) await this.refresh(sid);
  }
  // Mid-turn steering. The Gateway owns live injection into the active
  // JaegerAgent. If it honestly reports that no agent is steerable, the IDE
  // does not invent a second client-owned queue; the operator uses Queue next.
  async steer(text) {
    text = String(text).trim();
    const sid = this.state.session?.session_id;
    const rid = this.pending[sid]?.requestId;
    if (!text || !this.state.connected || !this.state.busy || this.sending || !sid || !rid) return false;
    try {
      const result = await this.gateway.steer(sid, rid, text);
      this.state.status = 'Steering accepted · next model step';
      this.emit();
      return Boolean(result.steered);
    } catch (error) {
      if (error.status !== 409) throw error;
      this.state.status = 'No live agent to steer · use Queue next';
      this.emit();
      return false;
    }
  }
  async loadQueue(sid, epoch = this.epoch) {
    if (!sid || !this.gateway.queue) return;
    const result = await this.gateway.queue(sid);
    if (epoch !== this.epoch || this.disposed) return;
    this.state.queue = Array.isArray(result.items) ? result.items : [];
  }
  async queue(text, model = '', provider = '', workspace = '', ide = null, allowedTools = null) {
    text = String(text).trim();
    const sid = this.state.session?.session_id;
    if (!text || !this.state.connected || !sid) return false;
    const epoch = this.epoch;
    const requestId = randomUUID();
    const attachmentIds = this.staged.map(a => a.attachment_id);
    let response;
    this.state.status = 'Queuing…'; this.emit();
    try {
      response = await this.gateway.queueAdd(sid, {
        text, request_id: requestId, attachment_ids: attachmentIds,
        ...(Array.isArray(allowedTools) ? { allowed_tools: allowedTools } : {}),
        ...(model ? { model, ...(provider ? { provider } : {}) } : {}),
        ...(workspace ? { workspace } : {}),
        ...(ide ? { options: { ide } } : {}),
      });
    } catch (error) {
      this.state.error = error.message;
      this.state.status = 'Queue not accepted';
      this.emit();
      return false;
    }
    if (epoch !== this.epoch || this.disposed) return false;
    await this.loadQueue(sid, epoch);
    this.state.error = '';
    this.publish({ accepted: true, submittedText: text });
    this.stagedGen++; this.staged = [];
    if (response.status === 'running' && response.request_id) {
      const rid = response.request_id;
      const startCursor = Math.max(0, Number(response.start_event_id || 1) - 1);
      this.pending[sid] = { requestId: rid, startCursor };
      const work = { requestId: rid, startedAt: Date.now(), finishedAt: null, status: 'running',
        userIndex: (this.state.session?.messages || []).filter(m => m.role === 'user').length };
      this.workBySession[sid] = [...(this.workBySession[sid] || []), work];
      this.state.busy = true;
      this.state.session = await this.gateway.session(sid);
      this.state.status = 'Working';
      await this.persist();
      this.emit();
      this.observe(sid, rid, startCursor, epoch);
    } else {
      this.state.status = 'Queued · waiting for the current turn';
      await this.persist();
      this.emit();
    }
    return true;
  }
  async queueUpdate(id, patch = {}) {
    const sid = this.state.session?.session_id;
    if (!sid) throw new Error('Open a conversation first.');
    await this.gateway.queueUpdate(sid, id, patch);
    await this.loadQueue(sid); this.emit();
  }
  async queueDelete(id) {
    const sid = this.state.session?.session_id;
    if (!sid) throw new Error('Open a conversation first.');
    await this.gateway.queueDelete(sid, id);
    await this.loadQueue(sid); this.emit();
  }
  async queueReorder(order) {
    const sid = this.state.session?.session_id;
    if (!sid) throw new Error('Open a conversation first.');
    const result = await this.gateway.queueReorder(sid, order);
    this.state.queue = Array.isArray(result.items) ? result.items : [];
    this.emit();
  }
  async submitParentTask({ goal, worker, taskId, idempotencyKey, readOnly = true }) {
    goal = String(goal || '').trim();
    worker = String(worker || '').trim();
    if (!goal || !worker || !this.state.connected || this.state.busy || this.sending) return;
    this.sending = true;
    const tid = taskId || randomUUID();
    const idemKey = idempotencyKey || tid;
    const epoch = this.epoch;
    this.state.busy = true; this.state.error = ''; this.state.status = 'Submitting task…'; this.emit();
    this.pendingTask = { taskId: tid, goal, worker, idempotencyKey: idemKey };
    let admittedSuccessfully = false;
    try {
      await this.persist();
      const task = await this.gateway.orchestrationSubmit({
        task_id: tid, goal, worker, idempotency_key: idemKey, read_only: readOnly,
      });
      admittedSuccessfully = true;
      this.state.activeTask = task;
      await this.persist();
      if (epoch !== this.epoch) return;
      this.publish({ accepted: true, submittedText: goal });
      this.state.status = task.state || 'submitted'; this.emit();
      if (taskTerminal.has(task.state)) {
        await this.finishTask(tid, epoch);
      } else {
        await this.observeTask(tid, epoch);
      }
    } catch (error) {
      if (!admittedSuccessfully && error.status >= 400 && error.status < 500) {
        this.pendingTask = null; await this.persist(); this.state.busy = false;
      }
      this.state.error = `${error.message}${this.pendingTask ? ' Delivery is uncertain. Retry connection to check the same task.' : ''}`;
      this.state.status = 'Request not confirmed'; this.emit();
    } finally { this.sending = false; }
  }
  async observeTask(taskId, epoch, intervalMs = 100) {
    while (epoch === this.epoch) {
      try {
        const task = await this.gateway.orchestrationTask(taskId);
        if (epoch !== this.epoch) return;
        this.state.activeTask = task;
        this.state.status = task.state || 'running';
        this.emit();
        if (taskTerminal.has(task.state)) {
          await this.finishTask(taskId, epoch);
          return;
        }
      } catch (err) {
        if (epoch !== this.epoch) return;
        this.state.error = err.message;
        this.emit();
        break;
      }
      await new Promise(resolve => setTimeout(resolve, intervalMs));
    }
  }
  async finishTask(taskId, epoch) {
    const task = await this.gateway.orchestrationTask(taskId);
    if (!taskTerminal.has(task.state)) throw new Error('Task is not in terminal state.');
    this.pendingTask = null; await this.persist();
    if (epoch !== this.epoch) return;
    this.state.activeTask = task;
    this.state.busy = false;
    this.state.status = task.state;
    this.state.error = (task.state === 'failed' || task.state === 'blocked' || task.state === 'quota' || task.state === 'auth' || task.state === 'unknown')
      ? String(task.result?.reason || task.result?.output || task.state) : '';
    this.emit();
  }
  // Registers a file already inside the Jaeger instance workspace with the
  // Gateway and stages it for the NEXT sent turn. The Gateway's attachment
  // store only accepts paths under its own instance workspace directory
  // (jaeger_ai/core/gateway/server.py::handle_add_attachment) — a file
  // picked from elsewhere is rejected with a real error, not silently
  // dropped or faked as attached.
  async addAttachment(file) {
    if (!this.state.session) throw new Error('Create or select a conversation first.');
    const epoch = this.epoch;
    const stagedGen = this.stagedGen;
    const row = await this.gateway.addAttachment(this.state.session.session_id, {
      path: file.path, filename: file.name, mime: file.mime, size: file.size,
    });
    // Discard if a refresh/dispose (epoch increments) or send (stagedGen increments)
    // ran while the upload was in-flight. removeStagedAttachment uses filter and
    // does not increment stagedGen, so removing a different attachment correctly
    // keeps this upload's completion live.
    if (this.epoch !== epoch || this.stagedGen !== stagedGen) return;
    this.staged.push(row);
    this.emit();
  }
  removeStagedAttachment(attachmentId) {
    this.staged = this.staged.filter(a => a.attachment_id !== attachmentId);
    this.emit();
  }
  async approve(id, approved) {
    if (!this.state.approvals.some(a => a.approval_id === id || a.id === id)) throw new Error('Approval is no longer pending in this conversation.');
    await this.gateway.approve(id, approved); await this.loadApprovals(); this.emit();
  }
  dispose() { clearTimeout(this.reconnectTimer); this.disposed = true; ++this.epoch; this.observer?.abort(); }
}
module.exports = {
  Conversation, COMPLETED_TIMELINE_SESSION_LIMIT, COMPLETED_TIMELINE_ROW_LIMIT,
  COMPLETED_TIMELINE_TEXT_LIMIT,
};
