# Widget conformance

The strong default this file promotes: **a reusable core widget is finished
once in `aether-ui`, to its full spec, and apps reuse it instead of growing
near-duplicates.** When an app genuinely needs different interaction semantics,
performance, or accessibility behavior, it may use a specialized component.
That exception is documented, reuses shared primitives/tokens where practical,
and receives its own gallery scenario and behavior tests. A missing generally
useful behavior should still be added here rather than patched independently in
each product.

Definition of done for a core widget:
1. **Spec** — its behavior checklist below is complete.
2. **Gallery** — every checklist behavior is demonstrable in
   `npm run gallery`, including at least two instances side by side
   proving identical behavior from different data.
3. **Pins** — RTL tests cover each behavior (`npm test`).
4. **Consumers stay thin** — apps normally pass data + handlers; intentional
   specialized behavior follows the documented exception practice above.

## Tree — spec v3 (flagship)

- [x] Hierarchical rows: disclosure, icon, label, badge, trailing actions
- [x] Selection: single click; ⌘/ctrl toggles; ⇧ selects a range over the
      visible (flattened, expanded) order
- [x] Disclosure click expands/collapses WITHOUT selecting
- [x] Expansion: uncontrolled by default; controlled via
      `expandedIDs` + `onToggle`
- [x] Keyboard: ↑/↓ move focus, → expands or enters children, ← collapses
      or moves to parent, Enter/Space selects, Home/End jump; roving
      tabindex
- [x] `filter` prop: hides non-matching rows, keeps ancestors of matches,
      auto-reveals matches inside collapsed branches
- [x] Trailing per-row actions (hover-revealed) that never change selection
- [x] `onActivate` (double-click) and `onContextMenu(id, x, y)` events
- [x] Disabled rows (skip focus/selection) and `dimmed` rows (styling only)
- [x] Empty state slot
- [x] Controlled inline rename via `renamingID`, `onRename`, and cancel
- [x] Drag re-order / re-parent signals with before/inside/after intent;
      applications retain graph mutation and validity policy
- [x] Expanded child loading and recoverable error/retry rows
- [x] Fixed-row virtualization for large visible hierarchies

## SearchField — spec v1

- [x] Controlled or uncontrolled query with immediate `onQueryChange`
- [x] Optional delayed `onSearch` intent with configurable delay
- [x] Enter flushes pending search; Escape and the named clear button reset it
- [x] Optional native scope selector and accessible singular/plural result count
- [x] Disabled, placeholder, autofocus, and external input-ref behavior

## Breadcrumbs — spec v1

- [x] Ordered stable-ID path with the final location marked `aria-current=page`
- [x] Native button navigation and disabled intermediate locations
- [x] Configurable long-path collapse through the definitive shared Menu
- [x] Named navigation landmark, quiet separators, truncation, and shared focus ring

## RadioGroup — spec v1

- [x] Native fieldset/radio semantics with controlled or uncontrolled selection
- [x] Horizontal/vertical layouts, labels, descriptions, disabled options, and group errors
- [x] Arrow wrapping plus Home/End navigation while skipping disabled options

## SegmentedControl — spec v1

- [x] Controlled or uncontrolled single-choice radiogroup semantics
- [x] Selected, hover, focus, option-disabled, and group-disabled states
- [x] Roving focus with wrapping arrows and Home/End while skipping disabled segments

## Slider — spec v1

- [x] Native range input with controlled or uncontrolled numeric state
- [x] Explicit min/max/step/unit and accessible value text
- [x] Optional output, disabled state, and token-driven filled-track presentation

## ColorField — spec v1

- [x] Synchronized native picker and six-digit hex editor
- [x] Controlled or uncontrolled value with normalized commit on Enter/blur
- [x] Validation diagnostics, Escape cancel, disabled state, and named inputs

## FileField — spec v1

- [x] Native browse and drag/drop selection with accept and single/multiple bounds
- [x] Controlled or uncontrolled file list, size display, and clear action
- [x] Label, help, error, disabled, focus, and drop-target states

## CommandPalette — spec v1

- [x] Controlled modal accepts product-supplied commands and emits stable IDs only
- [x] Ranked exact/prefix/substring/subsequence search across labels, descriptions, categories, and keywords
- [x] Recent ordering, category groups, icons, descriptions, shortcuts, disabled reasons, and no-results state
- [x] Input-retained arrow navigation with wrap, Home/End, Enter execution, Escape close, focus trap, and opener focus return
- [x] Optional typed argument follow-up with required validation, Enter submit, Back, and Escape return to search

