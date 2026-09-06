#!/usr/bin/env python3
"""Host opt-in write test: both real container users edit the same Mac file.

Creates an exclusive temporary directory in this checkout, then removes only
that directory. No tracked file is modified and no model is invoked.
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jaeger_ai.core.runtime.agent_workspaces import REPO_ROOT, container_name


def main():
    receipts = []
    with tempfile.TemporaryDirectory(prefix=".agent-cross-write-", dir=REPO_ROOT) as directory:
        path = Path(directory) / "probe.py"
        path.write_text("VALUE = 1\n")
        guest_path = "/mnt/host/GitHub/JaegerAI/" + str(path.relative_to(REPO_ROOT))
        for role, expected, replacement in (("hermes", 1, 2), ("openclaw", 2, 3)):
            code = (
                "from pathlib import Path; import ast,sys; p=Path(sys.argv[1]); "
                "old=int(sys.argv[2]); new=int(sys.argv[3]); "
                "assert p.read_text()==f'VALUE = {old}\\n'; "
                "p.write_text(f'VALUE = {new}\\n'); ast.parse(p.read_text()); print(p.read_text().strip())"
            )
            args = ["/opt/homebrew/bin/container", "exec"]
            if role == "hermes":
                args += ["--user", "hermeswebui"]
            start = time.monotonic()
            completed = subprocess.run([*args, container_name(role), "python3", "-c", code,
                                        guest_path, str(expected), str(replacement)],
                                       capture_output=True, text=True, timeout=15, check=True)
            assert path.read_text() == f"VALUE = {replacement}\n", "Write not visible on Mac"
            receipts.append({"role": role, "mac_observed": path.read_text().strip(),
                             "container_observed": completed.stdout.strip(),
                             "seconds": round(time.monotonic()-start, 4)})
    print(json.dumps({"ok": True, "receipts": receipts, "probe_removed": not Path(directory).exists()}, indent=2))


if __name__ == "__main__":
    main()
