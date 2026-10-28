import type { AppUpdate, EngineStatus, GatewayMessage, Problem, WindowAction } from './protocol';

/**
 * What the desktop app does on its own, without the engine (decision 0016): updates, logs, bug reports, links.
 * They keep working when the engine is down, so the engine's failure screen can offer them.
 */
export interface DesktopActions {
  checkUpdate(): Promise<AppUpdate | null>;
  installUpdate(): Promise<void>;
  openLogs(): Promise<void>;
  reportIssue(): Promise<void>;
  openUrl(url: string): Promise<void>;
  /* Optional so a test transport can leave them out; the adapter then says "not connected yet". */
  pickFile?(opts: { title?: string; filters?: { name: string; extensions: string[] }[] }): Promise<string | null>;
  pickFolder?(opts: { title?: string }): Promise<string | null>;
  openPath?(path: string): Promise<void>;
  windowAction?(action: WindowAction): Promise<void>;
  saveSupportLogs?(): Promise<string | null>;
}

/**
 * How the frontend reaches the engine. Two implementations:
 * - tauri.ts: the desktop app, through Rust (production).
 * - mock.ts: an in-memory engine for development and the browser preview.
 * Nothing else in the app imports either; they get a GatewayTransport.
 */
export interface GatewayTransport {
  readonly kind: 'tauri' | 'mock';
  /** The engine's state right now. */
  status(): Promise<EngineStatus>;
  /** Ask Rust to start the engine again. */
  restart(): Promise<void>;
  /**
   * Run an engine operation by its OpenAPI operation id. `epoch` pins the call to one
   * engine process: Rust refuses it with stale_epoch if that process is gone, so a cancel
   * meant for job j3 of the old engine can never hit j3 of the new one.
   */
  call<T = unknown>(operation: string, params?: Record<string, unknown>, opts?: { epoch?: number }): Promise<T>;
  /**
   * Open the one ordered stream of status and events. Resolves once Rust has
   * registered it; the returned function closes it. Callers go through the
   * hub (hub.ts), which keeps a single stream however many listeners there are.
   */
  subscribe(onMessage: (m: GatewayMessage) => void): Promise<() => void>;
  /** The app's own actions (desktop and preview); absent in test transports. */
  readonly app?: DesktopActions;
}

/** Every failed gateway call rejects with this, so the UI can tell codes apart and always has a sentence. */
export class GatewayError extends Error implements Problem {
  readonly code: string;
  readonly details?: Record<string, unknown>;
  constructor(p: Problem) {
    super(p.message);
    this.name = 'GatewayError';
    this.code = p.code;
    this.details = p.details;
  }
}

/** Whatever a transport rejected with, as a GatewayError with a readable message. */
export function toGatewayError(e: unknown): GatewayError {
  if (e instanceof GatewayError) return e;
  if (e && typeof e === 'object' && 'code' in e && 'message' in e) {
    const p = e as Problem;
    return new GatewayError({ code: String(p.code), message: String(p.message), details: p.details });
  }
  if (typeof e === 'string') return new GatewayError({ code: 'gateway_error', message: e });
  return new GatewayError({ code: 'gateway_error', message: e instanceof Error ? e.message : 'Something went wrong talking to the engine.' });
}

export const isGatewayError = (e: unknown, code?: string): e is GatewayError => e instanceof GatewayError && (code === undefined || e.code === code);
