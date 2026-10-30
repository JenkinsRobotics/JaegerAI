# Character scenes

Shared presentation for the Mac WKWebView and browser. `CharacterScene` renders
one agent, with explicit activity supplied by its caller. Classic agent details
use the existing store summary. The Apple UI opens `LiveCharacterScene`, which
reads `/v1/agents/summary` and selects only the requested ID. Missing activity or
failed reads show unavailable; no global presence, model calls, new task owner,
or character identity is created.

## Entry points

- Classic UI: click an agent's chat title to open details; the scene is inline.
  **Open character window** enlarges it in a modal.
- Apple UI: **Open character window** in the chat header.
- Study, Workshop and Portrait switch presentation locally; Pause freezes motion.
  These are in-app windows, not separate native desktop windows.

The first renderer combines a character's own portrait/icon with a layered body,
arms, desk, monitor, cup and scenery. It is a stylized puppet, not an automatic
full-body rig of the original artwork. Mochi uses its existing dedicated head
asset; Clanker declares a workshop. Robot presets use the same controller.

## Pack extension

The existing `character/v1` manifest's `render.scene` may declare:

```yaml
assets:
  icon: {file: assets/head.png, type: image, adapter: image}
  room: {file: assets/room.png, type: image, adapter: image}
  typing_scene: {file: assets/typing.mp4, type: video}
render:
  adapter: image
  asset: card.png
  scene:
    layout: desk  # portrait | desk | workbench
    background: room
    actions:
      type: typing_scene
```

Actions: `rest`, `read`, `type`, `listen`, `attention`, `check`, `celebrate`,
`blocked`, `offline`, `speak`, `stretch`, `sip`, `look`. An action's optional
image/video replaces the composed actor/desk with a full-scene layer. Missing
or failed media falls back to the procedural scene and existing avatar.
Media paths resolve by asset key through the Gateway; only contained pack files
with supported media extensions can be served. Pack scripts and SVG are not
executed. Animated image files are rejected because image-tag playback cannot
honor pause/reduced motion; use MP4/WebM for animated clips. The WebUI forwards
authenticated scene reads and byte ranges for video.
No new JS runtime dependency is needed.

State changes interrupt ambient activity immediately. Ambient actions rotate
with identity-dependent timing and cooldowns only while idle. Pause, reduced
motion, document visibility, intersection and the native `window.visibility`
event suspend animation. Completion animates only on an explicit completion
status, never on a working-to-idle guess. `speaking` is an input for observed
audio playback; this release does not connect native TTS or implement lip sync.

Bundled scenes are source assets. Operator-installed packs and preferences must
use the operator state root, never write into these bundled character folders.
Scene selection/pause currently last for the mounted view only.

## Verification

`CharacterScene.test.tsx` checks interruption, isolation, unavailable activity,
reduced motion, native visibility, failed art, robot identity, pack loading and
dialog behavior. Python `test_character_scene.py` checks pack containment and
real HTTP asset/range responses. Validate rich media on WKWebView before claiming
native delivery; browser fixture acceptance is separate.
