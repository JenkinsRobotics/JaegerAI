# Getting Started with JaegerAI

Welcome! This guide walks you through your first 10 minutes with JaegerAI — from installation to your first conversation with your AI agent.

---

## What You'll Build

By the end of this guide, you'll have:
- ✅ JaegerAI installed and running
- ✅ Your first AI agent created with a personality
- ✅ A conversation running in your chosen interface (Mac app, web, or terminal)
- ✅ Persistent memory that remembers you across sessions

**Time required:** ~15 minutes (plus installation time)

---

## Step 1: Install JaegerAI

### Option A: Double-Click Installer (macOS — Easiest)

1. Download the repository:
   ```bash
   git clone https://github.com/JenkinsRobotics/JaegerAI.git
   cd JaegerAI
   ```
   Or download as ZIP from GitHub and extract.

2. Double-click **`Install Jaeger AI.command`**

3. Wait 5-15 minutes for installation to complete.

### Option B: Command Line (All Platforms)

```bash
# Clone the repository
git clone https://github.com/JenkinsRobotics/JaegerAI.git
cd JaegerAI

# Run the installer
./install.sh
```

### Option C: One-Line Installer (Advanced)

```bash
curl -fsSL https://raw.githubusercontent.com/JenkinsRobotics/JaegerAI/master/scripts/install.sh | bash
```

### Prerequisites

| Requirement | macOS | Linux |
|-------------|-------|-------|
| Python 3.11 or 3.12 | `brew install python@3.12` | `sudo apt install python3.12` |
| C compiler | `xcode-select --install` | `sudo apt install build-essential` |
| Git | Pre-installed | `sudo apt install git` |
| Disk space | ~15 GB free | ~15 GB free |
| RAM | 8 GB+ (16 GB recommended) | 8 GB+ |

---

## Step 2: Create Your First Agent

An **agent** is your AI companion — it has its own personality, memory, and configuration.

```bash
./jaeger agent create
```

This launches an **interactive setup wizard** that asks:

### 1. Choose a Character
Pick a personality for your AI:
- **Assistant** — Professional, helpful, neutral
- **Jarvis** — Polished, witty, efficient (Iron Man style)
- **Lilith** — Mysterious, intellectual, poetic
- **Or create your own** — Custom personality

> 💡 **Tip:** You can change the character later. The agent's memory and identity persist.

### 2. Choose a Model
Select how your AI "thinks":

