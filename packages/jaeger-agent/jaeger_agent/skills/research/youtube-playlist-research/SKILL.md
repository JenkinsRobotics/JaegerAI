---
name: youtube-playlist-research
description: List, inspect, or research a YouTube playlist from a YouTube link. Use the official connector before generic web requests, and verify what was listed versus actually reviewed.
metadata:
  jros:
    tags: [youtube, playlist, captions, transcript, research]
    category: research
    version: 1.0.0
    platforms: [linux, macos, windows]
    requires-tools: [youtube_studio]
    requires-toolsets: [media]
---

# YouTube playlist research

- Start with `youtube_studio(action="playlist", url_or_id=the_link, limit=10)`.
  Report both `item_count` (the source's total) and `listed_count` (this sample).
  Do not treat a partial listing as exhaustive. For full analysis, use the
  Work → YouTube workspace for a bounded batch, or ask which slice matters.
- A listing only confirms metadata. For a selected video use the transcript
  action and check `has_transcript`. Say whether the conclusion came from captions,
  published metadata, or independently reviewed video. Never claim to have watched
  a video from its title, or to have read captions when none were returned.
- If the official connector says the list is private or unavailable, explain the
  reason and switch to an authorized browser if appropriate. The user signs in
  themselves. Do not copy browser cookies, retry through third-party mirrors, or read
  credential files. Do not fall back to shell access to protected tool-result paths.
- Scope changes separately. Reading or analyzing a playlist is not permission to
  edit, remove, or download its items. Report the result and any remaining blocker
  in chat instead of silently repeating failed calls.
