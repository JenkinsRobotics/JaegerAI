# Aether illustrated tools

Original 32 × 32 vector artwork for labeled ribbon commands, shared across Aether
apps through `ToolIcon` from `@aether/ui`. Blue shaded faces identify modeling
geometry; silver faces show the surrounding body; orange marks construction,
direction, and modification. These are tool illustrations, separate from the
preserved Fancy/Simple app identities and original application icons.

The SVGs are the shipped assets. `python3 core/assets/icons/tools/generate.py`
reproduces them from the editable vector geometry. Add new imports/names in
`core/ui/src/ToolIcon.tsx` when adding artwork. Never embed fonts or bitmaps.
The renderer scopes gradient IDs per instance, is decorative for accessibility,
and inherits the palette from `widgets.css` and `data-aether-theme="light"`.
Buttons supply accessible tool names and keep their real availability rules.
