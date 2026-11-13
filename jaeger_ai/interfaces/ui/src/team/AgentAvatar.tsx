/* One face per agent, the same everywhere (Team page, Process view): the pack's
 * image when it has one, else an orb drawn from the agent's avatar seed with its
 * initials. Seed -> colour idea from OpenBot's avatarSeed orbs (MIT); drawn here. */
import { memo } from "react";

export function seedHue(seed: string): [number, number] {
  let h = 2166136261;
  for (let i = 0; i < seed.length; i++) { h ^= seed.charCodeAt(i); h = Math.imul(h, 16777619); }
  const a = Math.abs(h) % 360;
  return [a, (a + 48 + (Math.abs(h >> 9) % 70)) % 360];
}

export function initials(name: string): string {
  const words = name.replace(/[&@]/g, " ").split(/\s+/).filter((w) => w && !/^(jaeger|jager|ai|the|and)$/i.test(w));
  const pick = (words.length ? words : name.split(/\s+/)).slice(0, 2).map((w) => w[0]?.toUpperCase() ?? "");
  return pick.join("") || "?";
}

export const AgentAvatar = memo(function AgentAvatar({ name, seed, url, size = 40, status }: {
  name: string; seed?: string | null; url?: string | null; size?: number; status?: string;
}) {
  const [a, b] = seedHue(seed || name);
  const ring = status === "working" || status === "running" ? " is-working" : status === "failed" ? " is-failed" : "";
  return (
    <span className={`jg-avatar${ring}`} style={{ width: size, height: size, fontSize: Math.max(10, Math.round(size * 0.36)) }}
      role="img" aria-label={name} title={name}>
      {url ? <img src={url} alt="" /> : (
        <span className="jg-avatar__orb" style={{ background: `radial-gradient(120% 120% at 25% 20%, hsl(${a} 85% 68%), hsl(${b} 70% 42%))` }}>
          {initials(name)}
        </span>
      )}
    </span>
  );
});

export default AgentAvatar;
