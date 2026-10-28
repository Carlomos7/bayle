import { describe, expect, it } from 'vitest';
import { createGateway } from '../hub';
import { createGatewayApi } from '../gatewayApi';
import { fakeTransport } from '../fakeTransport.test-util';
import { GatewayError } from '../transport';
import type { EngineConfigState } from './configs';

const ME3 = 'C:\\bayle\\profiles\\main.me3';
const INI = 'C:\\mods\\Cool\\cool.ini';
const DLL = 'C:\\mods\\Cool\\cool.dll';
const PAGE: EngineConfigState = {
  profile: ME3,
  nodes: [
    { key: 'native:cool', name: 'Cool', kind: 'native', enabled: true, loaded: true, target: DLL, files: [
      { path: INI, how: 'attached', exists: true, kind: 'form' },
      { path: 'C:\\mods\\Cool\\extra.ini', how: 'found', exists: true, kind: 'form' },
      { path: 'C:\\mods\\Cool\\gone.ini', how: 'attached', exists: false, kind: 'form' },
    ] },
    { key: 'seamless', name: 'ersc.dll', kind: 'seamless', enabled: true, loaded: true, target: null, files: [{ path: 'C:\\sc\\ersc_settings.ini', how: 'seamless', exists: true, kind: 'seamless' }] },
    { key: 'overhaul', name: 'Convergence', kind: 'overhaul', enabled: true, loaded: true, target: null, files: [{ path: 'C:\\o\\setup.toml', how: 'overhaul', exists: true, kind: 'text' }] },
  ],
};

function setup(answers: Record<string, unknown> = {}) {
  const t = fakeTransport({ state: 'ready', epoch: 1 });
  const base = t.call.bind(t);
  t.call = (async (op: string, params?: Record<string, unknown>, o?: { epoch?: number }) => {
    await base(op, params, o);
    const a = op === 'mod_configs' ? PAGE : answers[op];
    if (a instanceof Error) throw a;
    return a;
  }) as typeof t.call;
  return { t, api: createGatewayApi(createGateway(t)) };
}
const sent = (t: ReturnType<typeof setup>['t'], op: string) => t.calls.filter((c) => c.operation === op).map((c) => c.params);

