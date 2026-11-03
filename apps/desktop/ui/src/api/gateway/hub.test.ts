import { afterEach, describe, expect, it, vi } from 'vitest';
import { createGateway } from './hub';
import { fakeTransport, flush } from './fakeTransport.test-util';
import type { GatewayMessage } from './protocol';

afterEach(() => { vi.useRealTimers(); });

describe('gateway hub', () => {
  it('opens one stream however many parts of the UI listen, and closes it with the last', async () => {
    const t = fakeTransport();
    const g = createGateway(t);
    const a = g.on(() => {});
    const b = g.on(() => {});
    await flush();
    expect(t.openSubs()).toBe(1);
    a();
    expect(t.openSubs()).toBe(1);
    b();
    expect(t.openSubs()).toBe(0);
  });

  it('survives React StrictMode (listen, stop, listen again at once) with exactly one live stream', async () => {
    const t = fakeTransport();
    const g = createGateway(t);
    const got: GatewayMessage[] = [];
    g.on(() => {})(); // the first effect run, cleaned up before its subscribe resolved
    const off = g.on((m) => got.push(m));
    await flush();
    expect(t.openSubs()).toBe(1);
    t.setStatus({ state: 'ready', epoch: 1 });
    expect(got.at(-1)).toEqual({ kind: 'status', status: { state: 'ready', epoch: 1 } });
    off();
    expect(t.openSubs()).toBe(0);
  });

  it('asks for the current status once the stream is open', async () => {
    const t = fakeTransport({ state: 'ready', epoch: 3 });
    const g = createGateway(t);
    const got: GatewayMessage[] = [];
    g.on((m) => got.push(m));
    await flush(); await flush();
    expect(got).toContainEqual({ kind: 'status', status: { state: 'ready', epoch: 3 } });
    expect(g.current()?.epoch).toBe(3);
  });

  it('drops a status from an older epoch', async () => {
    const t = fakeTransport({ state: 'ready', epoch: 2 });
    const g = createGateway(t);
    g.on(() => {});
    await flush(); await flush();
    t.push({ kind: 'status', status: { state: 'starting', epoch: 1 } });
    expect(g.current()).toEqual({ state: 'ready', epoch: 2 });
  });

  it('reports unavailable and retries when the stream cannot be opened', async () => {
    vi.useFakeTimers();
    const t = fakeTransport({ state: 'ready', epoch: 1 });
    t.failNextSubscribes(1);
    const g = createGateway(t);
    const got: GatewayMessage[] = [];
    g.on((m) => got.push(m));
    await vi.advanceTimersByTimeAsync(0);
    expect(got[0]).toMatchObject({ kind: 'status', status: { state: 'unavailable' } });
    expect(t.openSubs()).toBe(0);
    await vi.advanceTimersByTimeAsync(600);
    expect(t.openSubs()).toBe(1);
    expect(g.current()?.state).toBe('ready');
  });

  it("pins a call to the current engine when asked ('current')", async () => {
    const t = fakeTransport({ state: 'ready', epoch: 4 });
    const g = createGateway(t);
    g.on(() => {});
    await flush(); await flush();
    await g.call('health', {}, { epoch: 'current' });
    expect(t.calls.at(-1)).toMatchObject({ operation: 'health', epoch: 4 });
  });
});