## DocumentTabs — spec v1

- [x] Controlled tab strip with active, dirty, pinned, preview, and disabled states
- [x] Active close control with explicit pinned-close policy and pin/unpin intent
- [x] Pointer drag reorder emits stable source/target IDs without owning document order
- [x] Bounded visible tabs keep the active document present and route hidden tabs through shared Menu overflow
- [x] Arrow wrapping plus Home/End navigation skip disabled tabs and follow selection
- [x] Shared Menu emits horizontal/vertical split intent while applications own pane layout

## Toast / NotificationCenter — spec v1

- [x] Shared product-free model covers success, warning, error, and progress with title/message/timestamp
- [x] Toast stack uses polite status or assertive error announcements, determinate progress, optional action, dismiss, and persistent state
- [x] NotificationCenter presents persistent read/unread history with mark-read, action, remove, clear-all, and named empty state
- [x] Every action emits a stable notification ID; applications own history storage and side effects
- [x] Compact stacking, keyboard focus, token styling, and progress accessibility are shared

## Status matrix (core widgets)

| Widget | Spec | Gallery | Pins | Notes |
|---|---|---|---|---|
| Tree | **v3** | full | full | flagship — see above |
| Button / IconButton | **v2** | yes | basic | shared keyboard-only focus ring (all interactive widgets) |
| Ribbon (+Group/Tool) | **v2** | yes | full | ←/→ across groups skipping disabled, wrap; overflow-x scroll |
| Tabs | **v2** | yes | full | ←/→ wrap + Home/End, roving tabindex, selection follows focus |
| Rail | v1 | yes | full | label/pressed/disabled/click and standard button/container attributes pinned |
| DockPanel / PanelHeading | v1 | yes | none | needs: collapse spec (rail chevron) |
| TextField | **v2** | yes | full | `invalid` (aria-invalid + error border), `unit` suffix (mm/deg/s) |
| SearchField | **v1** | full | full | controlled/uncontrolled query, delayed search intent, Enter flush, Escape/clear, optional scope, accessible result count, focus ref |
| Breadcrumbs | **v1** | full | full | stable current-page path, disabled locations, shared-Menu overflow, native keyboard navigation |
| RadioGroup | **v1** | full | full | native form semantics, descriptions/errors, controlled/uncontrolled selection, arrow/Home/End navigation |
| SegmentedControl | **v1** | full | full | single-choice radiogroup, controlled/uncontrolled selection, roving focus, disabled states |
| Slider | **v1** | full | full | native range semantics, min/max/step/unit/output, disabled state, token-driven fill |
| ColorField | **v1** | full | full | native picker plus validated hex commit/cancel, controlled/uncontrolled state |
| FileField | **v1** | full | full | browse/drop, accept, single/multiple, controlled list, clear/help/error/disabled states |
| CommandPalette | **v1** | full | full | fuzzy discovery, recents/categories, disabled reasons/shortcuts, keyboard traversal, argument follow-up, focus return |
| DocumentTabs | **v1** | full | full | active/dirty/pinned/preview states, close/pin/reorder/overflow/split intent, accessible keyboard selection |
| Toast / NotificationCenter | **v1** | full | full | status/error announcements, success/warning/error/progress, actions/dismiss, persistent read/unread history |
| NumberField | **v1** | full | full | arithmetic expressions, explicit display unit, min/max validation, mixed value, Enter/blur commit, Escape cancel, fine/coarse keyboard step, optional pointer scrub |
| SelectField | **v1** | full | full | native select semantics, data-driven options, placeholder, disabled options, invalid state |
| Checkbox | **v1** | full | full | native form behavior, label/description, disabled and indeterminate multi-selection state |
| FieldRow | **v1** | full | full | consistent label/editor/help/error/modified/reset composition; application retains transaction ownership |
| Dialog | **v2** | yes | full | document-level Escape, focus trap + wrap, focus returns to opener |
| Menu / ContextMenu | **v1** | full | full | controlled command model for dropdown, overflow, and point-anchored context surfaces; submenus, check/radio state, shortcuts, danger, disabled reasons, keyboard traversal, outside/Escape dismissal, focus return, viewport-aware placement |
| PanelPlacementMenu | **v1** | full | full | product-free Dock/Float/Hide radio menu; emits placement only while applications own stable panel IDs and persistence |
| Popover | **v1** | yes | full | controlled anchored surface; optional first-control focus and outside dismissal, Escape dismissal, focus return, viewport-aware placement |
| Tooltip | **v1** | full | full | delayed pointer and immediate focus help, shortcut/disabled explanation, accessible description, Escape dismissal, shared viewport-aware placement |
| EmptyState / ErrorState | **v1** | full | full | compact/full guidance, diagnostics, accessible error announcement, primary/secondary recovery actions |
| ProgressOverlay | **v1** | full | full | determinate/indeterminate phases, cancel/background actions, modal focus containment/return and Escape cancel, reduced-motion fallback |
| ListBox | **v1** | full | full | controlled single/multiple or semantic nonselectable collections, groups, range/toggle selection, type-ahead, disabled/dimmed rows, activation/context/row actions, empty/loading/error states, fixed-row virtualization |
| DataTable | **v1** | full | full | typed/resizable/reorderable columns, controlled sort/filter, single/multiple/range and keyboard row selection, inline edit, pinned columns, row commands, empty/loading/error states, fixed-row virtualization |
| PropertyGrid / PropertySection | **v1** | full | full | schema-driven editors, controlled/uncontrolled collapsible sections, filtering, modified-only projection, mixed/read-only state, shared help/error/reset composition |
| SplitPane / BottomPanel | **v1** | full | full | horizontal/vertical pointer and keyboard resizing, min/max, controlled persistence, collapse/restore; tabbed Problems/History/Console/BOM/Tasks surface with badges, actions, keyboard tabs, collapse/restore |
| StatusBar / StatusDot | v1 | yes | none | trivial |
| ViewportCanvas | v1 | yes | full | mount-once/teardown pinned |
| ViewportNavigationCube | **v1** | full | full | controlled product-free camera chrome; quaternion display plus accessible face, fit, 15-degree nudge, and quarter-turn roll intent; renderer behavior remains app-owned |
| WorkspaceShell | **v1** | full | full | app-window chrome ported from Swift `StudioWorkspaceScaffold`: docked / floating / canvas presets around one persistent center/viewport subtree; controlled or uncontrolled stable-ID panel placement/coordinates; rail-toggled panel stacks, tear-off drag/clamp/restack, canvas edge reveal. Deferred: drag-reorder of stacked panels, panels-on-outer-edge option, chrome shape presets |
| FloatingPanel | v1 | yes | via shell | draggable by header; also standalone for short-lived tools |
| FeatureWindow | v1 | yes | gallery | suite-standard feature editor: ✓/✕ header, Enter commits, Entities box, parameter rows, opacity slider; imperative DOM (openFeatureWindow) |
| SettingsWindow | v1 | yes | gallery | suite-standard per-app settings: macOS anatomy (traffic-light close, grouped sidebar, cards, rows); products supply sections/panes |
| DocumentBar | v1 | yes | none | 48px top row: leading/trailing clusters + window-centered tabs. Deferred: responsive breakpoint collapse (1320/1060/880) |
| LayoutPresetButton | v1 | yes | yes | the studio button — cycles floating → docked → canvas. Deferred: dropdown menu listing all modes |
| Timeline / DopeSheet | **v1** | yes | full | labeled tracks, keyframe diamonds, adaptive ruler, scrub/playhead, transport, keyframe select. Deferred until engine clip-CRUD: keyframe drag/add/delete, curves view |

The planned CAD-system widget expansion in
`dev/docs/roadmap/Aether_CAD_UI_System.md` is now represented in the shipped
matrix above. Remaining roadmap work is product adoption and Core-backed screen
behavior, not another parallel primitive set.

The reuse-first rule is the normal architecture: hierarchical product lists use
Tree; flat selectable lists use ListBox; tabular data uses DataTable; popup
commands use Menu; property editors use the shared field family and
PropertyGrid. Product applications usually supply schemas, rows, commands, and
event handlers only. Purpose-built exceptions are allowed when documented and
tested as described above.

Work the matrix top to bottom; a row is done when all three columns are
full. Contributions (either agent) follow the same definition of done.


### Studio convergence — 2026-09-08

WorkspaceShell now offers retained panel content (`preservePanelContent`),
validated per-preset device-local layouts (`storageKey` for uncontrolled state),
keyboard movement on floating headers, resize clamping, and compact rail-revealed
side panels. CAD and Animation both consume the shell and ViewportNavigationCube.
Native StudioDesignProfile is the structural theme baseline. Product CSS should
compose layout, not override shared control typography/colors or ViewCube skins.
