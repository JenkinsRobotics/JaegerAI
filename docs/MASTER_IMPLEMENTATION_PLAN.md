# JaegerAI v0.13.0 — Master Implementation Plan

**Date:** 2026-10-26
**Version:** 0.13.0
**Status:** In Progress
**Goal:** Production-grade AI assistant with Apple-native UI, full testing, and CI/CD

---

## Executive Summary

This plan consolidates **all remaining work** to get JaegerAI from its current state to **production-ready v0.13.0**. It includes:

1. **Apple-Native UI Polish** (wire up, fix bugs, SF Symbols, voice orb)
2. **Backend Integration** (connect new UI to existing Gateway)
3. **Complete Test Suite** (unit, integration, E2E for all components)
4. **CI/CD Pipeline** (GitHub Actions)
5. **All 10 Frontends** (Web UI, macOS, TUI, IDE, Avatar, APIs, Mobile)
6. **Documentation** (user guides, API docs, migration guides)

**Total Estimated Time:** 6-8 weeks
**Total Estimated Effort:** ~300 hours

---

## Current State Assessment

### ✅ Completed (252 files changed)

| Category | Status | Files |
|----------|--------|-------|
| Universal Cleanup | ✅ Done | 106+ "Matthew" references removed |
| Feature Deprecation | ✅ Done | 10 features marked DEPRECATED |
| Documentation | ✅ Done | 16 migration docs, getting-started guide |
| User Journey Audit | ✅ Done | 10 issues fixed, README overhaul |
| Backend: WebSocket | ✅ Done | `websocket.py` (JSON-RPC) |
| Backend: OpenAI API | ✅ Done | `openai_compat.py` |
| Backend: Memory Dreaming | ✅ Done | `dreaming.py` (3-phase) |
| Backend: Skills Adapters | ✅ Done | Hermes, OpenClaw, ClawHub adapters |
| Backend: Mobile Nodes | ✅ Done | `mobile/` (WebSocket + pairing) |
| Frontend: Apple Tokens | ✅ Done | `apple-tokens.css` (SF Pro, system colors) |
| Frontend: Apple Components | ✅ Done | `apple-components.css` (ChatGPT style) |
| Frontend: ChatGPT Messages | ✅ Done | `ChatGPTMessage.tsx` (grouped, no bubbles) |
| Frontend: Modern Components | ✅ Done | Sidebar, Chat, Command Palette, etc. |
| Test Infrastructure | ✅ Partial | Directory structure, conftest, requirements |

### 🟡 In Progress

| Task | Status | Notes |
|------|--------|-------|
| Wire Apple UI into main app | 🟡 0% | Need to connect to App.tsx |
| SF Symbols integration | 🟡 0% | Component created, not integrated |
| Voice Orb component | 🟡 0% | CSS ready, React component needed |
| GatewayClient connection | 🟡 0% | File created, not connected to backend |

### 🔴 Not Started

| Category | Tasks |
|----------|-------|
| Testing | Complete unit, integration, E2E tests |
| CI/CD | GitHub Actions pipeline |
| macOS App | Swift testing, UI polish |
| TUI | Test all commands, E2E |
| IDE Extension | Complete VS Code extension |
| Avatar | SwiftUI polish, testing |
| Mobile/PWA | PWA features, testing |
| Documentation | API docs, user guides, video tutorials |

---

## Phase 1: Wire & Ship Apple-Native UI (Week 1)

**Goal:** Get the new Apple-native UI working end-to-end with the existing backend.

**Duration:** 5 days (40 hours)
**Priority:** 🔴 CRITICAL

### Tasks

| # | Task | File(s) | Effort | Status |
|---|------|---------|--------|--------|
| 1.1 | Import Apple theme in main entry | `src/main.tsx` | 30m | ⬜ |
| 1.2 | Update App.tsx to use ChatGPTMessage | `src/App.tsx` | 4h | ⬜ |
| 1.3 | Replace old chat with new ModernChat | `src/App.tsx` | 4h | ⬜ |
| 1.4 | Wire GatewayClient to real backend | `src/lib/gateway-client.ts` | 6h | ⬜ |
| 1.5 | Test streaming chat end-to-end | — | 4h | ⬜ |
| 1.6 | Test in macOS app (WKWebView) | — | 4h | ⬜ |
| 1.7 | Fix layout/responsive issues | various | 6h | ⬜ |
| 1.8 | Add SF Symbols component | `src/components/SFIcon.tsx` | 6h | ⬜ |
| 1.9 | Replace Lucide icons with SF Symbols | various | 4h | ⬜ |
| 1.10 | Build production bundle | — | 2h | ⬜ |
| 1.11 | Create screenshots for documentation | — | 2h | ⬜ |
| 1.12 | Test on iPhone (Safari) | — | 2h | ⬜ |

