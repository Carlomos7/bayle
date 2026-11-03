import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { onlineManager, QueryClient } from '@tanstack/react-query';
import { createGateway } from '@/api/gateway/hub';
import { fakeTransport, flush } from '@/api/gateway/fakeTransport.test-util';
import { awaitJob, cancelJob, connectEngine, resetEngineState, useEngine, useJobStore } from './engine';
import { keyOf } from './jobState';
import type { EngineStatus } from '@/api/gateway/protocol';

const settle = async () => { await flush(); await flush(); };

function setup(initial: EngineStatus = { state: 'ready', epoch: 1 }) {
  const t = fakeTransport(initial);
  const g = createGateway(t);
  const qc = new QueryClient();
  const invalidate = vi.spyOn(qc, 'invalidateQueries');
  const off = connectEngine(g, qc);
  return { t, g, qc, invalidate, off };
}
const job = (epoch: number, id: string) => useJobStore.getState().jobs[keyOf({ epoch, id })];

beforeEach(() => resetEngineState());
afterEach(() => resetEngineState());

describe('engine state', () => {
  it('follows status and pauses queries while the engine is away', async () => {
    const { t } = setup({ state: 'starting', epoch: 1 });
    await settle();
    expect(useEngine.getState().status.state).toBe('starting');
    expect(onlineManager.isOnline()).toBe(false);
    t.setStatus({ state: 'ready', epoch: 1 });
    expect(useEngine.getState()).toMatchObject({ status: { state: 'ready' }, everReady: true });
    expect(onlineManager.isOnline()).toBe(true);
    t.setStatus({ state: 'restarting', epoch: 1 });
    expect(onlineManager.isOnline()).toBe(false);
    expect(useEngine.getState().everReady).toBe(true);
  });

  it('re-reads everything when a new engine epoch becomes ready, not on the first start', async () => {
    const { t, invalidate } = setup({ state: 'starting', epoch: 1 });
    await settle();
    t.setStatus({ state: 'ready', epoch: 1 });
    expect(invalidate).not.toHaveBeenCalled();
    t.setStatus({ state: 'starting', epoch: 2 });
    t.setStatus({ state: 'ready', epoch: 2 });
    expect(invalidate).toHaveBeenCalledTimes(1);
  });

  it('closes its gateway stream on cleanup', async () => {
    const { t, off } = setup();
    await settle();
    expect(t.openSubs()).toBe(1);
    off();
    expect(t.openSubs()).toBe(0);
  });
});

describe('jobs through the gateway', () => {
  it('updates a job from its events and resolves awaitJob on finished', async () => {
    const { t } = setup();
    await settle();
    t.event({ seq: 1, type: 'started', job_id: 'j1', data: { title: 'Installing…' } });
    const done = awaitJob({ epoch: 1, id: 'j1' });
    t.event({ seq: 2, type: 'progress', job_id: 'j1', data: { done: 1, total: 2, label: 'Copying' } });
    expect(job(1, 'j1')).toMatchObject({ phase: 'running', message: 'Copying' });
    t.event({ seq: 3, type: 'finished', job_id: 'j1', data: { result: 'ok' } });
    await expect(done).resolves.toMatchObject({ phase: 'done', result: 'ok' });
  });

  it('shows Stop as requested until the engine confirms, then rejects awaitJob as cancelled', async () => {
    const { t } = setup();
    await settle();
    t.event({ seq: 1, type: 'started', job_id: 'j1', data: { title: 'Rebuilding…' } });
    t.jobs.set('j1', { id: 'j1', title: 'Rebuilding…', state: 'running' }); // cancel answers "still running": it was only asked
    const done = awaitJob({ epoch: 1, id: 'j1' });
    await cancelJob(createGatewayFor(t), { epoch: 1, id: 'j1' });
    expect(job(1, 'j1')).toMatchObject({ phase: 'running', cancelRequested: true });
    expect(t.calls.at(-1)).toMatchObject({ operation: 'cancel_job', params: { job_id: 'j1' }, epoch: 1 });
    t.event({ seq: 2, type: 'cancelled', job_id: 'j1', data: { error: { code: 'cancelled', message: 'Stopped.' } } });
    await expect(done).rejects.toMatchObject({ code: 'cancelled' });
    expect(job(1, 'j1')).toMatchObject({ phase: 'cancelled', cancelRequested: false });
  });

  it('marks running jobs lost when the engine restarts, and never sends an old cancel to the new engine', async () => {
    const { t, g } = setup();
    await settle();
    t.event({ seq: 1, type: 'started', job_id: 'j1', data: { title: 'Rebuilding…' } });
    const done = awaitJob({ epoch: 1, id: 'j1' });
    t.setStatus({ state: 'restarting', epoch: 1 });
    t.setStatus({ state: 'starting', epoch: 2 });
    await expect(done).rejects.toMatchObject({ code: 'engine_restarted' });
    t.setStatus({ state: 'ready', epoch: 2 });
    // The new engine has its own j1: a cancel for the old one must be refused, not applied to it.
    t.jobs.set('j1', { id: 'j1', title: 'Something else', state: 'running' });
    await cancelJob(g, { epoch: 1, id: 'j1' });
    expect(t.calls.at(-1)).toMatchObject({ operation: 'cancel_job', epoch: 1 });
    expect(t.jobs.get('j1')!.state).toBe('running');
    expect(job(1, 'j1')!.phase).toBe('lost');
  });

  it('reads running jobs back after a resync and applies what the engine says', async () => {
    const { t } = setup();
    await settle();
    t.event({ seq: 1, type: 'started', job_id: 'j1', data: { title: 'Restoring…' } });
    t.jobs.set('j1', { id: 'j1', title: 'Restoring…', state: 'done', result: 'restored' });
    t.event({ seq: 20, type: 'resync', job_id: null, data: { requested: 1, oldest: 21, seq: 60 } });
    await settle();
    expect(t.calls).toContainEqual({ operation: 'get_job', params: { job_id: 'j1' }, epoch: 1 });
    expect(job(1, 'j1')).toMatchObject({ phase: 'done', result: 'restored' });
    expect(useJobStore.getState().refetch).toEqual([]);
  });

  it('loses a job the engine no longer knows when it is read back', async () => {
    const { t } = setup();
    await settle();
    t.event({ seq: 5, type: 'progress', job_id: 'j9', data: { label: 'midway' } }); // seen mid-way: read it back
    await settle();
    expect(job(1, 'j9')!.phase).toBe('lost');
  });
});

/** cancelJob takes a Gateway; for a transport already wired into setup(), a second hub over it is equivalent. */
function createGatewayFor(t: ReturnType<typeof fakeTransport>) {
  return createGateway(t);
}
