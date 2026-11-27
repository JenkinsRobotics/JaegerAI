import { useEffect, useMemo, useRef, useState } from "react";
import type { ApprovalPart, ChatMessage, SessionSummary } from "@jaeger/ui-protocol";
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
import { JAEGER_DESTINATIONS, type DestinationId } from "./destinations";

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

interface ToolRow {
  name: string;
  description: string;
  tier: string;
  read_only: boolean;
  source: string;
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

const BUSINESS_TEAM_ROLES = [
  { id: "producer", title: "Channel Producer", focus: "Owns multi-day YouTube & business schedules, delegates tasks, enforces approval gates." },
  { id: "researcher", title: "Research & Trends Analyst", focus: "Runs phased on-device YouTube playlist research, OCR, audience & competitor briefs." },
  { id: "writer", title: "Script & Copywriter", focus: "Drafts retention-first hooks, scripts, descriptions, newsletters, and sponsor outreach." },
  { id: "designer", title: "Visual & Thumbnail Designer", focus: "Creates storyboard frames, thumbnail concepts, and Aether-styled studio graphics." },
  { id: "engineer", title: "Software & Droid Engineer", focus: "Writes verified code edits via Aider fuzzy tools, tests, and JP01 / Minecraft embodiment." },
  { id: "ops", title: "Business Ops & Channels", focus: "Manages Mail, Calendar, iMessage/Telegram relays, MCP integrations, and analytics." },
];

const DEFAULT_STUDIO_CLIPS: StudioClip[] = [
  { id: "c1", track: "video", label: "Hook · JP01 Droid Live Demo", startSec: 0, durationSec: 22, status: "ready" },
  { id: "c2", track: "video", label: "Build Breakdown · 32GB Local Stack", startSec: 24, durationSec: 78, status: "ready" },
  { id: "c3", track: "video", label: "Minecraft Idle Persistence Demo", startSec: 105, durationSec: 55, status: "needs_review" },
  { id: "c4", track: "broll", label: "Thumbnail A/B + Architecture Diagram", startSec: 14, durationSec: 40, status: "ready" },
  { id: "c5", track: "voice", label: "Kokoro MLX Narration Track", startSec: 0, durationSec: 162, status: "ready" },
  { id: "c6", track: "captions", label: "Whisper Auto-Synced Captions", startSec: 0, durationSec: 162, status: "ready" },
];

const EMOTION_OPTIONS = ["warm", "focused", "happy", "curious", "calm", "concerned", "surprised"];

function NavIcon({ id }: { id: DestinationId }) {
  const paths: Record<DestinationId, string> = {
    chat: "M2.5 4A1.5 1.5 0 0 1 4 2.5h8A1.5 1.5 0 0 1 13.5 4v6A1.5 1.5 0 0 1 12 11.5H6l-3 2.5v-2.5A1.5 1.5 0 0 1 2.5 10V4Z",
    tasks: "M3 4.5h10M3 8h10M3 11.5h6",
    tools: "M10.5 2.5a3 3 0 0 0-3.7 3.7L2.5 10.5a1.4 1.4 0 1 0 2 2l4.3-4.3a3 3 0 0 0 3.7-3.7L11 6l-1-1 1.5-1.5Z",
    memory: "M8 2.5c2.8 0 5 1 5 2.3v6.4c0 1.3-2.2 2.3-5 2.3s-5-1-5-2.3V4.8c0-1.3 2.2-2.3 5-2.3Z",
    settings: "M8 5.2A2.8 2.8 0 1 0 8 10.8 2.8 2.8 0 0 0 8 5.2ZM2.5 8h1.4m8.2 0h1.4M8 2.5v1.4m0 8.2v1.4",
  };
  return (
    <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d={paths[id]} stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export interface JaegerAppProps {
  baseUrl?: string;
}

export function JaegerApp({ baseUrl = "" }: JaegerAppProps) {
  const [dest, setDest] = useState<DestinationId>("chat");
  const [theme, setTheme] = useState<"light" | "dark">(() =>
    typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light",
  );
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [watchOpen, setWatchOpen] = useState(true);
  const [watchTab, setWatchTab] = useState<"avatar" | "mind" | "artifacts">("avatar");

  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string>("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [prompt, setPrompt] = useState("");
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

  const [tools, setTools] = useState<ToolRow[]>([]);
  const [skills, setSkills] = useState<SkillRow[]>([]);
  const [mcpServers, setMcpServers] = useState<McpServerRow[]>([]);
  const [workflows, setWorkflows] = useState<WorkflowRow[]>([]);
  const [episodes, setEpisodes] = useState<Array<{ episode_id: string; title: string; stage: string; assigned_role: string; owner_approved: boolean; timeline_clips: StudioClip[] }>>([]);
  const [newEpTitle, setNewEpTitle] = useState("");
  const [teamRoles, setTeamRoles] = useState<Array<{ role_id: string; title: string; mission: string; default_model: string }>>([]);
  const [budgets, setBudgets] = useState<{ daily_cap_usd?: number; daily_spent_usd?: number; daily_remaining_usd?: number }>({});
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
  const [avatarUploadMsg, setAvatarUploadMsg] = useState("");
  const [identity, setIdentity] = useState<{ ai_name?: string; owner_name?: string; mission?: string; active_character_id?: string | null }>({});
  const [idAiName, setIdAiName] = useState("");
  const [idOwnerName, setIdOwnerName] = useState("");
  const [idSavedMsg, setIdSavedMsg] = useState("");
  const [droidDevices, setDroidDevices] = useState<{ gimbal_camera?: { name: string } | null; cameras?: Array<{ name: string }>; microphones?: Array<{ name: string }>; speakers?: Array<{ name: string }> }>({});
  const [droidPose, setDroidPose] = useState<{ pan_deg?: number; tilt_deg?: number; zoom?: number }>({});
  const [droidStatusMsg, setDroidStatusMsg] = useState("");
  const [mcpNewName, setMcpNewName] = useState("");
  const [mcpNewUrl, setMcpNewUrl] = useState("");
  const [mediaArchive, setMediaArchive] = useState<Array<{ asset_id: string; kind: string; scene_description: string; source_path: string; is_reconstructed: boolean }>>([]);

  const transportRef = useRef<HttpSseTransport | null>(null);
  const storeRef = useRef<SessionStore | null>(null);
  const scrollMachineRef = useRef(new ScrollFollowMachine());
  const scrollEndRef = useRef<HTMLDivElement | null>(null);
  const [showJump, setShowJump] = useState(false);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((v) => !v);
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

  const refreshSessions = async () => {
    const primaryResponse = !activeSessionId
      ? await fetch(`${baseUrl}/v1/chat/session`).catch(() => null)
      : null;
    const primary = primaryResponse?.ok
      ? (await primaryResponse.json() as { session?: SessionSummary }).session
      : undefined;
    if (primary) setActiveSessionId((current) => current || primary.session_id);
    const res = await fetch(`${baseUrl}/v1/sessions`).catch(() => null);
    if (!res?.ok) return;
    const data = (await res.json()) as { sessions?: SessionSummary[] };
    const rows = data.sessions ?? [];
    setSessions(rows);
    if (!primary && rows.length > 0) setActiveSessionId((current) => current || rows[0].session_id);
  };

  const createNewSession = async () => {
    const res = await fetch(`${baseUrl}/v1/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: "New Conversation" }),
    });
    if (!res.ok) return;
    const data = (await res.json()) as { session: SessionSummary };
    setSessions((prev) => [data.session, ...prev]);
    setActiveSessionId(data.session.session_id);
    setDest("chat");
  };

  useEffect(() => {
    void refreshSessions();
    void refreshSystem();
    const id = window.setInterval(() => void refreshSystem(), 12000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    if (!activeSessionId || !transportRef.current) return;
    storeRef.current?.dispose();
    const store = new SessionStore(activeSessionId, transportRef.current);
    storeRef.current = store;
    const unsub = store.subscribe(() => {
      const snap = store.getSnapshot();
      setMessages(snap.messages);
      setRunStatus(snap.status);
      if (scrollMachineRef.current.shouldAutoScroll) {
        scrollEndRef.current?.scrollIntoView({ behavior: "smooth" });
      }
    });
    const ac = new AbortController();
    void fetch(`${baseUrl}/v1/sessions/${encodeURIComponent(activeSessionId)}/messages`, { signal: ac.signal })
      .then((r) => (r.ok ? r.json() : { messages: [] }))
      .then((d: { messages?: Array<{ id?: number; role: string; content: string; created_at?: number }> }) => {
        const hist: ChatMessage[] = (d.messages ?? []).map((m, idx) => ({
          id: `hist_${m.id ?? idx}`,
          session_id: activeSessionId,
          role: m.role === "user" ? "user" : "assistant",
          content: m.content,
          parts: [{ type: "text", text: m.content }],
          created_at: m.created_at ?? Date.now(),
        }));
        if (hist.length > 0 && store.getSnapshot().messages.length === 0) {
          setMessages(hist);
        }
      })
      .catch(() => {});
    void transportRef.current
      .subscribe(activeSessionId, 0, (ev) => store.applyEvent(ev), ac.signal)
      .catch(() => {});
    return () => {
      ac.abort();
      unsub();
      store.dispose();
    };
  }, [activeSessionId, baseUrl]);

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

  useEffect(() => {
    if (dest === "tools") {
      void fetchJson(`${baseUrl}/v1/tools`).then((d) => setTools(d.tools ?? []));
      void fetchJson(`${baseUrl}/v1/skills`).then((d) => setSkills(d.skills ?? []));
      void fetchJson(`${baseUrl}/v1/mcp/servers`).then((d) => setMcpServers(d.servers ?? []));
      void fetchJson(`${baseUrl}/v1/business/team`).then((d) => {
        if (Array.isArray(d.team) && d.team.length > 0) setTeamRoles(d.team);
        if (d.budgets) setBudgets(d.budgets);
      });
    } else if (dest === "tasks") {
      void fetchJson(`${baseUrl}/v1/workflows`).then((d) => setWorkflows(d.workflows ?? []));
      void fetchJson(`${baseUrl}/v1/youtube/episodes`).then((d) => setEpisodes(d.episodes ?? []));
      void fetchJson(`${baseUrl}/v1/media/archive`).then((d) => setMediaArchive(d.items ?? []));
    } else if (dest === "memory") {
      void fetchJson(`${baseUrl}/v1/memory/facts`).then((d) => setFacts(d.facts ?? []));
      void fetchJson(`${baseUrl}/v1/memory/learning`).then((d) => setLearning(d.entries ?? []));
      void fetchJson(`${baseUrl}/v1/memory/goals`).then((d) => setGoals(d.goals ?? []));
    } else if (dest === "settings") {
      void fetchJson(`${baseUrl}/v1/models`).then((d) => {
        setModels(d.models ?? []);
        setActiveModel(d.active ?? "");
      });
      void fetchJson(`${baseUrl}/v1/identity`).then((d) => {
        if (d.identity) {
          setIdentity(d.identity);
          setIdAiName(d.identity.ai_name ?? "Jaeger");
          setIdOwnerName(d.identity.owner_name ?? "Owner");
        }
      });
      void fetchJson(`${baseUrl}/v1/droid/devices?refresh=1`).then((d) => {
        if (d.devices) setDroidDevices(d.devices);
      });
      void fetchJson(`${baseUrl}/v1/embodiment/status`).then((d) => {
        if (d.droid?.pose) setDroidPose(d.droid.pose);
      });
      void refreshSystem();
    }
  }, [dest, baseUrl]);

  const sendPrompt = async () => {
    const text = prompt.trim();
    if (!text) return;
    let sid = activeSessionId;
    if (!sid) {
      const res = await fetch(`${baseUrl}/v1/sessions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: text.slice(0, 48) }),
      });
      if (!res.ok) return;
      const data = (await res.json()) as { session: SessionSummary };
      sid = data.session.session_id;
      setSessions((prev) => [data.session, ...prev]);
      setActiveSessionId(sid);
    }
    setPrompt("");
    if (storeRef.current) {
      await storeRef.current.sendPrompt(text);
    } else {
      await fetch(`${baseUrl}/v1/sessions/${encodeURIComponent(sid)}/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: text }),
      });
    }
    void refreshSystem();
  };

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

  const paletteCommands: CommandItem[] = useMemo(
    () => [
      ...JAEGER_DESTINATIONS.map((d) => ({
        id: `nav:${d.id}`,
        label: `Open ${d.label}`,
        group: "Navigate",
        onSelect: () => setDest(d.id),
      })),
      { id: "act:new-chat", label: "New Conversation", group: "Action", onSelect: () => void createNewSession() },
      { id: "act:watch", label: watchOpen ? "Hide Live Watch & VR Avatar" : "Show Live Watch & VR Avatar", group: "View", onSelect: () => setWatchOpen((v) => !v) },
      { id: "act:theme", label: `Switch to ${theme === "dark" ? "Light" : "Dark"} Theme`, group: "View", onSelect: () => setTheme((t) => (t === "dark" ? "light" : "dark")) },
      { id: "act:idle", label: resources.idle_life_enabled ? "Pause Idle Minecraft Life" : "Enable Idle Minecraft Life", group: "Body", onSelect: () => void toggleIdleLife() },
      { id: "act:estop", label: resources.estop_active ? "Release Emergency Stop" : "Trigger Emergency Stop (E-Stop)", group: "Safety", onSelect: () => void toggleEstop() },
    ],
    [watchOpen, theme, resources.idle_life_enabled, resources.estop_active],
  );

  const avatarMode = avatarRec.avatar?.mode ?? "2d_character";
  const avatarModelUrl = avatarRec.asset?.format === "vrm" || avatarRec.asset?.format === "glb" ? `${baseUrl}${avatarRec.asset.uri}` : null;
  const avatarImageUrl = avatarRec.asset?.format === "image" ? `${baseUrl}${avatarRec.asset.uri}` : null;
  const liveEmotion = avatarRec.live?.emotion || cognition.emotion || "warm";
  const liveCogMode = resources.estop_active ? "estop" : cognition.mode || "observing";

  return (
    <div className="jg-app" data-testid="jaeger-modular-app">
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} items={paletteCommands} />

      <aside className="jg-sidebar">
        <div className="jg-brand">
          <span>Jaeger Modular</span>
          <span className="jg-pill">{health.all_green === false ? "Degraded" : "Live"}</span>
        </div>

        <button type="button" className="jg-btn" onClick={() => setPaletteOpen(true)}>
          Quick Command <kbd className="jg-kbd">⌘K</kbd>
        </button>

        <nav className="jg-nav" aria-label="Primary navigation">
          {JAEGER_DESTINATIONS.map((item) => (
            <button
              key={item.id}
              type="button"
              className="jg-nav-btn"
              data-active={dest === item.id}
              onClick={() => setDest(item.id)}
            >
              <NavIcon id={item.id} />
              <span>{item.label}</span>
            </button>
          ))}
        </nav>

        <div style={{ marginTop: 6, display: "flex", flexDirection: "column", gap: 6 }}>
          <button type="button" className="jg-btn jg-btn-primary" onClick={() => void createNewSession()}>
            + New Chat
          </button>
          <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
            {sessions.slice(0, 8).map((s) => (
              <button
                key={s.session_id}
                type="button"
                className="jg-nav-btn"
                data-active={dest === "chat" && activeSessionId === s.session_id}
                onClick={() => {
                  setActiveSessionId(s.session_id);
                  setDest("chat");
                }}
              >
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {s.title || s.session_id}
                </span>
              </button>
            ))}
          </div>
        </div>
      </aside>

      <main className="jg-main">
        <header className="jg-header">
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <strong>{JAEGER_DESTINATIONS.find((d) => d.id === dest)?.label}</strong>
            <span className="jg-pill">{health.model || activeModel || "modular"}</span>
            {resources.host_available_gb !== undefined && (
              <span className="jg-pill">
                {resources.host_available_gb.toFixed(1)}/{resources.host_total_gb?.toFixed(0)} GB free
              </span>
            )}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <button type="button" className="jg-btn" onClick={() => setWatchOpen((v) => !v)}>
              {watchOpen ? "Hide Avatar" : "Show Avatar"}
            </button>
            <button
              type="button"
              className={`jg-btn ${resources.estop_active ? "jg-btn-danger" : ""}`}
              onClick={() => void toggleEstop()}
            >
              {resources.estop_active ? "E-STOP ON" : "E-Stop"}
            </button>
            <button type="button" className="jg-btn" onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}>
              {theme === "dark" ? "Light" : "Dark"}
            </button>
          </div>
        </header>

        {dest === "chat" && (
          <div className={`jg-workspace-split ${watchOpen ? "" : "is-drawer-closed"}`}>
            <div className="jg-chat-column">
              <div
                className="jg-content"
                onScroll={(e) => {
                  const el = e.currentTarget;
                  const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
                  scrollMachineRef.current.transition(nearBottom ? { type: "REACHED_BOTTOM" } : { type: "USER_SCROLL_UP" });
                  setShowJump(!nearBottom);
                }}
              >
                {approvalError && <p role="alert">{approvalError}</p>}
                {scheduleApprovals?.sessionId === activeSessionId && scheduleApprovals.items.map((approval) => (
                  <ApprovalCard key={approval.approvalId} approval={approval} onDecision={handleApproval} disabled={decidingApproval !== undefined} />
                ))}
                {messages.length === 0 ? (
                  <div className="jg-card" style={{ maxWidth: 680, margin: "28px auto" }}>
                    <h3 style={{ marginTop: 0 }}>Jaeger Command Center</h3>
                    <p style={{ color: "var(--jg-text-secondary)", marginBottom: 0 }}>
                      Conversation is an interface to your persistent AI mind. Ask Jaeger to run YouTube research, edit code,
                      manage your business team, or check on its autonomous world state — all under your 32 GB resource budget.
                    </p>
                  </div>
                ) : (
                  messages.map((m) => (
                    <article key={m.id} className="jg-msg" data-role={m.role}>
                      <div style={{ fontSize: 11, fontWeight: 600, color: "var(--jg-text-muted)", marginBottom: 6 }}>
                        {m.role === "user" ? "You" : "Jaeger"}
                      </div>
                      {m.parts.map((part, idx) => {
                        if (part.type === "thinking") return <ThinkingDisclosure key={idx} part={part} />;
                        if (part.type === "tool") return <ToolCallCard key={idx} part={part} />;
                        if (part.type === "approval") {
                          return <ApprovalCard key={idx} approval={part} onDecision={handleApproval} />;
                        }
                        return <StreamingMarkdown key={idx} text={part.text} streaming={runStatus === "running"} />;
                      })}
                    </article>
                  ))
                )}
                <div ref={scrollEndRef} />
                {showJump && (
                  <button
                    type="button"
                    className="jg-btn jg-btn-primary"
                    style={{ position: "sticky", bottom: 12, float: "right" }}
                    onClick={() => {
                      scrollMachineRef.current.transition({ type: "JUMP_REQUESTED" });
                      scrollEndRef.current?.scrollIntoView({ behavior: "smooth" });
                      setShowJump(false);
                    }}
                  >
                    Jump to Latest
                  </button>
                )}
              </div>

              <ContextXrayBar
                usedTokens={estTokens}
                maxTokens={32768}
                hostTotalGb={resources.host_total_gb}
                hostAvailableGb={resources.host_available_gb}
                activeModel={health.model || activeModel}
              />

              <form
                className="jg-composer"
                onSubmit={(e) => {
                  e.preventDefault();
                  void sendPrompt();
                }}
              >
                <input
                  className="jg-input"
                  value={prompt}
                  placeholder="Command Jaeger or your business team... (Cmd+K for quick actions)"
                  onChange={(e) => setPrompt(e.target.value)}
                />
                <button type="submit" className="jg-btn jg-btn-primary" disabled={!prompt.trim() || runStatus === "running"}>
                  {runStatus === "running" ? "Running..." : "Send"}
                </button>
              </form>
            </div>

            {watchOpen && (
              <aside className="jg-watch-drawer" aria-label="Live Watch & VR Avatar">
                <div className="jg-tabs-inline">
                  <button type="button" data-active={watchTab === "avatar"} onClick={() => setWatchTab("avatar")}>
                    VR Avatar
                  </button>
                  <button type="button" data-active={watchTab === "mind"} onClick={() => setWatchTab("mind")}>
                    Live Mind
                  </button>
                  <button type="button" data-active={watchTab === "artifacts"} onClick={() => setWatchTab("artifacts")}>
                    Watch
                  </button>
                </div>

                {watchTab === "avatar" && (
                  <>
                    <AvatarStage
                      name={avatarRec.avatar?.display_name || "Jaeger"}
                      mode={avatarMode}
                      modelUrl={avatarModelUrl}
                      imageUrl={avatarImageUrl}
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

                {watchTab === "mind" && (
                  <div className="jg-card" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    <strong style={{ fontSize: 13 }}>24/7 Cognitive Life Loop</strong>
                    <div className="jg-muted">Mode: <strong>{liveCogMode}</strong></div>
                    <div className="jg-muted">Focus: {cognition.focus || "Observing"}</div>
                    <div className="jg-muted">Autonomous Ticks: {cognition.tick_count ?? 0}</div>
                    <div className="jg-muted">Idle Minecraft: {resources.idle_life_status || "ready"}</div>
                    <div className="jg-muted">Preemptions (Owner-First): {resources.preemption_count ?? 0}</div>
                  </div>
                )}

                {watchTab === "artifacts" && (
                  <div className="jg-card" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    <strong style={{ fontSize: 13 }}>Embodiment & Session Watch</strong>
                    <p className="jg-muted" style={{ margin: 0 }}>
                      Switch here to monitor active YouTube renders, live browser pages, or headless Minecraft checkpoints.
                    </p>
                    <button type="button" className="jg-btn" onClick={() => setDest("tasks")}>
                      Open YouTube Studio Timeline
                    </button>
                    <button type="button" className="jg-btn" onClick={() => setDest("memory")}>
                      Inspect Multi-Day Goals
                    </button>
                  </div>
                )}
              </aside>
            )}
          </div>
        )}

        {dest === "tasks" && (
          <div className="jg-content" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <StudioTimeline
              projectTitle={episodes[0] ? `YouTube Studio · ${episodes[0].title}` : "YouTube Channel Studio · Episode 01"}
              clips={episodes[0]?.timeline_clips?.length ? episodes[0].timeline_clips : DEFAULT_STUDIO_CLIPS}
              onDryRun={() => void runSafeDryRun()}
              dryRunBusy={dryRunBusy}
            />
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
                    <div className="jg-muted">Stage: {ep.stage} · Lead: {ep.assigned_role} · Clips: {ep.timeline_clips.length}</div>
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
                mediaArchive.slice(0, 8).map((item) => (
                  <div key={item.asset_id} style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", borderTop: "1px solid var(--jg-border-subtle)" }}>
                    <span><strong>[{item.kind}]</strong> {item.scene_description || item.source_path}</span>
                    <span className="jg-pill">{item.is_reconstructed ? "Reconstructed" : "Genuine"}</span>
                  </div>
                ))
              )}
            </div>
            {dryRunResult && (
              <div className="jg-card">
                <strong>Safe-Mode Dry-Run Result:</strong> <span className="jg-muted">{dryRunResult}</span>
              </div>
            )}
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

        {dest === "tools" && (
          <div className="jg-content" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                <h3 style={{ margin: 0 }}>Autonomous Business Team Roles</h3>
                {budgets.daily_cap_usd !== undefined && (
                  <span className="jg-pill">
                    Daily Budget: ${budgets.daily_spent_usd?.toFixed(2) ?? "0.00"} / ${budgets.daily_cap_usd.toFixed(2)}
                  </span>
                )}
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(250px, 1fr))", gap: 10 }}>
                {(teamRoles.length > 0
                  ? teamRoles.map((r) => ({ id: r.role_id, title: r.title, focus: r.mission, badge: r.default_model }))
                  : BUSINESS_TEAM_ROLES.map((r) => ({ id: r.id, title: r.title, focus: r.focus, badge: "Ready" }))
                ).map((role) => (
                  <div key={role.id} className="jg-card">
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <strong>{role.title}</strong>
                      <span className="jg-pill">{role.badge}</span>
                    </div>
                    <p className="jg-muted" style={{ marginBottom: 0 }}>{role.focus}</p>
                  </div>
                ))}
              </div>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
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

            <div>
              <h4>Registered Modular Tools ({tools.length})</h4>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(250px, 1fr))", gap: 10 }}>
                {tools.map((t) => (
                  <div key={t.name} className="jg-card">
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 6 }}>
                      <strong>{t.name}</strong>
                      <span className="jg-pill">{t.read_only ? "read-only" : t.tier}</span>
                    </div>
                    <p className="jg-muted" style={{ marginBottom: 0 }}>{t.description}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {dest === "memory" && (
          <div className="jg-content" style={{ display: "flex", flexDirection: "column", gap: 14, maxWidth: 900 }}>
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
          <div className="jg-content" style={{ display: "flex", flexDirection: "column", gap: 14, maxWidth: 820 }}>
            <div className="jg-card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
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
            </div>

            <div className="jg-card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
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
                {identity.active_character_id && <span className="jg-pill">Character: {identity.active_character_id}</span>}
                {idSavedMsg && <span className="jg-muted">{idSavedMsg}</span>}
              </form>
            </div>

            <div className="jg-card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <h3 style={{ margin: 0 }}>Droid Mode — Connected Host Peripherals</h3>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <span className="jg-pill">Gimbal: {droidDevices.gimbal_camera?.name ?? "None detected"}</span>
                <span className="jg-pill">Cameras: {droidDevices.cameras?.length ?? 0}</span>
                <span className="jg-pill">Mics: {droidDevices.microphones?.length ?? 0}</span>
                <span className="jg-pill">Speakers: {droidDevices.speakers?.length ?? 0}</span>
                <span className="jg-pill">Pose: pan {droidPose.pan_deg ?? 0}° · tilt {droidPose.tilt_deg ?? 0}°</span>
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                {[
                  { label: "Look Left", action: "look_at", params: { pan_deg: -35, tilt_deg: 0 } },
                  { label: "Center Gimbal", action: "center", params: {} },
                  { label: "Look Right", action: "look_at", params: { pan_deg: 35, tilt_deg: 0 } },
                ].map((cmd) => (
                  <button
                    key={cmd.label}
                    type="button"
                    className="jg-btn"
                    onClick={async () => {
                      const r = await fetch(`${baseUrl}/v1/embodiment/droid/act`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ action: cmd.action, params: cmd.params }),
                      });
                      const d = await r.json();
                      if (d.pose) setDroidPose(d.pose);
                      setDroidStatusMsg(d.ok ? `${cmd.label} OK` : d.error || "Refused");
                    }}
                  >
                    {cmd.label}
                  </button>
                ))}
                <button
                  type="button"
                  className="jg-btn"
                  onClick={async () => {
                    const r = await fetch(`${baseUrl}/v1/droid/capture`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ device_index: "0" }) });
                    const d = await r.json();
                    setDroidStatusMsg(d.ok ? `Captured frame #${d.frame?.frame_id ?? 1}` : d.error || "Capture unavailable");
                  }}
                >
                  Capture Camera Frame
                </button>
                {droidStatusMsg && <span className="jg-muted">{droidStatusMsg}</span>}
              </div>
            </div>

            <div className="jg-card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
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
            </div>

            <div className="jg-card">
              <h3 style={{ marginTop: 0 }}>Active Model (Local-First + Cloud)</h3>
              <select
                className="jg-input"
                value={activeModel}
                onChange={async (e) => {
                  const next = e.target.value;
                  setActiveModel(next);
                  await fetch(`${baseUrl}/v1/models/select`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ model: next }),
                  });
                }}
              >
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.id}
                  </option>
                ))}
              </select>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
