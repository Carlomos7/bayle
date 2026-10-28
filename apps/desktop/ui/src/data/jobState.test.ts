import { describe, expect, it } from 'vitest';
import type { EngineEvent, EngineStatus } from '@/api/gateway/protocol';
import { applyEvent, applySnapshot, applyStatus, EMPTY, keyOf, markCancelRequested, runningJobs, type JobsState } from './jobState';

const ev = (epoch: number, seq: number, type: EngineEvent['type'], job_id: string | null, data: Record<string, unknown> = {}) => ({ epoch, seq, type, job_id, data }) as EngineEvent;
const run = (s: JobsState, ...events: EngineEvent[]) => events.reduce(applyEvent, s);
const ready = (epoch: number): EngineStatus => ({ state: 'ready', epoch });
const job = (s: JobsState, epoch: number, id: string) => s.jobs[keyOf({ epoch, id })];

describe('job events', () => {
  it('follows a job from started through progress to finished', () => {
    const s = run(applyStatus(EMPTY, ready(1)),
      ev(1, 1, 'started', 'j1', { title: 'Rebuilding…' }),
      ev(1, 2, 'progress', 'j1', { done: 1, total: 4, label: 'Merging params' }),
      ev(1, 3, 'finished', 'j1', { result: { ok: true } }));
    const j = job(s, 1, 'j1')!;
    expect(j.phase).toBe('done');
    expect(j.title).toBe('Rebuilding…');
    expect(j.progress).toMatchObject({ done: 1, total: 4 });
    expect(j.result).toEqual({ ok: true });
    expect(runningJobs(s)).toHaveLength(0);
  });

  it('ignores a duplicate event (same seq replayed)', () => {
    const once = run(EMPTY, ev(1, 1, 'started', 'j1', { title: 'A' }), ev(1, 2, 'progress', 'j1', { label: 'first' }));
    const twice = applyEvent(once, ev(1, 2, 'progress', 'j1', { label: 'replayed' }));
    expect(twice).toBe(once);
    expect(job(twice, 1, 'j1')!.message).toBe('first');
  });

  it('ignores an event older than one already applied (out of order)', () => {
    const s = run(EMPTY, ev(1, 1, 'started', 'j1', { title: 'A' }), ev(1, 3, 'progress', 'j1', { label: 'newer' }), ev(1, 2, 'progress', 'j1', { label: 'older' }));
    expect(job(s, 1, 'j1')!.message).toBe('newer');
  });

  it('lets the first ending win: nothing after it changes the job', () => {
    const s = run(EMPTY,
      ev(1, 1, 'started', 'j1', { title: 'A' }),
      ev(1, 2, 'failed', 'j1', { error: { code: 'busy', message: 'Another operation is running.' } }),
      ev(1, 3, 'progress', 'j1', { label: 'late' }),
      ev(1, 4, 'finished', 'j1', {}));
    const j = job(s, 1, 'j1')!;
    expect(j.phase).toBe('failed');
    expect(j.error?.code).toBe('busy');
    expect(j.message).toBeUndefined();
  });

  it('ignores events from an older engine epoch', () => {
    const s = run(applyStatus(EMPTY, ready(2)), ev(2, 1, 'started', 'j1', { title: 'New' }));
    const after = applyEvent(s, ev(1, 99, 'finished', 'j1', {}));
    expect(after).toBe(s);
    expect(job(after, 2, 'j1')!.phase).toBe('running');
  });

  it('treats the same job id in two epochs as two jobs, and loses the old one', () => {
    let s = run(EMPTY, ev(1, 1, 'started', 'j1', { title: 'Old engine job' }));
    s = applyStatus(s, ready(2)); // the engine restarted: ids and seq start over
    s = run(s, ev(2, 1, 'started', 'j1', { title: 'New engine job' }));
    expect(job(s, 1, 'j1')!.phase).toBe('lost');
    expect(job(s, 1, 'j1')!.error?.code).toBe('engine_restarted');
    expect(job(s, 2, 'j1')).toMatchObject({ phase: 'running', title: 'New engine job' });
  });

  it('accepts seq 1 again after a new epoch (seq restarts with the engine)', () => {
    let s = run(EMPTY, ev(1, 1, 'started', 'j1', { title: 'A' }), ev(1, 50, 'finished', 'j1', {}));
    s = run(s, ev(2, 1, 'started', 'j1', { title: 'B' }));
    expect(s.epoch).toBe(2);
    expect(s.seq).toBe(1);
    expect(job(s, 2, 'j1')!.title).toBe('B');
  });

  it('loses running jobs when the engine fails for good, but not when it is briefly unavailable', () => {
    const s = run(EMPTY, ev(1, 1, 'started', 'j1', { title: 'A' }));
    expect(job(applyStatus(s, { state: 'unavailable', epoch: 1 }), 1, 'j1')!.phase).toBe('running');
    expect(job(applyStatus(s, { state: 'failed', epoch: 1 }), 1, 'j1')!.phase).toBe('lost');
  });

  it('never resumes a lost job, even if its old events turn up', () => {
    let s = run(EMPTY, ev(1, 1, 'started', 'j1', { title: 'A' }));
    s = applyStatus(s, ready(2));
    s = applyEvent(s, ev(1, 2, 'finished', 'j1', {}));
    expect(job(s, 1, 'j1')!.phase).toBe('lost');
  });

  it('keeps quiet jobs (the engine words their ending) marked as quiet', () => {
    expect(job(run(EMPTY, ev(1, 1, 'started', 'j1', { title: 'Launch', quiet: true })), 1, 'j1')!.quiet).toBe(true);
  });
});

