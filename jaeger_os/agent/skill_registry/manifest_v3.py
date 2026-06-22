"""Skill manifest v3 — parser, validator, legacy stub generator.

Implements the spec in ``dev/docs/skill_schema_v3.md``.  This module is
data-only: parsing YAML into typed objects, validating against the
closed enums, and synthesising stub manifests for legacy
``<name>_v<N>/`` folders that predate the v3 envelope.  It does NOT
import skill modules, register tools, or touch the audit log — that
work stays in :mod:`skill_loader`.

Three entry points the loader uses:

  * :func:`load_manifest_from_folder` — try ``manifest.yaml`` first,
    fall back to v3 frontmatter in ``SKILL.md``.  Returns ``None`` if
    the folder has neither (caller decides whether to generate a
    legacy stub).
  * :func:`legacy_stub_manifest` — produce a ``Manifest`` for a
    legacy ``<name>_v<N>/`` folder so the loader treats it uniformly
    with new v3 skills.
  * :func:`validate_manifest` — enforce closed enums + scope
    vocabulary.  Raises :class:`ManifestError`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml


# ─── schema constants ────────────────────────────────────────────────

SCHEMA = "jros.skill/v3"

# Closed enums.  Adding a value bumps the schema (v4) or extends an
# allow-list via this module — never via per-skill YAML.

ORIGIN_VALUES = ("human_authored", "agent_authored", "marketplace", "imported")

# ``code_skill`` is loaded into the agent process by ``skill_loader``.
# ``playbook`` is a valid package value — markdown procedures
# discovered + indexed by ``playbook_skills.discover_playbooks`` — but
# the code-skill loader returns *early* on playbook packages so it
# doesn't try to importlib a SKILL.md file as Python.  The schema
# still lists ``playbook`` as implemented because the value is
# accepted in manifests today and the playbook subsystem handles
# discovery; only the code-skill registration path skips it.
PACKAGE_IMPLEMENTED = ("code_skill", "playbook")
PACKAGE_RESERVED = ("tool_bundle", "mcp_server", "behavior_tree", "policy")
PACKAGE_ALL = PACKAGE_IMPLEMENTED + PACKAGE_RESERVED

RUNTIME_IMPLEMENTED = ("in_process",)
RUNTIME_RESERVED = (
    "subprocess", "mcp", "ros2_action", "policy_server", "external",
)
RUNTIME_ALL = RUNTIME_IMPLEMENTED + RUNTIME_RESERVED

DOMAIN_VALUES = (
    "cognitive", "physical", "social", "game", "media",
    "devops", "productivity", "research", "sensing", "other",
)

# Host-side resource scopes enforced in 0.3.0.
HOST_SCOPES = (
    "net.outbound",
    "fs.workspace", "fs.host",
    "subprocess",
    "display",
    "audio.in", "audio.out",
    "clipboard",
)

# Robot-side scopes — declared in manifests for forward-compat,
# enforced when JP01 lands.  The loader accepts them today but the
# permission middleware ignores them.
ROBOT_SCOPES_RESERVED = (
    "camera.rgb", "camera.depth",
    "arm.motion", "gripper.control", "base.motion",
    "imu.read", "lidar.read",
)

# ``net.outbound:<host>`` form is parameterised — handled separately.
_NET_OUTBOUND_PARAM_RE = re.compile(r"^net\.outbound:[A-Za-z0-9.\-*]{1,253}$")

# Manifest ``id`` slug — lowercase, underscores, digits.  Matches the
# legacy ``<name>_v<N>`` regex's name portion so a folder rename to
# strict v3 stays valid.  Used at parse time + by the loader to keep
# id, folder, and filesystem keys consistent.
_V3_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


# ─── error ───────────────────────────────────────────────────────────


class ManifestError(Exception):
    """Raised when a manifest is malformed or violates schema rules."""


# ─── dataclasses ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class Level:
    """Capability level bands + current value.  Bands are the score
    thresholds that promote a capability one level up; default 5-band
    progression matches the spec doc."""

    current: int = 1
    bands: tuple[float, ...] = (0.5, 0.7, 0.8, 0.9, 0.95)
    scorer: str | None = None              # relative path inside skill folder

    @property
    def max(self) -> int:
        return len(self.bands)


@dataclass(frozen=True)
class Capability:
    id: str
    signature: str
    description: str = ""
    level: Level = field(default_factory=Level)


@dataclass(frozen=True)
class Artifact:
    id: str
    kind: str
    path: str | None = None        # relative to skill folder
    uri: str | None = None         # for 0.4.x content store
    sha256: str | None = None
    size_bytes: int | None = None
    license: str | None = None


@dataclass(frozen=True)
class Embodiment:
    platforms: tuple[str, ...] = ()    # macos | linux | windows | any
    bodies: tuple[str, ...] = ()       # robot platform ids
    sensors: tuple[str, ...] = ()
    actuators: tuple[str, ...] = ()


@dataclass(frozen=True)
class Permissions:
    tier: int = 0
    resource_scopes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Dependencies:
    tools: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()  # "skill.cap>=N" comparator strings
    commands: tuple[str, ...] = ()       # OS-level binary requirements


@dataclass(frozen=True)
class Entrypoint:
    module: str | None = None
    attr: str | None = None


@dataclass(frozen=True)
class Provenance:
    """Per-instance fork-tracking block.  Only present on instance-zone
    copies; core-zone manifests omit it."""

    upstream_id: str
    upstream_version: str
    base_sha256: str
    forked_at: str
    forked_reason: str = ""
    fork_chain: tuple[dict[str, str], ...] = ()


@dataclass(frozen=True)
class Manifest:
    """A fully-validated v3 skill manifest.

    Immutable on purpose — the loader takes a snapshot at discovery
    and downstream code (audit, registry, scoring) reads it without
    risk of mid-load mutation.
    """

    schema: str
    id: str
    version: str
    origin: str
    package: str
    runtime: str
    domains: tuple[str, ...]
    description: str
    embodiment: Embodiment
    permissions: Permissions
    capabilities: tuple[Capability, ...]
    dependencies: Dependencies
    artifacts: tuple[Artifact, ...]
    entrypoint: Entrypoint | None
    body: str | None = None                # playbook markdown body
    provenance: Provenance | None = None
    source_path: Path | None = field(default=None, repr=False)

    @property
    def level_summary(self) -> int:
        """Derived skill-level score = ``min`` across capability levels.
        Honest about regressions; callers wanting average/max compute
        it themselves."""
        if not self.capabilities:
            return 0
        return min(cap.level.current for cap in self.capabilities)

    @property
    def is_supported_package(self) -> bool:
        return self.package in PACKAGE_IMPLEMENTED

    @property
    def is_supported_runtime(self) -> bool:
        return self.runtime in RUNTIME_IMPLEMENTED


# ─── parsing ─────────────────────────────────────────────────────────


def load_manifest_from_folder(folder: Path) -> Manifest | None:
    """Try ``manifest.yaml`` first, then a v3 frontmatter block in
    ``SKILL.md``.  Returns ``None`` when neither carries a v3 schema —
    the caller decides whether to fall through to legacy-stub
    generation.  Raises :class:`ManifestError` on a malformed v3
    document so a typo is loud."""
    yaml_path = folder / "manifest.yaml"
    if yaml_path.exists():
        return _parse_yaml_path(yaml_path)
    skill_md = folder / "SKILL.md"
    if skill_md.exists():
        fm = _frontmatter(skill_md)
        if fm and fm.get("schema") == SCHEMA:
            body = _body_after_frontmatter(skill_md)
            return _from_mapping(fm, source=skill_md, default_body=body)
    return None


def _parse_yaml_path(path: Path) -> Manifest:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ManifestError(f"{path}: couldn't read/parse: {exc}") from exc
    if not isinstance(raw, dict):
        raise ManifestError(f"{path}: top-level must be a mapping")
    return _from_mapping(raw, source=path)


def _frontmatter(path: Path) -> dict[str, Any] | None:
    """Parse the leading ``---``-delimited YAML block, ``None`` if
    absent or malformed."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    try:
        data = yaml.safe_load(text[3:end])
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def _body_after_frontmatter(path: Path) -> str | None:
    """Return the markdown body after the SKILL.md frontmatter block,
    used by playbook packages.  ``None`` if no body."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    if end == -1:
        return None
    body = text[end + 4:].lstrip("\n")
    return body or None


# ─── mapping → Manifest ──────────────────────────────────────────────


def _from_mapping(
    raw: dict[str, Any],
    *,
    source: Path,
    default_body: str | None = None,
) -> Manifest:
    schema = raw.get("schema")
    if schema != SCHEMA:
        raise ManifestError(
            f"{source}: schema must be {SCHEMA!r}, got {schema!r}"
        )

    manifest_id = _require_str(raw, "id", source)
    if not _V3_ID_RE.match(manifest_id):
        raise ManifestError(
            f"{source}: id {manifest_id!r} must match {_V3_ID_RE.pattern!r} "
            "(lowercase alphanumeric + underscore, starting with a letter)"
        )
    manifest = Manifest(
        schema=schema,
        id=manifest_id,
        version=_require_str(raw, "version", source),
        origin=_enum(raw, "origin", ORIGIN_VALUES, source),
        package=_enum(raw, "package", PACKAGE_ALL, source),
        runtime=_enum(raw, "runtime", RUNTIME_ALL, source),
        domains=_enum_list(raw, "domains", DOMAIN_VALUES, source, required=True),
        description=_optional_str(raw, "description", default="", source=source),
        embodiment=_parse_embodiment(raw.get("embodiment"), source),
        permissions=_parse_permissions(raw.get("permissions"), source),
        capabilities=_parse_capabilities(raw.get("capabilities"), source),
        dependencies=_parse_dependencies(raw.get("dependencies"), source),
        artifacts=_parse_artifacts(raw.get("artifacts"), source),
        entrypoint=_parse_entrypoint(raw.get("entrypoint"), source),
        body=raw.get("body") if isinstance(raw.get("body"), str) else default_body,
        provenance=_parse_provenance(raw.get("provenance"), source),
        source_path=source,
    )
    validate_manifest(manifest)
    return manifest


def _parse_embodiment(raw: Any, source: Path) -> Embodiment:
    if raw is None:
        return Embodiment()
    if not isinstance(raw, dict):
        raise ManifestError(f"{source}: 'embodiment' must be a mapping")
    return Embodiment(
        platforms=tuple(_str_list(raw, "platforms")),
        bodies=tuple(_str_list(raw, "bodies")),
        sensors=tuple(_str_list(raw, "sensors")),
        actuators=tuple(_str_list(raw, "actuators")),
    )


def _parse_permissions(raw: Any, source: Path) -> Permissions:
    if raw is None:
        return Permissions()
    if not isinstance(raw, dict):
        raise ManifestError(f"{source}: 'permissions' must be a mapping")
    tier = raw.get("tier", 0)
    if not isinstance(tier, int) or not (0 <= tier <= 5):
        raise ManifestError(
            f"{source}: permissions.tier must be int 0..5, got {tier!r}"
        )
    return Permissions(
        tier=tier,
        resource_scopes=tuple(_str_list(raw, "resource_scopes")),
    )


def _parse_capabilities(raw: Any, source: Path) -> tuple[Capability, ...]:
    if raw is None or raw == []:
        raise ManifestError(
            f"{source}: at least one entry required in 'capabilities'"
        )
    if not isinstance(raw, list):
        raise ManifestError(f"{source}: 'capabilities' must be a list")
    caps: list[Capability] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ManifestError(
                f"{source}: capabilities[{i}] must be a mapping"
            )
        level = _parse_level(entry.get("level"), source, i)
        caps.append(Capability(
            id=_require_str(entry, "id", source, field=f"capabilities[{i}].id"),
            signature=_require_str(entry, "signature", source,
                                   field=f"capabilities[{i}].signature"),
            description=_optional_str(entry, "description", default="", source=source),
            level=level,
        ))
    return tuple(caps)


def _parse_level(raw: Any, source: Path, idx: int) -> Level:
    if raw is None:
        return Level()
    if not isinstance(raw, dict):
        raise ManifestError(
            f"{source}: capabilities[{idx}].level must be a mapping"
        )
    current = raw.get("current", 1)
    if not isinstance(current, int) or current < 1:
        raise ManifestError(
            f"{source}: capabilities[{idx}].level.current must be int >= 1"
        )
    bands_raw = raw.get("bands", [0.5, 0.7, 0.8, 0.9, 0.95])
    if not isinstance(bands_raw, list) or not bands_raw:
        raise ManifestError(
            f"{source}: capabilities[{idx}].level.bands must be a non-empty list"
        )
    try:
        bands = tuple(float(b) for b in bands_raw)
    except (TypeError, ValueError) as exc:
        raise ManifestError(
            f"{source}: capabilities[{idx}].level.bands must be numbers: {exc}"
        ) from exc
    if current > len(bands):
        raise ManifestError(
            f"{source}: capabilities[{idx}].level.current ({current}) exceeds "
            f"band count ({len(bands)})"
        )
    if any(b < a for a, b in zip(bands, bands[1:])):
        raise ManifestError(
            f"{source}: capabilities[{idx}].level.bands must be ascending"
        )
    scorer = raw.get("scorer")
    if scorer is not None and not isinstance(scorer, str):
        raise ManifestError(
            f"{source}: capabilities[{idx}].level.scorer must be a string path"
        )
    return Level(current=current, bands=bands, scorer=scorer)


def _parse_dependencies(raw: Any, source: Path) -> Dependencies:
    if raw is None:
        return Dependencies()
    if not isinstance(raw, dict):
        raise ManifestError(f"{source}: 'dependencies' must be a mapping")
    return Dependencies(
        tools=tuple(_str_list(raw, "tools")),
        capabilities=tuple(_str_list(raw, "capabilities")),
        commands=tuple(_str_list(raw, "commands")),
    )


def _parse_artifacts(raw: Any, source: Path) -> tuple[Artifact, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ManifestError(f"{source}: 'artifacts' must be a list")
    out: list[Artifact] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ManifestError(f"{source}: artifacts[{i}] must be a mapping")
        size = entry.get("size_bytes")
        if size is not None and (not isinstance(size, int) or size < 0):
            raise ManifestError(
                f"{source}: artifacts[{i}].size_bytes must be a non-negative int"
            )
        out.append(Artifact(
            id=_require_str(entry, "id", source, field=f"artifacts[{i}].id"),
            kind=_require_str(entry, "kind", source, field=f"artifacts[{i}].kind"),
            path=_optional_str(entry, "path", source=source),
            uri=_optional_str(entry, "uri", source=source),
            sha256=_optional_str(entry, "sha256", source=source),
            size_bytes=size,
            license=_optional_str(entry, "license", source=source),
        ))
    return tuple(out)


def _parse_entrypoint(raw: Any, source: Path) -> Entrypoint | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ManifestError(f"{source}: 'entrypoint' must be a mapping")
    return Entrypoint(
        module=_optional_str(raw, "module", source=source),
        attr=_optional_str(raw, "attr", source=source),
    )


def _parse_provenance(raw: Any, source: Path) -> Provenance | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ManifestError(f"{source}: 'provenance' must be a mapping")
    chain_raw = raw.get("fork_chain") or []
    if not isinstance(chain_raw, list):
        raise ManifestError(f"{source}: provenance.fork_chain must be a list")
    chain: list[dict[str, str]] = []
    for i, entry in enumerate(chain_raw):
        if not isinstance(entry, dict):
            raise ManifestError(
                f"{source}: provenance.fork_chain[{i}] must be a mapping"
            )
        chain.append({k: str(v) for k, v in entry.items()})
    return Provenance(
        upstream_id=_require_str(raw, "upstream_id", source,
                                 field="provenance.upstream_id"),
        upstream_version=_require_str(raw, "upstream_version", source,
                                      field="provenance.upstream_version"),
        base_sha256=_require_str(raw, "base_sha256", source,
                                 field="provenance.base_sha256"),
        forked_at=_require_str(raw, "forked_at", source,
                               field="provenance.forked_at"),
        forked_reason=_optional_str(raw, "forked_reason", default="", source=source) or "",
        fork_chain=tuple(chain),
    )


# ─── validation ──────────────────────────────────────────────────────


def validate_manifest(manifest: Manifest) -> None:
    """Belt-and-suspenders validation on a parsed manifest.  Most
    checks are already done during parsing; this catches cross-field
    rules (resource scope vocabulary, source-path consistency)."""
    bad_scopes = list(_invalid_scopes(manifest.permissions.resource_scopes))
    if bad_scopes:
        raise ManifestError(
            f"{manifest.source_path}: unknown resource scope(s): "
            f"{', '.join(bad_scopes)}.  Known host scopes: "
            f"{', '.join(HOST_SCOPES)}; reserved robot scopes: "
            f"{', '.join(ROBOT_SCOPES_RESERVED)}."
        )
    if manifest.source_path is not None:
        # Folder basename must match `id` exactly OR be the legacy
        # ``<id>_v<N>`` shape during the migration window.  Looser
        # ``startswith`` would let ``computer_use_legacy/`` validate
        # for id ``computer_use``, hijacking the canonical resolution
        # key — a real foot-gun for an instance that forked a skill
        # under a sibling name.
        parent = manifest.source_path.parent.name
        if manifest.source_path.name in ("manifest.yaml", "SKILL.md"):
            exact = parent == manifest.id
            legacy = bool(re.match(
                rf"^{re.escape(manifest.id)}_v\d+$", parent,
            ))
            if not (exact or legacy):
                raise ManifestError(
                    f"{manifest.source_path}: id {manifest.id!r} must match "
                    f"folder basename exactly or the legacy "
                    f"``<id>_v<N>`` shape; got {parent!r}"
                )


def _invalid_scopes(scopes: Iterable[str]) -> Iterable[str]:
    known = set(HOST_SCOPES) | set(ROBOT_SCOPES_RESERVED)
    for scope in scopes:
        if scope in known:
            continue
        if _NET_OUTBOUND_PARAM_RE.match(scope):
            continue
        yield scope


# ─── legacy stub generation ──────────────────────────────────────────


def legacy_stub_manifest(
    *,
    folder: Path,
    name: str,
    version: int,
    description: str | None,
    tier: int,
    smoke_path: Path | None,
    entrypoint_module: str,
) -> Manifest:
    """Synthesize a v3 manifest for a legacy ``<name>_v<N>/`` folder
    that predates the v3 envelope.  The stub is intentionally
    conservative:

      * ``package: code_skill``, ``runtime: in_process`` — the only
        thing the legacy loader supports.
      * ``domains: [other]`` — operator promotes to a real domain
        when they port the manifest by hand.
      * One capability ``legacy`` with a scorer pointing at
        ``smoke_test.py`` so the existing pass/fail gate also
        produces a level signal (level 1 = passes smoke).
      * ``origin: human_authored`` — every legacy core skill is
        shipped, hence human-authored.  Instance-zone legacy skills
        get the same default; agents authoring new skills should
        write v3 manifests directly.
    """
    legacy_version = f"0.{version}.0"
    desc = description or f"Legacy v{version} skill: {name}."
    scorer = None
    if smoke_path is not None:
        try:
            scorer = str(smoke_path.relative_to(folder))
        except ValueError:
            scorer = smoke_path.name
    capability = Capability(
        id="legacy",
        signature="register(agent) -> None",
        description="Legacy register-tools entrypoint (no capability split).",
        level=Level(
            current=1,
            bands=(0.5,),
            scorer=scorer,
        ),
    )
    return Manifest(
        schema=SCHEMA,
        id=name,
        version=legacy_version,
        origin="human_authored",
        package="code_skill",
        runtime="in_process",
        domains=("other",),
        description=desc,
        embodiment=Embodiment(),
        permissions=Permissions(tier=tier, resource_scopes=()),
        capabilities=(capability,),
        dependencies=Dependencies(),
        artifacts=(),
        entrypoint=Entrypoint(module=entrypoint_module, attr="register"),
        body=None,
        provenance=None,
        source_path=None,
    )


# ─── small helpers ───────────────────────────────────────────────────


def _require_str(
    src: dict[str, Any],
    key: str,
    source: Path,
    *,
    field: str | None = None,
) -> str:
    label = field or key
    value = src.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{source}: missing/empty {label!r}")
    return value.strip()


def _optional_str(
    src: dict[str, Any],
    key: str,
    *,
    default: str | None = None,
    source: Path | None = None,
) -> str | None:
    """Return an optional string field; raise on a wrong-type value.

    Silently swallowing a non-string here used to hide typos like
    ``description: 42`` — the manifest would parse, the field would
    quietly default, and the operator wouldn't find out until the
    catalogue rendered blank.  v3 is strict: present-but-wrong-type
    is a manifest bug.  Absent is fine (returns the default).
    """
    if key not in src:
        return default
    value = src[key]
    if value is None:
        return default
    if not isinstance(value, str):
        where = f"{source}: " if source is not None else ""
        raise ManifestError(
            f"{where}{key!r} must be a string (got "
            f"{type(value).__name__})"
        )
    stripped = value.strip()
    return stripped or default


def _enum(
    src: dict[str, Any],
    key: str,
    valid: tuple[str, ...],
    source: Path,
) -> str:
    value = src.get(key)
    if not isinstance(value, str) or value not in valid:
        raise ManifestError(
            f"{source}: {key!r} must be one of {list(valid)}, got {value!r}"
        )
    return value


def _enum_list(
    src: dict[str, Any],
    key: str,
    valid: tuple[str, ...],
    source: Path,
    *,
    required: bool = False,
) -> tuple[str, ...]:
    raw = src.get(key)
    if raw is None:
        if required:
            raise ManifestError(f"{source}: {key!r} is required")
        return ()
    if not isinstance(raw, list):
        raise ManifestError(f"{source}: {key!r} must be a list")
    valid_set = set(valid)
    bad = [str(v) for v in raw if v not in valid_set]
    if bad:
        raise ManifestError(
            f"{source}: {key!r} has unknown value(s) {bad}, must be in {list(valid)}"
        )
    if required and not raw:
        raise ManifestError(f"{source}: {key!r} must have at least one entry")
    # De-dupe but preserve order.
    seen: set[str] = set()
    out: list[str] = []
    for v in raw:
        s = str(v)
        if s not in seen:
            seen.add(s)
            out.append(s)
    return tuple(out)


def _str_list(src: dict[str, Any], key: str) -> list[str]:
    raw = src.get(key)
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [str(v).strip() for v in raw if str(v).strip()]