describe('Mod Configs adapter', () => {
  it('lists the files the engine finds, by path, grouped under their mod', async () => {
    const { t, api } = setup();
    const list = await api.listConfigFiles(ME3);
    expect(sent(t, 'mod_configs')).toEqual([{ profile: ME3 }]);
    expect(list.map((f) => f.id)).toEqual([INI, 'C:\\mods\\Cool\\extra.ini', 'C:\\sc\\ersc_settings.ini', 'setup:C:\\o\\setup.toml']);
    expect(list[0]).toEqual({ id: INI, modId: DLL, modName: 'Cool', name: 'cool.ini', viaFile: 'cool.dll' });
    expect(list[2]).toMatchObject({ modId: 'seamless', modName: 'ersc.dll' });
    expect(list[3]).toMatchObject({ isSetup: true, name: 'setup.toml' });
  });

  it('opens a file as a form plus its text', async () => {
    const text = '[A]\n; 0 = false, 1 = true\nx = 1\n';
    const { t, api } = setup({ mod_configs_open: { path: INI, text, encoding: 'utf-8', crlf: false, sha: 'S1', stamp: [1, 2] } });
    const f = await api.getConfigFile(ME3, INI);
    expect(sent(t, 'mod_configs_open')).toEqual([{ profile: ME3, path: INI }]);
    expect(f).toMatchObject({ id: INI, path: INI, format: 'ini', modName: 'Cool', text });
    expect(f.sections![0]!.fields[0]).toMatchObject({ key: 'x', type: 'bool', value: true });
    await expect(api.getConfigFile(ME3, 'C:\\nope.ini')).rejects.toMatchObject({ code: 'not_found' });
  });

  it("saves edited values against the sha it read, in the file's own spelling, with no activity entry", async () => {
    const { t, api } = setup({
      mod_configs_open: { path: INI, text: '[A]\n; 0 = false, 1 = true\nx = 1\n[B.c]\ny = 3\n', encoding: 'utf-8', crlf: false, sha: 'S1', stamp: null },
      mod_configs_save: { name: 'cool.ini', saved: 2 },
    });
    await api.getConfigFile(ME3, INI);
    const r = await api.saveConfigFile(ME3, INI, { values: { 'A.x': false, 'B.c.y': 4 } });
    expect(sent(t, 'mod_configs_save')).toEqual([{ profile: ME3, path: INI, expect: 'S1', kind: 'values', edits: [{ section: 'A', key: 'x', value: '0' }, { section: 'B.c', key: 'y', value: '4' }] }]);
    expect(r).toEqual({ message: 'Saved cool.ini' });
    expect(r.entry).toBeUndefined();
  });

  it('saves text, and uses the Seamless kind for the Seamless file', async () => {
    const id = 'C:\\sc\\ersc_settings.ini';
    const { t, api } = setup({
      mod_configs_open: { path: id, text: '[GAMEPLAY]\ncooppassword = a\n', encoding: 'utf-8', crlf: false, sha: 'S9', stamp: null },
      mod_configs_save: { name: 'ersc_settings.ini', saved: 1, missing: ['nope'] },
    });
    await api.getConfigFile(ME3, id);
    const r = await api.saveConfigFile(ME3, id, { values: { 'GAMEPLAY.cooppassword': 'b' } });
    expect(sent(t, 'mod_configs_save')[0]).toMatchObject({ kind: 'seamless', expect: 'S9', edits: [{ section: 'GAMEPLAY', key: 'cooppassword', value: 'b' }] });
    expect(r.detail).toBe('Not in the file, so not written: nope');
    await api.getConfigFile(ME3, id);
    await api.saveConfigFile(ME3, id, { text: 'raw' });
    expect(sent(t, 'mod_configs_save')[1]).toMatchObject({ kind: 'text', text: 'raw', expect: 'S9' });
  });

  it("passes a stale save through as the engine's own error, and refuses a save with no read before it", async () => {
    const { api } = setup({
      mod_configs_open: { path: INI, text: 'x = 1\n', encoding: 'utf-8', crlf: false, sha: 'S1', stamp: null },
      mod_configs_save: new GatewayError({ code: 'stale', message: 'cool.ini changed on disk since it was read.' }),
    });
    await expect(api.saveConfigFile(ME3, INI, { text: 'x' })).rejects.toMatchObject({ code: 'stale' });
    await api.getConfigFile(ME3, INI);
    await expect(api.saveConfigFile(ME3, INI, { text: 'x' })).rejects.toMatchObject({ code: 'stale', message: 'cool.ini changed on disk since it was read.' });
  });

  it("attaches and detaches by the mod's target and the file's path", async () => {
    const { t, api } = setup({ mod_configs_attach: { ok: true }, mod_configs_detach: { ok: true } });
    const a = await api.attachConfig(ME3, DLL, ['extra.ini']);
    expect(sent(t, 'mod_configs_attach')).toEqual([{ profile: ME3, target: DLL, file: 'C:\\mods\\Cool\\extra.ini' }]);
    expect(a).toEqual({ message: 'extra.ini attached to Cool', detail: 'Edit it on Mod Configs.' });
    const d = await api.detachConfig(ME3, DLL, 'cool.ini');
    expect(sent(t, 'mod_configs_detach')).toEqual([{ profile: ME3, target: DLL, file: INI }]);
    expect(d.entry).toBeUndefined();
    await expect(api.detachConfig(ME3, 'C:\\other.dll', 'cool.ini')).rejects.toMatchObject({ code: 'not_found' });
    await expect(api.attachConfig(ME3, DLL, ['browsed.ini'])).rejects.toMatchObject({ code: 'not_found' });
  });

  it('lists what sits beside a mod without being attached', async () => {
    const { api } = setup();
    expect(await api.listAttachableConfigs(ME3, DLL)).toEqual(['extra.ini']);
    expect(await api.listAttachableConfigs(ME3, 'C:\\other.dll')).toEqual([]);
  });
});
