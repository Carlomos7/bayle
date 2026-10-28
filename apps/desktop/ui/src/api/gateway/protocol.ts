/**
 * The React ⇄ Rust gateway protocol, as the frontend needs it.
 *
 * STATUS: PROPOSAL. Nothing here is agreed with the Tauri/Rust workstream yet.
 * See docs/INTEGRATION.md › "Gateway contract (proposal)". Names of commands
 * and message kinds may change; the shapes below are what the UI relies on.
 *
 * React never sees the engine's port, token or URLs. It asks Rust to run an
 * engine operation by its OpenAPI operation id, and Rust forwards one ordered
 * stream of engine status and engine events, stamped with the engine epoch.
 *
 * Engine shapes (EngineJob, the event envelope and its data) mirror
 * apps/engine/src/bayle/api/models.py (contract "1"). They are hand-copied for
 * now and should be generated from docs/api/openapi.json once the gateway
 * contract settles; keep this file the only place they are declared.
 */

/** Bumped when this protocol changes incompatibly. Rust reports the one it speaks in EngineStatus. */
export const GATEWAY_PROTOCOL = 1;

/* ------------------------------------------------------------------ engine lifecycle */

/**
 * What Rust says about the Python engine.
 * - starting: Rust launched it and is waiting for its handshake and /v1/health.
 * - ready: health answered with a compatible contract; calls and events flow.
 * - unavailable: it was ready and stopped answering; Rust has not decided yet (brief).
 * - restarting: Rust is starting a replacement on its own. A new epoch follows.
 * - failed: Rust gave up (crashed on start, repeated crashes). Only a retry starts it again.
 * - incompatible: it answered with a contract major this app does not speak. Retrying won't help.
 */
export type EngineState = 'starting' | 'ready' | 'unavailable' | 'restarting' | 'failed' | 'incompatible';

export interface EngineStatus {
  state: EngineState;
  /**
   * Which engine process this is. Rust increments it every time it starts one. Job ids and event
   * sequence numbers restart with each process, so they only mean something together with the epoch.
   */
  epoch: number;
  /** The gateway protocol Rust speaks (see GATEWAY_PROTOCOL). */
  protocol?: number;
  /** From the engine's handshake and /v1/health, when known. */
  engineVersion?: string;
  contract?: string;
  /** The contract major this app expects, for the incompatible screen. */
  expectedContract?: string;
  /** For failed, unavailable and incompatible: a plain sentence. Never paths, ports or tokens. */
  problem?: Problem;
}

/* ------------------------------------------------------------------ errors */

/**
 * Every failed call rejects with this shape: the engine's own Problem
 * ({code, message, details}) passed through, or one of the gateway's codes.
 */
export interface Problem {
  code: string;
  message: string;
  details?: Record<string, unknown>;
}

/** Codes the gateway itself may answer with, besides the engine's (busy, not_found, stale, …). */
export type GatewayErrorCode =
  | 'engine_unavailable' // not ready: starting, restarting, failed
  | 'stale_epoch' // the call named an epoch that is no longer the current engine
  | 'not_allowed' // the operation id is not in the gateway's allowlist
  | 'not_wired' // the frontend has no mapping for this yet (frontend-only code)
  | 'gateway_error'; // anything else Rust could not do

/* ------------------------------------------------------------------ jobs */

export type EngineJobState = 'running' | 'done' | 'failed' | 'cancelled';

export interface EngineProgress {
  done?: number | null;
  total?: number | null;
  label?: string;
}

/** GET /v1/jobs/{id} and POST /v1/jobs/{id}/cancel answer with this. */
export interface EngineJob {
  id: string;
  title: string;
  state: EngineJobState;
  progress?: EngineProgress | null;
  result?: unknown;
  error?: Problem | null;
  undo?: Record<string, unknown> | null;
}

/** A job is only identified by its id together with the engine epoch that ran it. */
export interface JobRef {
  epoch: number;
  id: string;
}

/* ------------------------------------------------------------------ events */

interface Envelope<T extends string, D> {
  /** Stamped by Rust: the engine process the event came from. */
  epoch: number;
  /** The engine's sequence number: strictly increasing within one epoch. */
  seq: number;
  job_id: string | null;
  type: T;
  data: D;
}

