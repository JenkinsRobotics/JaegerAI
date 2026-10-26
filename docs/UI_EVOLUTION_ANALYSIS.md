# JaegerAI UI Evolution — Comprehensive Analysis

**Date:** 2026-10-25
**Scope:** Desktop UI, Web UI, IDE UI — Old vs New vs Aether Design Language
**Sources:** Desktop archives, GitHub projects, Jenkins Robotics ecosystem

---

## Executive Summary

JaegerAI's UI has evolved through **three distinct design languages**:

1. **OLD (Archived 2026-10-17):** Terminal/hacker aesthetic — dark, monospace, cyan/gold accents
2. **AETHER (Design System):** Engineering workbench — CAD-inspired, neutral, professional
3. **NEW (Current 2026-10-25):** Modern AI assistant — Linear/Vercel-inspired, indigo/violet

The goal is to **merge the best of all three** into a cohesive, production-grade UI.

---

## 1. DESKTOP UI (macOS App)

### OLD Version (Archived)

**Tech Stack:** SwiftUI + AppKit (MenuBarExtra, macOS 13+)

**Visual Appearance — "Terminal/Hacker" Aesthetic:**
```
┌─────────────────────────────────────────────────────────┐
│  TERMINAL DARK PALETTE                                  │
│  ─────────────────────────                              │
│  Background:  #0B0E14  (near-black)                     │
│  Panel:       #131720  (dark blue-gray)                 │
│  Accent:      #3aa0ff  (bright cyan-blue)               │
│  Text:        #DDE2EA  (off-white)                      │
│  Font:        SF Mono / Menlo, 13px                     │
└─────────────────────────────────────────────────────────┘
```

**Key Components:**

| Component | Size | Features |
|-----------|------|----------|
| **Menu Bar Tray** | 320px dropdown | Avatar + name + status, "Chat with Jaeger" button, settings gear |
| **Chat Window** | 940×680 | Terminal-style transcript with `❯` prompts, sidebar with sessions, tabs (Chat/Kanban/Tasks/Skills/Avatar) |
| **Floating Pill** | 720×248 | Global hotkey (⌥Space), Claude-style quick input, forced-light card |
| **Voice Orb** | 240×240 min | Animated spectrum ring (cyan→pink), idle/thinking/speaking states |
| **Settings HUD** | 900×600 | Dark green-tinted, icon rail, agent configuration |
| **First Boot** | 840×720 | Conversational onboarding, hardware bench |

**What It Looked Like:**
```
┌─────────────────────────────────────────────────────────┐
│  ● Jaeger (menu bar icon)                               │
│     │                                                   │
│     ▼ ┌─────────────────┐                               │
│       │ 🤖 Jaeger    ●   │  "Standing by"              │
│       │ ─────────────────│                             │
│       │ [Chat with Jaeger]│  ← prominent cyan button    │
│       │ ⚙️ Settings  ⏻  │                             │
│       └─────────────────┘                               │
│                                                         │
│  Chat Window (when opened):                            │
│  ┌─────────┬──────────────────────────────────────────┐│
│  │ SEARCH  │  ❯ What is quantum computing?           ││
│  │ [+New]  │                                          ││
│  │         │  Jaeger: Quantum computing is...        ││
│  │ PINNED  │                                          ││
│  │ 🤖 Jaeger│  [Chat] [Kanban] [Tasks] [Skills]...    ││
│  │ RECENT  │  ──────────────────────────────────────  ││
│  │ • Chat 1│  [+] [Mode ▼] [Type here...    ] [🎤] [➤]││
│  └─────────┴──────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────┘
```

**Strengths:**
- ✅ Native macOS feel
- ✅ Fast (Swift)
- ✅ Menu bar presence
- ✅ Voice orb was beautiful
- ✅ Terminal aesthetic matched the AI/dev audience

**Weaknesses:**
- ❌ Terminal aesthetic felt dated (2010s hacker vibe)
- ❌ Inconsistent with Aether brand
- ❌ Two implementations (Swift + PySide6) = maintenance burden
- ❌ No light mode (forced dark)
- ❌ Complex window management

---

### NEW Version (Current macos-shell)

**Tech Stack:** Swift + AppKit + WKWebView (loads web UI)

**Visual Appearance:** Now loads the **modern web UI** in a native window — gets all the new design automatically.

