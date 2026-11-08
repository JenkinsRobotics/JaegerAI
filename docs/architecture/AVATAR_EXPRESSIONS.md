# Jaeger character design

The approved character is the original `jaeger-sculpted.png` artwork in
`jaeger_ai/interfaces/ui/src/assets/characters`. Preserve its proportions,
defined limbs and fingers, sculpted shading, charcoal outline, and distinctive
mouth structure. The operator reaffirmed this design on November 8, 2026.

The softened expression atlas was rejected and removed from the live renderer.
The original cutout rig is restored. Empty-chat enlargement, retreat on send,
fixed toolbar controls, reduced motion, and custom portraits remain supported.

Future expressions must change the pose and expression of this same character,
not replace it with a softer, rounder mascot. The sharper mischievous grin remains
an occasional-expression direction; that requirement does not authorize changing
the character's anatomy or material. Faithful replacement expressions still need
visual review before deployment. The restored baseline retains its original grin.

## Signature grin variant

The operator selected panel D's signature grin for the current avatar and the
expression collection. `jaeger-signature-grin.png` is the isolated transparent
variant used by the existing cutout rig. The original `jaeger-sculpted.png` remains
available as the baseline reference. Do not adopt panel D's cheekbones or change
the character into the rejected softened mascot.

## Approved pose collection

The operator approved poses 1, 2, 3, 5, 6, 7, 8, 10, 11, and 12 from the revised
lean-character sheet. Poses 4 (Resolute) and 9 (Laughing) were explicitly rejected
and are not included in the production atlas, selector, or activity mappings.
`jaeger-approved-poses.png` contains the ten approved poses on a transparent 5-by-2
grid, in the order above. Keep `APPROVED_POSES` aligned with that ordering.

Idle retains the unchanged `jaeger-signature-grin.png` icon and its cutout rig.
Working and making something use Calculating (3); waiting uses Your move (5);
connecting uses Resting (7); completion uses Eureka (6). The existing chat hook
owns activity and completion timing. Facepalm and playful poses never activate
automatically from errors or inferred sentiment. Listening is a selectable pose,
not a claim that voice capture is active.

The small avatar selector previews any approved pose for eight seconds, then
returns to automatic. Activity changes clear previews immediately. Reduced motion
and still mode disable the pose fade. This is 2D pose switching, not a 3D rig.
