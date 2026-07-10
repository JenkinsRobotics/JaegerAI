# JROS — manual test prompts

Copy-paste prompts to exercise the agent's tools across the desktop window and
Telegram. Each notes the tool(s) it should trigger and what success looks like.
Watch the **activity stream** (desktop) or **👀 + typing** (Telegram) for the
live "working" feedback. Tool names are the real registered ones.

---

## Time & math
- `What time is it right now?` — `get_time` (must call the tool, never guess a date)
- `What's an 18% tip on $73.40 split 3 ways?` — `calculate`

## Timers & reminders (scheduling)
- `Remind me in 2 minutes to stretch.` — `schedule_prompt` (one-shot; wait → it fires)
- `Every weekday at 8am, give me the weather.` — `schedule_prompt` (recurring)
- `What reminders do I have set?` — `list_schedules`
- `Cancel the stretch reminder.` — `cancel_schedule`

## Kanban board
- `Add "wire up the OTA updater" to my board under To Do, tagged 0.6.` — `board_add`
- `Show me my board.` — `board_view` / `kanban`
- `Move "wire up the OTA updater" to In Progress.` — `board_move`

## Planning
- `Plan how you'd add a dark-mode toggle to a web app — break it into a todo list.` — `todo`
- `Spend background time researching the best local TTS options and report back.` — `propose_deep_think_task` (the plan→research→execute loop)
- `What's in your deep-think queue?` — `list_deep_think_queue`

## Coding (multi-step — exercises the loop)
- `Write a Python function for the nth Fibonacci number, then run it for n=20.` — `write_file` + `run_python`
- `Install the humanize package and print 1234567 as words.` — `install_package` + `run_in_venv`
- `Make a bar chart of [3,7,2,9,5] and save it as a PNG in my workspace.` — `install_package` (matplotlib) + `run_in_venv` + a file

## Web & research
- `What's the weather in Tokyo right now?` — `get_weather`
- `Search the web for the current Python version and what's new in it.` — `web_search` + `web_fetch` (also tests "confirm facts with the web")

## Memory (cross-session — works across desktop ↔ Telegram)
- `Remember that my dog's name is Biscuit, a corgi.` — `remember`
- *(later / a new conversation / the other interface)* `What's my dog's name?` — `recall` / `search_memory`

## Skills
- `What skills do you have for making comics?` — `skill` (playbook discover)
- `Write a new skill that converts Celsius to Fahrenheit with a smoke test, then reload it.` — `write_file` + `reload_skills`

## Vision & images
- `Generate an image of a robot drinking coffee.` — `generate_image`
- `Take a screenshot and tell me what's on screen.` — `look_at`

## Voice
- `Say "systems online" out loud.` — `speak` (TTS; should also print the text)

## Plugins / messaging
- `What plugins do I have and which are set up?` — `list_plugins`
- `Send a Telegram message to <chat_id> saying hi.` — `send_message` (telegram must be active)

## Background work
- `Start a background job that counts to 100 slowly, then check on it.` — `start_background` + `check_background`

## Persona / identity
- `What are your personality traits?` — `read_traits`
- `Be more concise and direct from now on.` — `adjust_trait`

## Diagnostics
- `Run a self-check and tell me if anything's wrong.` — `self_check`
- `How much memory and disk are you using?` — `system_status`

---

## Verify the hardened behaviors (this session's fixes)
- **No confabulation:** `What's my bank's API key?` → should say it doesn't have/can't access one, NOT invent it. `Run the install-plugin telegram command.` → should say there's no such command and use the real flow.
- **Ask when unsure:** `Set up my email integration.` → should ASK which provider / for credentials, not guess.
- **Web-verify:** `What's the latest version of macOS?` → should `web_search` rather than answer from stale training.
- **Steering (desktop):** send `Write a long story about a dragon.` then immediately `actually, make it a detective story.` → the running turn should redirect (watch the activity stream).
- **Cross-interface:** On **Telegram**: `Add "buy milk" to my board.` Then on **desktop**: `What's on my board?` → "buy milk" should be there (shared board + memory; conversation history is per-channel, but the board/memory are shared).

## Big agentic combo (stress the loop + activity stream)
- `Research the top 3 local LLM inference engines, make a comparison table, save it as a markdown file in my workspace, and add a board task to "try the winner".`
  — web + file + board, multi-step. The activity stream should show each tool as it runs.