describe('cancel', () => {
  it('is a request until the engine sends cancelled', () => {
    let s = run(EMPTY, ev(1, 1, 'started', 'j1', { title: 'A' }));
    s = markCancelRequested(s, { epoch: 1, id: 'j1' }, true);
    expect(job(s, 1, 'j1')).toMatchObject({ phase: 'running', cancelRequested: true });
    s = run(s, ev(1, 2, 'progress', 'j1', { label: 'still going' }));
    expect(job(s, 1, 'j1')).toMatchObject({ phase: 'running', cancelRequested: true });
    s = run(s, ev(1, 3, 'cancelled', 'j1', { error: { code: 'cancelled', message: 'Stopped.' } }));
    expect(job(s, 1, 'j1')).toMatchObject({ phase: 'cancelled', cancelRequested: false });
  });

  it('can end some other way after Stop (the work finished first)', () => {
    let s = run(EMPTY, ev(1, 1, 'started', 'j1', { title: 'A' }));
    s = markCancelRequested(s, { epoch: 1, id: 'j1' }, true);
    s = run(s, ev(1, 2, 'finished', 'j1', {}));
    expect(job(s, 1, 'j1')).toMatchObject({ phase: 'done', cancelRequested: false });
  });

  it('does nothing for a job that already ended', () => {
    const s = run(EMPTY, ev(1, 1, 'started', 'j1', { title: 'A' }), ev(1, 2, 'finished', 'j1', {}));
    expect(markCancelRequested(s, { epoch: 1, id: 'j1' }, true)).toBe(s);
  });
});

describe('recovery', () => {
  it('asks to refetch running jobs after a resync', () => {
    const s = run(EMPTY,
      ev(1, 1, 'started', 'j1', { title: 'A' }),
      ev(1, 2, 'started', 'j2', { title: 'B' }),
      ev(1, 3, 'finished', 'j2', {}),
      ev(1, 10, 'resync', null, { requested: 3, oldest: 11, seq: 40 }));
    expect(s.refetch).toEqual(['1:j1']);
  });

  it('asks to refetch a job first seen mid-way (the stream opened after it started)', () => {
    const s = run(EMPTY, ev(1, 7, 'progress', 'j4', { label: 'halfway' }));
    expect(job(s, 1, 'j4')!.phase).toBe('running');
    expect(s.refetch).toEqual(['1:j4']);
  });

  it('moves a job forward from a snapshot and clears its refetch', () => {
    let s = run(EMPTY, ev(1, 1, 'started', 'j1', { title: 'A' }), ev(1, 10, 'resync', null, { requested: 1, oldest: 11, seq: 20 }));
    s = applySnapshot(s, 1, { id: 'j1', title: 'A', state: 'done', result: 3 });
    expect(job(s, 1, 'j1')).toMatchObject({ phase: 'done', result: 3 });
    expect(s.refetch).toEqual([]);
  });

  it('never revives an ended job from a snapshot', () => {
    const s = run(EMPTY, ev(1, 1, 'started', 'j1', { title: 'A' }), ev(1, 2, 'cancelled', 'j1', { error: { code: 'cancelled', message: 'Stopped.' } }));
    expect(job(applySnapshot(s, 1, { id: 'j1', title: 'A', state: 'running' }), 1, 'j1')!.phase).toBe('cancelled');
  });

  it('ignores a snapshot from another epoch', () => {
    const s = applyStatus(EMPTY, ready(3));
    expect(applySnapshot(s, 2, { id: 'j1', title: 'A', state: 'running' })).toBe(s);
  });
});
