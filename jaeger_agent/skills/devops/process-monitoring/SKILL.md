---
name: process-monitoring
description: "Check what's running, what's using resources, or whether a process/service is alive — 'what's eating my memory', 'is X running', 'check CPU usage', 'why is my fan spinning', 'is the server still up'. Load this for any 'what's my machine doing' question before reaching for raw terminal commands."
version: 1.0.0
platforms: [macos, linux]
requires_tools: [terminal]
requires_toolsets: [code]
metadata:
  jros:
    tags: [process, monitoring, cpu, memory, ps, top, lsof, launchctl]
    category: devops
    related_skills: [log-calculations]
---

# PROCESS MONITORING — READ-ONLY RECIPES

There's no dedicated process-inspection tool yet — this is `run_shell`
(exposed as `terminal`) with a fixed set of read-only recipes. Every
command below only READS system state; nothing here starts, stops, or
kills anything.

## READ-ONLY BIAS (the default posture)

Default to inspect-and-report. Only take an action (restart a service,
kill a process) when the user explicitly asked for that action — a
diagnostic question ("what's eating my memory") gets a diagnostic
answer, not an unrequested fix. When something clearly looks wrong
(a runaway process, a crashed service), SUGGEST the restart/kill
command and what it would do rather than running it — `terminal` is
tier-4 PRIVILEGED, so a destructive command still goes through
confirmation, but naming the risk up front is kinder than a bare prompt.

## THE RECIPES (macOS/Linux; note where they diverge)

```
terminal(command="ps aux | sort -rk 3 | head -15")     top CPU consumers
terminal(command="ps aux | sort -rk 4 | head -15")      top memory consumers
terminal(command="top -l 1 -n 15 -o mem")               macOS one-shot snapshot (Linux: "top -bn1 | head -25")
terminal(command="lsof -i -P | grep LISTEN")            what's listening on which port
terminal(command="lsof -p <pid>")                       what files/sockets a specific PID holds
terminal(command="launchctl list | grep <name>")        macOS: is a launchd service loaded/running
terminal(command="ps -p <pid> -o pid,ppid,%cpu,%mem,etime,command")   one process's detail + uptime
terminal(command="df -h")                               disk space by volume
terminal(command="vm_stat")                              macOS memory pressure detail
```

## SOP

1. Classify the question: CPU-heavy ("what's eating my CPU/fan"),
   memory-heavy ("what's eating my memory"), "is X running/listening",
   or "is X still alive" (service/uptime check).
2. Pick the narrowest recipe that answers it — don't run a full `ps
   aux` dump and eyeball it when `sort -rk 3|4 | head` gets straight to
   the answer.
3. Run it via `terminal`. Parse `stdout` yourself and summarize the
   top few offenders by name + number — don't paste the raw table back
   at the user as the whole answer.
4. If the answer implies a fix (one process clearly runaway, a service
   clearly down), say what you'd run to fix it and ask before running
   it — see READ-ONLY BIAS above.

## WHEN TO SUGGEST RESTART VS JUST REPORT

- **Just report**: usage is high but plausible for what's running (a
  video call, a build), or nothing is obviously wrong — give the
  numbers, let the user decide.
- **Suggest a restart**: a single process is pinned near 100% CPU with
  no drop over a re-check, memory usage on one process is growing
  unboundedly (check twice, a minute apart, before calling it a leak),
  or a service the user asked about is NOT in `launchctl list` /
  `ps` output when it should be running.
- Never claim something "is definitely leaking/hung" from a single
  snapshot — one `ps` call is a point-in-time read; say "looks high
  right now" not "confirmed leaking" unless you took two readings.

## ERROR HATCH

- `lsof`/`launchctl` not found (non-macOS) -> Linux equivalents:
  `ss -tlnp` for listening ports, `systemctl status <name>` for
  services. Don't run a macOS-only command on Linux and report the
  "command not found" as if the service itself were absent.
- Command needs elevated privileges (some `lsof -p` on other users'
  processes) -> report the permission error plainly; don't retry with
  `sudo` unasked (that's its own confirmation-worthy escalation).

## EVAL EXAMPLES

| User ask | Expected recipe |
|---|---|
| "check what's eating my memory" | ps aux sorted by %mem (or top -l1 -o mem) |
| "is telegram's bridge process running" | ps/launchctl grep for the name — report, don't restart unasked |
| "why is my fan spinning" | CPU-sorted ps/top, name the top consumer |
| "is the server on port 8080 up" | lsof -i -P | grep LISTEN, check for :8080 |

## DONE WHEN

The user has the specific numbers/process names that answer their
question, sourced from an actual command run this turn — and any
suggested fix was proposed, not silently executed.
