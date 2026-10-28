/**
 * The engine as the UI sees it: its lifecycle state and the jobs it runs.
 * Fed by the gateway hub (one stream for the app), read with hooks. Nothing
 * here touches Tauri or the engine directly.
 */
import { onlineManager, type QueryClient } from '@tanstack/react-query';
import { create } from 'zustand';
import { useShallow } from 'zustand/react/shallow';
import type { Gateway } from '@/api/gateway/hub';
import { OPERATIONS, type EngineJob, type EngineStatus, type JobRef } from '@/api/gateway/protocol';
import { GatewayError, isGatewayError } from '@/api/gateway/transport';
import { applyEvent, applySnapshot, applyStatus, EMPTY, keyOf, LOST, markCancelRequested, runningJobs, type JobsState, type JobView } from './jobState';

/* ------------------------------------------------------------------ stores */

/** everReady: the engine has been ready at least once this session (so a later outage is a banner, not a start screen). */
export const useEngine = create<{ status: EngineStatus; everReady: boolean; readyEpoch: number }>(() => ({ status: { state: 'starting', epoch: 0 }, everReady: false, readyEpoch: 0 }));
export const useJobStore = create<JobsState>(() => EMPTY);

export const useEngineStatus = () => useEngine((s) => s.status);
export const useEngineReady = () => useEngine((s) => s.status.state === 'ready');
export const useJob = (ref: JobRef | undefined) => useJobStore((s) => (ref ? s.jobs[keyOf(ref)] : undefined));
/** Jobs still running that the UI should show (quiet ones word their own ending), oldest first. */
export const useActiveJobs = () => useJobStore(useShallow((s) => runningJobs(s).filter((j) => !j.quiet)));

/* ------------------------------------------------------------------ wiring */

// Queries pause while the engine is not ready and resume when it is; the browser's own online events don't apply.
onlineManager.setEventListener(() => () => {});

const fetching = new Set<string>();

/** Read back the jobs the tracker asked for (after a resync, or a job seen mid-way). One request per job at a time. */
function refetchJobs(gateway: Gateway) {
  const { refetch, epoch } = useJobStore.getState();
  for (const key of refetch) {
    if (fetching.has(key)) continue;
    const id = key.slice(key.indexOf(':') + 1);
    fetching.add(key);
    gateway.call<EngineJob>(OPERATIONS.getJob, { job_id: id }, { epoch })
      .then((job) => useJobStore.setState((s) => applySnapshot(s, epoch, job)))
      .catch((e) => {
        // The engine no longer knows it (or is another process now): its ending can't be known.
        if (isGatewayError(e, 'not_found') || isGatewayError(e, 'stale_epoch')) loseJob({ epoch, id });
      })
      .finally(() => fetching.delete(key));
  }
}

function loseJob(ref: JobRef) {
  useJobStore.setState((s) => {
    const j = s.jobs[keyOf(ref)];
    if (!j || j.phase !== 'running') return s;
    return { ...s, refetch: s.refetch.filter((k) => k !== keyOf(ref)), jobs: { ...s.jobs, [keyOf(ref)]: { ...j, phase: 'lost', error: LOST, cancelRequested: false } } };
  });
}

/**
 * Follow the gateway: engine status, job events, query pausing, and a full
 * re-read when a new engine epoch becomes ready. Returns the cleanup.
 */
export function connectEngine(gateway: Gateway, qc: QueryClient): () => void {
  return gateway.on((m) => {
    if (m.kind === 'status') {
      const { status: prev, readyEpoch } = useEngine.getState();
      if (m.status.epoch < prev.epoch) return;
      const ready = m.status.state === 'ready';
      useEngine.setState((s) => ({ status: m.status, everReady: s.everReady || ready, readyEpoch: ready ? m.status.epoch : s.readyEpoch }));
      useJobStore.setState((s) => applyStatus(s, m.status));
      onlineManager.setOnline(ready);
      // Ready with a different engine process than the last ready one: whatever the UI read may be out of date.
      if (ready && readyEpoch > 0 && m.status.epoch !== readyEpoch) void qc.invalidateQueries();
    } else {
      useJobStore.setState((s) => applyEvent(s, m.event));
    }
    if (useJobStore.getState().refetch.length) refetchJobs(gateway);
  });
}

/* ------------------------------------------------------------------ actions */

/**
 * Ask the engine to stop a job. The job shows "Stopping…" until the engine's
 * cancelled (or finished/failed) event arrives; the answer to this call is
 * only "asked".
 */
export async function cancelJob(gateway: Gateway, ref: JobRef): Promise<void> {
  useJobStore.setState((s) => markCancelRequested(s, ref, true));
  try {
    const job = await gateway.call<EngineJob>(OPERATIONS.cancelJob, { job_id: ref.id }, { epoch: ref.epoch });
    useJobStore.setState((s) => applySnapshot(s, ref.epoch, job));
  } catch (e) {
    if (isGatewayError(e, 'stale_epoch') || isGatewayError(e, 'not_found')) { loseJob(ref); return; }
    useJobStore.setState((s) => markCancelRequested(s, ref, false));
    throw e;
  }
}

/**
 * Wait for a job to end. Resolves with the finished job; rejects with a
 * GatewayError for failed (the engine's code), cancelled ('cancelled') and
 * lost ('engine_restarted'). Pass a signal to stop waiting (it doesn't stop the job).
 */
export function awaitJob(ref: JobRef, signal?: AbortSignal): Promise<JobView> {
  return new Promise((resolve, reject) => {
    const settle = (j: JobView | undefined) => {
      if (!j || j.phase === 'running') return false;
      if (j.phase === 'done') resolve(j);
      else reject(new GatewayError(j.error ?? { code: j.phase, message: j.phase === 'cancelled' ? 'Stopped.' : 'It did not finish.' }));
      return true;
    };
    if (settle(useJobStore.getState().jobs[keyOf(ref)])) return;
    const off = useJobStore.subscribe((s) => { if (settle(s.jobs[keyOf(ref)])) { off(); signal?.removeEventListener('abort', abort); } });
    const abort = () => { off(); reject(new GatewayError({ code: 'aborted', message: 'Stopped waiting.' })); };
    signal?.addEventListener('abort', abort, { once: true });
  });
}

/** For tests: back to a fresh state. */
export function resetEngineState() {
  useEngine.setState({ status: { state: 'starting', epoch: 0 }, everReady: false, readyEpoch: 0 });
  useJobStore.setState(EMPTY);
  fetching.clear();
  onlineManager.setOnline(true);
}