### Deliverables
- [ ] Working chat in web UI with Apple-native design
- [ ] Working chat in macOS app (WKWebView)
- [ ] SF Symbols throughout
- [ ] Screenshots for App Store/marketing
- [ ] Production build tested

### Success Criteria
- [ ] Chat works end-to-end (send message, receive response)
- [ ] UI matches ChatGPT quality
- [ ] No layout bugs on macOS/iPhone
- [ ] Streaming works smoothly
- [ ] Voice input button present (even if not functional yet)

---

## Phase 2: Voice & Interactive Features (Week 2)

**Goal:** Add voice visualization and interactive features.

**Duration:** 5 days (40 hours)
**Priority:** 🟡 High

### Tasks

| # | Task | File(s) | Effort | Status |
|---|------|---------|--------|--------|
| 2.1 | Create VoiceOrb component | `src/components/VoiceOrb.tsx` | 8h | ⬜ |
| 2.2 | Add waveform visualization | `src/components/Waveform.tsx` | 8h | ⬜ |
| 2.3 | Wire voice input to backend | `src/lib/voice.ts` | 8h | ⬜ |
| 2.4 | Add voice output (TTS) | — | 8h | ⬜ |
| 2.5 | Create PersonalityEmptyState | `src/components/PersonalityEmptyState.tsx` | 4h | ⬜ |
| 2.6 | Add suggestion cards | — | 4h | ⬜ |

### Deliverables
- [ ] Voice orb with gradient animation
- [ ] Waveform visualization for recording
- [ ] TTS playback with visualization
- [ ] Personality-driven empty states
- [ ] Suggestion cards on new chat

---

## Phase 3: Complete Test Suite (Weeks 3-4)

**Goal:** 70%+ test coverage across all components.

**Duration:** 10 days (80 hours)
**Priority:** 🔴 CRITICAL

### 3.1 Python Unit Tests (Week 3)

| # | Task | Directory | Effort | Status |
|---|------|-----------|--------|--------|
| 3.1.1 | Test WebSocket module | `dev/tests/unit/python/test_websocket*.py` | 8h | 🟡 Partial |
| 3.1.2 | Test Dreaming engine | `dev/tests/unit/python/test_dreaming*.py` | 8h | 🟡 Partial |
| 3.1.3 | Test Skills adapters | `dev/tests/unit/python/test_skills_adapters.py` | 8h | ⬜ |
| 3.1.4 | Test Mobile node server | `dev/tests/unit/python/test_mobile*.py` | 8h | ⬜ |
| 3.1.5 | Test UnifiedScheduler | `dev/tests/unit/python/test_scheduler.py` | 8h | ⬜ |
| 3.1.6 | Test Operator config | `dev/tests/unit/python/test_operator_config.py` | 4h | ⬜ |
| 3.1.7 | Test Channel config | `dev/tests/unit/python/test_channel_config.py` | 4h | ⬜ |

### 3.2 Python Integration Tests (Week 3-4)

| # | Task | Directory | Effort | Status |
|---|------|-----------|--------|--------|
| 3.2.1 | Test Gateway REST API | `dev/tests/integration/gateway/test_rest_api.py` | 8h | ⬜ |
| 3.2.2 | Test Gateway WebSocket API | `dev/tests/integration/gateway/test_websocket_api.py` | 8h | ⬜ |
| 3.2.3 | Test OpenAI compatibility | `dev/tests/integration/gateway/test_openai_compat.py` | 6h | ⬜ |
| 3.2.4 | Test SSE streaming | `dev/tests/integration/gateway/test_sse.py` | 6h | ⬜ |
| 3.2.5 | Test Mobile node server | `dev/tests/integration/mobile/test_node_server.py` | 8h | ⬜ |
| 3.2.6 | Test Dreaming integration | `dev/tests/integration/test_dreaming_integration.py` | 6h | ⬜ |

