# Desktop integration: React ⇄ Rust gateway ⇄ Python engine

Status: frontend preparation done; nothing has run against a real Rust gateway yet.
The gateway contract below is a **proposal** for the Tauri/Rust workstream.

```text
React + TypeScript (this repo)
   │  typed Tauri commands + one ordered Channel         ← src/api/gateway/tauri.ts is the only Tauri import
   ▼
Tauri 2 / Rust gateway (not in this repo)
   │  authenticated loopback HTTP + SSE                  ← port, token, URLs, lifecycle: Rust only
   ▼
Bayle Python engine (FastAPI, apps/engine in roundtable-souls)
```

## 1. Audit: what was already compatible

| Area | Finding | Tauri-ready? |
|---|---|---|
| Framework | React 19, Vite 8 (Rolldown), TypeScript 6 strict, pnpm | Yes |
| Output | Static SPA, `base: './'`, hash history (TanStack Router), code-split routes | Yes: loads from Tauri's asset protocol as is |
| SSR / Next.js / Node APIs | None in the app (`node:` only in config and tests) | Yes |
| Assets | Fonts via `@fontsource` (bundled), images local, no CDN | Yes; checked by `boundary.test.ts` |
| State | TanStack Query (engine data), Zustand (UI-only: game, launch mode, dialogs), URL (where you are) | Yes |
| Components | shadcn/ui on Radix, Lucide, cmdk, Sonner, Tailwind 4 | Yes |
| API boundary | One typed interface (`BayleApi`); pages reach it only through hooks in `src/data/` | Yes, kept as is |
| Browser APIs | `localStorage` (theme, UI prefs, wrapped in try/catch), `navigator.clipboard` (two Copy buttons), `window.open` (mock only) | Yes; `openUrl` should become a gateway command |
| Inline styles | React `style` props (CSSOM, not blocked by CSP); Sonner and Radix inject `<style>` tags at runtime | Needs `style-src 'self' 'unsafe-inline'` (see §5) |
| Tests | ESLint, `tsc`; the browser click-through suites lived outside the repo | Added Vitest for the integration layer |

**Gaps found, and what was done**

| Gap | Change |
|---|---|
| `src/api/bridge.ts` had pywebview, Qt WebChannel and **direct HTTP to `127.0.0.1:8765`** transports | Removed with `backend/` (pywebview example, Python stub) and its generator. History keeps them. |
| The mock was the default in every build, including production | Inside Tauri the gateway is always used. Outside it: the mock only in `vite dev` or `pnpm build:demo` (labelled "Preview data"). A production build in a browser says "Open Bayle from its desktop app". Desktop builds don't contain the mock: `@/api/preview` is aliased to a stub. |
| Long operations were awaited promises with a "busy" line | Jobs: id + epoch, progress, Stop (requested vs done), endings, recovery |
| No engine lifecycle | Start screen, failed (Try again), incompatible, reconnecting banner, queries paused while away |
| Events had no order or identity | Envelope with engine `seq` + gateway `epoch`; stale, duplicate and out-of-order events can't change state |

## 2. Architecture (frontend)

```text
src/
  api/
    BayleApi.ts, types.ts      what the UI needs (unchanged; pages use it via hooks)
    index.ts                   picks desktop | preview | outside-desktop, once, at startup
    guard.ts                   calls fail fast with a sentence while the engine isn't ready
    gateway/
      protocol.ts              PROPOSAL: commands, status, events, jobs, problems (engine shapes mirrored)
      transport.ts             GatewayTransport interface + GatewayError
      tauri.ts                 production transport: invoke + Channel (the only @tauri-apps import)
      hub.ts                   one stream for the whole app, reconnect, newest-epoch status
      gatewayApi.ts            BayleApi over the gateway (production adapter; wired method by method)
      mock.ts                  mock engine: boots, epochs, jobs, cancel, crash/fail/incompatible
    preview.ts                 mock engine + mock BayleApi (aliased to preview.disabled.ts in desktop builds)
    mock/                      the mock BayleApi and its seed data
  data/
    engine.ts                  stores + wiring: engine status, jobs, query pausing, resync refetch, Stop, awaitJob
    jobState.ts                pure job rules (tested on their own)
  app/shell/EngineScreens.tsx  start / failed / incompatible screens, reconnect banner, outside-desktop
```

