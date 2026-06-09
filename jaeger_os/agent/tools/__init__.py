"""Built-in tools for Jaeger — one file per category.

Mirrors python_pydantic_ai/core/tools/ for cross-framework structural
parity. Use either form:

    from jaeger_os.agent import tools             # then tools.get_time(...)
    from jaeger_os.agent.tools import get_time    # direct import

Categories:

  • _common.py        — bind() + audit log + sandbox resolver + git autocommit
  • files.py          — file_write, file_read, list_skill_dir  (sandboxed)
  • time_and_math.py  — get_time, calculate, system_status
  • memory.py         — remember, recall, forget, list_facts, search_memory
  • scheduling.py     — schedule_prompt, list_schedules, cancel_schedule
  • web.py            — web_search, get_weather
  • code.py           — run_python
  • speak.py          — speak (text or workspace file), warm_kokoro
  • vision.py         — look_at, generate_image (Moondream2 + SDXL-Turbo)
  • host.py           — open_on_host (macOS: URL / file / app)
  • credentials.py    — get_credential, list_credentials
  • delegation.py     — ask_user, help_me, delegate
"""

from __future__ import annotations

# Framework wiring (call bind() once at startup)
from ._common import (
    SandboxError,
    _audit,
    _require_layout,
    _resolve_under,
    bind,
    get_layout,
    git_autocommit,
)

# File ops (all sandboxed to <instance>/skills/)
from .files import (
    append_file,
    delete_file,
    edit_file,
    file_read,
    file_write,
    list_skill_dir,
    reset_read_tracker,
    search_files,
)

# Time / math / status
from .time_and_math import calculate, get_time, system_status

# Meta-tools — introspection over the agent's own tool registry.
from .meta import describe_tool, load_toolset

# Memory
from .memory import forget, list_facts, memory, recall, remember, search_memory

# Scheduling
from .scheduling import cancel_schedule, list_schedules, schedule_prompt

# Web
from .web import get_weather, web_fetch, web_search

# Code execution
from .code import run_python, run_shell

# Remote execution — ssh wrapper for the agent to run on other hosts
from .remote import ssh_exec

# Speak (TTS)
from .speak import (
    KOKORO_LANG,
    KOKORO_SAMPLE_RATE,
    KOKORO_VOICE,
    speak,
    warm_kokoro,
)

# Avatar (0.5 — AnimationNode driving)
from .avatar import play_timeline, set_avatar_state, warm_avatar

# Vision
from .vision import generate_image, look_at

# macOS host control
from .host import open_on_host

# Credentials
from .credentials import get_credential, list_credentials

# Coordination / meta
from .delegation import CAPABILITY_SUMMARY, ask_user, help_me

# Plugin awareness
from .plugins import list_plugins, setup_plugin

# Audio input — one-shot mic capture + whisper transcription
from .listen import listen

# Dependency install + venv execution (Phase 1/2 of Deep Think)
from .packages import install_package, list_venv_packages, run_in_venv

# Model management — list (read-only) + download + custom scan dirs
from .models import download_model, list_models, model_location

# Skill marketplace — package a skill into a shareable bundle
from .skill_market import benchmark_skill, package_skill

# Background processes — long-running work that outlives the turn
from .background import (
    check_background,
    list_background,
    pending_background,
    start_background,
    stop_background,
)

# Deep Think — agent-proposed task queueing
from .deepthink_tools import list_deep_think_queue, propose_deep_think_task

# Kanban task board
from .board import board_add, board_move, board_update, board_view, kanban

# Browser automation (Playwright) — one consolidated browser() tool
from .browser import browser

# Playbook skills — the skill() discover/read tool
from .skills import skill

# In-session task list (planning scratchpad)
from .todo import reset_todos, todo

# Self-update — the agent editing its own identity.yaml / soul.md
from .identity_tools import set_name, update_soul

# Agent self-benchmark — runs the flat bench corpus against the live
# pipeline (the model the user is actually talking to). Tier-1.
from .bench import run_benchmark

# Runtime diagnostics — fast idempotent health probe (post-boot
# counterpart to ``--doctor``).
from .diagnostics import system_health


__all__ = [
    # framework wiring
    "bind", "get_layout",
    "SandboxError", "_audit", "_require_layout", "_resolve_under", "git_autocommit",
    # files
    "file_write", "file_read", "list_skill_dir", "append_file", "delete_file",
    "edit_file", "search_files", "reset_read_tracker",
    # time_and_math
    "get_time", "calculate", "system_status",
    # memory
    "remember", "recall", "forget", "list_facts", "search_memory", "memory",
    # scheduling
    "schedule_prompt", "list_schedules", "cancel_schedule",
    # web
    "web_search", "web_fetch", "get_weather",
    # code
    "run_python", "run_shell",
    # remote execution
    "ssh_exec",
    # speak
    "speak", "warm_kokoro",
    "KOKORO_VOICE", "KOKORO_LANG", "KOKORO_SAMPLE_RATE",
    # vision
    "look_at", "generate_image",
    # host
    "open_on_host",
    # credentials
    "get_credential", "list_credentials",
    # delegation
    "ask_user", "help_me", "CAPABILITY_SUMMARY",
    # plugins
    "list_plugins", "setup_plugin",
    # audio input
    "listen",
    # dependency install + venv execution
    "install_package", "list_venv_packages", "run_in_venv",
    # model management
    "list_models", "download_model", "model_location",
    # skill marketplace
    "package_skill", "benchmark_skill",
    # background processes
    "start_background", "list_background", "check_background",
    "stop_background", "pending_background",
    # deep think
    "propose_deep_think_task", "list_deep_think_queue",
    # kanban board
    "board_view", "board_add", "board_move", "board_update", "kanban",
    # browser automation
    "browser",
    # playbook skills
    "skill",
    # in-session task list
    "todo", "reset_todos",
    # self-update (own identity / soul)
    "set_name", "update_soul",
    # agent self-benchmark
    "run_benchmark",
    # runtime diagnostics
    "system_health",
]
