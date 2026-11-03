import type { EngineEvent, EngineJob, EngineStatus, GatewayMessage } from './protocol';
import { GatewayError, type GatewayTransport } from './transport';

/**
 * A scripted transport for tests: the test pushes status and events, answers
 * calls, and can see what was asked and how many streams are open.
 */
export function fakeTransport(initial: EngineStatus = { state: 'starting', epoch: 1 }) {
  let status = initial;
  const subs = new Set<(m: GatewayMessage) => void>();
  const calls: { operation: string; params?: Record<string, unknown>; epoch?: number }[] = [];
  const jobs = new Map<string, EngineJob>();
  let subscribeFails = 0;
  let restarts = 0;
  const t: GatewayTransport & {
    push(m: GatewayMessage): void;
    setStatus(s: EngineStatus): void;
    event(e: Omit<EngineEvent, 'epoch'> & { epoch?: number }): void;
    calls: typeof calls;
    jobs: typeof jobs;
    openSubs(): number;
    failNextSubscribes(n: number): void;
    restarts(): number;
  } = {
    kind: 'mock',
    async status() { return status; },
    async restart() { restarts++; },
    async call<T>(operation: string, params?: Record<string, unknown>, opts?: { epoch?: number }) {
      calls.push({ operation, params, epoch: opts?.epoch });
      if (status.state !== 'ready') throw new GatewayError({ code: 'engine_unavailable', message: 'not ready' });
      if (opts?.epoch !== undefined && opts.epoch !== status.epoch) throw new GatewayError({ code: 'stale_epoch', message: 'old engine' });
      const j = jobs.get(String(params?.job_id));
      if (operation === 'get_job' || operation === 'cancel_job') {
        if (!j) throw new GatewayError({ code: 'not_found', message: 'No job.' });
        return { ...j } as T;
      }
      return undefined as T;
    },
    async subscribe(on) {
      if (subscribeFails > 0) { subscribeFails--; throw new GatewayError({ code: 'gateway_error', message: 'no channel' }); }
      subs.add(on);
      return () => { subs.delete(on); };
    },
    push(m) { subs.forEach((s) => s(m)); },
    setStatus(s) { status = s; subs.forEach((x) => x({ kind: 'status', status: s })); },
    event(e) { const full = { epoch: status.epoch, ...e } as EngineEvent; subs.forEach((x) => x({ kind: 'event', event: full })); },
    calls,
    jobs,
    openSubs: () => subs.size,
    failNextSubscribes(n) { subscribeFails = n; },
    restarts: () => restarts,
  };
  return t;
}

/** Let pending promise callbacks run. */
export const flush = () => new Promise<void>((r) => setTimeout(r, 0));
