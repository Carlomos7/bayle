/**
 * Job tracking as pure functions over plain state, so the rules that keep it
 * correct can be tested on their own (jobState.test.ts):
 *
 * - Events from an older engine epoch are ignored; a newer epoch first marks
 *   the old epoch's running jobs as lost (never resumed or guessed).
 * - Within an epoch, an event whose seq is not above the last one applied is
 *   a duplicate or out of order, and is ignored.
 * - A job's first terminal event wins; nothing after it changes the job.
 * - Snapshots (GET job after a resync or a gap) only move a job forward.
 * - "Stop" is a request until the engine says cancelled: cancelRequested is
 *   the UI's own flag, the phase changes only on the terminal event.
 */
import type { EngineEvent, EngineJob, EngineProgress, EngineStatus, JobRef, Problem } from '@/api/gateway/protocol';

export type JobPhase = 'running' | 'done' | 'failed' | 'cancelled' | 'lost';

export interface JobView extends JobRef {
  title: string;
  phase: JobPhase;
  /** The engine words the ending itself (StartedData.quiet): don't announce it. */
  quiet: boolean;
  progress?: EngineProgress;
  /** The newest progress label or log line, for one line of status. */
  message?: string;
  error?: Problem;
  result?: unknown;
  undo?: Record<string, unknown> | null;
  /** The player pressed Stop and the engine has not ended the job yet. */
  cancelRequested: boolean;
  /** A question the job is waiting on (prompt event), until it moves on. */
  prompt?: Record<string, unknown>;
}

export interface JobsState {
  /** The engine epoch the state follows. */
  epoch: number;
  /** The last event seq applied in that epoch. */
  seq: number;
  jobs: Record<string, JobView>;
  /** Running jobs whose state must be fetched again (after a resync, or events for a job we never saw start). */
  refetch: string[];
}

export const EMPTY: JobsState = { epoch: 0, seq: 0, jobs: {}, refetch: [] };
export const keyOf = (r: JobRef) => `${r.epoch}:${r.id}`;
const KEEP_FINISHED = 50;

export const LOST: Problem = {
  code: 'engine_restarted',
  message: "Bayle's engine stopped while this was running, so how it ended is unknown. Check Activity before trying again.",
};

const isRunning = (j: JobView) => j.phase === 'running';

/** Move to a newer epoch: the old epoch's running jobs are lost, not resumed. */
function enterEpoch(s: JobsState, epoch: number): JobsState {
  const jobs: Record<string, JobView> = {};
  for (const [k, j] of Object.entries(s.jobs)) jobs[k] = isRunning(j) && j.epoch < epoch ? { ...j, phase: 'lost', error: LOST, cancelRequested: false, prompt: undefined } : j;
  return { epoch, seq: 0, jobs, refetch: [] };
}

/** The engine's process is gone for good (failed, incompatible): its running jobs are lost too. */
function loseRunning(s: JobsState): JobsState {
  let changed = false;
  const jobs = { ...s.jobs };
  for (const [k, j] of Object.entries(jobs)) if (isRunning(j) && j.epoch === s.epoch) { jobs[k] = { ...j, phase: 'lost', error: LOST, cancelRequested: false, prompt: undefined }; changed = true; }
  return changed ? { ...s, jobs, refetch: [] } : s;
}

export function applyStatus(s: JobsState, status: EngineStatus): JobsState {
  if (status.epoch < s.epoch) return s;
  let next = status.epoch > s.epoch ? enterEpoch(s, status.epoch) : s;
  if (status.state === 'failed' || status.state === 'incompatible') next = loseRunning(next);
  return next;
}

function prune(jobs: Record<string, JobView>): Record<string, JobView> {
  const over = Object.values(jobs).filter((j) => !isRunning(j));
  if (over.length <= KEEP_FINISHED) return jobs;
  const drop = new Set(over.slice(0, over.length - KEEP_FINISHED).map(keyOf));
  return Object.fromEntries(Object.entries(jobs).filter(([k]) => !drop.has(k)));
}

