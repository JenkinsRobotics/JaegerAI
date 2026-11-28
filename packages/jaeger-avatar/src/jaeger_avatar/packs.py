"""Canonical ``avatar/v1`` Avatar Pack discovery & validation for jaeger-avatar.

Reads self-contained ``avatar.yaml`` packs authored by JaegerAvatar or
jaeger-module-omni without copying heavy media assets into JaegerAI. Enforces
schema version checks, safe lowercase IDs, and path-confinement against traversal.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable

_SAFE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _load_yaml_or_json(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".json":
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    try:
        import yaml  # type: ignore[import-untyped]

        parsed = yaml.safe_load(raw)
        return parsed if isinstance(parsed, dict) else {}
    except ImportError:
        # Lightweight stdlib fallback for simple top-level scalar YAML fields
        out: dict[str, Any] = {}
        for line in raw.splitlines():
            if not line.strip() or line.lstrip().startswith("#") or line[0].isspace():
                continue
            if ":" in line:
                k, _, v = line.partition(":")
                out[k.strip()] = v.strip().strip("'\"")
        return out


@dataclass(frozen=True)
class AvatarPackInfo:
    avatar_id: str
    name: str
    version: str
    description: str
    pack_dir: str
    schema: str
    default_profile: str
    default_representation: str
    profiles: tuple[str, ...]
    representations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "profiles": list(self.profiles),
            "representations": list(self.representations),
        }


def inspect_avatar_pack(pack_dir: Path) -> AvatarPackInfo:
    """Parse and validate a single ``avatar/v1`` pack directory."""
    root = Path(pack_dir).expanduser().resolve()
    manifest = root / "avatar.yaml"
    if not manifest.is_file():
        manifest = root / "avatar.json"
    if not manifest.is_file():
        raise ValueError(f"missing avatar.yaml in {root}")
    if manifest.is_symlink():
        raise ValueError(f"refusing symlinked manifest in {root}")

    data = _load_yaml_or_json(manifest)
    schema = str(data.get("schema") or "").strip()
    if schema != "avatar/v1":
        raise ValueError(f"unsupported avatar pack schema {schema!r}; expected 'avatar/v1'")

    avatar_id = str(data.get("avatar") or root.name).strip().lower()
    if not _SAFE_ID_RE.match(avatar_id):
        raise ValueError(f"invalid avatar pack id: {avatar_id!r}")

    profiles_map = data.get("profiles") if isinstance(data.get("profiles"), dict) else {}
    reps_map = data.get("representations") if isinstance(data.get("representations"), dict) else {}

    # Reject path traversal in representation roots
    for rep_name, rep_val in reps_map.items():
        if isinstance(rep_val, dict):
            rel_root = str(rep_val.get("root") or "").strip()
            if rel_root:
                resolved = (root / rel_root).resolve()
                if resolved != root and root not in resolved.parents:
                    raise ValueError(f"representation {rep_name!r} root escapes pack directory")

    return AvatarPackInfo(
        avatar_id=avatar_id,
        name=str(data.get("name") or avatar_id).strip(),
        version=str(data.get("version") or "0.1.0").strip(),
        description=str(data.get("description") or "").strip()[:300],
        pack_dir=str(root),
        schema=schema,
        default_profile=str(data.get("default_profile") or ""),
        default_representation=str(data.get("default_representation") or ""),
        profiles=tuple(sorted(str(k) for k in profiles_map.keys())),
        representations=tuple(sorted(str(k) for k in reps_map.keys())),
    )


def default_pack_search_dirs(*, state_dir: Path | None = None) -> list[Path]:
    """Return ordered search roots for installed ``avatar/v1`` packs."""
    dirs: list[Path] = []
    if state_dir is not None:
        dirs.append(Path(state_dir).expanduser().resolve() / "avatars" / "packs")
    env_dirs = (os.environ.get("JAEGER_AVATAR_PACK_DIRS") or "").strip()
    if env_dirs:
        for raw in env_dirs.split(os.pathsep):
            if raw.strip():
                dirs.append(Path(raw.strip()).expanduser().resolve())
    # Auto-detect sibling JenkinsRobotics repos if present locally (read-only discovery)
    gh_root = Path.home() / "GitHub"
    for sibling in (
        gh_root / "JaegerAvatar" / "avatars",
        gh_root / "jaeger-module-omni" / "jaeger_omni_v2" / "avatars",
    ):
        if sibling.is_dir():
            dirs.append(sibling.resolve())
    seen: set[Path] = set()
    uniq: list[Path] = []
    for d in dirs:
        if d not in seen:
            seen.add(d)
            uniq.append(d)
    return uniq


def discover_avatar_packs(
    search_dirs: Iterable[Path] | None = None,
    *,
    state_dir: Path | None = None,
) -> list[AvatarPackInfo]:
    """Scan ``search_dirs`` for valid ``avatar/v1`` packs (deduplicated by avatar_id)."""
    roots = list(search_dirs) if search_dirs is not None else default_pack_search_dirs(state_dir=state_dir)
    found: dict[str, AvatarPackInfo] = {}
    for root in roots:
        p = Path(root).expanduser().resolve()
        if not p.is_dir():
            continue
        candidates = [p] if (p / "avatar.yaml").is_file() else sorted(c for c in p.iterdir() if c.is_dir())
        for cand in candidates:
            if not ((cand / "avatar.yaml").is_file() or (cand / "avatar.json").is_file()):
                continue
            try:
                info = inspect_avatar_pack(cand)
            except Exception:  # noqa: BLE001
                continue
            found.setdefault(info.avatar_id, info)
    return sorted(found.values(), key=lambda item: item.avatar_id)


__all__ = [
    "AvatarPackInfo",
    "default_pack_search_dirs",
    "discover_avatar_packs",
    "inspect_avatar_pack",
]