| Option | Best For | Requires |
|--------|----------|----------|
| **Local model (GGUF)** | Privacy, offline use | 8+ GB RAM, downloaded model |
| **Ollama** | Easy local models | [Ollama](https://ollama.ai) installed |
| **Cloud API** | Best quality, no local compute | API key (OpenAI, Anthropic, etc.) |
| **CLI backend** | Using installed tools | Claude Code, Codex, Gemini CLI |

> 💡 **New to AI?** Start with **Ollama** (free, easy) or a **cloud API** (best quality).

### 3. Set Permissions
Choose how much control the agent has:
- **Ask me before each action (recommended)** — Safest. Agent asks before reading files, running commands, etc.
- **Auto-allow everything** — Faster, but less secure. Only for trusted environments.

### 4. Choose Interface
Pick how you'll interact:
- **GUI (Mac app)** — Default. Opens a native macOS window.
- **TUI (Terminal)** — For terminal users. Runs in your current terminal.
- **Voice** — Experimental. Mic input + spoken responses.

### 5. Review & Create
Review your choices and confirm. The wizard will:
- Create the agent's identity and configuration
- Download/warm up models (if local)
- Verify all systems are working

---

## Step 3: Start Chatting

### Mac App (Default)
```bash
./jaeger
```
Opens a native macOS window with a chat interface.

### Terminal UI
```bash
./jaeger --tui
# or
./jaeger dev --tui
```

### Web Browser
```bash
./jaeger webui start
```
Then open [http://localhost:8790](http://localhost:8790) in your browser.

### Voice Mode
```bash
./jaeger --voice
```

### One-Shot Commands
```bash
./jaeger "What's the weather in Tokyo?"
./jaeger "Summarize this file: ~/Documents/notes.txt"
```

---

## Step 4: Configure Your Agent

### Change the Character
```bash
./jaeger personality list           # See available characters
./jaeger personality use jarvis     # Switch to Jarvis
```

### Change the Model
```bash
# In the WebUI/Mac app: /model use <provider> <model>
# Or edit the config:
$EDITOR ~/.jaeger/instances/<agent-name>/config.yaml
```

### Customize Your Preferences
Create `~/.jaeger/operator.toml`:

```toml
[operator]
name = "Your Name"              # How the agent addresses you
business_name = "Your Company"  # Your business/projects
wake_word = "jarvis"            # Custom voice wake word
custom_context = """
I work on robotics projects.
I prefer concise, technical answers.
"""
```

See [docs/migration/OPERATOR_CONFIG.md](migration/OPERATOR_CONFIG.md) for all options.

---

## Step 5: Make It Yours

### Add Skills
Skills are reusable procedures the agent can learn:

```bash
./jaeger skills list              # See installed skills
./jaeger skill create my-skill    # Create a new skill
```

### Set Up Memory
Your agent remembers you automatically. View/edit memory:

```bash
./jaeger memory list              # See all memories
./jaeger memory search "project"  # Search memories
```

### Schedule Tasks
```bash
./jaeger "Every morning at 9am, summarize my calendar"
# The agent will schedule this and run it automatically
```

---

## Common First-Run Issues

### "Python not found"
Install Python 3.11 or 3.12:
```bash
# macOS
brew install python@3.12

# Linux
sudo apt install python3.12 python3.12-venv
```

### "Xcode Command Line Tools not found"
```bash
xcode-select --install
```
Then re-run `./install.sh`.

### "No model available"
- **Cloud:** Add your API key in the setup wizard or `~/.jaeger/instances/<name>/config.yaml`
- **Local:** Install [Ollama](https://ollama.ai) and run `ollama pull llama3.2`

### "Permission denied" errors
The agent asks before running commands or accessing files. Approve when prompted, or adjust in:
```bash
./jaeger config permissions     # View/edit permission settings
```

### "Port already in use"
Another service is using the WebUI port (8790). Check with:
```bash
./jaeger webui status
lsof -i :8790                    # See what's using the port
```

---

## Next Steps

- **[Configure your operator profile](migration/OPERATOR_CONFIG.md)** — Customize how the agent addresses you
- **[Set up YouTube Studio](migration/YOUTUBE_STUDIO_CONFIG.md)** — Automate video content
- **[Explore commands](COMMANDS.md)** — Full CLI reference
- **[Understand the architecture](architecture/ARCHITECTURE.md)** — How JaegerAI works
- **[Security & trust model](TRUST.md)** — What stays on your device
- **[Join the community](#community)** — Get help and share your setup

---

## Getting Help

- **Documentation:** [docs/](.) directory
- **CLI help:** `./jaeger --help` or `./jaeger <command> --help`
- **Diagnostics:** `./jaeger doctor` — Checks your setup
- **Issues:** [GitHub Issues](https://github.com/JenkinsRobotics/JaegerAI/issues)
- **Discussions:** [GitHub Discussions](https://github.com/JenkinsRobotics/JaegerAI/discussions)

---

## What Makes JaegerAI Different?

| Feature | JaegerAI | Typical AI Chatbots |
|---------|----------|---------------------|
| **Persistent identity** | Remembers you across sessions, devices, and restarts | Starts fresh every conversation |
| **Works on your computer** | Reads files, runs code, controls apps (with permission) | Only talks, no actions |
| **Proactive** | Schedules tasks, monitors, reaches out | Only responds when asked |
| **Multiple interfaces** | Mac app, web, terminal, voice — same agent everywhere | One interface only |
| **Your data stays yours** | Memory, approvals, audit log stay on your device | Data goes to their servers |
| **Learns skills** | Researches, writes, and versions its own procedures | Fixed capabilities |

---

*Ready to build your AI companion? Run `./jaeger agent create` and let's go!* 🚀
