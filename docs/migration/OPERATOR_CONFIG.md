# Operator Configuration Guide (v0.13.0)

**Date:** 2026-10-24
**Impact:** All users

## Summary

JaegerAI now has a **universal operator configuration system**. All personal
preferences are stored in `~/.jaeger/operator.toml` and can be overridden
per-instance.

## Configuration Files

### Global: `~/.jaeger/operator.toml`

Applies to all instances:

```toml
[operator]
name = "Alex"
email = "alex@example.com"
business_name = "Alex's Workshop"
project_root = "/Users/alex/projects"
nas_path = "/Volumes/WorkshopNAS"
timezone = "America/Los_Angeles"
language = "en"

# YouTube
youtube_channel_name = "Alex Builds"
youtube_channel_handle = "@alexbuilds"

# Voice
wake_word = "jarvis"
voice_enabled = true

# Email NEVER list
never_list = [
    "spam@example.com",
    "newsletter@shop.com",
    "noreply@bank.com",
]

# Extra allowed paths for tools
allowed_paths = [
    "/Users/alex/special-project",
]

# Notifications
ntfy_url = "https://your-host.ts.net:8443/ntfy/jaeger"
ntfy_token = "tk_your_token_here"  # Never logged

# Custom context for prompts
custom_context = """
I'm a robotics engineer. I prefer concise, technical answers.
I work on humanoid robots and home automation.
"""
```

### Per-Instance: `~/.jaeger/instances/<name>/operator.toml`

Overrides global settings for a specific instance:

```toml
[operator]
name = "Alex (Work)"
business_name = "Alex Robotics Inc"
youtube_channel_name = "Alex Robotics Official"
```

## Configuration Precedence

1. **Environment variables** (highest priority — for secrets)
2. **Instance config** (`instances/<name>/operator.toml`)
3. **Global config** (`~/.jaeger/operator.toml`)
4. **OS detection** (name from system account)
5. **Built-in defaults** (generic fallbacks)

## Environment Variables

Override any setting via environment:

| Variable | Config Key | Purpose |
|----------|-----------|---------|
| `JAEGER_OPERATOR_NAME` | `name` | Operator display name |
| `JAEGER_NTFY_URL` | `ntfy_url` | Notification endpoint |
| `JAEGER_NTFY_TOKEN` | `ntfy_token` | Notification auth token |
| `JAEGER_WAKE_WORD` | `wake_word` | Voice wake word |

## Creating a Config

Generate a template:

```bash
# Creates ~/.jaeger/operator.toml with all options commented out
jaeger config operator init

# Or force-overwrite existing
jaeger config operator init --force
```

## What Uses This Config?

| Feature | Config Keys Used |
|---------|-----------------|
| Greetings & prompts | `name`, `custom_context` |
| Initiative messages | `name` |
| YouTube Studio | `youtube_channel_name`, `youtube_channel_handle` |
| Notifications | `ntfy_url`, `ntfy_token` |
| Voice | `wake_word`, `voice_enabled` |
| Email tools | `never_list` |
| File tools | `allowed_paths`, `project_root`, `nas_path` |
| Honcho peer name | `name` |
| Timezone-aware scheduling | `timezone` |

## Auto-Detection

If no `name` is configured, JaegerAI detects it from:

1. **OS account full name** (GECOS field, e.g., "Alex Smith" → "Alex")
2. **OS account short name** (e.g., "alex")
3. **Home directory name** (e.g., `/Users/alex` → "Alex")

Service accounts ("root", "admin", "daemon") are rejected.

## Security

- Config file is created with `0600` permissions (owner read/write only)
- Tokens (like `ntfy_token`) are **never logged**
- Environment variables take precedence for secrets in CI/CD

## Example: Full Setup

```bash
# 1. Generate template
jaeger config operator init

# 2. Edit
cat > ~/.jaeger/operator.toml << 'EOF'
[operator]
name = "Jordan"
business_name = "Jordan's Lab"
project_root = "/Users/jordan/lab"
nas_path = "/Volumes/LabNAS"
youtube_channel_name = "Jordan Builds Robots"
wake_word = "hey robot"
custom_context = "I build small robots. Keep answers under 100 words."
EOF

# 3. Verify
jaeger config operator show

# 4. Restart Gateway to pick up changes
jaeger gateway daemon restart
```

## Questions?

See [README.md](README.md) for the migration guide index.