### 3.3 Frontend Tests (Week 4)

| # | Task | Directory | Effort | Status |
|---|------|-----------|--------|--------|
| 3.3.1 | Set up Vitest config | `jaeger_ai/interfaces/ui/vitest.config.ts` | 2h | ⬜ |
| 3.3.2 | Test ChatGPTMessage component | `src/components/__tests__/ChatGPTMessage.test.tsx` | 6h | ⬜ |
| 3.3.3 | Test ModernChat component | `src/components/__tests__/ModernChat.test.tsx` | 6h | ⬜ |
| 3.3.4 | Test ModernSidebar component | `src/components/__tests__/ModernSidebar.test.tsx` | 4h | ⬜ |
| 3.3.5 | Test CommandPalette component | `src/components/__tests__/CommandPalette.test.tsx` | 4h | ⬜ |
| 3.3.6 | Test GatewayClient | `src/lib/__tests__/gateway-client.test.ts` | 6h | ⬜ |
| 3.3.7 | Test ThemeProvider | `src/theme/__tests__/ThemeProvider.test.tsx` | 4h | ⬜ |

### 3.4 Frontend E2E Tests (Week 4)

| # | Task | File | Effort | Status |
|---|------|------|--------|--------|
| 3.4.1 | Set up Playwright | `jaeger_ai/interfaces/ui/playwright.config.ts` | 2h | ⬜ |
| 3.4.2 | Test chat flow | `tests/e2e/chat.spec.ts` | 6h | ⬜ |
| 3.4.3 | Test command palette | `tests/e2e/command-palette.spec.ts` | 4h | ⬜ |
| 3.4.4 | Test file upload | `tests/e2e/file-upload.spec.ts` | 4h | ⬜ |
| 3.4.5 | Test settings | `tests/e2e/settings.spec.ts` | 4h | ⬜ |
| 3.4.6 | Test mobile responsive | `tests/e2e/mobile.spec.ts` | 6h | ⬜ |

### 3.5 Swift Tests (Week 4)

| # | Task | Directory | Effort | Status |
|---|------|-----------|--------|--------|
| 3.5.1 | macOS app unit tests | `macos-shell/Tests/` | 8h | ⬜ |
| 3.5.2 | macOS app UI tests | `macos-shell/UITests/` | 8h | ⬜ |
| 3.5.3 | Avatar unit tests | `avatar/Tests/` | 6h | ⬜ |
| 3.5.4 | Avatar snapshot tests | `avatar/Tests/` | 6h | ⬜ |

### 3.6 TUI Tests (Week 4)

| # | Task | File | Effort | Status |
|---|------|------|--------|--------|
| 3.6.1 | Test slash commands | `dev/tests/unit/python/test_tui_commands.py` | 6h | ⬜ |
| 3.6.2 | Test TUI integration (pexpect) | `dev/tests/integration/test_tui.py` | 8h | ⬜ |
| 3.6.3 | Test TUI E2E | `dev/tests/e2e/test_tui_e2e.py` | 6h | ⬜ |

### Deliverables
- [ ] 70%+ Python code coverage
- [ ] 60%+ Frontend code coverage
- [ ] All critical paths tested
- [ ] CI-ready test suite

### Success Criteria
- [ ] `pytest` runs all tests in < 5 minutes
- [ ] `npm test` runs all frontend tests
- [ ] `swift test` runs all Swift tests
- [ ] No flaky tests

---

## Phase 4: CI/CD Pipeline (Week 5)

**Goal:** Automated testing and deployment.

**Duration:** 5 days (40 hours)
**Priority:** 🟡 High

### Tasks

| # | Task | File | Effort | Status |
|---|------|------|--------|--------|
| 4.1 | Create GitHub Actions workflow | `.github/workflows/ci.yml` | 8h | ⬜ |
| 4.2 | Lint job (ruff, mypy, eslint) | `.github/workflows/lint.yml` | 4h | ⬜ |
| 4.3 | Test job (Python, Frontend, Swift) | `.github/workflows/test.yml` | 8h | ⬜ |
| 4.4 | Build job (artifacts for all platforms) | `.github/workflows/build.yml` | 8h | ⬜ |
| 4.5 | Release job (GitHub Releases) | `.github/workflows/release.yml` | 4h | ⬜ |
| 4.6 | Codecov integration | `.github/workflows/coverage.yml` | 2h | ⬜ |
| 4.7 | Dependabot config | `.github/dependabot.yml` | 2h | ⬜ |
| 4.8 | Create release scripts | `scripts/release.sh` | 4h | ⬜ |

