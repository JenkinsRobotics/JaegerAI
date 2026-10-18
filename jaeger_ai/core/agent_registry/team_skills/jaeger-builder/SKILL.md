---
name: jaeger-builder
description: Builder role - implement a small app in the project root with code, build and test discipline, then prove it with the build/test checker.
metadata:
  role: builder
  version: "1"
---

# Builder: code, build, test, prove

1. Read the spec/RE findings in your task. Write a short plan
   with `update_plan`.
2. Scaffold minimal: prefer zero-dependency Node (plain `node:test`, no network
   installs) unless the task requires packages. A typical layout:
   `package.json` (scripts: `test`, `start`), `src/`, `test/`, `README.md`.
3. Keep logic testable: pure modules for state (e.g. a simulated flash progress
   model, a mock drive list, image file validation) with unit tests.
4. **Never touch real devices or disks.** Anything "flash"-like is simulated.
5. Run `run_build_check(root=<project root>, commands=["npm test"], expect_files=[...])`.
   Fix and rerun until it passes. The checker's JSON is your evidence.
6. Optionally `git init` + commit inside the project root (never push).
7. Result: files created, checker output (exit codes), known gaps.