**Changes from OLD:**
- Uses WKWebView to render the React UI
- Native window chrome (traffic lights)
- Bridge protocol for native features (voice, camera, etc.)
- Single codebase with web UI

---

## 2. WEB UI

### OLD Version (Archived — Hermes WebUI Fork)

**Tech Stack:** Vanilla JavaScript + Python server (no React!)

**Visual Appearance — "Warm Gold Terminal":**
```
┌─────────────────────────────────────────────────────────┐
│  HERMES WEBUI FORK PALETTE                              │
│  ─────────────────────────────                          │
│  Light Mode:                                            │
│    Background:  #FEFCF7  (warm cream)                   │
│    Accent:      #B8860B  (dark goldenrod)               │
│    Text:        #1A1610  (warm black)                   │
│                                                         │
│  Dark Mode:                                             │
│    Background:  #0D0D1A  (navy-black)                   │
│    Accent:      #FFD700  (gold)                         │
│    Text:        #FFF8DC  (cornsilk)                     │
│                                                         │
│  20+ Skins: default, ares, mono, graphite, codex,       │
│  terracotta, slate, catppuccin, nous, geist, neon...    │
└─────────────────────────────────────────────────────────┘
```

**Layout:**
```
┌─────────────────────────────────────────────────────────┐
│ [Profile ▼] Jaeger  [● Connected] [🕐] [🎤] [+] [↻]     │
├────┬────────────────────────────────────────────────────┤
│Rail│  Sidebar                                           │
│    │  ┌─────────────────┐  ┌─────────────────────────┐ │
│ 📝 │  │  Session Search │  │                         │ │
│ 📋 │  │  • Session 1    │  │   Main Content Area     │ │
│ 📊 │  │  • Session 2    │  │   (Chat/Tasks/Kanban)   │ │
│ 🧠 │  │                 │  │                         │ │
│ 📁 │  │  Projects       │  │  ┌───────────────────┐  │ │
│ 👤 │  │  Scheduled      │  │  │ 👤 You: Hello!    │  │ │
│ ✅ │  │  Settings       │  │  └───────────────────┘  │ │
│    │  │                 │  │  ┌───────────────────┐  │ │
│    │  │                 │  │  │ 🤖 Assistant: Hi! │  │ │
│    │  │                 │  │  └───────────────────┘  │ │
│    │  │                 │  │                         │ │
│    │  │                 │  │  [Type...        ] [➤] │ │
└────┴─────────────────┴────────────────────────────────┘
```

**Features (OLD):**
- Chat with streaming, markdown, syntax highlighting (Prism.js)
- 20+ visual skins
- Tasks/Cron management
- Kanban board
- Skills library
- Memory viewer
- Workspaces
- Terminal panel (xterm.js)
- Voice integration
- PWA support
- i18n (full translation system)

**Problems with OLD:**
- ❌ No React — vanilla JS, no components
- ❌ No TypeScript — no type safety
- ❌ 2500+ line CSS file
- ❌ Global mutable state
- ❌ Hermes branding (forked, not native)
- ❌ Confusing "Profiles" vs "Agents"
- ❌ No tests
- ❌ Hard to maintain

---

### NEW Version (Current — React)

**Tech Stack:** React 19 + TypeScript + Vite

**Visual Appearance — "Aether Studio Workbench":**
```
┌─────────────────────────────────────────────────────────┐
│  AETHER DESIGN LANGUAGE (from AetherStudio)             │
│  ─────────────────────────────────────                  │
│  Dark Mode (Default):                                   │
│    App BG:      #0e1013  (deep neutral black)           │
│    Shell BG:    #171a20  (dark blue-gray)               │
│    Panel BG:    #171a20  (same as shell)                │
│    Inset BG:    #1e222a  (slightly lighter)             │
│    Accent:      #4c9dff  (engineering blue)             │
│    Text:        #e7edf3  (soft white)                   │
│    Text Dim:    #8b96a5  (muted gray)                   │
│    OK:          #32cf84  (green)                        │
│    Warn:        #e7a843  (amber)                        │
│    Error:       #ff5a62  (red)                          │
│                                                         │
│  Light Mode:                                            │
│    App BG:      #ececee  (light gray)                   │
│    Panel BG:    #fbfbfc  (near white)                   │
│    Accent:      #2f7fe0  (darker blue)                  │
│    Text:        #1c1e21  (near black)                   │
│                                                         │
│  Typography:                                            │
│    Font:   -apple-system, "SF Pro Text", Inter          │
│    Body:   12px / 1.5 line-height                       │
│    Weight: 650 (semibold for emphasis)                  │
│                                                         │
│  Geometry:                                              │
│    Radius:     7px (controls), 8px (buttons)            │
│    Topbar:     56px                                     │
│    Sidebar:    250px                                    │
│    Rail:       42px                                     │
│    Row:        36px                                     │
│    Grid:       4px                                      │
└─────────────────────────────────────────────────────────┘
```

