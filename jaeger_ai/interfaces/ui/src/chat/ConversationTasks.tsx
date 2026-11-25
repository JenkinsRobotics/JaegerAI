import { useEffect, useState } from "react";
import type { Task } from "../api/types";
import { isInternalWork } from "../tasks/internalWork";
import type { WebHost } from "./webHost";

const states: Record<string, string> = { queued: "Queued", running: "Working", blocked: "Blocked", needs_owner: "Needs you", paused: "Paused" };
export function currentBackgroundTasks(tasks: Task[], sessionId: string): Task[] {
  return tasks.filter(t => t.provenance?.session_id === sessionId && Object.hasOwn(states, String(t.state))
    && !t.task_id.startsWith("turn:") && !isInternalWork(t.goal) && !isInternalWork(t.provenance?.submission_goal))
    .sort((a, b) => Number(b.updated_at ?? 0) - Number(a.updated_at ?? 0));
}

export function ConversationTasks({ host, sessionId, revision }: { host: WebHost; sessionId: string; revision: string }) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const hasTasks = tasks.length > 0;
  useEffect(() => {
    let alive = true;
    const read = async () => {
      try {
        const rows = await host.listConversationTasks(sessionId);
        if (alive) setTasks(currentBackgroundTasks(rows, sessionId));
      } catch { if (alive) setTasks([]); }
    };
    void read();
    const timer = hasTasks ? window.setInterval(() => { if (!document.hidden) void read(); }, 15000) : undefined;
    return () => { alive = false; window.clearInterval(timer); };
  }, [host, sessionId, revision, hasTasks]);
  if (!tasks.length || !host.openTask) return null;
  return <section className="jg-chat-tasks" aria-label="Background tasks">
    {tasks.map(task => <div className="jg-chat-task" key={task.task_id}>
      <div><strong title={task.goal}>{task.goal || "Background task"}</strong><small>{states[String(task.state)]}</small></div>
      <button type="button" className="jg-u-btn" onClick={() => host.openTask?.(task.task_id)}>View task</button>
    </div>)}
  </section>;
}
