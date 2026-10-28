/**
 * An in-memory engine for development and the browser preview. It behaves
 * like Rust + the Python engine as far as the UI can tell: it boots, has an
 * epoch, numbers its events, runs jobs with progress, honours cancel
 * cooperatively (cancel is a request; the ending comes later), and can crash,
 * fail or be incompatible on demand.
 *
 * Its timers stand in for the engine's real work; the UI never waits on a
 * timer of its own. Never used inside the desktop app (see ../index.ts).
 *
 * Scenarios for the preview, as a query parameter before the #:
 *   ?engine=slow           a 4 s start
 *   ?engine=fail           the first start fails (Retry then works)
 *   ?engine=incompatible   a contract this app doesn't speak
 * Controls in development: window.__bayleEngine.crash() / fail() / incompatible() / restart().
 */
import { OPERATIONS, type EngineEvent, type EngineJob, type EngineStatus, type GatewayMessage, type JobRef } from './protocol';
import { GatewayError, type GatewayTransport } from './transport';

export type MockScenario = 'normal' | 'slow' | 'fail' | 'incompatible';

export interface MockJobOptions {
  /** How long the work takes. */
  ms?: number;
  /** Progress labels, spread over the duration. */
  steps?: string[];
  /** What it ends with. */
  result?: unknown;
  /** End as failed with this sentence instead. */
  failWith?: string;
}

export interface MockEngine extends GatewayTransport {
  /** Start a job the way the engine would; `done` settles on its ending (rejects on failed/cancelled/lost). */
  runJob(title: string, opts?: MockJobOptions): { ref: JobRef; done: Promise<unknown> };
  controls: {
    /** The engine process dies: running jobs end without a word, Rust restarts it (new epoch). */
    crash(): void;
    /** Rust gives up: failed, until Retry. */
    fail(message?: string): void;
    incompatible(): void;
    /** Send one event twice and one out of order, as a flaky stream might. */
    stutter(): void;
  };
}

interface MockJob { snap: EngineJob; cancel: boolean; timer?: ReturnType<typeof setTimeout>; settle?: { resolve: (v: unknown) => void; reject: (e: unknown) => void } }

const CONTRACT = '1';

