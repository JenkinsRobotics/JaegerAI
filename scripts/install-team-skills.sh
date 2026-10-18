#!/bin/bash
# Copy the team role skills (and optionally the REA skill folder, whole) into an
# instance skills dir. Usage: install-team-skills.sh <skills_dir> [rea_skill_src_dir]
set -euo pipefail
dest="${1:?skills dir}"; rea="${2:-}"
here="$(cd "$(dirname "$0")/.." && pwd)/jaeger_ai/core/agent_registry/team_skills"
mkdir -p "$dest"
for d in "$here"/*/; do
  name="$(basename "$d")"; mkdir -p "$dest/$name"; cp -p "$d"SKILL.md "$dest/$name/SKILL.md"; echo "installed $name"
done
if [ -n "$rea" ]; then
  [ -f "$rea/SKILL.md" ] && [ -d "$rea/references" ] || { echo "REA source must hold SKILL.md and references/" >&2; exit 1; }
  mkdir -p "$dest/reverse-engineer-anything/references"
  cp -p "$rea/SKILL.md" "$dest/reverse-engineer-anything/SKILL.md"
  cp -p "$rea"/references/*.md "$dest/reverse-engineer-anything/references/"
  cat > "$dest/reverse-engineer-anything/jaeger-notes.md" <<'NOTE'
# Jaeger notes for REA
REA is registered in Jaeger's mcp.json as server `rea`; its tools are `mcp__rea__*`.
Do not run `rea setup` or `rea doctor --client`: Jaeger has no REA client id.
NOTE
  echo "installed reverse-engineer-anything ($(ls "$dest/reverse-engineer-anything/references" | wc -l | tr -d ' ') references)"
fi
