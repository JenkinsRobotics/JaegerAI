"""CI Hygiene and Clean Repository Guard.

Guarantees that JaegerAI adheres strictly to the OpenClaw standard:
  1. Zero in-repo runtime state, virtualenvs, or caches.
  2. No code writes databases, state, or instances into the git working tree.
  3. All persistent state routes cleanly to ~/.jaeger/.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]

FORBIDDEN_ROOT_NAMES = {
    ".venv",
    ".jaeger_ai",
    ".jaeger_agent",
    ".jaeger_os",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".vscode",
    "jaeger_ai.egg-info",
}


def test_repo_root_has_zero_runtime_junk():
    """Ensure no runtime artifacts or local virtualenvs pollute the git root."""
    found_forbidden = [
        p.name for p in REPO_ROOT.iterdir()
        if p.name in FORBIDDEN_ROOT_NAMES
    ]
    assert not found_forbidden, (
        f"Forbidden runtime junk directories found in repo root: {found_forbidden}. "
        "All state belongs in ~/.jaeger and all virtualenvs belong in ~/.jaeger/venv."
    )


def test_no_in_repo_state_writes_in_core():
    """Ensure no source files reintroduce hardcoded state writes to REPO_ROOT."""
    violations: list[str] = []
    source_root = REPO_ROOT / "jaeger_ai"

    for py_file in source_root.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        if 'REPO_ROOT / ".jaeger_ai"' in text or 'REPO_ROOT / ".jaeger_agent"' in text:
            violations.append(str(py_file.relative_to(REPO_ROOT)))

    assert not violations, (
        "Found hardcoded in-repo state writes in the following files:\n"
        + "\n".join(violations)
        + "\nAll runtime state must use operator_state_root() (~/.jaeger)."
    )


def test_product_never_uses_packages_default_in_repo_workspace():
    """A10 (RELEASE_AUDIT.md): ``packages/jaeger-agent/jaeger_agent/workspace.py``'s
    ``DefaultWorkspace`` defaults to ``<cwd>/.jaeger_agent`` — a deliberate,
    documented choice for a genuinely standalone embedder of the reusable
    package (see that module's docstring: "a robot's workspace lives with
    the robot's code"), reached via ``ensure_bound()`` or
    ``DefaultAgentRuntime()`` with no explicit root.

    The JaegerAI product must never take that default — it always binds an
    explicit ``InstanceLayout`` via ``workspace.bind(layout, ...)``
    (confirmed: ``jaeger_ai/core/entity/runtime.py``,
    ``jaeger_ai/core/gateway/server.py``). Running the real product with
    cwd inside this source checkout must not create
    ``<repo>/.jaeger_agent`` as a side effect of an unbound default. This
    is a static guard against a future caller silently reintroducing that
    default; it does not by itself prove every dynamic import path.
    """
    source_root = REPO_ROOT / "jaeger_ai"
    violations: list[str] = []
    for py_file in source_root.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        if ("ensure_bound(" in text or "DefaultWorkspace(" in text
                or "DefaultAgentRuntime(" in text):
            violations.append(str(py_file.relative_to(REPO_ROOT)))

    assert not violations, (
        "jaeger_ai/ (the product) must always bind an explicit InstanceLayout "
        "via workspace.bind(layout, ...), never the reusable package's "
        "standalone default (which creates <cwd>/.jaeger_agent):\n"
        + "\n".join(violations)
    )


def test_operator_state_root_defaults_to_user_home(monkeypatch):
    """Verify that operator_state_root resolves to ~/.jaeger when no test sandbox is set."""
    from jaeger_ai.core.instance.instance import operator_state_root

    monkeypatch.delenv("JAEGER_HOME", raising=False)
    monkeypatch.delenv("JAEGER_STATE_DIR", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("JAEGER_NO_ATTACH", raising=False)

    expected = Path.home() / ".jaeger"
    assert operator_state_root() == expected


def test_ci_and_local_share_the_isolated_runner():
    """A11 (RELEASE_AUDIT.md): CI used raw pytest / swift test and in-tree
    build output while local runs used the isolated runner. Both now use one
    definition of every tier; this pins it."""
    runner = (REPO_ROOT / "dev/scripts/run_tests.sh").read_text(encoding="utf-8")
    ci = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert ".venv/bin/pytest" not in runner, "no in-repository virtualenv fallback"
    assert "JAEGER_VENV" in runner
    for package in ("jaeger-agent", "jaeger-os", "jaeger-kokoro-tts", "jaeger-whisper-stt"):
        assert f'"packages/{package}"' in runner, f"{package} must be in the default package suites"

    assert "python -m pytest" not in ci, "CI must call dev/scripts/run_tests.sh, not raw pytest"
    assert "dev/scripts/run_tests.sh --unit" in ci
    assert "dev/scripts/run_tests.sh --package" in ci
    assert "--scratch-path" in ci and "--skip DispatcherLiveTests" in ci
    assert "dist/all" not in ci, "build output belongs outside the checkout"


def test_webui_launcher_does_not_adopt_a_sibling_hermes_checkout():
    """H03: the product is self-contained. A Hermes checkout beside the repo
    is used only when named by JAEGER_HERMES_AGENT_SRC, never by default."""
    launcher = (REPO_ROOT / "scripts/run-jaeger-webui.sh").read_text(encoding="utf-8")
    assert 'JAEGER_HERMES_AGENT_SRC:-${HOME}/GitHub/hermes-agent' not in launcher
    assert 'hermes_agent_src="${JAEGER_HERMES_AGENT_SRC:-}"' in launcher
    # H03 (updated): the vendor tree has been removed (2026-09-26 cleanup).
    # The product is self-contained via jaeger_ai/core + packages/jaeger-agent.
    # The webui bootstrap discovers an external agent dir at runtime; it no
    # longer depends on an in-tree vendor copy.
    assert not (REPO_ROOT / "jaeger_ai/vendor").exists()


ALLOWED_ROOT_ITEMS = {
    ".agents",
    ".git",
    ".gitattributes",
    ".github",
    ".gitignore",
    ".kilo",
    "AGENTS.md",
    "CHANGELOG.md",
    "CLAUDE.md",
    "COMMANDS.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "MANIFEST.in",
    "README.md",
    "SECURITY.md",
    "STRUCTURE.md",
    "apps",
    "clients",
    "conftest.py",
    "dev",
    "docs",
    "install.sh",
    "integrations",
    "jaeger",
    "jaeger.multimodal.toml",
    "jaeger.toml",
    "jaeger.windowed.toml",
    "jaeger_ai",
    "packages",
    "pyproject.toml",
    "requirements.txt",
    "run.sh",
    "scripts",
    "uv.lock",
}


def test_repo_root_strict_allowlist():
    """Fail if an unapproved file or directory appears in the repository root."""
    actual_items = {p.name for p in REPO_ROOT.iterdir()}
    unexpected = actual_items - ALLOWED_ROOT_ITEMS
    assert not unexpected, (
        f"Tripwire triggered: unapproved files/directories found in repository root: {sorted(unexpected)}. "
        "Every file in root must be in the approved ALLOWED_ROOT_ITEMS list. "
        "Do not leave scratch scripts, compat shims, or runtime artifacts in repo root."
    )


def test_no_compat_shims_or_vendor_paths():
    """Ensure dead compat shims and vendor directories never reappear."""
    forbidden_paths = [
        REPO_ROOT / "jaeger_ai" / "vendor",
        REPO_ROOT / "hermes_state.py",
        REPO_ROOT / "jaeger_ai" / "hermes_state.py",
        REPO_ROOT / "packages" / "jaeger-agent" / "hermes_state.py",
    ]
    reappeared = [str(p.relative_to(REPO_ROOT)) for p in forbidden_paths if p.exists()]
    assert not reappeared, (
        f"Tripwire triggered: forbidden vendor or compat shim path reappeared: {reappeared}. "
        "Per AGENTS.md §5, compat shims are strictly forbidden."
    )


def test_every_feature_has_a_readme():
    """Per AGENTS.md §5, every folder in jaeger_ai/features/ must have a README.md."""
    features_dir = REPO_ROOT / "jaeger_ai" / "features"
    missing: list[str] = []
    for item in sorted(features_dir.iterdir()):
        if item.is_dir() and not item.name.startswith((".", "_")):
            readme = item / "README.md"
            if not readme.is_file():
                missing.append(item.name)
    assert not missing, (
        f"Tripwire triggered: feature directories missing README.md: {missing}. "
        "Every feature in jaeger_ai/features/ must have a README.md explaining its purpose and touchpoints."
    )

