<!-- JAEGER-MAC-CONNECTION-BEGIN -->
## Mac connection and shared source checkout

You are running in a Linux Apple container on Matthew's Mac, not on the rack PC.
Your terminal/exec tool runs in Linux. For macOS operations use your authenticated
host MCP tools. Discover their actual names with the MCP inventory: look for
`host_environment`, `capabilities_inspect`, `workspace_read`, `workspace_write`,
`git_status`, and `service_status`. Call `host_environment` for current Mac facts;
do not infer Mac specifications from container `uname`, RAM, or CPU limits.

The direct Mac gateway is `192.168.64.1` (no Tailscale required): native Jaeger
MCP `http://192.168.64.1:8811/mcp`, host tools `http://192.168.64.1:8813/mcp`,
A2A `http://192.168.64.1:8812/.well-known/agent-card.json`.
Use your existing native MCP configuration for authentication; never print keys.

For JaegerAI code work, use `/mnt/host/GitHub/JaegerAI`. It is a live read/write
bind mount of the Mac checkout, NOT a copied repository. The host tool's
`host_environment` response gives its canonical macOS path. `/workspace` is
for general artifacts; `/workspace/GitHub/JaegerAI` is not the canonical checkout.
GitHub is directly mounted at `/mnt/host/GitHub`. Additional configured locations
(`/mnt/host/Desktop`, `/mnt/host/Documents`, `/mnt/nas/Jenkins_Robotics`,
`/mnt/nas/Personal-Drive`) require macOS privacy approval before direct mounting.
Do not claim those paths exist without checking. Use authorized host MCP tools
and their approved macOS roots where direct mounts are unavailable. NAS
availability can change: probe before claiming access.

When asked about connectivity, report promptly after bounded probes (5 seconds
per endpoint), separating verified results from configured/unknown access.
Use `python3 /mnt/host/GitHub/JaegerAI/scripts/agent-mac-check.py --role hermes`
for Hermes, or the same command with `--role openclaw` for OpenClaw.
The default check is read-only. `--write-probe` creates and removes its own
temporary file in the repo to test actual write/edit/rename access.

Before editing: read the repo instructions and `git status`; preserve others'
changes, use a worktree for concurrent tasks, and verify the actual diff. A patch
to JaegerAI does not automatically restart any agent. Do not restart your own
container, change live `.jaeger_ai` state, credentials, mounts, or service config
while doing ordinary code work. Use Linux environments for Linux tests; the
repo's Mac `.venv` is not usable in the container. For final Mac tests/restarts,
hand off to the Mac-side operator. Commit only requested, reviewed changes;
do not push without explicit authorization.
<!-- JAEGER-MAC-CONNECTION-END -->
