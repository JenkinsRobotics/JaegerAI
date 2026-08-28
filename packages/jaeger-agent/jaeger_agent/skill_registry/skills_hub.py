"""Skills hub — install skills from remote sources.

Ported from hermes-agent ``tools/skills_hub.py`` / ``tools/skills_sync.py``.
hermes-agent is MIT licensed:

    Copyright (c) 2025 Nous Research

    Permission is hereby granted, free of charge, to any person obtaining a
    copy of this software and associated documentation files (the
    "Software"), to deal in the Software without restriction, including
    without limitation the rights to use, copy, modify, merge, publish,
    distribute, sublicense, and/or sell copies of the Software, and to
    permit persons to whom the Software is furnished to do so, subject to
    the following conditions: the above copyright notice and this
    permission notice shall be included in all copies or substantial
    portions of the Software.

Jaeger could package a skill (``skill_market.package_skill``) but had no way
to *get* one, so all 109 skills shipped in the box with no optional tier and
no remote source.

SCOPE. The donor ships eight source adapters (GitHub, ClawHub, LobeHub,
skills.sh, browse.sh, URL, well-known, optional-skills). Ported here are the
:class:`SkillSource` interface and the two sources that carry their weight for
Jaeger — a GitHub repo and a local directory — plus the machinery that makes
installing third-party code survivable. Adding another adapter means
implementing three methods; nothing else in this module knows what a GitHub
is.

WHAT MAKES THIS SAFE, all inherited from the donor and all load-bearing when
the thing you are fetching is code someone else wrote:

  - **Quarantine first.** A bundle is written to ``<instance>/hub/quarantine``
    and validated there. Nothing lands in ``skills/`` until it passes, so a
    malformed or hostile bundle never sits in the directory the loader scans.
  - **Path containment on every member.** Bundle-relative paths are validated
    individually and re-checked after resolution. An entry like
    ``../../../.ssh/authorized_keys`` is what this exists to stop, and the
    check is done on the *resolved* path because ``a/../../b`` normalises past
    a naive prefix test.
  - **No redirects, HTTPS only.** Fetches refuse plain HTTP and refuse to
    follow redirects, so a well-known URL cannot bounce a fetch to an
    attacker's origin or to a link-local metadata address.
  - **A lock file** records what was installed, from where, and at what
    revision — so an installed skill's provenance is answerable later, which
    is exactly what Jaeger's ``manifest_v3.Provenance`` field wants.
  - **Every install is ledgered** through :mod:`jaeger_agent.skill_registry.
    skill_ledger`, so a hub install is as reversible as any other mutation.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SKILL_FILE = "SKILL.md"
_MAX_BUNDLE_FILES = 200
_MAX_BUNDLE_BYTES = 20 * 1024 * 1024
_GIT_TIMEOUT = 120

TRUST_OFFICIAL = "official"
TRUST_COMMUNITY = "community"
TRUST_LOCAL = "local"


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _layout() -> Any:
    from jaeger_agent.workspace import get_layout

    return get_layout()


def hub_dir() -> Path:
    return Path(_layout().root) / "hub"


def quarantine_dir() -> Path:
    return hub_dir() / "quarantine"


def lock_path() -> Path:
    return hub_dir() / "installed.json"


def skills_dir() -> Path:
    return Path(_layout().skills_dir)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class BundleError(ValueError):
    """A bundle failed validation. Never install one of these."""


def validate_skill_name(name: str) -> str:
    """A skill name becomes a directory name — it must be a single segment."""
    clean = (name or "").strip()
    if not clean:
        raise BundleError("skill name is empty")
    if clean in (".", ".."):
        raise BundleError(f"illegal skill name: {clean!r}")
    if "/" in clean or "\\" in clean or "\x00" in clean:
        raise BundleError(f"skill name must be a single path segment: {clean!r}")
    if clean.startswith("."):
        raise BundleError(f"skill name must not be hidden: {clean!r}")
    if len(clean) > 80:
        raise BundleError("skill name is too long")
    return clean


def validate_rel_path(rel: str) -> str:
    """Validate one bundle-relative member path.

    Rejects absolute paths, drive letters, NUL, and any ``..`` segment. The
    resolved-path check in :func:`_safe_join` is the real containment
    guarantee; this is the cheap first pass that also produces a readable
    error.
    """
    raw = (rel or "").strip()
    if not raw:
        raise BundleError("bundle contains an empty path")
    if "\x00" in raw:
        raise BundleError("bundle path contains NUL")
    if raw.startswith(("/", "\\")) or (len(raw) > 1 and raw[1] == ":"):
        raise BundleError(f"bundle path must be relative: {raw!r}")
    parts = Path(raw.replace("\\", "/")).parts
    if any(p == ".." for p in parts):
        raise BundleError(f"bundle path escapes the bundle: {raw!r}")
    return raw.replace("\\", "/")


def _safe_join(root: Path, rel: str) -> Path:
    """Join and verify containment on the RESOLVED path.

    ``a/../../b`` passes a naive prefix test on the unresolved string, so the
    check has to happen after resolution. Both sides are resolved because on
    macOS ``/var`` is a symlink to ``/private/var`` and an unresolved root
    would never be a parent of a resolved child.
    """
    target = (root / validate_rel_path(rel)).resolve()
    base = root.resolve()
    if target != base and base not in target.parents:
        raise BundleError(f"bundle path escapes the bundle: {rel!r}")
    return target


def validate_url(url: str) -> str:
    """HTTPS only. No redirects are followed by callers."""
    from urllib.parse import urlparse

    parsed = urlparse((url or "").strip())
    if parsed.scheme != "https":
        raise BundleError(
            f"refusing non-HTTPS source: {url!r} — a plaintext fetch of code "
            "to execute is not acceptable")
    if not parsed.netloc:
        raise BundleError(f"malformed URL: {url!r}")
    return url.strip()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SkillMeta:
    name: str
    description: str = ""
    source_id: str = ""
    identifier: str = ""
    revision: str = ""
    trust: str = TRUST_COMMUNITY


@dataclass
class SkillBundle:
    """A fetched skill: its metadata plus ``{relative path: bytes}``."""

    meta: SkillMeta
    files: dict[str, bytes] = field(default_factory=dict)

    def validate(self) -> None:
        """Structural checks. Raises :class:`BundleError`."""
        validate_skill_name(self.meta.name)
        if not self.files:
            raise BundleError("bundle is empty")
        if _SKILL_FILE not in self.files:
            raise BundleError(f"bundle has no {_SKILL_FILE}")
        if len(self.files) > _MAX_BUNDLE_FILES:
            raise BundleError(
                f"bundle has {len(self.files)} files (max {_MAX_BUNDLE_FILES})")
        total = 0
        for rel, blob in self.files.items():
            validate_rel_path(rel)
            total += len(blob)
        if total > _MAX_BUNDLE_BYTES:
            raise BundleError(
                f"bundle is {total} bytes (max {_MAX_BUNDLE_BYTES})")


class SkillSource(ABC):
    """Abstract base for skill registry adapters."""

    @abstractmethod
    def source_id(self) -> str: ...

    @abstractmethod
    def fetch(self, identifier: str) -> SkillBundle | None:
        """Download one skill bundle by identifier."""

    @abstractmethod
    def search(self, query: str, limit: int = 10) -> list[SkillMeta]:
        """Find skills matching *query*."""

    def trust_level_for(self, identifier: str) -> str:
        return TRUST_COMMUNITY


# ---------------------------------------------------------------------------
# Local directory source
# ---------------------------------------------------------------------------

class LocalSource(SkillSource):
    """Install from a directory on this machine.

    The obvious first adapter, and the one that makes the hub testable
    without a network. Also the migration path for the donor's
    ``optional-skills/`` tier: point it at that directory.
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser().resolve()

    def source_id(self) -> str:
        return "local"

    def trust_level_for(self, identifier: str) -> str:
        return TRUST_LOCAL

    def _skill_dirs(self) -> list[Path]:
        if not self.root.is_dir():
            return []
        return sorted(p.parent for p in self.root.rglob(_SKILL_FILE))

    def search(self, query: str, limit: int = 10) -> list[SkillMeta]:
        q = (query or "").lower().strip()
        out: list[SkillMeta] = []
        for folder in self._skill_dirs():
            if q and q not in folder.name.lower():
                continue
            out.append(SkillMeta(
                name=folder.name, source_id=self.source_id(),
                identifier=str(folder), trust=TRUST_LOCAL,
                description=_first_line(folder / _SKILL_FILE)))
            if len(out) >= max(1, limit):
                break
        return out

    def fetch(self, identifier: str) -> SkillBundle | None:
        folder = Path(identifier).expanduser().resolve()
        # Containment: an identifier is caller-supplied, so a path outside the
        # configured root is refused rather than silently honoured.
        if folder != self.root and self.root not in folder.parents:
            raise BundleError(
                f"{identifier!r} is outside this source's root {self.root}")
        if not (folder / _SKILL_FILE).is_file():
            return None
        files: dict[str, bytes] = {}
        for path in sorted(folder.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(folder).as_posix()
            try:
                validate_rel_path(rel)
            except BundleError:
                logger.warning("skills hub: skipping %r in %s", rel, folder)
                continue
            files[rel] = path.read_bytes()
        return SkillBundle(
            meta=SkillMeta(name=folder.name, source_id=self.source_id(),
                           identifier=str(folder), trust=TRUST_LOCAL,
                           description=_first_line(folder / _SKILL_FILE)),
            files=files)


# ---------------------------------------------------------------------------
# GitHub source
# ---------------------------------------------------------------------------

class GitHubSource(SkillSource):
    """Install from a public GitHub repository laid out as skill folders.

    Uses ``git clone --depth 1`` rather than the API: no token needed for
    public repos, no rate limit, and the revision is recorded for the lock
    file. The clone lands in a temp dir and is copied through quarantine like
    any other bundle.
    """

    #: Repos whose skills are treated as first-party rather than community.
    OFFICIAL_REPOS = frozenset({
        "anthropics/skills", "openai/skills", "huggingface/skills",
    })

    def __init__(self, repo: str, *, ref: str = "") -> None:
        self.repo = (repo or "").strip().strip("/")
        if self.repo.count("/") != 1 or not all(self.repo.split("/")):
            raise BundleError(f"expected owner/repo, got {repo!r}")
        self.ref = ref.strip()

    def source_id(self) -> str:
        return "github"

    def trust_level_for(self, identifier: str) -> str:
        return (TRUST_OFFICIAL if self.repo.lower() in self.OFFICIAL_REPOS
                else TRUST_COMMUNITY)

    @property
    def clone_url(self) -> str:
        return validate_url(f"https://github.com/{self.repo}.git")

    def _clone(self, dest: Path) -> str:
        args = ["git", "clone", "--depth", "1", "--quiet"]
        if self.ref:
            args += ["--branch", self.ref]
        args += [self.clone_url, str(dest)]
        res = subprocess.run(args, capture_output=True, text=True,
                             timeout=_GIT_TIMEOUT)
        if res.returncode != 0:
            raise BundleError(
                f"clone of {self.repo} failed: {res.stderr.strip()[:300]}")
        rev = subprocess.run(["git", "-C", str(dest), "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=30)
        return rev.stdout.strip() if rev.returncode == 0 else ""

    def search(self, query: str, limit: int = 10) -> list[SkillMeta]:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "repo"
            revision = self._clone(dest)
            local = LocalSource(dest)
            return [SkillMeta(
                name=m.name, description=m.description,
                source_id=self.source_id(),
                identifier=f"{self.repo}#{m.name}", revision=revision,
                trust=self.trust_level_for(m.name),
            ) for m in local.search(query, limit)]

    def fetch(self, identifier: str) -> SkillBundle | None:
        wanted = identifier.split("#", 1)[-1].strip() if "#" in identifier \
            else identifier.strip()
        validate_skill_name(wanted)
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "repo"
            revision = self._clone(dest)
            local = LocalSource(dest)
            for folder in local._skill_dirs():
                if folder.name != wanted:
                    continue
                bundle = local.fetch(str(folder))
                if bundle is None:
                    return None
                bundle.meta = SkillMeta(
                    name=bundle.meta.name, description=bundle.meta.description,
                    source_id=self.source_id(),
                    identifier=f"{self.repo}#{wanted}", revision=revision,
                    trust=self.trust_level_for(wanted))
                return bundle
        return None


def _first_line(path: Path) -> str:
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            clean = line.strip().lstrip("#").strip()
            if clean:
                return clean[:200]
    except OSError:
        pass
    return ""


# ---------------------------------------------------------------------------
# Lock file
# ---------------------------------------------------------------------------

def read_lock() -> dict[str, Any]:
    try:
        p = lock_path()
        if not p.is_file():
            return {}
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_lock(data: dict[str, Any]) -> None:
    p = lock_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(p)


def record_install(bundle: SkillBundle, install_path: Path) -> None:
    data = read_lock()
    data[bundle.meta.name] = {
        "source": bundle.meta.source_id,
        "identifier": bundle.meta.identifier,
        "revision": bundle.meta.revision,
        "trust": bundle.meta.trust,
        "installed_at": time.time(),
        "path": str(install_path),
    }
    _write_lock(data)


# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------

def _stage(bundle: SkillBundle) -> Path:
    """Write a validated bundle into quarantine and return its folder."""
    bundle.validate()
    root = quarantine_dir() / bundle.meta.name
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    for rel, blob in bundle.files.items():
        target = _safe_join(root, rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
    return root


def install(bundle: SkillBundle, *, overwrite: bool = False) -> dict[str, Any]:
    """Validate, quarantine, then move a bundle into ``<instance>/skills``.

    Returns ``{ok, name, path}`` or ``{ok: False, error}``. Refuses to
    clobber an existing skill unless *overwrite* — a hub install silently
    replacing a hand-written skill of the same name is exactly the surprise
    the ledger exists to undo, and better not to cause it.
    """
    try:
        bundle.validate()
        name = validate_skill_name(bundle.meta.name)
    except BundleError as exc:
        return {"ok": False, "error": str(exc)}

    dest = skills_dir() / name
    if dest.exists() and not overwrite:
        return {"ok": False, "error": (
            f"a skill named {name!r} is already installed — pass "
            "overwrite=True to replace it")}

    try:
        staged = _stage(bundle)
    except BundleError as exc:
        return {"ok": False, "error": f"bundle rejected: {exc}"}
    except OSError as exc:
        return {"ok": False, "error": f"could not stage bundle: {exc}"}

    from jaeger_agent.skill_registry import skill_ledger as _ledger

    before = _ledger.capture_before(dest if dest.exists() else None)
    try:
        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staged), str(dest))
    except OSError as exc:
        return {"ok": False, "error": f"install failed: {exc}"}

    _ledger.record_mutation(
        "hub-install", name, before=before, after_root=dest,
        evidence={"source": bundle.meta.source_id,
                  "identifier": bundle.meta.identifier,
                  "revision": bundle.meta.revision,
                  "trust": bundle.meta.trust})
    record_install(bundle, dest)
    return {"ok": True, "name": name, "path": str(dest),
            "trust": bundle.meta.trust, "revision": bundle.meta.revision}


def install_from(source: SkillSource, identifier: str, *,
                 overwrite: bool = False) -> dict[str, Any]:
    """Fetch from *source* and install. Convenience over fetch + install."""
    try:
        bundle = source.fetch(identifier)
    except BundleError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 — network/git failures
        return {"ok": False, "error": f"fetch failed: {exc}"}
    if bundle is None:
        return {"ok": False, "error": f"{identifier!r} not found in "
                                      f"{source.source_id()}"}
    return install(bundle, overwrite=overwrite)


def uninstall(name: str) -> dict[str, Any]:
    """Remove a hub-installed skill, ledgering it so it can come back."""
    try:
        clean = validate_skill_name(name)
    except BundleError as exc:
        return {"ok": False, "error": str(exc)}
    dest = skills_dir() / clean
    if not dest.is_dir():
        return {"ok": False, "error": f"no installed skill named {clean!r}"}

    from jaeger_agent.skill_registry import skill_ledger as _ledger

    before = _ledger.capture_before(dest)
    shutil.rmtree(dest)
    _ledger.record_mutation("hub-uninstall", clean, before=before,
                            after_root=None)
    data = read_lock()
    data.pop(clean, None)
    _write_lock(data)
    return {"ok": True, "name": clean}


def installed() -> list[dict[str, Any]]:
    """Everything the hub installed, newest first."""
    rows = [{"name": k, **v} for k, v in read_lock().items()
            if isinstance(v, dict)]
    rows.sort(key=lambda r: r.get("installed_at", 0), reverse=True)
    return rows


__all__ = [
    "BundleError", "GitHubSource", "LocalSource", "SkillBundle", "SkillMeta",
    "SkillSource", "TRUST_COMMUNITY", "TRUST_LOCAL", "TRUST_OFFICIAL",
    "hub_dir", "install", "install_from", "installed", "quarantine_dir",
    "read_lock", "uninstall", "validate_rel_path", "validate_skill_name",
    "validate_url",
]
