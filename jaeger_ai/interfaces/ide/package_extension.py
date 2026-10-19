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



def gateway_contract(repo: Path) -> dict:
    """LOOPBACK and GATEWAY_PORT's default from ports.py.

    Read with ``ast`` (never imported). ``GATEWAY_PORT`` is an env-overridable
    expression (``int(os.environ.get(...) or <default>)``); the built extension
    gets the default, the literal int inside it.
    """
    constants: dict = {}
    for node in ast.parse((repo / "jaeger_ai/contract/ports.py").read_text()).body:
        if not (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)):
            continue
        name = node.target.id
        if name not in {"LOOPBACK", "GATEWAY_PORT"}:
            continue
        if isinstance(node.value, ast.Constant):
            constants[name] = node.value.value
        else:
            ints = [n.value for n in ast.walk(node.value)
                    if isinstance(n, ast.Constant) and type(n.value) is int]
            if len(ints) != 1:
                raise SystemExit(f"cannot read the default of {name} from ports.py")
            constants[name] = ints[0]
    missing = {"LOOPBACK", "GATEWAY_PORT"} - set(constants)
    if missing:
        raise SystemExit(f"ports.py is missing {sorted(missing)}")
    return constants

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
    for name in ("package.json", "extension.js", "gateway.js", "conversation.js", "commands.js", "native-turn.js",
                 "README.md", "VERIFICATION.md", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(source / name, stage / name)
    # Editors and patch tools may leave rejected/backup files beside live
    # assets. They are neither runtime dependencies nor release content.
    shutil.copytree(
        source / "media", stage / "media",
        ignore=shutil.ignore_patterns("*.orig", "*.rej", ".DS_Store"),
    )
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
    constants = gateway_contract(repo)
    (stage / "contract.json").write_text(json.dumps({
        "gatewayUrl": f"http://{constants['LOOPBACK']}:{constants['GATEWAY_PORT']}",
    }) + "\n")
    # Hash the staged bytes, including generated contract and pinned renderer.
    hashes = {str(p.relative_to(stage)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(stage.rglob("*")) if p.is_file()}
    content_hash = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    try:
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True, timeout=5).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=normal", "--",
                                             str(source), "jaeger_ai/contract/ports.py", _SMD_SOURCE],
                                            cwd=repo, text=True, timeout=5).strip())
    except (OSError, subprocess.SubprocessError):
        revision, dirty = "unavailable", None
    (stage / "build.json").write_text(json.dumps({
        "version": json.loads((stage / "package.json").read_text())["version"],
        "sourceRevision": revision, "sourceDirty": dirty,
        "contentSha256": content_hash, "files": hashes,
    }, sort_keys=True, indent=2) + "\n")
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
