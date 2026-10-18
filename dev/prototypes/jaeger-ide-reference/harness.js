(() => {
  const now = Date.now();
  const sessions = [
    { session_id: "demo-gateway", title: "Fix Gateway reconnect handling", created_at: now - 86400000, updated_at: now - 3600000, status: "completed", workspace: "JaegerAI", metadata: {} },
    { session_id: "demo-webview", title: "Review the IDE chat surface", created_at: now - 259200000, updated_at: now - 86400000, status: "completed", workspace: "JaegerAI", metadata: {} },
    { session_id: "demo-stream", title: "Understand streamed tool activity", created_at: now - 432000000, updated_at: now - 172800000, status: "completed", workspace: "JaegerAI", metadata: {} },
    { session_id: "demo-archive", title: "Old prototype cleanup", created_at: now - 604800000, updated_at: now - 604800000, status: "completed", workspace: "JaegerAI", metadata: { archived: true } },
  ];
  const initialMessages = [
    { role: "user", id: "u1", content: "Why does the IDE panel stay on Connecting after the Gateway is available?" },
    { role: "assistant", id: "a1", content: "The panel needs to treat the connection snapshot as a priority update. If it waits behind frame-batched stream events, a throttled webview can keep showing stale status." },
    { role: "user", id: "u2", content: "Show me what the client does while a turn is running." },
    { role: "assistant", id: "a2", content: "It streams the reply, groups adjacent tool calls into a collapsible work section, and lets you steer the active request. The queue belongs to the Gateway, so a follow-up survives a client reconnect." },
  ];
  const state = {
    connected: true, busy: false, status: "Connected", sessions, session: { ...sessions[0], messages: [...initialMessages] },
    openSessionIds: ["demo-gateway", "demo-webview"], staged: [], queue: [], activity: [], timeline: [],
    workTurns: [{ requestId: "demo-work-1", userIndex: 0, startedAt: now - 16000, finishedAt: now - 9000, status: "completed" }],
    models: { providers: [{ id: "ollama", reachable: true, models: [{ id: "qwen3-coder:30b", available: true }, { id: "deepseek-r1:32b", available: true }] }, { id: "openai", reachable: true, models: [{ id: "gpt-5", available: true }] }] },
    configuredModel: "", autonomy: { mode: "ask", options: ["ask", "auto"] }, tier: { current: "agent", options: ["chat", "agent", "jaeger"] },
    ideContext: { active_file: "jaeger_ai/interfaces/ide/media/view.js", selection: { start_line: 849, end_line: 868 }, open_files: ["view.js", "index.html", "view.css"], workspace: "JaegerAI" },
    diagnostics: 2, selectedWorkspace: "", approvals: [], backgroundTasks: [], changes: null, feedback: {},
  };
  state.timeline = [
    { key: "tool-1", kind: "tool", requestId: "demo-work-1", name: "search_files", detail: "Find connection state transitions", phase: "completed", ok: true },
    { key: "tool-2", kind: "tool", requestId: "demo-work-1", name: "file_read", detail: "Inspect the webview state queue", phase: "completed", ok: true },
  ];
  const saved = { modelChoice: "config", mode: "manual", ideContext: true, drafts: {}, chatSearch: "" };
  const deliver = data => window.dispatchEvent(new MessageEvent("message", { data }));
  const publish = extra => deliver({ ...state, ...extra });
  const addSession = title => {
    const id = `demo-${Math.random().toString(36).slice(2, 9)}`;
    const session = { session_id: id, title, created_at: Date.now(), updated_at: Date.now(), status: "completed", workspace: "JaegerAI", metadata: {}, messages: [] };
    sessions.unshift(session); state.session = session; state.openSessionIds = [...new Set([...state.openSessionIds, id])];
  };
  window.acquireVsCodeApi = () => ({
    getState: () => saved,
    setState: value => Object.assign(saved, value),
    postMessage: message => handle(message),
  });

  function handle(message) {
    if (message.type === "ready") return setTimeout(() => publish(), 0);
    if (message.type === "new") { addSession("New conversation"); state.session.messages = []; state.status = "Connected"; return publish(); }
    if (message.type === "home") { state.session = null; state.busy = false; state.activity = []; state.text = ""; return publish(); }
    if (message.type === "select") {
      const session = sessions.find(item => item.session_id === message.id);
      if (session) { state.session = { ...session, messages: message.id === "demo-gateway" ? [...initialMessages] : [{ role: "user", id: `${message.id}-u`, content: `Continue: ${session.title}` }, { role: "assistant", id: `${message.id}-a`, content: "This is sample conversation data rendered by Jaeger's actual IDE webview." }] }; }
      return publish();
    }
    if (message.type === "closeSession") { state.openSessionIds = state.openSessionIds.filter(id => id !== message.id); return publish(); }
    if (message.type === "send" && message.text) return send(message.text);
    if (message.type === "steer" && message.text) { state.text = `Steering noted: ${message.text}`; return publish(); }
    if (message.type === "cancel") { state.busy = false; state.status = "Cancelled"; state.text = ""; return publish(); }
    if (message.type === "setTier") { state.tier = { ...state.tier, current: message.tier }; return publish(); }
    if (message.type === "setAutonomy") { state.autonomy = { ...state.autonomy, mode: message.mode }; return publish(); }
    if (message.type === "selectWorkspace") { state.selectedWorkspace = state.selectedWorkspace ? "" : "/Users/demo/JaegerAI"; return publish(); }
    if (message.type === "mentionFile") return deliver({ mention: "@jaeger_ai/interfaces/ide/media/view.js" });
    if (message.type === "info") return deliver({ info: { title: message.what === "status" ? "Connection status" : "Prototype result", lines: ["Local preview only", "No Gateway or workspace action was performed."] } });
    if (["settings", "attach", "selectWorktree", "runTestSuite", "reviewChanges", "turnChanges", "copy"].includes(message.type)) {
      return deliver({ info: { title: "Local preview", lines: [`${message.type} is represented by the real extension UI.`, "This standalone preview has no VS Code host or Gateway behind it."] } });
    }
  }
  function send(text) {
    if (!state.session) addSession(text.trim().slice(0, 48));
    const session = state.session;
    const title = session.title === "New conversation" ? text.trim().slice(0, 48) : session.title;
    session.title = title || "New conversation";
    session.messages ||= [];
    const userIndex = session.messages.filter(item => item.role === "user").length;
    const requestId = `demo-work-${Date.now()}`;
    session.messages.push({ role: "user", id: `${requestId}-u`, content: text });
    sessions[0] = sessions.splice(sessions.indexOf(session), 1)[0];
    session.updated_at = Date.now();
    deliver({ accepted: true, submittedText: text });
    state.busy = true; state.status = "Working"; state.text = "Checking the selected workspace context…";
    state.workTurns = [...(state.workTurns || []), { requestId, userIndex, startedAt: Date.now(), finishedAt: null, status: "running" }];
    state.timeline = [...(state.timeline || []), { key: `${requestId}-tool`, kind: "tool", requestId, name: "file_read", detail: "Inspect selected context", phase: "running", ok: true }];
    publish();
    setTimeout(() => {
      session.messages.push({ role: "assistant", id: `${requestId}-a`, content: "This turn is simulated. The preview is running Jaeger's real view.js and presentation code, but no agent or Gateway is connected." });
      state.busy = false; state.status = "Connected"; state.text = "";
      state.workTurns = state.workTurns.map(work => work.requestId === requestId ? { ...work, finishedAt: Date.now(), status: "completed" } : work);
      state.timeline = state.timeline.map(row => row.requestId === requestId ? { ...row, phase: "completed" } : row);
      return publish();
    }, 900);
  }
})();
