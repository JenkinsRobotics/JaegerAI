"""Stage and package outside the checkout using Microsoft's VSCE packager.

Run with PYTHONDONTWRITEBYTECODE=1. No npm install/build outputs enter source.
The default Gateway URL is generated from the existing canonical port contract.
"""
from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

# streaming-markdown@0.2.15 (MIT, Damian Tarnawski) — see THIRD_PARTY_NOTICES.md.
# The ONE copy of this file lives under the WebUI's vendor tree; staged here
# rather than committed a second time into interfaces/ide. Pinned by hash so
# an upstream WebUI vendor bump is a visible packaging failure, not a silent
# extension-side version drift.
_SMD_SOURCE = "jaeger_ai/features/webui/static/vendor/smd.min.js"
_SMD_SHA384 = "T6r95ocN9t3W8tUK2Fa6FPaO7bJryyjyW0WCalrUnpgtm2qXr5xcN4vwPYEJ6vHa"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--stage-only", action="store_true")
    args = parser.parse_args()
    source = Path(__file__).resolve().parent
    repo = source.parents[2]
    output = args.output_root.expanduser().resolve()
    if output == repo or repo in output.parents:
        parser.error("output-root must be outside the repository")
    output.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="jaeger-ide-", dir=output))
    for name in ("package.json", "extension.js", "gateway.js", "conversation.js", "commands.js",
                 "README.md", "VERIFICATION.md", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(source / name, stage / name)
    shutil.copytree(source / "media", stage / "media")
    smd_bytes = (repo / _SMD_SOURCE).read_bytes()
    actual = base64.b64encode(hashlib.sha384(smd_bytes).digest()).decode()
    if actual != _SMD_SHA384:
        parser.error(
            f"{_SMD_SOURCE} does not match the pinned streaming-markdown "
            f"build (expected sha384 {_SMD_SHA384}, got {actual}). The "
            "WebUI's vendored copy moved; update _SMD_SHA384 here after "
            "confirming the new file's license and version, and vice versa."
        )
    (stage / "media" / "vendor").mkdir(parents=True, exist_ok=True)
    (stage / "media" / "vendor" / "smd.min.js").write_bytes(smd_bytes)
    constants = {}
    for node in ast.parse((repo / "jaeger_ai/contract/ports.py").read_text()).body:
        if (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
                and node.target.id in {"LOOPBACK", "GATEWAY_PORT"}):
            constants[node.target.id] = ast.literal_eval(node.value)
    (stage / "contract.json").write_text(json.dumps({
        "gatewayUrl": f"http://{constants['LOOPBACK']}:{constants['GATEWAY_PORT']}",
    }) + "\n")
    print(f"STAGE={stage}", flush=True)
    if not args.stage_only:
        # The version lives in package.json only; the file name follows it.
        version = json.loads((stage / "package.json").read_text())["version"]
        target = stage / f"jaeger-ide-{version}.vsix"
        env = {**os.environ, "npm_config_cache": str(output / "npm-cache")}
        subprocess.run([
            "npx", "--yes", "--package", "@vscode/vsce@3.6.2", "vsce", "package",
            "--no-dependencies", "--skip-license", "--allow-missing-repository",
            "--out", str(target),
        ], cwd=stage, env=env, check=True)
        print(f"VSIX={target}")


if __name__ == "__main__":
    main()
