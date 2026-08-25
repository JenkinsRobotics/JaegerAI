---
name: mac-native
description: Route common macOS tasks to deterministic native tools for Shortcuts,
  Spotlight, Calendar, Contacts, clipboard, notifications, system/media control, OCR,
  files, and Mail. Use before GUI automation when a dedicated tool fits.
metadata:
  jros:
    version: 2.0.0
    lifecycle: core
    skill-class: first-class
    platforms:
    - macos
    requires-tools:
    - run_shortcut
    - list_shortcuts
    - spotlight_search
    - get_events
    - create_event
    - lookup_contact
    - clipboard_read
    - clipboard_write
    - notify
    - system_control
    - media_control
    - now_playing
    - ocr_file
    - open_on_host
    - move_file
    - copy_file
    - send_email
    - list_mailboxes
    - list_mail
    - move_mail
    - batch_move
    - send_message
    optional-tools:
    - computer_do
    requires-toolsets:
    - shortcuts
    - spotlight
    - calendar
    - contacts
    - clipboard
    - notifications
    - system_control
    - media_control
    - ocr
    - files
    aliases: []
    tags:
    - macos
    - native
    - calendar
    - files
    - system-control
    category: apple
    compatibility: Requires macOS and the corresponding Jaeger native toolsets.
---

# MAC NATIVE ROUTER

## SOP

1. Match the request to one dedicated tool: system/media setting, calendar,
   contact, clipboard, notification, Spotlight, Shortcut, OCR, file, or Mail.
2. Load its declared toolset if needed and inspect current state before mutation.
3. Call the narrow tool once with named arguments; verify its structured result.
4. For Mail organization load `macos-mail-organizer`. For an unsupported GUI
   interaction load `macos-computer-use` rather than inventing AppleScript.
5. Read `references/legacy-guide.md` only for detailed routing examples.

## ERROR HATCH

Tool unavailable or returns failure: stop and report it. Fall back to
`macos-computer-use` only when the task genuinely requires GUI interaction.

## DONE WHEN

The native tool confirms the requested state/result, or the exact unsupported
capability and safe fallback are reported.
