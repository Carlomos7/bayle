# How the UI is put together

## Layers

| Layer | Folder | Owns |
|---|---|---|
| Contract | `src/api/types.ts`, `src/api/BayleApi.ts` | Data shapes and every backend call. The only thing Python must match. |
| Gateway | `src/api/gateway/`, `src/api/index.ts` | The only code that knows how the engine is reached: the Tauri transport, the hub (one stream for the app), the protocol (a proposal), the production `BayleApi` adapter, and the mock engine for the preview. See INTEGRATION.md. |
| Preview | `src/api/preview.ts`, `src/api/mock/` | The mock `BayleApi` and its seed data, on the mock engine. Stubbed out of desktop builds. |
| Data | `src/data/` | TanStack Query hooks (`useProfile`, `useSaves`…), `useAction` (change + toast + Undo), `useCall` (plain calls), cache keys, the backend event listener. |
| Engine | `src/data/engine.ts`, `src/data/jobState.ts` | Engine lifecycle (starting, ready, restarting, failed, incompatible) and jobs (progress, Stop, endings), with the ordering rules: epochs, sequence numbers, first ending wins. |
| Routing | `src/routes/`, `src/router.ts`, `src/app/nav.ts` | Which page is open, and one-shot "open this" requests (`/mods?mod=`, `/configs?file=`, `/settings?section=`). |
| UI state | `src/state/` | Zustand stores for what only the UI cares about and isn't in the URL: game, launch mode, open dialog, palette. `toast()` wraps Sonner. |
| Primitives | `src/components/ui/` | shadcn/ui components on Radix, themed with Bayle's variables. Kept close to upstream so the shadcn CLI can update them. |
| Compositions | `src/components/bayle/` | Bayle-shaped pieces built from the primitives: `Dialog`, `Sheet`, menus from a list of entries, `Segmented`, `NameDialog`, tags, the file tree, page layout. Pages import from here first. |
| Shell | `src/app/` | Layout, menu bar, top bar (Launch, game, profile), page rail, command palette (Ctrl+K), global dialogs, shortcuts, theme. |
| Pages | `src/features/<page>/` | Mods, Mod Configs (+ `overhaul/` setup), Saves, Activity, Settings. |

Rule of thumb: **where you are lives in the URL, backend data lives in
TanStack Query, the rest of the UI state lives in Zustand, and a component
never calls the API directly.** It uses a hook from `src/data/hooks.ts`.

## Two levels

`components/bayle/advanced.tsx` is the one door to the second level: a folded
row whose label says what is inside. Use it on any page where rarely used
detail would crowd the common case; never add a global "advanced mode".

`features/mods/health.ts` is the single source for "what needs the user":
the chip next to Launch, the Before you play panel (`app/shell/HealthSheet.tsx`)
and the notices on Mods all read it, so they never disagree. Each item carries
its fix, so the panel can act without knowing the pages.

## Routing

File routes in `src/routes/` (TanStack Router, generated into
`src/routeTree.gen.ts`). Pages are code-split per route. Hash history keeps
the built app working from `file://` and inside a webview.

Navigate with `useGo()` from `src/app/nav.ts`: `go.page('saves')`,
`go.openMod(id)`, `go.openConfig(fileId)`, `go.openSettings('appearance')`.
Search params are validated with Zod in each route. A page reads its request
with `useSearchRequest`, acts on it once, and clears it from the URL, so Back
and reloads don't reopen things.

## Builds

`BuildReport` (`src/api/types.ts`) is the contract for merged game data:
state, the changes since the last build, the board cells (mod × file family ×
outcome), the clashes with how each is settled, and the dropped changes. The
backend owns all of it; the UI only reads it and calls `resolveClash` and
`rebuildMerged`. Clash picks are backend state, keyed by clash id, so they
survive rebuilds and are flagged `needsReview` when an input changes.

The mock marks a build stale from the same places the real backend would
(toggle, reorder, remove, a mod update, a changed pick) and records the reason.

Two more reads sit beside it: `searchPieces` (the piece index read backwards,
for "which mod changed this") and `suggestOrder` (a proposed order with a
reason per move; it changes nothing until `reorderMods`). `profileHealth` in
`features/mods/health.ts` turns profile + build into the one line next to
Launch and the notices on Mods, so both always agree.

## Forms

React Hook Form with a Zod schema; errors show under the field and Save stays
disabled until the form is valid.

- `NameDialog` (`components/bayle/name-dialog.tsx`): every "name this" dialog
  (new profile, renames, keep a copy). Required, length, and not already taken.
- Mod panel options: `features/mods/modOptions.ts` (package id unique in the
  profile, rebuild file when it stays last, initializer name or delay).
- Config files: `useConfigDraft` builds a schema from the file's fields
  (whole numbers, decimals, listed values). Numbers are kept as typed and
  converted on save, so a half-typed value is an error, not a silent revert.
- Settings number boxes save on blur or Enter when valid.

For a new form, use the shadcn `Form` components in `components/ui/form.tsx`.

## Changing something

```tsx
const { run } = useAction();
run((api) => api.setModsEnabled(profile.id, ids, false));
```

