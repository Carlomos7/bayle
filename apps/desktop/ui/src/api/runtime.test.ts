import { describe, expect, it } from 'vitest';
import { selectMode } from './index';
import { guardApi } from './guard';
import { createGateway } from './gateway/hub';
import { fakeTransport, flush } from './gateway/fakeTransport.test-util';
import type { BayleApi } from './BayleApi';

describe('which backend the app uses', () => {
  it('always uses the real gateway inside the desktop app, whatever the build flags say', () => {
    expect(selectMode({ inTauri: true, dev: true, demoBuild: true })).toBe('desktop');
    expect(selectMode({ inTauri: true, dev: false, demoBuild: false })).toBe('desktop');
  });
  it('uses the mock only for development or a deliberate demo build', () => {
    expect(selectMode({ inTauri: false, dev: true, demoBuild: false })).toBe('preview');
    expect(selectMode({ inTauri: false, dev: false, demoBuild: true })).toBe('preview');
  });
  it('never falls back to the mock in a production build outside the desktop app', () => {
    expect(selectMode({ inTauri: false, dev: false, demoBuild: false })).toBe('outside-desktop');
  });
});

describe('calls while the engine is away', () => {
  it('fail at once with a sentence instead of reaching a half-started engine', async () => {
    const t = fakeTransport({ state: 'starting', epoch: 1 });
    const g = createGateway(t);
    g.on(() => {});
    await flush(); await flush();
    let reached = false;
    const api = guardApi({ listActivity: async () => { reached = true; return []; }, subscribe: () => () => {} } as unknown as BayleApi, g);
    await expect(api.listActivity()).rejects.toMatchObject({ code: 'engine_unavailable' });
    expect(reached).toBe(false);
    t.setStatus({ state: 'ready', epoch: 1 });
    await expect(api.listActivity()).resolves.toEqual([]);
    expect(typeof api.subscribe(() => {})).toBe('function'); // listening is always allowed
  });
});