### Deliverables
- [ ] CI runs on every push/PR
- [ ] Automated testing for all platforms
- [ ] Automated builds for macOS/Linux
- [ ] Release automation
- [ ] Code coverage reporting

---

## Phase 5: macOS App Polish (Week 5-6)

**Goal:** Native macOS app that feels like a first-party Apple app.

**Duration:** 5 days (40 hours)
**Priority:** 🟡 High

### Tasks

| # | Task | File(s) | Effort | Status |
|---|------|---------|--------|--------|
| 5.1 | Window chrome polish | `macos-shell/Sources/` | 8h | ⬜ |
| 5.2 | Menu bar integration | `StatusItemController.swift` | 6h | ⬜ |
| 5.3 | Global hotkey (⌥Space) | `Hotkey.swift` | 6h | ⬜ |
| 5.4 | Keyboard shortcuts (⌘N, ⌘K, ⌘,) | — | 6h | ⬜ |
| 5.5 | Voice orb in menu bar | — | 8h | ⬜ |
| 5.6 | Quick input pill | `PillPanel.swift` | 6h | ⬜ |

### Deliverables
- [ ] Native macOS window chrome
- [ ] Menu bar with status
- [ ] Global hotkey for quick input
- [ ] Full keyboard shortcut support
- [ ] Voice orb visualization

---

## Phase 6: IDE Extension (Week 6)

**Goal:** Production-ready VS Code extension.

**Duration:** 5 days (40 hours)
**Priority:** 🟡 Medium

### Tasks

| # | Task | File(s) | Effort | Status |
|---|------|---------|--------|--------|
| 6.1 | Complete sidebar webview | `ide/src/` | 12h | ⬜ |
| 6.2 | Add inline code actions | — | 8h | ⬜ |
| 6.3 | Add diff view integration | — | 8h | ⬜ |
| 6.4 | Package as VSIX | — | 4h | ⬜ |
| 6.5 | Test in VS Code | — | 4h | ⬜ |
| 6.6 | Publish to marketplace | — | 4h | ⬜ |

### Deliverables
- [ ] Working VS Code extension
- [ ] Sidebar chat panel
- [ ] Inline code actions
- [ ] Published to marketplace

---

## Phase 7: Mobile/PWA (Week 6-7)

**Goal:** Installable PWA with mobile-optimized experience.

**Duration:** 5 days (40 hours)
**Priority:** 🟡 Medium

### Tasks

| # | Task | File(s) | Effort | Status |
|---|------|---------|--------|--------|
| 7.1 | Add PWA manifest | `public/manifest.json` | 2h | ⬜ |
| 7.2 | Add service worker | `public/sw.js` | 8h | ⬜ |
| 7.3 | Camera access (WebRTC) | `src/lib/camera.ts` | 8h | ⬜ |
| 7.4 | Push notifications | `src/lib/notifications.ts` | 8h | ⬜ |
| 7.5 | Offline support | — | 8h | ⬜ |
| 7.6 | Install prompt | — | 2h | ⬜ |
| 7.7 | Test on iPhone/Android | — | 4h | ⬜ |

### Deliverables
- [ ] Installable PWA
- [ ] Camera access
- [ ] Push notifications
- [ ] Offline support
- [ ] Works on iPhone/Android

---

## Phase 8: Avatar Polish (Week 7)

**Goal:** Beautiful avatar that works with the new UI.

**Duration:** 5 days (40 hours)
**Priority:** 🟢 Low

### Tasks

| # | Task | File(s) | Effort | Status |
|---|------|---------|--------|--------|
| 8.1 | Polish avatar animations | `avatar/Sources/` | 12h | ⬜ |
| 8.2 | Connect to chat emotions | — | 8h | ⬜ |
| 8.3 | Add voice visualization | — | 8h | ⬜ |
| 8.4 | Test on macOS | — | 6h | ⬜ |
| 8.5 | Package and distribute | — | 6h | ⬜ |

### Deliverables
- [ ] Smooth avatar animations
- [ ] Emotion-reactive avatar
- [ ] Voice visualization
- [ ] Packaged for distribution

---

