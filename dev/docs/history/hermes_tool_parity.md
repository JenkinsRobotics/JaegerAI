# Tool parity — Jaeger-OS vs. Hermes Agent

A 2026-05 audit of [Hermes Agent](https://github.com/NousResearch/hermes-agent)'s
built-in tool registry against Jaeger-OS's. Hermes ships ~70 tools, but
most are platform-specific plugins (Spotify, Feishu, Yuanbao, Home
Assistant, kanban, X, RL training, Discord admin). Comparing only the
**general-purpose agent tools**, the surfaces are close.

## Covered — Jaeger-OS has an equivalent

| Hermes | Jaeger-OS |
|---|---|
| `read_file` / `write_file` | `file_read` / `file_write` |
| `patch` | **`edit_file`** (added in this pass) |
| `search_files` | **`search_files`** (added in this pass) |
| `terminal` | `run_shell` |
| `process` | `start_background` / `list_background` / `check_background` / `stop_background` |
| `web_search` / `web_extract` | `web_search` / `web_fetch` |
| `memory` | `remember` / `recall` / `forget` / `list_facts` |
| `session_search` | `search_memory` |
| `execute_code` | `run_python` / `run_in_venv` |
| `clarify` | `ask_user` |
| `cronjob` | `schedule_prompt` / `list_schedules` / `cancel_schedule` |
| `delegate_task` | `delegate` |
| `skill_view` / `skill_manage` / `skills_list` | `reload_skills` / `package_skill` / `benchmark_skill` + `list_skill_dir` / `file_read` |
| `vision_analyze` | `look_at` |
| `image_generate` | `generate_image` |
| `text_to_speech` | `speak` |
| `send_message` | `send_message` |

Jaeger-OS additionally has tools Hermes does not: `get_time`,
`calculate`, `get_weather`, `system_status`, per-instance venv
(`install_package` / `run_in_venv` / `list_venv_packages`), model
management (`list_models` / `download_model`), Deep Think
(`propose_deep_think_task` / `list_deep_think_queue`), plugin awareness
(`list_plugins` / `setup_plugin`), `listen`, and `open_on_host`.

## Closed in this pass

- **`edit_file(path, old, new)`** — surgical find/replace edit, the
  equivalent of Hermes `patch`. Changing one region of a file no longer
  means regenerating (and risking truncating) the whole thing.
- **`search_files(query, path)`** — recursive content grep over the
  skills sandbox.
- **`file_read` pagination** — `offset` / `limit` line-range params for
  large files, matching Hermes `read_file`.

That brings the registered tool count to **50**.

## Deliberately not built — large subsystems, not single tools

- **Browser automation** (Hermes' 12 `browser_*` tools) — needs a real
  browser driver (Playwright / CDP), a snapshot/ref model, and a vision
  loop. A genuine feature project, not a tool. *This is the most
  user-visible gap* — the agent currently cannot drive a web page.
- **`computer_use`** — desktop control via screenshots + clicks. Same
  scale as browser automation.
- **`video_analyze` / `video_generate`** — deferred by project decision
  (no AI video for now).

## Not applicable

`mixture_of_agents` (Jaeger-OS uses `delegate` + the external-model
pipeline), Home Assistant, and the platform plugins (Spotify, Feishu,
Yuanbao, kanban, X) are out of scope for the core framework — they
belong in optional plugins if ever wanted.
