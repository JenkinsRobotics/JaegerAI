"""Run adversarial model scenarios inside an enforced macOS sandbox.

Only a disposable directory is writable; network and Apple events are denied.
The seed contains model/persona settings, never user credentials or memory.
Before inference, a child process must prove that an outside canary cannot be
read, rewritten, or chmodded, and that it cannot open a network connection.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


REPO = Path(__file__).resolve().parents[2]


def sandbox_profile(root: Path, read_paths: list[Path]) -> str:
    quote = lambda p: json.dumps(str(p.resolve()))
    reads = "\n".join(f"(allow file-read* (subpath {quote(p)}))" for p in read_paths)
    return f"""(version 1)
(deny default)
(allow process*)
(allow sysctl-read)
(allow mach-lookup)
(allow iokit-open)
(allow ipc-posix-shm)
(allow file-read-metadata)
(allow file-read* (literal "/") (literal {quote(REPO)}))
(allow file-read* (subpath "/System") (subpath "/usr")
 (subpath "/Library") (subpath "/opt/homebrew") (subpath "/dev")
 (literal "/private/etc/localtime") (literal "/private/etc/hosts")
 (literal "/private/etc/passwd") (literal "/private/etc/group"))
{reads}
(allow file-read* file-write* (subpath {quote(root)}))
(allow file-write-data (literal "/dev/null") (literal "/dev/tty"))
(deny network*)
(deny appleevent-send)
"""


PROBE = r'''
import os, pathlib, socket, subprocess, sys
p = pathlib.Path(os.environ["JAEGER_SANDBOX_CANARY"])
blocked = 0
for op in (p.read_text, lambda: p.write_text("changed"), lambda: p.chmod(0o777)):
    try:
        op()
    except PermissionError:
        blocked += 1
sock = None
try:
    sock = socket.socket()
    sock.connect(("127.0.0.1", 9))
except PermissionError:
    blocked += 1
finally:
    if sock is not None:
        sock.close()
if blocked != 4:
    raise SystemExit("sandbox probe failed: %s/4 denied" % blocked)
print("sandbox enforcement: 4/4 denied", flush=True)
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-instance", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ids", default="")
    parser.add_argument("--probe-only", action="store_true")
    args = parser.parse_args()
    if sys.platform != "darwin" or not shutil.which("sandbox-exec"):
        parser.error("This runner requires macOS sandbox-exec; use an equivalent isolated VM elsewhere.")
    import yaml
    from jaeger_ai.core.instance.schemas import Config, Identity, dump_yaml

    source = yaml.safe_load((args.source_instance / "config.yaml").read_text())
    config = Config.model_validate({"instance_name": "release-audit", **{
        key: source[key] for key in ("model", "persona", "multimodal") if key in source}})
    args.output = args.output.resolve()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="jaeger-security-") as temporary:
        root = Path(temporary).resolve()
        seed = root / "seed"
        seed.mkdir()
        (root / "tmp").mkdir()
        dump_yaml(seed / "config.yaml", config)
        dump_yaml(seed / "identity.yaml", Identity(name="Release Audit", role="assistant",
                                                 personality="Helpful and concise."))
        # Test the OS boundary against harmless data, never against a real
        # credential, user file, or system executable.
        with tempfile.NamedTemporaryFile(prefix="jaeger-denied-", mode="w") as canary:
            canary.write("unchanged")
            canary.flush()
            reads = [Path(sys.prefix), Path(sys.base_prefix), REPO / "jaeger_ai",
                     REPO / "dev", REPO / "pyproject.toml", REPO / "requirements.txt"]
            # The integrated product owns its dependencies under packages/.
            # Include installed wheels too; never require sibling checkouts.
            for package in (REPO / "packages").iterdir():
                if package.is_dir():
                    reads.extend(path for path in package.iterdir()
                                 if not path.name.startswith(".")
                                 and path.name not in {"tests", "dev", "build", "dist"})
            model = Path(config.model.model_path).expanduser().resolve()
            reads.append(model)
            from jaeger_agent import MultimodalConfig
            speech = config.multimodal or MultimodalConfig()
            reads.extend(Path(getattr(speech, name)).expanduser().resolve() for name in
                         ("silero_model_path", "vision_mmproj_path"))
            for path in (Path.home() / ".cache/huggingface/hub", Path.home() / ".cache/whisper",
                         Path.home() / ".cache/pywhispercpp"):
                if path.exists():
                    reads.append(path)
            profile = root / "sandbox.sb"
            profile.write_text(sandbox_profile(root, reads))
            env = {k: v for k, v in os.environ.items()
                   if not any(word in k.upper() for word in ("TOKEN", "SECRET", "PASSWORD", "API_KEY"))
                   and k not in {"GIT_ASKPASS", "SSH_AUTH_SOCK"}}
            env.update(JAEGER_INSTANCE_DIR=str(seed), JAEGER_INSTANCE_NAME="release-audit",
                       JAEGER_HOME=str(root), JAEGER_STATE_DIR=str(root), TMPDIR=str(root / "tmp"),
                       JAEGER_TEST_HEADLESS="1", PYTHONDONTWRITEBYTECODE="1",
                       HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                       JAEGER_SANDBOX_CANARY=canary.name)
            prefix = ["/usr/bin/sandbox-exec", "-f", str(profile), sys.executable]
            probe = subprocess.run([*prefix, "-c", PROBE], env=env, capture_output=True, text=True)
            if probe.returncode:
                sys.stderr.write(probe.stderr or probe.stdout or f"sandbox probe exited {probe.returncode}\n")
                return 2
            print(probe.stdout.strip(), flush=True)
            if args.probe_only:
                args.output.write_text(json.dumps({"sandbox_verified": True, "checks": 4}, indent=2) + "\n")
                return 0
            result_path = root / "security-results.json"
            command = [*prefix, str(REPO / "dev/benchmark/scenarios.py"), "--lane", "security",
                       "--no-prewarm", "--dump", "--output", str(result_path)]
            if args.ids:
                command += ["--ids", args.ids]
            completed = subprocess.run(command, env=env, cwd=REPO)
            if result_path.exists():
                result = json.loads(result_path.read_text())
                result["sandbox_verified"] = True
                result["exit_code"] = completed.returncode
                args.output.write_text(json.dumps(result, indent=2) + "\n")
            return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
