# Jaeger AI character packs

Jaeger AI stores each playable personality as a self-contained character pack:

```text
personality/characters/<character>/
  character.yaml
  card.png
  assets/
```

The manifest uses the ecosystem `character/v1` format shared with Mochi and
JaegerAnimation. The portable fields are:

- `character`, `name`, `version`, `author`, `license`, and `description`
- `card`, `kind`, typed `assets`, `default_asset`, `render`, and `expressions`
- `identity`, `prompt`, and `lore`

Jaeger AI is an agent application, not an animation runtime. Its bundled packs
therefore declare the card as a valid one-frame `clip_set` with an `idle`
expression. This lets a pack load in a `character/v1` renderer without making
Jaeger AI depend on one. Mochi or Anima Studio can later replace or extend that
render half with sprites, video, a procedural face, motion scripts, or a rig;
Jaeger AI will continue to read the speaking half.

The `traits`, `level`, and `revision` fields are Jaeger AI extensions. They are
additive: other `character/v1` consumers may ignore them, while Jaeger AI keeps
using them for persona compilation, progression, and live editing.

Older operator-created manifests remain readable. The loader accepts legacy
`id` and flat asset strings, but new files and bundled packs are always written
with `character` and typed assets.