**Layout:**
```
┌─────────────────────────────────────────────────────────┐
│  ┌────────┐  JaegerAI                              [🌙] │
│  │  🔮    │  ─────────────────────────────────────────  │
│  │(logo)  │                                             │
│  ├────────┤   ┌─────────────────────────────────────┐   │
│  │ 🔍     │   │                                     │   │
│  │ [+ New]│   │    How can I help you today?        │   │
│  ├────────┤   │                                     │   │
│  │ AGENTS │   │    [✨ Explain] [🤖 Code] [💡 Ideas]│   │
│  │ 🤖 As..│   │                                     │   │
│  │   ●    │   │  ┌─────────────────────────────┐    │   │
│  │ 🤖 Ja..│   │  │ 👤 What is quantum...     │    │   │
│  │   ●    │   │  └─────────────────────────────┘    │   │
│  │ 🤖 Li..│   │                                     │   │
│  │   ○    │   │  ┌─────────────────────────────┐    │   │
│  └────────┘   │  │ 🤖 Quantum computing is...  │    │   │
│               │  └─────────────────────────────┘    │   │
│  [⚙️ Settings]│           Just now  [📋][🔄][👍]     │   │
│               │                                     │   │
│               │  ┌─────────────────────────────┐    │   │
│               │  │ 📎 🎤 Message Jaeger...   ➤ │    │   │
│               │  └─────────────────────────────┘    │   │
│               └─────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

**Key Improvements:**
- ✅ React 19 + TypeScript — type-safe, component-based
- ✅ Modern design system (Aether tokens)
- ✅ Dark + Light themes
- ✅ Smooth animations
- ✅ Command palette (Cmd+K)
- ✅ Syntax highlighting (Shiki)
- ✅ File upload with preview
- ✅ Error boundaries
- ✅ Responsive (mobile/tablet/desktop)
- ✅ Clean separation of concerns

---

## 3. IDE EXTENSION UI (VS Code)

### OLD Version (Archived)

**Tech Stack:** Plain JavaScript + VS Code Webview API

**Location:** `jaeger_ai/interfaces/ide/`
**Extension ID:** `jenkins-robotics.jaeger-ide`

**Visual Appearance:**
- Matched VS Code's native theme
- Sidebar webview panel
- Used Aether design tokens (`tokens.css`, `motion.css`, `view.css`)

**Features:**
- Chat in sidebar
- Code actions
- Gateway connection
- Caller token from Keychain

**Layout:**
```
┌─────────────────────────────────────┐
│  VS CODE SIDEBAR                    │
│  ─────────────────────────          │
│  ┌─────────────────────────────┐    │
│  │ JAEGER                      │    │
│  │ ─────────────────           │    │
│  │                             │    │
│  │  👤 You:                    │    │
│  │  Hello!                     │    │
│  │                             │    │
│  │  🤖 Jaeger:                 │    │
│  │  Hi! How can I help?        │    │
│  │                             │    │
│  │  ─────────────────────────  │    │
│  │  [Type message...      ] ➤  │    │
│  └─────────────────────────────┘    │
└─────────────────────────────────────┘
```

**Problems:**
- ❌ Limited features
- ❌ Plain JS (no TypeScript)
- ❌ Basic styling
- ❌ Not well integrated

---

### NEW Version (Current)

**Status:** Early development (`jaeger_ai/interfaces/ide/`)

**Should Match:** GitHub Copilot Chat, Cursor, Windsurf

**Target Features:**
- Sidebar chat panel
- Inline code suggestions
- Code actions (explain, fix, test)
- File context awareness
- Multi-turn conversations
- Diff view integration

---

## 4. THE AETHER DESIGN LANGUAGE

**Source:** AetherStudio (CAD/Design tool suite)
**Shared across:** All Jenkins Robotics projects

### Core Principles

1. **Engineering Precision** — CAD-inspired, measured, exact
2. **Neutral Sophistication** — Cool grays, not warm
3. **Blue Accent** — `#4c9dff` / `#2f7fe0` — trustworthy, technical
4. **Dark by Default** — Deep blacks, not pure black
5. **Dense Information** — Power users, not minimal
6. **4px Grid** — Everything aligns to 4px
7. **Small Type** — 12px body (desktop app density)