Rules: components never import `api/gateway/*` or `api/mock/*` (tested). Engine data stays in TanStack Query; engine
lifecycle and jobs in two small Zustand stores. React decides nothing about the engine; it shows what Rust reports.

### Jobs

- An operation that starts a job gets `{job_id}`. The UI keys it as `{epoch, id}` (`j3` restarts with every engine).
- Events apply only if `epoch` is current and `seq` is above the last applied one (duplicates from replays and
  out-of-order events are ignored). A newer epoch first marks the old epoch's running jobs **lost** ("how it ended is
  unknown, check Activity"). Nothing resumes on its own.
- The first ending (`finished` / `failed` / `cancelled`) wins; later events for that job are ignored.
- Stop calls `cancel_job` pinned to the job's epoch and shows "Stopping…" until the engine's ending arrives; the
  cancel answer only means "asked". An old-epoch cancel is refused by the gateway (`stale_epoch`), never applied to the
  new engine's job with the same id.
- `resync` (or events for a job never seen starting) → read those jobs back with `get_job` (one request per job);
  snapshots only move a job forward. `not_found` → lost.
- `awaitJob(ref)` lets an adapter method keep its promise shape: resolve on finished, reject with the ending's code.
- One gateway stream for the app (the hub); listeners unsubscribe on unmount; React StrictMode double effects leave
  exactly one live stream (tested).

### Engine lifecycle

| State (from Rust) | Before first ready | After it has been ready |
|---|---|---|
| starting | "Starting Bayle…" (no timers decide anything; a note after 6 s) | banner "restarting…" |
| ready | the app | the app; a **new** epoch re-reads all queries |
| unavailable | "Can't reach Bayle's engine" + Try again | banner "Reconnecting…" + Retry now |
| restarting | start screen | banner |
| failed | "Bayle's engine didn't start" + Try again + Copy details | banner + Try again |
| incompatible | "This engine doesn't match this app" (no retry) | same screen |

While not ready, TanStack Query is offline (queries pause and resume) and every `BayleApi` call rejects at once with
`engine_unavailable`.

## 3. Gateway contract (agreed)

Implemented by the Rust gateway in `Carlomos7/bayle` `apps/desktop` (branch `feat/tauri-foundation`): `engine_status`,
`engine_restart`, `engine_subscribe`, `engine_unsubscribe`, `engine_call` and the `app_*` commands below. For
`engine_call`, Rust splits `params` into path, query and body from the OpenAPI contract, and answers `stale_epoch`
when `epoch` is old. Recovery is forward-only (decision 0016): update or reinstall, never roll back.

Few commands on purpose: one generic `engine_call` keyed by OpenAPI operation id, so Rust can allowlist operations
from the committed `docs/api/openapi.json` instead of a wrapper per endpoint.

### Commands

| Command | Args | Returns | Notes |
|---|---|---|---|
| `engine_status` | — | `EngineStatus` | Current state; cheap; callable any time. |
| `engine_restart` | — | `()` | Start the engine again (Try again). Idempotent while starting. |
| `engine_subscribe` | `{ channel: Channel<GatewayMessage> }` | `()` | Rust sends status and events on this channel, in order, until unsubscribed or the webview goes. |
| `engine_unsubscribe` | `{ channelId: number }` | `()` | |
| `engine_call` | `{ operation: string, params: object, epoch: number \| null }` | the operation's JSON result | `operation` = FastAPI route name (`activity`, `get_job`, `cancel_job`, …). Rust maps it to method + path, adds the token, refuses ids not on its allowlist (`not_allowed`). If `epoch` is set and isn't the current engine: `stale_epoch`. |

Every rejection is a `Problem` `{ code, message, details? }`: the engine's own (passed through unchanged) or the
gateway's, as bare names: `engine_unavailable`, `stale_epoch`, `not_allowed`, `bad_parameter`, `timeout`,
`gateway_error`. Messages are plain sentences; never
paths with tokens, ports or URLs.

The app's own commands work with the engine down, so the failed, incompatible and stopped screens offer them:

| Command | Args | Returns | Notes |
|---|---|---|---|
| `app_update_check` | — | `{ version, current, notes? }` or `null` | Signed manifest of this channel; only newer versions. |
| `app_update_install` | — | `()` | Installs what the check found; the app restarts. |
| `app_open_logs` | — | `()` | Opens the logs folder. |
| `app_report_issue` | — | `()` | Opens a new bug report in the browser. |
| `app_open_url` | `{ url }` | `()` | `https` only; anything else is refused. |

### Messages on the channel

```ts
type GatewayMessage =
  | { kind: 'status'; status: EngineStatus }
  | { kind: 'event'; event: { epoch: number; seq: number; job_id: string | null; type: string; data: object } };

interface EngineStatus {
  state: 'starting' | 'ready' | 'unavailable' | 'restarting' | 'failed' | 'incompatible';
  epoch: number;            // +1 every time Rust starts an engine process
  protocol?: number;        // this gateway protocol (1)
  engineVersion?: string; contract?: string; expectedContract?: string;
  problem?: { code: string; message: string };
}
```

- Status and events share one channel so a new epoch's status always precedes its events.
- `event` is the engine's SSE envelope (`apps/engine/src/bayle/api/routes.py`) plus `epoch`, forwarded in order.
- Rust holds **one** SSE connection (the engine allows 3) and fans it out; on reconnect it sends `Last-Event-ID`
  and forwards the engine's `resync` if one comes.
- Rust sends a status message on every state change, and should send the current one right after subscribe
  (the frontend also asks `engine_status`, so either way works).

### Suggested Tauri configuration

- **Capabilities:** only these custom commands for the main window. No `fs`, `shell`, `http` or `process` plugins
  for the webview (tested: the frontend imports none). Opening links: a small `open_url` command with an `https`
  allowlist, or `tauri-plugin-opener` scoped to `https://*`.
- **CSP** (`tauri.conf.json › app.security.csp`):
  ```json
  {
    "default-src": "'self'",
    "script-src": "'self'",
    "style-src": "'self' 'unsafe-inline'",
    "img-src": "'self' data: asset: http://asset.localhost",
    "font-src": "'self' data:",
    "connect-src": "ipc: http://ipc.localhost"
  }
  ```
  `'unsafe-inline'` for styles is needed by Sonner and Radix's scroll lock, which inject `<style>` at runtime;
  scripts stay strict. **No `http://127.0.0.1:*` in `connect-src`**: the webview never talks to the engine.

## 4. What is wired, mocked, blocked

| | Status |
|---|---|
| Engine lifecycle, jobs, Stop, recovery | Done on the frontend; runs on the mock engine; waits for Rust |
| Activity list + job log (`activity`, `activity_log`) | Wired in `gatewayApi.ts`. **Provisional mapping**: the engine types `ActivityJobs.jobs` as `dict[str, Any]`; fields taken from `adapters/system/logging.py _record` |
| Engine pushes | `invalidated` → cache scopes (provisional names), `notice` → toast, `game.state` → status line, job endings → Activity refresh |
| Every other `BayleApi` method | Rejects with `not_wired` ("isn't connected to the engine yet"). In the desktop app those pages show that error; in the preview they run on the mock |
| Prompts (`prompt` events, `answer_prompt`) | Kept in job state; no UI yet (the engine uses them only in the Launch flow) |
| Undo via the engine (`activity_undo` with the confirmed record) | Not wired |
| Mod versions, thumbnails | Hidden or placeholder until the engine provides them (`FEATURES.modVersions`) |

## 5. Decisions that need the other workstreams

1. **Decision record 0011 conflicts with the approved architecture.** It (still "Proposed") has the webview call
   FastAPI directly over loopback with a token and `connect-src http://127.0.0.1:*`. Approved: React → Rust only.
   0011 should be updated or superseded; its token, port-0 handshake, host check and SSE design still apply,
   between Rust and Python.
2. **Engine epoch.** The engine resets `seq` and job ids (`j1`…) per process and has no instance id. Proposal: Rust
   owns the epoch (+1 per spawn) and stamps it. Alternative: the engine reports a random instance id in its
   handshake and `/v1/health`.
