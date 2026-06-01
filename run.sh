#!/bin/bash
# JROS launcher — entry point for everything you do with the agent.
#
# AGENT MANAGEMENT
#   ./run.sh setup [NAME]      Create a new agent (or re-run wizard against
#                              an existing one). Default name is auto-picked.
#   ./run.sh list              List every agent installed on this machine.
#   ./run.sh delete NAME       Remove an agent (prompts to confirm).
#
# LAUNCH
#   ./run.sh                   Launch the default agent (wizard auto-fires
#                              if no instance exists yet).
#   ./run.sh --instance NAME   Launch a specific agent (wizard auto-fires
#                              if NAME doesn't exist yet).
#   ./run.sh start             Daemonised background agent.
#   ./run.sh status            Daemon status.
#
# INFO
#   ./run.sh help              Show this message.
#   ./run.sh --help            Forward to run.py's full argparse help.
#
# Any args not starting with a management subcommand fall through to
# jaeger_os/run.py, so every existing CLI flag still works unchanged.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$REPO_ROOT/.venv"

if [[ ! -d "$VENV" ]]; then
  echo "✗ .venv not found at $VENV" >&2
  echo "  run ./install.sh first" >&2
  exit 1
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"

# 0.2.6: package lives at <install_root>/jaeger_os/ (was src/jaeger_os/).
# PYTHONPATH points at the install root so ``import jaeger_os`` finds it
# without an editable install.
case ":${PYTHONPATH:-}:" in
  *":$REPO_ROOT:"*) ;;
  *) export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}" ;;
esac

# 0.2.6: the runtime resolves operator state at <install_root>/.jaeger_os/
# (instances, models, jaeger.env). install_root() defaults to the parent
# of the framework package, but we set JAEGER_HOME explicitly so the
# resolver gets a stable value regardless of how python computes
# __file__ (matters when sandbox symlinks the framework dir).
#
# Respect a pre-set JAEGER_HOME (e.g. ``source scripts/dev_env.sh``
# pointing at the in-repo sandbox) — only fall back to $REPO_ROOT when
# nothing is set. Otherwise dev_env.sh's sandbox redirect would get
# clobbered the moment ./run.sh started.
: "${JAEGER_HOME:=$REPO_ROOT}"
export JAEGER_HOME

# ── Subcommand dispatcher ────────────────────────────────────────────
#
# All management subcommands are thin shells around helpers that already
# exist in jaeger_os.core.instance and jaeger_os.main. We do the dispatch
# in bash rather than as argparse subparsers in main.py because (a)
# main.py's CLI is large and turbulent, (b) the launcher script is the
# natural place for user-facing UX, and (c) the bash form is easy to
# extend.