export type EngineEvent =
  | Envelope<'started', { title: string; quiet?: boolean }>
  | Envelope<'progress', EngineProgress & { detail?: Record<string, unknown> }>
  | Envelope<'log', { text: string; level: string }>
  | Envelope<'prompt', Record<string, unknown>>
  | Envelope<'finished', { result?: unknown; undo?: Record<string, unknown> | null }>
  | Envelope<'failed', { error: Problem; unexpected?: boolean }>
  | Envelope<'cancelled', { error: Problem; unexpected?: boolean }>
  /** The engine could not replay what was asked: refetch state (jobs, pages), then continue. */
  | Envelope<'resync', { requested: number; oldest: number; seq: number }>
  | Envelope<'game.state', { game: string; running: boolean; steam_problem?: boolean; dead_shells?: number }>
  | Envelope<'invalidated', { what: string[] }>
  | Envelope<'notice', { text: string; error?: boolean; details?: boolean }>
  | Envelope<'navigate', { page: string }>;

export type EngineEventType = EngineEvent['type'];
export const TERMINAL_EVENTS = new Set<EngineEventType>(['finished', 'failed', 'cancelled']);

/**
 * One ordered stream from Rust: status changes and engine events on the same
 * channel, so a new epoch's status always arrives before that epoch's events.
 */
export type GatewayMessage =
  | { kind: 'status'; status: EngineStatus }
  | { kind: 'event'; event: EngineEvent };

/* ------------------------------------------------------------------ commands (proposal) */

/**
 * The Tauri commands the frontend calls. Deliberately few: one generic
 * engine call keyed by OpenAPI operation id instead of one command per
 * operation, so the Rust side can allowlist ids from the committed OpenAPI
 * snapshot without a wrapper per endpoint.
 */
export const COMMANDS = {
  /** () → EngineStatus */
  status: 'engine_status',
  /** () → void. Start the engine again after failed/unavailable. Idempotent while starting. */
  restart: 'engine_restart',
  /** ({ channel }) → void. Rust sends GatewayMessage on the channel until engine_unsubscribe or the webview goes. */
  subscribe: 'engine_subscribe',
  /** ({ channelId }) → void */
  unsubscribe: 'engine_unsubscribe',
  /** ({ operation, params?, epoch? }) → the operation's JSON result, or rejects with Problem. */
  call: 'engine_call',
  /** () → AppShellInfo. This build's version, update channel, data folder and platform. */
  appInfo: 'app_info',
  /** () → AppUpdate | null. Rust checks this channel's signed manifest; works with the engine down. */
  updateCheck: 'app_update_check',
  /** () → void. Installs the update found by updateCheck; the app restarts on the new version. */
  updateInstall: 'app_update_install',
  /** () → void. Opens the folder with Bayle's logs. */
  openLogs: 'app_open_logs',
  /** () → void. Opens a new bug report in the browser. */
  reportIssue: 'app_report_issue',
  /** ({ url }) → void. Opens an https link in the browser; anything else is refused. */
  openUrl: 'app_open_url',
  /** ({ title?, filters? }) → path | null. The native file dialog. */
  pickFile: 'app_pick_file',
  /** ({ title? }) → path | null */
  pickFolder: 'app_pick_folder',
  /** ({ path }) → void. A folder opens; a file is shown in its folder. Never runs a file. */
  openPath: 'app_open_path',
  /** ({ action }) → void. minimize | toggle_maximize | close, on the main window. */
  window: 'app_window',
  /** () → boolean. Whether the main window is maximized (the title bar shows Restore). */
  windowMaximized: 'app_window_maximized',
  /** () → zip path | null (null: the save dialog was cancelled). */
  saveSupportLogs: 'app_save_support_logs',
} as const;

export type WindowAction = 'minimize' | 'toggle_maximize' | 'close';

/** An update Rust found (decision 0016): signed, and only ever a newer version. */
/** What Rust knows about this build (app_info). */
export interface AppShellInfo {
  version: string;
  channel: string;
  dataFolder: string;
  platform: string;
}

export interface AppUpdate {
  version: string;
  current: string;
  notes?: string | null;
}

/**
 * Engine operations the frontend uses so far, by OpenAPI operation id
 * (FastAPI route name). Rust maps each to its method and path.
 */
export const OPERATIONS = {
  health: 'health',
  getJob: 'get_job',
  cancelJob: 'cancel_job',
  answerPrompt: 'answer_prompt',
  activity: 'activity',
  activityLog: 'activity_log',
} as const;
