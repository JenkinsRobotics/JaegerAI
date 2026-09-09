#!/usr/bin/env python3
"""Materialize pinned upstream plus Jaeger-owned patches without editing donor repos."""
from pathlib import Path
import io
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def prepare():
    donor = ROOT / "vendor/hermes-webui"
    overlay = ROOT / "integrations/hermes_webui"
    destination = Path(tempfile.mkdtemp(prefix="jaeger-webui-"))
    archive = subprocess.check_output(["git", "-C", str(donor), "archive", "HEAD"])
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(destination, filter="data")
    subprocess.run(["git", "apply", "--check", str(overlay / "upstream.patch")], cwd=destination, check=True)
    subprocess.run(["git", "apply", str(overlay / "upstream.patch")], cwd=destination, check=True)
    subprocess.run(["git", "apply", "--check", str(overlay / "update-labels.patch")], cwd=destination, check=True)
    subprocess.run(["git", "apply", str(overlay / "update-labels.patch")], cwd=destination, check=True)
    subprocess.run(["git", "apply", "--check", str(overlay / "native-cancel-status.patch")], cwd=destination, check=True)
    subprocess.run(["git", "apply", str(overlay / "native-cancel-status.patch")], cwd=destination, check=True)
    subprocess.run(["git", "apply", "--check", str(overlay / "native-capabilities.patch")], cwd=destination, check=True)
    subprocess.run(["git", "apply", str(overlay / "native-capabilities.patch")], cwd=destination, check=True)
    subprocess.run(["git", "apply", str(overlay / "conversation.patch")], cwd=destination, check=True)
    shutil.copy2(overlay / "jaeger_conversation.py", destination / "api/jaeger_conversation.py")
    shutil.copy2(overlay / "jaeger_ollama.py", destination / "api/jaeger_ollama.py")
    shutil.copy2(overlay / "jaeger_agent_compat.py", destination / "api/jaeger_agent_compat.py")
    shutil.copy2(overlay / "jaeger_gateway_routes.py", destination / "api/jaeger_gateway_routes.py")
    extensions = destination / 'jaeger-extensions'
    extensions.mkdir()
    for name in ('jaeger_webui_extensions.json', 'jaeger_webui_branding.js', 'jaeger_dispatcher.js',
                 'jaeger_app_icon_16.png', 'jaeger_app_icon_32.png', 'jaeger_app_icon_256.png'):
        shutil.copy2(ROOT / 'jaeger_ai/assets' / name, extensions / name)
    shutil.copy2(ROOT / 'jaeger_ai/features/hermes_webui/dispatcher_sidecar.py',
                 destination / 'jaeger_dispatcher_sidecar.py')
    init = destination / 'docker_init.bash'
    marker = 'cd /app; python server.py || error_exit "hermes-webui failed or exited with an error"'
    content = init.read_text()
    if content.count(marker) != 1:
        raise RuntimeError('Upstream WebUI startup changed; review Dispatcher sidecar startup')
    content = content.replace(marker, '''export HERMES_WEBUI_EXTENSION_DIR=/apptoo/jaeger-extensions
export HERMES_WEBUI_EXTENSION_MANIFEST=jaeger_webui_extensions.json
python /apptoo/jaeger_dispatcher_sidecar.py &
jaeger_sidecar_pid=$!
trap 'kill "$jaeger_sidecar_pid" 2>/dev/null || true' EXIT
''' + marker)
    init.write_text(content)
    # Package explicitly: some Apple Container builders drop nested context
    # updates during incremental directory COPY. The build validates contents.
    with tarfile.open(destination / "jaeger-overlay.tar.gz", "w:gz") as tar:
        for name in ("api", "static", "docker_init.bash", "jaeger-extensions", "jaeger_dispatcher_sidecar.py"):
            tar.add(destination / name, arcname=name)
    shutil.copy2(overlay / "Containerfile", destination / "Containerfile.jaeger")
    print(destination)
    return destination


if __name__ == "__main__":
    prepare()