cmd_setup() {
  # CRITICAL — invoke via ``python -c``, NOT a heredoc.
  #
  # A heredoc form (``python - <<EOF ... EOF``) hands the heredoc body
  # to Python as stdin, which means when the wizard calls ``input()``
  # the very first read hits EOF and the whole flow dies with
  # ``EOFError: EOF when reading a line``. Using ``-c`` keeps the
  # interpreter attached to the terminal's stdin so the wizard's
  # prompts work.
  #
  # ``force=False`` so the wizard asks before backing up an existing
  # instance. Operators have lost real Lilith / agent identities to a
  # silent ``force=True`` overwrite — never again. The explicit
  # confirm in setup_wizard.py is the safety net; we keep it in place.
  # ``boot_after=False`` because this subcommand exits after the wizard
  # returns — no agent boot follows. The wizard's closing message
  # changes to "Done — launch with ./run.sh" instead of "Booting now…".
  if [[ $# -ge 1 ]]; then
    export JAEGER_SETUP_NAME="$1"
    exec python -c "import os; from jaeger_os.core.instance.setup_wizard import run_wizard; run_wizard(force=False, instance_name=os.environ['JAEGER_SETUP_NAME'], boot_after=False)"
  else
    exec python -c "from jaeger_os.core.instance.setup_wizard import run_wizard; run_wizard(force=False, boot_after=False)"
  fi
}

cmd_list() {
  exec python -c "import sys; from jaeger_os.main import _cli_list_instances; sys.exit(_cli_list_instances())"
}

cmd_delete() {
  local name="${1:-}"
  if [[ -z "$name" ]]; then
    echo "usage: ./run.sh delete NAME" >&2
    exit 2
  fi

  # Resolve the runtime instance dir via the same helper main.py uses,
  # so JAEGER_INSTANCE_DIR overrides etc. are honoured. ``python -c``
  # (not a heredoc) for the same stdin-preservation reason as the
  # interactive subcommands above — even though this one doesn't read
  # input, keeping the call style consistent makes the dispatcher
  # easier to reason about.
  local instance_dir
  instance_dir=$(JAEGER_DEL_NAME="$name" python -c "import os; from jaeger_os.core.instance.instance import resolve_instance_dir; print(resolve_instance_dir(os.environ['JAEGER_DEL_NAME']))")
  # 0.2.6: per-agent state moved INTO the instance dir. The old
  # user-layer location at jaeger_os/agents/<name>/ is no longer used —
  # delete-cmd only needs to clear the runtime instance dir.
  local user_dir=""

  local found=0
  echo "About to delete agent '$name':"
  if [[ -d "$instance_dir" ]]; then
    echo "  runtime:      $instance_dir"
    found=1
  fi
  if [[ -d "$user_dir" ]]; then
    echo "  user content: $user_dir"
    found=1
  fi
  if [[ "$found" -eq 0 ]]; then
    echo "  (nothing to delete — '$name' is not installed)" >&2
    exit 1
  fi

  echo
  echo "This is permanent. Memory, daemon state, and per-agent content"
  echo "will be removed. Persona/skills can be reinstated if you have a copy."
  echo
  read -r -p "Type the agent name to confirm: " confirm
  if [[ "$confirm" != "$name" ]]; then
    echo "Cancelled — name did not match."
    exit 1
  fi

  [[ -d "$instance_dir" ]] && rm -rf "$instance_dir"
  [[ -d "$user_dir"     ]] && rm -rf "$user_dir"
  echo "✓ deleted '$name'"
}

cmd_help() {
  cat <<'EOF'
JROS launcher — entry point for everything you do with the agent.

AGENT MANAGEMENT
  ./run.sh setup [NAME]      Create a new agent (or re-run wizard against
                             an existing one). Default name is auto-picked.
  ./run.sh list              List every agent installed on this machine.
  ./run.sh delete NAME       Remove an agent (prompts to confirm).

LAUNCH
  ./run.sh                   Launch the default agent (wizard auto-fires
                             if no instance exists yet).
  ./run.sh --instance NAME   Launch a specific agent (wizard auto-fires
                             if NAME doesn't exist yet).
  ./run.sh start             Daemonised background agent.
  ./run.sh status            Daemon status.

INFO
  ./run.sh help              Show this message.
  ./run.sh --help            Forward to run.py's full argparse help.

Examples:
  ./run.sh setup lilith       # create the lilith agent
  ./run.sh list               # see what's installed
  ./run.sh --instance lilith  # launch lilith
  ./run.sh delete eren        # remove eren after typing the name to confirm

For the full argparse surface (credentials, --doctor, --self-test, etc.):
  ./run.sh --help
EOF
}

case "${1:-}" in
  setup)
    shift
    cmd_setup "$@"
    ;;
  list|ls)
    shift
    cmd_list "$@"
    ;;
  delete|rm)
    shift
    cmd_delete "$@"
    ;;
  help)
    shift
    cmd_help "$@"
    ;;
  *)
    # Default: forward everything to run.py (handles --instance, --help,
    # bare launch, start/status/daemon, prompts, etc.).
    exec python "$REPO_ROOT/jaeger_os/run.py" "$@"
    ;;
esac
