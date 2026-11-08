# Jaeger expressions

The shared UI uses `src/avatar/JaegerAvatar.tsx` and the transparent
`src/assets/characters/jaeger-emotes.png` atlas inside `jaeger_ai/interfaces/ui`.
The atlas is four columns by three rows; each cell is square. Keep cell ordering
in sync with `EXPRESSIONS`. This is a rendered 2D pose system, not a skeletal 3D rig.

## Automatic activity

The existing chat activity hook remains the single source of runtime state.

| Runtime state | Pose |
| --- | --- |
| Idle | Seated, relaxed closed smile |
| Working | Deep thought |
| Making something | Determined |
| Waiting on a specialist | Open palms |
| Connecting or load error | Quiet resting pose |
| Newly completed turn | Brief friendly Eureka, then idle |

Automatic activity never selects facepalm, laughter, or the three mischievous
grins. No message-text sentiment guesses or model emotion claims are introduced.

## Optional expressions

The small selector on the avatar previews any of the twelve expressions for
eight seconds. A runtime state change immediately restores automatic activity.
Listening, facepalm, laughter, playful curiosity, playful invitation, and peekaboo
are selectable previews, not automatic voice or conversation interpretations.
The final three atlas cells preserve the approved occasional toothy grin and
subtle cheek shaping. Everyday poses keep the original smooth, eyeless design.

Custom portraits retain their existing rendering. Reduced motion and still mode
disable pose fade-in. Existing empty-chat enlargement and fixed toolbar layout
remain unchanged.

## Verification

Run the avatar and chat UI tests, production build, and
`node scripts/check-avatar-home.mjs` from the UI directory. Set
`PLAYWRIGHT_CHANNEL=chrome` to use an installed Chrome browser.
