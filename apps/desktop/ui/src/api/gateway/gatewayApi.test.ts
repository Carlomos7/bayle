import { describe, expect, it } from 'vitest';
import { createGateway } from './hub';
import { createGatewayApi, toActivityEntry, toBackendEvents } from './gatewayApi';
import { fakeTransport, flush } from './fakeTransport.test-util';

describe('production adapter', () => {
  it('refuses methods that are not wired yet instead of inventing data', async () => {
    const api = createGatewayApi(createGateway(fakeTransport({ state: 'ready', epoch: 1 })));
    await expect(api.getGames()).rejects.toMatchObject({ code: 'not_wired' });
    await expect(api.rebuildMerged('p1')).rejects.toMatchObject({ code: 'not_wired' });
  });

  it('reads Activity through the gateway by operation id, never by URL', async () => {
    const t = fakeTransport({ state: 'ready', epoch: 1 });
    const g = createGateway(t);
    g.on(() => {});
    await flush(); await flush();
    const call = t.call.bind(t);
    t.call = (async (op: string, params?: Record<string, unknown>, o?: { epoch?: number }) => {
      if (op === 'activity') return { jobs: [{ id: 'a1', title: 'Rebuilt merged game data', kind: 'rebuild', start: new Date().toISOString(), seconds: 38, outcome: 'done', summary: '9 clashes, all settled', log: 'a1.log' }], unseen: 0 };
      return call(op, params, o);
    }) as typeof t.call;
    const list = await createGatewayApi(g).listActivity();
    expect(list[0]).toMatchObject({ id: 'a1', kind: 'rebuild', ok: true, day: 'Today', duration: '38 s', hasLog: true, detail: '9 clashes, all settled' });
  });

  it('maps engine activity records defensively (the engine types them as loose dicts today)', () => {
    const now = new Date('2026-10-27T15:00:00');
    expect(toActivityEntry({ id: 'x', outcome: 'failed', problem: 'The file is in use.', start: '2026-10-26T09:00:00', seconds: 0.2 }, now))
      .toMatchObject({ ok: false, detail: 'The file is in use.', day: 'Yesterday', duration: 'under a second', kind: 'profile', title: 'Job' });
    expect(toActivityEntry({ id: 'y', undo: { type: 'rebuild' } }, now)).toMatchObject({ undoable: true, hasLog: false });
    expect(toActivityEntry({ id: 'z', undo: { type: 'rebuild' }, undone: true }, now)).toMatchObject({ undoable: false, undone: true });
  });

  it("turns engine pushes into the UI's events", () => {
    expect(toBackendEvents({ epoch: 1, seq: 1, job_id: null, type: 'invalidated', data: { what: ['pages'] } }).map((e) => e.type === 'changed' && e.scope)).toEqual(['profiles', 'saves', 'configs', 'activity']);
    expect(toBackendEvents({ epoch: 1, seq: 2, job_id: null, type: 'notice', data: { text: 'Steam is not signed in.', error: false } })).toEqual([{ type: 'notice', text: 'Steam is not signed in.', error: false }]);
    expect(toBackendEvents({ epoch: 1, seq: 3, job_id: 'j1', type: 'finished', data: {} })).toEqual([{ type: 'changed', scope: 'activity' }]);
    expect(toBackendEvents({ epoch: 1, seq: 4, job_id: 'j1', type: 'progress', data: { label: 'x' } })).toEqual([]);
  });

  it('opens links through the app (Rust), and refuses without it', async () => {
    const openUrl = async (_url: string) => {};
    const calls: string[] = [];
    const t = Object.assign(fakeTransport({ state: 'ready', epoch: 1 }), {
      app: { checkUpdate: async () => null, installUpdate: openUrl, openLogs: openUrl as () => Promise<void>, reportIssue: openUrl as () => Promise<void>, openUrl: async (u: string) => { calls.push(u); } },
    });
    await createGatewayApi(createGateway(t)).openUrl('https://example.com');
    expect(calls).toEqual(['https://example.com']);
    await expect(createGatewayApi(createGateway(fakeTransport({ state: 'ready', epoch: 1 }))).openUrl('https://example.com')).rejects.toMatchObject({ code: 'not_wired' });
  });
});