export function applyEvent(s: JobsState, e: EngineEvent): JobsState {
  if (e.epoch < s.epoch) return s; // an older engine's event
  if (e.epoch > s.epoch) s = enterEpoch(s, e.epoch);
  if (e.seq <= s.seq) return s; // duplicate (a replay) or out of order
  s = { ...s, seq: e.seq };

  if (e.type === 'resync') {
    // Events were lost: every running job in this epoch must be read again.
    return { ...s, refetch: [...new Set([...s.refetch, ...Object.values(s.jobs).filter((j) => isRunning(j) && j.epoch === s.epoch).map(keyOf)])] };
  }
  if (!e.job_id) return s; // pushes (notice, invalidated, game.state…) don't change jobs

  const ref = { epoch: e.epoch, id: e.job_id };
  const key = keyOf(ref);
  const had = s.jobs[key];
  if (had && !isRunning(had)) return s; // first ending wins

  const job: JobView = had ?? { ...ref, title: '', phase: 'running', quiet: false, cancelRequested: false };
  // A job we never saw start (the stream opened mid-job): fetch it for its title and state.
  const refetch = !had && e.type !== 'started' ? [...new Set([...s.refetch, key])] : s.refetch;
  let next: JobView;
  switch (e.type) {
    case 'started': next = { ...job, title: e.data.title, quiet: !!e.data.quiet }; break;
    case 'progress': next = { ...job, progress: { done: e.data.done, total: e.data.total, label: e.data.label }, message: e.data.label || job.message }; break;
    case 'log': next = e.data.level === 'debug' ? job : { ...job, message: e.data.text }; break;
    case 'prompt': next = { ...job, prompt: e.data }; break;
    case 'finished': next = { ...job, phase: 'done', result: e.data.result, undo: e.data.undo ?? null, cancelRequested: false, prompt: undefined }; break;
    case 'failed': next = { ...job, phase: 'failed', error: e.data.error, cancelRequested: false, prompt: undefined }; break;
    case 'cancelled': next = { ...job, phase: 'cancelled', error: e.data.error, cancelRequested: false, prompt: undefined }; break;
    default: return s;
  }
  return { ...s, refetch, jobs: prune({ ...s.jobs, [key]: next }) };
}

/** A job read back from the engine (GET job). It can only move a job forward, never revive an ended one. */
export function applySnapshot(s: JobsState, epoch: number, job: EngineJob): JobsState {
  if (epoch !== s.epoch) return s;
  const ref = { epoch, id: job.id };
  const key = keyOf(ref);
  const had = s.jobs[key];
  const refetch = s.refetch.filter((k) => k !== key);
  if (had && !isRunning(had)) return { ...s, refetch };
  const base: JobView = had ?? { ...ref, title: job.title, phase: 'running', quiet: false, cancelRequested: false };
  const phase: JobPhase = job.state === 'running' ? 'running' : job.state;
  const next: JobView = {
    ...base,
    title: job.title || base.title,
    phase,
    progress: job.progress ?? base.progress,
    message: job.progress?.label || base.message,
    error: job.error ?? undefined,
    result: job.result,
    undo: job.undo ?? null,
    cancelRequested: phase === 'running' ? base.cancelRequested : false,
    prompt: phase === 'running' ? base.prompt : undefined,
  };
  return { ...s, refetch, jobs: prune({ ...s.jobs, [key]: next }) };
}

/** The player pressed Stop. Only the engine's cancelled event ends the job. */
export function markCancelRequested(s: JobsState, ref: JobRef, on: boolean): JobsState {
  const key = keyOf(ref);
  const j = s.jobs[key];
  if (!j || !isRunning(j) || j.cancelRequested === on) return s;
  return { ...s, jobs: { ...s.jobs, [key]: { ...j, cancelRequested: on } } };
}

/** Jobs the engine is still running, oldest first. */
export const runningJobs = (s: JobsState) => Object.values(s.jobs).filter(isRunning);
