"""Workspace-scoped skill store: Jaeger saves a learned procedure into
``<workspace>/skills/<name>/SKILL.md`` and rediscovers it in a fresh session.

Content is treated strictly as procedure data (markdown only): nothing is
executed, no scripts are allowed, and the existing tool permission policy is
untouched. Every publish and every load re-runs the hard validator, the
advisory linter, and the skills-guard scanner (trust level ``agent-created``);
only content classified ``safe`` is published or surfaced.
"""

from __future__ import annotations

import errno
import os
import shutil
import stat
import tempfile
from pathlib import Path

from .skill_linter import ERROR, lint_skill
from .skills_guard import scan_skill
from .store import (
    MAX_SKILL_BYTES,
    SkillSummary,
    SkillValidationError,
    clean_skill_name,
    parse_frontmatter,
    rank_skills,
    validate_skill_markdown,
)

AGENT_CREATED = "agent-created"
SKILL_FILE = "SKILL.md"
_MAX_SEARCH_LIMIT = 50


class SkillStoreError(Exception):
    """Raised when a skill cannot be stored, found, or trusted."""


class SkillExistsError(SkillStoreError):
    """Raised when a skill name is already published (overwrite is denied)."""


class WorkspaceSkillStore:
    """Durable, workspace-local store for agent-learned procedures."""

    def __init__(self, workspace: str | os.PathLike[str]) -> None:
        raw = Path(workspace)
        # Reject a symlinked skills root on the original path, before resolving.
        if (raw / "skills").is_symlink():
            raise SkillStoreError("workspace skills root must not be a symlink")
        self.workspace = raw.resolve()
        self.skills_root = self.workspace / "skills"

    def _check_skills_root(self) -> None:
        """Reject a skills root swapped for a symlink after ``__init__``.

        Runs on every save/search/load, not just at construction: a root
        redirected later must never be followed into writes or reads.
        """
        if self.skills_root.is_symlink():
            raise SkillStoreError("workspace skills root must not be a symlink")

    # -- path safety -----------------------------------------------------

    def _skill_dir(self, name: str) -> Path:
        """Resolve ``skills/<normalized-name>`` and reject escapes/symlinks.

        Symlink checks run on the original (unresolved) candidate directory and
        SKILL.md *before* any resolution or read; resolved components are not
        walked again.
        """
        self._check_skills_root()
        clean = clean_skill_name(name)  # raises SkillValidationError on bad names
        candidate = self.skills_root / clean
        if candidate.is_symlink() or (candidate / SKILL_FILE).is_symlink():
            raise SkillStoreError(f"skill path contains a symlink: {name!r}")
        resolved = candidate.resolve()
        if resolved != self.skills_root and not resolved.is_relative_to(self.skills_root):
            raise SkillStoreError(f"skill path escapes the workspace skills root: {name!r}")
        return resolved

    def _skill_file(self, name: str) -> Path:
        return self._skill_dir(name) / SKILL_FILE

    def _read_bounded(self, root_fd: int, clean: str) -> str:
        """Read at most MAX_SKILL_BYTES + 1 bytes of ``skills/<clean>/SKILL.md``.

        The whole path is pinned to directory descriptors: the skills root is
        opened with O_DIRECTORY|O_NOFOLLOW, the skill directory is opened by
        name relative to that root fd with the same flags, and SKILL.md is
        opened by name relative to the skill dir fd with O_NOFOLLOW. A parent
        directory swapped for an outside symlink between checks and open is
        therefore refused (ELOOP) instead of reading a foreign file. The fd
        must fstat as a regular file before the bounded read.
        """
        flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
        try:
            skill_fd = os.open(clean, flags, dir_fd=root_fd)
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise SkillStoreError(f"skill path contains a symlink: {clean!r}") from exc
            if exc.errno == errno.ENOENT:
                raise SkillStoreError(f"skill {clean!r} not found") from exc
            raise
        try:
            if os.listdir(skill_fd) != [SKILL_FILE]:
                raise SkillStoreError(
                    f"skill directory of {clean!r} must contain only {SKILL_FILE}"
                )
            file_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
            try:
                fd = os.open(SKILL_FILE, file_flags, dir_fd=skill_fd)
            except OSError as exc:
                if exc.errno == errno.ELOOP:
                    raise SkillStoreError(f"skill path contains a symlink: {SKILL_FILE!r}") from exc
                if exc.errno == errno.ENOENT:
                    raise SkillStoreError(f"skill {clean!r} not found") from exc
                raise
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise SkillStoreError(f"skill {clean!r} is not a regular file")
                with os.fdopen(fd, "rb") as fh:
                    data = fh.read(MAX_SKILL_BYTES + 1)
            except OSError as exc:
                if exc.errno == errno.ELOOP:
                    raise SkillStoreError(f"skill path contains a symlink: {SKILL_FILE!r}") from exc
                raise
        finally:
            os.close(skill_fd)
        if len(data) > MAX_SKILL_BYTES:
            raise SkillValidationError(f"Skill content exceeds {MAX_SKILL_BYTES} bytes")
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise SkillValidationError(f"Skill content is not valid UTF-8: {exc}") from exc

    # -- safety gates ----------------------------------------------------

    def _lint_ok(self, skill_md: Path) -> None:
        findings = lint_skill(skill_md)
        errors = [f for f in findings if f.severity == ERROR]
        if errors:
            detail = "; ".join(f"{f.rule}: {f.message}" for f in errors[:3])
            raise SkillStoreError(f"skill failed lint: {detail}")

    def _scan_safe(self, path: Path) -> None:
        result = scan_skill(path, AGENT_CREATED, trust_level=AGENT_CREATED)
        if result.verdict != "safe":
            raise SkillStoreError(
                f"skills-guard classified the skill as {result.verdict!r}; refusing to publish"
            )

    def _stage_snapshot(self, clean: str, text: str) -> tuple[Path, Path]:
        """Write ``text`` to a private ``<staging>/<clean>/SKILL.md`` snapshot.

        Returns ``(staging_root, staged_md)``; the caller owns cleaning the
        staging root.
        """
        staging = Path(tempfile.mkdtemp(prefix=".jaeger-skill-stage-", dir=self.workspace))
        stage_dir = staging / clean  # parent name matches the frontmatter name
        stage_dir.mkdir()
        staged_md = stage_dir / SKILL_FILE
        staged_md.write_text(text, encoding="utf-8")
        return staging, staged_md

    def _load_verified(self, name: str) -> tuple[str, str, Path]:
        """Shared load gate: scope, symlink, content, validator, lint, scanner.

        Returns ``(clean_name, validated_text, skill_file)`` or raises. Only
        ``SKILL.md`` may live in a skill directory. The bounded bytes are read
        once, snapshotted into private staging, and the validator, linter and
        scanner all run on that exact snapshot — the same bytes returned to
        the model — never on a reopened, mutable original file.
        """
        clean = clean_skill_name(name)
        skill_dir = self._skill_dir(clean)  # root + original-path symlink + escape checks
        skill_file = skill_dir / SKILL_FILE
        if skill_file.is_symlink() or not skill_file.is_file():
            raise SkillStoreError(f"skill {clean!r} not found")
        # Pin the read to directory fds so a parent swapped for an outside
        # symlink just before the open cannot redirect the read.
        root_flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
        root_fd = os.open(self.skills_root, root_flags)
        try:
            raw = self._read_bounded(root_fd, clean)  # fd-pinned, bounded, UTF-8
        finally:
            os.close(root_fd)
        text = validate_skill_markdown(clean, raw)  # validator recheck
        staging, staged_md = self._stage_snapshot(clean, text)
        try:
            self._lint_ok(staged_md)  # lint the exact returned bytes
            self._scan_safe(staged_md)  # scan the exact returned bytes
        finally:
            shutil.rmtree(staging, ignore_errors=True)  # clean only owned staging
        return clean, text, skill_file

    # -- public API ------------------------------------------------------

    def save(self, name: str, markdown: str) -> Path:
        """Validate, lint, scan, then atomically publish a new SKILL.md.

        Never overwrites an existing skill. Staging happens in a private
        temporary directory inside the workspace (at ``<temp>/<name>/SKILL.md``
        so the linter's name-dir check sees a matching parent) and only that
        owned staging directory is cleaned up.
        """
        clean = clean_skill_name(name)
        text = validate_skill_markdown(clean, markdown)  # hard validator
        self._check_skills_root()  # reject a root swapped for a symlink after init
        dest_dir = self.skills_root / clean
        if dest_dir.is_symlink() or dest_dir.exists() or (dest_dir / SKILL_FILE).exists():
            raise SkillExistsError(f"skill {clean!r} already exists; overwrite is denied")

        self.workspace.mkdir(parents=True, exist_ok=True)
        self.skills_root.mkdir(parents=True, exist_ok=True)  # real dir, never a symlink
        staging, staged_md = self._stage_snapshot(clean, text)
        try:
            self._lint_ok(staged_md)
            self._scan_safe(staged_md)
            # Recheck the skills root immediately before publishing, then use
            # dir_fd-relative O_NOFOLLOW opens so a swapped root or destination
            # directory cannot redirect the write outside the workspace.
            self._check_skills_root()
            root_fd = os.open(self.skills_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                try:
                    os.mkdir(clean, 0o755, dir_fd=root_fd)
                except FileExistsError:
                    raise SkillExistsError(
                        f"skill {clean!r} already exists; overwrite is denied"
                    ) from None
                try:
                    dest_fd = os.open(
                        clean, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd
                    )
                except OSError as exc:
                    if exc.errno == errno.ELOOP:
                        raise SkillStoreError(
                            f"skill path contains a symlink: {clean!r}"
                        ) from exc
                    raise
                try:
                    staged_fd = os.open(
                        staged_md.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                    )
                    try:
                        os.link(
                            SKILL_FILE,
                            SKILL_FILE,
                            src_dir_fd=staged_fd,
                            dst_dir_fd=dest_fd,
                            follow_symlinks=False,
                        )
                    finally:
                        os.close(staged_fd)
                except FileExistsError:
                    # Leave any potentially replaced destination untouched.
                    raise SkillExistsError(
                        f"skill {clean!r} already exists; overwrite is denied"
                    ) from None
                finally:
                    os.close(dest_fd)
            finally:
                os.close(root_fd)
            return dest_dir / SKILL_FILE
        finally:
            shutil.rmtree(staging, ignore_errors=True)  # clean only owned staging

    def search(self, query: str, limit: int = 5) -> list[SkillSummary]:
        """Rank published skills by relevance, surfacing only safe ones."""
        try:
            cap = max(1, min(int(limit), _MAX_SEARCH_LIMIT))
        except (TypeError, ValueError):
            cap = 5
        self._check_skills_root()  # reject a root swapped for a symlink after init
        root = self.skills_root
        if root.is_symlink() or not root.is_dir():  # reads never create a missing skills folder
            return []
        candidates: list[SkillSummary] = []
        for entry in sorted(root.iterdir()):
            try:
                clean, text, skill_file = self._load_verified(entry.name)
            except (SkillValidationError, SkillStoreError, OSError):
                continue  # never surface unsafe or invalid files
            fm = parse_frontmatter(text)
            candidates.append(
                SkillSummary(
                    name=clean,
                    description=fm.get("description", ""),
                    path=str(skill_file),
                )
            )
        return rank_skills(query, candidates, limit=cap)

    def load(self, name: str) -> str:
        """Return the stored SKILL.md body after rechecking scope, validator, scanner."""
        _, text, _ = self._load_verified(name)
        return text
