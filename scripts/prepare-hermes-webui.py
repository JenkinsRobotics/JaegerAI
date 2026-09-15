#!/usr/bin/env python3
"""Materialize pinned upstream plus Jaeger-owned patches without editing donor repos."""
from pathlib import Path
import io
import os
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def _git() -> str:
    """Prefer Homebrew Git on macOS where Apple Git may be license-gated."""
    override = os.environ.get("JAEGER_GIT")
    if override:
        return override
    homebrew = Path("/opt/homebrew/bin/git")
    return str(homebrew) if homebrew.is_file() else (shutil.which("git") or "git")


def prepare():
    donor = ROOT / "vendor/hermes-webui"
    overlay = ROOT / "integrations/hermes_webui"
    destination = Path(tempfile.mkdtemp(prefix="jaeger-webui-"))
    git = _git()
    archive = subprocess.check_output([git, "-C", str(donor), "archive", "HEAD"])
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(destination, filter="data")
    def _apply_overlay(name: str) -> None:
        path = overlay / name
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"Required WebUI overlay is missing or empty: {name}")
        subprocess.run([git, "apply", "--check", str(path)], cwd=destination, check=True)
        subprocess.run([git, "apply", str(path)], cwd=destination, check=True)

    for _name in (
        "upstream.patch",
        "update-labels.patch",
        "native-cancel-status.patch",
        "conversation.patch",
        "dispatcher-sidecar.patch",
    ):
        _apply_overlay(_name)
    shutil.copy2(overlay / "jaeger_conversation.py", destination / "api/jaeger_conversation.py")
    shutil.copy2(overlay / "jaeger_ollama.py", destination / "api/jaeger_ollama.py")
    shutil.copy2(overlay / "jaeger_gateway_routes.py", destination / "api/jaeger_gateway_routes.py")
    shutil.copy2(overlay / "jaeger_agents.py", destination / "api/jaeger_agents.py")
    shutil.copy2(overlay / "jaeger_sessions.py", destination / "api/jaeger_sessions.py")
    extensions = destination / 'jaeger-extensions'
    extensions.mkdir()
    for name in ('jaeger_webui_extensions.json', 'jaeger_stream_continuity.js',
                 'jaeger_webui_branding.js', 'jaeger_dispatcher.js',
                 'jaeger_gateway_console.js',
                 'jaeger_app_icon_16.png', 'jaeger_app_icon_32.png', 'jaeger_app_icon_256.png'):
        shutil.copy2(ROOT / 'jaeger_ai/assets' / name, extensions / name)
    shutil.copy2(ROOT / 'jaeger_ai/features/dispatcher/sidecar.py',
                 destination / 'jaeger_dispatcher_sidecar.py')
    shutil.copy2(overlay / 'jaeger_sidecar_supervisor.py',
                 destination / 'jaeger_sidecar_supervisor.py')
    version = subprocess.check_output(
        [git, "-C", str(donor), "describe", "--tags", "--always"], text=True
    ).strip().removeprefix("v")
    if not version or version == "unknown":
        raise RuntimeError("Pinned Hermes WebUI version could not be determined")
    (destination / "api/_version.py").write_text(
        f"__version__ = {version!r}\n", encoding="utf-8"
    )
    # Package explicitly: some Apple Container builders drop nested context
    # updates during incremental directory COPY. The build validates contents.
    with tarfile.open(destination / "jaeger-overlay.tar.gz", "w:gz") as tar:
        for name in ("api", "static", "docker_init.bash", "jaeger-extensions",
                     "jaeger_dispatcher_sidecar.py", "jaeger_sidecar_supervisor.py"):
            tar.add(destination / name, arcname=name)
    shutil.copy2(overlay / "Containerfile", destination / "Containerfile.jaeger")
    print(destination)
    return destination


if __name__ == "__main__":
    prepare()