### Color Palette

| Token | Dark | Light | Usage |
|-------|------|-------|-------|
| `--bg-app` | `#0e1013` | `#ececee` | Main background |
| `--bg-shell` | `#171a20` | `#f6f6f7` | Window chrome |
| `--bg-panel` | `#171a20` | `#fbfbfc` | Sidebars, panels |
| `--bg-inset` | `#1e222a` | `#ececef` | Input fields, recessed |
| `--accent` | `#4c9dff` | `#2f7fe0` | Primary actions, links |
| `--text` | `#e7edf3` | `#1c1e21` | Primary text |
| `--text-dim` | `#8b96a5` | `#5c6269` | Secondary text |
| `--ok` | `#32cf84` | (same) | Success states |
| `--warn` | `#e7a843` | (same) | Warning states |
| `--error` | `#ff5a62` | (same) | Error states |

### Geometry

| Token | Value | Usage |
|-------|-------|-------|
| `--size-topbar` | 56px | Top bar height |
| `--size-rail` | 42px | Icon rail width |
| `--size-sidebar` | 250px | Sidebar width |
| `--size-row` | 36px | List row height |
| `--size-grid` | 4px | Base grid unit |
| `--radius-control` | 7px | Inputs, controls |
| `--radius-button` | 8px | Buttons |

### Typography

| Token | Value |
|-------|-------|
| `--font-family` | `-apple-system, "SF Pro Text", Inter, sans-serif` |
| `--font-size-body` | 12px |
| `--font-size-label` | 10px |
| `--font-weight-strong` | 650 |

---

## 5. OTHER JENKINS ROBOTICS PROJECTS

### AetherStudio (CAD/Design Tool)
- **Type:** Desktop CAD application
- **UI:** Full Aether design language
- **Key Patterns:** Ribbon toolbar, icon rail, property panels, viewport
- **Lesson:** Dense, professional, engineering-focused

### Aether-CAD, Aether-Animation, Aether-Sketch, etc.
- **Type:** Specialized CAD tools
- **UI:** Shared Aether components
- **Lesson:** Consistent design system across product family

### JROS (Robot OS)
- **Type:** Robot operating system
- **UI:** Likely dashboard/visualization (not yet examined)
- **Lesson:** Real-time monitoring, graph visualization

### Hermes WebUI
- **Type:** Web chat interface
- **UI:** The base JaegerAI forked from
- **Lesson:** Feature-rich but dated; good features, bad architecture

### JenkinsRobotics.github.io (Website)
- **Type:** Marketing website
- **UI:** Brand presence
- **Lesson:** JaegerAI should match the brand

---

## 6. DESIGN EVOLUTION TIMELINE

```
2025-2026: OLD UI (Terminal/Hacker)
    │
    │  • SwiftUI macOS app
    │  • PySide6 legacy
    │  • Hermes WebUI fork
    │  • Cyan/gold on black
    │  • Monospace fonts
    │
    ▼
2026-10-17: ARCHIVED (UI rebuild)
    │
    │  • Archived to Desktop
    │  • New design mockups created
    │  • Aether tokens extracted
    │
    ▼
2026-10-25: NEW UI (Aether + Modern)
    │
    │  • React 19 + TypeScript
    │  • Aether design tokens
    │  • Modern component library
    │  • Dark + Light themes
    │  • Command palette
    │  • Syntax highlighting
    │
    ▼
FUTURE: Production Grade
    │
    │  • Full Aether design system
    │  • Consistent across all UIs
    │  • Desktop/Web/IDE/Mobile
    │  • Best-in-class AI assistant UI
```

---

## 7. RECOMMENDATIONS: MERGING THE BEST

### What to Keep from OLD
- ✅ Menu bar presence (macOS)
- ✅ Voice orb (beautiful animation)
- ✅ Feature breadth (tasks, kanban, skills, memory)
- ✅ Terminal panel (for power users)
- ✅ Global hotkey (⌥Space)

### What to Keep from AETHER
- ✅ Design tokens (colors, spacing, typography)
- ✅ Engineering precision aesthetic
- ✅ Dark/light mode support
- ✅ 4px grid system
- ✅ Neutral, professional palette

