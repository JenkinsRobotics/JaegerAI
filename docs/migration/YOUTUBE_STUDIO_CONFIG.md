# YouTube Studio Configuration Guide (v0.13.0)

**Date:** 2026-10-24
**Impact:** Users of the YouTube Studio feature (`jaeger channel`)

## Summary

The YouTube Studio feature is now **fully configurable**. No channel names,
host descriptions, or content rules are hardcoded.

## Configuration File

Create `~/.jaeger/instances/<instance-name>/youtube.toml`:

```toml
# ~/.jaeger/instances/jaeger/youtube.toml

[channel]
# Channel identity
channel_name = "My Build Channel"
channel_description = "a build show about woodworking, 3D printing, and home automation"

# On-screen cast descriptions (used in prompts)
host_description = "an AI host that presents, explains and narrates"
robot_description = "a robot co-host with short, dry, practical lines"

# Project info
project_name = "Workshop Build"
project_description = "a home workshop with CNC, 3D printers, and local AI"

# Privacy rules — what NOT to mention on screen
# Default: "This is a build show, not a personal show: never mention age,
#          family, parents, relationships, marriage, finances beyond the
#          project budget, or location beyond 'the workshop'. Never invent
#          costs, measurements or test results: if a number is not in the
#          brief or build logs, write [TBD]."
privacy_rules = "This is a build show, not a personal show: never mention family, finances, or exact location. Never invent numbers."

# Section header for open questions (default: "Open questions for the operator")
open_questions_header = "Open questions for the host"

# Extra context added to every prompt (optional)
extra_context = "The host is enthusiastic about open-source hardware."
```

## What Gets Generated

When you run `jaeger channel script`, the system prompt is generated from
your configuration:

```
You write episodes for the YouTube channel "My Build Channel", a build show
about woodworking, 3D printing, and home automation.

On-screen cast:
- HOST: an AI host that presents, explains and narrates.
- ROBOT: a robot co-host with short, dry, practical lines.

The host is enthusiastic about open-source hardware.

This is a build show, not a personal show: never mention family, finances,
or exact location. Never invent numbers.

Return markdown with exactly these sections, in this order:
...
```

## Defaults

If no `youtube.toml` exists, these defaults are used:

| Setting | Default |
|---------|---------|
| `channel_name` | "Your Channel Name" |
| `channel_description` | "A build show about making things with local AI, 3D printing, and CNC" |
| `host_description` | "an AI host that presents, explains and narrates" |
| `robot_description` | "a robot co-host with short, dry, practical lines" |
| `project_name` | "Your Project" |
| `project_description` | "a habitat-in-a-box living and robotics workshop built on a small budget with local AI, 3D printing and CNC" |
| `privacy_rules` | See above (generic, no personal references) |
| `open_questions_header` | "Open questions for the operator" |

## Backward Compatibility

If you were using YouTube Studio with the old hardcoded settings, **no action
is required** — the defaults are generic and safe. To restore your previous
channel-specific prompts, create the `youtube.toml` file with your settings.

## Example: Robotics Channel

```toml
[channel]
channel_name = "Bot Builds"
channel_description = "a show about building robots from scratch"
host_description = "an AI engineer who explains the build process"
robot_description = "a half-finished humanoid robot who asks questions"
project_name = "J-Bot"
project_description = "a humanoid robot built with consumer-grade parts"
privacy_rules = "Show the build, not the builder's life. No family, no finances, no address."
extra_context = "Episodes should end with a teaser for the next build step."
```

## Questions?

See [README.md](README.md) for the migration guide index.
