The Apple UI browser suite is retained here as historical coverage for the
retired `?ui=apple` screen. Its hardcoded mock roster, selectors and voice-mode
expectations do not describe the current default application. Current browser
contracts live in `tests/e2e/stable-demo.spec.ts`: real Gateway, WebUI and SQLite,
with the existing scripted model boundary. They do not certify a real provider,
microphone, or new-user installation. See `STABLE_DEMO.md` for acceptance limits.
