import { useActivityRecorder } from "./ActivityHistory";
import { notifyRunEvent, useSetting } from "./userPreferences";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { ApprovalPart, ChatMessage, MessagePart, SessionSummary } from "@jaeger/ui-protocol";
import { HttpSseTransport, SessionStore } from "@jaeger/ui-sdk";
import {
  ApprovalCard,
  CommandPalette,
  ContextXrayBar,
  ScrollFollowMachine,
  StreamingMarkdown,
  StudioTimeline,
  ThinkingDisclosure,
  ToolCallCard,
  type CommandItem,
  type StudioClip,
} from "@jaeger/ui-kit";
import { AvatarStage, type VisemeFrame } from "@jaeger/ui-avatar";
import { OfficeWorkspace } from "@jaeger/ui-office";
import "./unifiedShell.css";
import { AwakeningWizard } from "./AwakeningWizard";
import { ConversationTimeline, type ConversationTopic } from "./ConversationTimeline";
import { DroidVoice } from "./DroidVoice";
import { MindAutonomyPanel } from "./MindAutonomyPanel";
import { ReturnBriefingBanner } from "./ReturnBriefingBanner";
import { SettingsWorkspace } from "./SettingsWorkspace";
import { ResearchPage } from "./ResearchPage";
import { ToolsPage } from "./ToolsPage";
import { characterLibrary, type LibraryCharacter } from "./characters";

interface GatewayRuntimeSnapshot {
  model?: string;
  tools_count?: number;
  uptime_s?: number;
  all_green?: boolean;
  workspace?: string;
  state_dir?: string;
}

interface ResourceSnapshot {
  host_total_gb?: number;
  host_available_gb?: number;
  memory_cap_gb?: number;
  active_owner_runs?: number;
  idle_life_enabled?: boolean;
  idle_life_allowed_now?: boolean;
  idle_life_status?: string;
  estop_active?: boolean;
  preemption_count?: number;
  active_heavy_model?: { model_id: string; tier: string; estimated_gb: number } | null;
}

interface CognitionSnapshot {
  mode?: string;
  emotion?: string;
  focus?: string;
  tick_count?: number;
  uptime_s?: number;
  last_action?: string;
}

interface AvatarRecord {
  avatar?: {
    mode?: "3d_vrm" | "2d_character" | "rive";
    display_name?: string;
    asset_sha?: string | null;
  };
  asset?: { uri?: string; format?: string; name?: string } | null;
  live?: { emotion?: string; intensity?: number; state?: string; amplitude?: number };
}

interface SkillRow {
  name: string;
  path: string;
  security_verdict?: string;
}

interface McpServerRow {
  name: string;
  transport: string;
  connected: boolean;
  tools_count: number;
  error?: string;
}

interface WorkflowRow {
  run_id: string;
  name: string;
  status: string;
  total_steps: number;
  next_ready: string[];
  steps?: Array<{ id: string; name: string; record?: { status: string } }>;
}

interface LearningRow {
  entry_id: string;
  scope: string;
  subject: string;
  content: string;
  importance: number;
  recall_count: number;
}

interface GoalRow {
  goal_id: string;
  domain: string;
  title: string;
  status: string;
  priority: number;
  checkpoint?: Record<string, unknown>;
}

interface FactRow {
  subject: string;
  key: string;
  value: string;
}

const EMOTION_OPTIONS = ["warm", "focused", "happy", "curious", "calm", "concerned", "surprised"];

const workspaceNavigation = [
  { id: "chat", label: "Chat", path: "/", aliases: ["/chat"] },
  { id: "tools", label: "Tools", path: "/tools", aliases: ["/agents"] },
  { id: "characters", label: "Characters", path: "/characters", aliases: ["/agents/characters"] },
  { id: "office", label: "Office", path: "/office", aliases: ["/agents/team"] },
  { id: "tasks", label: "Tasks", path: "/tasks", aliases: ["/work", "/work/tasks"] },
  { id: "youtube", label: "YouTube", path: "/youtube", aliases: ["/work/youtube"] },
  { id: "studio", label: "Media Studio", path: "/studio", aliases: ["/work/studio"] },
  { id: "media", label: "Media & Outputs", path: "/library" },
  { id: "research", label: "Research", path: "/research" },
  { id: "memory", label: "Memory", path: "/memory", aliases: ["/agents/knowledge"] },
  { id: "skills", label: "Skills", path: "/skills" },
  { id: "goals", label: "Goals", path: "/goals" },
  { id: "integrations", label: "Integrations", path: "/integrations", aliases: ["/settings/integrations"] },
  { id: "models", label: "Models", path: "/models", aliases: ["/settings/models"] },
  { id: "droid", label: "Droid", path: "/droid", aliases: ["/machine", "/settings/machine"] },
  { id: "settings", label: "Settings", path: "/settings" },
] as const satisfies readonly { id: string; label: string; path: string; aliases?: readonly string[] }[];

type WorkspaceView = typeof workspaceNavigation[number]["id"];

function readWorkspaceView(): WorkspaceView {
  if (typeof window === "undefined") return "chat";
  const path = window.location.pathname.replace(/\/+$/, "") || "/";
  if (path === "/library" && new URLSearchParams(window.location.search).get("section") === "knowledge") return "memory";
  return workspaceNavigation.find((item) => item.path === path
    || ("aliases" in item && item.aliases.some((alias) => path === alias)))?.id ?? "chat";
}

function characterLabel(character: LibraryCharacter) {
  return character.character_id === "truth-gate" ? `${character.name} (Gate)` : character.name;
}

function readPreference(key: string): string | null {
  try { return window.localStorage.getItem(key); } catch { return null; }
}

function savePreference(key: string, value: string) {
  try { window.localStorage.setItem(key, value); } catch { /* Storage can be disabled. */ }
}

function isCompactViewport(): boolean {
  return typeof window !== "undefined" && window.innerWidth < 860;
}

interface HistoryPage {
  messages: Array<{
    id: number; session_id?: string; role: "user" | "assistant" | "system"; content: string; created_at: number;
    metadata?: { request_id?: string; presentation?: MessagePart[] };
  }>;
  has_older: boolean;
  after_seq: number;
}

function transcriptMessages(sessionId: string, page: HistoryPage): ChatMessage[] {
  return page.messages.map((row) => {
    const requestId = row.metadata?.request_id;
    const prefix = row.role === "user" ? "opt" : "asst";
    return {
      id: requestId ? `${prefix}_${requestId}` : `hist_${row.id}`,
      session_id: row.session_id ?? sessionId, role: row.role, content: row.content,
      parts: row.role === "assistant" && row.metadata?.presentation?.length
        ? row.metadata.presentation
        : row.content ? [{ type: "text", text: row.content }] : [],
      created_at: row.created_at, request_id: requestId, record_id: row.id,
    };
  });
}

export interface JaegerAppProps {
  baseUrl?: string;
}

