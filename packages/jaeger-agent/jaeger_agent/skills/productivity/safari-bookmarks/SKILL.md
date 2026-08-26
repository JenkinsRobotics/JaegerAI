---
name: safari-bookmarks
description: Audit, deduplicate, organize, clean up, or roll back Safari bookmarks. Load for Safari bookmark requests; it routes through ARES's local privacy-preserving proposal and approval workflow instead of reading Bookmarks.plist or exposing URLs to a model.
metadata:
  jros:
    tags: [safari, bookmarks, cleanup, privacy, macos]
    category: productivity
    version: 1.0.0
    platforms: [macos]
    requires-tools: [terminal]
---

# Safari bookmarks

Use the ARES bookmark broker. Do not read, convert, copy, grep, or edit
`~/Library/Safari/Bookmarks.plist` yourself: bookmark titles and URLs are
private, and direct plist writes can race Safari or corrupt sync state.

## Read-only audit

Run only:

```text
terminal(command="ares bookmarks summary")
```

This returns aggregate counts and an opaque proposal ID. It never returns raw
titles, URLs, or the approval token. Report those counts and tell the user to
review private details locally with:

```text
ares bookmarks review PROPOSAL_ID
```

The review command displays duplicate groups only. It does **not** display
empty-folder paths or malformed URL details. Never claim otherwise, and never
read or recommend reading the raw proposal JSON to compensate.

If the command reports a permission boundary, quote that observed error. Do
not infer Full Disk Access from a generic file-tool refusal and do not retry by
opening Safari, using GUI automation, or reading the plist directly.

## Mutation boundary

Never call `ares bookmarks apply` for the user. The local review prints a
one-time approval token and the exact apply command; the human must run that
command in their terminal after reviewing every proposed removal. Empty
folders, malformed/non-web entries, and duplicates in different folders are
report-only and are never automatically removed.

After a locally approved apply, the broker requires Safari to be quit, verifies
the audited source hash, creates and checksums a backup, writes and validates a
temporary plist, atomically replaces the original, and verifies the resulting
bookmark count. Rollback remains a local human command:

```text
ares bookmarks rollback PROPOSAL_ID --approve-token TOKEN
```

Verify an apply or rollback with the aggregate, privacy-safe command:

```text
ares bookmarks verify PROPOSAL_ID
```

Do not invent `ares bookmarks validate`, and do not create a new `summary` as
proof of an older proposal's outcome: `summary` creates a separate proposal.

## Done when

For an audit, done means aggregate evidence and the local review command were
provided, with an explicit statement that no bookmarks changed. Never claim a
cleanup occurred unless the broker reports `status: applied`.
