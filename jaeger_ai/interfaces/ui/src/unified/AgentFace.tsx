/** One avatar for the unified UI: the agent's image, else its robot icon (default) or silhouette (per-device). */
import type { Agent } from "../api/types";
import { AgentAvatar } from "../agents/AgentAvatar";
import { RobotIcon, useRobotIcons } from "../agents/RobotIcon";
import { label } from "../agents/agentsLogic";

export function AgentFace({ agent, size = 28, status }: { agent: Agent; size?: number; status?: string }) {
  const [robots] = useRobotIcons();
  if (agent.avatar_url || !robots) return <AgentAvatar id={agent.id} name={label(agent)} src={agent.avatar_url} size={size} primary={agent.primary} />;
  return <RobotIcon id={agent.id} name={label(agent)} size={size} status={status} />;
}