export function createMockEngine(opts: { scenario?: MockScenario; bootMs?: number } = {}): MockEngine {
  let scenario = opts.scenario ?? 'normal';
  const bootMs = opts.bootMs ?? (scenario === 'slow' ? 4000 : 350);
  const subs = new Set<(m: GatewayMessage) => void>();
  let status: EngineStatus = { state: 'starting', epoch: 1, protocol: 1 };
  let seq = 0;
  let count = 0;
  let jobs = new Map<string, MockJob>();
  let bootTimer: ReturnType<typeof setTimeout> | undefined;
  const sent: EngineEvent[] = [];

  // Async like real IPC: a message never arrives inside the call that caused it.
  const send = (m: GatewayMessage) => setTimeout(() => subs.forEach((s) => s(m)), 0);
  const setStatus = (s: EngineStatus) => { status = s; send({ kind: 'status', status: s }); };
  const emit = (e: Omit<EngineEvent, 'seq' | 'epoch'>) => {
    const ev = { ...e, seq: ++seq, epoch: status.epoch } as EngineEvent;
    sent.push(ev);
    if (sent.length > 50) sent.shift();
    send({ kind: 'event', event: ev });
  };

  const boot = () => {
    if (bootTimer) clearTimeout(bootTimer);
    bootTimer = setTimeout(() => {
      if (scenario === 'fail') { setStatus({ ...status, state: 'failed', problem: { code: 'engine_exited', message: "Bayle's engine stopped while starting (exit code 1). Its log has the details." } }); scenario = 'normal'; return; }
      if (scenario === 'incompatible') { setStatus({ ...status, state: 'incompatible', engineVersion: '6.0.0', contract: '2', expectedContract: CONTRACT, problem: { code: 'incompatible', message: "This engine speaks contract 2; this app speaks contract 1." } }); return; }
      setStatus({ state: 'ready', epoch: status.epoch, protocol: 1, engineVersion: '5.0.0', contract: CONTRACT });
    }, bootMs);
  };

  const newProcess = () => {
    // A new engine: ids and sequence numbers start over, which is exactly why the epoch exists.
    jobs.forEach((j) => { if (j.timer) clearTimeout(j.timer); j.settle?.reject(new GatewayError({ code: 'engine_restarted', message: "Bayle's engine stopped while this was running." })); });
    jobs = new Map();
    seq = 0;
    count = 0;
    setStatus({ state: 'starting', epoch: status.epoch + 1, protocol: 1 });
    boot();
  };

  const notReady = () => new GatewayError({ code: 'engine_unavailable', message: status.state === 'starting' || status.state === 'restarting' ? "Bayle's engine is starting. Try again in a moment." : "Bayle's engine isn't running." });

  const engine: MockEngine = {
    kind: 'mock',
    async status() { return status; },
    async restart() {
      if (status.state === 'starting' || status.state === 'restarting') return;
      if (status.state === 'incompatible') scenario = 'normal';
      newProcess();
    },
    async call<T>(operation: string, params: Record<string, unknown> = {}, o?: { epoch?: number }): Promise<T> {
      if (status.state !== 'ready') throw notReady();
      if (o?.epoch !== undefined && o.epoch !== status.epoch) throw new GatewayError({ code: 'stale_epoch', message: 'That was for an engine that has since restarted.' });
      const job = jobs.get(String(params.job_id));
      switch (operation) {
        case OPERATIONS.health: return { app_version: status.engineVersion, contract_version: CONTRACT, ready: true } as T;
        case OPERATIONS.getJob:
          if (!job) throw new GatewayError({ code: 'not_found', message: `No job ${String(params.job_id)}.` });
          return { ...job.snap } as T;
        case OPERATIONS.cancelJob:
          if (!job) throw new GatewayError({ code: 'not_found', message: `No job ${String(params.job_id)}.` });
          if (job.snap.state === 'running') job.cancel = true; // cooperative: it stops at its next step
          return { ...job.snap } as T;
        default:
          throw new GatewayError({ code: 'not_wired', message: `The development engine has no ${operation}.` });
      }
    },
    async subscribe(onMessage) {
      subs.add(onMessage);
      return () => { subs.delete(onMessage); };
    },
    // The preview has no updater, log folder or bug tracker of its own; links open in a new tab.
    app: {
      checkUpdate: async () => null,
      installUpdate: async () => { throw new GatewayError({ code: 'not_wired', message: 'The preview has no updates.' }); },
      openLogs: async () => {},
      reportIssue: async () => { window.open('https://github.com/Carlomos7/bayle/issues/new', '_blank', 'noopener'); },
      openUrl: async (url: string) => { window.open(url, '_blank', 'noopener'); },
      // A browser tab has no native dialogs, file manager, window or log folder to offer.
      pickFile: async () => null,
      pickFolder: async () => null,
      openPath: async () => {},
      windowAction: async () => {},
      saveSupportLogs: async () => null,
    },

    runJob(title, o = {}) {
      if (status.state !== 'ready') throw notReady();
      const id = `j${++count}`;
      const ref = { epoch: status.epoch, id };
      const steps = o.steps?.length ? o.steps : [title];
      const ms = o.ms ?? 1200;
      const job: MockJob = { snap: { id, title, state: 'running', progress: null }, cancel: false };
      jobs.set(id, job);
      const done = new Promise<unknown>((resolve, reject) => { job.settle = { resolve, reject }; });
      done.catch(() => {}); // callers that don't await it shouldn't see an unhandled rejection
      emit({ type: 'started', job_id: id, data: { title } });
      let i = 0;
      const tick = () => {
        if (job.cancel) {
          job.snap = { ...job.snap, state: 'cancelled', error: { code: 'cancelled', message: 'Stopped.' } };
          emit({ type: 'cancelled', job_id: id, data: { error: { code: 'cancelled', message: 'Stopped.' } } });
          job.settle?.reject(new GatewayError({ code: 'cancelled', message: `${title.replace(/…$/, '')} stopped.` }));
          return;
        }
        if (i < steps.length) {
          const progress = { done: i, total: steps.length, label: steps[i]! };
          job.snap = { ...job.snap, progress };
          emit({ type: 'progress', job_id: id, data: progress });
          i++;
          job.timer = setTimeout(tick, ms / steps.length);
          return;
        }
        if (o.failWith) {
          const error = { code: 'failed', message: o.failWith };
          job.snap = { ...job.snap, state: 'failed', error };
          emit({ type: 'failed', job_id: id, data: { error } });
          job.settle?.reject(new GatewayError(error));
          return;
        }
        job.snap = { ...job.snap, state: 'done', progress: { done: steps.length, total: steps.length, label: steps[steps.length - 1] }, result: o.result ?? null };
        emit({ type: 'finished', job_id: id, data: { result: o.result ?? null } });
        job.settle?.resolve(o.result);
      };
      job.timer = setTimeout(tick, 0);
      return { ref, done };
    },

    controls: {
      crash() {
        if (status.state !== 'ready') return;
        jobs.forEach((j) => { if (j.timer) clearTimeout(j.timer); }); // the process is gone: no endings are sent
        setStatus({ ...status, state: 'restarting', problem: { code: 'engine_exited', message: "Bayle's engine stopped unexpectedly. Starting it again…" } });
        setTimeout(newProcess, 300);
      },
      fail(message = "Bayle's engine stopped and could not be started again.") {
        if (bootTimer) clearTimeout(bootTimer);
        jobs.forEach((j) => { if (j.timer) clearTimeout(j.timer); });
        setStatus({ ...status, state: 'failed', problem: { code: 'engine_exited', message } });
      },
      incompatible() {
        scenario = 'incompatible';
        newProcess();
      },
      stutter() {
        const last = sent[sent.length - 1];
        const older = sent[sent.length - 2];
        if (last) send({ kind: 'event', event: last }); // a duplicate
        if (older) send({ kind: 'event', event: older }); // and one from before it
      },
    },
  };

  send({ kind: 'status', status });
  boot();
  return engine;
}

/** Read ?engine=… from the address (development preview only). */
export function scenarioFromLocation(): MockScenario {
  try {
    const v = new URLSearchParams(window.location.search).get('engine');
    return v === 'slow' || v === 'fail' || v === 'incompatible' ? v : 'normal';
  } catch {
    return 'normal';
  }
}
