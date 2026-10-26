# Universal Cleanup — What Changed for All Users (v0.13.0)

**Date:** 2026-10-24
**Impact:** All users

## Summary

JaegerAI has been transformed from a personal project into a **universal,
public-facing platform**. All hardcoded personal references have been removed
and replaced with configurable, operator-specific settings.

## What Changed

### 1. No More Hardcoded Names

**Before:** Prompts and messages said "Matthew" (hardcoded).

**After:** The operator's name is detected from the OS account, or configured
in `~/.jaeger/operator.toml`:

```toml
[operator]
name = "Alex"  # Your name
```

If no name is configured, the system uses "the operator" as a fallback.

### 2. YouTube Studio is Configurable

**Before:** Hardcoded for "Matthew Walks the Way" channel.

**After:** Configure your own channel in `~/.jaeger/instances/<name>/youtube.toml`:

```toml
[channel]
channel_name = "My Build Channel"
channel_description = "a show about woodworking and robotics"
host_description = "an AI host that guides the build"
robot_description = "a sarcastic robot assistant"
project_name = "My Project"
project_description = "an indoor garden with automated watering"
```

See [YOUTUBE_STUDIO_CONFIG.md](YOUTUBE_STUDIO_CONFIG.md) for full options.

### 3. New Operator Configuration

A new configuration file `~/.jaeger/operator.toml` stores all personal
preferences:

```toml
[operator]
name = "Alex"
email = "alex@example.com"
business_name = "Alex's Robotics"
project_root = "/Users/alex/projects"
nas_path = "/Volumes/MyNAS"
youtube_channel_name = "Alex Builds"
timezone = "America/Los_Angeles"

# Custom wake word
wake_word = "jarvis"

# Email NEVER list (senders to never auto-process)
never_list = ["spam@example.com", "newsletter@shop.com"]

# Custom context added to prompts
custom_context = "I work on robotics. I prefer concise answers."
```

See [OPERATOR_CONFIG.md](OPERATOR_CONFIG.md) for all options.

### 4. NAS/File Storage Paths are Configurable

**Before:** Hardcoded `/Volumes/Jenkins_Robotics`.

**After:** Configure in `operator.toml`:

```toml
[operator]
nas_path = "/Volumes/YourNAS"
project_root = "/Users/you/projects"
```

## What Didn't Change

- All memory, sessions, and data are preserved
- Gateway, WebUI, CLI, and all interfaces work the same
- Approval gates, PolicyKernel, and security are unchanged
- Model providers and configurations are unchanged

## Action Required

**None for most users.** The system auto-detects your name from the OS.

**Optional:** Create `~/.jaeger/operator.toml` to customize:

```bash
# Generate a template
jaeger config operator init

# Edit it
$EDITOR ~/.jaeger/operator.toml
```

If you were using YouTube Studio, create
`~/.jaeger/instances/jaeger/youtube.toml` with your channel settings.

## Questions?

See [README.md](README.md) for the full migration guide index.
