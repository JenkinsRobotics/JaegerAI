# apple-mail-cleanup — independent module, NOT yet wired, DANGEROUS if wired wrong

Job: Apple Mail inbox-zero / junk handling, on-device, via AppleScript. This is distinct from Jaeger's existing mail tools: jaeger-agent has an email tool, and JaegerAI has features/channels, but neither is an inbox-cleanup job (review, delete, archive, junk, categorize, with a NEVER list).

Source, NOT copied into this module (review before any copy):
- Desktop "Ai  work " / ares-mail/ — inbox_zero.py 14,623 bytes (406 lines), junk_kill.py 15,771, bulk_junk.py 9,059, watchdog.sh 656, junk_watch.sh 499.
- Desktop "Ai  work " / clean_inbox.scpt 5,946 + clean_inbox2.scpt 5,484 + test_clean.scpt 625 — AppleScript mail cleaning, same job, older.
- inbox_zero.py head: "Process Apple Mail inbox by always acting on message 1 (fast, stable)", via osascript, stats reviewed/deleted/archived/junked/categorized/action_required/waiting/rules_created, report to /tmp/ares-mail/report.json, log to /tmp/ares-mail/run.log.

Warnings, do NOT ignore when wiring:
- DELETING MAIL IS IRREVERSIBLE. This module must NEVER auto-delete, auto-archive, or auto-junk without a Jaeger approval gate bound to the exact message/batch, with a dry-run + report first. The source script's "always acting on message 1" loop is fast, but speed is not safety here. Wire it as: propose -> report -> human approves that exact batch -> act -> verify counts, never as an unattended cron that deletes.
- The source NEVER list (ups, fedex, usps, dhl, dropbox, apple, icloud, github, openai, anthropic, ollama, etc.) is PERSONAL to the operator's mail at that time. Do NOT hardcode it into Jaeger as a default. The operator must review and approve a NEVER list as their own config, separate from code.
- ARES-era origin: ares-mail is an ARES predecessor tool, not Jaeger code. Do NOT present it as Jaeger mail, and do NOT wire it to Hermes/ARES ports or state. Jaeger is standalone; this module, if wired, is a Jaeger tool via the tool registry + approval gate only.

Test to run when code-run is available: dry-run on a test mailbox, report matches reality, NEVER list respected, approval gate blocks a delete batch until approved, approved batch deletes exactly that batch and counts verify, no mail outside the approved batch is touched.
