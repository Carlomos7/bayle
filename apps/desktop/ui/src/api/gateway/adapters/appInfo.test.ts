import { afterEach, describe, expect, it } from 'vitest';
import { QueryClient } from '@tanstack/react-query';
import { connectEngine, resetEngineState } from '@/data/engine';
import { createGateway } from '../hub';
import { fakeTransport, flush } from '../fakeTransport.test-util';
import { createGatewayApi } from '../gatewayApi';
import type { GatewayTransport } from '../transport';

afterEach(() => resetEngineState());

function setup(app: GatewayTransport['app'], me3: string | null = '1.2.3') {
  const t = Object.assign(fakeTransport({ state: 'ready', epoch: 1 }), app ? { app } : {});
  const call = t.call.bind(t);
  t.call = (async (op: string, params?: Record<string, unknown>, o?: { epoch?: number }) => {
    if (op === 'settings_me3') return { version: me3 };
    if (op === 'health') return { app_version: '9.9.9' };
    return call(op, params, o);
  }) as typeof t.call;
  const g = createGateway(t);
  connectEngine(g, new QueryClient());
  return flush().then(() => createGatewayApi(g));
}

const shell = { version: '0.1.0', channel: 'beta', dataFolder: 'C:\\data', platform: 'windows' };
const desktop = (found: { version: string; current: string } | null): NonNullable<GatewayTransport['app']> => ({
  info: async () => shell, checkUpdate: async () => found, installUpdate: async () => {}, openLogs: async () => {}, reportIssue: async () => {}, openUrl: async () => {},
});

describe('app info and updates', () => {
  it('reads the build from Rust and me3 from the engine', async () => {
    const api = await setup(desktop(null));
    expect(await api.getAppInfo()).toEqual({ version: '0.1.0', me3Version: '1.2.3', platform: 'Windows', dataFolder: 'C:\\data' });
  });

  it('shows an empty me3 version when me3 is not found, and the engine version without Rust', async () => {
    const api = await setup(undefined, null);
    expect(await api.getAppInfo()).toEqual({ version: '9.9.9', me3Version: '', platform: 'Browser', dataFolder: '' });
  });

  it('names the engine and its contract once it is ready', async () => {
    const t = fakeTransport({ state: 'ready', epoch: 1, protocol: 1, engineVersion: '5.0.2', contract: '1' });
    t.call = (async () => ({ version: null, app_version: '5.0.2' })) as typeof t.call;
    const g = createGateway(t);
    connectEngine(g, new QueryClient());
    await flush(); await flush();
    expect((await createGatewayApi(g).getAppInfo()).engine).toBe('5.0.2, contract 1');
  });

  it('adds the update Rust found, with the channel', async () => {
    const api = await setup(desktop({ version: '0.2.0', current: '0.1.0' }));
    expect((await api.checkForUpdates()).update).toEqual({ version: '0.2.0', channel: 'beta' });
    const none = await setup(desktop(null));
    expect((await none.checkForUpdates()).update).toBeUndefined();
  });
});