3. **The UI contract vs the engine API.** The engine API is shaped after the Qt pages (`GET /v1/mods` returns the
   page's facts; ~150 operations incl. `check_*`/do pairs). The new UI's `BayleApi` is shaped after the new pages
   (builds, clashes, rules, survival, suggestions). Options: engine adds view endpoints for the new UI (preferred:
   no business logic in React), or the frontend adapter maps per page. Decide per page as it is wired.
4. **Typed models for loose dicts** (`ActivityJobs.jobs`, prompt data) in OpenAPI, so the TypeScript types can be
   generated (`openapi-typescript` from `docs/api/openapi.json`) instead of hand-copied in `protocol.ts`.
5. **`engine_call` allowlist** generated from the OpenAPI snapshot at build time, so a new route isn't callable
   until it is in the snapshot.
6. **Cancel semantics.** `POST /v1/jobs/{id}/cancel` returns the job still `running`; the UI treats that as
   "requested" and waits for the event. Confirm that every writing job honours `ctx.cancelled()`, or mark jobs that
   can't be stopped (the UI would hide Stop for them; field proposal: `cancellable` in `StartedData`).

## 6. Handoff for the Tauri/Rust agent

To bring up the first end-to-end slice:

1. Create the Tauri 2 app with this repo's `pnpm build` output (`dist/`) as `frontendDist` and `pnpm dev`
   (`http://localhost:5173`) as `devUrl`. In `tauri dev` the frontend detects Tauri and uses the gateway, not the mock.
2. Spawn the engine (`bayle --backend`, onedir sidecar): token in an env var, read the one-line JSON handshake
   (`port`, `version`, `contract`), poll `/v1/health`, emit `starting` → `ready` (or `incompatible` if the contract
   major differs from the one the app expects, `failed` if it exits). Keep stdin open (watchdog) and use a Job Object
   (decision 0012).
3. Implement the five commands in §3. `engine_call`: map the operation id to method + path (start with `health`,
   `activity`, `activity_log`, `get_job`, `cancel_job`, `answer_prompt`), add `Authorization: Bearer`, return the
   JSON body or the engine's Problem.
4. Hold one SSE connection to `/v1/events`, stamp `epoch`, forward on every subscribed Channel in order; reconnect
   with `Last-Event-ID`.
5. On engine exit: `restarting` (same epoch) → spawn → `starting` with epoch + 1 → `ready`. After repeated
   failures: `failed` until `engine_restart`.
6. Check: Activity lists real jobs; starting a job in the engine shows progress and Stop beside Launch; killing the
   engine shows the banner, marks the running job lost, and the page re-reads after the new engine is ready.

Frontend files to read first: `src/api/gateway/protocol.ts` (the contract the UI expects), `src/api/gateway/tauri.ts`
(how it is called), `src/api/gateway/mock.ts` (the behaviour the UI is tested against).

## 7. Tests

`pnpm verify` runs typecheck, lint, build and `pnpm test` (Vitest, 54 tests):

- `data/jobState.test.ts`: started → progress → ending; duplicates and out-of-order ignored; first ending wins; older
  epochs ignored; same id in two epochs; lost on restart or failure, never resumed; Stop requested vs done; resync and
  mid-job reads; snapshots only forward.
- `data/engine.test.ts`: status → screens and query pausing; re-read on a new epoch; cleanup closes the stream; job
  events through the store; Stop until confirmed; restart loses running jobs and an old cancel can't hit the new
  engine; resync refetch; unknown job → lost.
- `api/gateway/hub.test.ts`: one stream for many listeners; StrictMode; older-epoch status dropped; reconnect after a
  failed subscribe; epoch pinning.
- `api/gateway/gatewayApi.test.ts`, `api/runtime.test.ts`: unwired methods refuse; Activity by operation id;
  defensive mapping; push mapping; mode selection never picks the mock in production; calls fail fast when away.
- `app/shell/EngineScreens.test.tsx` (jsdom): start, failed + Try again, incompatible, banner on restart and failure.
- `api/boundary.test.ts`: no engine address, token, auth header or direct HTTP/SSE in app code; Tauri imported in one
  file; no broad plugins; pages don't import transports; the production bundle has no mock data, no engine address,
  nothing from a CDN.

The browser click-through suites (13 scripts, about 250 checks) pass on the preview with the new layer in place.
