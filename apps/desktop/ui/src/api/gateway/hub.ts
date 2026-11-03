import type { EngineStatus, GatewayMessage } from './protocol';
import { toGatewayError, type DesktopActions, type GatewayTransport } from './transport';

/**
 * The app's one connection to the gateway. However many parts of the UI
 * listen, there is a single IPC stream: opened with the first listener,
 * closed with the last, reopened (with a growing pause) if it breaks.
 * It also remembers the newest engine status, and drops status messages
 * from an older epoch so a late message can't roll the UI back.
 */
export interface Gateway {
  readonly kind: GatewayTransport['kind'];
  /** The newest status seen, if any. */
  current(): EngineStatus | undefined;
  /** Listen to status and events. The returned function stops listening. */
  on(listener: (m: GatewayMessage) => void): () => void;
  /** Run an engine operation. `epoch: 'current'` pins it to the engine the UI is looking at. */
  call<T = unknown>(operation: string, params?: Record<string, unknown>, opts?: { epoch?: number | 'current' }): Promise<T>;
  /** Ask Rust for the status again (after a failed subscribe, or from a Retry button). */
  refresh(): Promise<EngineStatus>;
  restart(): Promise<void>;
  /** For tests: how many IPC streams are open (0 or 1). */
  openStreams(): number;
  /** The app's own actions (updates, logs, reports, links), when the transport has them. */
  readonly app?: DesktopActions;
}

const RETRY_MS = [500, 1000, 2000, 5000, 10000];

export function createGateway(t: GatewayTransport): Gateway {
  const listeners = new Set<(m: GatewayMessage) => void>();
  let latest: EngineStatus | undefined;
  let close: (() => void) | undefined;
  let streams = 0;
  let generation = 0; // bumps on every open/close, so a slow subscribe from an old generation closes itself
  let attempt = 0;
  let retryTimer: ReturnType<typeof setTimeout> | undefined;

  const deliver = (m: GatewayMessage) => {
    if (m.kind === 'status') {
      if (latest && m.status.epoch < latest.epoch) return; // an older engine's news
      latest = m.status;
    }
    listeners.forEach((l) => l(m));
  };

  const open = () => {
    const mine = ++generation;
    // A fresh callback per stream: closing an abandoned stream must never remove the live one's listener.
    void t.subscribe((m) => { if (mine === generation) deliver(m); }).then(
      (unsub) => {
        if (mine !== generation || !listeners.size) { unsub(); return; }
        attempt = 0;
        streams = 1;
        close = () => { streams = 0; unsub(); };
        // The stream may not repeat the current status, so ask once it is open (duplicates are harmless).
        void t.status().then((s) => deliver({ kind: 'status', status: s }), () => {});
      },
      (e) => {
        if (mine !== generation || !listeners.size) return;
        const err = toGatewayError(e);
        deliver({ kind: 'status', status: { state: 'unavailable', epoch: latest?.epoch ?? 0, problem: { code: err.code, message: err.message } } });
        retryTimer = setTimeout(() => { if (mine === generation && listeners.size) open(); }, RETRY_MS[Math.min(attempt++, RETRY_MS.length - 1)]);
      },
    );
  };

  const shut = () => {
    generation++;
    if (retryTimer) clearTimeout(retryTimer);
    close?.();
    close = undefined;
  };

  return {
    kind: t.kind,
    current: () => latest,
    on(listener) {
      listeners.add(listener);
      if (latest) listener({ kind: 'status', status: latest });
      if (listeners.size === 1) open();
      return () => {
        if (!listeners.delete(listener)) return;
        if (!listeners.size) shut();
      };
    },
    call<T>(operation: string, params?: Record<string, unknown>, opts?: { epoch?: number | 'current' }) {
      const epoch = opts?.epoch === 'current' ? latest?.epoch : opts?.epoch;
      return t.call<T>(operation, params, epoch === undefined ? undefined : { epoch }).catch((e: unknown) => { throw toGatewayError(e); });
    },
    async refresh() {
      const s = await t.status();
      deliver({ kind: 'status', status: s });
      return s;
    },
    restart: () => t.restart().catch((e) => { throw toGatewayError(e); }),
    openStreams: () => streams,
    app: t.app,
  };
}