export function JaegerApp({ baseUrl = "" }: JaegerAppProps) {
  const [dest, setView] = useState<WorkspaceView>(readWorkspaceView);
  useActivityRecorder(dest);
  const [leftSidebarOpen, setLeftSidebarOpen] = useState(
    () => (isCompactViewport() ? false : (readPreference("jaeger.shell.leftSidebar") ?? "open") !== "closed"),
  );
  const [leftSidebarTab, setLeftSidebarTab] = useState<"workspace" | "checkpoints">(
    () => (readPreference("jaeger.chat.timeline.open") === "open" ? "checkpoints" : "workspace"),
  );
  const [visibleTopicId, setVisibleTopicId] = useState<number>();
  const [highlightedTopicId, setHighlightedTopicId] = useState<number>();
  const setDest = (view: WorkspaceView) => {
    const path = workspaceNavigation.find((item) => item.id === view)!.path;
    if (readWorkspaceView() !== view) window.history.pushState(null, "", path);
    setView(view);
    if (isCompactViewport()) setLeftSidebarOpen(false);
  };

  useEffect(() => {
    const onPopState = () => setView(readWorkspaceView());
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);
  const [mode,setMode] = useSetting("mode");
  const [systemDark,setSystemDark] = useState(() =>
    typeof window.matchMedia === "function" ? window.matchMedia("(prefers-color-scheme: dark)").matches : true,
  );
  const theme = mode === "System" ? (systemDark ? "dark" : "light") : mode.toLowerCase();
  const [background] = useSetting("background"), [foreground] = useSetting("foreground");
  const [accent] = useSetting("accent"), [font] = useSetting("font");
  const [sendShortcut] = useSetting("sendShortcut"), [contextUsage] = useSetting("contextUsage");
  const [voiceEnabled] = useSetting("voiceEnabled"), [keepAwake] = useSetting("keepAwake");
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const update = () => setSystemDark(media.matches);
    media.addEventListener("change",update);
    return () => media.removeEventListener("change",update);
  }, []);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [rightSidebarOpen, setRightSidebarOpen] = useState(
    () => (isCompactViewport() ? false : (readPreference("jaeger.shell.rightSidebar") ?? readPreference("jaeger.chat.avatar") ?? "closed") === "open"),
  );
  const [rightSidebarTab, setRightSidebarTab] = useState<"inspector" | "avatar" | "mind">("inspector");
  const [rightSearch, setRightSearch] = useState("");
  const [sideQuestionOpen, setSideQuestionOpen] = useState(false);
  const [sideQuestionDraft, setSideQuestionDraft] = useState("");

  const [activeSessionId, setActiveSessionId] = useState("");
  const [historyState, setHistoryState] = useState<"loading" | "ready" | "reconnecting">("loading");
  const [historyError, setHistoryError] = useState("");
  const [olderCursor, setOlderCursor] = useState<number>();
  const [loadingOlder, setLoadingOlder] = useState(false);
  const olderRef = useRef<{ top: number; height: number } | null>(null);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const timelineTarget = useRef<number | undefined>(undefined);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  const olderLoadingRef = useRef(false);
  const sendingRef = useRef(false);

  useEffect(() => {
    if (!isCompactViewport()) savePreference("jaeger.shell.leftSidebar", leftSidebarOpen ? "open" : "closed");
  }, [leftSidebarOpen]);
  useEffect(() => savePreference("jaeger.chat.timeline.open", leftSidebarTab === "checkpoints" ? "open" : "closed"), [leftSidebarTab]);
  useEffect(() => {
    if (!isCompactViewport()) savePreference("jaeger.shell.rightSidebar", rightSidebarOpen ? "open" : "closed");
  }, [rightSidebarOpen]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [prompt, setPrompt] = useState("");
  const [liveReasoning, setLiveReasoning] = useState(() => readPreference("jaeger.chat.liveReasoning") === "on");
  const [liveTools, setLiveTools] = useState(() => readPreference("jaeger.chat.liveTools") === "on");
  useEffect(() => savePreference("jaeger.chat.liveReasoning", liveReasoning ? "on" : "off"), [liveReasoning]);
  useEffect(() => savePreference("jaeger.chat.liveTools", liveTools ? "on" : "off"), [liveTools]);
  const [runStatus, setRunStatus] = useState<string>("idle");
  const [scheduleApprovals, setScheduleApprovals] = useState<{ sessionId: string; items: ApprovalPart[] }>();
  const [approvalRefresh, setApprovalRefresh] = useState(0);
  const [approvalError, setApprovalError] = useState("");
  const [decidingApproval, setDecidingApproval] = useState<string>();

  const [health, setHealth] = useState<GatewayRuntimeSnapshot>({});
  const [resources, setResources] = useState<ResourceSnapshot>({});
  const [cognition, setCognition] = useState<CognitionSnapshot>({});
  const [avatarRec, setAvatarRec] = useState<AvatarRecord>({});
  const [visemes, setVisemes] = useState<VisemeFrame[]>([]);

  const [skills, setSkills] = useState<SkillRow[]>([]);
  const [mcpServers, setMcpServers] = useState<McpServerRow[]>([]);
  const [workflows, setWorkflows] = useState<WorkflowRow[]>([]);
  const [episodes, setEpisodes] = useState<Array<{ episode_id: string; title: string; stage: string; assigned_role: string; owner_approved: boolean; timeline_clips: StudioClip[] }>>([]);
  const [newEpTitle, setNewEpTitle] = useState("");
  const [dryRunResult, setDryRunResult] = useState<string>("");
  const [dryRunBusy, setDryRunBusy] = useState(false);

  const [learning, setLearning] = useState<LearningRow[]>([]);
  const [learningQuery, setLearningQuery] = useState("");
  const [goals, setGoals] = useState<GoalRow[]>([]);
  const [newGoalTitle, setNewGoalTitle] = useState("");
  const [newGoalDomain, setNewGoalDomain] = useState<"youtube" | "business" | "minecraft">("youtube");
  const [facts, setFacts] = useState<FactRow[]>([]);
  const [factKey, setFactKey] = useState("");
  const [factVal, setFactVal] = useState("");

  const [models, setModels] = useState<Array<{ id: string }>>([]);
  const [activeModel, setActiveModel] = useState("");
  const [modelRouting, setModelRouting] = useState<{ primary?: string; background?: string; vision?: string; fallback?: string }>({});
  const [routingSavedMsg, setRoutingSavedMsg] = useState("");
  const [awakeningOpen, setAwakeningOpen] = useState(false);
  const [onboardingDroidAvailable, setOnboardingDroidAvailable] = useState(false);
  const [avatarUploadMsg, setAvatarUploadMsg] = useState("");
  const [identity, setIdentity] = useState<{ ai_name?: string; owner_name?: string; mission?: string; active_character_id?: string | null; characters?: Record<string, LibraryCharacter> }>({});
  const [identityLoaded, setIdentityLoaded] = useState(false);
  const [characterPending, setCharacterPending] = useState(false);
  const [characterError, setCharacterError] = useState("");
  const [idAiName, setIdAiName] = useState("");
  const [idOwnerName, setIdOwnerName] = useState("");
  const [idSavedMsg, setIdSavedMsg] = useState("");
  const [droidDevices, setDroidDevices] = useState<{ gimbal_camera?: { name: string } | null; cameras?: Array<{ name: string }>; microphones?: Array<{ name: string }>; speakers?: Array<{ name: string }> }>({});
  const [droidPose, setDroidPose] = useState<{ pan_deg?: number; tilt_deg?: number; zoom?: number; tracking?: boolean }>({});
  const [droidSleeping, setDroidSleeping] = useState(false);
  const [droidVoiceEnrolled, setDroidVoiceEnrolled] = useState<boolean | null>(null);
  const [droidAutoPark, setDroidAutoPark] = useState<{ enabled: boolean; idle_park_s: number }>({ enabled: true, idle_park_s: 600 });
  const [droidCameraState, setDroidCameraState] = useState("ready");
  const [droidStatusMsg, setDroidStatusMsg] = useState("");
  const [droidBusy, setDroidBusy] = useState(false);
  const [droidPreview, setDroidPreview] = useState(false);
  const droidEpochRef = useRef(0);
  const [mcpNewName, setMcpNewName] = useState("");
  const [mcpNewUrl, setMcpNewUrl] = useState("");
  const [mediaArchive, setMediaArchive] = useState<Array<{ asset_id: string; kind: string; scene_description: string; source_path: string; is_reconstructed: boolean }>>([]);

  const transportRef = useRef<HttpSseTransport | null>(null);
  const storeRef = useRef<SessionStore | null>(null);
  const scrollMachineRef = useRef(new ScrollFollowMachine());
  const [showJump, setShowJump] = useState(false);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    const style = document.documentElement.style;
    style.setProperty("--jg-bg",background);
    style.setProperty("--jg-text-primary",foreground);
    style.setProperty("--jg-accent",({White:"white",Blue:"royalblue",Green:"seagreen"} as Record<string,string>)[accent] ?? "");
    style.setProperty("--jg-font-sans",font === "System" ? "" : font.toLowerCase());
  }, [theme,background,foreground,accent,font]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey)) return;
      const key = e.key.toLowerCase();
      if (key === "k") {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      } else if (key === "b") {
        e.preventDefault();
        setLeftSidebarOpen((v) => !v);
      } else if (key === ".") {
        e.preventDefault();
        setRightSidebarOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (!transportRef.current) {
    transportRef.current = new HttpSseTransport({ baseUrl });
  }

  const fetchJson = async (url: string): Promise<Record<string, any>> => {
    try {
      const r = await fetch(url);
      if (!r.ok) return {};
      return (await r.json()) as Record<string, any>;
    } catch {
      return {};
    }
  };

  const refreshSystem = async () => {
    const [rHealth, rRes, rCog, rAva] = await Promise.all([
      fetchJson(`${baseUrl}/health`),
      fetchJson(`${baseUrl}/v1/system/resources`),
      fetchJson(`${baseUrl}/v1/cognition/state`),
      fetchJson(`${baseUrl}/v1/avatars/jaeger`),
    ]);
    setHealth(rHealth);
    if (rRes.resources) setResources(rRes.resources);
    if (rCog.cognition) setCognition(rCog.cognition);
    if (rAva.avatar) setAvatarRec(rAva as AvatarRecord);
  };

  useEffect(() => {
    const controller = new AbortController();
    let timer: number | undefined;
    async function openChat() {
      try {
        const response = await fetch(`${baseUrl}/v1/chat/session`, { method: "POST", signal: controller.signal });
        if (!response.ok) throw new Error("Conversation unavailable");
        const data = (await response.json()) as { session: SessionSummary };
        if (!controller.signal.aborted) setActiveSessionId(data.session.session_id);
      } catch {
        if (!controller.signal.aborted) {
          setHistoryState("reconnecting");
          timer = window.setTimeout(() => void openChat(), 1500);
        }
      }
    }
    if (!activeSessionId) void openChat();
    return () => {
      controller.abort();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [baseUrl, activeSessionId]);

  useEffect(() => {
    void refreshSystem();
    const id = window.setInterval(() => void refreshSystem(), 12000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    if (!activeSessionId || !transportRef.current) return;
    const transport = transportRef.current;
    const store = new SessionStore(activeSessionId, transport);
    storeRef.current = store;
    scrollMachineRef.current = new ScrollFollowMachine();
    setShowJump(false);
    setMessages([]);
    setRunStatus("idle");
    setHistoryState("loading");
    setHistoryError("");
    setOlderCursor(undefined);
    setLoadingOlder(false);
    olderLoadingRef.current = false;
    olderRef.current = null;
    const unsub = store.subscribe((snapshot) => {
      setMessages(snapshot.messages);
      setRunStatus(snapshot.status);
      if (snapshot.lastError) setHistoryError(snapshot.lastError);
    });
    const controller = new AbortController();
    const { signal } = controller;
    let timer: number | undefined;
    const url = `${baseUrl}/v1/sessions/${encodeURIComponent(activeSessionId)}/messages?page=latest`;
    let initial = true;
    let savedId: number | undefined;
    let syncing = false;
    async function syncOtherSessions() {
      if (savedId === undefined || syncing) return;
      syncing = true;
      try {
        const response = await fetch(`${url}&after_id=${savedId}`, { signal });
        if (!response.ok || signal.aborted) return;
        const page: HistoryPage = await response.json();
        if (signal.aborted || !page.messages.length) return;
        savedId = Math.max(savedId, page.messages[page.messages.length - 1].id);
        store.mergeExternalHistory(transcriptMessages(activeSessionId, page).filter((message) =>
          message.session_id !== activeSessionId));
      } catch {
        // The live connection owns reconnect state.
      } finally {
        syncing = false;
      }
    }
    const syncInterval = window.setInterval(() => void syncOtherSessions(), 4000);
    async function connect() {
      try {
        const response = await fetch(url, { signal });
        if (!response.ok) {
          if (response.status === 404) {
            setActiveSessionId("");
            return;
          }
          throw new Error(`History request failed (${response.status}).`);
        }
        const page: HistoryPage = await response.json();
        if (signal.aborted) return;
        store.reconcileHistory(transcriptMessages(activeSessionId, page), page.after_seq);
        savedId = Math.max(savedId ?? 0, page.messages.at(-1)?.id ?? 0);
        if (initial) setOlderCursor(page.has_older ? page.messages[0]?.id : undefined);
        initial = false;
        setHistoryState("ready");
        setHistoryError("");
        await transport.subscribe(activeSessionId, page.after_seq, (event) => {
          const fresh = event.seq > store.getSnapshot().lastSeq;
          store.applyEvent(event);
          if (fresh) notifyRunEvent(event.event, activeSessionId + ":" + event.seq);
        }, signal);
      } catch {
        if (signal.aborted) return;
      }
      if (!signal.aborted) {
        setHistoryState("reconnecting");
        timer = window.setTimeout(() => void connect(), 1500);
      }
    }
    void connect();
    return () => {
      controller.abort();
      window.clearInterval(syncInterval);
      if (timer !== undefined) window.clearTimeout(timer);
      unsub();
      store.dispose();
      if (storeRef.current === store) storeRef.current = null;
    };
  }, [activeSessionId, baseUrl]);

  useLayoutEffect(() => {
    if ((dest !== "chat" && dest !== "droid") || !viewportRef.current) return;
    const viewport = viewportRef.current;
    if (timelineTarget.current !== undefined) {
      const target = viewport.querySelector<HTMLElement>(`[data-history-id="${timelineTarget.current}"]`);
      if (target) {
        const top = target.getBoundingClientRect().top - viewport.getBoundingClientRect().top + viewport.scrollTop;
        viewport.scrollTop = Math.max(0, top - 16);
        target.focus({ preventScroll: true });
        timelineTarget.current = undefined;
        olderRef.current = null;
        return;
      }
    }
    if (olderRef.current) {
      const { height, top } = olderRef.current;
      viewport.scrollTop = top + viewport.scrollHeight - height;
      olderRef.current = null;
    } else if (scrollMachineRef.current.shouldAutoScroll) {
      viewport.scrollTop = viewport.scrollHeight;
    }
  }, [messages, dest, highlightedTopicId, liveReasoning, liveTools, runStatus]);

  function trackVisibleTopic(viewport: HTMLDivElement) {
    let current: number | undefined;
    const cutoff = viewport.getBoundingClientRect().top + Math.min(130, viewport.clientHeight / 3);
    for (const message of viewport.querySelectorAll<HTMLElement>('article[data-role="user"][data-history-id]')) {
      const id = Number(message.dataset.historyId);
      if (current === undefined || message.getBoundingClientRect().top <= cutoff) current = id;
      else break;
    }
    setVisibleTopicId(current);
  }

  function jumpToLatest() {
    setHighlightedTopicId(undefined);
    timelineTarget.current = undefined;
    scrollMachineRef.current.transition({ type: "JUMP_REQUESTED" });
    const viewport = viewportRef.current;
    if (viewport) viewport.scrollTop = viewport.scrollHeight;
    setShowJump(false);
  }

  async function loadOlder(targetId?: number) {
    const store = storeRef.current;
    if (olderCursor === undefined || olderLoadingRef.current || !store) {
      if (targetId !== undefined && olderCursor === undefined) setHistoryError("This topic is no longer in the conversation log.");
      return;
    }
    olderLoadingRef.current = true;
    setLoadingOlder(true);
    setHistoryError("");
    try {
      let cursor: number | undefined = olderCursor;
      const pages: ChatMessage[][] = [];
      let found = false;
      do {
        const response = await fetch(`${baseUrl}/v1/sessions/${encodeURIComponent(activeSessionId)}/messages?page=latest&before_id=${cursor}`);
        if (!response.ok) throw new Error("Could not load earlier messages.");
        const page: HistoryPage = await response.json();
        if (storeRef.current !== store) return;
        pages.unshift(transcriptMessages(activeSessionId, page));
        found = page.messages.some((message) => message.id === targetId);
        cursor = page.has_older ? page.messages[0]?.id : undefined;
      } while (targetId !== undefined && !found && cursor !== undefined && cursor > targetId);

      const viewport = viewportRef.current;
      if (targetId !== undefined && found) {
        timelineTarget.current = targetId;
        setHighlightedTopicId(targetId);
      } else if (viewport) {
        olderRef.current = { top: viewport.scrollTop, height: viewport.scrollHeight };
      }
      scrollMachineRef.current.transition({ type: "USER_SCROLL_UP" });
      setShowJump(true);
      store.prependHistory(pages.flat());
      setOlderCursor(cursor);
      if (targetId !== undefined && !found) setHistoryError("This topic is no longer in the conversation log.");
    } catch {
      if (storeRef.current === store) setHistoryError("Could not load earlier messages. Try again.");
    } finally {
      if (storeRef.current === store) {
        olderLoadingRef.current = false;
        setLoadingOlder(false);
      }
    }
  }

  function jumpToTopic(id: number) {
    const viewport = viewportRef.current;
    const target = viewport?.querySelector<HTMLElement>(`[data-history-id="${id}"]`);
    if (!target || !viewport) {
      void loadOlder(id);
      return;
    }
    scrollMachineRef.current.transition({ type: "USER_SCROLL_UP" });
    setShowJump(true);
    setHighlightedTopicId(id);
    viewport.scrollTop += target.getBoundingClientRect().top - viewport.getBoundingClientRect().top - 16;
    target.focus({ preventScroll: true });
  }

  function resumeTopic(topic: ConversationTopic) {
    const excerpt = topic.excerpt.trim().replace(/\s+/g, " ");
    const followUp = `Let’s pick up this earlier topic: “${excerpt}”`;
    setPrompt((draft) => draft.trim() ? `${draft} ${followUp}` : followUp);
    composerRef.current?.focus();
  }

  const loadedTopics = useMemo(() => messages.flatMap((message, index) =>
    message.role === "user" && message.record_id !== undefined
      ? [{ id: message.record_id, created_at: message.created_at, excerpt: message.content.slice(0, 300),
          reply: messages[index + 1]?.role === "assistant" ? messages[index + 1].content.slice(0, 400) : undefined }]
      : [],
  ), [messages]);

  useEffect(() => {
    if (dest === "skills") {
      void fetchJson(`${baseUrl}/v1/skills`).then((d) => setSkills(d.skills ?? []));
    } else if (dest === "integrations") {
      void fetchJson(`${baseUrl}/v1/mcp/servers`).then((d) => setMcpServers(d.servers ?? []));
    } else if (dest === "tasks") {
      void fetchJson(`${baseUrl}/v1/workflows`).then((d) => setWorkflows(d.workflows ?? []));
    } else if (dest === "youtube" || dest === "studio") {
      void fetchJson(`${baseUrl}/v1/youtube/episodes`).then((d) => setEpisodes(d.episodes ?? []));
    } else if (dest === "media") {
      void fetchJson(`${baseUrl}/v1/media/archive`).then((d) => setMediaArchive(d.items ?? []));
    } else if (dest === "memory") {
      void fetchJson(`${baseUrl}/v1/memory/facts`).then((d) => setFacts(d.facts ?? []));
      setLearningQuery("");
      void fetchJson(`${baseUrl}/v1/memory/learning`).then((d) => setLearning(d.entries ?? []));
    } else if (dest === "goals") {
      void fetchJson(`${baseUrl}/v1/memory/goals`).then((d) => setGoals(d.goals ?? []));
    } else if (dest === "models" || dest === "settings") {
      void fetchJson(`${baseUrl}/v1/models`).then((d) => {
        setModels(d.models ?? []);
        setActiveModel(d.active ?? "");
        if (d.routing) setModelRouting(d.routing);
      });
    } else if (dest === "droid") {
      void fetchJson(`${baseUrl}/v1/droid/devices?refresh=1`).then((d) => {
        if (d.devices) setDroidDevices(d.devices);
      });
    }
  }, [dest, baseUrl]);

  const applyDroidSnapshot = (d: Record<string, any>) => {
    if (!d || typeof d !== "object") return;
    if (d.devices) setDroidDevices(d.devices);
    if (d.pose) setDroidPose(d.pose);
    if (typeof d.sleeping === "boolean") {
      setDroidSleeping(d.sleeping);
      if (d.sleeping) setDroidPreview(false);
    } else if (typeof d.awake === "boolean") {
      const asleep = !d.awake;
      setDroidSleeping(asleep);
      if (asleep) setDroidPreview(false);
    }
    if (typeof d.camera === "string" && d.camera) {
      setDroidCameraState(d.camera);
      if (d.camera === "parked") setDroidPreview(false);
    }
    if (typeof d.voice_enrolled === "boolean") {
      setDroidVoiceEnrolled(d.voice_enrolled);
    }
    if (d.reflex && typeof d.reflex === "object") {
      setDroidAutoPark({
        enabled: Boolean(d.reflex.auto_park_enabled),
        idle_park_s: Number(d.reflex.idle_park_s || 600),
      });
    }
    if (typeof d.estop_active === "boolean") {
      setResources((prev) => (prev.estop_active === d.estop_active ? prev : { ...prev, estop_active: d.estop_active }));
    }
  };

  useEffect(() => {
    if (dest !== "droid") return;
    let cancelled = false;
    const pollDroidStatus = async () => {
      const epoch = droidEpochRef.current;
      const d = await fetchJson(`${baseUrl}/v1/droid/status`);
      if (!cancelled && epoch === droidEpochRef.current && d.ok !== false && Object.keys(d).length > 0) {
        applyDroidSnapshot(d);
      }
    };
    void pollDroidStatus();
    const id = window.setInterval(() => void pollDroidStatus(), 2500);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [dest, baseUrl]);

  const wakeDroid = async (): Promise<boolean> => {
    droidEpochRef.current += 1;
    setDroidBusy(true);
    setDroidStatusMsg("Waking Droid…");
    try {
      const r = await fetch(`${baseUrl}/v1/droid/wake`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: "ui_operator" }),
      });
      const d = await r.json().catch(() => ({}));
      applyDroidSnapshot(d);
      if (r.ok && d.ok !== false) {
        setDroidSleeping(false);
        if (!d.camera) setDroidCameraState("ready");
        setDroidStatusMsg(
          d.hardware_dispatched === false
            ? "Droid awake (no gimbal hardware response)."
            : "Droid awake — camera centered.",
        );
        return true;
      }
      setDroidStatusMsg(d.error || (r.status === 409 ? "Wake blocked while E-Stop is active." : "Could not wake Droid."));
      return false;
    } catch {
      setDroidStatusMsg("Could not reach the Droid wake endpoint.");
      return false;
    } finally {
      setDroidBusy(false);
    }
  };

  const sleepDroid = async (): Promise<boolean> => {
    droidEpochRef.current += 1;
    setDroidBusy(true);
    setDroidPreview(false);
    setDroidStatusMsg("Parking camera and putting Droid to sleep…");
    try {
      const r = await fetch(`${baseUrl}/v1/droid/sleep`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: "ui_operator" }),
      });
      const d = await r.json().catch(() => ({}));
      applyDroidSnapshot(d);
      if (r.ok && d.ok !== false) {
        setDroidSleeping(true);
        if (!d.camera) setDroidCameraState("parked");
        setDroidPreview(false);
        setDroidStatusMsg("Droid asleep — camera parked.");
        return true;
      }
      setDroidStatusMsg(d.error || "Could not put Droid to sleep.");
      return false;
    } catch {
      setDroidStatusMsg("Could not reach the Droid sleep endpoint.");
      return false;
    } finally {
      setDroidBusy(false);
    }
  };

  useEffect(() => {
    void fetchJson(`${baseUrl}/v1/identity`).then((d) => {
      if (d.identity) {
        setIdentity(d.identity);
        setIdAiName(d.identity.ai_name ?? "Jaeger");
        setIdOwnerName(d.identity.owner_name ?? "Owner");
        setIdentityLoaded(true);
      }
    });
    void fetchJson(`${baseUrl}/v1/onboarding/status`).then((d) => {
      if (d.model_routing) setModelRouting(d.model_routing);
      if (typeof d.droid_available === "boolean") setOnboardingDroidAvailable(d.droid_available);
      if (d.completed === false && readPreference("jaeger.onboarding.dismissed") !== "1") {
        setAwakeningOpen(true);
      }
    });
  }, [baseUrl]);

  useEffect(() => {
    if (!awakeningOpen || models.length > 0) return;
    void fetchJson(`${baseUrl}/v1/models`).then((d) => {
      if (Array.isArray(d.models)) setModels(d.models);
      if (d.active) setActiveModel(d.active);
      if (d.routing) setModelRouting(d.routing);
    });
  }, [awakeningOpen, models.length, baseUrl]);

  const selectCharacter = async (characterId: string) => {
    const preset = characterLibrary.find((character) => character.character_id === characterId);
    const body = preset && !identity.characters?.[characterId]
      ? { character_id: preset.character_id, name: preset.name, style: preset.style, voice_id: preset.voice_id, activate: true }
      : { character_id: characterId || null, activate_only: true };
    setCharacterPending(true);
    setCharacterError("");
    try {
      const response = await fetch(`${baseUrl}/v1/identity/character`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await response.json();
      if (!response.ok || !data.identity) throw new Error(data.error || "Could not change character.");
      setIdentity(data.identity);
    } catch (error) {
      setCharacterError(error instanceof Error ? error.message : "Could not change character.");
    } finally {
      setCharacterPending(false);
    }
  };

  useEffect(() => {
    if (dest !== "droid" || resources.estop_active || droidSleeping) setDroidPreview(false);
  }, [dest, resources.estop_active, droidSleeping]);

  const sending = runStatus === "running" || runStatus === "queued" || runStatus === "awaiting_approval";
  useEffect(() => {
    if (!sending || keepAwake !== "on" || !navigator.wakeLock) return;
    let active = true;
    let lock: WakeLockSentinel | undefined;
    const acquire = async () => {
      if (document.visibilityState !== "visible" || (lock && !lock.released)) return;
      try {
        const next = await navigator.wakeLock.request("screen");
        if (active) lock = next; else await next.release();
      } catch { /* The OS can decline a screen wake lock. */ }
    };
    void acquire();
    document.addEventListener("visibilitychange",acquire);
    return () => {active=false;document.removeEventListener("visibilitychange",acquire);void lock?.release();};
  }, [sending,keepAwake]);
  const sendPrompt = async (voiceText?: string) => {
    const text = (voiceText ?? prompt).trim();
    if (!text || sending || sendingRef.current || historyState !== "ready") {
      if (voiceText) setPrompt((draft) => draft.trim() ? `${draft} ${text}` : text);
      return false;
    }
    sendingRef.current = true;
    try {
      const store = storeRef.current;
      if (!store || !activeSessionId || store.getSnapshot().sessionId !== activeSessionId) {
        throw new Error("The conversation is still reconnecting.");
      }
      if (!voiceText) setPrompt("");
      setHistoryError("");
      await store.sendPrompt(text);
      void refreshSystem();
      return true;
    } catch (failure) {
      setPrompt((current) => current ? `${current} ${text}` : text);
      setHistoryError(failure instanceof Error ? failure.message : "Could not send the message.");
      return false;
    } finally {
      sendingRef.current = false;
    }
  };

  useEffect(() => {
    if (!activeSessionId || dest !== "chat") return;
    const controller = new AbortController();
    const sessionId = activeSessionId;
    const url = `${baseUrl}/v1/approvals?session_id=${encodeURIComponent(sessionId)}`;
    async function loadScheduleApprovals() {
      try {
        const response = await fetch(url, { signal: controller.signal });
        if (!response.ok) {
          if (!controller.signal.aborted) setScheduleApprovals({ sessionId, items: [] });
          return;
        }
        const data: { approvals?: Array<{ approval_id: string; session_id: string; tool_name: string; prompt: string }> } = await response.json();
        if (controller.signal.aborted) return;
        const items: ApprovalPart[] = [];
        for (const row of Array.isArray(data.approvals) ? data.approvals : []) {
          if (!row || row.tool_name !== "schedule-proposal" || row.session_id !== sessionId || typeof row.approval_id !== "string") continue;
          try {
            const payload = JSON.parse(row.prompt);
            if (typeof payload?.prompt !== "string" || typeof payload.due_at !== "number" || !Number.isFinite(payload.due_at)) continue;
            const date = new Date(payload.due_at * 1000);
            const start = Number.isNaN(date.getTime()) ? String(payload.due_at) : date.toLocaleString();
            const interval = typeof payload.interval_s === "number" ? ` · Repeats every ${payload.interval_s} seconds` : "";
            items.push({
              type: "approval", approvalId: row.approval_id, toolName: "Scheduled job",
              prompt: `${payload.prompt} · Starts ${start}${interval}`, status: "pending",
            });
          } catch {
            // Ignore malformed proposals; do not offer an approval for them.
          }
        }
        setScheduleApprovals({ sessionId, items });
      } catch {
        if (!controller.signal.aborted) setScheduleApprovals({ sessionId, items: [] });
      }
    }
    void loadScheduleApprovals();
    return () => controller.abort();
  }, [activeSessionId, approvalRefresh, baseUrl, dest, runStatus]);

  const handleApproval = async (approvalId: string, decision: "approve" | "deny") => {
    setApprovalError("");
    setDecidingApproval(approvalId);
    try {
      const response = await fetch(`${baseUrl}/v1/approvals/${encodeURIComponent(approvalId)}/resolve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision }),
      });
      if (!response.ok) throw new Error("Could not record the approval decision.");
      setApprovalRefresh((current) => current + 1);
    } catch {
      setApprovalError("Could not record the approval decision.");
    } finally {
      setDecidingApproval(undefined);
    }
  };

  const runSafeDryRun = async () => {
    setDryRunBusy(true);
    try {
      const res = await fetch(`${baseUrl}/v1/workflows/dry-run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: "YouTube Episode Launch Pipeline",
          steps: [
            { id: "s1", name: "Playlist Research", action: "youtube_research", read_only: true },
            { id: "s2", name: "Script Draft", action: "write_script", read_only: true },
            { id: "s3", name: "Kokoro MLX Voiceover", action: "tts_render", read_only: true },
            { id: "s4", name: "Publish to YouTube", action: "youtube_publish", side_effect: true },
          ],
        }),
      });
      if (res.ok) {
        const d = await res.json();
        setDryRunResult(
          `Dry-Run OK: ${d.dry_run.total_steps} steps simulated, ${d.dry_run.total_side_effect_steps} side-effect step(s) safely intercepted.`,
        );
      }
    } finally {
      setDryRunBusy(false);
    }
  };

  const toggleIdleLife = async () => {
    const next = !resources.idle_life_enabled;
    const res = await fetch(`${baseUrl}/v1/system/idle-life`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: next }),
    });
    if (res.ok) {
      const d = await res.json();
      setResources(d.resources ?? {});
    }
  };

  const toggleEstop = async () => {
    const next = !resources.estop_active;
    const res = await fetch(`${baseUrl}/v1/system/estop`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ active: next, reason: "ui_operator_button" }),
    });
    if (res.ok) {
      const d = await res.json();
      setResources(d.resources ?? {});
    }
  };

  const triggerAvatarVisemeTest = async () => {
    const res = await fetch(
      `${baseUrl}/v1/avatars/jaeger/visemes?text=${encodeURIComponent("Hello! Jaeger is online and watching your studio.")}`,
    );
    if (res.ok) {
      const d = await res.json();
      setVisemes(d.frames ?? []);
    }
  };

  const setAvatarEmotion = async (emotion: string) => {
    const res = await fetch(`${baseUrl}/v1/avatars/jaeger/live`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ emotion, intensity: 0.8 }),
    });
    if (res.ok) {
      const d = await res.json();
      setAvatarRec((prev) => ({ ...prev, live: d.live }));
    }
  };

  const handleAvatarUpload = async (file: File) => {
    setAvatarUploadMsg("Uploading...");
    const b64 = await new Promise<string>((resolve, reject) => {
      const r = new FileReader();
      r.onload = () => resolve(String(r.result || ""));
      r.onerror = () => reject(r.error);
      r.readAsDataURL(file);
    });
    const up = await fetch(`${baseUrl}/v1/avatars/assets`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: file.name, data_base64: b64 }),
    });
    if (!up.ok) {
      const err = await up.json().catch(() => ({ error: "Upload failed" }));
      setAvatarUploadMsg(`Error: ${err.error}`);
      return;
    }
    const { asset } = await up.json();
    const mode = asset.format === "vrm" || asset.format === "glb" ? "3d_vrm" : "2d_character";
    const bind = await fetch(`${baseUrl}/v1/avatars/jaeger`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ asset_sha: asset.sha256, mode, display_name: "Jaeger" }),
    });
    if (bind.ok) {
      setAvatarRec(await bind.json());
      setAvatarUploadMsg(`Loaded ${asset.name} (${asset.format.toUpperCase()})`);
    }
  };

  const estTokens = useMemo(
    () => messages.reduce((sum, m) => sum + Math.ceil((m.content?.length ?? 0) / 4), 0),
    [messages],
  );

  useEffect(() => {
    if (!rightSidebarOpen) return;
    void fetchJson(`${baseUrl}/v1/workflows`).then((d) => {
      if (Array.isArray(d.workflows)) setWorkflows(d.workflows);
    });
  }, [rightSidebarOpen, baseUrl]);

  const recentToolTasks = useMemo(() => {
    const items: Array<{ id: string; toolName: string; status: string; durationMs?: number; recordId?: number }> = [];
    for (let mi = messages.length - 1; mi >= 0 && items.length < 8; mi -= 1) {
      const m = messages[mi];
      for (let pi = m.parts.length - 1; pi >= 0 && items.length < 8; pi -= 1) {
        const part = m.parts[pi];
        if (part.type === "tool") {
          items.push({
            id: `${m.id}:${part.callId || pi}`,
            toolName: part.toolName,
            status: part.status,
            durationMs: part.durationMs,
            recordId: m.record_id,
          });
        }
      }
    }
    return items;
  }, [messages]);

  const paletteCommands: CommandItem[] = useMemo(
    () => [
      ...workspaceNavigation.map((d) => ({
        id: `nav:${d.id}`,
        label: `Open ${d.label}`,
        group: "Navigate",
        onSelect: () => setDest(d.id),
      })),
      { id: "act:left-sidebar", label: leftSidebarOpen ? "Hide Left Sidebar" : "Show Left Sidebar", group: "View", onSelect: () => setLeftSidebarOpen((v) => !v) },
      { id: "act:right-sidebar", label: rightSidebarOpen ? "Hide Right Sidebar" : "Show Right Sidebar", group: "View", onSelect: () => setRightSidebarOpen((v) => !v) },
      {
        id: "act:checkpoints",
        label: "Open Conversation Checkpoints",
        group: "View",
        onSelect: () => {
          setLeftSidebarOpen(true);
          setLeftSidebarTab("checkpoints");
        },
      },
      {
        id: "act:avatar",
        label: "Open VR Avatar Inspector",
        group: "View",
        onSelect: () => {
          setRightSidebarOpen(true);
          setRightSidebarTab("avatar");
        },
      },
      { id: "act:theme", label: `Switch to ${theme === "dark" ? "Light" : "Dark"} Theme`, group: "View", onSelect: () => setMode(theme === "dark" ? "Light" : "Dark") },
      { id: "act:onboard", label: "Run Day-1 Awakening Setup Wizard", group: "Setup", onSelect: () => setAwakeningOpen(true) },
      { id: "act:idle", label: resources.idle_life_enabled ? "Pause Idle Minecraft Life" : "Enable Idle Minecraft Life", group: "Body", onSelect: () => void toggleIdleLife() },
      { id: "act:estop", label: resources.estop_active ? "Release Emergency Stop" : "Trigger Emergency Stop (E-Stop)", group: "Safety", onSelect: () => void toggleEstop() },
    ],
    [leftSidebarOpen, rightSidebarOpen, theme, resources.idle_life_enabled, resources.estop_active],
  );

  const characters = [
    ...characterLibrary.map((character) => identity.characters?.[character.character_id] ?? character),
    ...Object.values(identity.characters ?? {}).filter(
      (character) => !characterLibrary.some((preset) => preset.character_id === character.character_id),
    ),
  ];
  const characterId = identity.active_character_id ?? "";
  const activeCharacter = characters.find((character) => character.character_id === characterId);
  const characterPortrait = characterLibrary.find((character) => character.character_id === characterId)?.portrait;
  const truthClip = characterId === "truth" || characterId === "truth-gate"
    ? `/assets/avatar/jaeger/${["running", "streaming", "queued"].includes(runStatus) ? "working" : "idle"}.mp4`
    : null;
  const avatarMode = characterPortrait ? "2d_character" : avatarRec.avatar?.mode ?? "2d_character";
  const avatarModelUrl = avatarRec.asset?.format === "vrm" || avatarRec.asset?.format === "glb" ? `${baseUrl}${avatarRec.asset.uri}` : null;
  const avatarImageUrl = avatarRec.asset?.format === "image" ? `${baseUrl}${avatarRec.asset.uri}` : null;
  const liveEmotion = avatarRec.live?.emotion || cognition.emotion || "warm";
  const liveCogMode = resources.estop_active ? "estop" : cognition.mode || "observing";

  const brandName = activeCharacter?.name || identity.ai_name || "Jaeger";
  const currentViewLabel = workspaceNavigation.find((item) => item.id === dest)?.label ?? "Chat";
  const rightQuery = rightSearch.trim().toLowerCase();
  const matchingDestinations = rightQuery
    ? workspaceNavigation.filter((item) => item.label.toLowerCase().includes(rightQuery) || item.id.includes(rightQuery))
    : [];
  const filteredWorkflows = rightQuery
    ? workflows.filter((w) => w.name.toLowerCase().includes(rightQuery) || w.status.toLowerCase().includes(rightQuery))
    : workflows;
  const filteredToolTasks = rightQuery
    ? recentToolTasks.filter((t) => t.toolName.toLowerCase().includes(rightQuery) || t.status.toLowerCase().includes(rightQuery))
    : recentToolTasks;
  const backgroundTaskCount = (sending ? 1 : 0) + filteredWorkflows.length + filteredToolTasks.length;

  const saveRoutingTier = async (tier: "primary" | "background" | "vision" | "fallback", value: string) => {
    setModelRouting((prev) => ({ ...prev, [tier]: value }));
    setRoutingSavedMsg("");
    const res = await fetch(`${baseUrl}/v1/models/routing`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ [tier]: value }),
    });
    if (res.ok) {
      const d = await res.json();
      if (d.routing) setModelRouting(d.routing);
      if (d.active) setActiveModel(d.active);
      setRoutingSavedMsg(`Saved ${tier} tier.`);
    }
  };

  const modelPanel = (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div className="jg-card">
                <h3 style={{ marginTop: 0 }}>Active Model (Hybrid Cloud + Local)</h3>
                <select
                  className="jg-input"
                  value={activeModel}
                  onChange={async (e) => {
                    const next = e.target.value;
                    setActiveModel(next);
                    const r = await fetch(`${baseUrl}/v1/models/select`, {
                      method: "POST",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ model: next }),
                    });
                    if (r.ok) {
                      const d = await r.json();
                      if (d.routing) setModelRouting(d.routing);
                    }
                  }}
                >
                  {models.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.id}
                    </option>
                  ))}
                </select>
              </div>
              <div className="jg-card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <h4 style={{ margin: 0 }}>Hybrid Tier Routing</h4>
                  {routingSavedMsg && <span className="jg-muted">{routingSavedMsg}</span>}
                </div>
                <p className="jg-muted" style={{ margin: 0, fontSize: 12.5 }}>
                  Use flagship cloud or local models for chat, a fast/efficient model for background self-actions, and a local model for private vision and offline fallback.
                </p>
                {([
                  { key: "background", label: "Background & Autonomy Tier", emptyLabel: "Same as primary" },
                  { key: "vision", label: "Droid Vision Model", emptyLabel: "Default (qwen3-vl:8b-instruct)" },
                  { key: "fallback", label: "Offline Local Fallback", emptyLabel: "None" },
                ] as const).map((tier) => (
                  <label key={tier.key} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    <span style={{ fontSize: 12.5 }}>{tier.label}</span>
                    <select
                      className="jg-input"
                      aria-label={tier.label}
                      value={modelRouting[tier.key] ?? ""}
                      onChange={(e) => void saveRoutingTier(tier.key, e.target.value)}
                    >
                      <option value="">{tier.emptyLabel}</option>
                      {models.map((m) => (
                        <option key={m.id} value={m.id}>{m.id}</option>
                      ))}
                    </select>
                  </label>
                ))}
              </div>
            </div>
  );

  return (
    <div
      className="jg-ushell"
      data-testid="jaeger-modular-app"
      data-left-open={leftSidebarOpen ? "true" : "false"}
      data-right-open={rightSidebarOpen ? "true" : "false"}
    >
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} items={paletteCommands} />
      <AwakeningWizard
        baseUrl={baseUrl}
        open={awakeningOpen}
        initialOwnerName={identity.owner_name}
        initialAiName={identity.ai_name}
        initialMission={identity.mission}
        models={models}
        initialRouting={modelRouting}
        droidAvailable={onboardingDroidAvailable || Boolean(droidDevices.gimbal_camera || droidDevices.cameras?.length)}
        onWakeDroid={wakeDroid}
        onSleepDroid={sleepDroid}
        onComplete={(data) => {
          if (data.identity) {
            setIdentity(data.identity);
            setIdAiName(data.identity.ai_name ?? "Jaeger");
            setIdOwnerName(data.identity.owner_name ?? "Owner");
          }
          if (data.model_routing) setModelRouting(data.model_routing);
          setAwakeningOpen(false);
          void refreshSystem();
        }}
        onDismiss={() => {
          savePreference("jaeger.onboarding.dismissed", "1");
          setAwakeningOpen(false);
        }}
      />

      <header className="jg-ushell__header" aria-label="Jaeger toolbar">
        <div className="jg-ushell__header-start">
          <span className="jg-ushell__brand-name">{brandName}</span>
          <button
            type="button"
            className="jg-ushell__icon-btn jg-ushell__sidebar-toggle"
            aria-label="Toggle left sidebar"
            aria-pressed={leftSidebarOpen}
            aria-controls="jg-left-sidebar"
            title="Toggle left sidebar (⌘B)"
            onClick={() => setLeftSidebarOpen((open) => {
              const next = !open;
              if (next && isCompactViewport()) setRightSidebarOpen(false);
              return next;
            })}
          >
            <svg width="16" height="16" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
              <rect x="2" y="2.5" width="14" height="13" rx="2.5" />
              <path d="M6.75 2.5v13" />
            </svg>
          </button>
          <button
            type="button"
            className="jg-ushell__icon-btn"
            aria-label="Quick Command"
            title="Search & quick commands (⌘K)"
            onClick={() => setPaletteOpen(true)}
          >
            <svg width="15" height="15" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
              <circle cx="8" cy="8" r="5" />
              <path d="M12 12l3.5 3.5" strokeLinecap="round" />
            </svg>
          </button>
          <span className="jg-ushell__crumb-sep" aria-hidden="true">/</span>
          <div className="jg-ushell__title">{currentViewLabel}</div>
        </div>
        <div className="jg-ushell__header-end">
          <button type="button" className={`jg-btn ${resources.estop_active ? "jg-btn-danger" : ""}`} onClick={() => void toggleEstop()}>
            {resources.estop_active ? "E-STOP ON" : "E-Stop"}
          </button>
          <button type="button" className="jg-ushell__icon-btn jg-ushell__theme" onClick={() => setMode(theme === "dark" ? "Light" : "Dark")}>
            {theme === "dark" ? "Light" : "Dark"}
          </button>
          <button
            type="button"
            className="jg-ushell__icon-btn jg-ushell__sidebar-toggle"
            aria-label="Toggle right sidebar"
            aria-pressed={rightSidebarOpen}
            aria-controls="jg-right-sidebar"
            title="Toggle right sidebar (⌘.)"
            onClick={() => setRightSidebarOpen((open) => {
              const next = !open;
              if (next && isCompactViewport()) setLeftSidebarOpen(false);
              return next;
            })}
          >
            <svg width="16" height="16" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
              <rect x="2" y="2.5" width="14" height="13" rx="2.5" />
              <path d="M11.25 2.5v13" />
            </svg>
          </button>
        </div>
      </header>

      <aside
        id="jg-left-sidebar"
        className="jg-ushell__sidebar"
        aria-label="Primary navigation"
        hidden={!leftSidebarOpen}
      >
        <div className="jg-ushell__sidebar-top">
          <button
            type="button"
            className="jg-ushell__new-btn"
            onClick={() => {
              setDest("chat");
              jumpToLatest();
              composerRef.current?.focus();
            }}
          >
            <span aria-hidden="true">+</span>
            <span>Focus Chat</span>
          </button>
          <div className="jg-tabs-inline" role="tablist" aria-label="Left sidebar mode">
            <button
              type="button"
              role="tab"
              aria-selected={leftSidebarTab === "workspace"}
              data-active={leftSidebarTab === "workspace"}
              onClick={() => setLeftSidebarTab("workspace")}
            >
              Workspace
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={leftSidebarTab === "checkpoints"}
              data-active={leftSidebarTab === "checkpoints"}
              onClick={() => setLeftSidebarTab("checkpoints")}
            >
              Checkpoints
            </button>
          </div>
        </div>

        {leftSidebarTab === "workspace" ? (
          <nav className="jg-ushell__rail" aria-label="Destinations">
            {workspaceNavigation
              .filter((item) => item.id !== "settings")
              .map((item) => (
                <a
                  key={item.id}
                  className="jg-ushell__rail-btn"
                  href={item.path}
                  aria-current={dest === item.id ? "page" : undefined}
                  onClick={(event) => {
                    if (event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
                    event.preventDefault();
                    setDest(item.id);
                  }}
                >
                  <span>{item.label}</span>
                </a>
              ))}
          </nav>
        ) : (
          <div className="jg-ushell__sidebar-tracker">
            <ConversationTimeline
              mode="panel"
              baseUrl={baseUrl}
              open={leftSidebarOpen && leftSidebarTab === "checkpoints"}
              loadedTopics={loadedTopics}
              visibleTopicId={visibleTopicId}
              busy={loadingOlder}
              onJump={(id) => {
                if (dest !== "chat" && dest !== "droid") setDest("chat");
                jumpToTopic(id);
              }}
              onResume={(topic) => {
                if (dest !== "chat" && dest !== "droid") setDest("chat");
                resumeTopic(topic);
              }}
              onLatest={() => {
                if (dest !== "chat" && dest !== "droid") setDest("chat");
                jumpToLatest();
              }}
            />
          </div>
        )}

        <div className="jg-ushell__sidebar-footer">
          <a
            className="jg-ushell__rail-btn jg-ushell__settings-link"
            href="/settings"
            aria-current={dest === "settings" ? "page" : undefined}
            onClick={(event) => {
              if (event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
              event.preventDefault();
              setDest("settings");
            }}
          >
            <svg width="15" height="15" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
              <circle cx="9" cy="9" r="2.75" />
              <path d="M9 2.2v1.6M9 14.2v1.6M2.2 9h1.6M14.2 9h1.6M4.2 4.2l1.1 1.1M12.7 12.7l1.1 1.1M13.8 4.2l-1.1 1.1M5.3 12.7l-1.1 1.1" strokeLinecap="round" />
            </svg>
            <span>Settings</span>
          </a>
        </div>
      </aside>

      <main className="jg-main jg-ushell__main">
        {dest === "characters" && (
          <div className="jg-content jg-ushell__characters">
            <h1>Characters</h1>
            <div className="jg-ushell__character-actions">
              <p>Choose a character for Jaeger’s chats.</p>
              <button type="button" className="jg-btn" disabled={!identityLoaded || characterPending || !characterId} onClick={() => void selectCharacter("")}>
                Use default identity
              </button>
            </div>
            {characterError && <p role="alert">{characterError}</p>}
            <ul className="jg-ushell__character-grid">
              {characters.map((character) => {
                const portrait = characterLibrary.find((preset) => preset.character_id === character.character_id)?.portrait;
                return (
                  <li key={character.character_id}>
                    <button type="button" className="jg-ushell__character-card" aria-pressed={characterId === character.character_id}
                      disabled={!identityLoaded || characterPending} onClick={() => void selectCharacter(character.character_id)}>
                      {portrait ? <img src={portrait} alt="" loading="lazy" /> : <span aria-hidden="true">{character.name.slice(0, 1)}</span>}
                      <strong>{characterLabel(character)}</strong>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        )}

          <div hidden={dest !== "chat" && dest !== "droid"} className={`jg-workspace-split ${dest === "droid" ? "jg-droid-workspace" : "is-drawer-closed"}`}>
        {dest === "droid" && (
          <div className="jg-droid-panel">
            <div className="jg-card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <div className="jg-droid-header">
                <h3 style={{ margin: 0 }}>Droid Mode — Connected Host Peripherals</h3>
                <button
                  type="button"
                  role="switch"
                  aria-checked={!droidSleeping}
                  className={`jg-btn jg-droid-mode-toggle ${droidSleeping ? "is-off" : "is-on"}`}
                  disabled={droidBusy || (droidSleeping && Boolean(resources.estop_active))}
                  title={
                    droidSleeping
                      ? (resources.estop_active ? "Release E-Stop to turn on Droid Mode" : "Turn On Droid Mode")
                      : "Turn Off Droid Mode (Sleep & Park Camera)"
                  }
                  onClick={() => void (droidSleeping ? wakeDroid() : sleepDroid())}
                >
                  <span className="jg-droid-mode-indicator" aria-hidden="true" />
                  <span className="jg-droid-mode-state">
                    {droidSleeping ? "Droid Mode: OFF" : "Droid Mode: ON"}
                  </span>
                  <span className="jg-droid-mode-action">
                    {droidSleeping ? "Turn On Droid Mode" : "Turn Off Droid Mode"}
                  </span>
                </button>
              </div>
              {droidPreview && !resources.estop_active && !droidSleeping && (
                <img className="jg-droid-preview" src={`${baseUrl}/v1/droid/camera-stream`}
                  alt="Live Droid camera" onError={() => {
                    setDroidPreview(false);
                    setDroidStatusMsg("Could not open the live camera stream.");
                  }} />
              )}
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <span className={`jg-pill jg-droid-state-pill ${droidSleeping ? "is-asleep" : "is-awake"}`}>
                  State: {droidSleeping ? "Asleep (Camera Parked)" : "Awake"}
                </span>
                <span className="jg-pill">Camera: {droidCameraState}</span>
                <span className="jg-pill">Gimbal: {droidDevices.gimbal_camera?.name ?? "None detected"}</span>
                <span className="jg-pill">Cameras: {droidDevices.cameras?.length ?? 0}</span>
                <span className="jg-pill">Mics: {droidDevices.microphones?.length ?? 0}</span>
                <span className="jg-pill">Speakers: {droidDevices.speakers?.length ?? 0}</span>
                <span className="jg-pill">Pose: pan {droidPose.pan_deg ?? "—"}° · tilt {droidPose.tilt_deg ?? "—"}°</span>
                <span className="jg-pill">Face Tracking: {droidPose.tracking ? "ON" : "OFF"}</span>
                {droidVoiceEnrolled !== null && (
                  <span className="jg-pill">Voice ID: {droidVoiceEnrolled ? "Enrolled" : "Not enrolled"}</span>
                )}
                <button
                  type="button"
                  className="jg-pill"
                  style={{ cursor: "pointer" }}
                  title="Privacy reflex: automatically park camera when idle"
                  onClick={async () => {
                    const nextEnabled = !droidAutoPark.enabled;
                    try {
                      const r = await fetch(`${baseUrl}/v1/droid/reflex`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ auto_park_enabled: nextEnabled }),
                      });
                      const d = await r.json();
                      if (d.ok && d.reflex) {
                        setDroidAutoPark({
                          enabled: Boolean(d.reflex.auto_park_enabled),
                          idle_park_s: Number(d.reflex.idle_park_s || 600),
                        });
                        setDroidStatusMsg(nextEnabled ? `Privacy auto-park enabled (${Math.round((d.reflex.idle_park_s || 600) / 60)}m idle).` : "Privacy auto-park paused.");
                      }
                    } catch {
                      setDroidStatusMsg("Could not update Droid auto-park reflex.");
                    }
                  }}
                >
                  Auto-Park: {droidAutoPark.enabled ? `${Math.round(droidAutoPark.idle_park_s / 60)}m` : "OFF"}
                </button>
              </div>
              {droidVoiceEnrolled === false && (
                <div className="jg-muted" role="status" style={{ fontSize: 12.5 }}>
                  Voice ID not enrolled yet — start Droid Voice below and click Enroll so Jaeger recognizes only your voice.
                </div>
              )}
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                <button
                  type="button"
                  className={`jg-btn ${droidSleeping ? "jg-btn-primary" : ""}`}
                  disabled={droidBusy || Boolean(resources.estop_active)}
                  onClick={() => void wakeDroid()}
                >
                  Wake Droid
                </button>
                <button
                  type="button"
                  className="jg-btn jg-droid-sleep-btn"
                  disabled={droidBusy}
                  onClick={() => void sleepDroid()}
                >
                  Go to Sleep
                </button>
                {[
                  { label: "Look Left", action: "look_at", params: { pan_deg: -35, tilt_deg: 0 } },
                  { label: "Center Gimbal", action: "center", params: {} },
                  { label: "Look Right", action: "look_at", params: { pan_deg: 35, tilt_deg: 0 } },
                ].map((cmd) => (
                  <button
                    key={cmd.label}
                    type="button"
                    className="jg-btn"
                    disabled={droidBusy || Boolean(resources.estop_active) || droidSleeping}
                    title={droidSleeping ? "Wake Droid first" : undefined}
                    onClick={async () => {
                      setDroidBusy(true);
                      setDroidStatusMsg(`Sending ${cmd.label.toLowerCase()}…`);
                      try {
                        const r = await fetch(`${baseUrl}/v1/embodiment/droid/act`, {
                          method: "POST",
                          headers: { "Content-Type": "application/json" },
                          body: JSON.stringify({ action: cmd.action, params: cmd.params }),
                        });
                        const d = await r.json();
                        if (d.pose) setDroidPose(d.pose);
                        setDroidStatusMsg(d.ok
                          ? d.hardware_dispatched ? `${cmd.label}: command sent to camera` : "No gimbal command reached the camera. Check the controller connection."
                          : d.error || "Gimbal command refused");
                      } catch {
                        setDroidStatusMsg("Could not reach the Droid control endpoint.");
                      } finally {
                        setDroidBusy(false);
                      }
                    }}
                  >
                    {cmd.label}
                  </button>
                ))}
                <button
                  type="button"
                  className="jg-btn"
                  aria-pressed={Boolean(droidPose.tracking)}
                  disabled={droidBusy || Boolean(resources.estop_active) || droidSleeping}
                  title={droidSleeping ? "Wake Droid first" : undefined}
                  onClick={async () => {
                    const nextTracking = !droidPose.tracking;
                    setDroidBusy(true);
                    setDroidStatusMsg(nextTracking ? "Enabling face tracking…" : "Stopping face tracking…");
                    try {
                      const r = await fetch(`${baseUrl}/v1/embodiment/droid/act`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ action: "track_person", params: { enabled: nextTracking } }),
                      });
                      const d = await r.json().catch(() => ({}));
                      if (d.pose) setDroidPose(d.pose);
                      setDroidStatusMsg(d.ok ? (nextTracking ? "Face tracking enabled." : "Face tracking paused.") : (d.error || "Could not update tracking."));
                    } catch {
                      setDroidStatusMsg("Could not reach the Droid control endpoint.");
                    } finally {
                      setDroidBusy(false);
                    }
                  }}
                >
                  {droidPose.tracking ? "Stop Face Tracking" : "Track Face"}
                </button>
                <button
                  type="button"
                  className="jg-btn"
                  aria-pressed={droidPreview}
                  disabled={Boolean(resources.estop_active) || droidSleeping}
                  title={droidSleeping ? "Wake Droid first" : undefined}
                  onClick={() => {
                    setDroidStatusMsg("");
                    setDroidPreview(!droidPreview);
                  }}
                >
                  {droidPreview ? "Stop Live Camera" : "Start Live Camera"}
                </button>
                {droidStatusMsg ? (
                  <span className="jg-muted" role="status">{droidStatusMsg}</span>
                ) : droidSleeping ? (
                  <span className="jg-muted" role="status">Wake Droid first</span>
                ) : null}
              </div>
            </div>
          </div>
        )}

            <div className="jg-chat-with-timeline">
              <ConversationTimeline mode="rail" baseUrl={baseUrl} open={false} loadedTopics={loadedTopics}
                visibleTopicId={visibleTopicId}
                busy={loadingOlder} onJump={jumpToTopic} onResume={resumeTopic} onLatest={jumpToLatest} />
            <div className="jg-chat-column">
              {dest === "chat" && (
                <ReturnBriefingBanner
                  baseUrl={baseUrl}
                  onOpenOffice={() => setDest("office")}
                  onOpenApprovals={() => {
                    setRightSidebarTab("mind");
                    setRightSidebarOpen(true);
                  }}
                />
              )}
              <div
                className="jg-content"
                ref={viewportRef}
                aria-label="Conversation history"
                onScroll={(e) => {
                  const el = e.currentTarget;
                  trackVisibleTopic(el);
                  const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
                  scrollMachineRef.current.transition(nearBottom ? { type: "REACHED_BOTTOM" } : { type: "USER_SCROLL_UP" });
                  setShowJump(!nearBottom);
                  if (el.scrollTop <= 72 && !nearBottom) void loadOlder();
                }}
              >
                {olderCursor !== undefined && (
                  <button type="button" className="jg-btn" disabled={loadingOlder} onClick={() => void loadOlder()}>
                    {loadingOlder ? "Loading earlier messages…" : "Load earlier messages"}
                  </button>
                )}
                {historyState !== "ready" && <p role="status">{historyState === "loading" ? "Loading conversation…" : "Reconnecting to Jaeger…"}</p>}
                {historyError && <p role="alert">{historyError}</p>}
                {approvalError && <p role="alert">{approvalError}</p>}
                {scheduleApprovals?.sessionId === activeSessionId && scheduleApprovals.items.map((approval) => (
                  <ApprovalCard key={approval.approvalId} approval={approval} onDecision={handleApproval} disabled={decidingApproval !== undefined} />
                ))}
                {messages.length === 0 && historyState === "ready" ? (
                  <div className="jg-card" style={{ maxWidth: 680, margin: "28px auto" }}>
                    <h3 style={{ marginTop: 0 }}>Jaeger Command Center</h3>
                    <p style={{ color: "var(--jg-text-secondary)", marginBottom: 0 }}>
                      Conversation is an interface to your persistent AI mind. Ask Jaeger to run YouTube research, edit code,
                      manage your business team, or check on its autonomous world state — all under your 32 GB resource budget.
                    </p>
                  </div>
                ) : (
                  messages.map((m) => {
                    const live = sending && m === messages.at(-1) && m.role === "assistant";
                    let toolBatchStart = m.parts.length;
                    if (live && liveTools) {
                      while (toolBatchStart > 0 && m.parts[toolBatchStart - 1].type === "tool") toolBatchStart--;
                    }
                    return (
                      <article key={m.id} className="jg-msg" data-role={m.role} data-history-id={m.record_id}
                        data-timeline-target={highlightedTopicId !== undefined && highlightedTopicId === m.record_id || undefined}
                        tabIndex={m.role === "user" && m.record_id !== undefined ? -1 : undefined}>
                        <div style={{ fontSize: 11, fontWeight: 600, color: "var(--jg-text-muted)", marginBottom: 6 }}>
                          {m.role === "user" ? "You" : "Jaeger"}
                        </div>
                        {m.parts.map((part, idx) => {
                          const newest = idx === m.parts.length - 1;
                          if (part.type === "thinking") {
                            return <ThinkingDisclosure key={idx} part={part} autoOpen={liveReasoning && live && newest} />;
                          }
                          if (part.type === "tool") {
                            const inCurrentBatch = idx >= toolBatchStart;
                            return <ToolCallCard key={idx} part={part} autoOpen={liveTools && live && (inCurrentBatch || part.status === "running")} />;
                          }
                          if (part.type === "approval") {
                            return <ApprovalCard key={idx} approval={part} onDecision={handleApproval} />;
                          }
                          const streaming = m === messages.at(-1) && m.role === "assistant" && runStatus === "running";
                          return <StreamingMarkdown key={idx} text={part.text} streaming={streaming} />;
                        })}
                      </article>
                    );
                  })
                )}
                {showJump && (
                  <button
                    type="button"
                    className="jg-btn jg-btn-primary"
                    style={{ position: "sticky", bottom: 12, float: "right" }}
                    onClick={jumpToLatest}
                  >
                    Jump to Latest
                  </button>
                )}
              </div>

              {dest === "droid" && voiceEnabled === "on" && !resources.estop_active && (
                <DroidVoice
                  baseUrl={baseUrl}
                  aiName={activeCharacter?.name || identity.ai_name || "Jaeger"}
                  sleeping={droidSleeping}
                  busy={sending}
                  reply={messages.at(-1)?.role === "assistant" ? messages.at(-1)?.content ?? "" : ""}
                  replyId={messages.at(-1)?.role === "assistant" ? messages.at(-1)?.id : undefined}
                  onCamera={setDroidPreview}
                  onTranscript={(text) => sendPrompt(text)}
                  onSleep={sleepDroid}
                  onWake={wakeDroid}
                />
              )}
              <div className="jg-live-details" role="group" aria-label="Live stream details">
                <label><input type="checkbox" checked={liveReasoning} onChange={(event) => setLiveReasoning(event.target.checked)} /> Live reasoning</label>
                <label><input type="checkbox" checked={liveTools} onChange={(event) => setLiveTools(event.target.checked)} /> Live tool details</label>
              </div>
              {contextUsage === "on" && <ContextXrayBar
                usedTokens={estTokens}
                maxTokens={32768}
                hostTotalGb={resources.host_total_gb}
                hostAvailableGb={resources.host_available_gb}
                activeModel={health.model || activeModel}
              />}

              <form
                className="jg-composer"
                onSubmit={(e) => {
                  e.preventDefault();
                  void sendPrompt();
                }}
              >
                <textarea
                  rows={1}
                  aria-label="Message Jaeger"
                  onKeyDown={event => {
                    if (event.nativeEvent.isComposing || event.key !== "Enter" || event.shiftKey || event.altKey) return;
                    if (sendShortcut !== "Enter" && !event.metaKey && !event.ctrlKey) return;
                    event.preventDefault();
                    event.currentTarget.form?.requestSubmit();
                  }}
                  className="jg-input"
                  value={prompt}
                  ref={composerRef}
                  placeholder="Command Jaeger or your business team... (Cmd+K for quick actions)"
                  onChange={(e) => setPrompt(e.target.value)}
                />
                <button type="submit" className="jg-btn jg-btn-primary" disabled={!prompt.trim() || sending || historyState !== "ready"}>
                  {sending ? "Running..." : "Send"}
                </button>
              </form>
            </div>

            </div>
          </div>

        {dest === "research" && <ResearchPage baseUrl={baseUrl} />}

        {dest === "tasks" && (
          <div className="jg-content jg-workspace-page">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <h3 style={{ margin: 0 }}>Durable Business & Engineering Workflows</h3>
              <button
                type="button"
                className="jg-btn jg-btn-primary"
                onClick={async () => {
                  await fetch(`${baseUrl}/v1/workflows`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                      name: "YouTube Channel Production Run",
                      steps: [
                        { id: "research", name: "Analyze Playlist & Trends" },
                        { id: "script", name: "Draft Video Script", depends_on: ["research"] },
                        { id: "publish", name: "Human Approval & Publish", depends_on: ["script"], requires_approval: true },
                      ],
                    }),
                  });
                  const r = await fetch(`${baseUrl}/v1/workflows`);
                  if (r.ok) setWorkflows((await r.json()).workflows ?? []);
                }}
              >
                + Launch YouTube Pipeline
              </button>
            </div>
            {workflows.length === 0 ? (
              <div className="jg-card">No active workflow runs yet. Launch a YouTube pipeline or run Safe Dry-Run above.</div>
            ) : (
              workflows.map((w) => (
                <div key={w.run_id} className="jg-card">
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <strong>{w.name}</strong>
                    <span className="jg-pill">{w.status}</span>
                  </div>
                  <div className="jg-muted" style={{ marginTop: 6 }}>
                    Run ID: {w.run_id} · Steps: {w.total_steps} · Ready: {w.next_ready.join(", ") || "none"}
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {dest === "youtube" && (
          <div className="jg-content jg-workspace-page">
            <div className="jg-card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                <strong>YouTube Channel Episodes (32 GB Phased Pipeline)</strong>
                <span className="jg-pill">Owner Approval Required to Publish</span>
              </div>
              <form
                style={{ display: "flex", gap: 8 }}
                onSubmit={async (e) => {
                  e.preventDefault();
                  if (!newEpTitle.trim()) return;
                  const r = await fetch(`${baseUrl}/v1/youtube/episodes`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ title: newEpTitle.trim(), target_duration_s: 480 }),
                  });
                  if (r.ok) {
                    setNewEpTitle("");
                    const d = await fetchJson(`${baseUrl}/v1/youtube/episodes`);
                    setEpisodes(d.episodes ?? []);
                  }
                }}
              >
                <input
                  className="jg-input"
                  value={newEpTitle}
                  placeholder="New YouTube episode title (e.g. Ep 01: 24/7 Local Autonomous Droid)..."
                  onChange={(e) => setNewEpTitle(e.target.value)}
                />
                <button type="submit" className="jg-btn jg-btn-primary">+ Create Episode</button>
              </form>
              {episodes.map((ep) => (
                <div
                  key={ep.episode_id}
                  style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "6px 0", borderTop: "1px solid var(--jg-border-subtle)" }}
                >
                  <div>
                    <strong>{ep.title}</strong>
                    <div className="jg-muted">Stage: {ep.stage} · Lead: {ep.assigned_role} · Clips: {ep.timeline_clips?.length ?? 0}</div>
                  </div>
                  <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                    <button
                      type="button"
                      className="jg-btn-ghost"
                      onClick={async () => {
                        const d = await fetchJson(`${baseUrl}/v1/youtube/episodes/${encodeURIComponent(ep.episode_id)}/otio?fps=24`);
                        if (d.otio) {
                          const blob = new Blob([JSON.stringify(d.otio, null, 2)], { type: "application/json" });
                          const url = URL.createObjectURL(blob);
                          const a = document.createElement("a");
                          a.href = url;
                          a.download = `${ep.episode_id}.otio`;
                          a.click();
                          URL.revokeObjectURL(url);
                        }
                      }}
                    >
                      Export .otio
                    </button>
                    {!ep.owner_approved ? (
                      <button
                        type="button"
                        className="jg-btn"
                        onClick={async () => {
                          await fetch(`${baseUrl}/v1/youtube/episodes/${encodeURIComponent(ep.episode_id)}/advance`, {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ stage: "ready_to_publish", owner_approved: true, approval_note: "Approved in Studio UI" }),
                          });
                          const d = await fetchJson(`${baseUrl}/v1/youtube/episodes`);
                          setEpisodes(d.episodes ?? []);
                        }}
                      >
                        Approve to Publish
                      </button>
                    ) : (
                      <span className="jg-pill">Approved</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {dest === "studio" && (
          <div className="jg-content jg-workspace-page">
            <StudioTimeline
              projectTitle={episodes[0] ? `YouTube Studio · ${episodes[0].title}` : "Media Studio"}
              clips={episodes[0]?.timeline_clips ?? []}
              onDryRun={() => void runSafeDryRun()}
              dryRunBusy={dryRunBusy}
            />
            {dryRunResult && (
              <div className="jg-card">
                <strong>Safe-Mode Dry-Run Result:</strong> <span className="jg-muted">{dryRunResult}</span>
              </div>
            )}
          </div>
        )}

        {dest === "media" && (
          <div className="jg-content jg-workspace-page">
            <div className="jg-card">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <strong>Timestamped Media Archive (Capture → Archive → Edit)</strong>
                <span className="jg-pill">{mediaArchive.length} clips</span>
              </div>
              {mediaArchive.length === 0 ? (
                <div className="jg-muted" style={{ marginTop: 6 }}>
                  No archived clips yet. Camera, screen, and Minecraft captures indexed via <code>/v1/media/archive</code> appear here.
                </div>
              ) : (
                mediaArchive.map((item) => (
                  <div key={item.asset_id} style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", borderTop: "1px solid var(--jg-border-subtle)" }}>
                    <span><strong>[{item.kind}]</strong> {item.scene_description || item.source_path}</span>
                    <span className="jg-pill">{item.is_reconstructed ? "Reconstructed" : "Genuine"}</span>
                  </div>
                ))
              )}
            </div>
          </div>
        )}

        {dest === "office" && (
          <OfficeWorkspace
            baseUrl={baseUrl}
            onOpenChat={() => setDest("chat")}
            onOpenWorkflows={() => setDest("tasks")}
            onOpenDroid={() => setDest("droid")}
          />
        )}

        {dest === "tools" && <ToolsPage baseUrl={baseUrl} />}

        {dest === "skills" && (
          <div className="jg-content jg-workspace-page">
              <div className="jg-card">
                <h4 style={{ marginTop: 0 }}>Installed Skills (Hermes Skills Guard)</h4>
                {skills.length === 0 ? (
                  <div className="jg-muted">No skills discovered yet.</div>
                ) : (
                  skills.map((s) => (
                    <div key={s.path} style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", borderBottom: "1px solid var(--jg-border-subtle)" }}>
                      <span>{s.name}</span>
                      <span className="jg-pill">{s.security_verdict || "scanned"}</span>
                    </div>
                  ))
                )}
              </div>
          </div>
        )}

        {dest === "integrations" && (
          <div className="jg-content jg-workspace-page">
              <div className="jg-card">
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                  <h4 style={{ margin: 0 }}>Live MCP Servers (Aether / Resolve / Blender)</h4>
                  <button
                    type="button"
                    className="jg-btn-ghost"
                    onClick={async () => {
                      const r = await fetch(`${baseUrl}/v1/mcp/reload`, { method: "POST" });
                      if (r.ok) setMcpServers((await r.json()).servers ?? []);
                    }}
                  >
                    Hot-Reload
                  </button>
                </div>
                <form
                  style={{ display: "flex", gap: 6, marginBottom: 8 }}
                  onSubmit={async (e) => {
                    e.preventDefault();
                    if (!mcpNewName.trim() || !mcpNewUrl.trim()) return;
                    const r = await fetch(`${baseUrl}/v1/mcp/servers`, {
                      method: "POST",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ name: mcpNewName.trim(), transport: "streamable_http", url: mcpNewUrl.trim(), connect: true }),
                    });
                    if (r.ok) {
                      setMcpNewName("");
                      setMcpNewUrl("");
                      setMcpServers((await r.json()).servers ?? []);
                    }
                  }}
                >
                  <input className="jg-input" placeholder="Name (e.g. aether_studio)" value={mcpNewName} onChange={(e) => setMcpNewName(e.target.value)} />
                  <input className="jg-input" placeholder="HTTP MCP URL" value={mcpNewUrl} onChange={(e) => setMcpNewUrl(e.target.value)} />
                  <button type="submit" className="jg-btn">+ Connect</button>
                </form>
                {mcpServers.length === 0 ? (
                  <div className="jg-muted">No external MCP servers configured in ~/.jaeger/mcp_servers.json yet.</div>
                ) : (
                  mcpServers.map((m) => (
                    <div key={m.name} style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", borderBottom: "1px solid var(--jg-border-subtle)" }}>
                      <span>{m.name} ({m.transport})</span>
                      <span className="jg-pill">{m.connected ? `Connected (${m.tools_count})` : "Offline"}</span>
                    </div>
                  ))
                )}
              </div>
          </div>
        )}

        {dest === "goals" && (
          <div className="jg-content jg-workspace-page">
            <div className="jg-card">
              <h3 style={{ marginTop: 0 }}>Persistent Multi-Day Goals (Business & Idle Minecraft Life)</h3>
              <form
                style={{ display: "flex", gap: 8, marginBottom: 10 }}
                onSubmit={async (e) => {
                  e.preventDefault();
                  if (!newGoalTitle.trim()) return;
                  await fetch(`${baseUrl}/v1/memory/goals`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ domain: newGoalDomain, title: newGoalTitle.trim(), priority: newGoalDomain === "minecraft" ? 3 : 1 }),
                  });
                  setNewGoalTitle("");
                  const r = await fetch(`${baseUrl}/v1/memory/goals`);
                  if (r.ok) setGoals((await r.json()).goals ?? []);
                }}
              >
                <select className="jg-input" style={{ width: 150 }} value={newGoalDomain} onChange={(e) => setNewGoalDomain(e.target.value as "youtube" | "business" | "minecraft")}>
                  <option value="youtube">YouTube</option>
                  <option value="business">Business</option>
                  <option value="minecraft">Minecraft (Idle)</option>
                </select>
                <input className="jg-input" placeholder="Add persistent goal (survives reboots)..." value={newGoalTitle} onChange={(e) => setNewGoalTitle(e.target.value)} />
                <button type="submit" className="jg-btn jg-btn-primary">Add Goal</button>
              </form>
              {goals.length === 0 ? (
                <div className="jg-muted">No persistent goals yet — add a YouTube milestone or idle Minecraft project!</div>
              ) : (
                goals.map((g) => (
                  <div key={g.goal_id} style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", borderBottom: "1px solid var(--jg-border-subtle)" }}>
                    <span><strong>[{g.domain}]</strong> {g.title}</span>
                    <span className="jg-pill">P{g.priority} · {g.status}</span>
                  </div>
                ))
              )}
            </div>
          </div>
        )}

        {dest === "memory" && (
          <div className="jg-content jg-workspace-page">
            <div className="jg-card">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                <h3 style={{ margin: 0 }}>Memory 2.0 Learning Inspector (Cascading Forget)</h3>
                <input
                  className="jg-input"
                  style={{ maxWidth: 260 }}
                  placeholder="Recall search..."
                  value={learningQuery}
                  onChange={async (e) => {
                    const q = e.target.value;
                    setLearningQuery(q);
                    const r = await fetch(`${baseUrl}/v1/memory/learning?q=${encodeURIComponent(q)}`);
                    if (r.ok) setLearning((await r.json()).entries ?? []);
                  }}
                />
              </div>
              <div style={{ marginTop: 10 }}>
                {learning.length === 0 ? (
                  <div className="jg-muted">No learned memories matched.</div>
                ) : (
                  learning.map((entry) => (
                    <div key={entry.entry_id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 0", borderBottom: "1px solid var(--jg-border-subtle)", gap: 10 }}>
                      <div>
                        <span className="jg-pill">{entry.scope}</span>{" "}
                        <span>{entry.content}</span>
                      </div>
                      <button
                        type="button"
                        className="jg-btn-ghost"
                        onClick={async () => {
                          await fetch(`${baseUrl}/v1/memory/learning/${encodeURIComponent(entry.entry_id)}?cascade=true`, { method: "DELETE" });
                          setLearning((prev) => prev.filter((x) => x.entry_id !== entry.entry_id));
                        }}
                      >
                        Forget
                      </button>
                    </div>
                  ))
                )}
              </div>
            </div>

            <form
              className="jg-card"
              style={{ display: "flex", gap: 8 }}
              onSubmit={async (e) => {
                e.preventDefault();
                if (!factKey.trim()) return;
                await fetch(`${baseUrl}/v1/memory/facts`, {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ key: factKey.trim(), value: factVal.trim() }),
                });
                setFactKey("");
                setFactVal("");
                const r = await fetch(`${baseUrl}/v1/memory/facts`);
                if (r.ok) setFacts((await r.json()).facts ?? []);
              }}
            >
              <input className="jg-input" placeholder="Fact key" value={factKey} onChange={(e) => setFactKey(e.target.value)} />
              <input className="jg-input" placeholder="Fact value" value={factVal} onChange={(e) => setFactVal(e.target.value)} />
              <button type="submit" className="jg-btn jg-btn-primary">Remember</button>
            </form>
            {facts.map((f) => (
              <div key={`${f.subject}:${f.key}`} className="jg-card" style={{ display: "flex", justifyContent: "space-between" }}>
                <span><strong>{f.key}</strong>: {f.value}</span>
                <span className="jg-pill">{f.subject}</span>
              </div>
            ))}
          </div>
        )}

        {dest === "settings" && (
          <SettingsWorkspace baseUrl={baseUrl} sessionId={activeSessionId} panels={{
            General: (<div className="jg-card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <h3 style={{ margin: 0 }}>32 GB Apple Silicon Governor & Body Controls</h3>
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
                <span className="jg-pill">Host: {resources.host_available_gb ?? "?"} / {resources.host_total_gb ?? 32} GB free</span>
                <span className="jg-pill">Idle Minecraft: {resources.idle_life_status ?? "ready"}</span>
                <span className="jg-pill">Cognitive Mode: {liveCogMode}</span>
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <button type="button" className="jg-btn" onClick={() => void toggleIdleLife()}>
                  {resources.idle_life_enabled ? "Pause Idle Minecraft Life" : "Allow Idle Minecraft Life"}
                </button>
                <button
                  type="button"
                  className={`jg-btn ${resources.estop_active ? "jg-btn-danger" : ""}`}
                  onClick={() => void toggleEstop()}
                >
                  {resources.estop_active ? "Release Emergency Stop" : "Trigger Emergency Stop"}
                </button>
              </div>
            </div>),
            Profile: (<div className="jg-card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <h3 style={{ margin: 0 }}>Digital Counterpart Identity (User-Owned)</h3>
              <form
                style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}
                onSubmit={async (e) => {
                  e.preventDefault();
                  const r = await fetch(`${baseUrl}/v1/identity`, {
                    method: "PUT",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ ai_name: idAiName.trim() || "Jaeger", owner_name: idOwnerName.trim() || "Owner" }),
                  });
                  if (r.ok) {
                    const d = await r.json();
                    setIdentity(d.identity ?? {});
                    setIdSavedMsg(`Saved (${d.identity?.ai_name} · ${d.identity?.owner_name})`);
                  }
                }}
              >
                <input className="jg-input" style={{ maxWidth: 200 }} placeholder="AI Name (e.g. ARES)" value={idAiName} onChange={(e) => setIdAiName(e.target.value)} />
                <input className="jg-input" style={{ maxWidth: 200 }} placeholder="Owner Name" value={idOwnerName} onChange={(e) => setIdOwnerName(e.target.value)} />
                <button type="submit" className="jg-btn jg-btn-primary">Save Identity</button>
                <button type="button" className="jg-btn" onClick={() => setAwakeningOpen(true)}>Run Day-1 Setup Wizard</button>
                {identity.active_character_id && <span className="jg-pill">Character: {identity.active_character_id}</span>}
                {idSavedMsg && <span className="jg-muted">{idSavedMsg}</span>}
              </form>
            </div>),
            Avatar: (<div className="jg-card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <h3 style={{ margin: 0 }}>VR Avatar Studio (VRM 0.x / 1.0, GLB, 2D Character)</h3>
              <p className="jg-muted" style={{ margin: 0 }}>
                Upload a <code>.vrm</code>, <code>.glb</code>, or 2D character portrait. 3D VRM models automatically use studio 3-point lighting, relaxed stance, auto-blink, eye-tracking saccades, and Kokoro lip-sync.
              </p>
              <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                <input
                  type="file"
                  accept=".vrm,.glb,.png,.webp,.jpg,.jpeg"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) void handleAvatarUpload(f);
                  }}
                />
                <button type="button" className="jg-btn" onClick={() => void triggerAvatarVisemeTest()}>
                  Test Kokoro Viseme Sync
                </button>
                {avatarUploadMsg && <span className="jg-muted">{avatarUploadMsg}</span>}
              </div>
            </div>),
            Appearance: <div className="jg-card jg-settings-row"><label htmlFor="jg-settings-theme">Color theme</label>
              <select className="jg-input" id="jg-settings-theme" value={theme} onChange={e => setMode(e.target.value === "dark" ? "Dark" : "Light")}>
                <option value="light">Light</option><option value="dark">Dark</option>
              </select></div>,
            Models: modelPanel,
            Connections: <div className="jg-card jg-settings-row"><span>Connected tools and MCP servers</span>
              <button type="button" className="jg-btn" onClick={() => setDest("integrations")}>Manage connections</button></div>,
          }} />
        )}

        {dest === "models" && (
          <div className="jg-content jg-workspace-page">
            {modelPanel}
          </div>
        )}

      </main>

      <aside
        id="jg-right-sidebar"
        className="jg-ushell__right"
        aria-label="Workspace inspector"
        hidden={!rightSidebarOpen}
      >
        <div className="jg-tabs-inline" role="tablist" aria-label="Right sidebar panels">
          <button
            type="button"
            role="tab"
            aria-selected={rightSidebarTab === "inspector"}
            data-active={rightSidebarTab === "inspector"}
            onClick={() => setRightSidebarTab("inspector")}
          >
            Inspector
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={rightSidebarTab === "avatar"}
            data-active={rightSidebarTab === "avatar"}
            onClick={() => setRightSidebarTab("avatar")}
          >
            Avatar
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={rightSidebarTab === "mind"}
            data-active={rightSidebarTab === "mind"}
            onClick={() => setRightSidebarTab("mind")}
          >
            Mind
          </button>
        </div>

        {rightSidebarTab === "inspector" && (
          <div className="jg-right-inspector">
            <label className="jg-ushell__search">
              <svg width="14" height="14" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
                <circle cx="8" cy="8" r="5" />
                <path d="M12 12l3.5 3.5" strokeLinecap="round" />
              </svg>
              <input
                type="search"
                aria-label="Search tabs, tools, tasks and more"
                placeholder="Search tabs, tools, tasks and more"
                value={rightSearch}
                onChange={(event) => setRightSearch(event.target.value)}
              />
            </label>

            {matchingDestinations.length > 0 && (
              <div className="jg-right-section">
                <div className="jg-right-section-head">
                  <span>Matching Tabs</span>
                  <span className="jg-pill">{matchingDestinations.length}</span>
                </div>
                <div className="jg-right-list">
                  {matchingDestinations.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      className="jg-ushell__row"
                      onClick={() => {
                        setDest(item.id);
                        setRightSearch("");
                      }}
                    >
                      <span>{item.label}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            <div className="jg-right-section">
              <button
                type="button"
                className="jg-right-action"
                aria-expanded={sideQuestionOpen}
                onClick={() => setSideQuestionOpen((open) => !open)}
              >
                <svg width="15" height="15" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
                  <path d="M3 4.5A1.5 1.5 0 0 1 4.5 3h9A1.5 1.5 0 0 1 15 4.5v6A1.5 1.5 0 0 1 13.5 12H7l-3 2.5V12H4.5A1.5 1.5 0 0 1 3 10.5v-6Z" />
                </svg>
                <span>Side Question</span>
              </button>
              {sideQuestionOpen && (
                <form
                  className="jg-right-side-question"
                  onSubmit={(event) => {
                    event.preventDefault();
                    const text = sideQuestionDraft.trim();
                    if (!text) return;
                    setDest("chat");
                    setSideQuestionDraft("");
                    setSideQuestionOpen(false);
                    void sendPrompt(text);
                  }}
                >
                  <input
                    className="jg-input"
                    aria-label="Ask a side question"
                    placeholder="Ask Jaeger a quick side question…"
                    value={sideQuestionDraft}
                    onChange={(event) => setSideQuestionDraft(event.target.value)}
                  />
                  <button
                    type="submit"
                    className="jg-btn jg-btn-primary"
                    disabled={!sideQuestionDraft.trim() || sending || historyState !== "ready"}
                  >
                    Ask
                  </button>
                </form>
              )}
            </div>

            <div className="jg-right-section">
              <div className="jg-right-section-head">
                <span>Background Tasks</span>
                <span className="jg-pill">{backgroundTaskCount}</span>
              </div>
              <div className="jg-right-list">
                {sending && (
                  <button
                    type="button"
                    className="jg-right-task-row"
                    onClick={() => {
                      setDest("chat");
                      jumpToLatest();
                    }}
                  >
                    <span className="jg-right-task-icon is-running" aria-hidden="true" />
                    <span className="jg-right-task-name">Active conversation turn ({runStatus})</span>
                  </button>
                )}
                {filteredWorkflows.map((wf) => (
                  <button
                    key={wf.run_id}
                    type="button"
                    className="jg-right-task-row"
                    onClick={() => setDest("tasks")}
                  >
                    <span className="jg-right-task-icon" aria-hidden="true" />
                    <span className="jg-right-task-name">{wf.name}</span>
                    <span className="jg-pill">{wf.status}</span>
                  </button>
                ))}
                {filteredToolTasks.map((task) => (
                  <button
                    key={task.id}
                    type="button"
                    className="jg-right-task-row"
                    onClick={() => {
                      setDest("chat");
                      if (task.recordId !== undefined) jumpToTopic(task.recordId);
                    }}
                  >
                    <span
                      className={`jg-right-task-icon ${task.status === "running" ? "is-running" : ""}`}
                      aria-hidden="true"
                    />
                    <span className="jg-right-task-name">{task.toolName}</span>
                    <span className="jg-muted">
                      {task.durationMs !== undefined ? `${task.durationMs}ms` : task.status}
                    </span>
                  </button>
                ))}
                {backgroundTaskCount === 0 && (
                  <p className="jg-muted" style={{ margin: "4px 6px" }}>
                    {rightQuery ? "No matching background tasks." : "No recent background tasks yet."}
                  </p>
                )}
              </div>
            </div>

            <div className="jg-card jg-right-summary">
              <div className="jg-right-summary-row">
                <span className="jg-muted">Model</span>
                <strong>{health.model || activeModel || "—"}</strong>
              </div>
              <div className="jg-right-summary-row">
                <span className="jg-muted">Memory</span>
                <strong>
                  {resources.host_available_gb !== undefined && resources.host_total_gb !== undefined
                    ? `${resources.host_available_gb.toFixed(1)}/${resources.host_total_gb.toFixed(0)} GB free`
                    : "—"}
                </strong>
              </div>
              <div className="jg-right-summary-row">
                <span className="jg-muted">Mind Loop</span>
                <strong>{liveCogMode}</strong>
              </div>
              <div className="jg-right-summary-row">
                <span className="jg-muted">Droid</span>
                <button type="button" className="jg-btn-ghost" onClick={() => setDest("droid")}>
                  {droidSleeping ? "Asleep (Parked)" : "Awake"}
                </button>
              </div>
            </div>
          </div>
        )}

        {rightSidebarTab === "avatar" && (
          <>
            <label>
              Character
              <select
                className="jg-input"
                value={characterId}
                disabled={!identityLoaded || characterPending}
                onChange={(event) => void selectCharacter(event.target.value)}
              >
                <option value="">Default identity</option>
                {characters.map((character) => (
                  <option key={character.character_id} value={character.character_id}>{characterLabel(character)}</option>
                ))}
              </select>
            </label>
            {characterError && <div role="alert">{characterError}</div>}
            <AvatarStage
              name={activeCharacter?.name || avatarRec.avatar?.display_name || "Jaeger"}
              mode={avatarMode}
              modelUrl={avatarModelUrl}
              imageUrl={characterPortrait || avatarImageUrl}
              videoUrl={truthClip}
              emotion={liveEmotion}
              cognitiveMode={liveCogMode}
              focusText={cognition.focus || "Aware & standing by"}
              amplitude={avatarRec.live?.amplitude ?? 0}
              visemes={visemes}
            />
            <div className="jg-card" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <strong style={{ fontSize: 12.5 }}>Expression & Lip-Sync</strong>
                <button type="button" className="jg-btn-ghost" onClick={() => void triggerAvatarVisemeTest()}>
                  Test Lip-Sync
                </button>
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                {EMOTION_OPTIONS.map((em) => (
                  <button
                    key={em}
                    type="button"
                    className="jg-btn-ghost"
                    onClick={() => void setAvatarEmotion(em)}
                  >
                    {em}
                  </button>
                ))}
              </div>
            </div>
          </>
        )}

        {rightSidebarTab === "mind" && (
          <MindAutonomyPanel
            baseUrl={baseUrl}
            liveCogMode={liveCogMode}
            focusText={cognition.focus || "Observing"}
            tickCount={cognition.tick_count ?? 0}
            idleLifeStatus={resources.idle_life_status || "ready"}
            preemptionCount={resources.preemption_count ?? 0}
            estopActive={Boolean(resources.estop_active)}
            onOpenTasks={() => setDest("tasks")}
            onOpenGoals={() => setDest("goals")}
          />
        )}
      </aside>
    </div>
  );
}