`run` awaits the call, shows the backend's message as a Sonner toast with Undo,
refreshes cached data, and turns errors into an error toast. Use `useCall` for
calls that aren't undoable actions (switching profile, changing a setting).

## Styling

Tailwind v4, driven by theme variables. `src/styles/index.css` defines each
theme (`dark`, `tarnished`, `light`, `bayle`) as CSS variables on
`<html data-theme>`, and `@theme inline` exposes them as utilities:
`bg-panel`, `text-t2`, `border-line2`, `text-accent`, `bg-ok-bg`…

Colour roles:

- `accent` is the brand colour: the main action, where you are, links.
- `on`/`on-ink` are for "on" states (switches, ticked boxes). In Bayle they're
  white, so red never reads as an alarm.
- `ok`, `warn`, `bad`, `info`, `vio` are status and tag colours. Tag meaning:
  info = shared, vio = part of an overhaul, warn = needs care, neutral = how it loads.

shadcn's token names (`background`, `primary`, `muted-foreground`, `ring`…)
are aliased to these, so stock shadcn components fit in. One difference:
here `accent` is the brand colour, not shadcn's hover background; Bayle's
components use `bg-hover` for that.

Motion is CSS only: Tailwind transitions plus `tw-animate-css` for dialog,
menu and sheet enter/exit. The Effects setting turns them down or off.

Corners are 2, 3 or 4px (`rounded-xs`, `rounded-sm`, `rounded-lg`). Round
things (switches, dots, avatars) stay round.

Type sizes are named by role in `@theme`; use these, not `text-[Npx]`:

| Class | Size | For |
|---|---|---|
| `text-badge` | 10px | count badges |
| `text-tag` | 10.5px | small uppercase tags, step numbers |
| `text-micro` | 11px | column headers, keyboard hints |
| `text-caption` | 11.5px | secondary lines, chips |
| `text-code` | 12px | inline code, small mono values |
| `text-ui` | 12.5px | controls and rows (the default) |
| `text-body` | 13px | primary row text, dialog body |
| `text-emphasis` | 13.5px | row titles (mod and setting names) |
| `text-section` | 15px | section headings |
| `text-heading` | 22px | dialog, sheet and settings section titles |
| `text-title` | 26px | full-window screens |
| `text-display` | 30px | page titles |

A new size goes in `@theme` **and** in the `text` list in `src/lib/utils.ts`:
`cn()` (tailwind-merge) must know it is a font size, or it reads `text-ui` as
a colour and drops it next to `text-t3`.

Tints of a theme colour use Tailwind's opacity modifier (`border-warn/35`,
`bg-t1/4`), not `color-mix()` by hand. Hand-written `color-mix` is only for
mixing into an opaque surface (`color-mix(in srgb, var(--t1) 4%, var(--panel))`
for sticky headers that must hide what scrolls under them) and inside shadows.

Tailwind 4 syntax: important goes last (`size-3!`); `outline-hidden`, not
`outline-none`, so focus stays visible in Windows High Contrast. Join class
names with `cn()`, never template strings.

To add a theme, copy a `[data-theme="…"]` block, change the variables, and add
it to `ThemeName` in `types.ts` and the theme picker.

## Messages: which kind, and where

| Kind | Use it for | Where | Lifetime |
|---|---|---|---|
| Toast (Sonner) | The result of something the user just did, with Undo | Bottom right; moves up above the bulk bar, the unsaved bar and panel footers; full width of the content column under 600px | 4.5 s, 7 s with Undo, errors stay until closed |
| Notice strip | A state that needs the user, with its fix on the same line | Top of the page it belongs to; wraps, actions drop below the text under 700px | Until fixed |
| Before you play | Every notice for the active profile, gathered | A panel from the chip next to Launch, on any page | Until fixed |
| First-visit card | A one-time explanation of a page | Top of that page | Gone for good once dismissed |
| Status chip | A state, never a verb (Ready, Missing, Stale) | In place, next to the thing | While true |

Never a toast for a state, never a notice for an action's result, and never a modal for either.

## Conventions

- Strict TypeScript, no `any`. Shared shapes come from `@/api`.
- React 19: `ref` is a plain prop; no `forwardRef`.
- One component per file once it has its own state or passes ~150 lines: the mod panel is `features/mods/ModPanel.tsx` plus one file per tab in `features/mods/panel/`; Merge has one file per section.
- Accessibility is linted (`eslint-plugin-jsx-a11y`). Click handlers go on buttons, not `div`s; a row that opens on click ignores clicks that start on a control inside it. Custom widgets don't claim ARIA roles whose keyboard model they don't implement (the file tree is a list with disclosure buttons, not a `tree`).
- Statuses are states, not verbs ("Missing", not "Install again"), and never promises: "In place" and "Built" say what Bayle checked, not that the game will like it.
- Disabled menu items say why (`why`), instead of just greying out.
- Every list has an empty state, and every destructive action confirms and is undoable.
- Keyboard: Ctrl+1–5 pages, Ctrl+K search, Ctrl+L launch, Ctrl+N new profile,
  Ctrl+O install, F1 help, F5 rescan, `/` search on the page, Esc closes or clears.