### What to Keep from NEW (Modern)
- ✅ React + TypeScript architecture
- ✅ Component library
- ✅ Command palette (Cmd+K)
- ✅ Syntax highlighting
- ✅ File upload
- ✅ Error boundaries
- ✅ Responsive design
- ✅ Smooth animations

### What to Add
| Feature | Source | Priority |
|---------|--------|----------|
| Aether icon set | AetherStudio | 🔴 High |
| Ribbon toolbar | AetherStudio | 🟡 Medium |
| Property panel | AetherStudio | 🟡 Medium |
| Viewport/canvas area | AetherStudio | 🟢 Low |
| Voice orb animation | OLD macOS | 🔴 High |
| Menu bar integration | OLD macOS | 🔴 High |
| Terminal panel | OLD WebUI | 🟡 Medium |
| Keyboard shortcuts | Modern apps | 🔴 High |
| Session history | OLD WebUI | 🔴 High |
| Kanban board | OLD WebUI | 🟡 Medium |
| Settings organization | AetherStudio | 🟡 Medium |

---

## 8. PROPOSED UNIFIED DESIGN

**Name:** "Jaeger Design System" (JDS)
**Inspiration:** Aether + Linear + Vercel + ChatGPT

### Visual Identity

```
┌─────────────────────────────────────────────────────────┐
│  JAEGER DESIGN SYSTEM v1.0                              │
│  ═══════════════════════                                │
│                                                         │
│  PRINCIPLES:                                            │
│  1. Engineering precision (Aether)                      │
│  2. Modern simplicity (Linear)                          │
│  3. AI-native interactions (ChatGPT)                     │
│  4. Developer-friendly (Vercel)                          │
│                                                         │
│  COLORS:                                                │
│  • Primary:    #4c9dff (Aether blue)                    │
│  • Secondary:  #8b87ff (Aether joint purple)            │
│  • Accent:     #36d6c3 (Aether part teal)               │
│  • Success:    #32cf84 (Aether OK green)                │
│  • Warning:    #e7a843 (Aether warn amber)              │
│  • Error:      #ff5a62 (Aether error red)               │
│                                                         │
│  TYPOGRAPHY:                                            │
│  • UI:      Inter / SF Pro (12-14px)                    │
│  • Code:    JetBrains Mono / SF Mono (12-13px)          │
│  • Display: Inter (24-32px, 600-700 weight)             │
│                                                         │
│  SPACING: Aether 4px grid                               │
│  RADIUS:  7-8px (Aether) or 8-12px (modern)             │
│  SHADOWS: Layered depth (modern)                        │
└─────────────────────────────────────────────────────────┘
```

### Component Hierarchy

```
Level 1: SHELL (window chrome, menu bar, hotkeys)
    └── Level 2: LAYOUT (sidebar, main, panels)
        └── Level 3: VIEWS (chat, tasks, kanban, settings)
            └── Level 4: COMPONENTS (messages, inputs, cards)
                └── Level 5: ATOMS (buttons, badges, icons)
```

---

## 9. ACTION PLAN

### Phase 1: Adopt Aether Tokens (This Week)
- [ ] Replace modern purple (`#6366f1`) with Aether blue (`#4c9dff`)
- [ ] Use Aether background colors (`#0e1013`, `#171a20`)
- [ ] Apply Aether typography (SF Pro / Inter, 12px base)
- [ ] Use Aether spacing (4px grid)

### Phase 2: Add Aether Components (Next Week)
- [ ] Icon rail (42px, vertical icons)
- [ ] Property panel (right sidebar)
- [ ] Status bar (bottom, 27px)
- [ ] Aether icon set

### Phase 3: Keep Modern Features (Ongoing)
- [ ] Command palette (Cmd+K)
- [ ] Syntax highlighting
- [ ] File upload
- [ ] Smooth animations
- [ ] Dark/light toggle

### Phase 4: Desktop Polish (Week 3)
- [ ] Menu bar integration
- [ ] Voice orb
- [ ] Global hotkey
- [ ] Native window chrome

### Phase 5: IDE Extension (Week 4)
- [ ] Sidebar chat
- [ ] Code actions
- [ ] Inline suggestions
- [ ] Aether theming

---

*UI Evolution Analysis — 2026-10-25*
*JaegerAI: From Terminal Hacker to Engineering Precision*