## Phase 9: Documentation (Week 7-8)

**Goal:** Complete user and developer documentation.

**Duration:** 5 days (40 hours)
**Priority:** 🟡 High

### Tasks

| # | Task | File | Effort | Status |
|---|------|------|--------|--------|
| 9.1 | Update README with new UI screenshots | `README.md` | 4h | ⬜ |
| 9.2 | Create video tutorial (5 min) | — | 8h | ⬜ |
| 9.3 | API documentation (OpenAPI) | `docs/api/` | 8h | ⬜ |
| 9.4 | Developer guide | `docs/DEVELOPER_GUIDE.md` | 8h | ⬜ |
| 9.5 | Architecture documentation update | `docs/architecture/` | 4h | ⬜ |
| 9.6 | Troubleshooting guide | `docs/TROUBLESHOOTING.md` | 4h | ⬜ |
| 9.7 | Create website (GitHub Pages) | `docs/` | 4h | ⬜ |

### Deliverables
- [ ] Updated README with screenshots
- [ ] 5-minute video tutorial
- [ ] Complete API documentation
- [ ] Developer guide
- [ ] Troubleshooting guide
- [ ] Public website

---

## Phase 10: Final Polish & Release (Week 8)

**Goal:** Ship v0.13.0!

**Duration:** 5 days (40 hours)
**Priority:** 🔴 CRITICAL

### Tasks

| # | Task | Effort | Status |
|---|------|--------|--------|
| 10.1 | Final bug fixes | 16h | ⬜ |
| 10.2 | Performance optimization | 8h | ⬜ |
| 10.3 | Security audit | 8h | ⬜ |
| 10.4 | Create release notes | 4h | ⬜ |
| 10.5 | Build release artifacts | 4h | ⬜ |
| 10.6 | Create GitHub release | 2h | ⬜ |
| 10.7 | Announce release | 2h | ⬜ |

### Deliverables
- [ ] v0.13.0 released on GitHub
- [ ] Release notes published
- [ ] Download links working
- [ ] Announcement posted

---

## Summary Timeline

```
Week 1:  ████████ Phase 1: Wire & Ship Apple UI
Week 2:  ████████ Phase 2: Voice & Interactive Features
Week 3:  ████████ Phase 3a: Python Unit + Integration Tests
Week 4:  ████████ Phase 3b: Frontend + Swift + TUI Tests
Week 5:  ████████ Phase 4: CI/CD + Phase 5: macOS Polish
Week 6:  ████████ Phase 6: IDE Extension + Phase 7: Mobile/PWA
Week 7:  ████████ Phase 8: Avatar + Phase 9: Documentation
Week 8:  ████████ Phase 10: Final Polish & Release 🚀
```

---

## Success Metrics

### Code Quality
- [ ] 70%+ Python test coverage
- [ ] 60%+ Frontend test coverage
- [ ] 0 critical bugs
- [ ] 0 security vulnerabilities

### Performance
- [ ] Web UI load < 2s
- [ ] macOS app launch < 1s
- [ ] API p99 latency < 100ms
- [ ] WebSocket latency < 50ms

### User Experience
- [ ] App Store rating target: 4.8+ ⭐
- [ ] Chat response time < 2s
- [ ] Voice start latency < 500ms
- [ ] 0 crashes in production

### Business
- [ ] 1000+ GitHub stars
- [ ] 100+ active users
- [ ] 10+ community contributions

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Backend integration breaks | Extensive integration tests, feature flags |
| Performance issues | Benchmark suite, profiling tools |
| Security vulnerabilities | Security audit, dependency scanning |
| Scope creep | Strict phase boundaries, MVP focus |
| Burnout | Sustainable pace, regular breaks |

---

## Dependencies

### External
- Node.js 20+ (frontend)
- Python 3.11+ (backend)
- Swift 5.9+ (macOS)
- Xcode 15+ (macOS build)

### Internal
- jaeger-agent (packages/)
- jaeger-os (packages/)
- YouTube Studio (optional)

---

## Notes

- **Daily standups:** Review progress, unblock issues
- **Weekly demos:** Show progress to stakeholders
- **Bi-weekly releases:** Internal beta releases
- **Continuous:** Monitor production metrics

---

*Master Implementation Plan — 2026-10-26*
*JaegerAI v0.13.0: From Engineering Tool to Production Product*
